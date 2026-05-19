"""
TestForge Navigate 工具
========================

URL 导航，支持相对路径解析
"""

import os
from typing import Dict, Any, TYPE_CHECKING
from urllib.parse import urljoin, urlparse, urlunparse

if TYPE_CHECKING:
    from playwright.sync_api import Page


MAX_WAIT_SECONDS = 60


def is_absolute(url: str) -> bool:
    """检查是否是绝对 URL"""
    try:
        return urlparse(url).scheme in ("http", "https")
    except Exception:
        return False


def resolve_url(base: str, url: str) -> str:
    """
    解析 URL

    Args:
        base: 基础 URL
        url: 目标 URL

    Returns:
        解析后的 URL
    """
    url = url.strip()
    if not url:
        return ""

    # 绝对 URL
    if is_absolute(url):
        return url

    # 相对路径
    if url.startswith("/"):
        try:
            parsed = urlparse(base)
            resolved = urlunparse((
                parsed.scheme,
                parsed.netloc,
                url,
                "", "", ""
            ))
            return resolved
        except Exception:
            return ""

    # 其他相对路径
    return urljoin(base.rstrip("/") + "/", url)


async def navigate(
    page: "Page",
    base: str,
    url: str,
) -> Dict[str, Any]:
    """
    导航到 URL

    Args:
        page: Playwright Page
        base: 基础 URL
        url: 目标 URL (绝对或相对)

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    # 验证
    if not page:
        return fail(ErrorCode.INVALID_INPUT, "page is required")

    if not base:
        return fail(ErrorCode.INVALID_INPUT, "base is required")

    # 解析 URL
    resolved = resolve_url(base, url)
    if not resolved:
        return fail(ErrorCode.INVALID_INPUT, f"Invalid navigate url: {url}")

    # 执行导航
    try:
        await page.goto(resolved, wait_until="domcontentloaded")
        return ok({"url": resolved})
    except Exception as e:
        error = to_tool_error(e, default_code=ErrorCode.NAVIGATION_FAILED)
        return fail(error.code, error.message, retriable=error.retriable)


async def wait(page: "Page", seconds: float) -> Dict[str, Any]:
    """
    等待指定秒数

    Args:
        page: Playwright Page
        seconds: 秒数

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    if not isinstance(seconds, (int, float)) or seconds < 0 or seconds > MAX_WAIT_SECONDS:
        return fail(ErrorCode.INVALID_INPUT, f"Invalid seconds: {seconds}")

    try:
        await page.wait_for_timeout(seconds * 1000)
        return ok({"seconds": seconds})
    except Exception as e:
        error = to_tool_error(e)
        return fail(error.code, error.message, retriable=error.retriable)


async def scroll(page: "Page", direction: str, amount: float) -> Dict[str, Any]:
    """
    滚动页面

    Args:
        page: Playwright Page
        direction: 方向 ('up' 或 'down')
        amount: 滚动距离

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    if direction not in ("up", "down"):
        return fail(ErrorCode.INVALID_INPUT, f"Invalid direction: {direction}")

    if not isinstance(amount, (int, float)) or amount <= 0 or amount > 5000:
        return fail(ErrorCode.INVALID_INPUT, f"Invalid amount: {amount}")

    delta = amount if direction == "down" else -amount

    try:
        await page.evaluate(
            """(dy) => window.scrollBy(0, dy)""",
            delta
        )
        return ok({"direction": direction, "amount": amount})
    except Exception as e:
        error = to_tool_error(e)
        return fail(error.code, error.message, retriable=error.retriable)