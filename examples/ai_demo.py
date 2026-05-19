"""
TestForge AI 客户端演示
=======================

演示如何使用 AI (Claude/GPT) 来驱动自动化测试
"""

import asyncio
import sys
import os

# Windows GBK encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')

from src.ai_client import (
    AIConfig, AIClient, ClaudeClient, OpenAIClient, LocalClient,
    GeminiClient, DeepSeekClient, QwenClient, KimiClient, MiniMaxClient,
    create_ai_client, AIAgent, check_api_key
)


async def demo_ai_config():
    """演示 AI 配置"""
    print("\n" + "=" * 60)
    print("AI 配置演示")
    print("=" * 60)

    # 检查 API key
    provider = check_api_key()

    if not provider:
        print("\n将使用规则引擎作为后备")
        print("或者设置环境变量后重试")

    # 演示配置创建
    print("\n支持的配置:")

    configs = [
        AIConfig(provider="claude", model="claude-3-5-sonnet-20241022"),
        AIConfig(provider="openai", model="gpt-4o"),
        AIConfig(provider="gemini", model="gemini-2.0-flash"),
        AIConfig(provider="deepseek", model="deepseek-chat"),
        AIConfig(provider="qwen", model="qwen-turbo"),
        AIConfig(provider="kimi", model="moonshot-v1-8k"),
        AIConfig(provider="minimax", model="abab6-chat"),
        AIConfig(provider="local", model="llama3", base_url="http://localhost:11434"),
    ]

    for config in configs:
        print(f"  - {config.provider}: {config.model}")


async def demo_ai_analysis():
    """演示 AI 分析功能"""
    print("\n" + "=" * 60)
    print("AI 分析演示")
    print("=" * 60)

    # 检查 API key
    provider = check_api_key()
    if not provider:
        print("\n跳过 AI 分析演示（需要 API key）")
        return

    # 创建客户端
    try:
        client = create_ai_client()
        print(f"\n创建 AI 客户端: {client.config.provider}")

        # 演示分析
        print("\n分析测试目标...")
        response = await client.complete(
            """分析以下 Web 测试目标，识别关键步骤和元素。
格式: 列出主要步骤和需要关注的元素

目标: 登录博客系统，用户名为 admin，密码为 secret123，验证登录成功
""",
            system="你是一个测试规划助手，简洁回答。"
        )

        print(f"\n分析结果:\n{response[:500]}...")

    except Exception as e:
        print(f"\nAI 调用失败: {e}")
        print("可能原因:")
        print("  - API key 无效或过期")
        print("  - 网络连接问题")
        print("  - API 额度用完")


async def demo_ai_agent():
    """演示 AI Agent"""
    print("\n" + "=" * 60)
    print("AI Agent 演示")
    print("=" * 60)

    # 检查 API key
    provider = check_api_key()

    if not provider:
        print("\n跳过 AI Agent 演示")
        print("\n可以运行基础 Agent 演示:")
        print("  python examples/agent_demo.py")
        return

    # 创建浏览器
    print("\n[1] 启动浏览器...")
    from src.browser import create_browser
    result = await create_browser(headless=False)
    if not result.get("ok"):
        print(f"   失败: {result}")
        return

    browser = result["browser"]
    page = await browser.new_page()
    print("   成功!")

    # 创建 AI Agent
    print("\n[2] 创建 AI Agent...")
    agent = AIAgent(
        page=page,
        base_url="http://47.242.21.40",
    )
    print(f"   AI Provider: {agent.ai_client.config.provider}")
    print(f"   Model: {agent.ai_client.config.model}")

    # 运行目标
    goal = input("\n请输入测试目标（或直接按回车使用默认）: ").strip()
    if not goal:
        goal = "打开登录页面"

    print(f"\n[3] 执行目标: {goal}")
    result = await agent.run(goal)

    print(f"\n[4] 结果: 成功={result.get('success')}, 轮次={result.get('turns')}")

    # 显示统计
    stats = agent.get_stats()
    print(f"   工具调用次数: {stats['tool_calls']}")

    # 关闭浏览器
    await page.close()
    await browser.close()


def demo_env_setup():
    """演示环境变量设置"""
    print("\n" + "=" * 60)
    print("环境变量设置指南")
    print("=" * 60)

    print("""
要使用 AI 功能，需要设置 API key:

1. Claude (推荐):
   set ANTHROPIC_API_KEY=sk-ant-xxxxx

2. OpenAI GPT:
   set OPENAI_API_KEY=sk-xxxxx

3. 本地模型 (Ollama):
   set TF_AI_PROVIDER=local
   set LOCAL_MODEL_URL=http://localhost:11434

4. 查看当前设置:
   python -c "from src.ai_client import check_api_key; check_api_key()"
""")


async def main():
    print("""
============================================================
TestForge AI 客户端演示
============================================================

选项:
1. 查看配置
2. AI 分析演示
3. AI Agent 演示
4. 环境变量设置指南
5. 全部运行

请选择 (1-5):
""")

    choice = input().strip()

    if choice == "1":
        await demo_ai_config()
    elif choice == "2":
        await demo_ai_analysis()
    elif choice == "3":
        await demo_ai_agent()
    elif choice == "4":
        demo_env_setup()
    elif choice == "5":
        await demo_ai_config()
        await demo_ai_analysis()
        await demo_ai_agent()
        demo_env_setup()
    else:
        await demo_ai_config()


if __name__ == "__main__":
    asyncio.run(main())