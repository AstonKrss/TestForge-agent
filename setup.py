#!/usr/bin/env python
"""
TestForge 初始化脚本
===================

运行此脚本进行首次配置或启动程序
"""

import sys
import os

sys.path.insert(0, '.')

from src.init import load_config, apply_config


def show_menu():
    """显示主菜单"""
    print()
    print("=" * 60)
    print("   TestForge - AI Web Testing Framework")
    print("=" * 60)
    print()
    print("  1. 配置 AI (选择厂商/输入Key/测试连接)")
    print("  2. 启动 CLI 交互模式 (推荐)")
    print("  3. 启动 Agent 程序")
    print("  4. 交互式测试工具")
    print("  5. 查看当前配置")
    print("  6. 卸载/删除配置")
    print("  0. 退出")
    print()
    return input("请选择 (0-6): ").strip()


def option_config():
    """配置 AI"""
    print("\n启动配置向导...\n")

    import asyncio
    from src.init import init

    async def run_init():
        config = await init()
        return config

    asyncio.run(run_init())


def option_agent():
    """启动 Agent 程序"""
    print("\n启动 Agent...\n")

    # 应用配置
    if not apply_config():
        print("没有找到配置文件，请先配置 AI")
        print("运行 python setup.py 选择 1 进行配置")
        return

    # 检查 API key
    from src.ai_client import check_api_key
    provider = check_api_key()
    if not provider:
        print("\n没有检测到 API key")
        return

    import asyncio
    from src.ai_agent import AIAgent
    from src.browser import create_browser

    async def run_agent():
        result = await create_browser(headless=False)
        if not result.get("ok"):
            print(f"启动浏览器失败: {result}")
            return

        browser = result["browser"]
        page = await browser.new_page()

        # 创建 AI Agent（不使用 MCP Server，直接执行工具）
        agent = AIAgent(
            page=page,
            base_url="http://47.242.21.40",
            ai_client=None,  # 会在内部创建
            mcp_server=None,  # 直接执行，不通过 MCP
        )

        print("\n输入测试目标（中文），输入 q 退出")
        print("-" * 40)

        while True:
            try:
                goal = input("\n目标> ").strip()
            except EOFError:
                break
            if goal.lower() in ('q', 'quit', 'exit'):
                break
            if not goal:
                continue

            try:
                await agent.run(goal)
            except KeyboardInterrupt:
                print("\n已中断")
                break
            except Exception as e:
                print(f"\n错误: {e}")

        await page.close()
        await browser.close()

    asyncio.run(run_agent())


def option_cli():
    """启动 CLI 交互模式"""
    print("\n启动 TestForge CLI...\n")

    # 应用配置
    if not apply_config():
        print("没有找到配置文件，请先配置 AI")
        print("运行 python setup.py 选择 1 进行配置")
        return

    # 检查 API key
    from src.ai_client import check_api_key
    provider = check_api_key()
    if not provider:
        print("\n没有检测到 API key")
        return

    import subprocess
    import os
    root = os.path.dirname(os.path.abspath(__file__)) or '.'
    subprocess.run([sys.executable, os.path.join(root, "run_cli.py")])


def option_interactive():
    """交互式测试工具"""
    print("\n启动交互式测试...\n")

    try:
        from examples.interactive import main as interactive_main
        import asyncio
        asyncio.run(interactive_main())
    except Exception as e:
        print(f"启动失败: {e}")


def option_view_config():
    """查看当前配置"""
    config = load_config()
    if not config:
        print("\n没有找到配置文件")
        print("运行 python setup.py 选择 1 进行配置")
        return

    print("\n当前配置:")
    print("-" * 40)
    print(f"  AI 厂商:   {config.ai_provider}")
    print(f"  AI 模型:   {config.ai_model}")
    print(f"  浏览器:     {config.chromium_channel}")
    print(f"  基础URL:   {config.base_url}")
    if config.api_key:
        masked = config.api_key[:8] + "..." + config.api_key[-4:]
        print(f"  API Key:   {masked}")


def option_uninstall():
    """删除配置"""
    print("\n删除配置文件...")

    from src.init import InitWizard
    wizard = InitWizard()

    if wizard.config_file.exists():
        print(f"  删除: {wizard.config_file}")
        wizard.config_file.unlink()
        print("  已删除")
    else:
        print("  没有找到配置文件")

    # 清除环境变量
    env_vars = [
        "TF_AI_PROVIDER", "TF_AI_MODEL", "TF_BASE_URL",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY", "MINIMAX_API_KEY"
    ]
    for var in env_vars:
        if var in os.environ:
            del os.environ[var]
            print(f"  清除: {var}")


def main():
    while True:
        choice = show_menu()

        if choice == "1":
            option_config()
        elif choice == "2":
            option_cli()
        elif choice == "3":
            option_agent()
        elif choice == "4":
            option_interactive()
        elif choice == "5":
            option_view_config()
        elif choice == "6":
            option_uninstall()
        elif choice == "0":
            print("\n再见!")
            break
        else:
            print("\n无效选择，请重试")


if __name__ == "__main__":
    main()