# -*- coding: utf-8 -*-
"""集中配置：全部 env 可覆盖，函数式读取（测试可在运行期改 env）。"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def get(key, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def upstream_base():
    return get("BRIDGE_UPSTREAM", "http://localhost:3000/v1").rstrip("/")


def pool_key():
    return get("BRIDGE_WEBPOOL_KEY", "")


def bridge_token():
    return get("BRIDGE_TOKEN", "")


def allowed_models():
    return {m.strip() for m in get("BRIDGE_MODELS", "gpt-5-5,gpt-5-6,gpt-5-5-instant,auto").split(",") if m.strip()}


def up_timeout():
    return float(get("BRIDGE_UP_TIMEOUT", "90"))


def up_retry():
    return int(get("BRIDGE_UP_RETRY", "2"))


def up_retry_backoff():
    return float(get("BRIDGE_UP_RETRY_BACKOFF", "3"))


def repair_max():
    return int(get("BRIDGE_REPAIR_MAX", "2"))


def empty_retry_max():
    """上游返回 200 但正文为空时的原样重试次数（非工具修复阶梯，不贴预填充）。
    2026-09-28 P4 复盘：结果回填轮偶发 completion_tokens=0 → 客户端收到空白消息。
    默认 1 次；设 0 即关闭该兜底。"""
    return int(get("BRIDGE_EMPTY_RETRY", "1"))


def prefill_enabled():
    """助手预填充总开关（P1 实测有效，但保留快速关停能力）。"""
    return get("BRIDGE_PREFILL", "on").lower() in ("on", "1", "true", "yes")


def prune_enabled():
    """E 配置②：任务级最小工具清单（P1.3 实测：长清单是压垮合规率的主因，92% vs 65%）。"""
    return get("BRIDGE_PRUNE", "on").lower() in ("on", "1", "true", "yes")


def antirefusal_enabled():
    """E 配置①：反拒答条款（P1 失败分析：~90% 败因是模型拒答，不是格式错误）。"""
    return get("BRIDGE_ANTIREFUSAL", "on").lower() in ("on", "1", "true", "yes")


def lease_window_s():
    return float(get("BRIDGE_LEASE_WINDOW", "900"))


def lease_max_forwards():
    return int(get("BRIDGE_LEASE_FORWARDS", "36"))


def lease_max_toolrounds():
    return int(get("BRIDGE_LEASE_TOOLROUNDS", "12"))


def spin_limit():
    return int(get("BRIDGE_SPIN_LIMIT", "3"))


def budget_tokens():
    return int(get("BRIDGE_BUDGET_TOKENS", "12000"))


def system_keep():
    return int(get("BRIDGE_SYSTEM_KEEP", "2400"))


def result_keep():
    return int(get("BRIDGE_RESULT_KEEP", "1024"))


def keep_rounds():
    return int(get("BRIDGE_KEEP_ROUNDS", "3"))


def log_dir():
    return get("BRIDGE_LOG_DIR", os.path.join(_HERE, "logs"))


def audit_keep_days():
    return int(get("BRIDGE_AUDIT_KEEP_DAYS", "7"))


# ---------- 文本冷却账本（A 方案：池子"限流"状态只记生图配额，文本限流看不见，
# 本地把 timeout/net/5xx/429 当文本限流代理信号，连续到阈值进冷却窗口，期间不打上游）----------

def cd_enabled():
    return get("BRIDGE_CD", "on").lower() in ("on", "1", "true", "yes")


def cd_threshold():
    """连续多少次可重试失败后进入冷却（池子常态抖动，单次超时不算限流）。"""
    return int(get("BRIDGE_CD_THRESHOLD", "3"))


def cd_min_sec():
    return float(get("BRIDGE_CD_MIN_SEC", "600"))


def cd_max_sec():
    return float(get("BRIDGE_CD_MAX_SEC", "1800"))


def cd_state():
    return get("BRIDGE_CD_STATE", os.path.join(_HERE, "state", "cooldown.json"))


def est_tokens(s):
    return len(str(s)) // 3
