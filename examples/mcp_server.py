"""
TestForge MCP 服务器示例
========================

使用 FastMCP 暴露工具给 AI Agent
"""

import asyncio
from fastmcp import FastMCP


# 创建 MCP 服务器
mcp = FastMCP("TestForge")


@mcp.tool()
async def snapshot(page, step: int = None) -> dict:
    """
    捕获页面快照

    Returns:
        ARIA 和 AX 快照内容
    """
    from TestForge.src.browser import capture_aria_snapshot, capture_ax_snapshot

    aria = await capture_aria_snapshot(page)
    ax = await capture_ax_snapshot(page)

    return {
        "aria": aria.get("data", {}).get("yaml", ""),
        "ax": ax.get("data", {}).get("json", {}).get("full", ""),
    }


@mcp.tool()
async def navigate(page, url: str, base: str, step: int = None) -> dict:
    """
    导航到 URL

    Args:
        page: Playwright Page
        url: 目标 URL (绝对或相对)
        base: 基础 URL
        step: 步骤索引
    """
    from TestForge.src.tools.navigate import navigate

    return await navigate(page, base, url)


@mcp.tool()
async def click(page, description: str = "", ref: str = "", step: int = None) -> dict:
    """
    点击元素

    Args:
        page: Playwright Page
        description: 元素描述
        ref: 元素引用 (来自快照)
        step: 步骤索引
    """
    from TestForge.src.tools.click import click

    return await click(page, description, ref, step)


@mcp.tool()
async def fill(page, description: str = "", ref: str = "", text: str = "", step: int = None) -> dict:
    """
    填写表单

    Args:
        page: Playwright Page
        description: 目标描述
        ref: 元素引用
        text: 填充文本
        step: 步骤索引
    """
    from TestForge.src.tools.fill import fill

    return await fill(page, description, ref, text, step)


@mcp.tool()
async def wait(page, seconds: float, step: int = None) -> dict:
    """
    等待指定秒数

    Args:
        page: Playwright Page
        seconds: 秒数
        step: 步骤索引
    """
    from TestForge.src.tools.navigate import wait

    return await wait(page, seconds)


@mcp.tool()
async def scroll(page, direction: str, amount: float, step: int = None) -> dict:
    """
    滚动页面

    Args:
        page: Playwright Page
        direction: 方向 ('up' 或 'down')
        amount: 滚动距离 (像素)
        step: 步骤索引
    """
    from TestForge.src.tools.navigate import scroll

    return await scroll(page, direction, amount)


@mcp.tool()
async def assert_visible(page, description: str = "", ref: str = "", step: int = None) -> dict:
    """
    断言元素可见

    Args:
        page: Playwright Page
        description: 元素描述
        ref: 元素引用
        step: 步骤索引
    """
    from TestForge.src.tools.assertions import assert_element_visible

    return await assert_element_visible(page, description, ref)


@mcp.tool()
async def assert_text(page, text: str, step: int = None) -> dict:
    """
    断言页面包含文本

    Args:
        page: Playwright Page
        text: 要查找的文本
        step: 步骤索引
    """
    from TestForge.src.tools.assertions import assert_text_present

    return await assert_text_present(page, text)


if __name__ == "__main__":
    # 运行 MCP 服务器
    mcp.run(transport="stdio")