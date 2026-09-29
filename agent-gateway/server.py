# -*- coding: utf-8 -*-
"""Protocol Bridge :3460 —— ZCode(Anthropic /v1/messages) → 网页池(OpenAI 面无tools) 协议桥。

设计权威：../MERGED-PLAN.md 第1节（a~g 逐条对应本文件行为）；裁决：../CODEX-VERDICT.md。
桥不执行任何工具；只做协议翻译、封套解析、验证闸门与防线。
"""
import asyncio
import atexit
import json
import os
import sys
import threading
import uuid
import time

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import audit
import config
import cooldown
import guard
import protocol
import translate
import upstream


def _loop_exception_handler(loop, context) -> None:
    """asyncio 任务级未处理异常（不触发 sys.excepthook，是取证链唯一缺口）。"""
    try:
        exc = context.get("exception")
        if exc is not None:
            _crash_log("asyncio_task", (type(exc), exc, getattr(exc, "__traceback__", None)))
        else:
            _crash_log("asyncio_task", str(context.get("message") or "no exception object"))
    except Exception:
        pass
    loop.default_exception_handler(context)


@asynccontextmanager
async def _lifespan(app):
    try:
        asyncio.get_running_loop().set_exception_handler(_loop_exception_handler)
    except Exception:
        pass
    yield


app = FastAPI(title="agent-protocol-bridge", version="1.0", lifespan=_lifespan)

_sems: dict = {}  # 并发1（MERGED-PLAN 1f）；按事件循环惰性建，避免跨 loop 复用崩


def _get_sem() -> "asyncio.Semaphore":
    loop = asyncio.get_running_loop()
    key = id(loop)
    s = _sems.get(key)
    if s is None:
        s = _sems[key] = asyncio.Semaphore(1)
    return s
_stats = {"req": 0, "ok_chat": 0, "ok_tool": 0, "repair": 0, "bridge_reject": 0,
          "upstream_err": 0, "auth_reject": 0, "forced_nocall": 0, "empty_retry": 0,
          "since": time.time()}

# c4/c5 诊断标注（2026-09-27，主公批准：只标注、绝不伪造工具调用）。
# 客户端已经用 tool_choice=any/required/具名 明说"必须调工具"，而修复阶梯用尽仍拿不到
# 任何封套时，如实告诉客户端这是后端硬上限，而不是让它以为回复里那些"命令输出"是真的。
FORCED_NO_CALL_NOTE = ("[bridge] 诊断：客户端强制要求工具调用（tool_choice={choice}），"
                       "但修复阶梯已用尽（{attempts}/{max} 次重试，含深度预填充）仍未得到任何工具封套。"
                       "网页后端不会像官方 API 那样从 assistant 前缀真正续写，此类形状属硬上限，"
                       "非桥侧配置可解；桥不会伪造工具调用。")


def _choice_label(raw) -> str:
    """把客户端原始 tool_choice 还原成人读标签。

    内部 force 是归一化值（required/{"type":"required"} 都压成 "any"），直接拿它标注
    会对客户端撒谎——它明明发的 required，却看到 tool_choice=any。标注/审计一律用原值。
    """
    if raw is None:
        return "auto"
    if isinstance(raw, str):
        return raw or "auto"
    if isinstance(raw, dict):
        t = str(raw.get("type") or "")
        nm = raw.get("name") or (raw.get("function") or {}).get("name") or ""
        return f"{t}:{nm}" if nm else (t or "auto")
    return str(raw)


def _unverified_note(choice: str, attempts: int, forced_nocall: bool) -> str:
    """修复耗尽仍无调用时的诚实标注文本（两个协议面共用，口径一致）。"""
    head = "[bridge] 本回复未经任何工具调用验证，其中的命令输出/文件内容不来自你的机器。"
    if forced_nocall:
        head += "\n" + FORCED_NO_CALL_NOTE.format(
            choice=choice, attempts=attempts, max=config.repair_max())
    return head


