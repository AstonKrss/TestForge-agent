"""
TestForge Runner - Playwright Test Exporter
==========================================

从 IR 记录导出 Playwright Python 测试文件

参考 AutoQA-Agent src/runner/export-playwright-test.ts
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    # 移除 [\/:*?"<>|]
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    # 空格替换为下划线
    name = name.replace(" ", "_")
    # 限制长度
    if len(name) > 100:
        name = name[:100]
    return name or "test"


def get_export_dir(cwd: str, export_dir: Optional[str] = None) -> Path:
    """获取导出目录"""
    if export_dir:
        path = Path(cwd) / export_dir
    else:
        path = Path(cwd) / "tests" / "testforge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_export_path(cwd: str, spec_path: str, export_dir: Optional[str] = None) -> Path:
    """获取导出文件路径"""
    export_dir_path = get_export_dir(cwd, export_dir)
    spec_name = Path(spec_path).stem
    safe_name = sanitize_filename(spec_name)
    return export_dir_path / f"{safe_name}.py"


def ensure_export_dir(cwd: str, export_dir: Optional[str] = None) -> Path:
    """确保导出目录存在"""
    return get_export_dir(cwd, export_dir)


# ==================== 代码生成函数 ====================

def generate_navigate_code(record: Dict[str, Any], base_url: str) -> str:
    """生成 navigate 代码"""
    tool_input = record.get("toolInput", {})
    url = tool_input.get("url", "/")

    # 处理相对路径
    if not url.startswith("http"):
        url = f'BASE_URL + "/{url.lstrip("/")}"'
    else:
        url = f'"{url}"'

    return f"page.goto({url})"


def generate_click_code(record: Dict[str, Any]) -> str:
    """生成 click 代码"""
    element = record.get("element", {})
    chosen = element.get("chosenLocator", {})
    code = chosen.get("code", "")

    if code and code.startswith("page."):
        # 直接使用 code
        return f"{code}.click()"
    else:
        # 回退：生成基于 kind 的代码
        kind = chosen.get("kind", "")
        return f"# TODO: implement click with locator kind {kind}"


def generate_fill_code(record: Dict[str, Any]) -> str:
    """生成 fill 代码"""
    tool_input = record.get("toolInput", {})
    element = record.get("element", {})
    chosen = element.get("chosenLocator", {})
    code = chosen.get("code", "")

    # 获取填充值
    fill_value = tool_input.get("fillValue", {})
    if fill_value.get("kind") == "literal":
        # 显示长度而非实际值（安全）
        length = fill_value.get("length", 0)
        text = f'"x" * {length}'
    elif fill_value.get("kind") == "template_var":
        var_name = fill_value.get("name", "")
        text = f"os.environ.get('{var_name}', '')"
    elif fill_value.get("kind") == "redacted":
        text = 'os.environ.get("PASSWORD", "")'
    else:
        text = '"test_value"'

    if code and code.startswith("page."):
        return f"{code}.fill({text})"
    else:
        kind = chosen.get("kind", "")
        return f"# TODO: implement fill with locator kind {kind}"


def generate_select_code(record: Dict[str, Any]) -> str:
    """生成 select_option 代码"""
    tool_input = record.get("toolInput", {})
    label = tool_input.get("label", "")
    element = record.get("element", {})
    chosen = element.get("chosenLocator", {})
    code = chosen.get("code", "")

    if code and code.startswith("page."):
        return f'{code}.select_option("{label}")'
    else:
        return f'# TODO: implement select_option'


def generate_assert_code(record: Dict[str, Any]) -> str:
    """生成 assert 代码"""
    tool_input = record.get("toolInput", {})
    tool_name = record.get("toolName", "")

    if tool_name == "assertTextPresent":
        text = tool_input.get("text", "")
        return f'assert "{text}" in page.content()'

    if tool_name == "assertElementVisible":
        element = record.get("element", {})
        chosen = element.get("chosenLocator", {})
        code = chosen.get("code", "")
        if code and code.startswith("page."):
            return f"expect({code}).to_be_visible()"

    return f"# TODO: implement {tool_name}"


def generate_wait_code(record: Dict[str, Any]) -> str:
    """生成 wait 代码"""
    tool_input = record.get("toolInput", {})
    seconds = tool_input.get("seconds", 1)
    return f"page.wait_for_timeout({seconds * 1000})"


# ==================== 主导出函数 ====================

def generate_step_code(
    record: Dict[str, Any],
    base_url: str,
    step_vars: Optional[Dict[str, str]] = None,
) -> str:
    """生成单个步骤的代码"""
    tool_name = record.get("toolName", "")
    step_index = record.get("stepIndex", 0)
    step_text = record.get("stepText", "")

    lines = [f"\n    # Step {step_index}: {step_text}"]

    try:
        if tool_name == "navigate":
            lines.append(f"    {generate_navigate_code(record, base_url)}")
        elif tool_name == "click":
            lines.append(f"    {generate_click_code(record)}")
        elif tool_name == "fill":
            lines.append(f"    {generate_fill_code(record)}")
        elif tool_name == "select_option":
            lines.append(f"    {generate_select_code(record)}")
        elif tool_name in ("assertTextPresent", "assertElementVisible"):
            lines.append(f"    {generate_assert_code(record)}")
        elif tool_name == "wait":
            lines.append(f"    {generate_wait_code(record)}")
        elif tool_name == "snapshot":
            lines.append(f"    # snapshot captured")
        elif tool_name == "scroll":
            lines.append(f"    # scroll action")
        else:
            lines.append(f"    # {tool_name} not implemented")
    except Exception as e:
        lines.append(f"    # Error generating code: {e}")

    return "\n".join(lines)


def generate_test_file_content(
    spec_path: str,
    records: List[Dict[str, Any]],
    base_url: str = "",
    spec_name: Optional[str] = None,
) -> str:
    """
    生成完整的测试文件内容

    Args:
        spec_path: 原始 spec 路径
        records: IR 记录列表
        base_url: 基础 URL
        spec_name: 测试函数名

    Returns:
        Python 测试文件内容
    """
    if spec_name is None:
        spec_name = Path(spec_path).stem
    safe_name = sanitize_filename(spec_name)
    func_name = f"test_{safe_name}"

    # 文件头部
    lines = [
        '"""',
        f"TestForge Exported Test: {spec_name}",
        '"""',
        "",
        "from playwright.sync_api import expect",
        "import os",
        "",
        f'BASE_URL = os.environ.get("TF_BASE_URL", "{base_url}")',
        "",
        "",
        f"def {func_name}(page):",
        f'    """Auto-generated test from {Path(spec_path).name}"""',
    ]

    # 生成每个步骤的代码
    for record in records:
        step_code = generate_step_code(record, base_url)
        lines.append(step_code)

    lines.append("")
    return "\n".join(lines)


