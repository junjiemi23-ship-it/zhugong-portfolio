"""
Harness Smart Router - 无密钥冒烟测试
mock provider 调用，验证路由逻辑不依赖真实 API。
"""

import sys
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, ".")

import httpx

from router.route_candidates import ROUTE_CANDIDATES, GLOBAL_FALLBACK, Candidate, detect_task_type
from router.context_gate import estimate_tokens, select_candidate
from router.provider_client import HardBlockedProviderError, enforce_red_lines, sanitize_messages
from router.resilience import ProviderHealth, classify_status, classify_exception


class TestCandidates(unittest.TestCase):
    """候选链完整性"""

    def test_all_routes_have_candidates(self):
        for task_type, chain in ROUTE_CANDIDATES.items():
            self.assertGreater(len(chain), 0, f"{task_type} 候选链为空")

    def test_all_free(self):
        for task_type, chain in ROUTE_CANDIDATES.items():
            for c in chain:
                self.assertTrue(c.is_free, f"{task_type} 链含付费模型: {c.model}")

    def test_no_openrouter(self):
        for task_type, chain in ROUTE_CANDIDATES.items():
            for c in chain:
                self.assertNotEqual(c.provider, "openrouter", "OpenRouter 红线违规")

    def test_fallback_chain_ready(self):
        self.assertGreaterEqual(len(GLOBAL_FALLBACK), 3)

    def test_no_paid_bai_pro_in_any_chain(self):
        """基线改进3：B.AI 付费 deepseek-v4-pro 不应出现在任何链"""
        for task_type, chain in ROUTE_CANDIDATES.items():
            for c in chain:
                self.assertFalse(
                    c.provider == "bai" and c.model == "deepseek-v4-pro",
                    f"{task_type} 链含付费风险腿 bai/deepseek-v4-pro"
                )

    def test_no_dead_local_mimo_in_chains(self):
        """基线改进5：本地 mimo-v2.5（未运行）不应出现在任何链"""
        for task_type, chain in ROUTE_CANDIDATES.items():
            for c in chain:
                self.assertFalse(
                    c.provider == "local" and c.model == "mimo-v2.5",
                    f"{task_type} 链含不可用腿 local/mimo-v2.5"
                )

    def test_chinese_chain_first_leg_is_kimi(self):
        """2026-08-29: chinese_content 首腿应为 NVIDIA 免费 Kimi K3(Moonshot 中文旗舰, 1M ctx)"""
        chain = ROUTE_CANDIDATES["chinese_content"]
        self.assertEqual(chain[0].model, "moonshotai/kimi-k3")
        self.assertEqual(chain[0].provider, "nvidia")
        self.assertEqual(chain[1].model, "deepseek-v4-flash")
        self.assertEqual(chain[1].provider, "bai")

    def test_coding_chain_exists_and_strong(self):
        """基线改进1：coding 链存在且首选强模型(NVIDIA Kimi K3)"""
        chain = ROUTE_CANDIDATES["coding"]
        self.assertEqual(chain[0].provider, "nvidia")
        self.assertEqual(chain[0].model, "moonshotai/kimi-k3")
        # 2026-08-29 更新: pro-0813 / nemotron 由动态优先级自动管理(低负载恢复/上游503),
        # 允许作为末位兜底回归, 但不得占据首选位(强推理首选仍是 kimi-k3)
        self.assertNotEqual(chain[0].model, "deepseek-ai/deepseek-v4-pro-0813")
        self.assertNotEqual(chain[0].model, "nvidia/nemotron-3-ultra-550b-a55b")


class TestContextGate(unittest.TestCase):
    """上下文门控"""

    def test_estimate_tokens_english(self):
        # 英文 ~4 chars/token
        self.assertGreater(estimate_tokens("a" * 400), 80)

    def test_estimate_tokens_chinese(self):
        # 中文 ~1.5 chars/token
        self.assertGreater(estimate_tokens("测" * 150), 90)

    def test_small_context_keeps_all(self):
        chain = ROUTE_CANDIDATES["navigation_basic"]
        self.assertEqual(len(select_candidate(chain, 100)), len(chain))

    def test_large_context_filters_small_models(self):
        chain = ROUTE_CANDIDATES["navigation_basic"]
        filtered = select_candidate(chain, 200_000)
        for c in filtered:
            self.assertGreaterEqual(c.context_limit, 200_000)

    def test_all_filtered_falls_back_to_largest(self):
        chain = [Candidate("bai", "tiny", "Tiny", 8_000)]
        filtered = select_candidate(chain, 100_000)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].model, "tiny")


