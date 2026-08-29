"""
Harness Smart Router - 核心路由网关
FastAPI 应用，OpenAI 兼容协议，按任务类型分发到候选模型链。
"""

import json
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .route_candidates import ROUTE_CANDIDATES, Candidate, detect_task_type, TaskType
from .context_gate import estimate_tokens, select_candidate
from .fallback_chain import GLOBAL_FALLBACK
from .provider_client import call_provider_async, HardBlockedProviderError
from .health import health_check
from .resilience import (
    classify_exception,
    provider_health,
    model_speed,
    SERVER_RETRY_BACKOFF,
)
from .stats import route_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("harness_router")

app = FastAPI(title="Harness Smart Model Router", version="1.1.0")


def _extract_text(payload: dict[str, Any]) -> str:
    return " ".join(
        m.get("content", "") if isinstance(m.get("content"), str) else ""
        for m in payload.get("messages", [])
    )


def _current_user_text(payload: dict[str, Any]) -> str:
    """抽取「最后一条 user 消息」的文本，用于任务分类。

    与 _has_images() 的思路对齐：分类只看当前这一轮，避免历史里某条消息
    含触发词（如"识别图片/截图/图像分析"）污染后续所有请求的分类结果，
    把普通编码/中文请求误判进慢的 vision 链。
    带图请求由 _has_images() 在网关层强制走 vision，不依赖此文本。
    """
    messages = payload.get("messages", [])
    for m in reversed(messages):
        if m.get("role") in ("user",):
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # 多模态:只取 text 类型 part
                parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                return " ".join(parts)
            return ""
    return ""


def _has_images(payload: dict[str, Any]) -> bool:
    """检测「当前这一轮」是否带图（只看最后一条 user 消息），避免历史截图误触发 vision 链。

    浏览器 harness 常把上一步的截图留在消息历史里；若扫全历史会把后续纯文本/纯交互
    请求全部误判为视觉任务，拖慢每跳。因此只检查最后一条 user 消息的 content。
    """
    messages = payload.get("messages", [])
    for m in reversed(messages):
        role = m.get("role")
        if role in ("user",):
            content = m.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in ("image_url", "image", "input_image"):
                        return True
            return False  # 最后一条 user 消息看完即可，不回溯更早历史
    return False


def _classify(payload: dict[str, Any]) -> TaskType:
    """从 OpenAI 请求体推断任务类型。

    只用「最后一条 user 消息」的文本做分类基准（_current_user_text），
    避免全历史拼接后，历史里某条含触发词的消息污染后续所有分类。
    tool_rounds 与 context_chars 仍按全历史统计（用于 long_running 判断）。
    """
    messages = payload.get("messages", [])
    text = _current_user_text(payload)
    tool_rounds = len([m for m in messages if m.get("role") == "tool"])
    context_chars = len(_extract_text(payload))
    return detect_task_type(text, tool_rounds, context_chars)


def _force_override(payload: dict[str, Any]) -> tuple[str, str] | None:
    """检查人工强制指令（请求体 metadata 或环境变量）"""
    meta = payload.get("metadata") or {}
    fp = meta.get("force_provider") or os.getenv("HARNESS_FORCE_PROVIDER")
    fm = meta.get("force_model") or os.getenv("HARNESS_FORCE_MODEL")
    if fp and fm:
        return (fp, fm)
    return None


