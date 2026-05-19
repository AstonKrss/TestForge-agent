"""
TestForge Agent 使用示例
========================

用自然语言描述目标，Agent 自动规划并执行
"""

import asyncio
import sys

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')

from src.agent import Agent, AgentConfig, Memory, Planner
from src.browser import create_browser


async def demo_agent():
    """演示 Agent 功能"""

    # 创建浏览器
    print("\n[1] 启动浏览器...")
    result = await create_browser(headless=False)
    browser = result["browser"]
    page = await browser.new_page()

    print("   OK: 浏览器已启动")

    # 创建 Agent
    agent = Agent(
        page=page,
        base_url="http://47.242.21.40",
        config=AgentConfig(
            max_retries=3,
            thinking_enabled=True,
            reflection_enabled=True
        )
    )

    print("\n" + "=" * 60)
    print("TestForge Agent 演示")
    print("=" * 60)

    # 演示规划器
    print("\n[规划器演示]")
    goals = [
        "打开登录页面",
        "点击登录",
        "输入用户名 为 admin",
        "输入密码 为 123456",
    ]

    steps = Planner.parse_goal(";".join(goals))
    print(f"   目标: {'; '.join(goals)}")
    print(f"   解析为 {len(steps)} 个步骤:")
    for step in steps:
        print(f"     {step.index}. {step.action} -> {step.target or step.value}")

    # 演示记忆系统
    print("\n[记忆系统演示]")
    memory = Memory(max_size=10)

    # 添加一些记忆
    from src.agent import MemoryEntry
    memory.add(MemoryEntry(timestamp=0, action="click", target="登录", success=True))
    memory.add(MemoryEntry(timestamp=0, action="fill", target="username", success=True))
    memory.add(MemoryEntry(timestamp=0, action="fill", target="password", success=False, error="timeout"))

    stats = memory.get_stats()
    print(f"   记忆总数: {stats['total']}")
    print(f"   成功率: {stats['success_rate']:.0%}")
    print(f"   各动作统计:")
    for action, data in stats['actions'].items():
        print(f"     - {action}: {data['success']}/{data['total']} ({data['rate']:.0%})")

    # 演示 Agent 运行
    print("\n[Agent 运行演示]")
    print("   输入目标让 Agent 执行...")

    goal = input("\n   请输入目标 (输入 'quit' 退出): ").strip()

    if goal.lower() != 'quit' and goal:
        print()
        result = await agent.run(goal)
        print(f"\n   结果: {result['message']}")

    # 关闭浏览器
    await page.close()
    await browser.close()

    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)


async def demo_agent_auto():
    """自动演示 - 不需要用户输入"""

    print("\n[自动演示]")
    result = await create_browser(headless=False)
    browser = result["browser"]
    page = await browser.new_page()

    agent = Agent(
        page=page,
        base_url="http://47.242.21.40",
        config=AgentConfig(max_retries=2)
    )

    # 自动执行
    print("\n目标: 打开登录页面")
    print()
    result = await agent.run("打开登录页面")

    print(f"\n执行结果: {result['message']}")
    print(f"成功: {result['success']}")

    await page.close()
    await browser.close()


def demo_planner():
    """演示规划器"""

    print("\n" + "=" * 60)
    print("Planner 演示 - 自然语言转步骤")
    print("=" * 60)

    goals = [
        "打开登录页面; 输入用户名 为 admin; 输入密码 为 123456; 点击登录",
        "访问 /dashboard; 验证欢迎信息 存在",
        "去首页; 滚动页面; 等待 2 秒",
    ]

    for goal in goals:
        print(f"\n目标: {goal}")
        steps = Planner.parse_goal(goal)
        print(f"解析为 {len(steps)} 个步骤:")
        for step in steps:
            print(f"  [{step.index}] {step.action} -> {step.target or step.value}")

    print("\n" + "=" * 60)


def demo_memory():
    """演示记忆系统"""

    print("\n" + "=" * 60)
    print("Memory 演示 - 记住操作经验")
    print("=" * 60)

    memory = Memory(max_size=20)

    from src.agent import MemoryEntry

    # 模拟一系列操作
    operations = [
        ("navigate", "/login", True, None),
        ("fill", "username", True, None),
        ("fill", "password", True, None),
        ("click", "登录按钮", False, "not visible"),
        ("click", "登录按钮", True, None),
        ("assert_text", "登录成功", True, None),
    ]

    print("\n模拟操作记录:")
    for action, target, success, error in operations:
        memory.add(MemoryEntry(
            timestamp=0,
            action=action,
            target=target,
            success=success,
            error=error
        ))
        status = "成功" if success else "失败"
        print(f"  {action} {target} -> {status}")

    # 显示统计
    stats = memory.get_stats()
    print(f"\n记忆统计:")
    print(f"  总操作: {stats['total']}")
    print(f"  成功率: {stats['success_rate']:.0%}")

    # 获取失败模式
    failed = memory.get_failed_patterns()
    if failed:
        print(f"\n失败模式 ({len(failed)} 个):")
        for entry in failed:
            print(f"  - {entry.action} {entry.target}: {entry.error}")

    # 获取相似经验
    similar = memory.get_similar("fill", "password")
    if similar:
        print(f"\n类似 'fill password' 的成功经验: {len(similar)} 个")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        asyncio.run(demo_agent_auto())
    elif len(sys.argv) > 1 and sys.argv[1] == "--planner":
        demo_planner()
    elif len(sys.argv) > 1 and sys.argv[1] == "--memory":
        demo_memory()
    else:
        print("""
TestForge Agent 演示
====================

用法:
  python examples/agent_demo.py           # 交互式演示
  python examples/agent_demo.py --auto   # 自动演示
  python examples/agent_demo.py --planner # 规划器演示
  python examples/agent_demo.py --memory  # 记忆系统演示
""")
        demo_planner()
        demo_memory()
        print("\n运行交互式演示:")
        print("  python examples/agent_demo.py")
        asyncio.run(demo_agent())