class TestTaskDetection(unittest.TestCase):
    """任务类型检测"""

    def test_vision_priority(self):
        self.assertEqual(detect_task_type("capture screenshot of the page"), "vision")

    def test_long_running_by_tool_rounds(self):
        self.assertEqual(detect_task_type("do the thing", tool_calls_count=10), "long_running")

    def test_chinese_content(self):
        self.assertEqual(detect_task_type("这是一段纯粹的中文描述内容没有英文"), "chinese_content")

    def test_extraction(self):
        self.assertEqual(detect_task_type("extract the table into json"), "complex_extraction")

    def test_default_navigation(self):
        self.assertEqual(detect_task_type("open example.com"), "navigation_basic")

    def test_coding_detection(self):
        """基线样本：纯代码任务应进 coding 而非 navigation_basic"""
        self.assertEqual(
            detect_task_type("Write python code to sort a list of dicts by a key, explain complexity"),
            "coding",
        )

    def test_analyze_no_longer_triggers_vision(self):
        """基线样本：analyze 误触发 vision 应修复为 coding"""
        self.assertEqual(
            detect_task_type("Implement a recursive descent parser and analyze worst-case"),
            "coding",
        )

    def test_json_alone_no_longer_triggers_extraction(self):
        """基线样本：json 关键词撞车应修复，简单任务落 fast_worker"""
        self.assertEqual(detect_task_type("simple json cleanup task"), "fast_worker")

    def test_analyze_screenshot_still_vision(self):
        self.assertEqual(detect_task_type("analyze this screenshot ... visual layout"), "vision")

    def test_debug_error_is_coding(self):
        self.assertEqual(detect_task_type("debug this traceback: TypeError ..."), "coding")


class TestMultimodalDetection(unittest.TestCase):
    """带图请求强制 vision（能力校验）"""

    def _payload_with_image(self):
        return {
            "messages": [
                {"role": "user", "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
                ]},
            ]
        }

    def test_has_images(self):
        from router.harness_router import _has_images
        self.assertTrue(_has_images(self._payload_with_image()))

    def test_no_images(self):
        from router.harness_router import _has_images
        self.assertFalse(_has_images({"messages": [{"role": "user", "content": "hello"}]}))

    def test_image_payload_routes_to_vision_capable_only(self):
        """带图请求过滤掉非视觉模型：文本任务链里混入图片时应换成 vision 链"""
        from router.harness_router import route_request, ROUTE_CANDIDATES
        payload = self._payload_with_image()
        chain = ROUTE_CANDIDATES["vision"]
        vision_capable = [c for c in chain if c.vision_capable]
        self.assertTrue(all(c.vision_capable for c in vision_capable))


class TestErrorClassification(unittest.TestCase):
    """错误分类（对齐 opencode 错误分类速查）"""

    def test_status_mapping(self):
        self.assertEqual(classify_status(401), "auth")
        self.assertEqual(classify_status(403), "forbidden")
        self.assertEqual(classify_status(404), "not_found")
        self.assertEqual(classify_status(429), "rate_limited")
        self.assertEqual(classify_status(500), "server")
        self.assertEqual(classify_status(503), "server")
        self.assertEqual(classify_status(400), "client")

    def test_http_error_classification(self):
        req = httpx.Request("POST", "https://x")
        resp = httpx.Response(429, request=req)
        err = httpx.HTTPStatusError("429", request=req, response=resp)
        category, status = classify_exception(err)
        self.assertEqual(category, "rate_limited")
        self.assertEqual(status, 429)

    def test_timeout_classification(self):
        category, _ = classify_exception(httpx.ConnectTimeout("timeout"))
        self.assertEqual(category, "timeout")


