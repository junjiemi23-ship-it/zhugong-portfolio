#!/usr/bin/env bash
# 一键安装 Harness Smart Router 依赖（uv 环境）
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROUTER_DIR="$SKILL_DIR/router"

echo "[install] Using uv to sync dependencies..."
cd "$SKILL_DIR"

# 如果没有 pyproject.toml，创建一个最小的
if [[ ! -f pyproject.toml ]]; then
    cat > pyproject.toml <<'EOF'
[project]
name = "harness-smart-router"
version = "1.0.0"
description = "Smart model router for browser-use harness"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.32",
    "httpx>=0.28",
    "watchfiles>=1.0",
    "python-dotenv>=1.0",
]
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

# 纯依赖项目：只装依赖，不构建安装自身包（避免 flat-layout 构建问题）
[tool.uv]
package = false
EOF
fi

uv sync --frozen 2>/dev/null || uv sync

echo "[install] Verifying imports..."
uv run python -c "
from router import (
    app, ROUTE_CANDIDATES, GLOBAL_FALLBACK,
    detect_task_type, select_candidate, call_provider, health_check
)
print('All imports OK')
"

echo "[install] Done. Run with: uv run python -m router.harness_router"