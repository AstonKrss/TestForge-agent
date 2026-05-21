"""
Browser Tools - 浏览器操作工具
==============================

每个工具返回标准化结果：
  {"ok": True, "data": {...}} 或
  {"ok": False, "error": {"code": "...", "message": "..."}}

工具列表：
- navigate(url)         导航到 URL
- snapshot()            获取页面快照（元素列表）
- find_elements(desc)   搜索匹配描述的元素，返回多个候选
- click(ref/desc)      点击元素（优先用 ref，否则模糊匹配描述）
- fill(ref/desc, text) 填写表单字段
- scroll(direction, amount) 滚动页面
- wait(seconds)         等待
- screenshot()          截图（返回 base64）
"""

import asyncio
import base64
import re
from urllib.parse import urlparse, urlunparse
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """工具执行结果"""
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


def _fail(code: str, msg: str) -> ToolResult:
    return ToolResult(ok=False, error=msg, error_code=code)


def _ok(data: Dict[str, Any]) -> ToolResult:
    return ToolResult(ok=True, data=data)


# ─────────────────────────────────────────────────────────────────────────────
# 底层操作
# ─────────────────────────────────────────────────────────────────────────────


async def _capture_elements(page) -> List[Dict[str, Any]]:
    """用 JS 捕获页面元素"""
    try:
        elements = await page.evaluate("""
            () => {
                const result = [];
                const selectors = [
                    'a',
                    'button',
                    'input',
                    'select',
                    'textarea',
                    '[role="button"]',
                    '[role="link"]',
                    '[contenteditable="true"]',
                    '[tabindex]'
                ].join(',');
                const labelText = (el) => {
                    if (!el) return '';
                    if (el.id) {
                        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (label) return (label.innerText || label.textContent || '').trim();
                    }
                    const parentLabel = el.closest('label');
                    if (parentLabel) return (parentLabel.innerText || parentLabel.textContent || '').trim();
                    return '';
                };
                const textFor = (el) => {
                    const pieces = [
                        el.innerText,
                        el.textContent,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                        el.placeholder,
                        el.value,
                        labelText(el)
                    ];
                    const seen = new Set();
                    return pieces
                        .filter(Boolean)
                        .map((piece) => String(piece).replace(/\\s+/g, ' ').trim())
                        .filter((piece) => {
                            if (!piece || seen.has(piece)) return false;
                            seen.add(piece);
                            return true;
                        })
                        .join(' ')
                        .slice(0, 120);
                };
                document.querySelectorAll(selectors).forEach((el, idx) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const form = el.closest('form');
                    const visible = rect.width > 0 && rect.height > 0
                        && style.display !== 'none' && style.visibility !== 'hidden';
                    if (!visible) return;
                    const ref = 'e' + result.length;
                    el.setAttribute('data-testforge-ref', ref);
                    result.push({
                        ref,
                        tag: el.tagName.toLowerCase(),
                        text: textFor(el),
                        id: el.id || '',
                        name: el.name || '',
                        placeholder: el.placeholder || '',
                        type: el.type || '',
                        href: el.href || (el.closest('a')?.href || ''),
                        role: el.getAttribute('role') || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        title: el.getAttribute('title') || '',
                        label: labelText(el),
                        required: !!el.required || el.getAttribute('aria-required') === 'true',
                        disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        formId: form?.id || '',
                        formIndex: form ? Array.from(document.forms).indexOf(form) : -1,
                        className: el.className || '',
                    });
                });
                return result;
            }
        """)
        return elements
    except Exception:
        return []


async def _capture_page_text(page) -> str:
    """Capture visible page text for result verification."""
    try:
        text = await page.evaluate("""
            () => (document.body?.innerText || '')
                .replace(/\\s+/g, ' ')
                .trim()
                .slice(0, 6000)
        """)
        return text or ""
    except Exception:
        return ""


def _aliases(description: str) -> List[str]:
    """常见中英文同义词，帮助跨系统查找入口。"""
    desc = (description or "").lower()
    groups = [
        ["登录", "登入", "登陆", "login", "log in", "sign in", "signin"],
        ["注册", "register", "sign up", "signup", "创建账号", "新用户"],
        ["搜索", "search", "查询", "查找"],
        ["提交", "submit", "确定", "确认", "保存", "save"],
        ["退出", "logout", "log out", "sign out", "注销"],
        ["文章", "post", "blog", "博客", "写文章", "发布"],
    ]
    terms = {description.strip()} if description else set()
    for group in groups:
        if any(item.lower() in desc for item in group):
            terms.update(group)
    return [t for t in terms if t]


