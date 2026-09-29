# -*- coding: utf-8 -*-
"""防线（Codex Q4/Q5/Q8 定稿）：
- 任务租约：按 system 指纹滚动窗口，封顶 12 工具轮/36 次推理/15 分钟；
- 空转检测：同(工具名+规范化参数+结果hash) 连续 3 次 → 断；
- 修复重试梯度：普通 → 严格附加段 → 带失败原因；≤ repair_max 次；
- tool_choice 语义：none 不注入协议；required/指定工具强制调用；auto 仅"行动请求"触发修复。
"""
import hashlib
import json
import re
import threading
import time

import config

_lock = threading.Lock()
_lease: dict[str, dict] = {}
_spin: dict[str, int] = {}


def _fp(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()[:16]


def lease_fingerprint(system_text: str, first_user: str) -> str:
    """稳定任务标识：协议前 system 原文 + 首条用户文本。跨 nonce 更新不变。"""
    sys_wo_nonce = re.sub(r"(?m)^bridge-nonce:.*$", "", system_text or "")
    return _fp((sys_wo_nonce + "\n" + (first_user or ""))[:4000])


class LeaseExceeded(Exception):
    pass


def lease_check_and_count(fp: str, kind: str) -> dict:
    """kind: forward|toolround。forward=一次上游推理；toolround=合成了一次真调用。"""
    now = time.time()
    win = config.lease_window_s()
    with _lock:
        e = _lease.get(fp)
        if not e or now - e["t0"] > win:
            e = {"t0": now, "forwards": 0, "toolrounds": 0}
            _lease[fp] = e
        if kind == "forward":
            if e["forwards"] >= config.lease_max_forwards():
                raise LeaseExceeded(f"任务推理次数封顶 {config.lease_max_forwards()}（{int(win)}s 窗口），已拒绝——请开新会话")
            if e["toolrounds"] >= config.lease_max_toolrounds():
                raise LeaseExceeded(f"任务工具轮封顶 {config.lease_max_toolrounds()}（{int(win)}s 窗口），已拒绝")
            e["forwards"] += 1
        else:
            e["toolrounds"] += 1
        return dict(e)


def lease_snapshot() -> dict:
    now = time.time()
    with _lock:
        return {fp: {k: v for k, v in e.items()}
                for fp, e in _lease.items() if now - e["t0"] <= config.lease_window_s()}


def note_call_result(fp: str, name: str, params: dict, result_text: str) -> None:
    """空转检测：同参数同结果连续 N 次即抛。ZCode 若卡住反复跑同一命令，桥强制止损。"""
    sig = _fp(name + json.dumps(params, sort_keys=True, ensure_ascii=False) + (result_text or "")[:2000])
    with _lock:
        key = fp + ":" + sig
        _spin[key] = _spin.get(key, 0) + 1
        n = _spin[key]
    if n >= config.spin_limit():
        with _lock:
            _spin.pop(key, None)
        raise LeaseExceeded(f"检测到空转：同一工具+参数+结果连续 {n} 次，桥已熔断该任务")


ACTION_RE = re.compile(
    r"(?i)(跑|执行|运行|列出|查看|读一下|读[取]?\s|打开文件|查一下|查[看询]|搜索|找一下|"
    r"改一下|修改|写入|写一个|保存|删除|git |ls |cat |grep |python |node |npm |dir |powershell|"
    r"run |list |read |write |edit |create |check |search |show (?:me|the) |what files|which files|"
    r"how many |first \d+ lines|directory|folder|file)")
    # 2026-09-28 P4 复盘补漏：原表缺 search/show the/how many lines/first N lines，
    # 导致这类行动请求 is_action_request=False → 拒答时修复阶梯不触发（att=0，4/6 失败）。
    # 新增项均收窄到文件/命令语义，已离线核对不误伤 20 条闲聊样本（见 tests/test_refusal_regression.py）。


def is_action_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(ACTION_RE.search(t))


# 干净拒答识别（2026-09-25 实测缺口）：模型以"散文拒答"回应工具请求时，parse 抓不到封套、
# 也不算 malformed，旧逻辑直接当 chat 返回 → 客户端看到纯文本而非 tool_use，感官偏离官方。
# 只匹配"提及工具+否定/无能力"的组合，避免误伤 legitimately 不调工具的普通回答。
REFUSAL_RE = re.compile(
    r"(?i)(?:\b(?:tool|tools)\b[^.\n!]{0,80}?\b(?:isn'?t|is not|are not|not)\s+(?:available|provided|enabled|supported)|"
    r"\b(?:tool|tools)\b[^.\n!]{0,40}?\b(?:unavailable|missing|absent)\b|"
    r"I['’]?m unable to (?:access|retrieve|use|run|execute|call|invoke)|"
    r"I (?:can['’]?t|cannot) (?:access|use|run|execute|call|invoke)[^.\n!]{0,60}?\btool\b|"
    r"\bno (?:such |available )?tool\b|"
    r"tool (?:execution|calling|use) is (?:unavailable|not available|disabled)|"
    r"without (?:a |the |any )?(?:available )?tool|"
    # 2026-09-28 P4 复盘补漏：实测最高频拒答是"无法访问你的本机/本地文件"，句中常不含 "tool" 一词，
    # 旧规则全部漏判 → looks_like_refusal=False → 修复阶梯不触发。新增"访问否认 + 本机/本地对象"组合，
    # 收窄到 machine/filesystem/local/file/directory/tool，避免误伤闲聊正常散文答复。
    r"(?:can['’]?t|cannot|could not|couldn['’]?t|unable to|no access to|don['’]?t|do not|doesn['’]?t|does not)\s+"
    r"(?:have\s+)?(?:access|reach)\b[^.\n!]{0,50}?(?:local machine|your machine|my machine|the machine|"
    r"local filesystem|local file system|local files?|local director|your local|the local|local `?[A-Za-z]|"
    r"filesystem|file system)|"
    r"(?:if you run this|run (?:this|it) (?:on|in) your (?:machine|pc|computer)|paste the[^.\n!]{0,30}contents|"
    r"(?:can['’]?t|cannot|could not|couldn['’]?t|unable to|won['’]?t|am unable to)[^.\n!]{0,60}?(?:from|in) this chat|"
    r"in this chat (?:environment|session|context)[^.\n!]{0,40}?(?:can['’]?t|cannot|unable|no access|don['’]?t))|"
    r"无法(?:调用|使用|执行|访问)[^。\n！]{0,24}工具|"
    r"工具(?:不可用|不存在|未提供|无法使用)|"
    r"没有(?:可用)?工具)")


def looks_like_refusal(text: str) -> bool:
    """回复是否为"提及工具但拒绝/声称无工具"的散文拒答（用于触发修复重试）。"""
    t = (text or "").strip()
    if not t:
        return False
    return bool(REFUSAL_RE.search(t))


def result_present(messages: list) -> bool:
    """当前轮是否已是"工具结果回填轮"：末尾 user 消息只含 tool_result（无新指令文本）。
    此情形下 auto 不强制修复（Codex Q5：仅"明确行动请求+本机对象+缺成功结果"才触发）。"""
    for m in reversed(messages or []):
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list) and c:
            has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
            has_text = any(isinstance(b, dict) and b.get("type") == "text" and str(b.get("text") or "").strip()
                           for b in c)
            return bool(has_result and not has_text)
        return False
    return False