def export_from_ir(
    cwd: str,
    run_id: str,
    spec_path: str,
    export_dir: Optional[str] = None,
    base_url: str = "",
) -> Dict[str, Any]:
    """
    从 IR 记录导出 Playwright 测试文件

    Args:
        cwd: 工作目录
        run_id: 运行ID
        spec_path: spec 文件路径
        export_dir: 导出目录（可选）
        base_url: 基础 URL

    Returns:
        {ok, path, message}
    """
    # 读取 IR 记录
    from .ir_reader import get_spec_action_records

    records = get_spec_action_records(cwd, run_id, spec_path)
    if not records:
        return {
            "ok": False,
            "code": "NO_RECORDS",
            "message": f"No IR records found for {spec_path}",
        }

    # 过滤成功的元素操作记录
    element_targeting_tools = {"click", "fill", "select_option", "assertElementVisible", "navigate", "assertTextPresent"}
    valid_records = []
    for record in records:
        outcome = record.get("outcome", {})
        if outcome.get("ok"):
            tool_name = record.get("toolName", "")
            if tool_name in element_targeting_tools:
                valid_records.append(record)

    if not valid_records:
        return {
            "ok": False,
            "code": "NO_VALID_RECORDS",
            "message": "No valid action records to export",
        }

    # 生成文件内容
    content = generate_test_file_content(
        spec_path=spec_path,
        records=valid_records,
        base_url=base_url,
    )

    # 写入文件
    export_path = get_export_path(cwd, spec_path, export_dir)
    ensure_export_dir(cwd, export_dir)

    try:
        with open(export_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "ok": True,
            "path": str(export_path),
            "message": f"Exported {len(valid_records)} steps to {export_path}",
        }
    except Exception as e:
        return {
            "ok": False,
            "code": "WRITE_ERROR",
            "message": f"Failed to write file: {e}",
        }


def export_all_specs(
    cwd: str,
    run_id: str,
    spec_paths: List[str],
    export_dir: Optional[str] = None,
    base_url: str = "",
) -> Dict[str, Any]:
    """
    导出多个 spec 的测试

    Args:
        cwd: 工作目录
        run_id: 运行ID
        spec_paths: spec 路径列表
        export_dir: 导出目录
        base_url: 基础 URL

    Returns:
        {ok, exported, failed}
    """
    exported = []
    failed = []

    for spec_path in spec_paths:
        result = export_from_ir(cwd, run_id, spec_path, export_dir, base_url)
        if result["ok"]:
            exported.append(result["path"])
        else:
            failed.append({"spec": spec_path, "error": result.get("message")})

    return {
        "ok": len(failed) == 0,
        "exported": exported,
        "failed": failed,
        "summary": f"Exported {len(exported)}/{len(spec_paths)} specs",
    }


__all__ = [
    "sanitize_filename",
    "get_export_dir",
    "get_export_path",
    "generate_navigate_code",
    "generate_click_code",
    "generate_fill_code",
    "generate_assert_code",
    "generate_step_code",
    "generate_test_file_content",
    "export_from_ir",
    "export_all_specs",
]