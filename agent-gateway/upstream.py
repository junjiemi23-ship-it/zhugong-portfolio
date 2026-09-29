# -*- coding: utf-8 -*-
"""网页池客户端：OpenAI 面、不带 tools 字段、整包收取、401/403/429 直判失败不回退。"""
import json
import re
import time
from typing import Any

import httpx

import config
import cooldown


class UpstreamError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind      # auth / rate / http / timeout / net
        self.message = message
        self.status = status


def collect_content(text: str) -> str:
    """从 SSE 或整包 JSON 中提取 assistant 文本（池子 stream 参数未必全模式支持，双兼容）。"""
    text = text.strip()
    if not text:
        return ""
    if text.startswith("{"):
        try:
            j = json.loads(text)
            ch = (j.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            if msg.get("content"):
                return str(msg["content"])
            if msg.get("reasoning_content"):
                return ""  # 纯思考不出正文（视作空，触发修复）
        except Exception:
            pass
    out = []
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("[DONE]", ""):
            continue
        try:
            j = json.loads(payload)
        except Exception:
            continue
        for ch in j.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("content"):
                out.append(str(delta["content"]))
            msg = ch.get("message") or {}
            if msg.get("content") and not out:
                out.append(str(msg["content"]))
    return "".join(out)


def usage_of(raw: str) -> dict:
    try:
        j = json.loads(raw) if raw.strip().startswith("{") else None
    except Exception:
        j = None
    if j and isinstance(j.get("usage"), dict):
        return j["usage"]
    return {}


def call_upstream(model: str, messages: list[dict], max_tokens: int) -> tuple[str, dict, float, str | None]:
    """返回 (assistant_text, usage, elapsed_s, upstream_response_id)。失败抛 UpstreamError。
    瞬时可重试类（上游超时/5xx/网络）按 config.up_retry() 重试；重试由调用方换 nonce 前先在此重发。
    文本冷却（A 方案）：连续可重试失败到阈值或遇 429 → 进冷却窗口，期间 fast-fail 不打上游。"""
    if cooldown.is_blocked():
        raise UpstreamError("rate", "池子文本冷却中（上游连续超时/限流），跳过本次上游调用")
    last: UpstreamError | None = None
    for attempt in range(config.up_retry() + 1):
        try:
            r = _call_once(model, messages, max_tokens)
            cooldown.record_success()
            return r
        except UpstreamError as e:
            last = e
            retryable = e.kind in ("timeout", "net") or (e.status is not None and e.status >= 500)
            if not retryable:
                if e.kind == "rate":
                    cooldown.record_failure("rate")  # 429 是显式限流信号，立即触发冷却
                raise
            if cooldown.record_failure(e.kind):
                raise UpstreamError(
                    "rate", f"触发池子文本冷却（连续 {config.cd_threshold()} 次 {e.kind}，"
                            f"末次：{e.message}），停止重试避免加剧上游限流")
            if attempt < config.up_retry():
                time.sleep(config.up_retry_backoff())
                continue
            raise
    raise last or UpstreamError("net", "未知上游失败")


def _call_once(model: str, messages: list[dict], max_tokens: int) -> tuple[str, dict, float, str | None]:
    key = config.pool_key()
    if not key:
        raise UpstreamError("auth", "缺少 BRIDGE_WEBPOOL_KEY（池子密钥未配置）")
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,  # 实验验证过的路径；nonce 在 messages 里已改变池子 cache_key，防回放
    }
    headers = {"content-type": "application/json", "authorization": "Bearer " + key}
    t0 = time.time()
    try:
        with httpx.Client(trust_env=False, timeout=config.up_timeout()) as client:
            with client.stream("POST", config.upstream_base() + "/chat/completions",
                               json=body, headers=headers) as r:
                if r.status_code == 401:
                    raise UpstreamError("auth", "池子鉴权失败（401），密钥或账号问题", 401)
                if r.status_code == 403:
                    raise UpstreamError("auth", "池子拒绝（403）", 403)
                if r.status_code == 429:
                    raise UpstreamError("rate", "池子限流（429）", 429)
                if r.status_code >= 400:
                    txt = r.read().decode("utf-8", "replace")[:300]
                    raise UpstreamError("http", f"池子 HTTP {r.status_code}: {txt}", r.status_code)
                raw = r.read().decode("utf-8", "replace")
        # 响应后处理也必须在兜底范围内：collect_content/usage_of/正则任何异常
        # 都应成为 UpstreamError（→502），而不是裸异常冒泡成 500（2026-09-20 排障补齐）
        dt = time.time() - t0
        content = collect_content(raw)
        rid = None
        m = re.search(r'"id"\s*:\s*"(chatcmpl-[0-9a-f]+)"', raw)
        if m:
            rid = m.group(1)
        return content, usage_of(raw), dt, rid
    except httpx.TimeoutException as e:
        raise UpstreamError("timeout", f"上游超时 {config.up_timeout():.0f}s") from e
    except UpstreamError:
        raise
    except Exception as e:
        raise UpstreamError("net", f"上游连接失败: {type(e).__name__}: {e}") from e
