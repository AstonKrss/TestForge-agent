"""
TestForge IR - 中间表示层
=========================

核心功能:
- 元素指纹提取
- 9层定位器生成
- 定位器验证
- IR 记录

设计理念:
- 稳定性优于精确性
- 语义化定位优于硬编码选择器
- 可观测性优先
"""

import json
import time
from enum import IntEnum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


class LocatorKind(IntEnum):
    """
    9层定位器优先级

    数值越小优先级越高
    """
    TEST_ID = 1        # data-test 属性，最稳定
    ROLE = 2           # 语义化角色
    LABEL = 3          # 表单标签
    PLACEHOLDER = 4    # 输入占位符
    CSS_ID = 5         # CSS #ID
    CSS_ATTR = 6       # 属性选择器
    CSS_SELECTOR = 7   # 组合选择器
    TEXT_EXACT = 8     # 精确文本
    TEXT_FUZZY = 9     # 模糊文本


@dataclass
class ElementFingerprint:
    """
    元素指纹

    从 DOM 元素提取的稳定特征，用于定位器生成
    """
    # 基础属性
    tag_name: Optional[str] = None
    id: Optional[str] = None
    class_name: Optional[str] = None
    name_attr: Optional[str] = None
    type_attr: Optional[str] = None

    # 无障碍属性
    role: Optional[str] = None
    accessible_name: Optional[str] = None
    aria_label: Optional[str] = None
    aria_role: Optional[str] = None

    # 内容属性
    placeholder: Optional[str] = None
    text_content: Optional[str] = None
    text_snippet: Optional[str] = None

    # 测试属性
    test_id: Optional[str] = None
    data_test: Optional[str] = None

    # 位置信息
    index: int = 0
    depth: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tagName": self.tag_name,
            "id": self.id,
            "className": self.class_name,
            "nameAttr": self.name_attr,
            "typeAttr": self.type_attr,
            "role": self.role,
            "accessibleName": self.accessible_name,
            "ariaLabel": self.aria_label,
            "ariaRole": self.aria_role,
            "placeholder": self.placeholder,
            "textContent": self.text_content,
            "textSnippet": self.text_snippet,
            "testId": self.test_id,
            "dataTest": self.data_test,
            "index": self.index,
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ElementFingerprint":
        """从字典创建"""
        return cls(
            tag_name=data.get("tagName"),
            id=data.get("id"),
            class_name=data.get("className"),
            name_attr=data.get("nameAttr"),
            type_attr=data.get("typeAttr"),
            role=data.get("role"),
            accessible_name=data.get("accessibleName"),
            aria_label=data.get("ariaLabel"),
            aria_role=data.get("ariaRole"),
            placeholder=data.get("placeholder"),
            text_content=data.get("textContent"),
            text_snippet=data.get("textSnippet"),
            test_id=data.get("testId"),
            data_test=data.get("dataTest"),
            index=data.get("index", 0),
            depth=data.get("depth", 0),
        )


@dataclass
class LocatorCandidate:
    """
    定位器候选

    表示一个可能的元素定位方式
    """
    kind: LocatorKind
    value: str
    priority_score: float = 0.0
    # Playwright API 调用代码，如 page.getByRole("button", name="Login")
    code: Optional[str] = None
    # 验证结果 {unique, visible, enabled, editable, fingerprintMatch, error}
    validation: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        return f"{self.kind.name}: {self.value}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.name,
            "value": self.value,
            "score": self.priority_score,
            "code": self.code,
            "validation": self.validation,
        }


@dataclass
class LocatorChain:
    """
    定位器链

    一组候选定位器，按优先级排序
    """
    candidates: List[LocatorCandidate] = field(default_factory=list)
    best_candidate: Optional[LocatorCandidate] = None

    def add(self, candidate: LocatorCandidate):
        """添加候选"""
        self.candidates.append(candidate)
        self.candidates.sort(key=lambda x: (x.kind.value, -x.priority_score))

    def get_best(self, max_count: int = 3) -> List[LocatorCandidate]:
        """获取最佳候选"""
        return self.candidates[:max_count]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "candidates": [
                {"kind": c.kind.name, "value": c.value, "score": c.priority_score}
                for c in self.candidates
            ],
            "best": {
                "kind": self.best_candidate.kind.name if self.best_candidate else None,
                "value": self.best_candidate.value if self.best_candidate else None,
            } if self.best_candidate else None,
        }


