#!/usr/bin/env bash
# 2026-06-06: Linux/macOS 同时启动前后端。会在后台启动后端，再启动前端；退出时自动停止后端。
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[SmartHorse] 启动后端..."
bash "$ROOT/start_backend.sh" &
BACKEND_PID=$!

cleanup() {
  echo "[SmartHorse] 停止后端进程 $BACKEND_PID"
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 2
echo "[SmartHorse] 启动前端..."
bash "$ROOT/start_frontend.sh"
