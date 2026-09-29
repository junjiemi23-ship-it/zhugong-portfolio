# -*- coding: utf-8 -*-
"""空正文重发兜底的离线回归测试（2026-09-28 P4 复盘）。

背景：结果回填轮 / 闲聊轮偶发上游返回 200 但 completion_tokens=0（正文空），
旧逻辑因 need=False 直接把空白助手消息发给客户端 → 多轮 NOT_GROUNDED。
新逻辑：no-call 且 visible_text 为空 → 换 nonce 原样重发，最多 BRIDGE_EMPTY_RETRY 次。

全部 mock 上游，不发网络。运行：
  bridge 目录下  .venv/Scripts/python.exe -m pytest tests/test_empty_retry.py -q --basetemp=.tmp/pytest
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

import cooldown
import guard
import upstream

BASH = {"name": "Bash", "description": "run shell", "input_schema":
        {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}
READ = {"name": "Read", "description": "read file", "input_schema":
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}

_NONCE_RE = re.compile(r"bridge-nonce:\s*([0-9a-f]+)")


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("BRIDGE_WEBPOOL_KEY", "test-key")
    monkeypatch.setenv("BRIDGE_TOKEN", "")
    monkeypatch.setenv("BRIDGE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("BRIDGE_BUDGET_TOKENS", "12000")
    monkeypatch.setenv("BRIDGE_LEASE_WINDOW", "900")
    monkeypatch.setenv("BRIDGE_LEASE_FORWARDS", "36")
    monkeypatch.setenv("BRIDGE_LEASE_TOOLROUNDS", "12")
    monkeypatch.setenv("BRIDGE_SPIN_LIMIT", "3")
    monkeypatch.setenv("BRIDGE_REPAIR_MAX", "2")
    monkeypatch.setenv("BRIDGE_EMPTY_RETRY", "1")
    monkeypatch.setenv("BRIDGE_CD_STATE", str(tmp_path / "cd.json"))
    guard._lease.clear()
    guard._spin.clear()
    cooldown.reset()
    yield


def _mock(monkeypatch, replies):
    calls = []

    def fake(model, messages, max_tokens):
        import copy as _copy
        calls.append({"model": model, "messages": _copy.deepcopy(messages), "max_tokens": max_tokens})
        r = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(r, Exception):
            raise r
        return r, {"prompt_tokens": 10, "completion_tokens": len(r)}, 0.1, "chatcmpl-fake"
    monkeypatch.setattr(upstream, "call_upstream", fake)
    return calls


def _client():
    import server
    return TestClient(server.app)


def _body(user="list files please", **kw):
    b = {"model": "gpt-5-5", "max_tokens": 1000,
         "system": "You are ZCode agent.",
         "messages": [{"role": "user", "content": user}],
         "tools": [BASH, READ], "tool_choice": "auto"}
    b.update(kw)
    return b


_RESULT_HIST = [
    {"role": "user", "content": "list files in C:/tmp"},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_x1",
                                       "name": "Bash", "input": {"command": "dir C:/tmp"}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_x1",
                                  "content": "SENTINEL_abc", "is_error": False}]},
]


def _nonces(calls):
    out = []
    for c in calls:
        sysmsg = c["messages"][0]["content"]
        m = _NONCE_RE.search(sysmsg)
        out.append(m.group(1) if m else None)
    return out


def test_result_turn_empty_completion_retried(monkeypatch):
    """回填轮空正文 → 重发一次拿到散文，客户端得到非空回复、不贴未验证标注。"""
    calls = _mock(monkeypatch, ["", "结果里有 SENTINEL_abc，共 1 个标记。"])
    r = _client().post("/v1/messages", json=_body(user="ignored", messages=_RESULT_HIST))
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(calls) == 2, "空正文应触发一次原样重发"
    assert j["stop_reason"] == "end_turn"
    txt = j["content"][0]["text"]
    assert txt.strip(), "重发成功后不得返回空白"
    assert not txt.startswith("[bridge]"), "回填轮不得贴未验证标注"
    # 重发须换 nonce（破池子缓存），否则会回放同一个空响应
    ns = _nonces(calls)
    assert ns[0] != ns[1], f"重发未换 nonce：{ns}"


def test_chat_empty_completion_retried(monkeypatch):
    """闲聊轮空正文同样重发恢复。"""
    calls = _mock(monkeypatch, ["", "2+2=4"])
    r = _client().post("/v1/messages", json=_body(user="what is 2+2?"))
    j = r.json()
    assert len(calls) == 2
    assert j["content"][0]["text"] == "2+2=4"
    assert j["stop_reason"] == "end_turn"


def test_empty_retry_capped_no_loop(monkeypatch):
    """持续空正文时受 BRIDGE_EMPTY_RETRY 封顶，绝不无限循环。"""
    monkeypatch.setenv("BRIDGE_EMPTY_RETRY", "1")
    calls = _mock(monkeypatch, ["", "", ""])
    r = _client().post("/v1/messages", json=_body(user="ignored", messages=_RESULT_HIST))
    assert r.status_code == 200
    # 初始 1 次 + 空重发 1 次 = 2 次；不会因持续空而无限重试
    assert len(calls) == 2, f"空重发未按上限封顶：{len(calls)}"


def test_empty_retry_disabled(monkeypatch):
    """BRIDGE_EMPTY_RETRY=0 关闭兜底 → 空正文不重发（对照开关生效）。"""
    monkeypatch.setenv("BRIDGE_EMPTY_RETRY", "0")
    calls = _mock(monkeypatch, ["", "本不该被调用"])
    r = _client().post("/v1/messages", json=_body(user="ignored", messages=_RESULT_HIST))
    assert r.status_code == 200
    assert len(calls) == 1, "开关关闭时不应重发"


def test_valid_reply_not_retried(monkeypatch):
    """有效回复不得被误判为空而重发（保护既有单调用行为，如 T4 回填轮不强制修复）。"""
    calls = _mock(monkeypatch, ["目录里有 a.txt 和 b.txt 两个文件。", "NEVER"])
    r = _client().post("/v1/messages", json=_body(user="ignored", messages=_RESULT_HIST))
    j = r.json()
    assert len(calls) == 1, "非空回复不应触发空重发"
    assert j["stop_reason"] == "end_turn"
