"""
TestForge AI 驱动模块
====================

支持 8 个 AI 厂商的调用:
- Claude (Anthropic)
- OpenAI GPT
- Google Gemini
- DeepSeek
- 阿里 Qwen
- Moonshot Kimi
- MiniMax
- 本地模型 (Ollama)

工具调用模式 (参考 AutoQA-Agent):
- 定义工具规范 (snapshot, navigate, click, fill, etc.)
- LLM 决定调用哪个工具
- Ref-First: 先获取页面快照，再执行操作
"""

# 从子模块导出
from .agent import AIAgent, TOOLS, Tool, build_tools_description
from .client import (
    AIClient,
    ClaudeClient,
    OpenAIClient,
    LocalClient,
    GeminiClient,
    DeepSeekClient,
    QwenClient,
    KimiClient,
    MiniMaxClient,
    create_ai_client,
    check_api_key,
)
from .config import AIConfig

__all__ = [
    # Agent
    "AIAgent",
    "TOOLS",
    "Tool",
    "build_tools_description",
    # Config
    "AIConfig",
    # Clients
    "AIClient",
    "ClaudeClient",
    "OpenAIClient",
    "LocalClient",
    "GeminiClient",
    "DeepSeekClient",
    "QwenClient",
    "KimiClient",
    "MiniMaxClient",
    "create_ai_client",
    "check_api_key",
]