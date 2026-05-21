"""
Startup Menu - 启动菜单
======================

显示主菜单：
1. 配置 API
2. 进入 CLI 测试
3. 退出

如果已配置过 API key，直接进入 CLI。
"""

import sys
import os

# Python 3.7+ 默认 UTF-8，不需要手动包装 stdout


def show_banner():
    """显示横幅"""
    print()
    print("=" * 56)
    print("  TestForge CLI  -  AI 自动化 Web 测试")
    print("=" * 56)
    print()


def show_menu():
    """显示菜单"""
    print("  1. 配置 API          - 选择 AI 厂商 / 输入 Key / 写入配置文件")
    print("  2. 进入 CLI 测试      - 打开浏览器，开始交互测试")
    print("  3. 运行测试用例       - 导入 Markdown 用例执行")
    print()
    print("  0. 退出")
    print()


def load_existing_config():
    """加载已有配置"""
    try:
        from ..config_loader import load, has_api_key
        config = load()
        if has_api_key():
            return config
        return None
    except Exception:
        return None


async def option_config_api():
    """配置 API"""
    print()
    print("[配置 API]")
    print()

    from ..init import init

    config = await init()
    print()
    print(f"  ✓ 配置完成: {config.ai_provider} / {config.ai_model}")
    print()
    return config


async def option_enter_cli():
    """进入 CLI 测试模式"""
    from ..config_loader import has_api_key, load

    if not has_api_key():
        print()
        print("  ✗ 未配置 API Key")
        print()
        print("  请先选择 1 配置 API")
        print()
        return False

    # 加载配置
    config = load()

    print()
    print(f"[启动 CLI]  AI: {config.ai.provider} / {config.ai.model}")
    print()

    # 启动浏览器
    from ..browser import create_browser
    browser_result = await create_browser(headless=False)
    if not browser_result.get("ok"):
        print(f"  ✗ 浏览器启动失败: {browser_result.get('error')}")
        return False

    browser = browser_result["browser"]
    playwright = browser_result.get("playwright")
    context = browser_result.get("context")
    if context is None:
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()

    # 创建并运行主 Agent
    from .main_agent import MainAgent
    from ..ai_client import create_ai_client
    from ..config_loader import get_ai_config_for_client

    ai_config = get_ai_config_for_client()
    ai_client = create_ai_client(ai_config)
    main_agent = MainAgent(page=page, ai_client=ai_client)

    try:
        await main_agent.run()
    except KeyboardInterrupt:
        print("\n\n  已退出")
    finally:
        for closeable in (context, browser):
            try:
                await closeable.close()
            except BaseException:
                pass
        if playwright:
            try:
                await playwright.stop()
            except BaseException:
                pass
        try:
            await asyncio.sleep(0.2)
        except BaseException:
            pass

    return True


async def option_run_spec():
    """运行 Markdown 测试用例"""
    from ..config_loader import has_api_key

    if not has_api_key():
        print()
        print("  ✗ 未配置 API Key")
        print("  请先选择 1 配置 API")
        print()
        return False

    spec_path = input("  请输入测试用例 Markdown 文件路径: ").strip().strip('"')
    if not spec_path:
        print("  ✗ 路径不能为空")
        return False

    from .main_agent import run_spec_file_once

    return await run_spec_file_once(spec_path)


def run():
    """运行启动菜单"""
    import asyncio

    async def async_run():
        show_banner()

        # 检查已有配置，但仍然显示菜单，让用户明确选择下一步
        existing = load_existing_config()

        if existing:
            from ..config_loader import has_api_key
            if has_api_key():
                print("  检测到已有配置，可直接进入 CLI")
                print()

        # 显示菜单
        while True:
            show_menu()
            choice = input("  请选择 (0-3): ").strip()

            if choice == "1":
                await option_config_api()
            elif choice == "2":
                success = await option_enter_cli()
                if success:
                    break
            elif choice == "3":
                await option_run_spec()
            elif choice == "0":
                print("\n  再见!\n")
                break
            else:
                print("\n  无效选择，请重试\n")

    try:
        asyncio.run(async_run())
    except KeyboardInterrupt:
        print("\n\n  已退出\n")
