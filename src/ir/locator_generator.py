"""
TestForge IR - 定位器生成器
==========================

基于元素指纹生成稳定的定位器
"""

import re
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from . import ElementFingerprint, LocatorCandidate, LocatorKind, LocatorChain, calculate_priority_score


# 停用词集合 (用于模糊匹配)
STOP_WORDS = {
    "a", "an", "the", "with", "for", "to", "in", "on", "of",
    "and", "or", "input", "field", "textbox", "text", "box",
    "element", "form", "id", "name", "placeholder", "data", "test",
    "button", "link", "item",
}


def normalize_for_matching(value: str) -> str:
    """
    规范化文本用于匹配

    1. 转小写
    2. 分词
    3. 过滤停用词
    4. 合并
    """
    tokens = re.split(r'[^a-z0-9]+', value.lower())
    tokens = [t.strip() for t in tokens if t.strip() and t not in STOP_WORDS]
    return " ".join(tokens)


def _generate_code(fp: "ElementFingerprint", kind: "LocatorKind", value: str) -> str:
    """Generate Playwright API code for a locator candidate."""
    # Extract the meaningful value from the existing value field
    if kind == LocatorKind.TEST_ID:
        test_id = fp.test_id or fp.data_test or ""
        return f'page.getByTestId("{test_id}")'
    elif kind == LocatorKind.ROLE:
        name = fp.accessible_name or fp.aria_label or fp.text_snippet or ""
        role = fp.role or "button"
        return f'page.getByRole("{role}", name="{name}")'
    elif kind == LocatorKind.LABEL:
        label = fp.accessible_name or ""
        return f'page.getByLabel("{label}")'
    elif kind == LocatorKind.PLACEHOLDER:
        placeholder = fp.placeholder or ""
        return f'page.getByPlaceholder("{placeholder}")'
    elif kind == LocatorKind.CSS_ID:
        return f'page.locator("#{fp.id}")'
    elif kind == LocatorKind.CSS_ATTR:
        # Try to extract attribute from value like [name="x"]
        import re as re_module
        m = re_module.match(r'\[(\w+)=["\'](.*?)["\']\]', value)
        if m:
            attr, attr_val = m.groups()
            return f'page.locator("[{attr}=\'{attr_val}\']")'
        return f'page.locator("{value}")'
    elif kind == LocatorKind.CSS_SELECTOR:
        return f'page.locator("{value}")'
    elif kind == LocatorKind.TEXT_EXACT:
        text = fp.text_content and fp.text_content.strip() or ""
        return f'page.getByText("{text}", exact=True)'
    elif kind == LocatorKind.TEXT_FUZZY:
        text = fp.text_content and fp.text_content.strip() or fp.text_snippet or ""
        return f'page.getByText("{text}")'
    return f'page.locator("{value}")'


