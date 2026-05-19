"""
TestForge Click 工具
====================

Ref-First 智能点击
优先使用 aria-ref 定位，降级到描述定位
"""

import re
from typing import Optional, Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


# 停用词
STOP_WORDS = {
    "a", "an", "the", "with", "for", "to", "in", "on", "of",
    "and", "or", "button", "link", "element", "item",
}


def is_valid_ref(ref: str) -> bool:
    """检查是否是有效的 ref 格式 (如 e15)"""
    return bool(re.match(r"^e\d+$", ref))


def normalize_input(value: str) -> str:
    """
    规范化输入

    1. 移除首尾引号
    2. 移除 Markdown 代码块
    """
    if not value:
        return ""

    value = value.strip()

    # 移除代码块
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        value = value[1:-1].strip()

    # 移除引号
    if len(value) >= 2:
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1].strip()

    return value


def normalize_for_matching(value: str) -> str:
    """规范化文本用于匹配"""
    tokens = re.split(r'[^a-z0-9]+', value.lower())
    tokens = [t.strip() for t in tokens if t.strip() and t not in STOP_WORDS]
    return " ".join(tokens)


def extract_selectors(description: str) -> List[str]:
    """从描述中提取 CSS 选择器"""
    selectors = []

    # id 选择器
    id_match = re.search(r"\bid\b\s*(?:[:=]|is)?\s*[\"']?([a-zA-Z0-9_-]+)[\"']?", description, re.IGNORECASE)
    if id_match and id_match.group(1):
        selectors.append(f"#{id_match.group(1)}")

    # data-test
    dt_match = re.search(r"\bdata-test\b\s*(?:[:=]|is)?\s*[\"']?([^\"'\"'\s]+)[\"']?", description, re.IGNORECASE)
    if dt_match and dt_match.group(1):
        selectors.append(f'[data-test="{dt_match.group(1)}"]')

    # name 属性
    name_match = re.search(r"\bname\b\s*(?:[:=]|is)?\s*[\"']?([^\"'\"'\s]+)[\"']?", description, re.IGNORECASE)
    if name_match and name_match.group(1):
        selectors.append(f'[name="{name_match.group(1)}"]')

    # class
    cls_match = re.search(r"\bclass\b\s*(?:[:=]|is)?\s*[\"']?([a-zA-Z0-9_-]+)[\"']?", description, re.IGNORECASE)
    if cls_match and cls_match.group(1):
        selectors.append(f".{cls_match.group(1)}")

    return selectors


def build_fuzzy_regex(value: str):
    """构建模糊匹配正则"""
    normalized = normalize_for_matching(value)
    if not normalized:
        return None

    tokens = normalized.split()
    if not tokens:
        return None

    if len(tokens) == 1:
        return re.compile(re.escape(tokens[0]), re.IGNORECASE)

    lookaheads = "".join(f"(?=.*{re.escape(t)})" for t in tokens)
    return re.compile(f"{lookaheads}.*", re.IGNORECASE)


async def resolve_ref_locator(page: "Page", ref: str) -> Optional["Locator"]:
    """使用 aria-ref 解析元素"""
    if not is_valid_ref(ref):
        return None

    try:
        locator = page.locator(f"aria-ref={ref}").first
        count = await locator.count()
        if count > 0:
            return locator
    except Exception:
        pass

    return None


async def pick_first_visible(locator: "Locator") -> Optional["Locator"]:
    """选择第一个可见元素"""
    try:
        count = await locator.count()
        if count <= 0:
            return None

        limit = min(count, 5)
        for i in range(limit):
            candidate = locator.nth(i)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue

        return locator.first
    except Exception:
        return None


async def resolve_click_target(page: "Page", description: str) -> Optional["Locator"]:
    """
    解析点击目标

    使用 9 层优先级
    """
    description = normalize_input(description)
    candidates: List["Locator"] = []

    # 层级1-2: CSS 选择器
    for selector in extract_selectors(description):
        try:
            candidates.append(page.locator(selector))
        except Exception:
            pass

    # 层级3-5: getByRole
    for role in ["combobox", "button", "link"]:
        try:
            candidates.append(page.get_by_role(role, name=description))
        except Exception:
            pass

    # 层级6: getByText
    try:
        candidates.append(page.get_by_text(description))
    except Exception:
        pass

    # 层级7: 模糊匹配
    fuzzy = build_fuzzy_regex(description)
    if fuzzy:
        for role in ["combobox", "button", "link"]:
            try:
                candidates.append(page.get_by_role(role, name=fuzzy))
            except Exception:
                pass
        try:
            candidates.append(page.get_by_text(fuzzy))
        except Exception:
            pass

    # 选择第一个可见的
    for candidate in candidates:
        picked = await pick_first_visible(candidate)
        if picked:
            return picked

    return None


async def try_select_option(page: "Page", label: str) -> bool:
    """尝试 select option 处理"""
    try:
        select = page.locator("select").filter(has_text=label).first
        if await select.count() > 0 and await select.is_visible():
            await select.select_option(label=label)
            return True
    except Exception:
        pass

    return False


async def click(
    page: "Page",
    description: str = "",
    ref: str = "",
    step: Optional[int] = None,
) -> Dict[str, Any]:
    """
    点击元素

    Args:
        page: Playwright Page
        description: 元素描述
        ref: 元素引用 (来自快照)
        step: 步骤索引

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    # 规范化
    description = normalize_input(description)
    ref = normalize_input(ref)

    # 验证
    if not ref and not description:
        return fail(ErrorCode.INVALID_INPUT, "Either ref or description is required")

    if ref and not is_valid_ref(ref):
        return fail(ErrorCode.INVALID_INPUT, f"Invalid ref: {ref}")

    locator = None
    use_ref = False

    # 优先 ref
    if ref:
        locator = await resolve_ref_locator(page, ref)
        use_ref = True

    # 使用描述定位
    if not locator:
        locator = await resolve_click_target(page, description)

    # select option 降级
    if not locator:
        if await try_select_option(page, description or ref):
            return ok({"description": description, "ref": ref, "step": step})

    if not locator:
        return fail(
            ErrorCode.ELEMENT_NOT_FOUND,
            f"Element not found: {description or ref}",
            retriable=True,
        )

    # 执行点击
    try:
        await locator.click()
        return ok({"description": description, "ref": ref if use_ref else "", "step": step})
    except Exception as e:
        error = to_tool_error(e)

        # 处理 select 拦截
        msg = str(e).lower()
        if "intercepts pointer events" in msg and "select" in msg:
            if await try_select_option(page, description or ref):
                return ok({"description": description, "ref": ref, "step": step})

        return fail(
            error.code,
            error.message,
            retriable=error.retriable,
        )