"""
TestForge 初始化配置向导
========================

交互式引导用户配置:
1. 选择 AI 厂商
2. 输入 API key
3. 测试连接
4. 保存配置
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

# Windows encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ==================== 配置数据结构 ====================

@dataclass
class Config:
    """TestForge 配置"""
    # AI 配置
    ai_provider: str = "claude"  # claude, openai, local, gemini, deepseek, qwen, kimi, minimax
    ai_model: str = "claude-3-5-sonnet-20241022"
    api_key: Optional[str] = None
    api_base: Optional[str] = None  # API base URL (有些厂商需要)

    # 浏览器配置
    chromium_channel: str = "chrome"  # chrome, msedge, chromium
    chromium_path: Optional[str] = None
    headless: bool = False

    # 其他配置
    base_url: str = "http://localhost:3000"
    timeout_ms: int = 30000
    debug: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ai": {
                "provider": self.ai_provider,
                "model": self.ai_model,
                "api_key": self.api_key[:10] + "..." if self.api_key else None,  # 脱敏
                "api_base": self.api_base,
            },
            "browser": {
                "chromium_channel": self.chromium_channel,
                "chromium_path": self.chromium_path,
                "headless": self.headless,
            },
            "other": {
                "base_url": self.base_url,
                "timeout_ms": self.timeout_ms,
                "debug": self.debug,
            },
        }

    def to_env(self) -> Dict[str, str]:
        """转换为环境变量"""
        env = {
            "TF_AI_PROVIDER": self.ai_provider,
            "TF_AI_MODEL": self.ai_model,
            "TF_CHROMIUM_CHANNEL": self.chromium_channel,
            "TF_BASE_URL": self.base_url,
            "TF_DEBUG": str(int(self.debug)),
        }
        if self.api_key:
            # 根据厂商设置对应的环境变量
            if self.ai_provider == "claude":
                env["ANTHROPIC_API_KEY"] = self.api_key
            elif self.ai_provider == "openai":
                env["OPENAI_API_KEY"] = self.api_key
            elif self.ai_provider == "gemini":
                env["GOOGLE_API_KEY"] = self.api_key
            elif self.ai_provider == "deepseek":
                env["DEEPSEEK_API_KEY"] = self.api_key
            elif self.ai_provider == "qwen":
                env["DASHSCOPE_API_KEY"] = self.api_key
            elif self.ai_provider == "kimi":
                env["MOONSHOT_API_KEY"] = self.api_key
            elif self.ai_provider == "minimax":
                env["MINIMAX_API_KEY"] = self.api_key
        if self.api_base:
            env["TF_AI_BASE_URL"] = self.api_base
        if self.chromium_path:
            env["TF_CHROMIUM_PATH"] = self.chromium_path
        return env


# ==================== 初始化向导 ====================

class InitWizard:
    """
    交互式初始化向导

    使用示例:
        wizard = InitWizard()
        config = await wizard.run()
        wizard.save_config(config)
    """

    # 支持的 AI 厂商和模型
    AI_PROVIDERS = {
        "1": {
            "id": "claude",
            "name": "Claude (Anthropic)",
            "models": [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241007",
                "claude-3-opus-20240229",
                "claude-3-sonnet-20240229",
            ],
            "api_key_env": "ANTHROPIC_API_KEY",
            "api_url": "https://api.anthropic.com",
            "color": "cyan",
        },
        "2": {
            "id": "openai",
            "name": "GPT (OpenAI)",
            "models": [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-4",
                "gpt-3.5-turbo",
            ],
            "api_key_env": "OPENAI_API_KEY",
            "api_url": "https://api.openai.com",
            "color": "green",
        },
        "3": {
            "id": "gemini",
            "name": "Gemini (Google)",
            "models": [
                "gemini-2.0-flash",
                "gemini-1.5-pro",
                "gemini-1.5-flash",
                "gemini-1.5-flash-8b",
            ],
            "api_key_env": "GOOGLE_API_KEY",
            "api_url": "https://generativelanguage.googleapis.com",
            "color": "yellow",
        },
        "4": {
            "id": "deepseek",
            "name": "DeepSeek",
            "models": [
                "deepseek-chat",
                "deepseek-coder",
            ],
            "api_key_env": "DEEPSEEK_API_KEY",
            "api_url": "https://api.deepseek.com",
            "color": "magenta",
        },
        "5": {
            "id": "qwen",
            "name": "Qwen (阿里通义)",
            "models": [
                "qwen-turbo",
                "qwen-plus",
                "qwen-max",
                "qwen-max-longcontext",
            ],
            "api_key_env": "DASHSCOPE_API_KEY",
            "api_url": "https://dashscope.aliyuncs.com",
            "color": "blue",
        },
        "6": {
            "id": "kimi",
            "name": "Kimi (Moonshot)",
            "models": [],  # 让用户直接输入
            "api_key_env": "MOONSHOT_API_KEY",
            "api_url": "https://api.moonshot.cn",
            "color": "cyan",
        },
        "7": {
            "id": "minimax",
            "name": "MiniMax",
            "models": [],  # 让用户直接输入
            "api_key_env": "MINIMAX_API_KEY",
            "api_url": "https://api.minimax.chat",
            "color": "white",
        },
        "8": {
            "id": "local",
            "name": "Local Model (Ollama)",
            "models": [
                "llama3",
                "llama3.1",
                "qwen2.5",
                "deepseek-v2",
                "mistral",
                "codellama",
            ],
            "api_key_env": "LOCAL_MODEL_URL",
            "api_url": "http://localhost:11434",
            "color": "white",
        },
    }

    # 支持的浏览器
    BROWSER_CHANNELS = {
        "1": {"id": "chrome", "name": "Chrome (系统安装)"},
        "2": {"id": "msedge", "name": "Edge (系统安装)"},
        "3": {"id": "chromium", "name": "Playwright Chromium (默认)"},
    }

    CONFIG_DIR = Path.home() / ".testforge"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    def __init__(self):
        self.config = Config()
        self.config_dir = self.CONFIG_DIR
        self.config_file = self.CONFIG_FILE

    def print_header(self):
        """打印标题"""
        print()
        print("=" * 60)
        print("  TestForge 初始化配置向导")
        print("=" * 60)
        print()

    def print_step(self, num: int, total: int, title: str):
        """打印步骤标题"""
        print(f"\n[{num}/{total}] {title}")
        print("-" * 40)

    def input_with_default(self, prompt: str, default: str = "") -> str:
        """带默认值的输入"""
        if default:
            user_input = input(f"  {prompt} [{default}]: ").strip()
            return user_input if user_input else default
        else:
            return input(f"  {prompt}: ").strip()

    def confirm(self, prompt: str, default: bool = False) -> bool:
        """确认提示"""
        suffix = " [Y/n]" if default else " [y/N]"
        result = input(f"  {prompt}{suffix}: ").strip().lower()
        if not result:
            return default
        return result in ("y", "yes")

    async def step_select_ai_provider(self) -> str:
        """步骤1: 选择 AI 厂商"""
        self.print_step(1, 6, "选择 AI 厂商")

        print("  可用选项:")
        for key, provider in self.AI_PROVIDERS.items():
            print(f"    {key}. {provider['name']}")

        print()
        while True:
            choice = input("  请选择 (1-8): ").strip()
            if choice in self.AI_PROVIDERS:
                provider = self.AI_PROVIDERS[choice]
                print(f"\n  已选择: {provider['name']}")
                return provider["id"]
            print("  无效选择，请重试")

    async def step_select_model(self, provider_id: str) -> str:
        """步骤2: 选择模型"""
        self.print_step(2, 6, "选择模型")

        provider = self.AI_PROVIDERS.get(
            [k for k, v in self.AI_PROVIDERS.items() if v["id"] == provider_id][0],
            {}
        )

        if not provider:
            return provider_id

        models = provider.get("models", [])

        if provider_id == "local":
            print("  本地模型需要先安装 Ollama")
            print("  模型列表由 Ollama 决定，这里使用默认 llama3")
            return "llama3"

        print(f"  {provider['name']} 可用模型:")

        # 有可靠模型列表的显示，否则让用户输入
        if models and models[0] not in ["abab6-chat", "moonshot-v1-8k"]:
            for i, model in enumerate(models, 1):
                print(f"    {i}. {model}")
            print()
            while True:
                choice = input(f"  请选择 (1-{len(models)}): ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(models):
                    model = models[int(choice) - 1]
                    print(f"\n  已选择: {model}")
                    return model
                print("  无效选择，请重试")
        else:
            # 让用户直接输入模型名
            default_model = provider.get("models", [""])[0] if models else ""
            hint = f"  参考: {default_model}" if default_model else ""
            if hint:
                print(hint)
            model = input("  请输入模型名称: ").strip()
            if model:
                print(f"\n  已选择: {model}")
                return model
            elif default_model:
                print(f"  使用默认: {default_model}")
                return default_model
            else:
                print("  不能为空，请重新输入")
                return await self.step_select_model(provider_id)

    async def step_input_api_key(self, provider_id: str) -> str:
        """步骤3: 输入 API Key"""
        self.print_step(3, 6, "输入 API Key")

        provider = self.AI_PROVIDERS.get(
            [k for k, v in self.AI_PROVIDERS.items() if v["id"] == provider_id][0],
            {}
        )

        if not provider:
            return ""

        api_url = provider.get("api_url", "")
        env_var = provider.get("api_key_env", "")

        if provider_id == "local":
            print("  请输入本地模型服务地址")
            print("  默认: http://localhost:11434 (Ollama)")
            api_key = input(f"  输入 URL [{api_url}]: ").strip()
            return api_key or api_url

        print(f"  请输入 {provider['name']} 的 API Key")
        print(f"  获取地址: {api_url.replace('api.', 'console.')}")

        # 检查是否已有环境变量
        existing = os.environ.get(env_var)
        if existing:
            print(f"\n  检测到已有 {env_var}")
            if self.confirm("使用现有值吗", default=True):
                return existing

        api_key = input(f"  输入 {env_var}: ").strip()
        if not api_key:
            print("  不能为空")
            return await self.step_input_api_key(provider_id)

        return api_key

    async def step_select_browser(self) -> str:
        """步骤4: 选择浏览器"""
        self.print_step(4, 6, "选择浏览器")

        print("  可用选项:")
        for key, browser in self.BROWSER_CHANNELS.items():
            print(f"    {key}. {browser['name']}")

        print()
        while True:
            choice = input("  请选择 (1-3): ").strip()
            if choice in self.BROWSER_CHANNELS:
                browser = self.BROWSER_CHANNELS[choice]
                print(f"\n  已选择: {browser['name']}")
                return browser["id"]
            print("  无效选择，请重试")

    async def step_test_connection(self, provider: str, api_key: str, model: str) -> bool:
        """步骤5: 测试连接"""
        self.print_step(5, 6, "测试 AI 连接")

        print("  正在测试连接...")
        print("  发送: 你好，请回复'连接成功'确认正常工作")
        print()

        try:
            if provider == "claude":
                response_text = await self._test_claude(api_key, model)
            elif provider == "openai":
                response_text = await self._test_openai(api_key, model)
            elif provider == "gemini":
                response_text = await self._test_gemini(api_key, model)
            elif provider == "deepseek":
                response_text = await self._test_deepseek(api_key, model)
            elif provider == "qwen":
                response_text = await self._test_qwen(api_key, model)
            elif provider == "kimi":
                response_text = await self._test_kimi(api_key, model)
            elif provider == "minimax":
                response_text = await self._test_minimax(api_key, model)
            else:
                response_text = await self._test_local(api_key)

            print(f"  AI 回复: {response_text[:200]}")
            success = True
        except Exception as e:
            print(f"  连接失败: {e}")
            success = False

        if success:
            print("\n  [OK] 连接成功!")
        else:
            print("\n  [X] 连接失败")
            print("  可以跳过继续，或重新输入")

        return success

    async def _test_claude(self, api_key: str, model: str) -> str:
        """测试 Claude 连接"""
        import httpx

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "max_tokens": 50,
            "messages": [{"role": "user", "content": "请回复'连接成功'四个字确认正常工作"}],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["content"][0]["text"]
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_openai(self, api_key: str, model: str) -> str:
        """测试 OpenAI 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "请回复'连接成功'四个字确认正常工作"}],
            "max_tokens": 50,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_local(self, url: str) -> str:
        """测试本地模型连接"""
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{url}/api/tags",
            )

        if response.status_code == 200:
            models = response.json().get("models", [])
            if models:
                return f"可用模型: {', '.join([m['name'] for m in models[:3]])}"
            return "连接成功"
        else:
            raise Exception(f"连接失败: {response.status_code}")

    async def _test_gemini(self, api_key: str, model: str) -> str:
        """测试 Gemini 连接"""
        import httpx

        headers = {
            "content-type": "application/json",
        }

        data = {
            "contents": [{
                "parts": [{"text": "请回复'连接成功'四个字确认正常工作"}]
            }],
            "generationConfig": {
                "maxOutputTokens": 50,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        elif response.status_code == 400:
            raise Exception("请求格式错误")
        elif response.status_code == 403:
            raise Exception("API Key 无效或权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_deepseek(self, api_key: str, model: str) -> str:
        """测试 DeepSeek 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "请回复'连接成功'四个字确认正常工作"}],
            "max_tokens": 50,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_qwen(self, api_key: str, model: str) -> str:
        """测试 Qwen 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "input": {
                "messages": [{"role": "user", "content": "请回复'连接成功'四个字确认正常工作"}]
            },
            "parameters": {
                "max_tokens": 50,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["output"]["text"]
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足或余额不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_kimi(self, api_key: str, model: str) -> str:
        """测试 Kimi 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "请回复'连接成功'四个字确认正常工作"}],
            "max_tokens": 50,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_minimax(self, api_key: str, model: str) -> str:
        """测试 MiniMax 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "请回复'连接成功'四个字确认正常工作"}],
            "max_output_tokens": 50,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.minimax.chat/v1/text/chatcompletion_v2",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            result = response.json()
            return result["choices"][0]["message"]["content"]
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_gemini(self, api_key: str, model: str) -> bool:
        """测试 Gemini 连接"""
        import httpx

        headers = {
            "content-type": "application/json",
        }

        data = {
            "contents": [{
                "parts": [{"text": "Hi"}]
            }],
            "generationConfig": {
                "maxOutputTokens": 10,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            return True
        elif response.status_code == 400:
            raise Exception("请求格式错误")
        elif response.status_code == 403:
            raise Exception("API Key 无效或权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_deepseek(self, api_key: str, model: str) -> bool:
        """测试 DeepSeek 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_qwen(self, api_key: str, model: str) -> bool:
        """测试 Qwen 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "input": {
                "messages": [{"role": "user", "content": "Hi"}]
            },
            "parameters": {
                "max_tokens": 10,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足或余额不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_kimi(self, api_key: str, model: str) -> bool:
        """测试 Kimi 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 10,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.moonshot.cn/v1/chat/completions",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    async def _test_minimax(self, api_key: str, model: str) -> bool:
        """测试 MiniMax 连接"""
        import httpx

        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }

        data = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_output_tokens": 10,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.minimax.chat/v1/text/chatcompletion_v2",
                headers=headers,
                json=data,
            )

        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            raise Exception("API Key 无效")
        elif response.status_code == 403:
            raise Exception("API Key 权限不足")
        else:
            raise Exception(f"错误 {response.status_code}: {response.text[:100]}")

    def step_save_config(self, config: Config) -> str:
        """步骤5: 保存配置"""
        self.print_step(5, 5, "保存配置")

        # 确保目录存在
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # 保存配置
        config_data = {
            "ai_provider": config.ai_provider,
            "ai_model": config.ai_model,
            "api_key": config.api_key,
            "chromium_channel": config.chromium_channel,
            "base_url": config.base_url,
        }

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False)

        print(f"\n  配置已保存到: {self.config_file}")

        # 同时设置环境变量
        for key, value in config.to_env().items():
            os.environ[key] = value

        return str(self.config_file)

    async def run(self) -> Config:
        """运行初始化向导"""
        self.print_header()

        # 如果已有配置，询问是否使用
        if self.config_file.exists():
            print("  检测到已有配置文件")
            if self.confirm("是否使用现有配置", default=True):
                existing = self.load_config()
                if existing:
                    print("  已加载现有配置")
                    return existing

        # 步骤1: 选择 AI 厂商
        provider = await self.step_select_ai_provider()
        self.config.ai_provider = provider

        # 步骤2: 选择模型
        model = await self.step_select_model(provider)
        self.config.ai_model = model

        # 步骤3: 输入 API Key
        api_key = await self.step_input_api_key(provider)
        self.config.api_key = api_key

        # 步骤4: 选择浏览器
        browser = await self.step_select_browser()
        self.config.chromium_channel = browser

        # 步骤5: 测试连接
        while True:
            success = await self.step_test_connection(provider, api_key, model)
            if success:
                break
            if self.confirm("是否跳过连接测试", default=False):
                break
            # 重新输入
            print("\n  请重新输入:")
            api_key = await self.step_input_api_key(provider)
            self.config.api_key = api_key

        # 步骤6: 保存配置
        config_file = self.step_save_config(self.config)

        print("\n" + "=" * 60)
        print("  初始化完成!")
        print("=" * 60)
        print()
        print(f"  配置文件: {config_file}")
        print(f"  AI 厂商: {self.config.ai_provider}")
        print(f"  AI 模型: {self.config.ai_model}")
        print(f"  浏览器: {self.config.chromium_channel}")
        print()
        print("  接下来可以运行:")
        print("    python examples/ai_demo.py")
        print("    python examples/agent_demo.py")
        print()

        return self.config

    def load_config(self) -> Optional[Config]:
        """加载配置文件"""
        if not self.config_file.exists():
            return None

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.config.ai_provider = data.get("ai_provider", "claude")
            self.config.ai_model = data.get("ai_model", "claude-3-5-sonnet-20241022")
            self.config.api_key = data.get("api_key")
            self.config.chromium_channel = data.get("chromium_channel", "chrome")
            self.config.base_url = data.get("base_url", "http://localhost:3000")

            return self.config
        except Exception as e:
            print(f"  加载配置失败: {e}")
            return None

    def apply_config(self, config: Optional[Config] = None):
        """将配置应用到环境变量"""
        if config is None:
            config = self.load_config()
            if config is None:
                return False

        for key, value in config.to_env().items():
            if value:
                os.environ[key] = value

        return True


# ==================== 便捷函数 ====================

async def init():
    """初始化 TestForge"""
    wizard = InitWizard()
    return await wizard.run()


def load_config() -> Optional[Config]:
    """加载配置"""
    wizard = InitWizard()
    return wizard.load_config()


def apply_config():
    """应用配置到环境变量"""
    wizard = InitWizard()
    return wizard.apply_config()


# ==================== 导出 ====================

__all__ = [
    "Config",
    "InitWizard",
    "init",
    "load_config",
    "apply_config",
]


# ==================== 主程序 ====================

if __name__ == "__main__":
    print("""
============================================================
TestForge 配置初始化
============================================================
""")

    async def main():
        wizard = InitWizard()
        config = await wizard.run()

    asyncio.run(main())