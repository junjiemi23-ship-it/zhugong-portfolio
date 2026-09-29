# -*- coding: utf-8 -*-
"""拒答回归集（2026-09-28 P4 门槛批复盘沉淀）。

背景：P4 全量批首轮合规 51/57=89%（< 95% 门槛），6 个失败全是模型拒答，其中 4 个
att=0——桥的修复阶梯根本没触发。根因不是"模型救不回"，而是检测门漏判：
  - ACTION_RE 缺 search / show the / how many lines / first N lines；
  - REFUSAL_RE 只认 ASCII 撇号（模型实际输出弯引号 can’t），且漏"无法访问本机"高频句式。
本测试把当时真实失败样本钉死，防止以后改正则/提示词时静默回退。

运行：bridge 目录下  .venv/Scripts/python.exe -m pytest tests/test_refusal_regression.py -q
全部离线，不碰网络、不烧配额。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import guard


# ---- P4 实测真实拒答复文（取自 p4-full-0927.jsonl，弯引号为模型原样输出）----
REFUSALS = [
    "I can’t access your local machine or run the requested `Grep` tool in this chat "
    "environment, so I can’t search `C:/chatgpt2api/services/protocol/` directly.",
    "I can’t run `git status` on `C:/chatgpt2api` from this chat because the local machine "
    "tool required to execute it isn’t available here.",
    "I can’t access your local machine in this chat environment, so I can’t determine the "
    "line count of `C:/chatgpt2api/main.py` directly. If you run this on your machine it "
    "will give the answer.",
    "I can’t access your local machine or read `C:/chatgpt2api/docker-compose.yml` from this "
    "chat environment. If you paste the file contents I can explain them.",
    "I don’t have access to the local `Grep` tool in this chat environment, so I can’t "
    "inspect `C:/chatgpt2api/services/protocol/` or verify matches.",
    "I can’t access your local machine in this chat session because the required local "
    "filesystem tool isn’t reachable from here.",
]

# ---- P4 实测曾被 ACTION_RE 漏判、导致 att=0 的行动任务 ----
MISSED_ACTIONS = [
    "Search for the word 'tool_calls' inside C:/chatgpt2api/services/protocol/.",
    "How many lines are in C:/chatgpt2api/main.py?",
    "Show the first 5 lines of C:/chatgpt2api/docker-compose.yml.",
    "Read C:/chatgpt2api/pyproject.toml and list the dependencies.",
    "Find all files named VERSION under C:/chatgpt2api.",
    "Show me the size of C:/chatgpt2api/data/accounts.json.",
]

# ---- 闲聊/讲解任务：不得被新增正则误判为"行动请求"（门槛：闲聊误触发=0）----
# 注：以下 5 条含 list/write/python/git/file 等通用词，是改动前就存在的既有匹配，
# 冒烟已证明不会造成假触发（模型对闲聊仍散文作答）。本测试锁定"既有集合不得增长"。
KNOWN_CHAT_MATCHES = {
    "What's the difference between a list and a tuple in Python?",
    "Write a haiku about autumn.",
    "What year did Python 3.0 come out?",
    "Name two common git workflows.",
    "What is the purpose of a README file?",
}
CHAT_TASKS = [
    "What is 17 * 23?",
    "Explain in one sentence what an HTTP 429 status code means.",
    "Translate 'good morning' into Chinese.",
    "Summarize what an OpenAI-compatible API is in two sentences.",
    "What's the difference between a list and a tuple in Python?",
    "Give me a one-line definition of idempotency.",
    "Write a haiku about autumn.",
    "What year did Python 3.0 come out?",
    "Explain what an API gateway does, briefly.",
    "Two truths and a lie about SQL, one line each.",
    "What is the capital of France?",
    "Explain the difference between TCP and UDP in one sentence.",
    "What does the acronym JSON stand for?",
    "Give me three tips for writing clear commit messages.",
    "Explain what a semaphore is in one sentence.",
    "What is 0.1 + 0.2 in floating point, and why?",
    "Name two common git workflows.",
    "What is the purpose of a README file?",
    "Explain 'cache invalidation' in one sentence.",
    "Tell me a short joke about programmers.",
]

# ---- 正常散文答复：不得被误判为拒答（否则闲聊会被推进修复阶梯）----
NORMAL_PROSE = [
    "The capital of France is Paris.",
    "17 * 23 = 391.",
    "HTTP 429 means Too Many Requests — the client sent too many requests.",
    "A list is mutable and a tuple is immutable.",
    "JSON stands for JavaScript Object Notation.",
    "Autumn wind whispers through the empty field.",
    "A semaphore is a counter that controls access to a shared resource.",
    "git rebase and git merge are two common workflows.",
    "0.1 + 0.2 gives 0.30000000000000004 because of IEEE 754 binary rounding.",
]


@pytest.mark.parametrize("text", REFUSALS)
def test_real_refusals_detected(text):
    """P4 实测拒答句式必须被 looks_like_refusal 命中，才能触发修复阶梯。"""
    assert guard.looks_like_refusal(text), f"漏判拒答: {text[:60]}"


@pytest.mark.parametrize("task", MISSED_ACTIONS)
def test_missed_actions_now_detected(task):
    """P4 曾 att=0 漏判的行动任务，现在 is_action_request 必须为 True。"""
    assert guard.is_action_request(task), f"漏判行动请求: {task[:60]}"


@pytest.mark.parametrize("text", NORMAL_PROSE)
def test_normal_prose_not_refusal(text):
    """正常散文答复不得被误判为拒答。"""
    assert not guard.looks_like_refusal(text), f"误伤散文: {text[:60]}"


def test_chat_false_positive_set_does_not_grow():
    """闲聊被误判为行动请求的集合不得超出既有基线（防新增正则扩大误伤面）。"""
    matched = {c for c in CHAT_TASKS if guard.is_action_request(c)}
    new = matched - KNOWN_CHAT_MATCHES
    assert not new, f"新增闲聊误判（会威胁闲聊误触发=0 门槛）: {new}"


def test_refusal_does_not_fire_on_chat_answers():
    """闲聊的正常答复一律不算拒答——保证闲聊不会被推进修复阶梯。"""
    for text in NORMAL_PROSE:
        assert not guard.looks_like_refusal(text)
