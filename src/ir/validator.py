"""
TestForge IR - Locator 验证器
=============================

验证定位器候选的有效性

参考 AutoQA-Agent src/ir/locator-validator.ts
"""

import asyncio
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page
    from . import ElementFingerprint, LocatorCandidate, LocatorKind


async def validate_candidate(
    page: "Page",
    candidate: "LocatorCandidate",
    action_type: str,
    original_fingerprint: "ElementFingerprint",
) -> "LocatorCandidate":
    """
    验证单个定位器候选

    检查项:
    - unique: count() == 1
    - visible: is_visible()
    - enabled: is_enabled() (click actions)
    - editable: is_editable() (fill actions)
    - fingerprint_match: 重新提取指纹是否匹配

    Args:
        page: Playwright page
        candidate: 定位器候选
        action_type: 操作类型 "click", "fill", "select", "assert"
        original_fingerprint: 原始元素指纹

    Returns:
        带验证结果的 LocatorCandidate
    """
    from . import LocatorKind

    # 构建 Playwright locator
    try:
        locator = _build_locator(page, candidate)
    except Exception as e:
        candidate.validation = {"error": f"locator_build_failed: {e}"}
        return candidate

    validation: Dict[str, Any] = {}

    # 1. Count check - 必须匹配恰好 1 个元素
    try:
        count = await locator.count()
        validation["unique"] = count == 1
        validation["count"] = count
        if count == 0:
            validation["error"] = "no_elements_found"
            candidate.validation = validation
            return candidate
        if count > 1:
            validation["error"] = "multiple_elements_found"
            candidate.validation = validation
            return candidate
    except Exception as e:
        validation["error"] = f"count_check_failed: {e}"
        candidate.validation = validation
        return candidate

    # 2. Visibility check
    try:
        validation["visible"] = await locator.is_visible(timeout=2000)
    except Exception:
        validation["visible"] = False

    # 3. Action-specific checks
    if action_type in ("click", "assert", "select"):
        try:
            validation["enabled"] = await locator.is_enabled()
        except Exception:
            validation["enabled"] = False

    if action_type == "fill":
        try:
            validation["editable"] = await locator.is_editable()
        except Exception:
            validation["editable"] = False

    # 4. Fingerprint match
    try:
        validation["fingerprintMatch"] = await _check_fingerprint_match(
            page, locator, original_fingerprint
        )
    except Exception as e:
        validation["fingerprintMatch"] = None  # 无法验证

    candidate.validation = validation
    return candidate


