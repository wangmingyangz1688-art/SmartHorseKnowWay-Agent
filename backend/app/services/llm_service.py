"""LLM服务模块"""

import threading
from hello_agents import HelloAgentsLLM
from ..config import get_settings

# 全局LLM实例
_llm_instance = None
_llm_lock = threading.Lock()


def get_llm() -> HelloAgentsLLM:
    global _llm_instance

    if _llm_instance is None:
        with _llm_lock:
            if _llm_instance is None:
                settings = get_settings()
                _llm_instance = HelloAgentsLLM()

                print(f"[OK] LLM服务初始化成功")  # 2026-06-03 修复：emoji 编码
                print(f"   提供商: {_llm_instance.provider}")
                print(f"   模型: {_llm_instance.model}")

    return _llm_instance


def reset_llm():
    global _llm_instance
    with _llm_lock:
        _llm_instance = None
