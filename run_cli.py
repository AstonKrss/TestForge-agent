"""
TestForge CLI - 主入口（独立运行，不依赖 cli 包）
"""

import asyncio
import sys
import os

# 添加项目路径
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)

# Windows encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


async def main():
    """主入口"""
    print("=" * 60)
    print("TestForge CLI - AI 自动化测试框架")
    print("=" * 60)
    print()

    # 启动浏览器
    print("[1/2] 启动浏览器...")
    from src.browser import create_browser
    result = await create_browser(headless=False)
    if not result.get("ok"):
        print(f"  失败: {result.get('error')}")
        return

    browser = result["browser"]
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()
    print("  成功: 浏览器已启动")
    print()

    # 导入并运行主 Agent
    from src.cli.main_agent import MainAgent
    main_agent = MainAgent(page)

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