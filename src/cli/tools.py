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


async def performance_audit(page, runs: int = 1, reload: bool = False) -> ToolResult:
    """Collect browser-side performance metrics for the current page."""
    if not getattr(page, "url", "") or page.url == "about:blank":
        return _fail("NO_PAGE", "请先打开一个页面再进行性能测试")

    runs = max(1, min(int(runs or 1), 5))
    samples = []
    for index in range(runs):
        try:
            if reload or index > 0:
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    try:
                        await page.goto(page.url, wait_until="domcontentloaded", timeout=30000)
                    except Exception:
                        pass
            else:
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=8000)
                except Exception:
                    pass
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            await asyncio.sleep(0.3)
            samples.append(await page.evaluate("""
                () => {
                    const nav = performance.getEntriesByType('navigation')[0] || {};
                    const paints = {};
                    for (const entry of performance.getEntriesByType('paint')) {
                        paints[entry.name] = Math.round(entry.startTime || 0);
                    }
                    const resources = performance.getEntriesByType('resource')
                        .map((entry) => ({
                            name: entry.name,
                            initiatorType: entry.initiatorType || 'other',
                            duration: Math.round(entry.duration || 0),
                            transferSize: Math.round(entry.transferSize || 0),
                            encodedBodySize: Math.round(entry.encodedBodySize || 0),
                        }));
                    const byType = {};
                    for (const item of resources) {
                        const type = item.initiatorType || 'other';
                        if (!byType[type]) byType[type] = { count: 0, transferSize: 0, encodedBodySize: 0 };
                        byType[type].count += 1;
                        byType[type].transferSize += item.transferSize || 0;
                        byType[type].encodedBodySize += item.encodedBodySize || 0;
                    }
                    return {
                        url: location.href,
                        title: document.title || '',
                        timing: {
                            ttfb: Math.round((nav.responseStart || 0) - (nav.requestStart || 0)),
                            domContentLoaded: Math.round(nav.domContentLoadedEventEnd || 0),
                            load: Math.round(nav.loadEventEnd || nav.duration || 0),
                            duration: Math.round(nav.duration || 0),
                        },
                        paints,
                        resources: {
                            total: resources.length,
                            transferSize: resources.reduce((sum, item) => sum + (item.transferSize || 0), 0),
                            encodedBodySize: resources.reduce((sum, item) => sum + (item.encodedBodySize || 0), 0),
                            byType,
                            slow: resources
                                .filter((item) => item.duration >= 500)
                                .sort((a, b) => b.duration - a.duration)
                                .slice(0, 10),
                        },
                    };
                }
            """))
        except Exception as e:
            return _fail("PERFORMANCE_AUDIT_FAILED", str(e))

    summary = _summarize_performance(samples)
    return _ok({"samples": samples, "summary": summary, "runs": runs, "reload": reload})


