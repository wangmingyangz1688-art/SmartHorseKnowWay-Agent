#!/usr/bin/env bash
# 2026-06-06: Linux/macOS 首次配置脚本，复制环境模板、创建后端虚拟环境并安装前后端依赖。
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "[SmartHorse] 项目根目录: $ROOT"

if [ ! -f "$BACKEND/.env" ]; then
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  echo "[SmartHorse] 已生成 backend/.env，请稍后填写 LLM、AMAP、Neo4j 配置。"
else
  echo "[SmartHorse] backend/.env 已存在，跳过复制。"
fi

if [ ! -f "$FRONTEND/.env" ]; then
  cp "$FRONTEND/.env.example" "$FRONTEND/.env"
  echo "[SmartHorse] 已生成 frontend/.env，请稍后填写高德 Web JS Key。"
else
  echo "[SmartHorse] frontend/.env 已存在，跳过复制。"
fi

if [ ! -x "$PYTHON" ]; then
  echo "[SmartHorse] 创建 Python 虚拟环境..."
  python3 -m venv "$VENV"
fi

echo "[SmartHorse] 安装/更新后端依赖..."
"$PIP" install -r "$BACKEND/requirements.txt"

echo "[SmartHorse] 安装/更新前端依赖..."
cd "$FRONTEND"
npm install

echo ""
echo "[SmartHorse] 首次配置完成。下一步："
echo "  1. 编辑 backend/.env，填写 LLM_API_KEY、LLM_BASE_URL、LLM_MODEL_ID、AMAP_API_KEY。"
echo "  2. 编辑 frontend/.env，填写 VITE_AMAP_WEB_JS_KEY。"
echo "  3. 如需 Neo4j，启动 Neo4j Desktop 并在 backend/.env 设置 NEO4J_ENABLED=true。"
echo "  4. 运行 ./start_all.sh 启动本地服务。"
