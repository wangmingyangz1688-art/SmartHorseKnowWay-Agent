#!/usr/bin/env bash
# 2026-06-06: Linux/macOS 后端一键启动脚本，只负责启动服务；依赖安装交给 setup.sh。
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "[SmartHorse] Backend root: $BACKEND"

if [ ! -f "$BACKEND/.env" ]; then
  echo "[SmartHorse] backend/.env missing. Run ./setup.sh first, then fill API keys."
  exit 1
fi

if [ ! -x "$PYTHON" ]; then
  echo "[SmartHorse] backend/.venv missing. Run ./setup.sh first."
  exit 1
fi

echo "[SmartHorse] 启动后端：http://127.0.0.1:8000"
cd "$BACKEND"
"$PYTHON" run.py