def is_forced(force: str) -> bool:
    """force 是否来自客户端的显式强制（tool_choice=any/required/具名工具）。

    与"桥自己推断的行动请求"区分开：后者失败只是没触发调用，前者失败意味着
    客户端已经明说"必须调工具"而桥交不出 —— 这是需要单独计数的诊断信号
    （Jev c4/c5：网页后端不从 assistant 前缀真正续写，弱工具先验形状属硬上限）。
    """
    f = str(force or "")
    return f == "any" or f.startswith("named:")


def tool_choice_policy(tool_choice) -> tuple[bool, str]:
    """返回 (inject: bool, force: none|any|named:<x>)。"""
    if tool_choice in (None, "auto"):
        return True, "none"
    if tool_choice == "none":
        return False, "none"
    if tool_choice == "any" or tool_choice == "required":
        return True, "any"
    if isinstance(tool_choice, dict):
        # Anthropic 字典形态：{"type":"any"}/{"type":"required"} 语义=必须调用，映射 force any
        # （2026-09-25 实测缺口：旧代码只认字符串 any/required，字典 any 落到 force none，
        #  干净拒答不进修复阶梯 → 客户端拿不到 tool_use）。
        if tool_choice.get("type") in ("any", "required"):
            return True, "any"
        nm = tool_choice.get("name") or (tool_choice.get("function") or {}).get("name") or ""
        if tool_choice.get("type") in ("tool", "function") and nm:
            return True, "named:" + str(nm)
    return True, "none"
