"""
TestForge IR - 元素指纹提取
==========================

从 DOM 元素提取稳定特征
"""

from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle


async def extract_fingerprint(handle: "ElementHandle") -> Optional[Dict[str, Any]]:
    """
    从元素提取指纹

    Args:
        handle: Playwright 元素句柄

    Returns:
        元素指纹字典
    """
    try:
        # 获取所有属性
        properties = await handle.evaluate("""
// Element properties extractor
const el = document.activeElement;
const props = {
    tagName: el.tagName?.toLowerCase(),
    id: el.id || null,
    className: el.className || null,
    name: el.name || null,
    type: el.type || null,
    role: el.getAttribute('role') || null,
    ariaLabel: el.getAttribute('aria-label') || null,
    ariaRole: el.getAttribute('aria-role') || null,
    placeholder: el.placeholder || null,
    textContent: el.textContent?.trim() || null,
    testId: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || null,
    dataTest: el.getAttribute('data-test') || null,
};
// Text snippet (first 50 chars)
props.textSnippet = props.textContent ? props.textContent.slice(0, 50) : null;
props
""")
        return properties
    except Exception:
        return None


async def extract_accessible_name(handle: "ElementHandle") -> Optional[str]:
    """
    提取无障碍名称

    Args:
        handle: Playwright 元素句柄

    Returns:
        无障碍名称
    """
    try:
        return await handle.evaluate("""
// Get accessible name following ARIA spec
const el = document.activeElement;

// 1. aria-labelledby
if (el.hasAttribute('aria-labelledby')) {
    const ids = el.getAttribute('aria-labelledby').split(' ');
    const names = ids.map(id => document.getElementById(id)?.textContent?.trim()).filter(Boolean);
    if (names.length) return names.join(' ');
}

// 2. aria-label
if (el.hasAttribute('aria-label')) {
    return el.getAttribute('aria-label');
}

// 3. label element
if (el.id) {
    const label = document.querySelector(`label[for="${el.id}"]`);
    if (label) return label.textContent?.trim();
}

// 4. placeholder
if (el.placeholder) return el.placeholder;

// 5. text content
return el.textContent?.trim() || null;
""")
    except Exception:
        return None


def fingerprint_to_search_text(fp: Dict[str, Any]) -> str:
    """
    将指纹转换为搜索文本

    用于模糊匹配
    """
    fields = [
        fp.get("accessibleName"),
        fp.get("ariaLabel"),
        fp.get("textSnippet"),
        fp.get("id"),
        fp.get("testId"),
        fp.get("nameAttr"),
        fp.get("placeholder"),
        fp.get("role"),
        fp.get("tagName"),
    ]

    text = " ".join(f for f in fields if f and isinstance(f, str) and f.strip())
    return text.lower()