# ---------- 崩溃取证（2026-09-20：桥多次无痕迹退出——uvicorn 输出只在 cmd 窗口，
# 事后零证据。现把未捕获异常/线程异常/致命信号全部落盘；心跳线程给出精确死亡时刻；
# atexit 记录区分"正常关停/Ctrl+C"与"被强杀"——强杀时 atexit 不触发、心跳冻结）----------
def _crash_log(tag: str, dump=None) -> None:
    try:
        path = os.path.join(config.log_dir(), f"crash-{time.strftime('%Y%m%d')}.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n==== {time.strftime('%Y-%m-%dT%H:%M:%S')} pid={os.getpid()} tag={tag} ====\n")
            if dump is not None:
                import traceback
                if isinstance(dump, tuple):
                    traceback.print_exception(dump[0], dump[1], dump[2], file=f)
                elif hasattr(dump, "exc_type"):  # threading.ExceptHookArgs
                    traceback.print_exception(dump.exc_type, dump.exc_value, dump.exc_traceback, file=f)
                else:
                    f.write(str(dump))
    except Exception:
        pass


def _heartbeat_loop() -> None:
    while True:
        try:
            p = os.path.join(config.log_dir(), "heartbeat.json")
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "uptime_s": int(time.time() - _stats["since"])}, f)
            os.replace(tmp, p)
        except Exception:
            pass
        time.sleep(15)


def _install_crash_hooks() -> None:
    try:
        os.makedirs(config.log_dir(), exist_ok=True)
        import faulthandler
        faulthandler.enable()  # 致命 C 级故障 → 全线程栈写 stderr（已重定向到日志文件）
        sys.excepthook = lambda et, ev, tb: _crash_log("uncaught", (et, ev, tb))
        threading.excepthook = lambda a: _crash_log("thread", a)
        atexit.register(lambda: _crash_log("exit", "uvicorn 进程退出（正常关停或 Ctrl+C）"))
        threading.Thread(target=_heartbeat_loop, daemon=True,
                         name="bridge-heartbeat").start()
    except Exception:
        pass


_install_crash_hooks()


PROTO_MARK = "[Bridge tool protocol v1]"
NONCE_MARK = "bridge-nonce:"


def _auth_ok(request: Request) -> bool:
    tok = config.bridge_token()
    if not tok:
        return True  # 未配置 = loopback 本地信任（与 8124 网关口径一致）
    hdr = request.headers.get("authorization") or ""
    xapi = request.headers.get("x-api-key") or ""
    given = xapi or (hdr[7:] if hdr.lower().startswith("bearer ") else "")
    import hmac
    return hmac.compare_digest(given, tok)


def _err(status: int, etype: str, msg: str) -> JSONResponse:
    return JSONResponse({"type": "error", "error": {"type": etype, "message": msg}},
                        status_code=status)


