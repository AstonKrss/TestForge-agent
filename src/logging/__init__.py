"""
TestForge 日志系统
==================

特性:
- 敏感信息自动脱敏
- 结构化日志输出
- 彩色终端支持
"""

import os
import re
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from enum import Enum


class LogLevel(Enum):
    DEBUG = 1
    INFO = 2
    WARN = 3
    ERROR = 4


class Logger:
    """
    结构化日志记录器

    特性:
    - JSON 结构化输出 (生产环境)
    - 彩色终端输出 (开发环境)
    - 敏感信息自动脱敏
    """

    # 颜色代码
    COLORS = {
        "reset": "\033[0m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
    }

    # 日志级别颜色
    LEVEL_COLORS = {
        LogLevel.DEBUG: "cyan",
        LogLevel.INFO: "green",
        LogLevel.WARN: "yellow",
        LogLevel.ERROR: "red",
    }

    def __init__(self, name: str = "TestForge", level: LogLevel = LogLevel.INFO):
        self.name = name
        self.level = level
        self._is_tty = sys.stderr.isatty() if hasattr(sys.stderr, "isatty") else False

        # 敏感信息模式
        self._secret_patterns = [
            r"password", r"secret", r"token", r"api_key",
            r"auth", r"credential", r"private_key",
        ]

    def _color(self, text: str, color: str) -> str:
        """添加颜色"""
        if not self._is_tty:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def _should_redact(self, key: str) -> bool:
        """检查是否应该脱敏"""
        key_lower = key.lower()
        return any(re.search(p, key_lower) for p in self._secret_patterns)

    def _redact_value(self, value: Any, depth: int = 0) -> Any:
        """脱敏值"""
        if depth > 5:
            return "[REDACTED:too deep]"

        if isinstance(value, str) and len(value) > 4:
            # 如果值看起来像敏感信息，脱敏
            if any(re.search(p, value.lower()) for p in self._secret_patterns):
                return "[REDACTED]"
            return value

        if isinstance(value, dict):
            return {k: self._redact_value(v, depth + 1) if self._should_redact(k) else v
                    for k, v in value.items()}

        if isinstance(value, (list, tuple)):
            return [self._redact_value(item, depth + 1) for item in value]

        return value

    def _format_color(self, level: LogLevel, message: str, data: Optional[Dict] = None) -> str:
        """格式化彩色日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_str = level.name.ljust(5)
        color = self.LEVEL_COLORS.get(level, "white")

        parts = [
            self._color(f"[{timestamp}]", "white"),
            self._color(f"[{level_str}]", color),
            self._color(f"[{self.name}]", "magenta"),
            message,
        ]

        if data:
            redacted_data = self._redact_value(data)
            parts.append(self._color(json.dumps(redacted_data, ensure_ascii=False), "cyan"))

        return " ".join(parts)

    def _format_json(self, level: LogLevel, message: str, data: Optional[Dict] = None) -> str:
        """格式化 JSON 日志"""
        log_obj = {
            "timestamp": datetime.now().isoformat(),
            "level": level.name,
            "logger": self.name,
            "message": message,
        }

        if data:
            log_obj["data"] = self._redact_value(data)

        return json.dumps(log_obj, ensure_ascii=False)

    def log(
        self,
        message: str,
        level: LogLevel = LogLevel.INFO,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        记录日志

        Args:
            message: 日志消息
            level: 日志级别
            data: 附加数据
            **kwargs: 其他字段
        """
        if level.value < self.level.value:
            return

        full_data = {**(data or {}), **kwargs}

        # 生产环境输出 JSON，调试环境输出彩色
        output = self._format_json(level, message, full_data) if not self._is_tty \
                else self._format_color(level, message, full_data)

        print(output, file=sys.stderr)

    def debug(self, message: str, **kwargs):
        self.log(message, LogLevel.DEBUG, **kwargs)

    def info(self, message: str, **kwargs):
        self.log(message, LogLevel.INFO, **kwargs)

    def warn(self, message: str, **kwargs):
        self.log(message, LogLevel.WARN, **kwargs)

    def error(self, message: str, **kwargs):
        self.log(message, LogLevel.ERROR, **kwargs)


# 默认日志器
_default_logger: Optional[Logger] = None


def get_logger(name: str = "TestForge", level: LogLevel = LogLevel.INFO) -> Logger:
    """获取日志器"""
    global _default_logger
    if _default_logger is None:
        _default_logger = Logger(name, level)
    return _default_logger


def redact_tool_input(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    脱敏工具输入

    对于敏感字段，值替换为 [REDACTED]
    """
    sensitive_fields = {
        "fill": ["text", "password", "value"],
        "navigate": [],
        "click": [],
        "scroll": [],
        "wait": [],
    }

    fields_to_redact = sensitive_fields.get(tool_name, ["password", "secret", "token"])

    redacted = dict(tool_input)
    for field in fields_to_redact:
        if field in redacted and isinstance(redacted[field], str):
            redacted[field] = "[REDACTED]"

    return redacted