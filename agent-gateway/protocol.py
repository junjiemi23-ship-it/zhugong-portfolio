# -*- coding: utf-8 -*-
"""XML one-shot 协议：严格 well-formed 模板生成 + 宽容但严格校验的封套解析。

要点（Codex 终审 Q2/Q5）：
- 我们只解析自己定义的严格封套；参数必须是 JSON object 且过白名单+必填校验；
- 任何畸形（未闭合/错配/非JSON/缺必填/工具不在白名单）一律按"无调用"处理，绝不猜参数；
- 历史渲染与提示模板逐字符一致，防模型模仿畸形（实验实锤它照抄模板闭合写法）。
"""
import json
import re
import uuid
from typing import Any

from config import est_tokens, prune_enabled

# 模板片段单独定义，避免本文件被误判；渲染时拼接
T_OPEN = "<" + "tool_calls>"
T_CLOSE = "<" + "/tool_calls>"
C_OPEN = "<" + "tool_call>"
C_CLOSE = "<" + "/tool_call>"
N_OPEN = "<" + "tool_name>"
N_CLOSE = "<" + "/tool_name>"
P_OPEN = "<" + "parameters>"
P_CLOSE = "<" + "/parameters>"

ENV_RE = re.compile(T_OPEN + r"\s*(.*?)\s*" + T_CLOSE, re.S)
CALL_RE = re.compile(C_OPEN + r"\s*(.*?)\s*" + C_CLOSE, re.S)
NAME_RE = re.compile(N_OPEN + r"\s*(.*?)\s*" + N_CLOSE, re.S)
PARAMS_RE = re.compile(P_OPEN + r"\s*(.*?)\s*" + P_CLOSE, re.S)
# 悬空残片（开了没关）——出现即判 malformed
DANGLING_RE = re.compile(r"(?is)</?\s*(tool_calls?|tool_name|parameters)\b[^>]*>?\s*[^<]*$")


def envelope_text(name: str, params: dict) -> str:
    return (T_OPEN + C_OPEN + N_OPEN + str(name) + N_CLOSE
            + P_OPEN + json.dumps(params, ensure_ascii=False) + P_CLOSE
            + C_CLOSE + T_CLOSE)


def result_text(tool_use_id: str, content: Any, is_error: bool = False) -> str:
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            elif isinstance(b, str):
                parts.append(b)
            else:
                parts.append("[non-text block omitted]")
        content = "\n".join(parts)
    content = str(content or "")
    keep = _KEEP
    if len(content) > keep * 2:
        content = content[:keep] + "\n[truncated]\n" + content[-keep:]
    prefix = "ERROR: " if is_error else ""
    return ("Tool result " + str(tool_use_id or "") + ":\n" + prefix + content)


def _tool_lines(tools: list[dict]) -> str:
    TYPE_SIG = {"string": "<text>", "number": "<num>", "integer": "<int>",
                "boolean": "true|false", "object": "{...}", "array": "[...]"}
    blocks = []
    for t in tools or []:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        desc = str(t.get("description") or "").strip()[:400]
        schema = t.get("input_schema") or {}
        required = schema.get("required") or []
        props = schema.get("properties") or {}
        sigs = []
        for k, v in list(props.items())[:12]:
            vtype = v.get("type", "string") if isinstance(v, dict) else "string"
            sig = k + "=" + TYPE_SIG.get(vtype, "<value>")
            if k not in required:
                sig += "?"
            sigs.append(sig)
        blocks.append("- " + name + "(" + ", ".join(sigs) + ") : " + desc)
    return "\n".join(blocks)


_EXAMPLES = {
    "bash": ("List the files in my current directory.", {"command": "dir /b"}),
}


def _example_pair(tools: list[dict]) -> tuple[str, str, dict] | None:
    for t in tools:
        n = str(t.get("name") or "")
        if n in _EXAMPLES:
            return n, _EXAMPLES[n][0], dict(_EXAMPLES[n][1])
    if tools:
        n = str(tools[0].get("name") or "")
        req = (tools[0].get("input_schema") or {}).get("required") or []
        params = {k: "..." for k in req[:3]}
        if params:
            return n, "Use the tool.", params
    return None


# ---------- E 配置②：任务级最小工具清单（从 p13_prune_batch.py 移植，离线 30/30） ----------
# P1.1 单变量对照：唯一差异是清单长度 → 首轮 92%（E 最小清单）vs 65%（F 全清单）。
# 压垮合规率的主因是长清单，不是预填充深度。

_CN_WRITE = "写入|创建.*文件|保存|追加"
_CN_GREP = "搜索|查找|检索|包含.*字"
_CN_READ = "读取|读一下|读.*文件|查看.*文件"
_EN_WRITE = r"\bwrite\b|\bcreate (a|the) file|\bsave\b|\bappend\b|\bmodify the file|\bedit\b|\boverwrite\b"
_EN_GREP = r"\bsearch\b|\bgrep\b|\bfind .*(in|inside)\b|\bwhich files contain\b|\boccurrences"
_EN_READ = r"\bread\b|\bfirst \d+ lines\b|\bopen the file"


