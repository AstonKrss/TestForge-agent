"""
TestForge 原创功能示例
======================

展示 TestForge 的 5 大原创创新功能
"""

import asyncio
import time


async def demo_smart_wait():
    """演示 SmartWait 智能等待"""
    from TestForge.src.smart_wait import create_smart_wait, WaitConfig
    from TestForge.src.browser import create_browser

    print("\n" + "=" * 60)
    print("🎯 功能1: SmartWait - 智能等待")
    print("=" * 60)

    result = await create_browser(headless=True)
    if not result.get("ok"):
        print(f"Browser failed: {result}")
        return

    browser = result.get("browser")
    ctx = await browser.new_context()
    page = await ctx.new_page()

    try:
        # 创建智能等待实例
        sw = create_smart_wait(page, WaitConfig(timeout_ms=5000))

        # 加载测试页面
        await page.set_content("""
            <html><body>
                <div id="loading" style="display:none">Loaded!</div>
                <button id="btn">Click me</button>
            </body></html>
        """)

        print("\n1. 等待元素出现...")
        # SmartWait 会智能选择等待策略
        sw.for_element("#btn").to_appear()

        print("   ✓ 元素出现了!")

        print("\n2. 等待元素变为可见...")
        await page.locator("#loading").evaluate("el => el.style.display = 'block'")
        sw.for_element("#loading").to_appear()

        print("   ✓ 元素可见了!")

        print("\n3. 等待网络空闲...")
        await page.evaluate("""
            fetch('/fake-api').then(() => {});
        """)
        sw.for_network_idle().to_idle()

        print("   ✓ 网络空闲!")

    except Exception as e:
        print(f"   ✗ Error: {e}")
    finally:
        await page.close()
        await ctx.close()


async def demo_intent_engine():
    """演示 Intent Engine 意图推断"""
    from TestForge.src.intent_engine import create_intent_engine, IntentType

    print("\n" + "=" * 60)
    print("🎯 功能2: Intent Engine - 意图推断")
    print("=" * 60)

    engine = create_intent_engine()

    # 测试各种中文步骤
    test_steps = [
        "打开登录页面",
        "输入用户名 为 testuser",
        "输入密码 填成 secret123",
        "点击登录按钮",
        "等待 3 秒",
        "验证欢迎信息 存在",
        "确认页面 包含 测试用户",
    ]

    print("\n中文步骤 → 意图推断结果:\n")
    for step in test_steps:
        intent = engine.parse(step)
        icon = "✓" if intent.confidence > 0.7 else "✗"
        print(f"   {icon} \"{step}\"")
        print(f"     → 类型: {intent.type.value}, 置信度: {intent.confidence:.0%}")
        if intent.target:
            print(f"     → 目标: {intent.target}")
        if intent.value:
            print(f"     → 值: {intent.value}")
        print()


async def demo_adaptive_locator():
    """演示 Adaptive Locator 自适应定位"""
    from TestForge.src.adaptive_locator import get_adaptive_locator

    print("\n" + "=" * 60)
    print("🎯 功能3: Adaptive Locator - 自适应定位")
    print("=" * 60)

    al = get_adaptive_locator()

    # 模拟历史记录
    print("\n1. 模拟定位器使用历史...")

    test_cases = [
        ("登录按钮", "role", "button", True),
        ("登录按钮", "text", "登录", True),
        ("登录按钮", "text", "登录", False),  # 失败一次
        ("登录按钮", "role", "button", True),
        ("用户名", "label", "用户名", True),
        ("用户名", "placeholder", "请输入用户名", True),
    ]

    for element_id, loc_type, value, success in test_cases:
        al.record_attempt(element_id, loc_type, value, success, duration_ms=50)

    print("   ✓ 记录了 6 次尝试")

    # 获取统计
    print("\n2. 查看成功率统计...")
    stats = al.get_stats("登录按钮")
    for key, stat in stats.items():
        print(f"   • {stat['type']}: {stat['value']}")
        print(f"     成功率: {stat['successRate']:.0%}, 尝试: {stat['attempts']}")

    # 获取最佳定位器
    print("\n3. 获取最佳定位器...")
    candidates = [
        ("role", "button"),
        ("text", "登录"),
        ("data_test", "login-btn"),
    ]
    best = al.get_best_locator("登录按钮", candidates)
    if best:
        print(f"   ✓ 最佳定位器: {best[0]} = {best[1]}")


