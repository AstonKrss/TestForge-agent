"""
TestForge 配置系统
==================

支持环境变量和配置文件
"""

import os
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from pathlib import Path


class Guardrails:
    """Guardrails 配置"""
    def __init__(
        self,
        max_tool_calls: int = 200,
        max_consecutive_errors: int = 5,
        max_retries_per_step: int = 3,
        max_agent_turns: int = 50,
    ):
        self.max_tool_calls = max_tool_calls
        self.max_consecutive_errors = max_consecutive_errors
        self.max_retries_per_step = max_retries_per_step
        self.max_agent_turns = max_agent_turns


@dataclass
class Config:
    """TestForge 配置"""

    # 基础配置
    base_url: str = "http://localhost:3000"

    # 浏览器配置
    headless: bool = True
    slow_mo: Optional[int] = None
    chromium_channel: str = ""

    # Guardrails
    guardrails: Guardrails = field(default_factory=Guardrails)

    # 上下文模式
    tool_context: str = "screenshot"  # screenshot | snapshot | none
    artifacts_mode: str = "fail"  # all | fail | none
    screenshot_timing: str = "pre"  # pre | post
    ui_language: str = "en"  # en | zh

    # 执行配置
    debug: bool = False
    cwd: str = ""

    def __post_init__(self):
        if not self.cwd:
            self.cwd = os.getcwd()

    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量加载配置"""
        return cls(
            base_url=os.environ.get("TF_BASE_URL", "http://localhost:3000"),
            headless=os.environ.get("TF_HEADLESS", "true").lower() != "false",
            slow_mo=int(os.environ["TF_SLOW_MO"]) if os.environ.get("TF_SLOW_MO") else None,
            chromium_channel=os.environ.get("TF_CHROMIUM_CHANNEL", ""),
            tool_context=os.environ.get("TF_TOOL_CONTEXT", "screenshot"),
            artifacts_mode=os.environ.get("TF_ARTIFACTS", "fail"),
            screenshot_timing=os.environ.get("TF_SCREENSHOT_TIMING", "pre"),
            ui_language=os.environ.get("TF_UI_LANGUAGE", "en"),
            debug=os.environ.get("TF_DEBUG", "0") == "1",
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "base_url": self.base_url,
            "headless": self.headless,
            "slow_mo": self.slow_mo,
            "chromium_channel": self.chromium_channel,
            "tool_context": self.tool_context,
            "artifacts_mode": self.artifacts_mode,
            "screenshot_timing": self.screenshot_timing,
            "ui_language": self.ui_language,
            "debug": self.debug,
            "guardrails": {
                "max_tool_calls": self.guardrails.max_tool_calls,
                "max_consecutive_errors": self.guardrails.max_consecutive_errors,
                "max_retries_per_step": self.guardrails.max_retries_per_step,
            },
        }