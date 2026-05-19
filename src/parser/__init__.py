"""
TestForge Parser - Markdown 规范解析
==================================

支持:
- 标准 Markdown 格式
- include: 语法复用步骤
- {{VARIABLE}} 模板变量
"""

import re
from typing import Dict, Any, List, Optional


class SpecStep:
    """规范步骤"""
    def __init__(
        self,
        index: int,
        text: str,
        kind: str = "action",  # action | assertion
        expected: Optional[str] = None,
    ):
        self.index = index
        self.text = text
        self.kind = kind
        self.expected = expected


class Spec:
    """测试规范"""
    def __init__(self, preconditions: List[str], steps: List[SpecStep]):
        self.preconditions = preconditions
        self.steps = steps


class ParseResult:
    """解析结果"""
    def __init__(self, ok: bool, spec: Optional[Spec] = None, error: Optional[str] = None):
        self.ok = ok
        self.spec = spec
        self.error = error


def classify_step(text: str) -> str:
    """分类步骤类型"""
    t = text.strip().lower()
    if t.startswith("verify") or t.startswith("assert"):
        return "assertion"
    if t.startswith("验证") or t.startswith("断言"):
        return "assertion"
    return "action"


def _extract_expected_from_nested(text: str) -> Optional[str]:
    """
    从嵌套列表中提取 Expected 值

    支持格式:
    1. 提交登录表单
       - Expected: 成功消息出现
       - Expected: 跳转首页
    """
    # 查找嵌套的 - Expected: 行
    pattern = r"^\s*[-•]\s*expected:\s*(.+)$"
    matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
    if matches:
        # 返回最后一个 Expected
        return matches[-1].strip()
    return None