class TestProviderHealth(unittest.TestCase):
    """Provider 熔断冷却"""

    def test_cooldown_blocks_then_expires(self):
        h = ProviderHealth()
        h.record_failure("bai", "rate_limited", 429)
        self.assertTrue(h.is_cooling_down("bai"))
        self.assertGreater(h.remaining_seconds("bai"), 0)
        # 模拟冷却过期
        h._cooldown_until["bai"] = 0
        self.assertFalse(h.is_cooling_down("bai"))

    def test_success_clears_cooldown(self):
        h = ProviderHealth()
        h.record_failure("nvidia", "server", 500)
        self.assertTrue(h.is_cooling_down("nvidia"))
        h.record_success("nvidia")
        self.assertFalse(h.is_cooling_down("nvidia"))

    def test_auth_cooldown_longer_than_server(self):
        h = ProviderHealth()
        h.record_failure("bai", "auth", 401)
        auth_remaining = h.remaining_seconds("bai")
        h.record_failure("nvidia", "server", 500)
        self.assertGreater(auth_remaining, h.remaining_seconds("nvidia"))

    def test_snapshot_shape(self):
        h = ProviderHealth()
        h.record_failure("bai", "rate_limited", 429)
        snap = h.snapshot()
        self.assertIn("bai", snap)
        self.assertEqual(snap["bai"]["last_error"], "rate_limited(429)")


class TestMessageSanitize(unittest.TestCase):
    """NVIDIA/Groq 消息结构清洗（基线第4节：孤立 tool 消息 400）"""

    def test_orphan_tool_message_dropped_for_nvidia(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "orphan result"},  # 无前置 assistant tool_calls
            {"role": "assistant", "content": "answer"},
        ]
        cleaned = sanitize_messages("nvidia", msgs)
        self.assertEqual([m["role"] for m in cleaned], ["user", "assistant"])

    def test_valid_tool_flow_kept_for_nvidia(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "tool_calls": [{"id": "t1"}]},
            {"role": "tool", "content": "result", "tool_call_id": "t1"},
        ]
        cleaned = sanitize_messages("nvidia", msgs)
        self.assertEqual(len(cleaned), 3)

    def test_bai_untouched(self):
        msgs = [{"role": "user", "content": "hi"}, {"role": "tool", "content": "x"}]
        cleaned = sanitize_messages("bai", msgs)
        self.assertEqual(len(cleaned), 2)


