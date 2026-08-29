"""
全局 Fallback 链：仅当网关进程不可用时由调用方直连使用。
"""

from .route_candidates import GLOBAL_FALLBACK, Candidate

__all__ = ["GLOBAL_FALLBACK", "Candidate"]