def _element_text_blob(element: Dict[str, Any]) -> str:
    return " ".join([
        str(element.get("text", "")),
        str(element.get("placeholder", "")),
        str(element.get("label", "")),
        str(element.get("ariaLabel", "")),
        str(element.get("title", "")),
        str(element.get("id", "")),
        str(element.get("name", "")),
        str(element.get("role", "")),
        str(element.get("type", "")),
        str(element.get("href", "")),
        str(element.get("className", "")),
    ]).lower()


# ─────────────────────────────────────────────────────────────────────────────
# 工具实现
# ─────────────────────────────────────────────────────────────────────────────


async def navigate(page, url: str) -> ToolResult:
    """导航到 URL"""
    if not url.startswith('http'):
        return _fail("INVALID_URL", f"需要完整 URL: {url}")

    candidates = [url]
    parsed = urlparse(url)
    if parsed.scheme == "http":
        candidates.append(urlunparse(parsed._replace(scheme="https")))
    if parsed.hostname and not parsed.hostname.startswith("www."):
        netloc = "www." + parsed.netloc
        candidates.append(urlunparse(parsed._replace(scheme=parsed.scheme or "https", netloc=netloc)))
        candidates.append(urlunparse(parsed._replace(scheme="https", netloc=netloc)))

    seen = set()
    unique_candidates = []
    for candidate in candidates:
        if candidate not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate)

    errors = []
    for candidate in unique_candidates:
        try:
            await page.goto(candidate, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
            data = {"url": page.url, "title": await page.title()}
            if candidate != url:
                data["fallback"] = candidate
            return _ok(data)
        except Exception as e:
            errors.append(f"{candidate}: {e}")

    return _fail("NAVIGATION_FAILED", "; ".join(errors))


async def snapshot(page) -> ToolResult:
    """获取页面快照"""
    try:
        elements = await _capture_elements(page)
        text = await _capture_page_text(page)
        url = page.url
        title = await page.title()
        return _ok({
            "url": url,
            "title": title,
            "elements": elements,
            "text": text,
            "count": len(elements),
        })
    except Exception as e:
        return _fail("SNAPSHOT_FAILED", str(e))


async def find_elements(page, description: str) -> ToolResult:
    """
    搜索匹配描述的元素，返回多个候选。

    用于：当有多个相似元素时（如多个"登录"按钮），
    让 AI 或用户选择最合适的一个。
    """
    elements = await _capture_elements(page)
    if not elements:
        return _ok({"candidates": [], "description": description})

    candidates = []
    desc_lower = description.lower().strip()
    alias_terms = [t.lower() for t in _aliases(description)]

    # 精确匹配文本
    for e in elements:
        text = (e.get("text") or e.get("placeholder") or "").strip().lower()
        if text == desc_lower:
            candidates.append({**e, "score": 100, "match": "exact_text"})

    # 包含匹配
    if len(candidates) < 5:
        for e in elements:
            if any(e.get("ref") == c["ref"] for c in candidates):
                continue
            text = (e.get("text") or e.get("placeholder") or "").lower()
            if desc_lower in text or text in desc_lower:
                candidates.append({**e, "score": 80, "match": "contains"})

    # 同义词匹配（如 登录 -> login/sign in）
    if len(candidates) < 8 and alias_terms:
        for e in elements:
            if any(e.get("ref") == c["ref"] for c in candidates):
                continue
            fields = _element_text_blob(e)
            if any(term and term in fields for term in alias_terms):
                candidates.append({**e, "score": 70, "match": "alias"})

    # 属性模糊匹配
    if len(candidates) < 5:
        for e in elements:
            if any(e.get("ref") == c["ref"] for c in candidates):
                continue
            fields = _element_text_blob(e)
            if desc_lower in fields:
                candidates.append({**e, "score": 50, "match": "attr_fuzzy"})

    # 按 score 排序
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # 精简输出
    simplified = []
    for c in candidates[:8]:
        simplified.append({
            "ref": c["ref"],
            "tag": c["tag"],
            "text": c.get("text", ""),
            "placeholder": c.get("placeholder", ""),
            "id": c.get("id", ""),
            "type": c.get("type", ""),
            "y": c.get("y", 0),
            "formIndex": c.get("formIndex", -1),
            "score": c["score"],
            "match": c["match"],
        })

    return _ok({"candidates": simplified, "description": description, "total": len(candidates)})


async def click(page, ref: str = "", description: str = "", candidates: List = None) -> ToolResult:
    """
    点击元素。

    优先级：ref（基于位置索引） > candidates > description
    """
    display_name = description or ref

    # 策略1: ref 直接定位（e0, e1, e2... 是位置索引）
    if ref:
        match = re.match(r'^e(\d+)$', ref)
        if match:
            try:
                loc = page.locator(f"[data-testforge-ref='{ref}']")
                if await loc.count() > 0:
                    await loc.click(timeout=5000)
                    await asyncio.sleep(0.5)
                    return _ok({"ref": ref, "method": "by_ref"})
            except Exception:
                pass

    # 策略2: candidates 列表
    if candidates:
        for cand in candidates:
            c_ref = cand.get("ref", "")
            c_text = cand.get("text") or cand.get("placeholder", "")
            c_tag = cand.get("tag", "")
            c_id = cand.get("id", "")
            c_placeholder = cand.get("placeholder", "")

            # 优先用 id
            if c_id:
                try:
                    loc = page.locator(f"#{c_id}")
                    if await loc.count() > 0:
                        await loc.first.click(timeout=5000)
                        await asyncio.sleep(0.5)
                        return _ok({"ref": c_ref, "text": c_text, "method": "by_id"})
                except Exception:
                    pass

            # 用 ref（位置索引）
            m = re.match(r'^e(\d+)$', c_ref)
            if m:
                try:
                    loc = page.locator(f"[data-testforge-ref='{c_ref}']")
                    await loc.first.click(timeout=5000)
                    await asyncio.sleep(0.5)
                    return _ok({"ref": c_ref, "text": c_text, "method": "by_ref", "score": cand.get("score", 0)})
                except Exception:
                    pass

            # 文本匹配
            if c_text:
                try:
                    loc = page.get_by_text(c_text, exact=False)
                    if await loc.count() > 0:
                        await loc.first.click(timeout=5000)
                        await asyncio.sleep(0.5)
                        return _ok({"ref": c_ref, "text": c_text, "method": "by_text"})
                except Exception:
                    pass

    # 策略3: description 模糊匹配
    if description:
        strategies = [
            page.get_by_text(description, exact=False),
            page.get_by_role("button", name=description),
            page.get_by_role("link", name=description),
            page.get_by_placeholder(description),
            page.locator(f"#{description}"),
        ]
        for loc in strategies:
            try:
                if await loc.count() > 0:
                    await loc.first.click(timeout=5000)
                    await asyncio.sleep(0.5)
                    return _ok({"description": description, "method": "fuzzy"})
            except Exception:
                continue

    return _fail("ELEMENT_NOT_FOUND", f"找不到元素: {display_name}")


async def fill(page, ref: str = "", description: str = "", text: str = "",
               candidates: List = None) -> ToolResult:
    """
    填写表单字段。

    策略：id > ref（位置索引）> candidates > description
    """
    # 策略1: candidates 中找 id/placeholder
    if candidates:
        for cand in candidates:
            c_id = cand.get("id", "")
            c_placeholder = cand.get("placeholder", "")
            c_ref = cand.get("ref", "")

            if c_id:
                try:
                    loc = page.locator(f"#{c_id}")
                    if await loc.count() > 0:
                        await loc.first.fill(text)
                        return _ok({"ref": c_ref, "placeholder": c_placeholder, "text_len": len(text), "method": "by_id"})
                except Exception:
                    pass

            if c_placeholder:
                try:
                    loc = page.get_by_placeholder(c_placeholder)
                    if await loc.count() > 0:
                        await loc.first.fill(text)
                        return _ok({"ref": c_ref, "placeholder": c_placeholder, "text_len": len(text), "method": "by_placeholder"})
                except Exception:
                    pass

            # ref 位置索引
            m = re.match(r'^e(\d+)$', c_ref)
            if m:
                try:
                    loc = page.locator(
                        f"input[data-testforge-ref='{c_ref}'], "
                        f"textarea[data-testforge-ref='{c_ref}'], "
                        f"select[data-testforge-ref='{c_ref}'], "
                        f"[contenteditable='true'][data-testforge-ref='{c_ref}']"
                    )
                    await loc.first.fill(text)
                    return _ok({"ref": c_ref, "text_len": len(text), "method": "by_ref"})
                except Exception:
                    pass

    # 策略2: ref 直接用位置索引
    if ref:
        match = re.match(r'^e(\d+)$', ref)
        if match:
            try:
                loc = page.locator(
                    f"input[data-testforge-ref='{ref}'], "
                    f"textarea[data-testforge-ref='{ref}'], "
                    f"select[data-testforge-ref='{ref}'], "
                    f"[contenteditable='true'][data-testforge-ref='{ref}']"
                )
                await loc.first.fill(text)
                return _ok({"ref": ref, "text_len": len(text), "method": "by_ref"})
            except Exception:
                pass

    # 策略3: description 模糊匹配
    if description:
        strategies = [
            page.get_by_placeholder(description, exact=False),
            page.get_by_label(description),
            page.locator(f"#{description}"),
            page.locator(f"[name='{description}']"),
            page.locator(f"input[placeholder*='{description}']"),
            page.locator(f"textarea[placeholder*='{description}']"),
        ]
        for loc in strategies:
            try:
                if await loc.count() > 0:
                    await loc.first.fill(text)
                    return _ok({"description": description, "text_len": len(text)})
            except Exception:
                continue

    return _fail("INPUT_NOT_FOUND", f"找不到输入框: {description or ref}")


async def scroll(page, direction: str = "down", amount: int = 300) -> ToolResult:
    """滚动页面"""
    delta = amount if direction == "down" else -amount
    try:
        await page.evaluate(f"window.scrollBy(0, {delta})")
        await asyncio.sleep(0.3)
        return _ok({"direction": direction, "amount": amount})
    except Exception as e:
        return _fail("SCROLL_FAILED", str(e))


async def wait(seconds: float) -> ToolResult:
    """等待"""
    await asyncio.sleep(seconds)
    return _ok({"waited": seconds})


async def screenshot(page) -> ToolResult:
    """截图（返回 base64）"""
    try:
        buf = await page.screenshot()
        b64 = base64.b64encode(buf).decode("utf-8")
        return _ok({"screenshot": b64, "size": len(buf)})
    except Exception as e:
        return _fail("SCREENSHOT_FAILED", str(e))


async def assert_text(page, text: str) -> ToolResult:
    """断言页面包含可见文本"""
    try:
        loc = page.get_by_text(text, exact=False)
        count = await loc.count()
        for i in range(min(count, 5)):
            if await loc.nth(i).is_visible():
                return _ok({"text": text})
        return _fail("ASSERT_TEXT_FAILED", f"页面未找到文本: {text}")
    except Exception as e:
        return _fail("ASSERT_TEXT_FAILED", str(e))


async def assert_visible(page, description: str = "", ref: str = "") -> ToolResult:
    """断言元素可见"""
    try:
        if ref:
            loc = page.locator(f"[data-testforge-ref='{ref}']")
            if await loc.count() > 0 and await loc.first.is_visible():
                return _ok({"ref": ref})
        if description:
            loc = page.get_by_text(description, exact=False)
            count = await loc.count()
            for i in range(min(count, 5)):
                if await loc.nth(i).is_visible():
                    return _ok({"description": description})
        return _fail("ASSERT_VISIBLE_FAILED", f"元素不可见: {description or ref}")
    except Exception as e:
        return _fail("ASSERT_VISIBLE_FAILED", str(e))


async def extract_links(page) -> ToolResult:
    """Extract visible links with refs."""
    try:
        elements = await _capture_elements(page)
        links = [
            {
                "ref": e.get("ref", ""),
                "text": e.get("text", ""),
                "href": e.get("href", ""),
                "y": e.get("y", 0),
            }
            for e in elements
            if e.get("href")
        ]
        return _ok({"links": links, "total": len(links)})
    except Exception as e:
        return _fail("EXTRACT_LINKS_FAILED", str(e))


async def extract_search_results(page) -> ToolResult:
    """Extract likely article search results."""
    try:
        await _capture_elements(page)
        results = await page.evaluate("""
            () => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                const seen = new Set();
                return anchors
                    .map((a) => {
                        const rect = a.getBoundingClientRect();
                        const href = a.href || '';
                        const text = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
                        const card = a.closest('article, li, .card, [class*="card"], [class*="post"], [class*="article"]');
                        const summary = card ? (card.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 240) : '';
                        const ref = a.getAttribute('data-testforge-ref') || '';
                        return { ref, text, href, summary, y: Math.round(rect.y), visible: rect.width > 0 && rect.height > 0 };
                    })
                    .filter((item) => item.visible && item.href && item.text)
                    .filter((item) => /\\/blog\\//.test(new URL(item.href).pathname) || /查看全文|阅读全文|read more|article|post|博客/.test(item.text + ' ' + item.summary))
                    .filter((item) => {
                        const key = item.href.split('#')[0];
                        if (seen.has(key)) return false;
                        seen.add(key);
                        return true;
                    })
                    .sort((a, b) => a.y - b.y)
                    .slice(0, 10);
            }
        """)
        return _ok({"results": results, "total": len(results)})
    except Exception as e:
        return _fail("EXTRACT_SEARCH_RESULTS_FAILED", str(e))


async def extract_forms(page) -> ToolResult:
    """Extract forms and input fields."""
    try:
        await _capture_elements(page)
        forms = await page.evaluate("""
            () => Array.from(document.forms).map((form, formIndex) => ({
                id: form.id || '',
                action: form.action || '',
                method: form.method || '',
                fields: Array.from(form.querySelectorAll('input, textarea, select')).map((el) => ({
                    ref: el.getAttribute('data-testforge-ref') || '',
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    value: el.type === 'password' ? '' : (el.value || ''),
                    required: !!el.required,
                })),
                formIndex,
            }))
        """)
        return _ok({"forms": forms, "total": len(forms)})
    except Exception as e:
        return _fail("EXTRACT_FORMS_FAILED", str(e))


async def extract_article_content(page) -> ToolResult:
    """Extract article-ish content summary."""
    try:
        data = await page.evaluate("""
            () => {
                const root = document.querySelector('article, main') || document.body;
                const title = (document.querySelector('h1')?.innerText || document.title || '').trim();
                const headings = Array.from(root.querySelectorAll('h1, h2, h3')).map(h => h.innerText.trim()).filter(Boolean).slice(0, 20);
                const text = (root.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 4000);
                return { title, headings, text, url: location.href };
            }
        """)
        return _ok(data)
    except Exception as e:
        return _fail("EXTRACT_ARTICLE_FAILED", str(e))


async def extract_auth_requirements(page) -> ToolResult:
    """Detect auth-required hints and login links."""
    try:
        elements = await _capture_elements(page)
        text = await _capture_page_text(page)
        terms = ["请登录", "请先登录", "登录后", "点击登录", "未登录", "需要登录", "login required", "please login"]
        lower = text.lower()
        required = any(term.lower() in lower for term in terms)
        login_links = [
            e for e in elements
            if e.get("href") and any(term in _element_text_blob(e) for term in ["登录", "login", "sign in", "signin"])
        ]
        return _ok({"auth_required": required or bool(login_links), "login_links": login_links[:5], "text": text[:1000]})
    except Exception as e:
        return _fail("EXTRACT_AUTH_FAILED", str(e))


async def extract_like_buttons(page) -> ToolResult:
    """Extract likely like/upvote buttons."""
    try:
        elements = await _capture_elements(page)
        candidates = []
        for e in elements:
            blob = _element_text_blob(e)
            if any(term in blob for term in ["点赞", "赞", "like", "heart", "thumb", "upvote", "喜欢"]):
                candidates.append(e)
        return _ok({"buttons": candidates[:8], "total": len(candidates)})
    except Exception as e:
        return _fail("EXTRACT_LIKE_FAILED", str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 工具注册表
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = {
    "navigate": navigate,
    "snapshot": snapshot,
    "find_elements": find_elements,
    "click": click,
    "fill": fill,
    "scroll": scroll,
    "wait": wait,
    "screenshot": screenshot,
    "assert_text": assert_text,
    "assert_visible": assert_visible,
    "extract_links": extract_links,
    "extract_search_results": extract_search_results,
    "extract_forms": extract_forms,
    "extract_article_content": extract_article_content,
    "extract_auth_requirements": extract_auth_requirements,
    "extract_like_buttons": extract_like_buttons,
}


async def call_tool(page, tool_name: str, **kwargs) -> ToolResult:
    """调用工具的统一入口"""
    tool = TOOLS.get(tool_name)
    if not tool:
        return _fail("UNKNOWN_TOOL", f"未知工具: {tool_name}")
    try:
        return await tool(page, **kwargs)
    except Exception as e:
        return _fail("TOOL_ERROR", str(e))


__all__ = [
    "ToolResult",
    "TOOLS",
    "call_tool",
    "navigate",
    "snapshot",
    "find_elements",
    "click",
    "fill",
    "scroll",
    "wait",
    "screenshot",
    "assert_text",
    "assert_visible",
    "extract_links",
    "extract_search_results",
    "extract_forms",
    "extract_article_content",
    "extract_auth_requirements",
    "extract_like_buttons",
]