def generate_locator_chain(fp: "ElementFingerprint") -> "LocatorChain":
    """
    为元素指纹生成定位器链

    Args:
        fp: 元素指纹

    Returns:
        LocatorChain: 排序后的定位器候选列表
    """
    from . import LocatorCandidate, LocatorChain, LocatorKind, calculate_priority_score

    chain = LocatorChain()
    candidates: List[LocatorCandidate] = []

    # 层级1: TEST_ID
    if fp.test_id or fp.data_test:
        value = fp.test_id or fp.data_test
        css_val = f'[data-test="{value}"]'
        candidates.append(LocatorCandidate(
            kind=LocatorKind.TEST_ID,
            value=css_val,
            priority_score=calculate_priority_score(fp, LocatorKind.TEST_ID),
            code=_generate_code(fp, LocatorKind.TEST_ID, css_val),
        ))

    # 层级2: ROLE
    if fp.role:
        role_value = fp.accessible_name or fp.aria_label or fp.text_snippet or ""
        candidates.append(LocatorCandidate(
            kind=LocatorKind.ROLE,
            value=f'role={fp.role}, name={role_value}',
            priority_score=calculate_priority_score(fp, LocatorKind.ROLE),
            code=_generate_code(fp, LocatorKind.ROLE, ""),
        ))

    # 层级3: LABEL
    if fp.accessible_name and fp.tag_name in ("input", "textarea", "select"):
        candidates.append(LocatorCandidate(
            kind=LocatorKind.LABEL,
            value=f'label={fp.accessible_name}',
            priority_score=calculate_priority_score(fp, LocatorKind.LABEL),
            code=_generate_code(fp, LocatorKind.LABEL, ""),
        ))

    # 层级4: PLACEHOLDER
    if fp.placeholder:
        candidates.append(LocatorCandidate(
            kind=LocatorKind.PLACEHOLDER,
            value=f'placeholder={fp.placeholder}',
            priority_score=calculate_priority_score(fp, LocatorKind.PLACEHOLDER),
            code=_generate_code(fp, LocatorKind.PLACEHOLDER, ""),
        ))

    # 层级5: CSS_ID
    if fp.id:
        css_val = f'#{fp.id}'
        candidates.append(LocatorCandidate(
            kind=LocatorKind.CSS_ID,
            value=css_val,
            priority_score=calculate_priority_score(fp, LocatorKind.CSS_ID),
            code=_generate_code(fp, LocatorKind.CSS_ID, css_val),
        ))

    # 层级6: CSS_ATTR
    if fp.name_attr:
        css_val = f'[name="{fp.name_attr}"]'
        candidates.append(LocatorCandidate(
            kind=LocatorKind.CSS_ATTR,
            value=css_val,
            priority_score=calculate_priority_score(fp, LocatorKind.CSS_ATTR),
            code=_generate_code(fp, LocatorKind.CSS_ATTR, css_val),
        ))

    if fp.test_id:
        css_val = f'[data-test="{fp.test_id}"]'
        candidates.append(LocatorCandidate(
            kind=LocatorKind.CSS_ATTR,
            value=css_val,
            priority_score=calculate_priority_score(fp, LocatorKind.CSS_ATTR),
            code=_generate_code(fp, LocatorKind.CSS_ATTR, css_val),
        ))

    # 层级7: CSS_SELECTOR
    selector_parts = []
    if fp.tag_name:
        selector_parts.append(fp.tag_name)
    if fp.class_name:
        # 取第一个类名
        first_class = fp.class_name.split()[0] if fp.class_name else None
        if first_class:
            selector_parts.append(f'.{first_class}')
    if selector_parts:
        css_val = "".join(selector_parts)
        candidates.append(LocatorCandidate(
            kind=LocatorKind.CSS_SELECTOR,
            value=css_val,
            priority_score=calculate_priority_score(fp, LocatorKind.CSS_SELECTOR),
            code=_generate_code(fp, LocatorKind.CSS_SELECTOR, css_val),
        ))

    # 层级8: TEXT_EXACT
    if fp.text_content and fp.text_content.strip():
        text = fp.text_content.strip()
        if len(text) >= 2 and len(text) <= 100:
            candidates.append(LocatorCandidate(
                kind=LocatorKind.TEXT_EXACT,
                value=f'text={text}',
                priority_score=calculate_priority_score(fp, LocatorKind.TEXT_EXACT),
                code=_generate_code(fp, LocatorKind.TEXT_EXACT, ""),
            ))

    # 层级9: TEXT_FUZZY
    if fp.text_snippet:
        normalized = normalize_for_matching(fp.text_snippet)
        if normalized:
            candidates.append(LocatorCandidate(
                kind=LocatorKind.TEXT_FUZZY,
                value=f'text={normalized}',
                priority_score=calculate_priority_score(fp, LocatorKind.TEXT_FUZZY),
                code=_generate_code(fp, LocatorKind.TEXT_FUZZY, ""),
            ))

    # 按优先级排序
    candidates.sort(key=lambda c: (c.kind.value, -c.priority_score))

    for c in candidates:
        chain.add(c)

    # 设置最佳候选
    if candidates:
        chain.best_candidate = candidates[0]

    return chain


def generate_best_locator(fp: "ElementFingerprint") -> str:
    """
    生成最佳定位器字符串

    Args:
        fp: 元素指纹

    Returns:
        str: 最佳定位器
    """
    chain = generate_locator_chain(fp)
    if chain.best_candidate:
        return f"{chain.best_candidate.kind.name}: {chain.best_candidate.value}"
    return ""


def generate_playwright_locator(fp: "ElementFingerprint") -> str:
    """
    生成 Playwright 风格的定位器

    Returns:
        str: Playwright API 调用代码
    """
    # 实现 Playwright 定位器生成
    if fp.test_id:
        return f'page.getByTestId("{fp.test_id}")'

    if fp.role and fp.accessible_name:
        return f'page.getByRole("{fp.role}", name="{fp.accessible_name}")'

    if fp.accessible_name and fp.tag_name in ("input", "textarea", "select"):
        return f'page.getByLabel("{fp.accessible_name}")'

    if fp.placeholder:
        return f'page.getByPlaceholder("{fp.placeholder}")'

    if fp.id:
        return f'page.locator("#{fp.id}")'

    if fp.name_attr:
        return f'page.locator("[name=\'{fp.name_attr}\']")'

    if fp.text_content:
        return f'page.getByText("{fp.text_content.strip()}")'

    return f'page.locator("{fp.tag_name or "unknown"}")'