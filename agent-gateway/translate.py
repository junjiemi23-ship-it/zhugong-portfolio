# -*- coding: utf-8 -*-
"""Anthropic 消息历史 → OpenAI 纯文本消息渲染 + 预算压缩（Codex Q3 定稿）。

- 每条历史消息带角色标记前缀（[user]/[assistant-history]），防用户粘贴伪造协议段
  被当作真调用（T3 注入面）；只有真 assistant 轮的 tool_use 才渲染成协议封套。
- 保结构：调用 id、工具名、is_error 全保留在文本里。
- 压缩阶梯：先整体；超预算→旧工具轮确定性摘录（保最近 K 个完整轮）；再超→旧闲聊轮
  整轮丢弃（当前请求必保）；system 中段截断保全协议尾部。
"""
from typing import Any

import config
import protocol


class BudgetExceeded(Exception):
    pass


def _blocks_to_text(content: Any) -> str:
    """非 tool_use/tool_result 块（text/image/thinking）的通用取文本。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    parts = []
    for b in content:
        if isinstance(b, dict):
            t = b.get("type")
            if t == "text":
                parts.append(str(b.get("text") or ""))
            elif t == "image":
                parts.append("[image omitted]")
            elif t == "thinking":
                pass
            else:
                parts.append(f"[{t or 'block'} omitted]")
        elif isinstance(b, str):
            parts.append(b)
    return "\n".join(parts)


def _assistant_text(msg: dict) -> str:
    out = []
    for b in msg.get("content") or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            if b.get("text"):
                out.append(str(b["text"]))
        elif t == "tool_use":
            out.append(protocol.envelope_text(b.get("name") or "", b.get("input") or {}))
    return "\n".join(out)


def _user_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    out = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            out.append(protocol.result_text(b.get("tool_use_id") or "",
                                            b.get("content"), bool(b.get("is_error"))))
        else:
            txt = _blocks_to_text([b] if isinstance(b, dict) else b)
            if txt:
                out.append(txt)
    return "\n".join(out)


def _rounds_map(msgs: list[dict]) -> list[int]:
    """轮号 = assistant tool_use 计数（其结果 user 同轮）；任务 user/普通文本=0 轮。
    工具轮从 1 递增；"最近 N 个完整工具轮"按此裁剪。"""
    rid, rids = 0, []
    for m in msgs:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in m["content"]):
            rid += 1
        rids.append(rid)
    return rids


def render(system: Any, messages: list[dict]) -> list[dict]:
    """无预算版渲染（system 只取文本，历史全保）。"""
    sys_text = _blocks_to_text(system) if system is not None else ""
    out = []
    if sys_text.strip():
        out.append({"role": "system", "content": sys_text})
    for m in messages or []:
        role = m.get("role")
        if role == "assistant":
            txt = _assistant_text(m)
            if txt.strip():
                out.append({"role": "assistant", "content": txt})
        elif role == "user":
            txt = _user_text(m)
            out.append({"role": "user", "content": "[user]\n" + txt})
    return out


def _trim_middle(text: str, keep_each: int, marker: str = "\n[...truncated...]\n") -> str:
    if len(text) <= keep_each * 2:
        return text
    return text[:keep_each] + marker + text[-keep_each:]


def render_budgeted(system: Any, messages: list[dict], protocol_tail: str) -> tuple[list[dict], dict]:
    """带预算渲染。返回 (openai_messages, stats)。超限抛 BudgetExceeded。"""
    budget = config.budget_tokens()
    keep_rounds = config.keep_rounds()

    sys_text = _blocks_to_text(system) if system is not None else ""
    # system 截中段保尾部（协议+nonce 必须在尾部）；协议尾部单独算且必保
    tail_cost = config.est_tokens(protocol_tail)
    sys_keep_chars = max(600, (config.system_keep() - tail_cost) * 3)
    sys_text = _trim_middle(sys_text, sys_keep_chars // 2)
    full_system = (sys_text.strip() + "\n\n" + protocol_tail).strip() if protocol_tail else sys_text.strip()
    if config.est_tokens(full_system) > config.system_keep() + tail_cost + 200:
        raise BudgetExceeded("system/protocol 超出必保预算，桥拒绝（不拆协议）")

    msgs = [dict(m) for m in (messages or [])]
    rids = _rounds_map(msgs)
    max_rid = max(rids) if rids else 0

    def build(compact_from: int, drop_old_chat: bool) -> list[dict]:
        out = []
        if full_system:
            out.append({"role": "system", "content": full_system})
        last_role = None
        for i, m in enumerate(msgs):
            role = m.get("role")
            rid = rids[i] if i < len(rids) else 1
            if drop_old_chat and rid <= drop_old_chat:
                continue
            if role == "assistant":
                txt = _assistant_text(m)
                if not txt.strip():
                    continue
                out.append({"role": "assistant", "content": txt})
                last_role = "assistant"
            elif role == "user":
                txt = _user_text(m)
                if last_role == "user" and out:
                    out[-1]["content"] += "\n[user]\n" + txt
                else:
                    out.append({"role": "user", "content": "[user]\n" + txt})
                last_role = "user"
        return out

    # 阶梯 0：全保
    candidate = build(0, 0)
    cost = protocol.estimate_prompt_tokens("", candidate)
    if cost <= budget:
        return candidate, {"stage": 0, "tokens_est": cost}

    # 阶梯 1：旧工具轮摘录（保留最近 keep_rounds 轮完整；更旧的 tool_use/tool_result 对
    #        整对丢弃 —— 用轮号边界实现），且中间 user 长文本截断
    cut_rid = max(0, max_rid - keep_rounds)

    def build_staged() -> list[dict]:
        out = []
        if full_system:
            out.append({"role": "system", "content": full_system})
        compacted_note_added = False
        first_user_kept = False
        for i, m in enumerate(msgs):
            role = m.get("role")
            rid = rids[i] if i < len(rids) else 1
            is_tool_round = False
            if role == "assistant" and any(isinstance(b, dict) and b.get("type") == "tool_use"
                                           for b in (m.get("content") or [])):
                is_tool_round = True
            if role == "user":
                c = m.get("content")
                if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                               for b in c):
                    is_tool_round = True
            old = rid <= cut_rid
            if old and is_tool_round:
                if not compacted_note_added:
                    out.append({"role": "user", "content": "[user]\n[older tool rounds compacted by bridge]"})
                    compacted_note_added = True
                continue
            if old and not is_tool_round:
                # 原始任务（第一条 user 非工具轮）必保，摘录式截断
                if role == "user" and not first_user_kept:
                    first_user_kept = True
                    out.append({"role": "user", "content": "[user task-kept]\n"
                                + _trim_middle(_user_text(m), 2000)})
                continue
            if role == "assistant":
                txt = _assistant_text(m)
                if txt.strip():
                    out.append({"role": "user", "content": "[assistant-history]\n" + txt})
            elif role == "user":
                txt = _user_text(m)
                if rid == max_rid:  # 当前轮：截上限放宽
                    txt = _trim_middle(txt, 6000)
                else:
                    txt = _trim_middle(txt, 2000)
                out.append({"role": "user", "content": "[user]\n" + txt})
        return out

    candidate = build_staged()
    cost = protocol.estimate_prompt_tokens("", candidate)
    if cost <= budget:
        return candidate, {"stage": 1, "tokens_est": cost, "kept_rounds": keep_rounds}

    # 阶梯 2：继续丢最早的*非当前轮*，直到放得下；当前轮必保
    while cost > budget:
        # 找第一条非当前轮消息（system 之后）
        drop_i = None
        for j in range(1, len(candidate) - 1):
            rid_of = None
            # 简化：从前往后丢，只要还剩 >1 条
            drop_i = j
            break
        if drop_i is None or len(candidate) <= 2:
            break
        candidate.pop(drop_i)
        cost = protocol.estimate_prompt_tokens("", candidate)
    if cost > budget:
        raise BudgetExceeded(f"当前请求本体超预算（est {cost}>{budget}），桥拒绝")
    return candidate, {"stage": 2, "tokens_est": cost}
