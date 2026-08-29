"""
错误分类 + Provider 熔断冷却（对齐 opencode 错误分类速查机制）：

- 401 auth        → credential 问题，换模型无用 → 冷却该 provider 长窗口，直接换下一候选
- 403 forbidden   → 权限/额度策略 → 同上
- 404 not_found   → model id 或 baseURL 错 → 该候选必失败，冷却 provider，换下一候选
- 429 rate_limited→ 限流/配额 → 绝不立即重试，冷却该 provider 后换腿
                     （避免链内下一腿同 provider 再吃一次 429）
- 5xx server      → provider 上游故障 → 同候选退避重试一次，仍失败则换 provider
- timeout         → 网络/代理链路 → 冷却换腿
- 4xx client      → 请求与该模型不兼容（如消息结构）或上游瞬时故障 → 冷却 provider
                     120s 再换腿。2026-08-29 教训：b.ai 高峰期间歇性 400，原 10s
                     冷却导致「冷却到期→再撞 400」循环 26 分钟，Hermes 每轮全链
                     重试被拖爆。400 多为 provider 侧问题，短冷却等于反复撞墙。
"""

import logging
import os
import time
from typing import Any

logger = logging.getLogger("harness_router.resilience")

# 各错误类别对应的 provider 冷却秒数（可用环境变量 HARNESS_COOLDOWN_<大写类别> 覆盖）
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


CATEGORY_COOLDOWN_SECONDS: dict[str, float] = {
    # 429 默认 180s(2026-08-29): NVIDIA 持续限流期 30s 冷却导致"冷却到期→再撞429"循环,
    # 每次浪费 2-3s 等待失败。env HARNESS_COOLDOWN_RATE_LIMITED 仍可覆盖。
    "rate_limited": _env_float("HARNESS_COOLDOWN_RATE_LIMITED", 180.0),
    "server": _env_float("HARNESS_COOLDOWN_SERVER", 15.0),
    "timeout": _env_float("HARNESS_COOLDOWN_TIMEOUT", 20.0),
    "auth": _env_float("HARNESS_COOLDOWN_AUTH", 300.0),
    "forbidden": _env_float("HARNESS_COOLDOWN_FORBIDDEN", 300.0),
    "not_found": _env_float("HARNESS_COOLDOWN_NOT_FOUND", 300.0),
    "client": _env_float("HARNESS_COOLDOWN_CLIENT", 120.0),
    "unknown": _env_float("HARNESS_COOLDOWN_UNKNOWN", 10.0),
}

# 5xx 同候选退避重试间隔（opencode 约定：5xx 等待重试一次，仍失败才换 provider）
SERVER_RETRY_BACKOFF = 0.8


def classify_status(status: int) -> str:
    """HTTP 状态码 → 错误类别"""
    if status == 401:
        return "auth"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if 500 <= status < 600:
        return "server"
    if 400 <= status < 500:
        return "client"
    return "unknown"


def classify_exception(e: Exception) -> tuple[str, int | None]:
    """
    异常 → (错误类别, HTTP 状态码或 None)
    httpx.HTTPStatusError 带 .response.status_code；超时/连接类归入 timeout。
    MissingAPIKeyError(凭据缺失)归入 auth —— 长冷却，换模型无用只换 provider。
    AllKeysFailedError(池内全 key 失败)按底层真实状态码分类 —— 2026-08-29 修复：
    此前无条件归 auth，导致 key 池撞 429 被误报成凭证异常，且 provider 侧
    rate_limited 指数退避（_consecutive_429）被 auth 分支清空计数、形同虚设。
    """
    from .provider_client import MissingAPIKeyError, AllKeysFailedError

    if isinstance(e, MissingAPIKeyError):
        return "auth", None
    if isinstance(e, AllKeysFailedError):
        inner = getattr(e, "last_error", None)
        if inner is not None:
            return classify_exception(inner)  # 429→rate_limited / 401→auth / 403→forbidden
        return "auth", None  # 无底层异常可参照，保守按凭证处理
    status = getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(status, int):
        return classify_status(status), status
    try:
        import httpx
        if isinstance(e, (httpx.TimeoutException, httpx.TransportError)):
            return "timeout", None
    except ImportError:
        pass
    if isinstance(e, (TimeoutError, ConnectionError)):
        return "timeout", None
    return "unknown", None