def _summarize_performance(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    latest = samples[-1] if samples else {}
    timings = [sample.get("timing", {}) for sample in samples]

    def avg(key: str) -> int:
        values = [item.get(key, 0) for item in timings if item.get(key, 0)]
        return round(sum(values) / len(values)) if values else 0

    resources = latest.get("resources", {})
    transfer_size = int(resources.get("transferSize") or 0)
    resource_count = int(resources.get("total") or 0)
    load_ms = avg("load") or avg("duration")
    fcp = latest.get("paints", {}).get("first-contentful-paint", 0)

    score = 100
    recommendations = []
    if load_ms > 4000:
        score -= 30
        recommendations.append("页面 load 超过 4s，建议拆分首屏资源、减少阻塞脚本并启用缓存")
    elif load_ms > 2500:
        score -= 15
        recommendations.append("页面 load 超过 2.5s，可继续压缩资源并延迟非首屏脚本")
    if fcp and fcp > 2500:
        score -= 20
        recommendations.append("FCP 超过 2.5s，首屏渲染偏慢，检查 CSS/字体/首屏接口")
    if transfer_size > 3 * 1024 * 1024:
        score -= 20
        recommendations.append("传输体积超过 3MB，建议压缩图片、开启 gzip/br、移除未用资源")
    elif transfer_size > 1024 * 1024:
        score -= 10
        recommendations.append("传输体积超过 1MB，建议关注图片和 JS 包大小")
    if resource_count > 120:
        score -= 10
        recommendations.append("资源请求数量较多，建议合并或延迟加载低优先级资源")
    if not recommendations:
        recommendations.append("基础加载指标良好，可继续结合业务接口和并发压测验证")

    score = max(0, min(100, score))
    rating = "good" if score >= 85 else "needs_attention" if score >= 65 else "poor"
    return {
        "score": score,
        "rating": rating,
        "average": {
            "ttfb": avg("ttfb"),
            "domContentLoaded": avg("domContentLoaded"),
            "load": load_ms,
            "duration": avg("duration"),
        },
        "firstContentfulPaint": fcp,
        "resourceCount": resource_count,
        "transferSize": transfer_size,
        "recommendations": recommendations,
        "slowResources": resources.get("slow", []),
        "byType": resources.get("byType", {}),
    }


async def load_test(
    page,
    url: str = "",
    requests: int = 20,
    concurrency: int = 2,
    method: str = "GET",
    timeout: float = 10.0,
) -> ToolResult:
    """Run a bounded HTTP load test against one URL."""
    target = (url or getattr(page, "url", "") or "").strip()
    if not target or target == "about:blank":
        return _fail("NO_TARGET", "请先打开页面，或指定压力测试 URL")

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return _fail("INVALID_TARGET", f"压力测试只支持 http/https URL: {target}")

    method = (method or "GET").upper()
    if method not in {"GET", "HEAD"}:
        return _fail("UNSAFE_METHOD", "当前压力测试工具只允许 GET/HEAD，避免误改业务数据")

    total_requests = max(1, min(int(requests or 20), 100))
    concurrency = max(1, min(int(concurrency or 2), 10))
    timeout = max(1.0, min(float(timeout or 10.0), 30.0))

    try:
        import httpx
    except Exception as e:
        return _fail("MISSING_HTTPX", f"缺少 httpx，无法进行压力测试: {e}")

    started_at = asyncio.get_event_loop().time()
    queue: asyncio.Queue[int] = asyncio.Queue()
    for index in range(total_requests):
        queue.put_nowait(index)

    samples: List[Dict[str, Any]] = []

    async def worker(client):
        while True:
            try:
                await queue.get()
            except Exception:
                return
            start = asyncio.get_event_loop().time()
            try:
                response = await client.request(method, target)
                duration = (asyncio.get_event_loop().time() - start) * 1000
                samples.append({
                    "ok": True,
                    "status": response.status_code,
                    "duration": round(duration, 2),
                    "size": len(response.content or b""),
                    "error": "",
                })
            except Exception as e:
                duration = (asyncio.get_event_loop().time() - start) * 1000
                samples.append({
                    "ok": False,
                    "status": 0,
                    "duration": round(duration, 2),
                    "size": 0,
                    "error": str(e)[:160],
                })
            finally:
                queue.task_done()

    headers = {"User-Agent": "TestForgeLoadTest/0.2 controlled"}
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
        ) as client:
            workers = [asyncio.create_task(worker(client)) for _ in range(concurrency)]
            await queue.join()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
    except Exception as e:
        return _fail("LOAD_TEST_FAILED", str(e))

    finished_at = asyncio.get_event_loop().time()
    summary = _summarize_load_samples(samples, started_at, finished_at)
    summary.update({
        "url": target,
        "method": method,
        "requested": total_requests,
        "concurrency": concurrency,
        "timeout": timeout,
    })
    return _ok({"summary": summary, "samples": samples})