def _clean_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(b.get("text") or "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p).strip()
    return str(content or "").strip()


def _swap_tail(content: str, new_tail: str) -> str:
    """替换 system 消息里的协议尾部（幂等：先剪旧尾再接新尾）。"""
    c = str(content or "")
    cut = len(c)
    for mark in (PROTO_MARK, NONCE_MARK):
        i = c.rfind(mark)
        if i != -1:
            # 协议段前可能有 "\n\n"，一并剪掉
            cut = min(cut, c.rfind("\n\n", 0, i) if c.rfind("\n\n", 0, i) != -1 else i)
    return (c[:cut].rstrip() + "\n\n" + new_tail).strip()


def _first_user(msgs: list) -> str:
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            t = _clean_text(m.get("content"))
            if t:
                return t
    return ""


def _last_user(msgs: list) -> str:
    """会话里最后一条非空 user 消息（任务路由用）。

    ZCode 会在 messages 开头注入工作区上下文（含“创建/写入文件”等能力描述），
    若按首条 user 做任务级剪枝会被注入文本误导；用户最新意图在末条。
    指纹（lease_fingerprint）仍用 _first_user，会话级语义不变。
    """
    t = ""
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user":
            s = _clean_text(m.get("content"))
            if s:
                t = s
    return t


async def _forward(model: str, oa_msgs: list, max_tokens: int) -> tuple[str, dict, float, str]:
    return await asyncio.to_thread(upstream.call_upstream, model, oa_msgs, max_tokens)


# ---------- Anthropic 面（ZCode 主路） ----------

async def _agent_loop(body: dict) -> JSONResponse:
    model = str(body.get("model") or "auto").strip() or "auto"
    if model not in config.allowed_models():
        _stats["bridge_reject"] += 1
        return _err(400, "invalid_request_error",
                    f"模型 '{model}' 不在桥白名单（{sorted(config.allowed_models())}）")
    sys_in = body.get("system")
    msgs_in = body.get("messages") or []
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    max_tokens = int(body.get("max_tokens") or 4096)
    inject, force = guard.tool_choice_policy(body.get("tool_choice"))

    first_user = _first_user(msgs_in)
    fp = guard.lease_fingerprint(_clean_text(sys_in), first_user)
    # E 配置②：任务级最小工具清单——协议提示里只列任务相关的那一个工具（P1.3 主因杠杆），
    # 但 parse() 的白名单仍是完整 tools（模型若吐别的工具仍按白名单判，不因剪枝而误杀）。
    prompt_tools = protocol.prune_tools(tools, _last_user(msgs_in)) if (inject and tools) else tools
    nonce = uuid.uuid4().hex[:12]
    tail = protocol.protocol_prompt(prompt_tools, nonce) if (inject and tools) else (NONCE_MARK + " " + nonce)
    try:
        oa_msgs, rstats = translate.render_budgeted(sys_in, msgs_in, tail)
    except translate.BudgetExceeded as e:
        _stats["bridge_reject"] += 1
        audit.emit("reject", fp=fp, reason=str(e))
        return _err(400, "invalid_request_error", f"桥上下文预算拒绝：{e}")

    attempts, strict, failure_note = 0, False, ""
    empty = 0
    while True:
        # 每次尝试（含修复重试/空正文重发）换新 nonce → 池子 cache_key 必然变化，杜绝缓存回放致命重试
        if attempts or empty:
            nonce = uuid.uuid4().hex[:12]
            for m in oa_msgs:
                if m.get("role") == "system":
                    # 2026-09-28 P4 复跑：strict 修复提示改用【剪枝后的 prompt_tools】而非全量 tools。
                    # 旧代码此处传 tools（4 工具），导致首轮拒答后 strict 重发把 Bash 也摆出来，
                    # 模型遂挑 Bash → 3 条 WRONG_TOOL（期望 Grep/Read）。与首轮口径对齐后，
                    # 模型被持续约束在任务相关的那一个工具上。parse 白名单仍是全量 tools（不误杀）。
                    new_tail = (protocol.protocol_prompt(
                        prompt_tools if (inject and tools) else tools, nonce,
                        strict_addendum=True, failure_note=failure_note)
                        if strict else
                        (protocol.protocol_prompt(prompt_tools, nonce)
                         if (inject and tools) else (NONCE_MARK + " " + nonce)))
                    m["content"] = _swap_tail(m.get("content"), new_tail)
                    break
        # 修复升级序列（P1 实测：深度预填充在 auto 上把合规率从 33% 拉到 100%）：
        #   首轮原生（自主性最完整）→ D 级骨架预填充（模型自选工具）→ C 级深预填充（仅具名工具）
        pre = ""
        if config.prefill_enabled() and attempts == 1 and inject and tools:
            pre = protocol.prefill_scaffold(tools)
        elif config.prefill_enabled() and attempts >= 2 and inject and tools:
            named = force[len("named:"):] if force.startswith("named:") else ""
            # 2026-09-25：force none 时也借剪枝后的单工具名做深预填充（P1：auto 33%→100% 的主杠杆），
            # 否则 lookup 形状请求在骨架预填充下仍会干净拒答。
            if not named and len(prompt_tools) == 1:
                named = prompt_tools[0]["name"]
            pre = protocol.prefill_deep(named) if named else protocol.prefill_scaffold(tools)
        send = list(oa_msgs)
        if pre:
            send.append({"role": "assistant", "content": pre})
        try:
            guard.lease_check_and_count(fp, "forward")
        except guard.LeaseExceeded as e:
            _stats["bridge_reject"] += 1
            audit.emit("lease_block", fp=fp, reason=str(e))
            return _err(429, "rate_limit_error", str(e))
        try:
            text, usage, dt, up_id = await _forward(model, send, max_tokens)
        except upstream.UpstreamError as e:
            _stats["upstream_err"] += 1
            audit.emit("upstream_err", fp=fp, kind=e.kind, status=e.status)
            return _err(502, "api_error", f"上游失败[{e.kind}]：{e.message}")
        calls, malformed = protocol.parse(text, tools if inject else [], prefill=pre)
        audit.emit("forward", fp=fp, model=model, nonce=nonce, ms=int(dt * 1000),
                   up_id=up_id, attempts=attempts, stage=rstats.get("stage"),
                   tokens_est=rstats.get("tokens_est"), calls=len(calls),
                   malformed=malformed, usage=usage, text_len=len(text),
                   prefill=bool(pre), prompt_tools=[t["name"] for t in prompt_tools] if inject else [])
        need = force == "any" or force.startswith("named") or (
            inject and bool(tools) and guard.is_action_request(first_user)
            and not guard.result_present(msgs_in)) or (
            # 2026-09-25：干净拒答也触发修复阶梯（感官对齐官方：给了工具+要求用，就该回 tool_use）
            inject and bool(tools) and not calls and guard.looks_like_refusal(text))
        # 空正文重发（2026-09-28 P4 复盘）：上游返回 200 但正文为空（实测结果回填轮偶发
        # completion_tokens=0）→ 客户端看到空白助手消息，感官为"已读结果却沉默"。
        # 这不是协议失败也不算拒答，旧逻辑因 result_present/need=False 直接放行空回复。
        # 判据用【原始正文】为空，而非 visible_text 为空：后者会把"畸形封套被剥标签后为空"
        # 也误判进来，抢在修复阶梯前重发 → 破坏 T2 畸形重试次数契约（离线测试实测 4≠3）。
        # 独立走一次原样重发（换 nonce 破缓存、不贴预填充、不进强制调用阶梯），最多 empty_retry_max 次；
        # 设 0 即关闭。与 need/repair 阶梯互不干扰：优先于拒答修复，因为空回复没有可"修复"的内容。
        if not calls and not (text or "").strip() and empty < config.empty_retry_max():
            empty += 1
            _stats["empty_retry"] += 1
            continue
        if not calls and need and attempts < config.repair_max():
            attempts += 1
            _stats["repair"] += 1
            strict = True
            failure_note = "上一次回复没有有效工具封套" + (f"（问题：{malformed}）" if malformed else "") \
                           + "。现在只输出封套，参数用完整 JSON。"
            continue
        break

    stop = "tool_use" if calls else "end_turn"
    _stats["ok_tool" if calls else "ok_chat"] += 1
    clean = protocol.visible_text(text)
    # c4/c5：客户端显式强制（force=any/named）却拿不到任何调用 → 单独计数 + 显式标注
    forced_nocall = bool(guard.is_forced(force) and need and not calls)
    if forced_nocall:
        _stats["forced_nocall"] += 1
    if need and not calls:
        # 诚实标注（Codex Q5）：修复耗尽仍无调用 → 明确"未经工具验证"，不让假执行话术裸奔
        clean = _unverified_note(_choice_label(body.get("tool_choice")), attempts,
                                 forced_nocall) + "\n\n" + clean
    content = ([{"type": "text", "text": clean}] if clean else []) + [
        {"type": "tool_use", "id": uid, "name": n, "input": p} for uid, n, p in calls]
    resp = {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message", "role": "assistant", "model": model,
        "content": content, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": int(usage.get("prompt_tokens") or 0),
                  "output_tokens": int(usage.get("completion_tokens") or 0)},
        "bridge": {"attempts": attempts, "malformed": malformed or None, "upstream_id": up_id,
                   "forced_nocall": forced_nocall},
    }
    audit.emit("respond", fp=fp, stop=stop, calls=[(n, p) for _, n, p in calls],
               tool_choice=_choice_label(body.get("tool_choice")), force=force,
               attempts=attempts, forced_nocall=forced_nocall)
    if body.get("stream"):
        return _sse_response(resp, fp)
    return JSONResponse(resp)