class ProviderHealth:
    """
    内存态 provider 健康（熔断冷却）：
    - record_failure(provider, category)：按类别设置冷却窗口
    - record_success(provider)：清除冷却
    - is_cooling_down(provider)：冷却期内返回 True（路由层据此跳过该 provider 的候选）
    - 429 指数退避：同一 provider 连续 rate_limited 时冷却翻倍（180→360→720...，上限 30min），
      消除「固定 180s 到期 → 第一个请求再撞 429 → 又 180s」的循环惩罚
    """

    MAX_CONSECUTIVE_429 = 5  # 指数退避上限 2^4 * 180s = 48min → 封顶 30min

    def __init__(self) -> None:
        self._cooldown_until: dict[str, float] = {}
        self._last_error: dict[str, str] = {}
        self._consecutive_429: dict[str, int] = {}

    def record_failure(self, provider: str, category: str, status: int | None = None) -> None:
        base = CATEGORY_COOLDOWN_SECONDS.get(category, CATEGORY_COOLDOWN_SECONDS["unknown"])
        if category == "rate_limited":
            n = self._consecutive_429.get(provider, 0)
            cooldown = min(base * (2 ** min(n, self.MAX_CONSECUTIVE_429)), 1800.0)
            self._consecutive_429[provider] = n + 1
            if n >= 1:
                logger.warning(f"[health] {provider} 连续 429 x{n+1}，冷却指数退避至 {cooldown:.0f}s")
        else:
            self._consecutive_429.pop(provider, None)
            cooldown = base
        self._cooldown_until[provider] = time.time() + cooldown
        self._last_error[provider] = f"{category}({status})" if status else category

    def record_success(self, provider: str) -> None:
        self._cooldown_until.pop(provider, None)
        self._last_error.pop(provider, None)
        self._consecutive_429.pop(provider, None)

    def is_cooling_down(self, provider: str) -> bool:
        until = self._cooldown_until.get(provider)
        return until is not None and time.time() < until

    def remaining_seconds(self, provider: str) -> float:
        until = self._cooldown_until.get(provider)
        return max(0.0, round(until - time.time(), 1)) if until else 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            p: {
                "cooldown_remaining": self.remaining_seconds(p),
                "last_error": self._last_error.get(p),
            }
            for p in self._cooldown_until
        }


# 网关进程级单例
provider_health = ProviderHealth()


# ============================================================
# 模型级速度跟踪（2026-08-29 动态优先级评分）
# 目标：实现「好模型恢复自动上位」。
#   - 每个模型维护一个 EMA(指数移动平均) 实测耗时
#   - 数据来源 1：真实业务请求成功时的耗时（零额外成本）
#   - 数据来源 2：后台低频冷探测（仅对"冷"模型，10min 一次最小请求）
#   - 排序时只读缓存表，O(1)，不阻塞请求路径
# ============================================================

SPEED_EMA_ALPHA = float(os.getenv("HARNESS_SPEED_EMA_ALPHA", "0.3"))  # 越新越重的平滑系数
COLD_PROBE_INTERVAL = float(os.getenv("HARNESS_COLD_PROBE_INTERVAL", "60.0"))  # 冷模型探测周期(秒)
COLD_PROBE_SINCE = float(os.getenv("HARNESS_COLD_PROBE_SINCE", "180.0"))  # 距上次请求多久视为"冷"


class ModelSpeedTracker:
    """模型级实测耗时 EMA 跟踪 + 冷探测标记。

    - record_success(model, ms)：真实请求/探测成功 → 更新 EMA
    - record_failure(model)：失败 → 标记不可用（排序沉底）
    - last_seen / is_cold：距上次成功多久 → 决定是否需要冷探测
    - sort_key(model)：排序键（可用性优先，其次速度）
    """

    def __init__(self) -> None:
        self._ema_ms: dict[str, float] = {}          # 模型唯一键 -> EMA 耗时
        self._last_seen: dict[str, float] = {}        # 模型唯一键 -> 最近成功时间
        self._failed_at: dict[str, float] = {}        # 模型唯一键 -> 最近失败时间

    @staticmethod
    def _key(candidate: Any) -> str:
        return f"{candidate.provider}/{candidate.model}"

    def record_success(self, candidate: Any, ms: float) -> None:
        k = self._key(candidate)
        old = self._ema_ms.get(k)
        self._ema_ms[k] = (old * (1 - SPEED_EMA_ALPHA) + ms * SPEED_EMA_ALPHA) if old else ms
        self._last_seen[k] = time.time()
        self._failed_at.pop(k, None)

    def record_failure(self, candidate: Any) -> None:
        self._failed_at[self._key(candidate)] = time.time()

    def is_available(self, candidate: Any) -> bool:
        """有 EMA 记录且最近失败后又有成功 → 可用；只有失败记录 → 不可用"""
        k = self._key(candidate)
        if k not in self._ema_ms:
            return True  # 无历史记录（从未被探测/请求过）→ 默认可用，不惩罚
        return k not in self._failed_at or self._last_seen.get(k, 0) > self._failed_at.get(k, 0)

    def is_cold(self, candidate: Any) -> bool:
        """距上次成功请求超过 COLD_PROBE_SINCE 秒 → 需要冷探测"""
        last = self._last_seen.get(self._key(candidate))
        return last is None or (time.time() - last) > COLD_PROBE_SINCE

    def ema_ms(self, candidate: Any) -> float:
        return self._ema_ms.get(self._key(candidate), float("inf"))

    def snapshot(self) -> dict[str, dict]:
        return {
            k: {
                "ema_ms": round(v, 1) if v != float("inf") else None,
                "last_seen": round(self._last_seen.get(k, 0)),
            }
            for k, v in self._ema_ms.items()
        }


