"""
AI 客户端模块
=============

支持 8 个 AI 厂商:
- Claude (Anthropic)
- OpenAI GPT
- Google Gemini
- DeepSeek
- 阿里 Qwen
- Moonshot Kimi
- MiniMax
- 本地模型 (Ollama)
"""

import os
from typing import Optional

from .config import AIConfig


# ==================== AI 客户端 ====================

class AIClient:
    """AI 客户端基类"""

    def __init__(self, config: AIConfig):
        self.config = config

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """完成对话"""
        raise NotImplementedError


class ClaudeClient(AIClient):
    """Claude AI 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 Claude API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("需要设置 ANTHROPIC_API_KEY 环境变量")

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "assistant", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"Claude API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["content"][0]["text"]


class OpenAIClient(AIClient):
    """OpenAI GPT 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 OpenAI API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("需要设置 OPENAI_API_KEY 环境变量")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        base_url = self.config.base_url or "https://api.openai.com/v1"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"OpenAI API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]


class LocalClient(AIClient):
    """本地模型客户端 (Ollama 等)"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用本地模型"""
        import httpx

        base_url = self.config.base_url or "http://localhost:11434"
        model = self.config.model or "llama3"

        data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"本地模型错误: {response.status_code}")

        result = response.json()
        return result.get("response", "")


class GeminiClient(AIClient):
    """Google Gemini 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 Gemini API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("需要设置 GOOGLE_API_KEY 环境变量")

        headers = {
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "user", "parts": [{"text": f"[System] {system}"}]})
        messages.append({"role": "user", "parts": [{"text": prompt}]})

        data = {
            "contents": messages,
            "generationConfig": {
                "maxOutputTokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent?key={api_key}",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"Gemini API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]


class DeepSeekClient(AIClient):
    """DeepSeek 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 DeepSeek API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("需要设置 DEEPSEEK_API_KEY 环境变量")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"DeepSeek API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]


class QwenClient(AIClient):
    """阿里通义千问 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 Qwen API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("需要设置 DASHSCOPE_API_KEY 环境变量")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.config.model,
            "input": {"messages": messages},
            "parameters": {
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            },
        }

        base_url = self.config.base_url or "https://dashscope.aliyuncs.com"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{base_url}/api/v1/services/aigc/text-generation/generation",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"Qwen API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["output"]["text"]


class KimiClient(AIClient):
    """Moonshot Kimi 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 Kimi API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("MOONSHOT_API_KEY")
        if not api_key:
            raise ValueError("需要设置 MOONSHOT_API_KEY 环境变量")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"Kimi API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]


class MiniMaxClient(AIClient):
    """MiniMax 客户端"""

    async def complete(self, prompt: str, system: Optional[str] = None) -> str:
        """调用 MiniMax API"""
        import httpx

        api_key = self.config.api_key or os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError("需要设置 MINIMAX_API_KEY 环境变量")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.config.model,
            "messages": messages,
            "max_output_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.minimax.chat/v1/text/chatcompletion_v2",
                headers=headers,
                json=data,
            )

        if response.status_code != 200:
            raise Exception(f"MiniMax API 错误: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]


def create_ai_client(config: Optional[AIConfig] = None) -> AIClient:
    """创建 AI 客户端"""
    if config is None:
        config = AIConfig.from_env()

    if config.provider == "claude":
        return ClaudeClient(config)
    elif config.provider == "openai":
        return OpenAIClient(config)
    elif config.provider == "gemini":
        return GeminiClient(config)
    elif config.provider == "deepseek":
        return DeepSeekClient(config)
    elif config.provider == "qwen":
        return QwenClient(config)
    elif config.provider == "kimi":
        return KimiClient(config)
    elif config.provider == "minimax":
        return MiniMaxClient(config)
    elif config.provider == "local":
        return LocalClient(config)
    else:
        raise ValueError(f"未知 AI provider: {config.provider}")


# ==================== 便捷函数 ====================

def check_api_key():
    """检查 API key 是否设置"""
    # 检查所有支持的 API key
    keys = {
        "claude": os.environ.get("ANTHROPIC_API_KEY"),
        "openai": os.environ.get("OPENAI_API_KEY"),
        "gemini": os.environ.get("GOOGLE_API_KEY"),
        "deepseek": os.environ.get("DEEPSEEK_API_KEY"),
        "qwen": os.environ.get("DASHSCOPE_API_KEY"),
        "kimi": os.environ.get("MOONSHOT_API_KEY"),
        "minimax": os.environ.get("MINIMAX_API_KEY"),
    }

    for provider, key in keys.items():
        if key:
            names = {
                "claude": "Claude",
                "openai": "GPT (OpenAI)",
                "gemini": "Gemini (Google)",
                "deepseek": "DeepSeek",
                "qwen": "Qwen (Alibaba)",
                "kimi": "Kimi (Moonshot)",
                "minimax": "MiniMax",
            }
            print(f"[OK] API key is set ({names[provider]})")
            return provider

    print("[X] No API key detected")
    print()
    print("支持的厂商和环境变量:")
    print("  Claude:    set ANTHROPIC_API_KEY=sk-ant-...")
    print("  OpenAI:    set OPENAI_API_KEY=sk-...")
    print("  Gemini:    set GOOGLE_API_KEY=...")
    print("  DeepSeek:  set DEEPSEEK_API_KEY=sk-...")
    print("  Qwen:      set DASHSCOPE_API_KEY=sk-...")
    print("  Kimi:      set MOONSHOT_API_KEY=sk-...")
    print("  MiniMax:   set MINIMAX_API_KEY=...")
    print()
    print("或使用本地模型:")
    print("  set TF_AI_PROVIDER=local")
    print("  set LOCAL_MODEL_URL=http://localhost:11434")
    return None


__all__ = [
    "AIConfig",
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