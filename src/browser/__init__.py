"""
TestForge Browser - 浏览器管理
==============================

浏览器生命周期管理

快速开始 - 使用已有浏览器:
    TF_CHROMIUM_CHANNEL=chrome  python examples/quickstart.py

    或手动指定路径:
    TF_CHROMIUM_PATH="C:/Program Files/Google/Chrome/Application/chrome.exe"
"""

import os
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page


async def create_browser(
    headless: bool = True,
    slow_mo: Optional[float] = None,
    executable_path: Optional[str] = None,
    channel: Optional[str] = None,
) -> Dict[str, Any]:
    """
    创建浏览器实例

    Args:
        headless: 无头模式
        slow_mo: 操作延迟
        executable_path: 手动指定浏览器路径（如已有Chrome）
        channel: 浏览器渠道 ("chrome", "msedge", "chromium")

    Returns:
        {ok, browser, context}
    """
    from src.tools.error import ok, fail, ErrorCode

    # 环境变量优先级: executable_path > channel > 默认
    executable_path = executable_path or os.environ.get("TF_CHROMIUM_PATH", "").strip() or None
    channel = channel or os.environ.get("TF_CHROMIUM_CHANNEL", "").strip() or None

    if not channel and not headless:
        channel = "chrome"

    user_data_dir = os.environ.get("TF_CHROMIUM_USER_DATA_DIR", "").strip()
    user_data_dir = user_data_dir if user_data_dir else None

    translate_off = os.environ.get("TF_CHROME_DISABLE_TRANSLATE", "1").strip().lower()
    translate_off = translate_off in ("1", "true", "")
    translate_args = ["--disable-features=Translate,TranslateUI", "--disable-translate"] if translate_off else []

    args = (["--window-size=1440,900"] + translate_args) if headless else (["--start-maximized"] + translate_args)

    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()

        launch_kwargs = {
            "headless": headless,
            "slow_mo": slow_mo,
            "args": args,
        }

        # 优先使用 executable_path（手动指定已有浏览器）
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        elif channel:
            launch_kwargs["channel"] = channel
        else:
            # 默认使用已安装的 chromium（版本兼容）
            import glob
            local_appdata = os.environ.get("LOCALAPPDATA", "C:/Users/32239/AppData/Local")
            browsers = glob.glob(os.path.join(local_appdata, "ms-playwright", "chromium-*/chrome-win64/chrome.exe"))
            if browsers:
                launch_kwargs["executable_path"] = browsers[0]
            else:
                # 回退到已知路径
                launch_kwargs["executable_path"] = "C:/Users/32239/AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe"

        if user_data_dir:
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir,
                **launch_kwargs,
            )
            browser = ctx.browser()
            return {"ok": True, "browser": browser, "context": ctx}

        browser = await pw.chromium.launch(**launch_kwargs)
        return {"ok": True, "browser": browser}
    except Exception as e:
        return fail(ErrorCode.UNKNOWN, f"Browser launch failed: {e}")


async def capture_screenshot(page: "Page", quality: int = 60) -> Dict[str, Any]:
    """捕获 JPEG 截图"""
    from src.tools.error import ok, fail

    try:
        buffer = await page.screenshot(type="jpeg", quality=max(1, min(100, quality)))
        viewport = page.viewport_size

        return ok({
            "buffer": buffer,
            "width": viewport.get("width") if viewport else None,
            "height": viewport.get("height") if viewport else None,
        })
    except Exception as e:
        return fail(ErrorCode.UNKNOWN, f"Screenshot failed: {e}")


async def capture_aria_snapshot(page: "Page", timeout: int = 5000) -> Dict[str, Any]:
    """捕获 ARIA 快照"""
    from src.tools.error import ok, fail, ErrorCode

    try:
        yaml = await page.locator("body").aria_snapshot(timeout=timeout)
        return ok({"yaml": yaml})
    except Exception as e:
        return fail(ErrorCode.UNKNOWN, f"ARIA snapshot failed: {e}")


async def create_browser_page(browser):
    """创建浏览器页面 (用于 planner)"""
    context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.newPage()
    return page, context


async def capture_ax_snapshot(page: "Page", timeout: int = 5000) -> Dict[str, Any]:
    """捕获 AX 快照"""
    from src.tools.error import ok, fail, ErrorCode

    # 优先使用 _snapshotForAI
    snapshot_fn = getattr(page, "_snapshot_for_ai", None)
    if snapshot_fn:
        try:
            result = await snapshot_fn(timeout=timeout)
            return ok({"json": result})
        except Exception:
            pass

    # 使用 accessibility.snapshot
    accessibility = getattr(page, "accessibility", None)
    if accessibility:
        try:
            result = await accessibility.snapshot()
            return ok({"json": result})
        except Exception:
            pass

    return fail(ErrorCode.UNKNOWN, "No AX snapshot method available")