async def _try_chain(chain: list[Candidate], payload: dict[str, Any], task_type: str = "unknown") -> dict[str, Any]:
    """
    错误分类驱动的候选链遍历（对齐 opencode 切换策略）：
    - 冷却中的 provider 直接跳过；若整链被冷却跳过则忽略冷却兜底重试一遍
    - 429/401/403/404/timeout/4xx → 冷却 provider 后换下一候选（429 绝不立即重试）
    - 5xx → 同候选退避重试一次，仍失败换 provider

    观测性（2026-08-29）：全程收集 path=[(腿键, ok, 类别, 状态码)]，
    结束时一次性交给 route_stats.record_route()。统计失败不影响路由。
    """
    attempted_any = False
    last_error: Exception | None = None
    path: list[tuple[str, bool, str | None, int | None]] = []
    t_chain = time.perf_counter()

    def _finish(ok: bool) -> None:
        try:
            ms = (time.perf_counter() - t_chain) * 1000
            route_stats.record_route(task_type, path, final_ms=ms if ok else None)
        except Exception:
            pass  # 统计永不影响路由

    for ignore_cooldown in (False, True):
        for candidate in chain:
            if not ignore_cooldown and provider_health.is_cooling_down(candidate.provider):
                logger.info(
                    f"[route] skip {candidate.provider}/{candidate.model} "
                    f"(cooldown {provider_health.remaining_seconds(candidate.provider)}s left)"
                )
                continue

            attempt = 0
            while attempt < 2:  # 仅 5xx 会在第 1 次失败后退避重试
                attempt += 1
                attempted_any = True
                t0 = time.perf_counter()
                leg_key = f"{candidate.provider}/{candidate.model}"
                try:
                    result = await call_provider_async(candidate, payload)
                    provider_health.record_success(candidate.provider)
                    model_speed.record_success(
                        candidate, (time.perf_counter() - t0) * 1000
                    )
                    logger.info(f"[route] success via {candidate.provider}/{candidate.model}")
                    path.append((leg_key, True, None, None))
                    _finish(ok=True)
                    return result
                except HardBlockedProviderError:
                    raise  # 红线不重试
                except Exception as e:
                    model_speed.record_failure(candidate)
                    category, status = classify_exception(e)
                    last_error = e
                    path.append((leg_key, False, category, status))
                    logger.warning(
                        f"[route] {candidate.provider}/{candidate.model} failed "
                        f"(category={category}, status={status}): {e}"
                    )
                    provider_health.record_failure(candidate.provider, category, status)
                    if category == "server" and attempt == 1:
                        await _sleep(SERVER_RETRY_BACKOFF)
                        continue  # 5xx 退避后重试一次
                    break  # 其余类别：换下一候选

        if attempted_any:
            break  # 第一遍有实际尝试就不再做忽略冷却的兜底遍历

    _finish(ok=False)
    raise HTTPException(status_code=502, detail=f"所有候选模型均失败: {last_error}")


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


def _reorder_by_speed(chain: list[Candidate], pinned_model: str | None = None) -> list[Candidate]:
    """动态优先级排序（2026-08-29 修订：质量分层优先）

    排序键 = 「可用性 → 质量层 quality_tier → EMA 实测耗时」：
    - 可用性最优先：不可用（最近失败未恢复）的模型沉底，但保留在链中待冷探测恢复
    - 质量层次之（用户理念）：tier1 顶尖且稳 > tier2 顶尖但不稳 > tier3 一般但稳
      —— 强模型排在一般模型之前，其不稳定性由「自动切换」兜底（route_request 逐腿重试）
    - EMA 速度最后：同层内快的排前（层内竞争）
    - 无速度记录的模型 ema=inf，但仍按 tier 参与排序（stable sort 保同层静态序）
    - pinned_model：显式指定模型时置顶（opencode 客户端带具体 model id 时的「人工优先」）
    """
    if not chain:
        return chain
    pin = pinned_model or ""
    return sorted(
        chain,
        key=lambda c: (
            c.model != pin,                # 指定的模型置顶（True 排后）
            not model_speed.is_available(c),   # False(可用) 排前
            c.quality_tier,                    # 1 顶尖且稳 → 2 顶尖但不稳 → 3 一般但稳
            model_speed.ema_ms(c),             # 同层内快的排前
        ),
    )


async def route_request(payload: dict[str, Any]) -> dict[str, Any]:
    """
    核心路由逻辑：
    1. 人工强制 → 直连指定模型
    2. 自动分类任务类型（带图请求强制 vision）→ 取候选链
    3. 能力校验（带图请求过滤非视觉模型）
    4. 上下文门控过滤
    5. 错误分类驱动依次尝试，失败按类别冷却/重试/换腿
    """
    # 1. 人工强制
    forced = _force_override(payload)
    if forced:
        fp, fm = forced
        candidate = Candidate(fp, fm, f"{fm} (forced)", context_limit=1_000_000)
        logger.info(f"[route] forced → {fp}/{fm}")
        t0 = time.perf_counter()
        try:
            result = await call_provider_async(candidate, payload)
            route_stats.record_route(
                "forced", [(f"{fp}/{fm}", True, None, None)],
                final_ms=(time.perf_counter() - t0) * 1000,
            )
            return result
        except Exception as e:
            category, status = classify_exception(e)
            route_stats.record_route("forced", [(f"{fp}/{fm}", False, category, status)])
            raise

    # 2. 任务分类（多模态强制 vision）
    has_images = _has_images(payload)
    task_type = "vision" if has_images else _classify(payload)
    chain = ROUTE_CANDIDATES.get(task_type, GLOBAL_FALLBACK)
    logger.info(f"[route] task_type={task_type}, chain_len={len(chain)}")

    # 2b. 指定模型名（opencode 等 OpenAI 兼容客户端常带具体 model id）：
    #     若该名字在本网关候选池内，pin 它为首选（保留原链其余腿作为后备）；
    #     名字不在池内 → 忽略并走 auto 分类。pool: provider/model 精确匹配（当前由 auto 分类统一管理）。
    req_model = str(payload.get("model") or "auto")
    if req_model not in ("auto", "") and req_model != "auto":
        named = [c for c in chain + GLOBAL_FALLBACK if c.model == req_model]
        if named:
            pinned = named[0]
            rest = [c for c in chain if c.model != req_model]
            chain = [pinned] + rest
            logger.info(f"[route] pin named model '{req_model}' → {pinned.provider}/{pinned.model}, rest={len(rest)}")
        else:
            logger.info(f"[route] model '{req_model}' 不在池内，忽略命名走 auto 分类")

    # 3. 能力校验：带图请求只允许视觉模型
    if has_images:
        vision_chain = [c for c in chain if c.vision_capable] or \
                       [c for c in GLOBAL_FALLBACK if c.vision_capable]
        if vision_chain:
            chain = vision_chain

    # 4. 上下文门控
    est_tokens = estimate_tokens(_extract_text(payload))
    chain = select_candidate(chain, est_tokens)
    if not chain:
        raise HTTPException(status_code=503, detail="候选链为空（上下文门控后无可用模型）")

    # 5. 动态优先级排序：可用性 → EMA 实测耗时（好模型恢复自动上位）。
    #    若本请求指定了池内模型（pin），保留其首选地位，不被速度重排压后。
    pinned_model = None
    if req_model not in ("auto", ""):
        pinned_model = req_model
    chain = _reorder_by_speed(chain, pinned_model=pinned_model)
    logger.info(f"[route] after speed reorder: {[c.model for c in chain]}")

    # 6. 依次尝试
    return await _try_chain(chain, payload, task_type=task_type)


