"""
TestForge CLI 使用示例
=======================

演示如何使用 TestForge 进行自动化测试
"""

import asyncio


async def example_basic():
    """基础示例"""
    from TestForge.src.tools import click, fill, navigate, assert_text_present
    from TestForge.src.browser import create_browser

    print("=" * 60)
    print("TestForge 基础示例")
    print("=" * 60)

    # 创建浏览器
    result = await create_browser(headless=True)
    if not result.get("ok"):
        print(f"Browser failed: {result}")
        return

    browser = result.get("browser")

    # 创建上下文和页面
    ctx = await browser.new_context()
    page = await ctx.new_page()

    try:
        # 导航
        print("\n1. 导航到示例页面...")
        result = await navigate(page, "https://example.com", "/")
        print(f"   Result: {result.get('ok', False)}")

        # 断言
        print("\n2. 断言页面包含文本...")
        result = await assert_text_present(page, "Example Domain")
        print(f"   Result: {result.get('ok', False)}")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
    finally:
        await page.close()
        await ctx.close()


async def example_ref_first():
    """Ref-First 定位示例"""
    from TestForge.src.tools import click, fill
    from TestForge.src.browser import create_browser

    print("\n" + "=" * 60)
    print("TestForge Ref-First 定位示例")
    print("=" * 60)

    result = await create_browser(headless=True)
    if not result.get("ok"):
        print(f"Browser failed: {result}")
        return

    browser = result.get("browser")
    ctx = await browser.new_context()
    page = await ctx.new_page()

    try:
        await page.goto("https://example.com")

        # 模拟快照中的 ref
        print("\n1. 使用 ref 定位 (aria-ref=e15)...")
        # result = await click(page, ref="e15")  # 需要快照获取的 ref
        print("   (ref 定位需要先调用 snapshot 获取元素引用)")

        # 使用描述定位作为降级
        print("\n2. 使用描述定位...")
        result = await click(page, description="More information...")
        print(f"   Result: {result.get('ok', False)}")

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
    finally:
        await page.close()
        await ctx.close()


async def example_form_fill():
    """表单填写示例"""
    from TestForge.src.tools import fill, click
    from TestForge.src.browser import create_browser

    print("\n" + "=" * 60)
    print("TestForge 表单填写示例")
    print("=" * 60)

    result = await create_browser(headless=True)
    if not result.get("ok"):
        print(f"Browser failed: {result}")
        return

    browser = result.get("browser")
    ctx = await browser.new_context()
    page = await ctx.new_page()

    try:
        # 模拟登录页面
        await page.set_content("""
            <html>
            <body>
                <form>
                    <input name="username" placeholder="Username" />
                    <input name="password" type="password" placeholder="Password" />
                    <button type="submit">Login</button>
                </form>
            </body>
            </html>
        """)

        print("\n1. 填写用户名...")
        result = await fill(page, description="username", text="testuser")
        print(f"   Fill Value: {result.get('data', {}).get('fill_value', {})}")

        print("\n2. 填写密码 (自动脱敏)...")
        result = await fill(page, description="password", text="secret123", is_password=True)
        print(f"   Fill Value: {result.get('data', {}).get('fill_value', {})}")

        print("\n3. 点击登录按钮...")
        result = await click(page, description="Login")
        print(f"   Result: {result.get('ok', False)}")

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
    finally:
        await page.close()
        await ctx.close()


async def main():
    """运行所有示例"""
    print("\n" + "=" * 60)
    print("🎯 TestForge - AI驱动的Web测试自动化框架")
    print("=" * 60)

    await example_basic()
    await example_ref_first()
    await example_form_fill()

    print("\n" + "=" * 60)
    print("示例完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())