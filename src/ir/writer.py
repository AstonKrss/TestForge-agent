"""
TestForge IR - JSONL Writer
===========================

流式写入 IR 记录到 JSONL 文件

参考 AutoQA-Agent src/ir/writer.ts
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


def sanitize_path_segment(name: str) -> str:
    """
    清理路径片段，防止路径遍历攻击

    参考 AutoQA-Agent sanitizeName()
    """
    # 禁止字符
    forbidden = r'[<>:"\\|?*\x00-\x1f]'
    name = re.sub(forbidden, "", name)

    # 禁止路径遍历
    name = name.replace("..", "_")

    # 长度限制
    max_len = 200
    if len(name) > max_len:
        name = name[:max_len]

    # 空字符串保护
    if not name:
        name = "unnamed"

    return name


def ensure_dir(path: Path) -> None:
    """确保目录存在，递归创建"""
    path.mkdir(parents=True, exist_ok=True)


def build_ir_path(cwd: str, run_id: str) -> Path:
    """
    构建 IR JSONL 文件路径

    Args:
        cwd: 工作目录
        run_id: 运行ID

    Returns:
        .testforge/runs/{run_id}/ir.jsonl
    """
    run_id = sanitize_path_segment(run_id)
    base = Path(cwd) / ".testforge" / "runs" / run_id
    ensure_dir(base)
    return base / "ir.jsonl"


def redact_tool_input(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    脱敏工具输入中的敏感信息

    参考 AutoQA-Agent redactToolInput()
    """
    if not tool_input:
        return {}

    # 复制避免修改原对象
    redacted = dict(tool_input)

    # 密码字段
    sensitive_fields = {"password", "pass", "pwd", "secret", "token", "api_key", "apikey"}
    for field in sensitive_fields:
        if field in redacted:
            redacted[field] = "[REDACTED]"

    # fill 工具的 text 字段
    if tool_name == "fill":
        if "text" in redacted:
            text = redacted["text"]
            # 保留长度信息用于调试
            if text and len(text) > 0:
                redacted["textLength"] = len(text)
                redacted["text"] = "[FILLED]"
            else:
                redacted["text"] = ""

        # 保留 fillValue 结构
        if "fillValue" in tool_input:
            fv = tool_input["fillValue"]
            if isinstance(fv, dict):
                if fv.get("kind") == "redacted":
                    redacted["fillValue"] = {"kind": "redacted"}
                elif fv.get("kind") == "template_var":
                    redacted["fillValue"] = {"kind": "template_var", "name": fv.get("name")}
                elif fv.get("kind") == "literal":
                    redacted["fillValue"] = {"kind": "literal", "length": len(fv.get("value", ""))}
            else:
                redacted["fillValue"] = {"kind": "redacted"}
        elif "text" in redacted:
            # 从 text 字段构建 fillValue
            redacted["fillValue"] = {"kind": "literal", "length": len(redacted.get("text", ""))}

    # 移除截图等大数据
    if "screenshot" in redacted:
        del redacted["screenshot"]

    return redacted


class IRWriter:
    """
    IR JSONL 流式写入器

    将 ActionRecord 逐行追加写入 ir.jsonl

    格式: 每行一个 JSON 对象
    {runId, specPath, stepIndex, stepText, toolName, toolInput, outcome, pageUrl, element, timestamp}
    """

    def __init__(self, cwd: str, run_id: str):
        self.cwd = cwd
        self.run_id = sanitize_path_segment(run_id)
        self._path = build_ir_path(cwd, run_id)
        self._count = 0

    @property
    def path(self) -> Path:
        """获取 IR 文件路径"""
        return self._path

    @property
    def relative_path(self) -> str:
        """获取相对路径字符串"""
        return str(self._path.relative_to(Path.cwd()))

    def append(self, record: Dict[str, Any]) -> None:
        """
        追加一条记录到文件

        Args:
            record: ActionRecord 字典
        """
        ensure_dir(self._path.parent)

        line = json.dumps(record, ensure_ascii=False)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        self._count += 1

    def append_action(
        self,
        run_id: str,
        spec_path: str,
        step_index: Optional[int],
        step_text: Optional[str],
        tool_name: str,
        tool_input: Dict[str, Any],
        outcome: Dict[str, Any],
        page_url: Optional[str] = None,
        element: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """
        便捷方法：追加动作记录

        Args:
            run_id: 运行ID
            spec_path: 规范文件路径
            step_index: 步骤索引
            step_text: 步骤原始文本
            tool_name: 工具名称
            tool_input: 工具输入（将被脱敏）
            outcome: 执行结果 {ok, errorCode?, errorMessage?}
            page_url: 当前页面URL
            element: 元素记录（指纹+定位器）
            timestamp: 时间戳
        """
        record = {
            "runId": run_id,
            "specPath": spec_path,
            "stepIndex": step_index,
            "stepText": step_text,
            "toolName": tool_name,
            "toolInput": redact_tool_input(tool_name, tool_input),
            "outcome": outcome,
            "pageUrl": page_url,
            "element": element,
            "timestamp": timestamp or datetime.now().timestamp(),
        }

        self.append(record)

    def get_count(self) -> int:
        """获取已写入的记录数"""
        return self._count

    def exists(self) -> bool:
        """检查文件是否存在"""
        return self._path.exists()

    def read_all(self):
        """
        读取所有记录

        Returns:
            List[Dict]: 所有 ActionRecord 列表
        """
        if not self.exists():
            return []

        records = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records


__all__ = [
    "IRWriter",
    "build_ir_path",
    "redact_tool_input",
    "sanitize_path_segment",
]