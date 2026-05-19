"""
TestForge 断言工具
==================
"""

import re
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


from .click import normalize_input, is_valid_ref, resolve_ref_locator, pick_first_visible, STOP_WORDS


STOP_WORDS_EXTENDED = STOP_WORDS | {
    "input", "field", "textbox", "text", "box",
    "form", "id", "name", "placeholder", "data", "test",
}


def build_fuzzy_regex(value: str):
    """构建模糊匹配正则"""
    tokens = re.split(r'[^a-z0-9]+', value.lower())
    tokens = [t.strip() for t in tokens if t.strip() and t not in STOP_WORDS_EXTENDED]

    if not tokens:
        return None

    if len(tokens) == 1:
        return re.compile(re.escape(tokens[0]), re.IGNORECASE)

    lookaheads = "".join(f"(?=.*{re.escape(t)})" for t in tokens)
    return re.compile(f"{lookaheads}.*", re.IGNORECASE)


def extract_selectors(description: str) -> List[str]:
    """从描述中提取选择器"""
    selectors = []

    id_match = re.search(r"\bid\b\s*(?:[:=]|is)?\s*[\"']?([a-zA-Z0-9_-]+)[\"']?", description, re.IGNORECASE)
    if id_match and id_match.group(1):
        selectors.append(f"#{id_match.group(1)}")

    dt_match = re.search(r"\bdata-test\b\s*(?:[:=]|is)?\s*[\"']?([^\"'\"'\s]+)[\"']?", description, re.IGNORECASE)
    if dt_match and dt_match.group(1):
        selectors.append(f'[data-test="{dt_match.group(1)}"]')

    name_match = re.search(r"\bname\b\s*(?:[:=]|is)?\s*[\"']?([^\"'\"'\s]+)[\"']?", description, re.IGNORECASE)
    if name_match and name_match.group(1):
        selectors.append(f'[name="{name_match.group(1)}"]')

    return selectors


async def resolve_visible_element(page: "Page", description: str) -> Optional["Locator"]:
    """解析可见元素"""
    description = normalize_input(description)
    candidates = []

    # CSS 选择器
    for selector in extract_selectors(description):
        try:
            candidates.append(page.locator(selector))
        except Exception:
            pass

    # getByRole
    for role in ["combobox", "button", "link", "heading"]:
        try:
            candidates.append(page.get_by_role(role, name=description))
        except Exception:
            pass

    # getByPlaceholder
    try:
        candidates.append(page.get_by_placeholder(description))
    except Exception:
        pass

    # getByText
    try:
        candidates.append(page.get_by_text(description))
    except Exception:
        pass

    # 模糊匹配
    fuzzy = build_fuzzy_regex(description)
    if fuzzy:
        for role in ["combobox", "button", "link", "heading", "textbox"]:
            try:
                candidates.append(page.get_by_role(role, name=fuzzy))
            except Exception:
                pass
        try:
            candidates.append(page.get_by_text(fuzzy))
            candidates.append(page.get_by_placeholder(fuzzy))
        except Exception:
            pass

    for candidate in candidates:
        picked = await pick_first_visible(candidate)
        if picked:
            return picked

    return None


async def assert_element_visible(
    page: "Page",
    description: str = "",
    ref: str = "",
) -> Dict[str, Any]:
    """
    断言元素可见

    Args:
        page: Playwright Page
        description: 目标描述
        ref: 元素引用

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    description = normalize_input(description)
    ref = normalize_input(ref)

    if not ref and not description:
        return fail(ErrorCode.INVALID_INPUT, "Either ref or description is required")

    locator = None

    if ref:
        locator = await resolve_ref_locator(page, ref)
        if locator:
            count = await locator.count()
            if count > 0:
                if await locator.is_visible():
                    return ok({"description": description, "ref": ref})
                return fail(
                    ErrorCode.ASSERTION_FAILED,
                    f"Element with ref not visible: {ref}",
                    retriable=True,
                )

    if not locator:
        locator = await resolve_visible_element(page, description)

    if locator:
        return ok({"description": description})

    return fail(
        ErrorCode.ASSERTION_FAILED,
        f"Element not visible: {description}",
        retriable=True,
    )


async def assert_text_present(page: "Page", text: str) -> Dict[str, Any]:
    """
    断言页面包含文本

    Args:
        page: Playwright Page
        text: 要查找的文本

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    text = normalize_input(text)

    if not text:
        return fail(ErrorCode.INVALID_INPUT, "text is required")

    try:
        locator = page.get_by_text(text)
        count = await locator.count()

        if count > 0:
            limit = min(count, 5)
            for i in range(limit):
                if await locator.nth(i).is_visible():
                    return ok({"text_length": len(text)})

        return fail(
            ErrorCode.ASSERTION_FAILED,
            f"Text not found: {text}",
            retriable=True,
        )
    except Exception as e:
        error = to_tool_error(e, default_code=ErrorCode.ASSERTION_FAILED)
        return fail(error.code, error.message, retriable=error.retriable)