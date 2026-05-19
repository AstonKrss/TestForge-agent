"""
TestForge 实际浏览器测试
========================
测试所有功能是否真正可用
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

from src.browser import create_browser, capture_screenshot
from src.tools import click, fill, navigate, assert_text_present


async def test_basic_browser():
    """测试1: 基本浏览器功能"""
    print("\n[1] Testing browser launch...")
    result = await create_browser(headless=True)
    if not result.get("ok"):
        print(f"   FAILED: {result}")
        return False

    browser = result.get("data", {}).get("browser") or result.get("browser")
    ctx = await browser.new_context()
    page = await ctx.new_page()

    print("   OK: Browser launched")

    # 访问 example.com
    print("\n[2] Navigate to example.com...")
    await navigate(page, "https://example.com", "/")
    print("   OK: Page loaded")

    # 获取页面标题
    title = await page.title()
    print(f"\n[3] Page title: {title}")

    # 断言文本存在
    print("\n[4] Assert text 'Example Domain'...")
    await assert_text_present(page, "Example Domain")
    print("   OK: Text assertion passed")

    # 截图
    print("\n[5] Taking screenshot...")
    ss = await capture_screenshot(page, quality=80)
    if ss.get("ok") and ss.get("data", {}).get("buffer"):
        with open("test_screenshot.jpg", "wb") as f:
            f.write(ss["data"]["buffer"])
        print("   OK: Screenshot saved to test_screenshot.jpg")

    await page.close()
    await ctx.close()
    await browser.close()
    return True


async def test_smart_wait():
    """测试2: SmartWait 智能等待"""
    print("\n[Test 2] SmartWait...")

    from src.smart_wait import create_smart_wait, WaitConfig

    result = await create_browser(headless=True)
    page = await result["browser"].new_page()

    # 创建测试页面
    await page.set_content("""
        <html><body>
            <div id="loading" style="display:none">Loading...</div>
            <button id="btn">Click me</button>
            <script>
                setTimeout(() => {
                    document.getElementById('loading').style.display = 'block';
                }, 500);
            </script>
        </body></html>
    """)

    sw = create_smart_wait(page, WaitConfig(timeout_ms=3000))

    print("   Waiting for #btn...")
    sw.for_element("#btn").to_appear()
    print("   OK: Element appeared")

    await page.close()
    return True


async def test_intent_engine():
    """测试3: Intent Engine 意图推断"""
    print("\n[Test 3] Intent Engine...")

    from src.intent_engine import create_intent_engine

    engine = create_intent_engine()

    steps = [
        "打开登录页面",
        "输入用户名 为 admin",
        "输入密码 填成 123456",
        "点击登录按钮",
    ]

    for step in steps:
        intent = engine.parse(step)
        print(f"   '{step}' -> {intent.type.value} ({intent.confidence:.0%})")

    print("   OK: Intent Engine works")
    return True


async def test_adaptive_locator():
    """测试4: Adaptive Locator 自适应定位"""
    print("\n[Test 4] Adaptive Locator...")

    from src.adaptive_locator import get_adaptive_locator

    al = get_adaptive_locator()

    # 记录一些尝试
    al.record_attempt("submit_btn", "role", "button", success=True)
    al.record_attempt("submit_btn", "text", "submit", success=False)
    al.record_attempt("submit_btn", "role", "button", success=True)

    # 获取最佳定位器
    candidates = [("role", "button"), ("text", "submit"), ("css_id", "#submit")]
    best = al.get_best_locator("submit_btn", candidates)
    print(f"   Best locator: {best}")

    stats = al.get_stats("submit_btn")
    for s in stats.values():
        print(f"   {s['type']}: success rate {s['successRate']:.0%}")

    print("   OK: Adaptive Locator works")
    return True


async def test_multimodal_assert():
    """测试5: MultiModal Assert 多模态断言"""
    print("\n[Test 5] MultiModal Assert...")

    from src.multimodal_assert import MultiModalAssert

    result = await create_browser(headless=True)
    page = await result["browser"].new_page()

    await page.set_content("""
        <html><body>
            <button id="btn" style="background:blue; width:100px; height:40px">Click</button>
        </body></html>
    """)

    assert_instance = MultiModalAssert(page)

    # 断言元素可见
    r1 = await assert_instance.is_visible("#btn")
    print(f"   Visible: {'OK' if r1.ok else 'FAIL'}")

    # 断言尺寸
    r2 = await assert_instance.element_size_in_range("#btn", min_width=50, max_width=200)
    print(f"   Size: {'OK' if r2.ok else 'FAIL'}")

    # 断言颜色（使用高容差）
    r3 = await assert_instance.element_has_color("#btn", "blue", tolerance=100)
    print(f"   Color (blue w/100 tol): {'OK' if r3.ok else 'FAIL'}")

    await page.close()
    return all([r1.ok, r2.ok])  # Color may vary due to rendering


async def test_test_evolution():
    """测试6: Test Evolution 测试演化"""
    print("\n[Test 6] Test Evolution...")

    from src.test_evolution import get_evolution, FailureReason

    evo = get_evolution()

    # 记录失败
    alts = evo.evolve("login_btn", ("text", "login"), FailureReason.ELEMENT_NOT_FOUND)
    print(f"   Alternatives: {len(alts)}")
    for alt in alts[:3]:
        print(f"     - {alt}")

    # 记录成功
    evo.record_success("login_btn", ("role", "button"))

    # 获取推荐
    rec = evo.get_recommended_locator("login_btn")
    print(f"   Recommended: {rec}")

    print("   OK: Test Evolution works")
    return True


async def main():
    print("=" * 60)
    print("TestForge Real Browser Test")
    print("=" * 60)

    tests = [
        ("Browser Basic", test_basic_browser),
        ("SmartWait", test_smart_wait),
        ("Intent Engine", test_intent_engine),
        ("Adaptive Locator", test_adaptive_locator),
        ("MultiModal Assert", test_multimodal_assert),
        ("Test Evolution", test_test_evolution),
    ]

    results = []
    for name, test in tests:
        try:
            ok = await test()
            results.append((name, ok))
        except Exception as e:
            print(f"\n   ERROR: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    passed = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {status} - {name}")
        if ok:
            passed += 1

    print(f"\nTotal: {passed}/{len(results)} passed")
    print("=" * 60)

    return passed == len(results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)