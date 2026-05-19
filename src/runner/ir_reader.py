"""
TestForge Runner - IR Reader
===========================

从 JSONL 文件读取 IR 记录

参考 AutoQA-Agent src/runner/ir-reader.ts
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional


def build_ir_path(cwd: str, run_id: str) -> Path:
    """构建 IR JSONL 文件路径"""
    return Path(cwd) / ".testforge" / "runs" / run_id / "ir.jsonl"


def read_ir_file(cwd: str, run_id: str) -> List[Dict[str, Any]]:
    """
    读取 IR JSONL 文件

    Args:
        cwd: 工作目录
        run_id: 运行ID

    Returns:
        ActionRecord 字典列表
    """
    path = build_ir_path(cwd, run_id)
    if not path.exists():
        return []

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def filter_by_spec_path(records: List[Dict[str, Any]], spec_path: str) -> List[Dict[str, Any]]:
    """
    按 spec 路径过滤记录

    Args:
        records: 所有记录
        spec_path: 规范文件路径（绝对或相对）

    Returns:
        匹配该 spec 的记录
    """
    from pathlib import Path

    # 标准化 spec_path
    spec_path_obj = Path(spec_path).resolve()

    filtered = []
    for record in records:
        record_path = record.get("specPath", "")
        if record_path:
            record_path_obj = Path(record_path).resolve()
            if record_path_obj == spec_path_obj or Path(record_path).name == Path(spec_path).name:
                filtered.append(record)

    return filtered


def get_spec_action_records(cwd: str, run_id: str, spec_path: str) -> List[Dict[str, Any]]:
    """
    获取指定 spec 的所有动作记录

    Args:
        cwd: 工作目录
        run_id: 运行ID
        spec_path: 规范文件路径

    Returns:
        该 spec 的 ActionRecord 列表
    """
    all_records = read_ir_file(cwd, run_id)
    return filter_by_spec_path(all_records, spec_path)


def has_valid_chosen_locator(record: Dict[str, Any]) -> bool:
    """
    检查记录是否有有效的 chosenLocator

    Args:
        record: ActionRecord 字典

    Returns:
        True 如果有有效的 chosenLocator
    """
    element = record.get("element")
    if not element:
        return False

    chosen = element.get("chosenLocator")
    if not chosen:
        return False

    # 检查 code 字段
    code = chosen.get("code")
    if not code:
        return False

    # 检查验证结果
    validation = chosen.get("validation", {})
    if not validation:
        return True  # 没有验证信息，假定有效

    return validation.get("unique", False)


def get_missing_locator_actions(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    获取缺少有效定位器的动作记录

    这些记录需要人工补充定位器

    Args:
        records: 动作记录列表

    Returns:
        缺少定位器的记录列表
    """
    element_targeting_tools = {"click", "fill", "select_option", "assertElementVisible"}
    missing = []

    for record in records:
        tool_name = record.get("toolName", "")
        if tool_name not in element_targeting_tools:
            continue

        outcome = record.get("outcome", {})
        if not outcome.get("ok"):
            continue  # 跳过失败的记录

        if not has_valid_chosen_locator(record):
            missing.append(record)

    return missing


def get_action_summary(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    获取动作摘要

    Args:
        records: 动作记录列表

    Returns:
        摘要信息列表
    """
    summary = []

    for record in records:
        tool_name = record.get("toolName", "")
        step_index = record.get("stepIndex")
        step_text = record.get("stepText", "")
        outcome = record.get("outcome", {})
        element = record.get("element")

        chosen = element.get("chosenLocator") if element else None

        summary.append({
            "stepIndex": step_index,
            "toolName": tool_name,
            "stepText": step_text,
            "ok": outcome.get("ok", False),
            "locatorKind": chosen.get("kind") if chosen else None,
            "locatorCode": chosen.get("code") if chosen else None,
        })

    return summary


__all__ = [
    "build_ir_path",
    "read_ir_file",
    "filter_by_spec_path",
    "get_spec_action_records",
    "has_valid_chosen_locator",
    "get_missing_locator_actions",
    "get_action_summary",
]