def parse_spec(markdown: str) -> ParseResult:
    """
    解析 Markdown 测试规范

    格式:
    ## Preconditions
    - 条件1
    - 条件2

    ## Steps
    1. 步骤1
    2. 步骤2 (带 Expected: 结果)
    """
    md = markdown or ""

    # 解析前置条件
    pre_match = re.search(r"##\s*Preconditions\s*\n((?:\s*-\s*.+\n)+)", md, re.IGNORECASE | re.MULTILINE)
    if not pre_match:
        return ParseResult(ok=False, error="Missing ## Preconditions section")

    preconditions = []
    for line in pre_match.group(1).split("\n"):
        m = re.match(r"^\s*-\s*(.+)$", line)
        if m:
            preconditions.append(m.group(1).strip())

    if not preconditions:
        return ParseResult(ok=False, error="Empty preconditions")

    # 解析步骤
    steps_match = re.search(r"##\s*Steps\s*\n((?:\s*\d+\.\s*.+\n?)+)", md, re.IGNORECASE | re.MULTILINE)
    if not steps_match:
        return ParseResult(ok=False, error="Missing ## Steps section")

    steps = []
    for line in steps_match.group(1).split("\n"):
        if not line.strip():
            continue

        m = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if m:
            text = m.group(2).strip()
            idx = int(m.group(1))

            # 提取 Expected - 支持行内和嵌套格式
            expected = None

            # 1. 先尝试行内格式: 步骤文本 - Expected: ...
            exp_match = re.search(r"(.*?)\n?\s*[-•]?\s*expected:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
            if exp_match:
                text = exp_match.group(1).strip()
                expected = exp_match.group(2).strip()
            else:
                # 2. 尝试从后续行中提取嵌套的 Expected
                # 获取多行内容（包含后续缩进行）
                multiline_text = line
                # 查找后续缩进行
                rest_match = re.search(r"^\s*\d+\.\s*(.+)(?:\n((?:\s+.+\n)*))", line + "\n", re.MULTILINE)
                if rest_match and rest_match.group(2):
                    nested_text = rest_match.group(2)
                    expected = _extract_expected_from_nested(nested_text)

            steps.append(SpecStep(
                index=idx,
                text=text,
                kind=classify_step(text),
                expected=expected,
            ))

    if not steps:
        return ParseResult(ok=False, error="Empty steps")

    return ParseResult(ok=True, spec=Spec(preconditions=preconditions, steps=steps))


def spec_to_dict(spec: Spec) -> Dict[str, Any]:
    """规范转字典"""
    return {
        "preconditions": spec.preconditions,
        "steps": [
            {"index": s.index, "text": s.text, "kind": s.kind, "expected": s.expected}
            for s in spec.steps
        ],
    }


def parse_spec_with_includes(
    markdown: str,
    include_root: str,
) -> ParseResult:
    """
    解析 Markdown 规范，支持 include 语法

    Args:
        markdown: Markdown 文本
        include_root: include 文件根目录

    Returns:
        ParseResult with parsed Spec
    """
    # 导入 include 模块
    from .include import expand_includes, is_include_step

    md = markdown or ""

    # 1. 解析 preconditions
    pre_match = re.search(r"##\s*Preconditions\s*\n((?:\s*-\s*.+\n)+)", md, re.IGNORECASE | re.MULTILINE)
    if pre_match:
        preconditions = []
        for line in pre_match.group(1).split("\n"):
            m = re.match(r"^\s*-\s*(.+)$", line)
            if m:
                preconditions.append(m.group(1).strip())
    else:
        preconditions = []

    # 2. 解析 steps（先不展开 include）
    steps_match = re.search(r"##\s*Steps\s*\n((?:\s*\d+\.\s*.+\n?)+)", md, re.IGNORECASE | re.MULTILINE)
    if not steps_match:
        return ParseResult(ok=False, error="Missing ## Steps section")

    raw_step_texts = []
    for line in steps_match.group(1).split("\n"):
        if not line.strip():
            continue
        m = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if m:
            raw_step_texts.append(m.group(2).strip())

    if not raw_step_texts:
        return ParseResult(ok=False, error="Empty steps")

    # 3. 展开 include
    include_result = expand_includes(raw_step_texts, include_root)
    if not include_result["ok"]:
        return ParseResult(ok=False, error=include_result.get("message"))

    expanded_texts = include_result["steps"]

    # 4. 解析展开后的步骤
    steps = []
    for idx, text in enumerate(expanded_texts, 1):
        # 跳过 include 行（已在 expand_includes 中处理）
        if is_include_step(text):
            continue

        # 提取 Expected
        expected = None
        exp_match = re.search(r"(.*?)\n?\s*[-•]?\s*expected:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
        if exp_match:
            text = exp_match.group(1).strip()
            expected = exp_match.group(2).strip()

        steps.append(SpecStep(
            index=idx,
            text=text,
            kind=classify_step(text),
            expected=expected,
        ))

    if not steps:
        return ParseResult(ok=False, error="No valid steps after expansion")

    return ParseResult(ok=True, spec=Spec(preconditions=preconditions, steps=steps))


def render_spec_with_vars(spec: Spec, vars: Dict[str, str]) -> ParseResult:
    """
    渲染 Spec 中的模板变量

    Args:
        spec: Spec 对象
        vars: 变量映射

    Returns:
        新的 Spec（带渲染后的文本）或错误
    """
    from .template import render_template, validate_template_vars

    # 验证变量
    validation = validate_template_vars(spec, vars)
    if not validation["ok"]:
        return ParseResult(ok=False, error=validation["message"])

    # 渲染 preconditions
    rendered_preconditions = []
    for pre in spec.preconditions:
        result = render_template(pre, vars)
        if result["ok"]:
            rendered_preconditions.append(result["value"])
        else:
            return ParseResult(ok=False, error=result["message"])

    # 渲染 steps
    rendered_steps = []
    for step in spec.steps:
        # 渲染步骤文本
        text_result = render_template(step.text, vars)
        if not text_result["ok"]:
            return ParseResult(ok=False, error=text_result["message"])

        # 渲染 expected
        expected_result = None
        if step.expected:
            expected_result = render_template(step.expected, vars)
            if not expected_result["ok"]:
                return ParseResult(ok=False, error=expected_result["message"])
            expected_result = expected_result["value"]

        rendered_steps.append(SpecStep(
            index=step.index,
            text=text_result["value"],
            kind=step.kind,
            expected=expected_result,
        ))

    return ParseResult(
        ok=True,
        spec=Spec(preconditions=rendered_preconditions, steps=rendered_steps),
    )