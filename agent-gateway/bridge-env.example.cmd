@echo off
rem ============================================================================
rem  Agent Gateway Protocol Bridge - example launcher (Windows)
rem  Copy this file to bridge-env.cmd and fill in the placeholders. NEVER commit
rem  your real key: bridge-env.cmd is gitignored; only this example is tracked.
rem
rem  KEEP THIS FILE PURE ASCII. cmd's OEM codepage mis-decodes non-ASCII (e.g.
rem  Chinese) comments and can swallow the following line - a UTF-8 remark once
rem  ate a newline and silently turned the next `set` into part of the comment.
rem
rem  PYTHONUNBUFFERED=1 : tracebacks flush immediately, so a hard kill cannot
rem                       lose evidence.
rem  pythonw (no console): the bridge is not killed by console-close or a stray
rem                       Ctrl+C in another window of the same console session.
rem ============================================================================
set PYTHONUNBUFFERED=1

rem --- REQUIRED: your own upstream. The bridge ships no account and proxies none. ---
rem Key for your web-reverse pool / OpenAI-face upstream. Leave empty if it needs none.
set BRIDGE_WEBPOOL_KEY=<YOUR_UPSTREAM_KEY>
rem Upstream base URL (OpenAI face). Default is http://localhost:3000/v1
set BRIDGE_UPSTREAM=http://localhost:3000/v1

rem --- Auth for the bridge itself ---
rem Empty = loopback trust (fine for localhost-only). SET THIS before exposing the
rem bridge beyond 127.0.0.1, otherwise anyone who reaches the URL burns your quota.
set BRIDGE_TOKEN=

rem --- Model whitelist (comma-separated). Persist it here or the bridge falls back
rem     to the config.py default on every restart. ---
set BRIDGE_MODELS=auto,gpt-5-5,gpt-5-6,gpt-5-5-instant

rem --- Optional tuning (uncomment to override defaults; see README config table) ---
rem set BRIDGE_EMPTY_RETRY=1
rem set BRIDGE_REPAIR_MAX=2
rem set BRIDGE_PRUNE=on
rem set BRIDGE_PREFILL=on
rem set BRIDGE_CD=on

rem --- Launch ---
rem cd to the bridge dir (the folder holding server.py). Adjust if you placed it
rem elsewhere; keep it machine-independent by deriving from this script's location.
cd /d "%~dp0"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "_d=%%i"
start "agent-bridge" /b ".venv\Scripts\pythonw.exe" -m uvicorn server:app --host 127.0.0.1 --port 3460 --app-dir "%~dp0" >> "logs\bridge-server-%_d%.log" 2>&1
