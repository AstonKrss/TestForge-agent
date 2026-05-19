"""
TestForge 交互式测试工具
=======================

输入网址，然后进行各种自动化测试
"""

import asyncio
import sys

# Windows encoding fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, '.')

from src.browser import create_browser


def safe_input(prompt):
    """安全的 input 函数"""
    try:
        return input(prompt)
    except (EOFError, IOError):
        return ""


async def interactive_test():
    """交互式测试"""
    print("=" * 60)
    print("TestForge 交互式测试工具")
    print("=" * 60)
    print()

    # 获取网址
    url = safe_input("请输入网址 (例如 https://example.com): ").strip()
    if not url:
        url = "https://example.com"
        print(f"使用默认: {url}")

    print("\n[1] 启动浏览器...")
    result = await create_browser(headless=False)
    if not result.get("ok"):
        print(f"   失败: {result}")
        return

    browser = result["browser"]
    ctx = await browser.new_context()
    page = await ctx.new_page()

    print("   成功: 浏览器已启动")

    # 导航
    print(f"\n[2] 正在打开 {url}...")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        print(f"   成功: 页面已加载")
    except Exception as e:
        print(f"   失败: {e}")
        await page.close()
        await browser.close()
        return

    # 显示页面信息
    print(f"\n[3] 页面信息:")
    print(f"   标题: {await page.title()}")
    print(f"   网址: {page.url}")

    # 截图
    print("\n[4] 正在截图...")
    await page.screenshot(path="test_screenshot.jpg")
    print("   已保存: test_screenshot.jpg")

    # 交互选择
    print("\n" + "=" * 60)
    print("接下来做什么?")
    print("=" * 60)
    print("1. 点击元素 (按文本)")
    print("2. 填写表单 (按选择器)")
    print("3. 获取页面内容")
    print("4. 再次截图")
    print("5. SmartWait 智能等待")
    print("6. 列出所有可点击元素")
    print("7. 退出")
    print()

    while True:
        try:
            choice = safe_input("请选择 (1-7): ").strip()
        except (EOFError, IOError):
            choice = "7"

        if choice == "1":
            text = safe_input("  请输入要点击的文本: ").strip()
            print(f"   正在点击 '{text}'...")
            try:
                # 获取所有匹配的元素
                locators = page.get_by_text(text, exact=False)
                count = await locators.count()
                if count > 1:
                    print(f"   找到 {count} 个匹配元素，请选择:")
                    print("   " + "=" * 60)
                    for i in range(count):
                        el = locators.nth(i)
                        tag = await el.evaluate("el => el.tagName")
                        href = await el.get_attribute("href") or ""

                        # 获取更多信息来区分
                        role = await el.get_attribute("role") or ""
                        parent = await el.evaluate("el => el.parentElement?.tagName || ''")

                        # 检查是否在表单内
                        is_in_form = await el.evaluate("""
                            el => {
                                let p = el.parentElement;
                                while(p) {
                                    if(p.tagName === 'FORM') return true;
                                    p = p.parentElement;
                                }
                                return false;
                            }
                        """)

                        # 获取class（截取部分）
                        cls = await el.get_attribute("class") or ""
                        cls_short = cls[:40] + "..." if len(cls) > 40 else cls

                        # 位置提示
                        location = "表单内" if is_in_form else "导航栏"

                        print(f"   [{i+1}] {location}")
                        print(f"       标签: <{tag.lower()}> href={href or '无'}")
                        if role:
                            print(f"       role: {role}")
                        if cls:
                            print(f"       class: {cls_short}")
                    print("   " + "=" * 60)

                    # 让用户选择
                    sel = safe_input(f"   选择编号 (1-{count}) 或按回车选第一个: ").strip()
                    if sel.isdigit() and 1 <= int(sel) <= count:
                        idx = int(sel) - 1
                    else:
                        idx = 0
                        print(f"   选择第1个")
                else:
                    idx = 0

                await locators.nth(idx).click(timeout=5000)
                print("   成功: 已点击!")
            except Exception as e:
                err = str(e)
                if "strict mode violation" in err.lower() or "resolved to" in err.lower():
                    print("   失败: 找到多个匹配元素，请使用选项6查看所有元素")
                else:
                    print(f"   失败: {e}")

        elif choice == "2":
            # 表单填写模式 - 持续填写直到用户返回
            print("\n   ===== 表单填写模式 =====")
            print("   输入选择器并填写，回车后继续填写下一个字段")
            print("   输入 'done' 完成, 'back' 返回主菜单\n")

            while True:
                # 显示当前表单状态
                print("   当前表单值:")
                try:
                    inputs = await page.locator("input, textarea, select").all()
                    for inp in inputs:
                        id = await inp.get_attribute("id") or ""
                        val = await inp.input_value() if await inp.count() else ""
                        type = await inp.get_attribute("type") or "text"
                        if id:
                            masked = "****" if type == "password" else val
                            print(f"     #{id}: {masked or '(空)'}")
                except:
                    pass
                print()

                user_input = safe_input("  选择器 #xxx (或 'done' 完成, 'back' 返回): ").strip()

                if user_input.lower() == "back":
                    break
                elif user_input.lower() == "done":
                    # 询问是否点击提交按钮
                    submit = safe_input("   提交表单? (y/n): ").strip().lower()
                    if submit == "y":
                        # 尝试找到并点击提交按钮
                        print("   查找提交按钮...")
                        try:
                            btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('登录'), button:has-text('提交'), button:has-text('确定')").first
                            await btn.click(timeout=3000)
                            print("   已点击提交!")
                        except:
                            print("   未找到提交按钮，请在下方输入要点击的元素文本")
                    break

                # 处理输入的选择器
                selector = user_input
                if not selector.startswith("#"):
                    selector = "#" + selector

                value = safe_input("  值: ").strip()
                if value.lower() == "back":
                    break

                print(f"   正在填写 {selector} -> '{value}'...")
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    await page.fill(selector, value)
                    print("   成功!")
                except Exception as e:
                    print(f"   失败: {e}")

        elif choice == "3":
            print("\n   页面HTML (前500字符):")
            content = await page.content()
            print("   " + content[:500].replace("\n", "\n   "))

        elif choice == "4":
            name = safe_input("  文件名 (默认: screenshot.jpg): ").strip() or "screenshot.jpg"
            await page.screenshot(path=name)
            print(f"   已保存: {name}")

        elif choice == "5":
            from src.smart_wait import create_smart_wait, WaitConfig
            sw = create_smart_wait(page, WaitConfig(timeout_ms=10000))

            selector = safe_input("  要等待的元素选择器: ").strip()
            print(f"   正在等待 '{selector}'...")
            try:
                sw.for_element(selector).to_appear()
                print("   成功: 元素出现了!")
            except Exception as e:
                print(f"   失败: {e}")

        elif choice == "6":
            print("\n   所有可点击元素:")
            print("   ----------------------------------------")
            try:
                links = await page.locator("a").all()
                for i, link in enumerate(links[:20]):  # 最多显示20个
                    text = await link.text_content()
                    href = await link.get_attribute("href") or ""
                    print(f"   [{i+1}] {text or '(无文本)'} -> {href}")
                if len(links) > 20:
                    print(f"   ... 还有 {len(links)-20} 个元素")
                print("   ----------------------------------------")
                print("   输入元素编号来点击，或输入 'back' 返回")
                sub = safe_input("   选择: ").strip()
                if sub.isdigit() and 1 <= int(sub) <= len(links):
                    await links[int(sub)-1].click()
                    print("   成功: 已点击!")
            except Exception as e:
                print(f"   失败: {e}")

        elif choice == "7":
            print("\n正在关闭浏览器...")
            await page.close()
            await ctx.close()
            await browser.close()
            print("完成!")
            break

        print()


async def main():
    try:
        await interactive_test()
    except KeyboardInterrupt:
        print("\n\n已取消。再见!")
    except Exception as e:
        print(f"\n错误: {e}")
    finally:
        # 确保浏览器关闭
        try:
            from src.browser import _browser_instance
            if _browser_instance:
                await _browser_instance.close()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(main())