async def validate_candidates(
    page: "Page",
    candidates: List["LocatorCandidate"],
    action_type: str,
    original_fingerprint: "ElementFingerprint",
) -> List["LocatorCandidate"]:
    """
    并行验证多个定位器候选

    Args:
        page: Playwright page
        candidates: 候选列表
        action_type: 操作类型
        original_fingerprint: 原始元素指纹

    Returns:
        带验证结果的候选列表
    """
    tasks = [
        validate_candidate(page, candidate, action_type, original_fingerprint)
        for candidate in candidates
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    validated = []
    for r in results:
        if isinstance(r, Exception):
            continue
        validated.append(r)

    return validated


def filter_valid_candidates(
    candidates: List["LocatorCandidate"],
    action_type: str,
) -> List["LocatorCandidate"]:
    """
    筛选出通过验证的候选定位器

    Args:
        candidates: 已验证的候选列表
        action_type: 操作类型

    Returns:
        通过验证的候选列表（按优先级排序）
    """
    valid = []

    for c in candidates:
        v = c.validation
        if not v:
            continue

        # 跳过有错误的
        if v.get("error"):
            continue

        # 必须唯一匹配
        if not v.get("unique"):
            continue

        # 必须可见
        if not v.get("visible"):
            continue

        # 操作类型特定检查
        if action_type in ("click", "assert", "select"):
            if not v.get("enabled"):
                continue

        if action_type == "fill":
            if not v.get("editable"):
                continue

        valid.append(c)

    # 按优先级排序
    valid.sort(key=lambda x: x.kind.value)
    return valid


def get_best_valid_locator(
    candidates: List["LocatorCandidate"],
    action_type: str,
) -> Optional["LocatorCandidate"]:
    """
    获取最佳有效定位器

    Args:
        candidates: 已验证的候选列表
        action_type: 操作类型

    Returns:
        最佳定位器候选，或 None
    """
    valid = filter_valid_candidates(candidates, action_type)
    return valid[0] if valid else None


def get_validation_summary(candidates: List["LocatorCandidate"]) -> str:
    """
    获取验证摘要字符串（调试用）

    Args:
        candidates: 已验证的候选列表

    Returns:
        摘要字符串
    """
    lines = []
    for i, c in enumerate(candidates):
        v = c.validation
        status = "OK" if v and not v.get("error") else f"FAIL({v.get('error', 'unknown')})"
        lines.append(f"  [{i+1}] {c.kind.name}: {c.value[:40]} - {status}")
        if v:
            details = []
            if v.get("count") is not None:
                details.append(f"count={v['count']}")
            if v.get("visible") is not None:
                details.append(f"visible={v['visible']}")
            if v.get("enabled") is not None:
                details.append(f"enabled={v['enabled']}")
            if details:
                lines.append(f"       {' '.join(details)}")
    return "\n".join(lines)


def _build_locator(page: "Page", candidate: "LocatorCandidate") -> Any:
    """根据候选类型构建 Playwright locator"""
    from . import LocatorKind

    kind = candidate.kind
    fp_value = candidate.value

    # 从 code 字段直接解析 (如果已生成)
    if candidate.code:
        # code 格式是 page.getByXxx(...) 或 page.locator(...)
        # 我们直接构建 locator
        pass

    # 根据 kind 构建
    if kind == LocatorKind.TEST_ID:
        # 提取 testId 值
        import re
        m = re.search(r'getByTestId\(["\'](.*?)["\']\)', candidate.code or "")
        if m:
            test_id = m.group(1)
        else:
            # 从 value 中提取
            m = re.search(r'data-test["\']?\s*=\s*["\'](.*?)["\']', fp_value)
            test_id = m.group(1) if m else fp_value
        return page.get_by_test_id(test_id)

    elif kind == LocatorKind.ROLE:
        import re
        m = re.search(r'getByRole\(["\'](\w+)["\']', candidate.code or "")
        role = m.group(1) if m else "button"
        m2 = re.search(r'name=["\'](.*?)["\']', candidate.code or "")
        name = m2.group(1) if m2 else ""
        return page.get_by_role(role, name=name)

    elif kind == LocatorKind.LABEL:
        import re
        m = re.search(r'getByLabel\(["\'](.*?)["\']', candidate.code or "")
        label = m.group(1) if m else fp_value
        return page.get_by_label(label)

    elif kind == LocatorKind.PLACEHOLDER:
        import re
        m = re.search(r'getByPlaceholder\(["\'](.*?)["\']', candidate.code or "")
        ph = m.group(1) if m else fp_value
        return page.get_by_placeholder(ph)

    elif kind == LocatorKind.CSS_ID:
        import re
        m = re.search(r'locator\(["\'](#[^"\']+)["\']', candidate.code or "")
        sel = m.group(1) if m else fp_value
        return page.locator(sel)

    elif kind == LocatorKind.CSS_ATTR:
        import re
        m = re.search(r'locator\(["\'](.*?)["\']', candidate.code or "")
        sel = m.group(1) if m else fp_value
        return page.locator(sel)

    elif kind == LocatorKind.CSS_SELECTOR:
        return page.locator(fp_value)

    elif kind == LocatorKind.TEXT_EXACT:
        import re
        m = re.search(r'getByText\(["\'](.*?)["\']', candidate.code or "")
        text = m.group(1) if m else fp_value
        return page.get_by_text(text, exact=True)

    elif kind == LocatorKind.TEXT_FUZZY:
        import re
        m = re.search(r'getByText\(["\'](.*?)["\']', candidate.code or "")
        text = m.group(1) if m else fp_value
        return page.get_by_text(text, exact=False)

    # 回退
    return page.locator(fp_value)


async def _check_fingerprint_match(
    page: "Page",
    locator: Any,
    original_fp: "ElementFingerprint",
) -> Optional[bool]:
    """
    检查重新找到的元素指纹是否与原始指纹匹配

    Args:
        page: Playwright page
        locator: Playwright locator
        original_fp: 原始元素指纹

    Returns:
        True/False/None(无法验证)
    """
    try:
        element = await locator.element_handle(timeout=2000)
        if not element:
            return None

        # 重新提取指纹
        from .fingerprint import extract_fingerprint
        new_fp_dict = await extract_fingerprint(element)
        if not new_fp_dict:
            return None

        # 比较关键字段
        from . import ElementFingerprint
        new_fp = ElementFingerprint(
            tag_name=new_fp_dict.get("tagName"),
            id=new_fp_dict.get("id"),
            role=new_fp_dict.get("role"),
            accessible_name=new_fp_dict.get("accessibleName"),
            test_id=new_fp_dict.get("testId"),
        )

        return fingerprints_match(original_fp, new_fp)
    except Exception:
        return None


def fingerprints_match(a: "ElementFingerprint", b: "ElementFingerprint") -> bool:
    """
    比较两个指纹是否匹配

    匹配规则:
    - testId/id 精确匹配
    - 50%+ 属性匹配
    - text snippet 包含关系
    """
    # 1. 精确匹配 testId
    if a.test_id and b.test_id and a.test_id == b.test_id:
        return True

    # 2. 精确匹配 id
    if a.id and b.id and a.id == b.id:
        return True

    # 3. 计算属性匹配率
    fields_to_compare = [
        ("tag_name", a.tag_name, b.tag_name),
        ("role", a.role, b.role),
        ("accessible_name", a.accessible_name, b.accessible_name),
    ]

    matched = 0
    total = 0

    for field_name, val_a, val_b in fields_to_compare:
        if val_a and val_b:
            total += 1
            if val_a.lower() == val_b.lower():
                matched += 1

    if total > 0 and matched / total >= 0.5:
        return True

    # 4. Text snippet 包含关系
    if a.text_snippet and b.text_content:
        if a.text_snippet.lower() in b.text_content.lower():
            return True

    return False


__all__ = [
    "validate_candidate",
    "validate_candidates",
    "filter_valid_candidates",
    "get_best_valid_locator",
    "get_validation_summary",
    "fingerprints_match",
]