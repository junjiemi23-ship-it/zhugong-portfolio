"""
统一 Provider 客户端：处理 B.AI/NVIDIA/Groq/本地 等不同鉴权与端点。
"""

import os
import logging
from pathlib import Path
from typing import Any

import httpx

from .route_candidates import Candidate

logger = logging.getLogger("harness_router.provider")


class MissingAPIKeyError(Exception):
    """凭据缺失 —— 属于 auth 类长冷却问题，换模型无用，只换 provider"""
    pass


def _load_hermes_env() -> None:
    """从 Hermes .env 补齐缺失的 API Key（手动解析，无 pyyaml 依赖）。

    根因修复(2026-08-29)：bash/计划任务/快捷方式/其他会话启动网关时，
    进程继承不到用户级 BAI_API_KEY/NVIDIA_API_KEY，导致 nvidia 全腿秒失败。
    网关自己读 .env 后，任何启动方式都健康。已存在的环境变量不覆盖。
    """
    # 2026-08-29 多 key 轮换：池内任一 key 缺失都要尝试加载（不再只看主 key）
    pool_envs = {e for cfg in PROVIDER_CONFIGS.values() for e in cfg.get("key_pool_envs", []) if not os.getenv(e)}
    if not pool_envs:
        return  # key 池全部就位，无需读取
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env",
        Path(os.environ.get("APPDATA", "")) / "hermes" / ".env",
        Path.home() / ".hermes" / ".env",
    ]
    for p in candidates:
        try:
            if not p.is_file():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and not os.getenv(k):
                    os.environ[k] = v
            logger.info(f"[env] loaded missing API keys from {p}")
        except Exception:
            continue


# 注意：_load_hermes_env 现在依赖 PROVIDER_CONFIGS 的 key_pool_envs，
# 调用点移到配置表之后（见下方 _load_hermes_env() 调用）。

# 共享 HTTP 连接池：避免每次请求新建 client 带来的 TCP/TLS 握手开销
_HTTP_CLIENT: httpx.Client | None = None


def _get_http_client(timeout: float) -> httpx.Client:
    """懒加载全局共享的 httpx.Client，复用连接避免握手开销。"""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=20),
            # 不自动解压以跳过不必要的开销（上游默认 gzip，命中时再解压）
            headers={"Accept-Encoding": "identity"},
        )
    return _HTTP_CLIENT

# 红线：付费 SKU 白名单（仅这些在显式授权时可放行）
# 2026-08-29: kimi-k3 已从 NVIDIA 免费化, 移出付费名单
PAID_SKUS = {"deepseek-v4-pro", "deepseek-r2", "glm-5.3"}


class HardBlockedProviderError(Exception):
    """红线拦截：OpenRouter 或未授权付费 SKU"""
    pass


# Provider 端点与鉴权配置（从环境变量读取密钥，绝不硬编码）
# key_pool_envs：多 key 轮换池（按顺序优先）。2026-08-29 三智能体统一接入 8124 后，
# BAI 侧流量 = Hermes + harness + opencode 之和，且两把 BAI key 属不同账号（独立额度池），
# 故把 opencode 原 key 收编为 BAI_API_KEY_2：撞 429/401 时自动换 key，两池分摊、限流风险不升反降。
# NVIDIA 两把 key 同账号共享速率池，轮换无收益，保持单 key。
PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "bai": {
        "base_url": "https://api.b.ai/v1",
        "key_env": "BAI_API_KEY",
        "key_pool_envs": ["BAI_API_KEY", "BAI_API_KEY_2"],
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
        "key_pool_envs": ["NVIDIA_API_KEY"],
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "key_pool_envs": ["GROQ_API_KEY"],
    },
    "local": {
        "base_url": os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "key_env": None,  # 本地模型通常无需鉴权
        "key_pool_envs": [],
    },
}

_load_hermes_env()


# ---------------------------------------------------------------------------
# 多 key 轮换（per-provider key pool）
# ---------------------------------------------------------------------------
# key 冷却表：env 名 -> 冷却到期时间戳。429/401/403 只冷却"这把 key"，
# 不冷却整个 provider —— 同 provider 的另一把 key（不同账号）立即可用。
_key_cooldown: dict[str, float] = {}
_key_rr_index: dict[str, int] = {}  # provider -> round-robin 游标


def _key_pool(provider: str) -> list[str]:
    cfg = PROVIDER_CONFIGS.get(provider) or {}
    return [e for e in cfg.get("key_pool_envs", []) if e]


def get_api_keys(provider: str) -> list[str]:
    """返回该 provider 当前可用（未冷却、非空）的 key 列表，按轮换优先级排序。

    全部冷却时忽略冷却兜底返回（与 _try_chain 的 ignore_cooldown 语义一致），
    保证有 key 就绝不空转；真正缺 key 才抛 MissingAPIKeyError。
    """
    import time as _t
    env_names = _key_pool(provider)
    if not env_names:
        env_names = [PROVIDER_CONFIGS.get(provider, {}).get("key_env") or ""]
    live = [e for e in env_names if e and os.getenv(e)]
    if not live:
        raise MissingAPIKeyError(
            f"Provider '{provider}' 缺少环境变量 {env_names}"
        )
    now = _t.time()
    fresh = [e for e in live if _key_cooldown.get(e, 0) <= now]
    pool = fresh or live  # 全冷却则兜底忽略冷却
    # round-robin：把上次用的 key 挪到队尾，分摊多账号流量
    idx = _key_rr_index.get(provider, 0) % len(pool)
    _key_rr_index[provider] = idx + 1
    return pool[idx:] + pool[:idx]