def _sse_response(resp: dict, fp: str) -> "StreamingResponse":
    """Anthropic SSE 事件序列（ZCode 期待的标准格式）：
    message_start → content_block_start → content_block_delta×N → content_block_stop
    → message_delta(stop_reason+usage) → message_stop。非流式逻辑不变，只是把同一份
    响应拆成事件流；桥内部仍整包收上游（池子 stream 支持不稳），对客户端再做流式适配。"""
    from fastapi.responses import StreamingResponse

    def gen():
        def ev(t: str, data: dict) -> str:
            return "event: " + t + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n"

        msg_id = resp["id"]
        # message_start 的 content 必须是空数组、stop_reason 必须为 null（Anthropic SSE
        # 标准）。内容全部由后续 content_block_* 事件递增交付。此前把完整 content 塞进
        # message_start -> ZCode SDK 校验 "Expected 'tool_use'" 失败（text 块不合法）。
        start_msg = {k: v for k, v in resp.items() if k != "bridge"}
        start_msg["content"] = []
        start_msg["stop_reason"] = None
        yield ev("message_start", {"type": "message_start", "message": start_msg})
        idx = 0
        for block in resp["content"]:
            bid = block["id"] if "id" in block else "blk_" + msg_id[4:] + "_" + str(idx)
            if "id" not in block:
                block["id"] = bid
            # content_block_start 只带结构元信息，text/input 必须为空 -> 全部内容
            # 由后续 delta 递增给出（Anthropic SSE 标准）。
            if block["type"] == "text":
                start_block = {"type": "text", "text": "", "id": bid}
            else:
                start_block = {"type": "tool_use", "id": bid, "name": block["name"], "input": {}}
            yield ev("content_block_start",
                     {"type": "content_block_start", "index": idx, "content_block": start_block})
            if block["type"] == "text":
                for chunk in _text_chunks(block["text"]):
                    yield ev("content_block_delta", {"type": "content_block_delta", "index": idx,
                                                     "delta": {"type": "text_delta", "text": chunk}})
            else:
                yield ev("content_block_delta", {"type": "content_block_delta", "index": idx,
                                                 "delta": {"type": "input_json_delta",
                                                           "partial_json": json.dumps(block["input"], ensure_ascii=False)}})
            yield ev("content_block_stop", {"type": "content_block_stop", "index": idx})
            idx += 1
        yield ev("message_delta", {"type": "message_delta", "delta": {
            "stop_reason": resp["stop_reason"], "stop_sequence": None},
            "usage": resp["usage"]})
        yield ev("message_stop", {"type": "message_stop"})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _text_chunks(text: str, size: int = 240) -> list[str]:
    """按行/句切，单块不超过 size 字符，避免一个巨大 delta。"""
    if len(text) <= size:
        return [text] if text else []
    out, buf = [], ""
    for line in text.splitlines(keepends=True):
        buf += line
        if len(buf) >= size:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


