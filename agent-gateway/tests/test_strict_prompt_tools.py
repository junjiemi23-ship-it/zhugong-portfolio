# -*- coding: utf-8 -*-
"""strict 修复提示工具清单对齐的离线回归（2026-09-28 P4 复跑）。

背景：P4 复跑暴露 3 条 WRONG_TOOL——首轮剪枝提示只列目标工具（Grep/Read），
但旧代码 strict 重发传的是【全量 4 工具】，模型遂挑 Bash → 语义选错。
修法：strict 分支改用 prompt_tools。本测试证明：
  (1) 目标工具被剪枝选中（prune 命中 Grep）；
  (2) 拒答后 strict 重发的 system 里【只列 Grep、不再暴露 Bash/Read】；
  (3) 模型据新提示回 Grep → 桥正确产出 tool_use(Grep)。
全部 mock 上游，不发网络。运行：
  bridge 目录下  .venv/Scripts/python.exe -m pytest tests/test_strict_prompt_tools.py -q --basetemp=.tmp/pytest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

import cooldown
import guard
import protocol
import upstream

BASH = {"name": "Bash", "description": "run shell", "input_schema":
        {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}
READ = {"name": "Read", "description": "read file", "input_schema":
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}
GREP = {"name": "Grep", "description": "search file contents for a pattern",
        "input_schema": {"type": "object",
                         "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                         "required": ["pattern"]}}


def _env(name: str, params: str = '{"pattern": "foo"}') -> str:
    return protocol.T_OPEN + protocol.C_OPEN + protocol.N_OPEN + name + protocol.N_CLOSE \
        + protocol.P_OPEN + params + protocol.P_CLOSE \
        + protocol.C_CLOSE + protocol.T_CLOSE


# 实测最高频拒答句式（含弯引号），须命中 REFUSAL_RE → need=True → 触发修复
_REFUSAL = "I can’t access your local machine in this chat environment, so I can’t run that search."


@pytest.fixture(autouse=True)
def _envfix(monkeypatch, tmp_path):
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
        return r, {"prompt_tokens": 10, "completion_tokens": 8}, 0.1, "chatcmpl-fake"
    monkeypatch.setattr(upstream, "call_upstream", fake)
    return calls


def _client():
    import server
    return TestClient(server.app)


def _body(user, **kw):
    b = {"model": "gpt-5-5", "max_tokens": 1000,
         "system": "You are ZCode agent.",
         "messages": [{"role": "user", "content": user}],
         "tools": [BASH, READ, GREP], "tool_choice": "auto"}
    b.update(kw)
    return b


def test_prune_selects_grep_for_search_task():
    """前置事实：'search ... inside dir' 被剪枝命中 Grep（否则本修法无靶子）。"""
    picked = protocol.prune("Search for the word foo inside C:/chatgpt2api/services/")
    assert picked == "Grep", picked


def test_strict_retry_prompt_lists_only_pruned_tool(monkeypatch):
    """拒答 → strict 重发的 system 只列 Grep，不再暴露 Bash/Read；模型据新提示回 Grep。"""
    calls = _mock(monkeypatch, [_REFUSAL, _env("Grep")])
    r = _client().post("/v1/messages", json=_body(
        "Search for the word foo inside C:/chatgpt2api/services/"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert len(calls) == 2, "首轮拒答应触发一次 strict 修复"
    assert j["stop_reason"] == "tool_use"
    tu = [b for b in j["content"] if b["type"] == "tool_use"]
    assert len(tu) == 1 and tu[0]["name"] == "Grep", f"修复后应产出 Grep，实得 {[t['name'] for t in tu]}"

    sys1 = calls[0]["messages"][0]["content"]
    sys2 = calls[1]["messages"][0]["content"]
    # 首轮与 strict 轮都应只暴露 Grep（与 prune 一致），不得把 Bash/Read 摆出来诱导误选
    for tag, s in (("首轮", sys1), ("strict", sys2)):
        assert "- Grep(" in s, f"{tag}提示未列出目标工具 Grep"
        assert "- Bash(" not in s, f"{tag}提示不应暴露 Bash（正是 WRONG_TOOL 根因）"
        assert "- Read(" not in s, f"{tag}提示不应暴露 Read"
    assert "STRICT RETRY" in sys2, "第二轮应是 strict 附加段"


def test_full_whitelist_still_parses_other_tool(monkeypatch):
    """安全网：parse 白名单仍是全量 tools——模型即便吐合法 Bash 也不被误杀为畸形（只是判为选错）。"""
    calls = _mock(monkeypatch, [_env("Bash", '{"command": "ls"}')])
    r = _client().post("/v1/messages", json=_body(
        "Search for the word foo inside C:/chatgpt2api/services/"))
    j = r.json()
    # 模型硬吐 Bash（提示没给但仍合法）→ 桥按全量白名单接受为 tool_use(Bash)，不报 malformed
    assert j["stop_reason"] == "tool_use"
    tu = [b for b in j["content"] if b["type"] == "tool_use"]
    assert len(tu) == 1 and tu[0]["name"] == "Bash"
