"""启动脚本"""

import os
import sys

# 2026-06-03 修复：Windows 控制台默认 gbk 编码无法输出 emoji
# 第三方库 hello_agents 的 protocol_tools.py 中有 emoji print 语句
# 强制 stdout/stderr 使用 utf-8 编码
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # Python < 3.7 无此方法

import uvicorn
from dotenv import load_dotenv
load_dotenv()

# 确保触发补丁
import app

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()

    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower()
    )