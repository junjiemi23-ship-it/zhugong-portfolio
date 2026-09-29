# -*- coding: utf-8 -*-
"""文本冷却账本（池级）。

为什么需要：池子（chatgpt2api 系）的「限流」状态只记生图配额，文本用量不记账
（openai_backend_api.py::get_user_info 只取 image_gen 的 remaining，见
local-web-pool-api.md「账号调度真实机制」）。上游真文本限流时本地账本看不见，
客户端会在限流窗口内继续打请求——正是加剧风控的行为。

代理信号：上游 timeout / net / 5xx / 429。连续到阈值 → 进入随机时长冷却窗口，
期间 call_upstream 直接 fast-fail，不向上游发请求。窗口到期自动解除并清零，
重新学习。

范围=池级：OpenAI 面响应不含账号 id，无法按账号归因（P3 多号分散态再升级为账号级）。
状态持久化到 JSON，桥重启不丢失冷却窗口。
"""
import json
import os
import random
import threading
import time

import config

_lock = threading.Lock()
_cd = None  # 惰性加载：{"consecutive": int, "until": float|None, "engaged": int, "blocks": int}


def _now():
    return time.time()


def _ensure():
    global _cd
    if _cd is None:
        _cd = {"consecutive": 0, "until": None, "engaged": 0, "blocks": 0}
        try:
            with open(config.cd_state(), "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                _cd["consecutive"] = int(d.get("consecutive") or 0)
                _cd["until"] = float(d["until"]) if d.get("until") else None
                _cd["engaged"] = int(d.get("engaged") or 0)
                _cd["blocks"] = int(d.get("blocks") or 0)
        except Exception:
            pass  # 无文件/损坏 → 全新状态
    return _cd


def _persist():
    try:
        p = config.cd_state()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cd, f)
        os.replace(tmp, p)
    except Exception:
        pass  # 持久化失败不阻断冷却判断（内存态仍权威）


def reset():
    """清空内存与磁盘状态（测试隔离用）。"""
    global _cd
    with _lock:
        _cd = {"consecutive": 0, "until": None, "engaged": 0, "blocks": 0}
        try:
            os.remove(config.cd_state())
        except OSError:
            pass


def is_blocked() -> bool:
    if not config.cd_enabled():
        return False
    with _lock:
        s = _ensure()
        u = s["until"]
        if u is None:
            return False
        if _now() < u:
            s["blocks"] += 1
            _persist()
            return True
        # 窗口到期：自动解除并清零，重新学习
        s["until"] = None
        s["consecutive"] = 0
        _persist()
        return False


def record_success():
    """成功清零连续计数（池级：当前态任一成功即说明池子在服务）。"""
    if not config.cd_enabled():
        return
    with _lock:
        s = _ensure()
        if s["consecutive"]:
            s["consecutive"] = 0
            _persist()


def record_failure(kind: str) -> bool:
    """记录一次失败。返回 True = 冷却刚刚触发（调用方应立即停止重试，别加剧限流）。

    kind=rate（429 显式限流信号）→ 立即触发；
    其他（timeout/net/5xx 代理信号）→ 累计到阈值触发。
    """
    if not config.cd_enabled():
        return False
    with _lock:
        s = _ensure()
        if kind == "rate":
            just = True
        else:
            s["consecutive"] += 1
            just = s["consecutive"] >= config.cd_threshold()
        if just:
            lo, hi = config.cd_min_sec(), config.cd_max_sec()
            win = random.uniform(lo, hi) if hi > lo else lo
            s["until"] = _now() + win
            s["engaged"] += 1
            s["consecutive"] = 0
            _persist()
        return just


def snapshot() -> dict:
    with _lock:
        s = _ensure()
        u = s["until"]
        return {
            "enabled": config.cd_enabled(),
            "blocked": u is not None and _now() < u,
            "until": u,
            "remaining_s": max(0, int(u - _now())) if u else 0,
            "consecutive": s["consecutive"],
            "threshold": config.cd_threshold(),
            "engaged": s["engaged"],
            "blocks": s["blocks"],
        }


def status_line() -> str:
    s = snapshot()
    if not s["enabled"]:
        return "文本冷却[关]"
    if s["blocked"]:
        return f"文本冷却中 剩{s['remaining_s']}s 已触发{s['engaged']}次 拦截{s['blocks']}次"
    return f"文本冷却待机 {s['consecutive']}/{s['threshold']}"