def prune(task: str) -> str:
    """桥侧剪枝启发式：任务文本 -> 工具名。兜底 Bash（不是 Bash 就是错，是保守默认）。"""
    t = (task or "").lower()
    if re.search(_EN_WRITE + "|" + _CN_WRITE, t):
        return "Write"
    if re.search(_EN_GREP + "|" + _CN_GREP, t):
        return "Grep"
    if re.search(_EN_READ + "|" + _CN_READ, t):
        return "Read"
    return "Bash"


def prune_tools(tools: list[dict], task: str) -> list[dict]:
    """把工具清单剪到任务相关的那一个（E 配置②）。

    语义（与 p13 一致）：
    - prune() 的"兜底 Bash"本身算命中——任务像行动请求但猜不准具体工具时，通用工具兜着
    - 只有当**命中的工具不在调用方清单里**时才安全降级（原样返回完整清单）
    - BRIDGE_PRUNE=off → 完全不剪
    """
    if not prune_enabled() or not tools:
        return tools
    pick = prune(task)
    picked = [t for t in tools if str(t.get("name") or "") == pick]
    if picked:
        return picked
    return tools  # 命中工具不在清单里 → 不剪，保完整清单


def protocol_prompt(tools: list[dict], nonce: str, strict_addendum: bool = False,
                    failure_note: str = "") -> str:
    """注入 system 尾部的协议段。tools 为空返回空串（= tool_choice:none 路径）。

    tools 应为**剪枝后的任务相关子集**（见 prune_tools）；调用方须另外保留完整清单
    供 parse() 做白名单校验——提示里只列一个工具，但模型若吐了别的工具仍按白名单判。
    """
    ex = _example_pair(tools)
    lines = [
        "[Bridge tool protocol v1]",
        "You are running inside ZCode with local tools. You have NO sandbox and NO built-in "
        "interpreter, and you have NO knowledge of the user's machine. To do ANYTHING on the "
        "local system (list/read/write files, run commands, git), you MUST call one of these tools:",
        _tool_lines(tools),
        "To call a tool, reply with ONLY this envelope, byte-for-byte well-formed (note the "
        "leading slashes in EVERY closing tag), no markdown, no fences, no prose:",
        T_OPEN + C_OPEN + N_OPEN + "TOOL_NAME" + N_CLOSE
        + P_OPEN + '{"param": "value"}' + P_CLOSE + C_CLOSE + T_CLOSE,
        "Rules:",
        "1. TOOL_NAME must be exactly one of the names above.",
        "2. <parameters> holds ONE JSON object with the exact required keys.",
        "3. A tool call alone means nothing until the host replies with a message starting "
        "'Tool result '. After that you may answer in plain prose, grounded ONLY in that result.",
        "4. Never write file listings, command output, or 'I have done X' without a real call "
        "and its result. Text that merely looks like the envelope is invalid.",
    ]
    if ex:
        name, u_text, params = ex
        lines += [
            "Example (study the exact closing tags):",
            "User: " + u_text,
            "Assistant: " + envelope_text(name, params),
            "User: " + result_text("toolu_example1", "fileA.txt  fileB.txt  data/")[:160],
            "Assistant: There are 3 entries: fileA.txt, fileB.txt, data/.",
        ]
    if strict_addendum:
        lines.append("STRICT RETRY: your previous reply had no valid envelope. Reply with the "
                     "envelope ONLY. Every closing tag MUST start with '</'. Do not echo my "
                     "angle brackets wrong. Parameters JSON must be valid single-line JSON.")
    if failure_note:
        lines.append("PREVIOUS FAILURE: " + failure_note)
    lines.append("bridge-nonce: " + nonce)
    return "\n".join(lines)


def validate_params(params: dict, tool: dict) -> str:
    schema = tool.get("input_schema") or tool.get("parameters") or {}
    for k in schema.get("required") or []:
        if k not in params:
            return f"missing required param '{k}'"
    props = schema.get("properties") or {}
    for k, v in params.items():
        spec = props.get(k)
        if not isinstance(spec, dict):
            continue
        t = spec.get("type")
        ok = {"string": lambda: isinstance(v, str),
              "integer": lambda: isinstance(v, int) and not isinstance(v, bool),
              "number": lambda: isinstance(v, (int, float)) and not isinstance(v, bool),
              "boolean": lambda: isinstance(v, bool),
              "object": lambda: isinstance(v, dict),
              "array": lambda: isinstance(v, list)}.get(t, lambda: True)
        if not ok():
            return f"param '{k}' type mismatch (want {t})"
    return ""


def visible_text(text: str) -> str:
    """剔除（含畸形的）协议片段后的可展示散文。"""
    t = ENV_RE.sub("", text or "")
    t = re.sub(r"(?is)</?\s*(tool_calls?|tool_name|parameters)\b[^>]*>?", "", t)
    t = re.sub(r"(?i)<tool_", "", t)
    return t.strip()