class TestRouteRequestRetry(unittest.IsolatedAsyncioTestCase):
    """route_request 错误分类驱动切换（mock 上游）"""

    def setUp(self):
        # 隔离进程级单例状态：清空速度表，让排序退化为"保序"（无数据不动顺序）
        from router.resilience import model_speed
        model_speed._ema_ms.clear()
        model_speed._last_seen.clear()
        model_speed._failed_at.clear()

    async def test_429_switches_leg_and_cooldowns_provider(self):
        """429 → 冷却该 provider 并换下一候选，绝不立即重试"""
        from router import harness_router as hr

        ok_result = {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        calls = []

        async def fake_call(candidate, payload, timeout=60.0):
            calls.append((candidate.provider, candidate.model))
            # chinese_content 链首腿现在是 kimi-k3(nvidia)
            if candidate.provider == "nvidia" and candidate.model == "moonshotai/kimi-k3":
                req = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
                resp = httpx.Response(429, request=req)
                raise httpx.HTTPStatusError("429", request=req, response=resp)
            return ok_result

        payload = {"messages": [{"role": "user", "content": "这是一段中文内容测试路由回退"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            result = await hr.route_request(payload)
            # 断言在 patch 上下文内：kimi-k3 429 后 nvidia 进入冷却，切到下一腿 deepseek-v4-flash(bai)
            self.assertEqual(result, ok_result)
            self.assertEqual(calls[0], ("nvidia", "moonshotai/kimi-k3"))
            self.assertEqual(calls[1], ("bai", "deepseek-v4-flash"))
            self.assertTrue(hr.provider_health.is_cooling_down("nvidia"))
        hr.provider_health.record_success("nvidia")  # 清理

    async def test_500_retries_same_candidate_once_then_switches(self):
        """5xx → 同候选退避重试一次，仍失败换 provider"""
        from router import harness_router as hr

        ok_result = {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        calls = []

        async def fake_call(candidate, payload, timeout=60.0):
            calls.append(candidate.model)
            # chinese_content 链首腿现在是 kimi-k3; 模拟 500 看它重试后切到 deepseek-v4-flash
            if candidate.model == "moonshotai/kimi-k3":
                req = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
                resp = httpx.Response(500, request=req)
                raise httpx.HTTPStatusError("500", request=req, response=resp)
            return ok_result

        payload = {"messages": [{"role": "user", "content": "这是一段中文内容测试5xx重试"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr, "SERVER_RETRY_BACKOFF", 0.01), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            result = await hr.route_request(payload)

        self.assertEqual(result, ok_result)
        # kimi-k3 尝试两次（重试一次），然后换 deepseek-v4-flash
        self.assertEqual(calls[:2], ["moonshotai/kimi-k3", "moonshotai/kimi-k3"])
        self.assertEqual(calls[2], "deepseek-v4-flash")
        hr.provider_health.record_success("nvidia")

    async def test_404_skips_without_retry(self):
        """404 → 不重试直接换腿"""
        from router import harness_router as hr

        ok_result = {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        calls = []

        async def fake_call(candidate, payload, timeout=60.0):
            calls.append(candidate.model)
            # chinese_content 链首腿现在是 kimi-k3; 404 不重试直接换 deepseek-v4-flash
            if candidate.model == "moonshotai/kimi-k3":
                req = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
                resp = httpx.Response(404, request=req)
                raise httpx.HTTPStatusError("404", request=req, response=resp)
            return ok_result

        payload = {"messages": [{"role": "user", "content": "这是一段中文内容测试404换腿"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            result = await hr.route_request(payload)

        self.assertEqual(result, ok_result)
        self.assertEqual(calls, ["moonshotai/kimi-k3", "deepseek-v4-flash"])
        hr.provider_health.record_success("bai")


class TestQualityTierOrdering(unittest.TestCase):
    """质量分层排序（用户理念 2026-08-29）：
    性能强且稳定(tier1) > 性能强但不稳定(tier2) > 性能一般但稳定(tier3)。
    tier 是排序主键，速度只在同层内竞争；tier2 的不稳定由自动换腿兜底。"""

    def setUp(self):
        from router.resilience import model_speed
        model_speed._ema_ms.clear()
        model_speed._last_seen.clear()
        model_speed._failed_at.clear()

    def tearDown(self):
        self.setUp()

    def test_tier_values_assigned(self):
        """kimi-k3 独占 tier1；pro-0813/nemotron 为 tier2；flash/qwen/minimax/glm 为 tier3"""
        seen = {}
        for chain in list(ROUTE_CANDIDATES.values()) + [GLOBAL_FALLBACK]:
            for c in chain:
                seen[c.model] = c.quality_tier
        self.assertEqual(seen["moonshotai/kimi-k3"], 1)
        self.assertEqual(seen["deepseek-ai/deepseek-v4-pro-0813"], 2)
        self.assertEqual(seen["nvidia/nemotron-3-ultra-550b-a55b"], 2)
        for m in ("deepseek-v4-flash", "qwen3.8-flash", "glm-5.3-flash",
                  "minimaxai/minimax-m3", "deepseek-ai/deepseek-v4-flash-0731"):
            self.assertEqual(seen[m], 3, f"{m} 应为 tier3")

    def test_strong_models_beat_fast_weak_models(self):
        """即使 pro-0813 慢(31s)、flash 快(1.7s)，tier2 仍排在 tier3 之前（质量优先于速度）"""
        from router.resilience import model_speed
        from router.harness_router import _reorder_by_speed
        chain = ROUTE_CANDIDATES["coding"]
        for c in chain:
            if "pro-0813" in c.model or "nemotron" in c.model:
                model_speed.record_success(c, 31000)   # 慢
            else:
                model_speed.record_success(c, 1700)    # flash 系快
        ordered = _reorder_by_speed(chain)
        pos = {c.model: i for i, c in enumerate(ordered)}
        # kimi(t1) 第一
        self.assertEqual(ordered[0].model, "moonshotai/kimi-k3")
        # pro-0813(t2) 排在所有 tier3 之前，尽管它慢 18 倍
        tier3_models = [c.model for c in chain if c.quality_tier == 3]
        for t3 in tier3_models:
            self.assertLess(pos["deepseek-ai/deepseek-v4-pro-0813"], pos[t3],
                            f"pro-0813(t2) 应排在 {t3}(t3) 之前，即使更慢")

    def test_unavailable_strong_model_sinks(self):
        """tier2 模型最近失败(不可用) → 沉底，由 tier3 稳定腿兜底（自动切换弥补不稳定）"""
        from router.resilience import model_speed
        from router.harness_router import _reorder_by_speed
        chain = ROUTE_CANDIDATES["long_running"]
        for c in chain:
            model_speed.record_success(c, 2000)
        pro = [c for c in chain if "pro-0813" in c.model][0]
        model_speed.record_failure(pro)
        ordered = _reorder_by_speed(chain)
        # 不可用的 pro-0813 沉到最后
        self.assertIs(ordered[-1], pro)
        # 可用的 kimi 仍在第一
        self.assertEqual(ordered[0].model, "moonshotai/kimi-k3")

    def test_short_task_chains_have_no_strong_models(self):
        """短任务链(navigation/fast/vision)不含 tier1/2，避免强模型拖慢高频短指令"""
        for tt in ("navigation_basic", "fast_worker", "vision"):
            for c in ROUTE_CANDIDATES[tt]:
                self.assertEqual(c.quality_tier, 3,
                                 f"{tt} 链不应含 tier<3 模型（{c.model} tier={c.quality_tier}）")


class TestRedLines(unittest.TestCase):
    """红线拦截"""

    def test_openrouter_blocked(self):
        c = Candidate("openrouter", "any-model", "Any", 128_000)
        with self.assertRaises(HardBlockedProviderError):
            enforce_red_lines(c)

    def test_deepseek_paid_blocked_without_env(self):
        c = Candidate("deepseek", "deepseek-v4-pro", "DS Paid", 128_000)
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HardBlockedProviderError):
                enforce_red_lines(c)

    def test_deepseek_paid_allowed_with_env(self):
        c = Candidate("deepseek", "deepseek-v4-pro", "DS Paid", 128_000)
        with patch.dict("os.environ", {"ALLOW_DEEPSEEK_PAID": "1"}):
            try:
                enforce_red_lines(c)  # 不应抛异常
            except HardBlockedProviderError:
                self.fail("显式授权后不应拦截")


class TestKeyPoolRotation(unittest.TestCase):
    """多 key 轮换（2026-08-29 三智能体统一接入后 BAI 双账号分摊）"""

    def setUp(self):
        from router import provider_client as pc
        pc._key_cooldown.clear()
        pc._key_rr_index.clear()

    def test_bai_pool_has_two_keys(self):
        from router import provider_client as pc
        with patch.dict("os.environ", {"BAI_API_KEY": "k1", "BAI_API_KEY_2": "k2"}):
            keys = pc.get_api_keys("bai")
            self.assertEqual(len(keys), 2)
            self.assertEqual(set(keys), {"BAI_API_KEY", "BAI_API_KEY_2"})

    def test_round_robin_spreads_traffic(self):
        from router import provider_client as pc
        with patch.dict("os.environ", {"BAI_API_KEY": "k1", "BAI_API_KEY_2": "k2"}):
            first = pc.get_api_keys("bai")[0]
            second = pc.get_api_keys("bai")[0]
            self.assertNotEqual(first, second, "连续两次调用应优先不同 key")

    def test_cooled_key_skipped(self):
        from router import provider_client as pc
        with patch.dict("os.environ", {"BAI_API_KEY": "k1", "BAI_API_KEY_2": "k2"}):
            pc.mark_key_cooling("BAI_API_KEY", 300)
            keys = pc.get_api_keys("bai")
            self.assertEqual(keys, ["BAI_API_KEY_2"])

    def test_all_cooled_fallback_returns_all(self):
        from router import provider_client as pc
        with patch.dict("os.environ", {"BAI_API_KEY": "k1", "BAI_API_KEY_2": "k2"}):
            pc.mark_key_cooling("BAI_API_KEY", 300)
            pc.mark_key_cooling("BAI_API_KEY_2", 300)
            keys = pc.get_api_keys("bai")
            self.assertEqual(len(keys), 2, "全冷却时兜底返回全部，绝不空转")

    def test_missing_all_keys_raises(self):
        from router import provider_client as pc
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(pc.MissingAPIKeyError):
                pc.get_api_keys("bai")

    def test_call_provider_rotates_on_429(self):
        """第一把 key 429 → 冷却它 → 第二把 key 成功返回"""
        from router import provider_client as pc

        ok = httpx.Response(200, json={"choices": []}, request=httpx.Request("POST", "https://x"))
        rate = httpx.Response(429, request=httpx.Request("POST", "https://x"))
        seen_headers = []

        class FakeClient:
            def post(self, url, json=None, headers=None, timeout=None):
                seen_headers.append(headers["Authorization"])
                if len(seen_headers) == 1:
                    raise httpx.HTTPStatusError("429", request=headers and httpx.Request("POST", url), response=rate)
                return ok

        c = Candidate("bai", "glm-5.3-flash", "GLM", 128_000)
        with patch.dict("os.environ", {"BAI_API_KEY": "k1", "BAI_API_KEY_2": "k2"}), \
             patch.object(pc, "_get_http_client", return_value=FakeClient()):
            result = pc.call_provider(c, {"messages": []})
        self.assertEqual(result, {"choices": []})
        self.assertEqual(len(seen_headers), 2, "应换第二把 key 重试")
        self.assertTrue(pc.key_cooldown_remaining("BAI_API_KEY") > 0, "429 的 key 应进冷却")

    def test_all_keys_failed_with_429_classifies_rate_limited(self):
        """回归(2026-08-29)：key 池撞 429 曾被误报成 auth（凭证异常），
        且绕过了 provider 侧 429 指数退避。现应按底层真实状态码分类。"""
        from router import provider_client as pc
        rate = httpx.Response(429, request=httpx.Request("POST", "https://x"))
        inner = httpx.HTTPStatusError("429", request=rate.request, response=rate)
        cat, status = classify_exception(pc.AllKeysFailedError("nvidia", inner))
        self.assertEqual(cat, "rate_limited")
        self.assertEqual(status, 429, "health 里要能看到真实状态码，不再只显示裸 auth")

    def test_all_keys_failed_with_401_still_classifies_auth(self):
        """真凭证失效仍归 auth —— 修复不能把 401 也降级成限流。"""
        from router import provider_client as pc
        un = httpx.Response(401, request=httpx.Request("POST", "https://x"))
        inner = httpx.HTTPStatusError("401", request=un.request, response=un)
        cat, status = classify_exception(pc.AllKeysFailedError("nvidia", inner))
        self.assertEqual(cat, "auth")
        self.assertEqual(status, 401)

    def test_all_keys_failed_without_inner_is_auth(self):
        from router import provider_client as pc
        cat, status = classify_exception(pc.AllKeysFailedError("bai", None))
        self.assertEqual(cat, "auth")
        self.assertIsNone(status)

    def test_missing_api_key_classifies_auth(self):
        """凭据缺失与限流是两回事：缺 key 归 auth，换模型无用。"""
        from router import provider_client as pc
        cat, _ = classify_exception(pc.MissingAPIKeyError("bai"))
        self.assertEqual(cat, "auth")

    def test_keypool_429_drives_exponential_backoff(self):
        """误分类的实际代价：归 auth 时 _consecutive_429 被清空，指数退避永不生效。
        修复后连续两次 key 池 429 应让冷却从 180s 翻倍到 360s。"""
        from router import provider_client as pc
        health = ProviderHealth()
        rate = httpx.Response(429, request=httpx.Request("POST", "https://x"))
        wrapped = pc.AllKeysFailedError(
            "nvidia", httpx.HTTPStatusError("429", request=rate.request, response=rate)
        )
        for expected in (180.0, 360.0):
            cat, status = classify_exception(wrapped)
            health.record_failure("nvidia", cat, status)
            self.assertAlmostEqual(
                health.remaining_seconds("nvidia"), expected, delta=2.0,
                msg=f"第 {int(expected/180)} 次 429 冷却应为 {expected:.0f}s",
            )

    def test_nvidia_single_key(self):
        """NVIDIA 同账号双 key 无轮换收益 → 池内只有主 key"""
        from router import provider_client as pc
        with patch.dict("os.environ", {"NVIDIA_API_KEY": "n1"}):
            keys = pc.get_api_keys("nvidia")
            self.assertEqual(keys, ["NVIDIA_API_KEY"])


class TestRouteStats(unittest.IsolatedAsyncioTestCase):
    """观测性统计（2026-08-29）：口径、环形上限、异常隔离、换腿推导"""

    def setUp(self):
        from router.stats import RouteStats
        from router import harness_router as hr
        self.stats = RouteStats()
        self._orig = hr.route_stats
        hr.route_stats = self.stats
        # 隔离速度表，让链排序退化为保序
        from router.resilience import model_speed
        model_speed._ema_ms.clear()
        model_speed._last_seen.clear()
        model_speed._failed_at.clear()

    def tearDown(self):
        from router import harness_router as hr
        hr.route_stats = self._orig

    async def test_ok_first_leg_and_switch_derivation(self):
        """首腿 429 → 换腿成功：requests 计数 + switches 历史 + legs 分布"""
        from router import harness_router as hr
        ok_result = {"id": "x", "choices": [{"message": {"content": "ok"}}]}

        async def fake_call(candidate, payload, timeout=60.0):
            if candidate.provider == "nvidia" and candidate.model == "moonshotai/kimi-k3":
                req = httpx.Request("POST", "https://x")
                resp = httpx.Response(429, request=req)
                raise httpx.HTTPStatusError("429", request=req, response=resp)
            return ok_result

        payload = {"messages": [{"role": "user", "content": "这是一段中文内容测试路由回退"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            await hr.route_request(payload)

        snap = self.stats.snapshot()
        self.assertEqual(snap["requests"]["routed_total"], 1)
        self.assertEqual(snap["requests"]["ok_after_switch"], 1)
        self.assertEqual(snap["requests"]["ok_first_leg"], 0)
        self.assertEqual(snap["requests"]["failed_all"], 0)
        # 换腿事件：from kimi-k3 to 下一腿，reason 带真实状态码
        self.assertEqual(len(snap["switches"]), 1)
        sw = snap["switches"][0]
        self.assertEqual(sw["from"], "nvidia/moonshotai/kimi-k3")
        self.assertEqual(sw["reason"], "rate_limited(429)")
        # 每腿分布：失败腿有 rate_limited 计数，成功腿 successes=1
        self.assertEqual(
            snap["legs"]["nvidia/moonshotai/kimi-k3"]["failures_by_category"]["rate_limited"], 1)
        self.assertEqual(snap["legs"]["bai/deepseek-v4-flash"]["successes"], 1)

    async def test_all_failed_counts(self):
        """全链耗尽 → failed_all 计数，且不带 final_ms 污染 avg"""
        from router import harness_router as hr

        async def always_500(candidate, payload, timeout=60.0):
            req = httpx.Request("POST", "https://x")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("500", request=req, response=resp)

        payload = {"messages": [{"role": "user", "content": "hello simple task"}]}
        with patch.object(hr, "call_provider_async", side_effect=always_500), \
             patch.object(hr.provider_health, "_cooldown_until", {}), \
             patch.object(hr, "_sleep", new=lambda s: __import__("asyncio").sleep(0)):
            with self.assertRaises(Exception):  # HTTPException 502
                await hr.route_request(payload)

        snap = self.stats.snapshot()
        self.assertEqual(snap["requests"]["failed_all"], 1)
        for leg in snap["legs"].values():
            self.assertIsNone(leg["avg_ms"], "失败请求不应产生耗时样本")

    def test_ring_buffer_bounded(self):
        """换腿历史必须封顶 500 条（内存有界红线）"""
        path = [(f"p/m{i}", False, "rate_limited", 429) for i in range(600)]
        path.append(("p/final", True, None, None))
        self.stats.record_route("coding", path)
        snap = self.stats.snapshot(recent_switches=1000)
        self.assertLessEqual(len(self.stats._switches), 500)
        # 保留的是最新的换腿（deque appendleft + maxlen 丢最旧）：
        # 600 条失败腿推导出 600 次换腿，最后一条是 m599→final
        self.assertEqual(snap["switches"][0]["from"], "p/m599")
        self.assertEqual(snap["switches"][0]["to"], "p/final")

    def test_stats_never_raises_on_garbage(self):
        """异常隔离红线：喂垃圾数据不得抛出，路由不受影响"""
        self.stats.record_route("x", [("k", "not-a-bool", None, None)])  # 类型错误也不炸
        self.stats.record_route("x", [])  # 空 path
        self.stats.record_event("t", None)

    def test_snapshot_shape(self):
        self.stats.record_route("coding", [("bai/glm-5.3-flash", True, None, None)], final_ms=1234.0)
        snap = self.stats.snapshot()
        for key in ("window_seconds", "requests", "legs", "switches", "events"):
            self.assertIn(key, snap)
        self.assertEqual(snap["legs"]["bai/glm-5.3-flash"]["avg_ms"], 1234.0)


class TestNamedModelPin(unittest.IsolatedAsyncioTestCase):
    """指定模型名路由（opencode 客户端带具体 model id）"""

    def setUp(self):
        from router.resilience import model_speed
        model_speed._ema_ms.clear()
        model_speed._last_seen.clear()
        model_speed._failed_at.clear()

    async def test_named_model_pins_first_leg(self):
        from router import harness_router as hr
        tried = []

        async def fake_call(candidate, payload, timeout=60.0):
            tried.append(candidate.model)
            return {"id": "x", "choices": [{"message": {"content": "ok"}}]}

        # 普通文本请求 + 指定池内模型名 → 该模型排到链首（即使速度排序可能把它压后）
        payload = {"model": "minimaxai/minimax-m3",
                   "messages": [{"role": "user", "content": "hello world quick task"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            await hr.route_request(payload)
        self.assertEqual(tried[0], "minimaxai/minimax-m3", "命名模型应 pin 为首选腿")

    async def test_named_model_pin_survives_speed_reorder(self):
        """pinned 模型即使速度慢也应置顶（不被 _reorder_by_speed 压后）"""
        from router import harness_router as hr
        from router.resilience import model_speed
        # 给 minimax-m3 一个很慢的 EMA 记录，另一个模型很快
        model_speed.record_success(Candidate("bai", "qwen3.8-flash", "Q", 128_000), 100.0)
        model_speed.record_success(Candidate("nvidia", "minimaxai/minimax-m3", "M", 128_000), 50000.0)
        tried = []

        async def fake_call(candidate, payload, timeout=60.0):
            tried.append(candidate.model)
            return {"id": "x", "choices": [{"message": {"content": "ok"}}]}

        payload = {"model": "minimaxai/minimax-m3",
                   "messages": [{"role": "user", "content": "hello world quick task"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            await hr.route_request(payload)
        self.assertEqual(tried[0], "minimaxai/minimax-m3", "即使慢也应置顶")

    async def test_unknown_model_name_falls_back_to_auto(self):
        from router import harness_router as hr
        tried = []

        async def fake_call(candidate, payload, timeout=60.0):
            tried.append(candidate.model)
            return {"id": "x", "choices": [{"message": {"content": "ok"}}]}

        payload = {"model": "smto/some-nonexistent-model",
                   "messages": [{"role": "user", "content": "hello"}]}
        with patch.object(hr, "call_provider_async", side_effect=fake_call), \
             patch.object(hr.provider_health, "_cooldown_until", {}):
            await hr.route_request(payload)
        self.assertTrue(tried, "未知模型名应回退 auto 分类并成功路由")


if __name__ == "__main__":
    unittest.main(verbosity=2)
