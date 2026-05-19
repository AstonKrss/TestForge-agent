"""
TestForge 工具错误处理
======================

将异常转换为标准化工具结果
"""

from typing import Optional, Dict, Any


# 错误代码
class ErrorCode:
    INVALID_INPUT = "INVALID_INPUT"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    ELEMENT_NOT_VISIBLE = "ELEMENT_NOT_VISIBLE"
    ELEMENT_NOT_ENABLED = "ELEMENT_NOT_ENABLED"
    ELEMENT_NOT_EDITABLE = "ELEMENT_NOT_EDITABLE"
    ASSERTION_FAILED = "ASSERTION_FAILED"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERCEPTED = "INTERCEPTED"
    DETACHED = "DETACHED"
    UNKNOWN = "UNKNOWN"


class ToolError:
    """工具错误"""
    def __init__(
        self,
        code: str,
        message: str,
        retriable: bool = False,
        cause: Optional[str] = None,
    ):
        self.code = code
        self.message = message
        self.retriable = retriable
        self.cause = cause

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retriable": self.retriable,
            "cause": self.cause,
        }


def is_timeout_error(err: Exception) -> bool:
    """检查是否是超时错误"""
    msg = str(err).lower()
    return "timeout" in msg or "timed out" in msg


def to_tool_error(
    error: Exception,
    default_code: str = ErrorCode.UNKNOWN,
    default_retriable: bool = False,
) -> ToolError:
    """
    将异常转换为工具错误

    Args:
        error: 原始异常
        default_code: 默认错误代码
        default_retriable: 默认是否可重试

    Returns:
        ToolError
    """
    msg = str(error).lower()

    if is_timeout_error(error):
        return ToolError(ErrorCode.TIMEOUT, str(error), retriable=True, cause=default_code)

    if "not found" in msg or "could not locate" in msg:
        return ToolError(ErrorCode.ELEMENT_NOT_FOUND, str(error), retriable=True, cause=default_code)

    if "not visible" in msg or "is hidden" in msg:
        return ToolError(ErrorCode.ELEMENT_NOT_VISIBLE, str(error), retriable=True, cause=default_code)

    if "not enabled" in msg or "disabled" in msg:
        return ToolError(ErrorCode.ELEMENT_NOT_ENABLED, str(error), retriable=False, cause=default_code)

    if "not editable" in msg or "read-only" in msg:
        return ToolError(ErrorCode.ELEMENT_NOT_EDITABLE, str(error), retriable=False, cause=default_code)

    if "intercepts pointer events" in msg:
        return ToolError(ErrorCode.INTERCEPTED, str(error), retriable=True, cause=default_code)

    if "detached" in msg:
        return ToolError(ErrorCode.DETACHED, str(error), retriable=True, cause=default_code)

    if "navigation" in msg or "net::err" in msg:
        return ToolError(ErrorCode.NAVIGATION_FAILED, str(error), retriable=True, cause=default_code)

    return ToolError(default_code, str(error), retriable=default_retriable)


def ok(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功结果"""
    result = {"ok": True}
    if data:
        result["data"] = data
    return result


def fail(
    code: str,
    message: str,
    retriable: bool = False,
    cause: Optional[str] = None,
) -> Dict[str, Any]:
    """创建失败结果"""
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retriable": retriable,
            "cause": cause,
        },
    }