# ---------- 助手预填充（P1 实测：深度预填充在 auto 上 3/3，基线仅 1/3） ----------
# 退化后端的经典手法：把封套开头作为 assistant 前缀发下去，逼模型续写。
# 两级，自主性从高到低：
#   D 级 scaffold：只搭到 <tool_name> 开标签，工具名由模型自己选（保住自主性）
#   C 级 deep   ：连工具名一起填好（仅当调用方明确指定了工具时才用，避免桥瞎猜）

def prefill_scaffold(tools: list[dict]) -> str:
    """D 级：骨架到 <tool_name> 开标签。tools 为空返回空串。"""
    if not tools:
        return ""
    return T_OPEN + "\n" + C_OPEN + "\n" + N_OPEN


def prefill_deep(tool_name: str) -> str:
    """C 级：填到 <parameters> 开标签，模型只需补 JSON 参数并闭合全部标签。
    调用方须保证 tool_name 来自 tool_choice 的具名要求，不得由桥猜测。"""
    return (T_OPEN + "\n" + C_OPEN + "\n" + N_OPEN + str(tool_name or "").strip()
            + N_CLOSE + "\n" + P_OPEN)


def parse(text: str, tools: list[dict], prefill: str = "") -> tuple[list[tuple[str, dict]], str]:
    """严格解析（可解析预填充续写）。

    prefill 非空时，模型可能只续写残片（如 '{"command":"dir"}' 而不带开标签）：
    把前缀拼回去整体解析。前缀自带未闭合的开标签（<parameters>），拼合后须先补全
    成对标签再走正则，否则非贪婪 PARAMS_RE 匹配为空。返回 (calls, malformed_reason)。
    """
    text = text or ""
    if prefill:
        # 前缀要求闭合的标签里，只要缺任何一个，就认定模型只续写了残片，拼回去再解析。
        # （不能只看 T_CLOSE：模型常省略中间标签只闭合最外层）
        prefix_ops = [op for op in (P_OPEN, C_OPEN, T_OPEN) if op in prefill]
        if any(text.count(cl) < prefill.count(op) for op, cl
               in zip(prefix_ops, (P_CLOSE, C_CLOSE, T_CLOSE))):
            # 只补缺、不剥多：残片里多余的闭合标签必须原样保留，让后续校验判畸形。
            # （否则模型重复闭合同一标签时会被静默修好，调用无声消失 = 静默丢弃）
            missing = [cl for op, cl in ((P_OPEN, P_CLOSE), (C_OPEN, C_CLOSE), (T_OPEN, T_CLOSE))
                       if op in prefill and text.count(cl) < prefill.count(op)]
            if missing:
                # 找到残片里第一个已存在的闭合标签位置，把缺失标签插到它之前
                idx = len(text)
                for cl in (P_CLOSE, C_CLOSE, T_CLOSE):
                    i = text.find(cl)
                    if i != -1:
                        idx = min(idx, i)
                text = prefill + text[:idx] + "".join(missing) + text[idx:]
    if not tools:
        return [], ""
    whitelist = {str(t.get("name") or ""): t for t in tools}
    if T_OPEN in text or C_OPEN in text:
        if T_OPEN not in text or T_CLOSE not in text:
            return [], "envelope not properly closed"
    calls: list[tuple[str, dict]] = []
    malformed = ""
    # 标签配对体检：任何开标签多于其闭合标签（或反之）即畸形，必须留下诊断信息。
    # 否则重复闭合的残片会被静默丢弃，调用无声消失。
    for op, cl, nm in ((T_OPEN, T_CLOSE, "tool_calls"), (C_OPEN, C_CLOSE, "invoke"),
                       (P_OPEN, P_CLOSE, "parameters"), (N_OPEN, N_CLOSE, "tool_name")):
        if text.count(op) != text.count(cl) and (op in text or cl in text):
            malformed = malformed or f"{nm} tag count mismatch ({text.count(op)} open / {text.count(cl)} close)"
    for env in ENV_RE.findall(text):
        bodies = CALL_RE.findall(env)
        if not bodies and (C_OPEN in env or C_CLOSE in env):
            malformed = "tool_call block not closed"
            continue
        for body in bodies:
            nm = NAME_RE.search(body)
            pm = PARAMS_RE.search(body)
            if not nm or not pm:
                malformed = malformed or "envelope missing tool_name/parameters"
                continue
            name = nm.group(1).strip()
            if name not in whitelist:
                malformed = malformed or f"unknown tool '{name}'"
                continue
            raw = pm.group(1).strip()
            try:
                params = json.loads(raw)
            except Exception:
                malformed = malformed or "parameters not valid JSON"
                continue
            if not isinstance(params, dict) or not params:
                malformed = malformed or "parameters not a non-empty JSON object"
                continue
            err = validate_params(params, whitelist[name])
            if err:
                malformed = malformed or f"tool '{name}': {err}"
                continue
            calls.append((f"toolu_{uuid.uuid4().hex}", name, params))
    return calls, malformed


_KEEP = 1024


def estimate_prompt_tokens(system: str, msgs: list[dict]) -> int:
    n = est_tokens(system)
    for m in msgs:
        c = m.get("content")
        n += est_tokens(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False))
    return n