def _summarize_load_samples(samples: List[Dict[str, Any]], started_at: float, finished_at: float) -> Dict[str, Any]:
    durations = sorted(float(item.get("duration") or 0) for item in samples)
    total = len(samples)
    ok_count = sum(1 for item in samples if item.get("ok") and int(item.get("status") or 0) < 500)
    failed = total - ok_count
    elapsed = max(0.001, finished_at - started_at)
    status_counts: Dict[str, int] = {}
    errors: Dict[str, int] = {}
    for item in samples:
        status = str(item.get("status") or "ERR")
        status_counts[status] = status_counts.get(status, 0) + 1
        if item.get("error"):
            error = item["error"]
            errors[error] = errors.get(error, 0) + 1

    def percentile(p: float) -> float:
        if not durations:
            return 0.0
        index = min(len(durations) - 1, max(0, round((len(durations) - 1) * p)))
        return round(durations[index], 2)

    avg = round(sum(durations) / len(durations), 2) if durations else 0.0
    error_rate = round((failed / total) * 100, 2) if total else 0.0
    rps = round(total / elapsed, 2)
    recommendations = []
    if error_rate > 5:
        recommendations.append("错误率超过 5%，需要检查服务端日志、限流、网关超时或接口异常")
    if percentile(0.95) > 2000:
        recommendations.append("P95 超过 2s，建议排查慢接口、数据库查询、缓存命中率和资源瓶颈")
    if rps < 1 and total >= 10:
        recommendations.append("吞吐偏低，建议拆分静态资源和动态接口分别压测定位瓶颈")
    if not recommendations:
        recommendations.append("低压探测结果正常；正式压测建议在自有环境逐步提升并发并监控服务端指标")

    return {
        "total": total,
        "ok": ok_count,
        "failed": failed,
        "errorRate": error_rate,
        "rps": rps,
        "elapsed": round(elapsed, 2),
        "avg": avg,
        "min": round(durations[0], 2) if durations else 0.0,
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "max": round(durations[-1], 2) if durations else 0.0,
        "statusCounts": status_counts,
        "errors": errors,
        "recommendations": recommendations,
    }


async def quality_audit(page) -> ToolResult:
    """Run a lightweight page quality, accessibility, and safety audit."""
    if not getattr(page, "url", "") or page.url == "about:blank":
        return _fail("NO_PAGE", "请先打开一个页面再进行页面质量检查")

    try:
        raw = await page.evaluate("""
            () => {
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                };
                const accessibleName = (el) => {
                    const parts = [
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                        el.getAttribute('placeholder'),
                        el.innerText,
                        el.textContent,
                    ];
                    if (el.id) {
                        const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (label) parts.push(label.innerText || label.textContent);
                    }
                    const parentLabel = el.closest('label');
                    if (parentLabel) parts.push(parentLabel.innerText || parentLabel.textContent);
                    return parts.filter(Boolean).join(' ').replace(/\\s+/g, ' ').trim();
                };
                const ids = Array.from(document.querySelectorAll('[id]')).map((el) => el.id).filter(Boolean);
                const duplicateIds = ids.filter((id, index) => ids.indexOf(id) !== index);
                const images = Array.from(document.images).filter(visible);
                const formFields = Array.from(document.querySelectorAll('input, select, textarea'))
                    .filter((el) => visible(el) && (el.type || '').toLowerCase() !== 'hidden');
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(visible);
                const links = Array.from(document.querySelectorAll('a[href]')).filter(visible);
                const passwordFields = formFields.filter((el) => (el.type || '').toLowerCase() === 'password');
                return {
                    url: location.href,
                    title: document.title || '',
                    lang: document.documentElement.lang || '',
                    hasViewport: !!document.querySelector('meta[name="viewport"]'),
                    h1Count: document.querySelectorAll('h1').length,
                    duplicateIds: Array.from(new Set(duplicateIds)).slice(0, 20),
                    images: {
                        total: images.length,
                        missingAlt: images.filter((img) => !img.hasAttribute('alt') || !(img.getAttribute('alt') || '').trim()).length,
                    },
                    forms: {
                        fields: formFields.length,
                        missingNames: formFields.filter((el) => !accessibleName(el)).length,
                        passwordFields: passwordFields.length,
                        passwordAutocompleteMissing: passwordFields.filter((el) => !el.getAttribute('autocomplete')).length,
                        insecureActions: Array.from(document.forms).filter((form) => {
                            const action = form.action || location.href;
                            return location.protocol === 'https:' && action.startsWith('http:');
                        }).length,
                    },
                    buttons: {
                        total: buttons.length,
                        empty: buttons.filter((button) => !accessibleName(button)).length,
                    },
                    links: {
                        total: links.length,
                        empty: links.filter((a) => !accessibleName(a)).length,
                        javascriptHref: links.filter((a) => (a.getAttribute('href') || '').trim().toLowerCase().startsWith('javascript:')).length,
                        targetBlankUnsafe: links.filter((a) => a.target === '_blank' && !/(noopener|noreferrer)/i.test(a.rel || '')).length,
                    },
                    mixedContent: Array.from(document.querySelectorAll('[src], [href]')).filter((el) => {
                        const value = el.src || el.href || '';
                        return location.protocol === 'https:' && value.startsWith('http:');
                    }).length,
                };
            }
        """)
        summary = _summarize_quality(raw)
        return _ok({"raw": raw, "summary": summary})
    except Exception as e:
        return _fail("QUALITY_AUDIT_FAILED", str(e))


