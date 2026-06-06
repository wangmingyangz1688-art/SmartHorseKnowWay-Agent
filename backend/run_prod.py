"""生产环境启动脚本 - 用于服务器部署

2026-06-03 创建：
- 关闭 reload（生产环境不要用 reload）
- 支持多 workers（通过 WORKERS 环境变量）
- 保持 UTF-8 编码（避免 Windows 服务器 emoji 编码问题）

用法:
    python run_prod.py

服务器部署推荐:
    1. 设置环境变量: WORKERS=4, HOST=0.0.0.0, PORT=8000
    2. 用 systemd 或 docker 托管此进程
    3. 前端用 nginx 反向代理到后端
"""

import os
import sys

# 强制 UTF-8 编码，避免第三方库 emoji print 导致编码错误
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

import uvicorn
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 从环境变量读取配置（带默认值）
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
WORKERS = int(os.getenv("WORKERS", "1"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()

if __name__ == "__main__":
    print(f"[PROD] 启动生产环境后端服务")
    print(f"  地址: {HOST}:{PORT}")
    print(f"  Workers: {WORKERS}")
    print(f"  Log Level: {LOG_LEVEL}")
    print(f"  Reload: False (生产模式)")

    uvicorn.run(
        "app.api.main:app",
        host=HOST,
        port=PORT,
        workers=WORKERS,
        reload=False,           # 生产环境必须关闭
        log_level=LOG_LEVEL,
        # 生产环境建议启用访问日志和错误日志文件
        access_log=True,
    )