def mark_key_cooling(env_name: str, seconds: float) -> None:
    import time as _t
    _key_cooldown[env_name] = _t.time() + seconds
    logger.warning(f"[keypool] {env_name} 冷却 {seconds:.0f}s")


def key_cooldown_remaining(env_name: str) -> float:
    import time as _t
    return max(0.0, _key_cooldown.get(env_name, 0) - _t.time())


class AllKeysFailedError(Exception):
    """该 provider 池内所有 key 均失败（调用方据此冷却 provider 并换腿）"""
    def __init__(self, provider: str, last_error: Exception):
        self.provider = provider
        self.last_error = last_error
        super().__init__(f"provider '{provider}' 全部 {len(_key_pool(provider))} 把 key 均失败: {last_error}")


def enforce_red_lines(candidate: Candidate) -> None:
    """
    红线硬拦截：
    1. OpenRouter 彻底禁止 —— 任何情况下抛异常
    2. DeepSeek 官方付费 API —— 仅 ALLOW_DEEPSEEK_PAID=1 且用户显式授权时放行
    """
    if candidate.provider == "openrouter":
        raise HardBlockedProviderError(
            "红线拦截：OpenRouter 已被用户明令禁止，不得进入任何调用链"
        )

    if candidate.provider == "deepseek" and candidate.model in PAID_SKUS:
        if os.getenv("ALLOW_DEEPSEEK_PAID") != "1":
            raise HardBlockedProviderError(
                f"红线拦截：DeepSeek 官方付费 SKU '{candidate.model}' 未获人工显式授权"
            )


# 对消息结构校验严格的上游（孤立 role=tool 消息会 400）
STRICT_MESSAGE_PROVIDERS = {"nvidia", "groq"}


def sanitize_messages(provider: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    按上游清洗消息结构：
    NVIDIA/Groq 对「无前置 assistant tool_calls 的 role=tool 消息」返回 400，
    剔除这类孤立 tool 消息（合成的工具响应常见此问题）。
    """
    if provider not in STRICT_MESSAGE_PROVIDERS:
        return messages
    cleaned: list[dict[str, Any]] = []
    prev_assistant_had_tool_calls = False
    for m in messages:
        role = m.get("role")
        if role == "tool":
            if not prev_assistant_had_tool_calls:
                logger.warning("[sanitize] dropped orphan tool message (no preceding assistant tool_calls)")
                continue
        if role == "assistant":
            prev_assistant_had_tool_calls = bool(m.get("tool_calls"))
        cleaned.append(m)
    return cleaned


def call_provider(
    candidate: Candidate,
    payload: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """
    统一调用 Provider 的 OpenAI 兼容端点（多 key 轮换）。
    池内逐 key 尝试：429/401/403 只冷却当前 key 并换下一把（不同账号=独立额度池）；
    其余错误（5xx/timeout/4xx）换 key 无意义，直接抛出交给上层换模型腿。
    全部 key 失败 → AllKeysFailedError（包装最后一个错误，保持 classify_exception 兼容）。
    """
    enforce_red_lines(candidate)

    config = PROVIDER_CONFIGS.get(candidate.provider)
    if config is None:
        raise ValueError(f"未知 Provider: {candidate.provider}")

    keys = get_api_keys(candidate.provider)  # 缺 key 时在这里抛 MissingAPIKeyError

    url = f"{config['base_url'].rstrip('/')}/chat/completions"
    body = {**payload, "model": candidate.model}
    if isinstance(body.get("messages"), list):
        body["messages"] = sanitize_messages(candidate.provider, body["messages"])

    client = _get_http_client(timeout=timeout)
    last_exc: Exception | None = None
    for env_name in keys:
        api_key = os.getenv(env_name) or ""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        logger.info(
            f"[provider_call] provider={candidate.provider} model={candidate.model} "
            f"key={env_name} ({len(keys)} in pool)"
        )
        try:
            resp = client.post(url, json=body, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            last_exc = e
            if status in (429, 401, 403):
                # 这把 key 的账号被限流/失效 → 冷却它，换池内下一把 key
                mark_key_cooling(env_name, 180.0 if status == 429 else 300.0)
                continue
            raise  # 5xx/4xx：换 key 无用，交给 _try_chain 换腿
        except Exception:
            raise  # timeout/连接错误：换 key 无用
    raise AllKeysFailedError(candidate.provider, last_exc) if last_exc else MissingAPIKeyError(candidate.provider)


async def call_provider_async(
    candidate: Candidate,
    payload: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """异步版本（供 FastAPI 网关使用）"""
    import asyncio
    return await asyncio.to_thread(call_provider, candidate, payload, timeout)