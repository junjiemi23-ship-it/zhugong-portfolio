"""
Harness Smart Router - 智能模型路由网关
为 browser-use harness 提供类似 Hermes 的自动模型选择与切换能力。
"""

from .harness_router import app, route_request
from .route_candidates import ROUTE_CANDIDATES, Candidate, detect_task_type
from .context_gate import select_candidate
from .fallback_chain import GLOBAL_FALLBACK
from .provider_client import call_provider
from .health import health_check

__all__ = [
    "app",
    "route_request",
    "ROUTE_CANDIDATES",
    "Candidate",
    "detect_task_type",
    "select_candidate",
    "GLOBAL_FALLBACK",
    "call_provider",
    "health_check",
]