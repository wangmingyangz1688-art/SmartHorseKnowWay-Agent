#!/usr/bin/env bash
# 2026-06-06: Linux/macOS 前端一键启动脚本，只负责启动服务；依赖安装交给 setup.sh。
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$ROOT/frontend"

echo "[SmartHorse] Frontend root: $FRONTEND"

if [ ! -f "$FRONTEND/.env" ]; then
  echo "[SmartHorse] frontend/.env missing. Run ./setup.sh first, then fill AMap Web JS key."
  exit 1
fi

cd "$FRONTEND"
if [ ! -d "node_modules" ]; then
  echo "[SmartHorse] frontend/node_modules missing. Run ./setup.sh first."
  exit 1
fi

echo "[SmartHorse] 启动前端"
npm run dev