@app.post("/v1/messages")
async def messages(request: Request):
    _stats["req"] += 1
    if not _auth_ok(request):
        _stats["auth_reject"] += 1
        return _err(401, "authentication_error", "桥鉴权失败（BRIDGE_TOKEN 不匹配）")
    try:
        body = await request.json()
    except Exception:
        return _err(400, "invalid_request_error", "请求体不是合法 JSON")
    if not config.pool_key():
        return _err(500, "api_error", "桥未配置 BRIDGE_WEBPOOL_KEY")
    async with _get_sem():
        return await _agent_loop(body)


# ---------- OpenAI 兼容面（Hermes web profile 等无执行回路客户端；同闸门） ----------

def _norm_tools(tools_raw) -> list:
    out = []
    for t in tools_raw if isinstance(tools_raw, list) else []:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") or {}
        out.append({"name": fn.get("name") or t.get("name") or "",
                    "description": fn.get("description") or t.get("description") or "",
                    "input_schema": fn.get("parameters") or t.get("input_schema") or {}})
    return [t for t in out if t["name"]]


async def _chat_loop(body: dict) -> JSONResponse:
    model = str(body.get("model") or "auto").strip() or "auto"
    if model not in config.allowed_models():
        _stats["bridge_reject"] += 1
        return _err(400, "invalid_request_error", f"模型 '{model}' 不在桥白名单")
    msgs_in = [dict(m) for m in (body.get("messages") or []) if isinstance(m, dict)]
    tools = _norm_tools(body.get("tools"))
    inject, force = guard.tool_choice_policy(body.get("tool_choice"))
    first_user = _first_user(msgs_in)
    sys_base = "\n".join(_clean_text(m.get("content")) for m in msgs_in
                         if m.get("role") == "system")
    fp = guard.lease_fingerprint(sys_base, first_user)
    prompt_tools = protocol.prune_tools(tools, _last_user(msgs_in)) if (inject and tools) else tools
    nonce = uuid.uuid4().hex[:12]
    tail = protocol.protocol_prompt(prompt_tools, nonce) if (inject and tools) else (NONCE_MARK + " " + nonce)
    oa_msgs = [m for m in msgs_in if m.get("role") != "system"]
    oa_msgs.insert(0, {"role": "system", "content": (sys_base + "\n\n" + tail).strip()})

    attempts = 0
    failure_note = ""
    while True:
        if attempts:
            nonce = uuid.uuid4().hex[:12]
            oa_msgs[0]["content"] = _swap_tail(oa_msgs[0]["content"], protocol.protocol_prompt(
                tools, nonce, strict_addendum=True, failure_note=failure_note))
        pre = ""
        if config.prefill_enabled() and attempts == 1 and inject and tools:
            pre = protocol.prefill_scaffold(tools)
        elif config.prefill_enabled() and attempts >= 2 and inject and tools:
            named = force[len("named:"):] if force.startswith("named:") else ""
            # 2026-09-25：force none 时也借剪枝后的单工具名做深预填充（P1：auto 33%→100% 的主杠杆），
            # 否则 lookup 形状请求在骨架预填充下仍会干净拒答。
            if not named and len(prompt_tools) == 1:
                named = prompt_tools[0]["name"]
            pre = protocol.prefill_deep(named) if named else protocol.prefill_scaffold(tools)
        send = list(oa_msgs)
        if pre:
            send.append({"role": "assistant", "content": pre})
        try:
            guard.lease_check_and_count(fp, "forward")
        except guard.LeaseExceeded as e:
            _stats["bridge_reject"] += 1
            return _err(429, "rate_limit_error", str(e))
        try:
            text, usage, dt, up_id = await _forward(model, send, int(body.get("max_tokens") or 4096))
        except upstream.UpstreamError as e:
            _stats["upstream_err"] += 1
            audit.emit("upstream_err", fp=fp, kind=e.kind, status=e.status)
            return _err(502, "api_error", f"上游失败[{e.kind}]：{e.message}")
        calls, malformed = protocol.parse(text, tools if inject else [], prefill=pre)
        audit.emit("forward", fp=fp, face="chat", model=model, ms=int(dt * 1000),
                   calls=len(calls), malformed=malformed, up_id=up_id, attempts=attempts,
                   prefill=bool(pre), prompt_tools=[t["name"] for t in prompt_tools] if inject else [])
        last_is_tool = bool(msgs_in) and str(msgs_in[-1].get("role") or "") == "tool"
        need = force == "any" or force.startswith("named") or (
            inject and bool(tools) and guard.is_action_request(first_user) and not last_is_tool) or (
            # 2026-09-25：干净拒答也触发修复阶梯（与 Anthropic 面同口径）
            inject and bool(tools) and not calls and guard.looks_like_refusal(text))
        if not calls and need and attempts < config.repair_max():
            attempts += 1
            _stats["repair"] += 1
            failure_note = f"上一次回复无效（{malformed or '无封套'}）。只输出封套。"
            continue
        break

    finish = "tool_calls" if calls else "stop"
    visible = protocol.visible_text(text)
    forced_nocall = bool(guard.is_forced(force) and need and not calls)
    if forced_nocall:
        _stats["forced_nocall"] += 1
    if need and not calls:
        visible = _unverified_note(_choice_label(body.get("tool_choice")), attempts,
                                   forced_nocall) + "\n\n" + (visible or "")
    msg = {"role": "assistant", "content": visible or None}
    if calls:
        msg["tool_calls"] = [{"id": uid, "type": "function",
                              "function": {"name": n, "arguments": json.dumps(p, ensure_ascii=False)}}
                             for uid, n, p in calls]
    _stats["ok_tool" if calls else "ok_chat"] += 1
    audit.emit("respond", fp=fp, face="chat", stop=finish,
               tool_choice=_choice_label(body.get("tool_choice")), force=force,
               attempts=attempts, forced_nocall=forced_nocall,
               calls=[(n, p) for _, n, p in calls])
    if body.get("stream"):
        resp = {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                "usage": usage}
        return _chat_sse_response(resp)
    return JSONResponse({"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion",
                         "model": model,
                         "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                         "usage": usage})


def _chat_sse_response(resp: dict) -> "StreamingResponse":
    """OpenAI 兼容 SSE：data: {chunk}×N → data: [DONE]。"""
    from fastapi.responses import StreamingResponse

    def gen():
        msg = resp["choices"][0]["message"]
        cid = resp["id"]
        first = {"id": cid, "object": "chat.completion.chunk", "model": resp["model"],
                 "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
        yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
        if msg.get("content"):
            for chunk in _text_chunks(msg["content"]):
                yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'model': resp['model'], 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
        for tc in msg.get("tool_calls") or []:
            yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'model': resp['model'], 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': tc['id'], 'type': 'function', 'function': {'name': tc['function']['name'], 'arguments': tc['function']['arguments']}}]}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'model': resp['model'], 'choices': [{'index': 0, 'delta': {}, 'finish_reason': resp['choices'][0]['finish_reason']}], 'usage': resp['usage']}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/v1/chat/completions")
async def chat(request: Request):
    _stats["req"] += 1
    if not _auth_ok(request):
        _stats["auth_reject"] += 1
        return _err(401, "authentication_error", "桥鉴权失败")
    try:
        body = await request.json()
    except Exception:
        return _err(400, "invalid_request_error", "请求体不是合法 JSON")
    async with _get_sem():
        return await _chat_loop(body)


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "bridge"}
                                        for m in sorted(config.allowed_models())]}


