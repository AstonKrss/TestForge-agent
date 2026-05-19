"""
TestForge Fill 工具
====================

表单填充，支持密码脱敏和模板变量
"""

import re
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


from .click import normalize_input, is_valid_ref, resolve_ref_locator, extract_selectors, pick_first_visible


class FillValue:
    """填充值表示"""
    def __init__(self, kind: str, name: Optional[str] = None, value: Optional[str] = None):
        self.kind = kind  # "template_var", "literal", "redacted"
        self.name = name
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "value": self.value,
        }


def build_fuzzy_regex(value: str):
    """构建模糊匹配正则"""
    STOP_WORDS = {
        "a", "an", "the", "with", "for", "to", "in", "on", "of",
        "and", "or", "input", "field", "textbox", "text", "box",
    }

    tokens = re.split(r'[^a-z0-9]+', value.lower())
    tokens = [t.strip() for t in tokens if t.strip() and t not in STOP_WORDS]

    if not tokens:
        return None

    if len(tokens) == 1:
        return re.compile(re.escape(tokens[0]), re.IGNORECASE)

    lookaheads = "".join(f"(?=.*{re.escape(t)})" for t in tokens)
    return re.compile(f"{lookaheads}.*", re.IGNORECASE)


async def resolve_fill_target(page: "Page", description: str) -> Optional["Locator"]:
    """解析填充目标"""
    description = normalize_input(description)
    candidates = []

    # CSS 选择器
    for selector in extract_selectors(description):
        try:
            candidates.append(page.locator(selector))
        except Exception:
            pass

    # getByRole
    for role in ["textbox", "combobox"]:
        try:
            candidates.append(page.get_by_role(role, name=description))
        except Exception:
            pass

    # getByLabel
    try:
        candidates.append(page.get_by_label(description))
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
        for role in ["textbox", "combobox"]:
            try:
                candidates.append(page.get_by_role(role, name=fuzzy))
            except Exception:
                pass
        try:
            candidates.append(page.get_by_placeholder(fuzzy))
        except Exception:
            pass

    for candidate in candidates:
        picked = await pick_first_visible(candidate)
        if picked:
            return picked

    return None


def compute_fill_value(
    text: str,
    is_password: bool = False,
    template_vars: Optional[list] = None,
) -> FillValue:
    """
    计算填充值表示

    Args:
        text: 填充文本
        is_password: 是否是密码字段
        template_vars: 模板变量列表

    Returns:
        FillValue
    """
    # 模板变量
    if template_vars:
        return FillValue(kind="template_var", name=template_vars[0])

    # 密码脱敏
    if is_password:
        return FillValue(kind="redacted")

    return FillValue(kind="literal", value=text)


async def fill(
    page: "Page",
    description: str = "",
    ref: str = "",
    text: str = "",
    step: Optional[int] = None,
    is_password: bool = False,
) -> Dict[str, Any]:
    """
    填写表单

    Args:
        page: Playwright Page
        description: 目标描述
        ref: 元素引用
        text: 填充文本
        step: 步骤索引
        is_password: 是否是密码字段

    Returns:
        工具结果
    """
    from .error import fail, ok, to_tool_error, ErrorCode

    # 规范化
    description = normalize_input(description)
    ref = normalize_input(ref)
    text = normalize_input(text)

    # 验证
    if not text:
        return fail(ErrorCode.INVALID_INPUT, "text is required")

    if not ref and not description:
        return fail(ErrorCode.INVALID_INPUT, "Either ref or description is required")

    locator = None
    use_ref = False

    # 优先 ref
    if ref:
        locator = await resolve_ref_locator(page, ref)
        use_ref = True

    # 描述定位
    if not locator:
        locator = await resolve_fill_target(page, description)

    if not locator:
        return fail(
            ErrorCode.ELEMENT_NOT_FOUND,
            f"Element not found: {description or ref}",
            retriable=True,
        )

    # 计算填充值
    fill_value = compute_fill_value(text, is_password)

    # 执行填充
    try:
        await locator.fill(text)
        return ok({
            "description": description,
            "ref": ref if use_ref else "",
            "text_length": len(text),
            "fill_value": fill_value.to_dict(),
            "step": step,
        })
    except Exception:
        # 尝试子元素
        try:
            descendant = locator.locator("input, textarea, [contenteditable='true']").first
            if await descendant.count() > 0:
                await descendant.fill(text)
                return ok({
                    "description": description,
                    "ref": ref if use_ref else "",
                    "text_length": len(text),
                    "fill_value": fill_value.to_dict(),
                    "step": step,
                })
        except Exception:
            pass

        error = to_tool_error(Exception("Fill failed"), default_code=ErrorCode.ELEMENT_NOT_EDITABLE)
        return fail(error.code, error.message, retriable=False)