def _summarize_quality(raw: Dict[str, Any]) -> Dict[str, Any]:
    score = 100
    issues: List[str] = []
    recommendations: List[str] = []

    if not raw.get("title"):
        score -= 10
        issues.append("页面缺少 title")
        recommendations.append("补充明确的页面 title，方便测试报告和搜索结果识别")
    if not raw.get("lang"):
        score -= 8
        issues.append("html 缺少 lang")
        recommendations.append("为 html 设置 lang，提升无障碍和翻译体验")
    if not raw.get("hasViewport"):
        score -= 8
        issues.append("缺少 viewport meta")
        recommendations.append("补充 viewport meta，避免移动端布局异常")
    if raw.get("h1Count", 0) != 1:
        score -= 6
        issues.append(f"H1 数量为 {raw.get('h1Count', 0)}")
        recommendations.append("保持一个清晰 H1，利于可访问性和页面结构")
    if raw.get("duplicateIds"):
        score -= 10
        issues.append("存在重复 id")
        recommendations.append("修复重复 id，避免定位器和 label 关联混乱")

    images = raw.get("images", {})
    if images.get("missingAlt", 0):
        score -= min(12, images["missingAlt"] * 2)
        issues.append(f"{images['missingAlt']} 张图片缺少 alt")
        recommendations.append("给信息型图片添加 alt，装饰图使用空 alt")

    forms = raw.get("forms", {})
    if forms.get("missingNames", 0):
        score -= min(15, forms["missingNames"] * 3)
        issues.append(f"{forms['missingNames']} 个表单控件缺少可访问名称")
        recommendations.append("为 input/select/textarea 添加 label、aria-label 或明确 placeholder")
    if forms.get("passwordAutocompleteMissing", 0):
        score -= min(6, forms["passwordAutocompleteMissing"] * 2)
        issues.append("密码框缺少 autocomplete")
        recommendations.append("为登录/注册密码框设置合适 autocomplete")
    if forms.get("insecureActions", 0):
        score -= 15
        issues.append("HTTPS 页面存在 HTTP 表单提交")
        recommendations.append("表单 action 使用 HTTPS，避免凭证泄露风险")

    buttons = raw.get("buttons", {})
    if buttons.get("empty", 0):
        score -= min(12, buttons["empty"] * 3)
        issues.append(f"{buttons['empty']} 个按钮缺少可访问名称")
        recommendations.append("为空图标按钮添加 aria-label 或 title")

    links = raw.get("links", {})
    if links.get("empty", 0):
        score -= min(10, links["empty"] * 2)
        issues.append(f"{links['empty']} 个链接缺少可访问名称")
        recommendations.append("链接文本应能表达目标含义")
    if links.get("javascriptHref", 0):
        score -= min(8, links["javascriptHref"] * 2)
        issues.append("存在 javascript: 链接")
        recommendations.append("避免 javascript: href，使用 button 或安全事件处理")
    if links.get("targetBlankUnsafe", 0):
        score -= min(8, links["targetBlankUnsafe"] * 2)
        issues.append("target=_blank 缺少 noopener/noreferrer")
        recommendations.append("外链 target=_blank 加 rel=noopener noreferrer")
    if raw.get("mixedContent", 0):
        score -= 15
        issues.append("HTTPS 页面存在混合内容")
        recommendations.append("将图片、脚本、样式等资源全部切到 HTTPS")

    if not issues:
        recommendations.append("基础页面质量良好；可继续做键盘可达性、读屏和跨浏览器测试")

    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "recommendations": recommendations,
    }


