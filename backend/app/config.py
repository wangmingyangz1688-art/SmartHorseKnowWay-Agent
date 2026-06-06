"""配置管理模块 - 本地活动规划与执行Agent"""

import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量
# 首先尝试加载当前目录的.env
load_dotenv()

# 然后尝试加载HelloAgents的.env(如果存在)
helloagents_env = Path(__file__).parent.parent.parent.parent / "HelloAgents" / ".env"
if helloagents_env.exists():
    load_dotenv(helloagents_env, override=False)  # 不覆盖已有的环境变量


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str = "本地活动规划助手"
    app_version: str = "1.0.0"
    debug: bool = False

    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS配置 - 使用字符串,在代码中分割
    cors_origins: str = "http://localhost:8888,http://localhost:3000,http://127.0.0.1:8888,http://127.0.0.1:3000"

    # 高德地图API配置
    amap_api_key: str = ""

    # LLM配置 (从环境变量读取,由HelloAgents管理)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4"

    # Mock 服务配置
    mock_success_rate: float = 0.9  # Mock 操作默认成功率 (0.0~1.0)
    mock_max_queue: int = 15        # Mock 排队最大组数
    mock_delivery_base_min: int = 30  # Mock 配送基础时间(分钟)

    # 2026-06-04: Neo4j 图谱记忆配置，未配置或未启动时不影响主流程
    neo4j_enabled: bool = False
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # 日志配置
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的环境变量

    def get_cors_origins_list(self) -> List[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(',')]


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


# 验证必要的配置
def validate_config():
    """验证配置是否完整"""
    errors = []
    warnings = []

    if not settings.amap_api_key:
        errors.append("AMAP_API_KEY未配置 — 场所搜索、天气查询等功能将不可用")

    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not llm_api_key:
        warnings.append("LLM_API_KEY或OPENAI_API_KEY未配置,LLM功能可能无法使用")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        print("\n[WARN] 配置警告:")  # 2026-06-03 修复：emoji 编码
        for w in warnings:
            print(f"  - {w}")

    return True


# 打印配置信息(用于调试)
def print_config():
    """打印当前配置(隐藏敏感信息)"""
    # 2026-06-03 修复：Windows emoji 编码崩溃，替换为纯文本
    print(f"\n[CONFIG] 应用配置:")
    print(f"  应用名称: {settings.app_name}")
    print(f"  版本: {settings.app_version}")
    print(f"  服务器: {settings.host}:{settings.port}")
    print(f"  调试模式: {settings.debug}")
    print(f"  高德地图API Key: {'[OK] 已配置' if settings.amap_api_key else '[ERR] 未配置'}")

    # 检查LLM配置
    llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    llm_base_url = os.getenv("LLM_BASE_URL") or settings.openai_base_url
    llm_model = os.getenv("LLM_MODEL_ID") or settings.openai_model

    print(f"  LLM API Key: {'[OK] 已配置' if llm_api_key else '[ERR] 未配置'}")  # 2026-06-03 修复：emoji 编码
    print(f"  LLM Base URL: {llm_base_url}")
    print(f"  LLM Model: {llm_model}")

    # Mock 服务配置
    print(f"  Mock成功率: {settings.mock_success_rate:.0%}")
    print(f"  Mock最大排队: {settings.mock_max_queue}组")
    print(f"  Mock配送基础时间: {settings.mock_delivery_base_min}分钟")
    print(f"  Neo4j图谱记忆: {'[ON] 已启用' if settings.neo4j_enabled else '[OFF] 未启用'}")
    if settings.neo4j_enabled:
        print(f"  Neo4j URI: {settings.neo4j_uri}")
        print(f"  Neo4j Database: {settings.neo4j_database}")

    print(f"  日志级别: {settings.log_level}")
