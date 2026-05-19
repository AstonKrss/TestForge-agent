"""
Explore - 探索应用入口
======================

使用 Agent 驱动的探索策略探索 Web 应用
"""

import asyncio
from typing import Dict, Any, Optional

from .explorer_agent import run_explore_agent, ExplorationResult


async def explore(
    config: Dict[str, Any],
    browser,
    logger,
    run_id: str,
    cwd: str = ".",
) -> "ExplorationResult":
    """
    探索 Web 应用

    Args:
        config: 规划配置
        browser: Playwright browser
        logger: 日志器
        run_id: 运行 ID
        cwd: 工作目录

    Returns:
        ExplorationResult
    """
    from ...browser import create_browser_page
    from .explorer_agent import ExplorationResult

    # 创建浏览器上下文和页面
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
    )
    page = await context.new_page()

    try:
        # 使用探索 Agent
        result = await run_explore_agent(
            run_id=run_id,
            config=config,
            page=page,
            cwd=cwd,
            logger=logger,
        )

        return result

    finally:
        await page.close()
        await context.close()