async def demo_multimodal_assert():
    """演示 MultiModal Assert 多模态断言"""
    from TestForge.src.multimodal_assert import assert_that
    from TestForge.src.browser import create_browser

    print("\n" + "=" * 60)
    print("🎯 功能4: MultiModal Assert - 多模态断言")
    print("=" * 60)

    result = await create_browser(headless=True)
    if not result.get("ok"):
        print(f"Browser failed: {result}")
        return

    browser = result.get("browser")
    ctx = await browser.new_context()
    page = await ctx.new_page()

    try:
        await page.set_content("""
            <html><body>
                <form>
                    <input id="username" placeholder="用户名" />
                    <input id="password" type="password" placeholder="密码" />
                    <button id="submit" type="submit" style="background: blue; width: 100px; height: 40px">登录</button>
                </form>
                <div id="welcome" style="display:none">欢迎回来!</div>
            </body></html>
        """)

        print("\n1. 断言元素可见...")
        result = assert_that(page).element("#submit").is_visible()
        print(f"   ✓ 按钮可见: {result.ok}")

        print("\n2. 断言元素尺寸...")
        result = assert_that(page).element("#submit").size_in_range(
            min_width=50, max_width=200,
            min_height=30, max_height=50
        )
        print(f"   ✓ 尺寸符合范围: {result.ok}")

        print("\n3. 断言元素颜色...")
        result = assert_that(page).element("#submit").has_color("blue")
        print(f"   ✓ 蓝色按钮: {result.ok}")

        print("\n4. 组合断言...")
        result = assert_that(page).element("#submit").is_visible()
        result2 = assert_that(page).element("#submit").is_enabled()
        print(f"   ✓ 可见且启用: {result.ok and result2.ok}")

    except Exception as e:
        print(f"   ✗ Error: {e}")
    finally:
        await page.close()
        await ctx.close()


async def demo_test_evolution():
    """演示 Test Evolution 测试演化"""
    from TestForge.src.test_evolution import get_evolution, FailureReason

    print("\n" + "=" * 60)
    print("🎯 功能5: Test Evolution - 测试演化")
    print("=" * 60)

    evo = get_evolution()

    print("\n1. 模拟失败场景...")

    # 模拟一系列失败
    scenarios = [
        ("登录按钮", ("text", "登录"), FailureReason.ELEMENT_NOT_FOUND),
        ("登录按钮", ("text", "登录"), FailureReason.ELEMENT_NOT_VISIBLE),
    ]

    for element_id, locator, reason in scenarios:
        alternatives = evo.evolve(element_id, locator, reason)
        print(f"   失败: {locator} → {len(alternatives)} 个替代方案")
        for alt in alternatives[:3]:
            print(f"     • {alt}")

    print("\n2. 模拟成功记录...")
    evo.record_success("登录按钮", ("role", "button"), duration_ms=45)
    evo.record_success("登录按钮", ("text", "登录"), duration_ms=50)

    print("   ✓ 记录了 2 次成功定位")

    print("\n3. 获取推荐定位器...")
    recommended = evo.get_recommended_locator("登录按钮")
    if recommended:
        print(f"   ✓ 推荐: {recommended[0]} = {recommended[1]}")

    print("\n4. 失败模式统计...")
    patterns = evo.get_failure_patterns("登录按钮")
    for reason, count in patterns.items():
        print(f"   • {reason}: {count} 次")


async def main():
    """运行所有演示"""
    print("\n" + "=" * 60)
    print("🚀 TestForge 原创功能演示")
    print("=" * 60)

    await demo_smart_wait()
    await demo_intent_engine()
    await demo_adaptive_locator()
    await demo_multimodal_assert()
    await demo_test_evolution()

    print("\n" + "=" * 60)
    print("🎉 所有原创功能演示完成!")
    print("=" * 60)
    print("""
这些是 TestForge 的原创创新:

1. SmartWait - 不是傻等，是观察DOM变化
2. Intent Engine - 直接写中文，AI自动理解
3. Adaptive Locator - 记录成功率，越用越准
4. MultiModal Assert - 不仅断言文本，还支持截图对比
5. Test Evolution - 从失败中学习，自动修复
""")


if __name__ == "__main__":
    asyncio.run(main())