"""
Startup Menu - 启动菜单
======================

显示主菜单：
1. 配置 API
2. 进入 CLI 测试
3. 运行测试用例
4. 加载会话
0. 退出

如果已配置过 API key，直接进入 CLI。
"""

import sys
from pathlib import Path
import os

# Python 3.7+ 默认 UTF-8，不需要手动包装 stdout


def show_banner():
    """显示横幅"""
    print()
    print("=" * 64)
    print("  TestForge CLI  -  AI 自动化 Web 测试工作台")
    print("=" * 64)
    print("  MainAgent 规划  |  BrowserAgent 执行  |  VerifierAgent 断言")
    print("  支持: 功能测试 / 全量测试 / 性能压测 / 安全无障碍 / 报告")
    print()


def show_menu():
    """显示菜单"""
    print("  1. 配置 API            选择 AI 厂商 / 输入 Key / 写入配置文件")
    print("  2. 进入 CLI 测试        打开浏览器，开始自然语言自动测试")
    print("  3. 运行测试用例         导入 Markdown 用例执行")
    print("  4. 加载本地会话         继续上次项目 / 回归测试 / 查看历史上下文")
    print()
    print("  常用示例:")
    print("    完整测试 http://example.com 并生成报告")
    print("    测试当前页面所有已知功能")
    print("    压力测试 http://example.com 50次 并发5")
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


async def option_enter_cli(load_session_name: str = ""):
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
        video_dir = Path.home() / ".testforge" / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(video_dir),
        )
    page = await context.new_page()

    # 创建并运行主 Agent
    from .main_agent import MainAgent
    from .main_agent import SessionContext
    from ..ai_client import create_ai_client
    from ..config_loader import get_ai_config_for_client

    ai_config = get_ai_config_for_client()
    ai_client = create_ai_client(ai_config)
    main_agent = MainAgent(page=page, ai_client=ai_client)
    if load_session_name:
        try:
            data = main_agent.session_store.load(load_session_name)
            main_agent.context = SessionContext.from_dict(data)
            main_agent.context.session_name = data.get("session_name") or load_session_name
            print(f"  ✓ 已加载会话: {main_agent.context.session_name}")
            print(f"  {main_agent.context.to_summary()}")
            if main_agent.context.current_url:
                await main_agent._handle_navigate(main_agent.context.current_url)
        except FileNotFoundError as e:
            print(f"  ✗ {e}")
            return False

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


async def option_load_session():
    """从启动菜单加载本地会话并进入 CLI"""
    from ..config_loader import has_api_key
    from .session_store import SessionStore

    if not has_api_key():
        print()
        print("  ✗ 未配置 API Key")
        print("  请先选择 1 配置 API")
        print()
        return False

    store = SessionStore()
    sessions = store.list()
    if not sessions:
        print()
        print("  暂无本地会话。进入 CLI 后可以用：保存会话 blog-test")
        print()
        return False

    print()
    print("[本地会话]")
    for index, item in enumerate(sessions[:20], 1):
        print(f"  {index}. {item['name']} | {item.get('updated_at', '')} | {item.get('current_url', '')}")
    print()
    raw = input("  请输入会话名或序号: ").strip()
    if not raw:
        print("  ✗ 会话名不能为空")
        return False

    session_name = raw
    if raw.isdigit():
        index = int(raw) - 1
        if 0 <= index < len(sessions[:20]):
            session_name = sessions[index]["name"]
        else:
            print("  ✗ 序号无效")
            return False

    return await option_enter_cli(load_session_name=session_name)


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
            choice = input("  请选择 (0-4): ").strip()

            if choice == "1":
                await option_config_api()
            elif choice == "2":
                success = await option_enter_cli()
                if success:
                    break
            elif choice == "3":
                await option_run_spec()
            elif choice == "4":
                success = await option_load_session()
                if success:
                    break
            elif choice == "0":
                print("\n  再见!\n")
                break
            else:
                print("\n  无效选择，请重试\n")

    try:
        asyncio.run(async_run())
    except KeyboardInterrupt:
        print("\n\n  已退出\n")
