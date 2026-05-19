"""
TestForge Runner - 测试执行引擎
=============================
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Browser


class RunResult:
    """运行结果"""
    def __init__(
        self,
        ok: bool,
        passed: int = 0,
        failed: int = 0,
        errors: Optional[List[Dict]] = None,
    ):
        self.ok = ok
        self.passed = passed
        self.failed = failed
        self.errors = errors or []


async def run_specs(
    browser: "Browser",
    base_url: str,
    specs: List[Dict[str, Any]],
    headless: bool = True,
    debug: bool = False,
    on_spec: Optional[Callable] = None,
) -> RunResult:
    """
    运行测试规范

    Args:
        browser: Playwright Browser
        base_url: 基础 URL
        specs: 规范列表
        headless: 无头模式
        debug: 调试模式
        on_spec: 每个规范的回调 (async function)

    Returns:
        RunResult
    """
    from .browser import create_browser

    # 创建浏览器
    result = await create_browser(headless=headless)
    if not result.get("ok"):
        return RunResult(ok=False, errors=[{"code": "BROWSER_FAILED", "message": result.get("error")}])

    browser = result.get("browser")
    passed = 0
    failed = 0
    errors = []

    for spec in specs:
        spec_path = spec.get("spec_path", "unknown")
        try:
            ctx = await browser.new_context(
                viewport={"width": 1440, "height": 900} if not debug else None
            )
            page = await ctx.new_page()

            if on_spec:
                await on_spec(
                    base_url=base_url,
                    spec_path=spec_path,
                    spec=spec.get("spec"),
                    page=page,
                )

            passed += 1
            await page.close()
            await ctx.close()
        except Exception as e:
            failed += 1
            errors.append({
                "spec": spec_path,
                "error": str(e),
            })

    return RunResult(
        ok=failed == 0,
        passed=passed,
        failed=failed,
        errors=errors,
    )


async def run_single_spec(
    browser: "Browser",
    base_url: str,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """运行单个规范"""
    from .tools import click, fill, navigate, scroll, wait, assert_element_visible, assert_text_present

    results = []
    steps = spec.get("steps", [])

    ctx = await browser.new_context()
    page = await ctx.new_page()

    try:
        for step in steps:
            idx = step.get("index", 0)
            text = step.get("text", "")
            kind = step.get("kind", "action")
            expected = step.get("expected")

            # 解析动作
            if text.lower().startswith("navigate"):
                # 提取 URL
                url_match = text.split("navigate", 1)[1].strip()
                result = await navigate(page, base_url, url_match)
            elif text.lower().startswith("click"):
                # 提取描述
                desc_match = text.split("click", 1)[1].strip()
                result = await click(page, description=desc_match, step=idx)
            elif text.lower().startswith("fill") or "fill" in text.lower():
                # 提取描述和值
                parts = text.replace("fill", "").replace("with", "|").split("|")
                desc = parts[0].strip() if len(parts) > 0 else ""
                value = parts[1].strip() if len(parts) > 1 else ""
                result = await fill(page, description=desc, text=value, step=idx)
            elif kind == "assertion":
                if expected:
                    result = await assert_text_present(page, expected)
                else:
                    result = await assert_element_visible(page, description=text)
            else:
                result = {"ok": False, "error": {"code": "UNKNOWN_ACTION", "message": f"Unknown action: {text}"}}

            results.append({"step": idx, "result": result})

            if not result.get("ok"):
                break

        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        await page.close()
        await ctx.close()