"""
TestForge CLI 模块
==================

入口:
    python run_cli.py

子模块:
    startup_menu  - 启动菜单（配置 API / 进入 CLI / 退出）
    main_agent    - 主对话 Agent（理解用户意图，协调 ExecutorAgent）
    executor_agent - 执行 Agent（浏览器操作，工具调用）
    tools         - 浏览器操作工具集
"""

from .main_agent import MainAgent, SessionContext
from .executor_agent import ExecutorAgent, ExecutorResult, ResultType
from .tools import (
    ToolResult,
    TOOLS,
    call_tool,
    navigate,
    snapshot,
    find_elements,
    click,
    fill,
    scroll,
    wait,
    screenshot,
    performance_audit,
    load_test,
    quality_audit,
    security_audit,
    accessibility_audit,
)
from .session_store import SessionStore

__all__ = [
    # 入口
    "MainAgent",
    "SessionContext",
    # 执行器
    "ExecutorAgent",
    "ExecutorResult",
    "ResultType",
    # 工具
    "ToolResult",
    "TOOLS",
    "call_tool",
    "navigate",
    "snapshot",
    "find_elements",
    "click",
    "fill",
    "scroll",
    "wait",
    "screenshot",
    "performance_audit",
    "load_test",
    "quality_audit",
    "security_audit",
    "accessibility_audit",
    "SessionStore",
]
