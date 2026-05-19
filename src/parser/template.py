"""
TestForge Parser - 模板变量支持
==============================

支持 {{VARIABLE}} 语法

参考 AutoQA-Agent src/markdown/template.ts
"""

import re
from typing import Dict, Any, Set


TEMPLATE_VAR_PATTERN = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}", re.IGNORECASE)


def extract_template_vars(text: str) -> Set[str]:
    """
    从文本中提取所有模板变量名

    Args:
        text: 包含 {{VAR}} 的文本

    Returns:
        变量名集合 {"BASE_URL", "USERNAME", ...}
    """
    matches = TEMPLATE_VAR_PATTERN.findall(text)
    return {m.upper() for m in matches}


def render_template(text: str, vars: Dict[str, str]) -> Dict[str, Any]:
    """
    渲染模板变量

    Args:
        text: 包含 {{VAR}} 的文本
        vars: 变量名到值的映射

    Returns:
        {ok, value} 或 {ok: False, message, unknown_vars, missing_vars}
    """
    unknown_vars = set()
    missing_vars = set()

    def replace_var(match):
        var_name = match.group(1).upper()
        if var_name in vars:
            return vars[var_name]
        elif var_name in ("BASE_URL",):
            # 默认值
            return ""
        else:
            missing_vars.add(var_name)
            return match.group(0)

    result = TEMPLATE_VAR_PATTERN.sub(replace_var, text)

    if unknown_vars:
        return {
            "ok": False,
            "code": "UNKNOWN_VARIABLES",
            "message": f"Unknown variables: {', '.join(sorted(unknown_vars))}",
            "unknown_vars": sorted(unknown_vars),
        }

    if missing_vars:
        return {
            "ok": False,
            "code": "MISSING_VARIABLES",
            "message": f"Missing variables: {', '.join(sorted(missing_vars))}",
            "missing_vars": sorted(missing_vars),
        }

    return {"ok": True, "value": result}


def render_markdown_template(markdown: str, vars: Dict[str, str]) -> Dict[str, Any]:
    """
    渲染整个 Markdown 文档的模板变量

    Args:
        markdown: Markdown 文本
        vars: 变量名到值的映射

    Returns:
        {ok, value} 或 {ok: False, message, unknown_vars, missing_vars}
    """
    unknown_vars = set()
    missing_vars = set()

    def replace_var(match):
        var_name = match.group(1).upper()
        if var_name in vars:
            return vars[var_name]
        else:
            missing_vars.add(var_name)
            return match.group(0)

    result = TEMPLATE_VAR_PATTERN.sub(replace_var, markdown)

    if unknown_vars:
        return {
            "ok": False,
            "code": "UNKNOWN_VARIABLES",
            "message": f"Unknown variables: {', '.join(sorted(unknown_vars))}",
            "unknown_vars": sorted(unknown_vars),
        }

    if missing_vars:
        return {
            "ok": False,
            "code": "MISSING_VARIABLES",
            "message": f"Missing variables: {', '.join(sorted(missing_vars))}",
            "missing_vars": sorted(missing_vars),
        }

    return {"ok": True, "value": result}


def get_template_vars(spec) -> Set[str]:
    """
    从 Spec 对象中提取所有变量

    Args:
        spec: Spec 对象

    Returns:
        变量名集合
    """
    vars_set: Set[str] = set()

    # 从 preconditions 中提取
    for pre in spec.preconditions:
        vars_set.update(extract_template_vars(pre))

    # 从 steps 中提取
    for step in spec.steps:
        vars_set.update(extract_template_vars(step.text))
        if step.expected:
            vars_set.update(extract_template_vars(step.expected))

    return vars_set


def validate_template_vars(spec, vars: Dict[str, str]) -> Dict[str, Any]:
    """
    验证 Spec 中的所有变量是否都已提供

    Args:
        spec: Spec 对象
        vars: 提供的变量映射

    Returns:
        {ok} 或 {ok: False, missing_vars}
    """
    required = get_template_vars(spec)
    provided = {k.upper() for k in vars.keys()}
    missing = required - provided

    if missing:
        return {
            "ok": False,
            "code": "MISSING_VARIABLES",
            "message": f"Missing variables: {', '.join(sorted(missing))}",
            "missing_vars": sorted(missing),
        }

    return {"ok": True}


__all__ = [
    "TEMPLATE_VAR_PATTERN",
    "extract_template_vars",
    "render_template",
    "render_markdown_template",
    "get_template_vars",
    "validate_template_vars",
]