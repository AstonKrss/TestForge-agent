"""
TestForge CLI - 主入口
=====================

两层 Agent 架构:
1. 主Agent (Planner): 理解用户、规划任务、询问用户、汇总结果
2. 执行Agent (Executor): 打开浏览器、执行操作、返回结果
"""

import asyncio
import sys
import os

# Windows encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')
# 添加 src 目录
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, src_path)

from src.browser import create_browser


async def main():
    """主入口"""
    print("=" * 60)
    print("TestForge CLI - AI 自动化测试框架")
    print("=" * 60)
    print()

    # 启动浏览器
    print("[1/2] 启动浏览器...")
    result = await create_browser(headless=False)
    if not result.get("ok"):
        print(f"  失败: {result.get('error')}")
        return

    browser = result["browser"]
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()
    print("  成功: 浏览器已启动")
    print()

    # 导入并启动主 Agent (从 src.cli)
    import importlib.util
    root = os.path.dirname(os.path.abspath(__file__))
    src_cli_path = os.path.join(root, "..", "src", "cli", "main_agent.py")
    spec = importlib.util.spec_from_file_location("main_agent", src_cli_path)
    ma = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ma)
    main_agent = ma.MainAgent(page)

    try:
        await main_agent.run()
    except KeyboardInterrupt:
        print("\n\n已退出")
    finally:
        await page.close()
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())