def _sse_chunks(result: dict[str, Any]):
    """把非流式 completion 合成为 OpenAI 兼容 SSE 块（GUI 聊天走 stream:true）。"""
    cid = result.get("id", "chatcmpl-router")
    created = result.get("created", int(time.time()))
    model = result.get("model", "auto")

    def _chunk(delta: dict[str, Any], finish: str | None, index: int = 0) -> str:
        return "data: " + json.dumps({
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": index, "delta": delta, "finish_reason": finish}],
        }, ensure_ascii=False) + "\n\n"

    choices = result.get("choices") or [{}]
    for i, ch in enumerate(choices):
        msg = ch.get("message") or {}
        yield _chunk({"role": "assistant", "content": ""}, None, i)
        delta: dict[str, Any] = {}
        if msg.get("reasoning_content"):
            delta["reasoning_content"] = msg["reasoning_content"]
        if msg.get("content"):
            delta["content"] = msg["content"]
        if msg.get("tool_calls"):
            delta["tool_calls"] = [
                {**tc, "index": tc.get("index", j)}
                for j, tc in enumerate(msg["tool_calls"])
            ]
        if not delta:
            delta["content"] = ""
        yield _chunk(delta, None, i)
        yield _chunk({}, ch.get("finish_reason") or "stop", i)
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效 JSON")

    # 流式兼容：上游统一非流式调用，流式请求由网关合成 SSE
    wants_stream = bool(payload.get("stream"))
    if wants_stream:
        payload = {k: v for k, v in payload.items() if k not in ("stream", "stream_options")}

    try:
        result = await route_request(payload)
    except HardBlockedProviderError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[route] unexpected error")
        raise HTTPException(status_code=500, detail=str(e))

    if not wants_stream:
        return JSONResponse(content=result)
    return StreamingResponse(_sse_chunks(result), media_type="text/event-stream")


@app.get("/v1/models")
@app.get("/v1/models/auto")
@app.get("/models")
async def list_models():
    """OpenAI 兼容的模型列表端点。

    Hermes / browser-use 客户端在初始化时会枚举模型（/v1/models、/v1/models/auto 等），
    此前这些端点全部 404，导致客户端反复探测并可能触发回退/重试。这里返回网关路由
    支持的全部候选模型 id，消掉该噪音。
    """
    seen: dict[str, dict[str, Any]] = {}
    for chain in ROUTE_CANDIDATES.values():
        for c in chain:
            seen.setdefault(c.model, {
                "id": c.model,
                "object": "model",
                "owned_by": c.provider,
                "created": 0,
            })
    return {"object": "list", "data": list(seen.values())}


@app.get("/health")
async def health(probe: bool = False):
    return health_check(probe=probe)


@app.get("/health/stats")
@app.get("/stats")
async def health_stats(switches: int = 30, events: int = 10, format: str = "text"):
    """路由统计快照（自本进程启动以来，重启清零）。

    口径见 router/stats.py 模块文档。只读、无副作用；参数控制返回的
    换腿/事件历史条数（上限 500 = 环形缓冲容量）。

    - 默认返回人类可读文本（终端一眼看懂）
    - ?format=json 返回原始 JSON 数据
    """
    snap = route_stats.snapshot(
        recent_switches=max(1, min(switches, 500)),
        recent_events=max(1, min(events, 500)),
    )
    if format == "json":
        return snap
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(_format_stats_plain(snap))


