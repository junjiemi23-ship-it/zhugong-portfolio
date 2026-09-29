# -*- coding: utf-8 -*-
"""JSONL 脱敏审计：参数/结果只记 hash+长度+首尾片段；不记完整对话；按天滚动+保留天数。"""
import hashlib
import json
import os
import time

import config


def _frag(s: str, keep: int = 64) -> str:
    s = str(s or "")
    if len(s) <= keep * 2:
        return s
    return s[:keep] + "…" + s[-keep:]


def _h(s: str) -> str:
    return hashlib.sha256(str(s or "").encode("utf-8", "replace")).hexdigest()[:16]


def emit(event: str, **fields) -> None:
    try:
        d = config.log_dir()
        os.makedirs(d, exist_ok=True)
        now = time.time()
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "ev": event}
        for k, v in fields.items():
            if k in ("params", "result"):
                s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                rec[k + "_hash"] = _h(s)
                rec[k + "_len"] = len(s)
                rec[k + "_frag"] = _frag(s)
            else:
                rec[k] = v
        path = os.path.join(d, f"audit-{time.strftime('%Y%m%d', time.localtime(now))}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 审计失败绝不影响热路径


def prune() -> None:
    try:
        d = config.log_dir()
        cutoff = time.time() - config.audit_keep_days() * 86400
        for fn in os.listdir(d):
            if fn.startswith("audit-") and fn.endswith(".jsonl"):
                p = os.path.join(d, fn)
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
    except Exception:
        pass
