"""
Logging - 日志系统
==================

结构化日志输出
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, List


def sanitize_path_segment(value: str) -> str:
    """清理路径段"""
    cleaned = (value or "").replace(r"[^a-zA-Z0-9._-]+", "_").replace(r"\.{2,}", "_").replace("^_+|_+$", "")
    if cleaned in (".", ".."):
        return "unknown"
    return cleaned if cleaned else "unknown"


def get_log_file_path(run_id: str, cwd: str = ".") -> str:
    """获取日志文件路径"""
    safe_run_id = sanitize_path_segment(run_id)
    return os.path.join(cwd, ".testforge", "runs", safe_run_id, "run.log.jsonl")


def ensure_log_dir(run_id: str, cwd: str = ".") -> None:
    """确保日志目录存在"""
    safe_run_id = sanitize_path_segment(run_id)
    dir_path = os.path.join(cwd, ".testforge", "runs", safe_run_id)
    os.makedirs(dir_path, exist_ok=True)


class Logger:
    """TestForge 日志器"""

    def __init__(
        self,
        run_id: str,
        cwd: str = ".",
        debug: bool = False,
        write_to_file: bool = True,
    ):
        self.run_id = run_id
        self.cwd = cwd
        self.debug = debug
        self.write_to_file = write_to_file

        self._buffer: List[str] = []
        self._buffer_bytes = 0
        self._max_buffer_bytes = 5 * 1024 * 1024  # 5MB
        self._file = None
        self._closed = False

        self.log_path: Optional[str] = None
        self.log_init_error: Optional[str] = None

        # 确保目录存在
        if write_to_file:
            try:
                ensure_log_dir(run_id, cwd)
                log_path = get_log_file_path(run_id, cwd)
                self._file = open(log_path, "w", encoding="utf-8")
                self.log_path = f".testforge/runs/{sanitize_path_segment(run_id)}/run.log.jsonl"
            except Exception as e:
                self.log_init_error = str(e)
                self._file = None

    def log(self, event: Dict[str, Any]) -> None:
        """
        记录日志事件

        Args:
            event: 事件字典，必须包含 "event" 字段
        """
        # 添加 runId
        event = dict(event)
        event["runId"] = self.run_id

        # 添加时间戳
        if "timestamp" not in event:
            event["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # 序列化为 JSON 行
        try:
            line = json.dumps(event, ensure_ascii=False)
        except Exception:
            line = json.dumps({"event": "LOG_ERROR", "message": "Failed to serialize event"})

        # 写入内存缓冲区
        self._buffer.append(line)
        self._buffer_bytes += len(line)

        # 清理超出限制的条目
        while self._buffer_bytes > self._max_buffer_bytes and self._buffer:
            removed = self._buffer.pop(0)
            self._buffer_bytes -= len(removed)

        # 写入文件
        if self._file:
            try:
                self._file.write(line + "\n")
                self._file.flush()
            except Exception:
                pass

        # 写入 stderr (调试模式)
        if self.debug:
            try:
                print(line, file=__import__("sys").stderr)
            except Exception:
                pass

    async def flush(self) -> None:
        """刷新日志"""
        if self._file:
            try:
                self._file.flush()
            except Exception:
                pass

    async def persist_to_file(self) -> Dict[str, Any]:
        """持久化缓冲区到文件"""
        if self.log_path:
            return {"ok": True, "logPath": self.log_path}

        try:
            ensure_log_dir(self.run_id, self.cwd)
            log_path = get_log_file_path(self.run_id, self.cwd)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("\n".join(self._buffer))
            relative_path = f".testforge/runs/{sanitize_path_segment(self.run_id)}/run.log.jsonl"
            self.log_path = relative_path
            return {"ok": True, "logPath": relative_path}
        except Exception as e:
            self.log_init_error = str(e)
            return {"ok": False, "error": str(e)}


def create_logger(
    run_id: str,
    cwd: str = ".",
    debug: bool = False,
    write_to_file: bool = True,
) -> Logger:
    """创建日志器"""
    return Logger(run_id, cwd, debug, write_to_file)


def get_artifact_root_path(run_id: str, cwd: str = ".") -> str:
    """获取 artifact 根目录"""
    safe_run_id = sanitize_path_segment(run_id)
    return f".testforge/runs/{safe_run_id}"


def get_relative_log_path(run_id: str) -> str:
    """获取相对日志路径"""
    safe_run_id = sanitize_path_segment(run_id)
    return f".testforge/runs/{safe_run_id}/run.log.jsonl"


async def ensure_artifact_dir(run_id: str, cwd: str = ".") -> str:
    """确保 artifact 目录存在"""
    safe_run_id = sanitize_path_segment(run_id)
    dir_path = os.path.join(cwd, ".testforge", "runs", safe_run_id)
    os.makedirs(dir_path, exist_ok=True)
    return f".testforge/runs/{safe_run_id}"


# ==================== 敏感信息脱敏 ====================

SENSITIVE_PATTERNS = [
    (r"password[=:]\s*[^\s&]+", "password=***"),
    (r"token[=:]\s*[^\s&]+", "token=***"),
    (r"api[_-]?key[=:]\s*[^\s&]+", "apikey=***"),
    (r"secret[=:]\s*[^\s&]+", "secret=***"),
    (r"auth[=:]\s*[^\s&]+", "auth=***"),
    (r"bearer\s+[A-Za-z0-9._-]+", "bearer ***"),
]


def redact_tool_input(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏工具输入"""
    import re

    redacted = dict(tool_input)

    # 脱敏密码字段
    if tool_name in ("fill",):
        if "text" in redacted:
            # 如果是密码字段，脱敏
            if "password" in str(tool_input.get("targetDescription", "")).lower():
                redacted["text"] = "***REDACTED***"

    # 通用脱敏
    for key, value in list(redacted.items()):
        if isinstance(value, str):
            for pattern, replacement in SENSITIVE_PATTERNS:
                if re.search(pattern, key, re.IGNORECASE):
                    redacted[key] = "***"
                    break

    return redacted


__all__ = [
    "Logger",
    "create_logger",
    "get_log_file_path",
    "ensure_log_dir",
    "ensure_artifact_dir",
    "get_artifact_root_path",
    "get_relative_log_path",
    "redact_tool_input",
]