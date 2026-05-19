"""
TestForge Parser - Include 支持
==============================

支持 include: 语法引用可复用的步骤片段

参考 AutoQA-Agent src/markdown/include.ts
"""

import re
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any


INCLUDE_PATTERN = re.compile(r"^[\s]*include:\s*([a-zA-Z0-9_\-./]+)[\s]*$", re.IGNORECASE)


def is_include_step(step_text: str) -> bool:
    """
    检查是否是 include 步骤

    Returns:
        True 如果文本是 include: step-name 格式
    """
    return bool(INCLUDE_PATTERN.match(step_text))


def parse_include_name(step_text: str) -> Optional[str]:
    """
    从 include 步骤中提取名称

    Args:
        step_text: include: step-name

    Returns:
        step-name 或 None
    """
    m = INCLUDE_PATTERN.match(step_text)
    if m:
        return m.group(1).strip()
    return None


def validate_include_name(name: str) -> Dict[str, Any]:
    """
    验证 include 名称

    规则:
    - 不允许路径遍历 (..)
    - 不允许反斜杠
    - 只允许字母、数字、下划线、连字符、正斜杠、.md
    """
    # 路径遍历检查
    if ".." in name:
        return {"ok": False, "code": "INVALID_INCLUDE_NAME", "message": "Path traversal not allowed"}

    # 反斜杠检查
    if "\\" in name:
        return {"ok": False, "code": "INVALID_INCLUDE_NAME", "message": "Backslash not allowed"}

    # 字符白名单
    allowed_pattern = r"^[a-zA-Z0-9_\-./]+$"
    if not re.match(allowed_pattern, name):
        return {"ok": False, "code": "INVALID_INCLUDE_NAME", "message": "Invalid characters"}

    return {"ok": True}


def resolve_include_path(name: str, include_root: str) -> Path:
    """
    解析 include 路径

    查找顺序:
    1. steps/{name}.md
    2. specs/steps/{name}.md
    3. {name}.md (相对于 include_root)
    """
    root = Path(include_root)

    # 如果已经有 .md 后缀
    if name.endswith(".md"):
        # 直接相对于 root
        path = root / name
        if path.exists():
            return path
    else:
        # 尝试添加 .md 后缀
        candidates = [
            root / "steps" / f"{name}.md",
            root / "specs" / "steps" / f"{name}.md",
            root / f"{name}.md",
        ]
        for path in candidates:
            if path.exists():
                return path

    # 返回默认路径（用于错误消息）
    return root / "steps" / f"{name}.md"


def expand_includes(
    step_texts: List[str],
    include_root: str,
    read_file_fn: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """
    展开 include 步骤

    Args:
        step_texts: 步骤文本列表
        include_root: include 文件根目录
        read_file_fn: 读取文件函数，默认使用 Path.read_text

    Returns:
        {ok, steps} 或 {ok: False, error}
    """
    if read_file_fn is None:
        def read_file_fn(path: str) -> str:
            return Path(path).read_text(encoding="utf-8")

    expanded = []

    for step_text in step_texts:
        if not is_include_step(step_text):
            expanded.append(step_text)
            continue

        name = parse_include_name(step_text)

        # 验证名称
        validation = validate_include_name(name)
        if not validation["ok"]:
            return {
                "ok": False,
                "code": validation["code"],
                "message": f"Invalid include name '{name}': {validation['message']}",
            }

        # 解析路径
        path = resolve_include_path(name, include_root)

        if not path.exists():
            return {
                "ok": False,
                "code": "INCLUDE_NOT_FOUND",
                "message": f"Include file not found: {path}",
            }

        # 读取并解析 include 文件
        try:
            content = read_file_fn(str(path))
        except Exception as e:
            return {
                "ok": False,
                "code": "INCLUDE_READ_ERROR",
                "message": f"Cannot read include file: {e}",
            }

        # 提取步骤部分
        steps_text = extract_steps_from_markdown(content)
        if not steps_text:
            return {
                "ok": False,
                "code": "EMPTY_INCLUDE",
                "message": f"Include file has no steps: {path}",
            }

        # 递归检查（禁止嵌套 include）
        included_lines = steps_text.split("\n")
        for line in included_lines:
            if is_include_step(line.strip()):
                return {
                    "ok": False,
                    "code": "NESTED_INCLUDE_NOT_ALLOWED",
                    "message": "Nested include is not allowed",
                }

        # 添加到展开列表
        expanded.extend(included_lines)

    return {"ok": True, "steps": expanded}


def extract_steps_from_markdown(content: str) -> str:
    """
    从 Markdown 内容中提取步骤文本

    查找 ## Steps 部分
    """
    import re as re_module

    # 查找 ## Steps 部分
    match = re_module.search(
        r"##\s*Steps\s*\n((?:.*\n)*)",
        content,
        re_module.IGNORECASE | re_module.MULTILINE
    )

    if not match:
        return ""

    steps_text = match.group(1).strip()

    # 移除编号前缀
    lines = []
    for line in steps_text.split("\n"):
        # 移除 1. 2. 等前缀
        m = re_module.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if m:
            lines.append(m.group(2).strip())
        elif line.strip():
            lines.append(line.strip())

    return "\n".join(lines)


__all__ = [
    "is_include_step",
    "parse_include_name",
    "validate_include_name",
    "resolve_include_path",
    "expand_includes",
    "extract_steps_from_markdown",
]