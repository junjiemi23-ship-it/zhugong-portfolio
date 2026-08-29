"""
健康检查端点逻辑
"""

import time
from typing import Any

from .route_candidates import ROUTE_CANDIDATES, GLOBAL_FALLBACK
from .resilience import provider_health, model_speed, probe_and_degrade

_START_TIME = time.time()


def health_check(probe: bool = False) -> dict[str, Any]:
    """返回网关健康状态（含 provider 熔断冷却状态）。
    probe=True 时先对候选链做一次主动探活/降级，再返回。
    """
    candidates_count = sum(len(chain) for chain in ROUTE_CANDIDATES.values())
    out = {
        "status": "ok",
        "candidates_count": candidates_count,
        "fallback_ready": len(GLOBAL_FALLBACK) > 0,
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "routes": list(ROUTE_CANDIDATES.keys()),
        "provider_health": provider_health.snapshot(),
        "model_speed": model_speed.snapshot(),
    }
    if probe:
        # 收集候选链全部候选做探活
        all_candidates = [c for chain in ROUTE_CANDIDATES.values() for c in chain]
        out["probe"] = probe_and_degrade(all_candidates)
        out["provider_health"] = provider_health.snapshot()
    return out
