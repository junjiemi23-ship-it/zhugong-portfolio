"""
上下文门控：请求 token 接近模型上限时自动跳过小上下文模型。
"""

from .route_candidates import Candidate


# 安全系数：估算 token × 1.2 后仍需小于模型上下文上限
SAFETY_MARGIN = 1.2


def estimate_tokens(text: str) -> int:
    """
    粗略估算文本的 token 数。
    英文按 ~4 chars/token，中文按 ~1.5 chars/token（偏保守）。
    """
    if not text:
        return 0
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def select_candidate(candidates: list[Candidate], estimated_tokens: int) -> list[Candidate]:
    """
    过滤候选链：剔除 context_limit < estimated_tokens × 1.2 的模型。
    保持原有优先级顺序，返回过滤后的链。
    """
    if estimated_tokens <= 0:
        return list(candidates)
    threshold = int(estimated_tokens * SAFETY_MARGIN)
    filtered = [c for c in candidates if c.context_limit >= threshold]
    if not filtered and candidates:
        # 全被过滤时，退回上下文最大的模型（宁可溢出报错也不无模型可用）
        return [max(candidates, key=lambda c: c.context_limit)]
    return filtered