def _fmt_time(ts) -> str:
    """Unix 时间戳 → HH:MM:SS（本地时间）；无效值原样返回。"""
    try:
        import datetime
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(ts)


_REASON_ZH = {
    "rate_limited": "限流429",
    "auth": "凭证问题",
    "timeout": "超时",
    "upstream_5xx": "上游故障",
    "model_not_found": "模型不存在",
    "client": "请求错误",
    "network": "网络错误",
    "unknown": "未知错误",
    "reprobe_recovered": "复探恢复",
}


def _fmt_reason(reason) -> str:
    """rate_limited(429) → 限流429；timeout → 超时。"""
    if not reason:
        return "?"
    base = str(reason).split("(")[0]
    return _REASON_ZH.get(base, str(reason))


def _format_stats_plain(snap: dict) -> str:
    """把 stats 快照转成人类可读的终端文本。"""
    req = snap.get("requests", {})
    total = req.get("routed_total", 0)
    ok1 = req.get("ok_first_leg", 0)
    ok2 = req.get("ok_after_switch", 0)
    fail = req.get("failed_all", 0)
    uptime = snap.get("window_seconds", 0)
    lines = []
    lines.append(f"路由统计 — 启动以来 {uptime}s")
    lines.append(f"  {total} 次请求 | 首腿成功 {ok1} 次 | 换腿后成功 {ok2} 次 | 全链耗尽 {fail} 次")
    lines.append("")

    # 每腿一览
    legs = snap.get("legs", {})
    if legs:
        lines.append("▸ 每腿统计")
        # 按失败数降序排，最差的在最上面
        sorted_legs = sorted(legs.items(), key=lambda kv: kv[1].get("failures", 0), reverse=True)
        for leg, s in sorted_legs:
            att = s.get("attempts", 0)
            suc = s.get("successes", 0)
            fai = s.get("failures", 0)
            avg = s.get("avg_ms")
            cat = s.get("failures_by_category", {})
            cat_str = ", ".join(f"{_fmt_reason(k)}={v}" for k, v in sorted(cat.items())) if cat else ""
            ms_str = f" | 均耗时 {avg:.0f}ms" if avg is not None else ""
            fail_str = f" | 失败 {fai} 次" if fai else ""
            cat_str = f" ({cat_str})" if cat_str else ""
            lines.append(f"    {leg:45s} 尝试 {att} 次 | 成功 {suc} 次{fail_str}{cat_str}{ms_str}")
        lines.append("")

    # 换腿历史
    switches = snap.get("switches", [])
    if switches:
        lines.append(f"▸ 最近 {len(switches)} 次换腿（新→旧）")
        for sw in switches:
            lines.append(
                f"    {_fmt_time(sw.get('t'))}  "
                f"{sw.get('from', '?')}  →  {sw.get('to', '?')}  "
                f"[{_fmt_reason(sw.get('reason'))}]"
            )
        lines.append("")

    # 事件
    events = snap.get("events", [])
    if events:
        lines.append(f"▸ 事件 ({len(events)} 条)")
        for ev in events:
            kind = _fmt_reason(ev.get("kind", "?"))
            detail = " | ".join(f"{k}={v}" for k, v in ev.items() if k not in ("t", "kind"))
            lines.append(f"    {_fmt_time(ev.get('t'))}  {kind}  {detail}")
        lines.append("")

    lines.append("提示：curl http://127.0.0.1:8124/stats?format=json  查看原始数据")
    return "\n".join(lines)


def main():
    import uvicorn
    port = int(os.getenv("HARNESS_ROUTER_PORT", "8124"))
    logger.info(f"启动 Harness Smart Router @ 127.0.0.1:{port}")

    # 启动探活(2026-08-29 接线)：后台对全链候选做一次轻量探测，
    # 失效/缺key/限流腿提前进入冷却，业务请求不再当第一个探针白撞死腿。
    def _startup_probe():
        import threading, time as _t

        def _run():
            _t.sleep(1.0)  # 等服务端口就绪
            try:
                from .health import health_check
                out = health_check(probe=True)
                probe_out = out.get("probe", {})
                results = probe_out.get("results", []) if isinstance(probe_out, dict) else []
                bad = [f"{r['provider']}:{r.get('error')}" for r in results if not r.get("ok")]
                logger.info(f"[startup-probe] done: {probe_out.get('probed', 0)} providers, bad={bad or 'none'}")
            except Exception as e:
                logger.warning(f"[startup-probe] failed (non-fatal): {e}")

        threading.Thread(target=_run, daemon=True).start()

    @app.on_event("startup")
    async def _on_startup():
        from .resilience import start_periodic_reprobe
        start_periodic_reprobe()  # 冷却 provider 的后台复探，恢复即提前解封
        _startup_probe()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()