# 网关进程级单例
model_speed = ModelSpeedTracker()


# ============================================================
# 主动探活 / 降级(2026-08-28 新增, 对齐 opencode-smart-router)
# 目的: 解决进度文件 #4 待办 —— 不稳定模型(gLM-5.3-flash 限流等)仅被动熔断,
#       缺少主动探测。启动时/定期对候选链做轻量探活, 把失效 provider 提前降级,
#       避免业务请求先撞一次失败才换腿。被动熔断(record_failure)仍保留作兜底。
# ============================================================

PROBE_TIMEOUT = float(os.getenv("HARNESS_PROBE_TIMEOUT", "12"))
# 探活失败判定阈值: 超过该秒数视为"慢到不可用"(如 glm-5.3-flash 限流 45s)
PROBE_SLOW_MS = float(os.getenv("HARNESS_PROBE_SLOW_MS", "15000"))


def probe_provider(provider: str, base_url: str, api_key: str | None, model: str) -> dict[str, Any]:
    """
    对单个 provider+model 发一个最小请求, 返回可用性诊断。
    - ok: 能正常返回且耗时 < PROBE_SLOW_MS
    - slow: 能返回但过慢(限流前兆)
    - error: 请求失败(超时/4xx/5xx)
    """
    import time
    if not api_key:
        return {"provider": provider, "model": model, "ok": False, "error": "missing_api_key"}
    import httpx

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    start = time.time()
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as c:
            resp = c.post(url, json=payload, headers=headers)
        ms = int((time.time() - start) * 1000)
        if resp.status_code in (401, 403):
            return {"provider": provider, "model": model, "ok": False, "error": f"auth_{resp.status_code}", "ms": ms}
        if resp.status_code == 404:
            return {"provider": provider, "model": model, "ok": False, "error": "not_found", "ms": ms}
        if resp.status_code == 429:
            return {"provider": provider, "model": model, "ok": False, "error": "rate_limited", "ms": ms}
        if resp.status_code >= 500:
            return {"provider": provider, "model": model, "ok": False, "error": f"server_{resp.status_code}", "ms": ms}
        if resp.status_code != 200:
            return {"provider": provider, "model": model, "ok": False, "error": f"http_{resp.status_code}", "ms": ms}
        if ms > PROBE_SLOW_MS:
            return {"provider": provider, "model": model, "ok": True, "slow": True, "ms": ms}
        return {"provider": provider, "model": model, "ok": True, "ms": ms}
    except Exception as e:
        ms = int((time.time() - start) * 1000)
        return {"provider": provider, "model": model, "ok": False, "error": type(e).__name__, "ms": ms}


def probe_and_degrade(candidates: list[Any]) -> dict[str, Any]:
    """
    探测候选链中所有 provider 的可用性, 把失效/慢的自动加入冷却降级。
    返回诊断摘要。可在启动时异步调用一次, 也可由 /health?probe=1 触发。
    """
    import asyncio

    seen: dict[str, tuple[str, str]] = {}  # provider -> (base_url, model)
    for cand in candidates:
        seen.setdefault(cand.provider, (cand.provider, cand.model))

    results = []
    for provider, (base_url, primary_model) in seen.items():
        # 从 providers.yaml 读 endpoint/key(缺省 None→标 missing)
        base_url, api_key = _resolve_provider_config(provider, base_url)
        r = probe_provider(provider, base_url, api_key, primary_model)
        results.append(r)
        if not r.get("ok", False):
            cat = "rate_limited" if r.get("error") == "rate_limited" else (
                "server" if str(r.get("error", "")).startswith("server_") else "unknown"
            )
            # 失效/慢 → 冷却降级(长窗口 300s, 探活有独立冷却避免污染业务熔断)
            provider_health.record_failure(provider, cat, None)
        elif r.get("slow"):
            # 慢到不可用边界 → 轻冷却
            provider_health.record_failure(provider, "timeout", None)

    return {"probed": len(results), "results": results}