async def security_audit(page) -> ToolResult:
    """Run low-risk browser-visible security checks."""
    if not getattr(page, "url", "") or page.url == "about:blank":
        return _fail("NO_PAGE", "请先打开一个页面再进行安全检查")
    try:
        response = await page.context.request.get(page.url, timeout=15000)
        headers = {k.lower(): v for k, v in response.headers.items()}
    except Exception:
        headers = {}
    try:
        dom = await page.evaluate("""
            () => ({
                mixedContent: Array.from(document.querySelectorAll('[src], [href]')).filter((el) => {
                    const value = el.src || el.href || '';
                    return location.protocol === 'https:' && value.startsWith('http:');
                }).length,
                passwordFields: Array.from(document.querySelectorAll('input[type="password"]')).map((el) => ({
                    autocomplete: el.getAttribute('autocomplete') || '',
                    formAction: el.form?.action || location.href,
                })),
                dangerousLinks: Array.from(document.querySelectorAll('a[href^="javascript:"]')).length,
                targetBlankUnsafe: Array.from(document.querySelectorAll('a[target="_blank"]')).filter((a) => !/(noopener|noreferrer)/i.test(a.rel || '')).length,
            })
        """)
    except Exception:
        dom = {}
    issues = []
    recommendations = []
    expected_headers = {
        "content-security-policy": "建议配置 CSP，降低 XSS 和资源注入风险",
        "x-frame-options": "建议配置 X-Frame-Options 或 CSP frame-ancestors，降低点击劫持风险",
        "x-content-type-options": "建议配置 X-Content-Type-Options: nosniff",
        "referrer-policy": "建议配置 Referrer-Policy，减少来源信息泄露",
        "permissions-policy": "建议配置 Permissions-Policy，限制敏感浏览器能力",
    }
    for header, recommendation in expected_headers.items():
        if header not in headers:
            issues.append(f"缺少响应头: {header}")
            recommendations.append(recommendation)
    if page.url.startswith("https://") and "strict-transport-security" not in headers:
        issues.append("HTTPS 页面缺少 HSTS")
        recommendations.append("建议配置 Strict-Transport-Security")
    if dom.get("mixedContent"):
        issues.append(f"存在 {dom['mixedContent']} 个混合内容资源")
        recommendations.append("HTTPS 页面不要加载 HTTP 资源")
    if dom.get("dangerousLinks"):
        issues.append("存在 javascript: 链接")
        recommendations.append("避免 javascript: href，改用 button 和安全事件处理")
    if dom.get("targetBlankUnsafe"):
        issues.append("target=_blank 缺少 noopener/noreferrer")
        recommendations.append("外链 target=_blank 加 rel=noopener noreferrer")
    score = max(0, 100 - min(80, len(issues) * 8))
    if not recommendations:
        recommendations.append("基础安全检查未发现明显问题；可继续做接口鉴权、越权和输入安全测试")
    return _ok({"headers": headers, "dom": dom, "summary": {"score": score, "issues": issues, "recommendations": recommendations}})


async def accessibility_audit(page) -> ToolResult:
    """Run a lightweight accessibility audit without external dependencies."""
    result = await quality_audit(page)
    if not result.ok:
        return result
    raw = result.data.get("raw", {})
    issues = []
    if not raw.get("lang"):
        issues.append("html 缺少 lang")
    if raw.get("images", {}).get("missingAlt", 0):
        issues.append(f"{raw['images']['missingAlt']} 张图片缺少 alt")
    if raw.get("forms", {}).get("missingNames", 0):
        issues.append(f"{raw['forms']['missingNames']} 个表单控件缺少可访问名称")
    if raw.get("buttons", {}).get("empty", 0):
        issues.append(f"{raw['buttons']['empty']} 个按钮缺少可访问名称")
    if raw.get("links", {}).get("empty", 0):
        issues.append(f"{raw['links']['empty']} 个链接缺少可访问名称")
    if raw.get("h1Count", 0) != 1:
        issues.append(f"H1 数量为 {raw.get('h1Count', 0)}")
    score = max(0, 100 - min(90, len(issues) * 12))
    recommendations = [
        "补齐 label/aria-label/alt/lang 等基础语义",
        "后续可接 axe-core 做颜色对比、键盘可达性和 ARIA 规则检查",
    ] if issues else ["基础无障碍检查良好；后续可接 axe-core 做更完整规则扫描"]
    return _ok({"raw": raw, "summary": {"score": score, "issues": issues, "recommendations": recommendations}})


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
    "performance_audit": performance_audit,
    "load_test": load_test,
    "quality_audit": quality_audit,
    "security_audit": security_audit,
    "accessibility_audit": accessibility_audit,
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
    "performance_audit",
    "load_test",
    "quality_audit",
    "security_audit",
    "accessibility_audit",
]
