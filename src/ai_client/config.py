"""
AI 配置模块
===========

AIConfig 类定义
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class AIConfig:
    """AI 配置"""
    provider: str = "claude"  # "claude", "openai", "gemini", "deepseek", "qwen", "kimi", "minimax", "local"
    model: str = "claude-3-5-sonnet-20241022"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> "AIConfig":
        """从环境变量创建配置"""
        provider = os.environ.get("TF_AI_PROVIDER", "claude")

        config = cls(provider=provider)

        if provider == "claude":
            config.api_key = os.environ.get("ANTHROPIC_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "claude-3-5-sonnet-20241022")
        elif provider == "openai":
            config.api_key = os.environ.get("OPENAI_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "gpt-4o")
            config.base_url = os.environ.get("TF_AI_BASE_URL")
        elif provider == "gemini":
            config.api_key = os.environ.get("GOOGLE_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "gemini-2.0-flash")
        elif provider == "deepseek":
            config.api_key = os.environ.get("DEEPSEEK_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "deepseek-chat")
        elif provider == "qwen":
            config.api_key = os.environ.get("DASHSCOPE_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "qwen-turbo")
        elif provider == "kimi":
            config.api_key = os.environ.get("MOONSHOT_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "moonshot-v1-8k")
        elif provider == "minimax":
            config.api_key = os.environ.get("MINIMAX_API_KEY")
            config.model = os.environ.get("TF_AI_MODEL", "abab6-chat")
        elif provider == "local":
            config.base_url = os.environ.get("LOCAL_MODEL_URL", "http://localhost:11434")
            config.model = os.environ.get("TF_AI_MODEL", "llama3")

        return config


__all__ = ["AIConfig"]