def _resolve_provider_config(provider: str, default_url: str) -> tuple[str, str | None]:
    """复用 provider_client.PROVIDER_CONFIGS 的端点/鉴权配置(不引入 yaml 依赖)。
    网关进程环境未装 pyyaml, 故不读 providers.yaml, 与 provider_client 保持一致。
    """
    from .provider_client import PROVIDER_CONFIGS
    cfg = PROVIDER_CONFIGS.get(provider, {})
    base_url = cfg.get("base_url", default_url)
    key_env = cfg.get("key_env")
    api_key = os.getenv(key_env) if key_env else None
    return base_url, api_key


def start_periodic_reprobe(interval: float | None = None) -> None:
    """后台线程(2026-08-29)：探测冷却中的 provider + 冷模型，恢复即自动上位。

    两类探测：
    1. 冷却中的 provider → 恢复即解除熔断（原有逻辑）
    2. 冷模型（距上次成功 > COLD_PROBE_SINCE，如恢复的末位腿）→ 更新速度表，
       让"恢复的好模型"能自动排前被优先使用。
    每轮对每个候选发一次最小请求(max_tokens=5)，成本可忽略。
    """
    from .route_candidates import GLOBAL_FALLBACK, ROUTE_CANDIDATES

    interval = interval or _env_float("HARNESS_REPROBE_INTERVAL", 120.0)
    import threading

    def _all_candidates() -> list:
        """收集所有链 + 全局兜底中的全部候选（去重）"""
        seen: dict[str, Any] = {}
        for chain in list(ROUTE_CANDIDATES.values()) + [GLOBAL_FALLBACK]:
            for cand in chain:
                seen.setdefault(model_speed._key(cand), cand)
        return list(seen.values())

    def _run():
        while True:
            time.sleep(interval)
            try:
                now = time.time()
                # 1. 冷却中的 provider → 探活，恢复即解除冷却
                cooling = [p for p, until in list(provider_health._cooldown_until.items()) if until > now]
                for provider in cooling:
                    cand = next((c for c in _all_candidates() if c.provider == provider), None)
                    if cand is None:
                        continue
                    base_url, api_key = _resolve_provider_config(provider, "")
                    r = probe_provider(provider, base_url, api_key, cand.model)
                    if r.get("ok") and not r.get("slow"):
                        provider_health.record_success(provider)
                        model_speed.record_success(cand, r.get("ms", 0))
                        logger.info(
                            f"[reprobe] {provider} recovered via {cand.model} "
                            f"({r.get('ms')}ms) — cooldown cleared early"
                        )
                        try:
                            from .stats import route_stats
                            route_stats.record_event("reprobe_recovered", {
                                "provider": provider, "leg": f"{provider}/{cand.model}", "ms": r.get("ms"),
                            })
                        except Exception:
                            pass  # 统计永不影响复探
                    # 失败/慢：保持冷却不动(不叠加，避免重置指数退避进度)

                # 2. 冷模型 → 探测，更新速度表（发现"恢复的好模型"自动上位）
                for cand in _all_candidates():
                    if not model_speed.is_cold(cand):
                        continue
                    base_url, api_key = _resolve_provider_config(cand.provider, "")
                    r = probe_provider(cand.provider, base_url, api_key, cand.model)
                    if r.get("ok") and not r.get("slow"):
                        model_speed.record_success(cand, r.get("ms", 0))
                        logger.info(
                            f"[probe] cold model {cand.provider}/{cand.model} OK "
                            f"({r.get('ms')}ms) — speed table updated, will be promoted"
                        )
                    else:
                        model_speed.record_failure(cand)
            except Exception as e:
                logger.warning(f"[reprobe] cycle failed (non-fatal): {e}")

    threading.Thread(target=_run, daemon=True).start()
    logger.info(
        f"[reprobe] periodic re-probe started (interval={interval:.0f}s, "
        f"cooling-providers + cold-models, cold interval={COLD_PROBE_INTERVAL:.0f}s)"
    )