@app.get("/health")
async def health():
    s = guard.lease_snapshot()
    up = "未配置" if not config.pool_key() else "已配置"
    return PlainTextResponse(
        f"桥在线 | 请求 {_stats['req']} | 聊天 {_stats['ok_chat']} | 工具 {_stats['ok_tool']} | "
        f"修复 {_stats['repair']} | 强制无调用 {_stats['forced_nocall']} | "
        f"桥拒 {_stats['bridge_reject']} | 上游错 {_stats['upstream_err']} | "
        f"鉴权拒 {_stats['auth_reject']} | 池密钥 {up} | 活动租约 {len(s)} | "
        f"运行 {int(time.time()-_stats['since'])}s | {cooldown.status_line()}")


@app.get("/stats")
async def stats(format: str = "text"):
    if format == "json":
        return JSONResponse({"stats": _stats, "leases": guard.lease_snapshot(),
                             "cooldown": cooldown.snapshot()})
    s = guard.lease_snapshot()
    lines = [f"协议桥统计 — 启动以来 {int(time.time()-_stats['since'])}s",
             f"  {_stats['req']} 请求 | 聊天 {_stats['ok_chat']} | 工具调用 {_stats['ok_tool']} | "
             f"修复重试 {_stats['repair']} | 桥拒 {_stats['bridge_reject']} | 上游错 {_stats['upstream_err']}",
             f"  强制无调用（c4/c5）：{_stats['forced_nocall']} —— 客户端 tool_choice=any/required/具名，"
             f"但修复阶梯用尽仍无任何封套（网页后端硬上限，桥不伪造调用）",
             f"  {cooldown.status_line()}",
             "", "▸ 活动任务租约（15分钟窗口）"]
    for fp, e in sorted(s.items(), key=lambda kv: -kv[1]["forwards"])[:10]:
        lines.append(f"  {fp}  推理 {e['forwards']}  工具轮 {e['toolrounds']}  "
                     f"已用 {int(time.time()-e['t0'])}s")
    if not s:
        lines.append("  （无）")
    return PlainTextResponse("\n".join(lines))


audit.prune()
