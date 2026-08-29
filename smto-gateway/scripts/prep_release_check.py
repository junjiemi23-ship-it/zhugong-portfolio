#!/usr/bin/env python3
"""发布前安全检查：扫描目录里的敏感信息与垃圾文件。
用法: python scripts/prep_release_check.py [目录=当前目录]
适合在 `git push` 前跑一遍，确认不会把 key/token/日志/临时文件推上去。
"""
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

PATTERNS = [
    re.compile(r"\b(sk-[A-Za-z0-9]{16,})\b"),
    re.compile(r"\b(nvapi-[A-Za-z0-9]{16,})\b"),
    re.compile(r"\b(gsk_[A-Za-z0-9]{16,})\b"),
    re.compile(r"\b(api[_-]?key\s*[=:]\s*['\"][A-Za-z0-9]{16,})", re.IGNORECASE),
    re.compile(r"\b(Authorization:\s*(Bearer\s+)?[A-Za-z0-9._-]{16,})"),
    re.compile(r"\b(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
    re.compile(r"\b(Bearer\s+[A-Za-z0-9._-]{20,})"),
]

SKIP_DIRS = {".venv", "__pycache__", ".git", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
JUNK = {"router.log", "router.err.log", "kill8124.ps1", ".router.pid"}
SUSPICIOUS_NAME = re.compile(r"(key|token|secret|credential|password)", re.IGNORECASE)

hits, junk, suspects = [], [], []

for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, ROOT)
        if fn in JUNK:
            junk.append(rel)
        if SUSPICIOUS_NAME.search(fn):
            suspects.append(rel)
        try:
            if os.path.getsize(full) > 200_000:
                continue
            with open(full, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for p in PATTERNS:
                if p.search(line):
                    hits.append(f"{rel}:{i}: {line.strip()[:120]}")
                    break

print("=== 敏感信息命中 ===")
for h in hits:
    print(h)
print(f"({len(hits)} 处)")

print("\n=== 垃圾/临时文件 ===")
for j in junk:
    print(j)
print(f"({len(junk)} 个)")

print("\n=== 可疑文件名（需人工确认）===")
for s in suspects:
    print(s)
print(f"({len(suspects)} 个)")

if not hits and not junk and not suspects:
    print("\n干净，可直接发布")
else:
    print("\n需清理后再发布")
    sys.exit(1)