@dataclass
class IRAction:
    """
    IR 动作记录

    记录一次工具调用及其结果
    """
    tool_name: str
    tool_input: Dict[str, Any]
    step_index: int
    timestamp: str = ""

    # 元素信息
    locator_used: Optional[LocatorCandidate] = None
    fingerprint: Optional[ElementFingerprint] = None

    # 结果
    ok: bool = True
    error: Optional[str] = None

    # 元数据
    duration_ms: int = 0
    screenshot_path: Optional[str] = None
    snapshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool": self.tool_name,
            "input": self.tool_input,
            "stepIndex": self.step_index,
            "timestamp": self.timestamp,
            "locator": {
                "kind": self.locator_used.kind.name if self.locator_used else None,
                "value": self.locator_used.value if self.locator_used else None,
            } if self.locator_used else None,
            "fingerprint": self.fingerprint.to_dict() if self.fingerprint else None,
            "ok": self.ok,
            "error": self.error,
            "durationMs": self.duration_ms,
            "screenshotPath": self.screenshot_path,
            "snapshotPath": self.snapshot_path,
        }


def calculate_priority_score(fp: ElementFingerprint, kind: LocatorKind) -> float:
    """
    计算定位器优先级分数

    基于元素特征和定位器类型
    """
    score = 0.0

    # TEST_ID 优先
    if kind == LocatorKind.TEST_ID and fp.test_id:
        score += 100
    elif kind == LocatorKind.CSS_ID and fp.id:
        score += 80

    # 语义化属性加分
    if fp.accessible_name:
        score += 30
    if fp.aria_label:
        score += 25
    if fp.placeholder:
        score += 20

    # 位置惩罚
    score -= fp.depth * 2
    score -= fp.index * 1

    return max(0, score)


def describe_locator_kind(kind: LocatorKind) -> str:
    """获取定位器类型描述"""
    descriptions = {
        LocatorKind.TEST_ID: "Test ID (data-test attribute)",
        LocatorKind.ROLE: "Semantic role (getByRole)",
        LocatorKind.LABEL: "Form label (getByLabel)",
        LocatorKind.PLACEHOLDER: "Placeholder text",
        LocatorKind.CSS_ID: "CSS ID selector (#id)",
        LocatorKind.CSS_ATTR: "CSS attribute selector",
        LocatorKind.CSS_SELECTOR: "Composite CSS selector",
        LocatorKind.TEXT_EXACT: "Exact text match",
        LocatorKind.TEXT_FUZZY: "Fuzzy text match",
    }
    return descriptions.get(kind, str(kind))


# ==================== 填充值类型 ====================

@dataclass
class FillValue:
    """填充值表示 - 支持模板变量和字面值"""
    kind: str  # "template_var", "literal", "redacted"
    name: Optional[str] = None
    value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        if self.kind == "template_var":
            return {"kind": "template_var", "name": self.name}
        elif self.kind == "literal":
            return {"kind": "literal", "value": self.value}
        return {"kind": "redacted"}

    @classmethod
    def literal(cls, value: str) -> "FillValue":
        return cls(kind="literal", value=value)

    @classmethod
    def template_var(cls, name: str) -> "FillValue":
        return cls(kind="template_var", name=name)

    @classmethod
    def redacted(cls) -> "FillValue":
        return cls(kind="redacted")


# ==================== 操作结果 ====================

@dataclass
class ActionOutcome:
    """操作结果"""
    ok: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errorCode": self.error_code,
            "errorMessage": self.error_message,
        }


# ==================== 操作记录 ====================

