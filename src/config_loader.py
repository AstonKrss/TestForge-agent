"""
ConfigLoader - 统一配置加载
===========================

支持两种配置来源（优先级从高到低）：
1. 环境变量（命令行覆盖）
2. config.json 配置文件

同时作为 InitWizard 和 AIConfig 的桥梁。
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field


CONFIG_FILE = Path.home() / ".testforge" / "config.json"


@dataclass
class AIConfig:
    """AI 配置"""
    provider: str = "claude"
    model: str = "claude-3-5-sonnet-20241022"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.0


@dataclass
class BrowserConfig:
    """浏览器配置"""
    channel: str = "chrome"
    headless: bool = False
    executable_path: Optional[str] = None


@dataclass
class AppConfig:
    """应用程序配置"""
    ai: AIConfig = field(default_factory=AIConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    base_url: str = "http://localhost:3000"
    timeout_ms: int = 30000
    debug: bool = False


def _env_or_json(env_key: str, json_value: Any, default: Any = None) -> Any:
    """优先使用环境变量，否则用 JSON 配置"""
    env_val = os.environ.get(env_key)
    if env_val is not None:
        if isinstance(default, bool):
            return env_val.lower() in ("1", "true", "yes")
        if isinstance(default, int):
            return int(env_val)
        return env_val
    if json_value is not None:
        return json_value
    return default


def load_config_file() -> Dict[str, Any]:
    """从 config.json 加载配置"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_config_to_env(config: Dict[str, Any]) -> None:
    """将 config.json 的内容应用到环境变量"""
    ai = config.get("ai", {})
    browser = config.get("browser", {})

    if ai.get("api_key"):
        provider = ai.get("provider", "claude")
        if provider == "claude":
            os.environ.setdefault("ANTHROPIC_API_KEY", ai["api_key"])
        elif provider == "openai":
            os.environ.setdefault("OPENAI_API_KEY", ai["api_key"])
        elif provider == "gemini":
            os.environ.setdefault("GOOGLE_API_KEY", ai["api_key"])
        elif provider == "deepseek":
            os.environ.setdefault("DEEPSEEK_API_KEY", ai["api_key"])
        elif provider == "qwen":
            os.environ.setdefault("DASHSCOPE_API_KEY", ai["api_key"])
        elif provider == "kimi":
            os.environ.setdefault("MOONSHOT_API_KEY", ai["api_key"])
        elif provider == "minimax":
            os.environ.setdefault("MINIMAX_API_KEY", ai["api_key"])

        os.environ.setdefault("TF_AI_PROVIDER", ai.get("provider", "claude"))
        os.environ.setdefault("TF_AI_MODEL", ai.get("model", ""))

    if browser:
        os.environ.setdefault("TF_CHROMIUM_CHANNEL", browser.get("channel", "chrome"))
        if browser.get("executable_path"):
            os.environ.setdefault("TF_CHROMIUM_PATH", browser["executable_path"])

    os.environ.setdefault("TF_BASE_URL", config.get("base_url", "http://localhost:3000"))


def _normalize_config(file_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    规范化配置格式。

    InitWizard 使用扁平格式保存，但 load() 期望嵌套格式。
    自动检测并转换。
    """
    # 已经是嵌套格式
    if "ai" in file_config and isinstance(file_config["ai"], dict):
        return file_config

    # 扁平格式转换
    return {
        "ai": {
            "provider": file_config.get("ai_provider", "claude"),
            "model": file_config.get("ai_model", "claude-3-5-sonnet-20241022"),
            "api_key": file_config.get("api_key"),
            "api_base": file_config.get("api_base"),
        },
        "browser": {
            "channel": file_config.get("chromium_channel", "chrome"),
            "executable_path": file_config.get("chromium_path"),
            "headless": file_config.get("headless", False),
        },
        "base_url": file_config.get("base_url", "http://localhost:3000"),
        "timeout_ms": file_config.get("timeout_ms", 30000),
        "debug": file_config.get("debug", False),
    }


def load() -> AppConfig:
    """
    加载完整配置（config.json + 环境变量覆盖）

    优先级：环境变量 > config.json > 默认值
    """
    file_config = load_config_file()
    # 支持扁平格式（InitWizard 保存的）和嵌套格式
    file_config = _normalize_config(file_config)
    ai_data = file_config.get("ai", {})
    browser_data = file_config.get("browser", {})

    # AI 配置
    ai_provider = _env_or_json("TF_AI_PROVIDER", ai_data.get("provider"), "claude")
    ai_model = _env_or_json("TF_AI_MODEL", ai_data.get("model"), "claude-3-5-sonnet-20241022")
    api_key = None

    if ai_provider == "claude":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "gemini":
        api_key = os.environ.get("GOOGLE_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "qwen":
        api_key = os.environ.get("DASHSCOPE_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "kimi":
        api_key = os.environ.get("MOONSHOT_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "minimax":
        api_key = os.environ.get("MINIMAX_API_KEY") or ai_data.get("api_key")
    elif ai_provider == "local":
        api_key = os.environ.get("LOCAL_MODEL_URL") or ai_data.get("api_key") or "http://localhost:11434"

    ai_config = AIConfig(
        provider=ai_provider,
        model=ai_model,
        api_key=api_key,
        base_url=(
            (os.environ.get("LOCAL_MODEL_URL") or api_key or "http://localhost:11434").rstrip("/")
            if ai_provider == "local"
            else _env_or_json("TF_AI_BASE_URL", ai_data.get("api_base"), None)
        ),
    )

    # 浏览器配置
    browser_config = BrowserConfig(
        channel=_env_or_json("TF_CHROMIUM_CHANNEL", browser_data.get("channel"), "chrome"),
        headless=_env_or_json("TF_HEADLESS", browser_data.get("headless"), False),
        executable_path=_env_or_json("TF_CHROMIUM_PATH", browser_data.get("executable_path"), None),
    )

    # 应用到环境变量（供 AI 客户端使用）
    apply_config_to_env(file_config)

    return AppConfig(
        ai=ai_config,
        browser=browser_config,
        base_url=_env_or_json("TF_BASE_URL", file_config.get("base_url"), "http://localhost:3000"),
        timeout_ms=_env_or_json("TF_TIMEOUT_MS", file_config.get("timeout_ms"), 30000),
        debug=_env_or_json("TF_DEBUG", file_config.get("debug"), False),
    )


def has_api_key() -> bool:
    """检查是否配置了 API key"""
    file_config = load_config_file()

    # InitWizard 使用扁平格式：api_key 直接在根目录
    key = file_config.get("api_key", "")
    if key:
        return True

    # 兜底：环境变量
    provider = os.environ.get("TF_AI_PROVIDER", "")
    if provider == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        return True
    if provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        return True
    if provider == "gemini" and os.environ.get("GOOGLE_API_KEY"):
        return True
    if provider == "deepseek" and os.environ.get("DEEPSEEK_API_KEY"):
        return True
    if provider == "qwen" and os.environ.get("DASHSCOPE_API_KEY"):
        return True
    if provider == "kimi" and os.environ.get("MOONSHOT_API_KEY"):
        return True
    if provider == "minimax" and os.environ.get("MINIMAX_API_KEY"):
        return True

    return False


def get_ai_config_for_client() -> AIConfig:
    """返回适合传递给 AI 客户端的配置"""
    config = load()
    return config.ai


__all__ = [
    "AppConfig",
    "AIConfig",
    "BrowserConfig",
    "CONFIG_FILE",
    "load",
    "has_api_key",
    "get_ai_config_for_client",
]