@dataclass
class ActionRecord:
    """
    单条操作记录

    包含执行的操作、输入、结果和元素信息
    """
    run_id: str
    spec_path: str
    step_index: Optional[int]
    step_text: Optional[str]
    tool_name: str
    tool_input: Dict[str, Any]
    outcome: ActionOutcome
    page_url: Optional[str] = None
    element: Optional["ElementRecord"] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runId": self.run_id,
            "specPath": self.spec_path,
            "stepIndex": self.step_index,
            "stepText": self.step_text,
            "toolName": self.tool_name,
            "toolInput": self.tool_input,
            "outcome": self.outcome.to_dict(),
            "pageUrl": self.page_url,
            "element": self.element.to_dict() if self.element else None,
            "timestamp": self.timestamp,
        }


@dataclass
class ElementRecord:
    """元素记录"""
    fingerprint: ElementFingerprint
    locator_candidates: List[LocatorCandidate] = field(default_factory=list)
    chosen_locator: Optional[LocatorCandidate] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint.to_dict(),
            "locatorCandidates": [c.to_dict() for c in self.locator_candidates],
            "chosenLocator": self.chosen_locator.to_dict() if self.chosen_locator else None,
        }


# ==================== IR 录制器 ====================

class IRRecorder:
    """
    IR 录制器

    录制所有操作并生成可执行的测试代码

    支持:
    - 内存中记录
    - JSONL 文件流式写入
    - 定位器验证
    """

    def __init__(
        self,
        cwd: str = ".",
        run_id: str = "default",
        spec_path: str = "",
        enabled: bool = True,
        write_to_file: bool = True,
    ):
        self.cwd = cwd
        self.run_id = run_id
        self.spec_path = spec_path
        self.enabled = enabled
        self.write_to_file = write_to_file
        self.records: List[ActionRecord] = []

        # JSONL writer
        self._writer = None
        if write_to_file:
            from .writer import IRWriter
            self._writer = IRWriter(cwd, run_id)

    def is_enabled(self) -> bool:
        return self.enabled

    def get_ir_path(self) -> Optional[str]:
        """获取 IR 文件路径"""
        if self._writer:
            return str(self._writer.path)
        return None

    async def prepare_for_action(
        self, page, tool_name: str, locator, action_type: Optional[str] = None
    ) -> Optional[Dict]:
        """在执行操作前准备，提取元素信息并验证定位器"""
        if not self.enabled:
            return None

        try:
            element = await locator.element_handle(timeout=2000)
            if element:
                # 提取指纹
                from .fingerprint import extract_fingerprint
                fp_dict = await extract_fingerprint(element)
                if fp_dict:
                    fp = ElementFingerprint(
                        tag_name=fp_dict.get("tagName"),
                        id=fp_dict.get("id"),
                        accessible_name=fp_dict.get("accessibleName") or fp_dict.get("ariaLabel"),
                        role=fp_dict.get("role"),
                        placeholder=fp_dict.get("placeholder"),
                        test_id=fp_dict.get("testId"),
                        data_test=fp_dict.get("dataTest"),
                        text_content=fp_dict.get("textContent"),
                        text_snippet=fp_dict.get("textSnippet"),
                    )

                    # 生成定位器链
                    from .locator_generator import generate_locator_chain
                    chain = generate_locator_chain(fp)

                    # 确定操作类型
                    if action_type is None:
                        action_type = _infer_action_type(tool_name)

                    # 验证候选定位器
                    from .validator import validate_candidates
                    validated = await validate_candidates(page, chain.candidates, action_type, fp)

                    # 过滤有效候选
                    from .validator import filter_valid_candidates
                    valid = filter_valid_candidates(validated, action_type)

                    return {
                        "fingerprint": fp,
                        "candidates": validated,  # 所有候选带验证结果
                        "valid_candidates": valid,  # 通过验证的候选
                    }
        except Exception:
            pass

        return None

    async def record_action(
        self,
        context: Dict,
        outcome: Dict,
        pre_result: Optional[Dict] = None,
    ) -> None:
        """录制一条操作"""
        if not self.enabled:
            return

        tool_name = context.get("toolName", "")
        tool_input = context.get("toolInput", {})
        step_index = context.get("stepIndex")
        step_text = context.get("stepText")
        page_url = context.get("pageUrl")

        # 构建元素记录
        element_record = None
        if pre_result and tool_name in ("click", "fill", "select_option", "assertElementVisible"):
            fp = pre_result.get("fingerprint")
            candidates = pre_result.get("valid_candidates", pre_result.get("candidates", []))

            if fp:
                # 选择最佳定位器
                chosen = candidates[0] if candidates else None

                # 更新原始候选的验证结果
                original_candidates = pre_result.get("candidates", [])
                for orig in original_candidates:
                    for val in candidates:
                        if orig.kind == val.kind and orig.value == val.value:
                            orig.validation = val.validation
                            break

                element_record = ElementRecord(
                    fingerprint=fp,
                    locator_candidates=original_candidates,
                    chosen_locator=chosen,
                )

        # 处理填充值
        if tool_name == "fill" and "fillValue" not in tool_input:
            text = tool_input.get("text", "")
            tool_input["fillValue"] = FillValue.literal(text).to_dict()

        # 构建结果
        outcome_obj = ActionOutcome(
            ok=outcome.get("ok", False),
            error_code=outcome.get("error", {}).get("code") if isinstance(outcome.get("error"), dict) else None,
            error_message=outcome.get("error", {}).get("message") if isinstance(outcome.get("error"), dict) else str(outcome.get("error", "")),
        )

        # 创建记录
        record = ActionRecord(
            run_id=self.run_id,
            spec_path=self.spec_path,
            step_index=step_index,
            step_text=step_text,
            tool_name=tool_name,
            tool_input=tool_input,
            outcome=outcome_obj,
            page_url=page_url,
            element=element_record,
        )

        self.records.append(record)

        # 写入 JSONL 文件
        if self._writer:
            from .writer import redact_tool_input
            self._writer.append_action(
                run_id=self.run_id,
                spec_path=self.spec_path,
                step_index=step_index,
                step_text=step_text,
                tool_name=tool_name,
                tool_input=redact_tool_input(tool_name, tool_input),
                outcome=outcome_obj.to_dict(),
                page_url=page_url,
                element=element_record.to_dict() if element_record else None,
            )

    def get_records(self) -> List[ActionRecord]:
        """获取所有记录"""
        return self.records

    def export(self, path: Optional[str] = None) -> str:
        """导出为 JSON"""
        data = {
            "runId": self.run_id,
            "specPath": self.spec_path,
            "records": [r.to_dict() for r in self.records],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def export_to_file(self, path: Optional[str] = None) -> str:
        """导出到文件"""
        import os
        if path is None:
            path = os.path.join(self.cwd, ".testforge", "runs", self.run_id, "ir.json")

        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = self.export()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path


def _infer_action_type(tool_name: str) -> str:
    """从工具名推断操作类型"""
    mapping = {
        "click": "click",
        "fill": "fill",
        "select_option": "select",
        "assertElementVisible": "assert",
        "assertTextPresent": "assert",
        "navigate": "navigate",
        "wait": "navigate",
        "scroll": "navigate",
        "snapshot": "navigate",
    }
    return mapping.get(tool_name, "click")


class NullRecorder:
    """空录制器 - 不录制任何内容"""

    def is_enabled(self) -> bool:
        return False

    async def prepare_for_action(self, page, tool_name: str, locator):
        return None

    async def record_action(self, context: Dict, outcome: Dict, pre_result: Optional[Dict] = None):
        pass

    def get_records(self) -> List:
        return []


# ==================== 导出 ====================

__all__ = [
    "LocatorKind",
    "ElementFingerprint",
    "LocatorCandidate",
    "LocatorChain",
    "IRAction",
    "calculate_priority_score",
    "describe_locator_kind",
    "FillValue",
    "ActionOutcome",
    "ActionRecord",
    "ElementRecord",
    "IRRecorder",
    "NullRecorder",
]

# 子模块
from .writer import IRWriter, build_ir_path, redact_tool_input, sanitize_path_segment
from .validator import (
    validate_candidate,
    validate_candidates,
    filter_valid_candidates,
    get_best_valid_locator,
    get_validation_summary,
    fingerprints_match,
)