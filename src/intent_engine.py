"""
TestForge Intent Engine - 意图推断引擎
=====================================

用 AI 理解自然语言测试步骤

核心创新:
1. 中文理解 - 直接写中文步骤
2. 意图推断 - 理解用户想做什么
3. 参数提取 - 自动识别目标、值、条件
4. 动作映射 - 转换为具体工具调用
"""

import re
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache


class IntentType(Enum):
    """意图类型"""
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    WAIT = "wait"
    SCROLL = "scroll"
    ASSERT_VISIBLE = "assert_visible"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"
    UNKNOWN = "unknown"


@dataclass
class Intent:
    """推断的意图"""
    type: IntentType
    confidence: float  # 0-1
    description: str
    target: Optional[str] = None  # 目标元素
    value: Optional[str] = None  # 输入值
    options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "confidence": self.confidence,
            "description": self.description,
            "target": self.target,
            "value": self.value,
            "options": self.options,
        }


class IntentPattern:
    """意图模式"""

    # 导航模式
    NAVIGATE_PATTERNS = [
        r"打开\s*(.+)",
        r"访问\s*(.+)",
        r"导航到\s*(.+)",
        r"去\s*(.+)",
        r"进入\s*(.+)",
        r"goto\s+(.+)",
        r"navigate\s+to\s+(.+)",
        r"visit\s+(.+)",
        r"go\s+to\s+(.+)",
    ]

    # 点击模式
    CLICK_PATTERNS = [
        r"点击\s*(.+)",
        r"按下\s*(.+)",
        r"选择\s*(?!.*\b下拉\b|\b选项\b)(.+)",  # 选择但不匹配下拉
        r"click\s+(on\s+)?(.+)",
        r"press\s+(.+)",
        r"tap\s+(.+)",
    ]

    # 填写模式
    FILL_PATTERNS = [
        r"输入\s*(.+?)\s+为\s*(.+)",
        r"填写\s*(.+?)\s+为\s*(.+)",
        r"在\s*(.+?)\s+输入\s*(.+)",
        r"把\s*(.+?)\s+填成\s*(.+)",
        r"fill\s+(.+?)\s+(?:with|as)\s+(.+)",
        r"type\s+(.+?)\s+(?:into|in)\s+(.+)",
        r"enter\s+(.+?)\s+(?:into|in)\s+(.+)",
    ]

    # 等待模式
    WAIT_PATTERNS = [
        r"等待\s*(\d+)\s*秒",
        r"等\s*(\d+)\s*秒",
        r"wait\s+(\d+)\s*(?:second|s)?",
        r"pause\s+for\s+(\d+)",
    ]

    # 断言模式
    ASSERT_VISIBLE_PATTERNS = [
        r"(?:验证|确认|检查)\s*(.+?)\s*(?:存在|可见|显示)",
        r"(?:verify|assert|check)\s+(.+?)\s*(?:is\s+)?visible",
        r"确保\s*(.+)",
        r"expect\s+(.+)",
    ]

    ASSERT_TEXT_PATTERNS = [
        r"(?:验证|确认)\s*(?:页面|文本)\s*(?:包含|有)\s*(.+)",
        r"verify\s+(?:page|text)\s+contains\s+(.+)",
        r"assert\s+(?:page|text)\s+(?:has|contains)\s+(.+)",
        r"expect\s+.*\s+(?:to\s+)?(?:show|contain|have)\s+(.+)",
    ]

    # 下拉选择
    SELECT_PATTERNS = [
        r"选择\s*(.+?)\s*(?:下拉|选项|select)",
        r"select\s+(.+?)\s+(?:from|in)\s+(?:the\s+)?(.+)",
        r"choose\s+(.+?)\s+from\s+(.+)",
    ]


class IntentEngine:
    """
    意图推断引擎

    将自然语言步骤转换为结构化意图
    """

    def __init__(self):
        self._patterns = IntentPattern()
        self._cache: Dict[str, Intent] = {}

    def parse(self, step_text: str) -> Intent:
        """
        解析步骤文本为意图

        Args:
            step_text: 步骤文本，如 "点击登录按钮"

        Returns:
            Intent
        """
        text = step_text.strip()
        if not text:
            return Intent(IntentType.UNKNOWN, 0.0, "Empty step")

        # 检查缓存
        if text in self._cache:
            return self._cache[text]

        intent = self._infer_intent(text)

        # 缓存结果
        self._cache[text] = intent

        return intent

    def _infer_intent(self, text: str) -> Intent:
        """推断意图"""
        # 按优先级尝试匹配

        # 1. 导航
        intent = self._match_pattern(
            text,
            self._patterns.NAVIGATE_PATTERNS,
            IntentType.NAVIGATE,
            "导航到页面",
        )
        if intent.confidence > 0.7:
            return intent

        # 2. 填写
        intent = self._match_fill(text)
        if intent.confidence > 0.7:
            return intent

        # 3. 点击
        intent = self._match_pattern(
            text,
            self._patterns.CLICK_PATTERNS,
            IntentType.CLICK,
            "点击元素",
        )
        if intent.confidence > 0.7:
            return intent

        # 4. 等待
        intent = self._match_wait(text)
        if intent.confidence > 0.7:
            return intent

        # 5. 断言可见
        intent = self._match_pattern(
            text,
            self._patterns.ASSERT_VISIBLE_PATTERNS,
            IntentType.ASSERT_VISIBLE,
            "验证元素可见",
        )
        if intent.confidence > 0.7:
            return intent

        # 6. 断言文本
        intent = self._match_pattern(
            text,
            self._patterns.ASSERT_TEXT_PATTERNS,
            IntentType.ASSERT_TEXT,
            "验证文本存在",
        )
        if intent.confidence > 0.7:
            return intent

        # 7. 下拉选择
        intent = self._match_pattern(
            text,
            self._patterns.SELECT_PATTERNS,
            IntentType.SELECT,
            "选择选项",
        )
        if intent.confidence > 0.7:
            return intent

        # 无法识别
        return Intent(
            IntentType.UNKNOWN,
            0.0,
            f"无法识别的步骤: {text}",
        )

    def _match_pattern(
        self,
        text: str,
        patterns: List[str],
        intent_type: IntentType,
        description: str,
    ) -> Intent:
        """匹配模式"""
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if groups:
                    target = groups[0].strip() if groups[0] else None
                    return Intent(
                        intent_type,
                        confidence=0.9,
                        description=description,
                        target=target,
                    )
                else:
                    return Intent(
                        intent_type,
                        confidence=0.8,
                        description=description,
                    )

        return Intent(intent_type, 0.0, description)

    def _match_fill(self, text: str) -> Intent:
        """匹配填写意图"""
        patterns = self._patterns.FILL_PATTERNS

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    target = groups[0].strip()
                    value = groups[1].strip()
                    return Intent(
                        IntentType.FILL,
                        confidence=0.95,
                        description=f"填写 {target} 为 {value}",
                        target=target,
                        value=value,
                    )

        return Intent(IntentType.FILL, 0.0, "填写表单")

    def _match_wait(self, text: str) -> Intent:
        """匹配等待意图"""
        patterns = self._patterns.WAIT_PATTERNS

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if groups and groups[0]:
                    seconds = float(groups[0].strip())
                    return Intent(
                        IntentType.WAIT,
                        confidence=0.95,
                        description=f"等待 {seconds} 秒",
                        value=str(seconds),
                        options={"seconds": seconds},
                    )

        return Intent(IntentType.WAIT, 0.0, "等待")

    def parse_steps(self, steps: List[str]) -> List[Intent]:
        """
        批量解析步骤

        Args:
            steps: 步骤文本列表

        Returns:
            意图列表
        """
        return [self.parse(step) for step in steps]

    def execute_intent(
        self,
        intent: Intent,
        page,
        base_url: str,
    ) -> Dict[str, Any]:
        """
        执行意图

        Args:
            intent: 意图
            page: Playwright Page
            base_url: 基础 URL

        Returns:
            执行结果
        """
        from .tools import (
            navigate, click, fill, wait, scroll,
            assert_element_visible, assert_text_present,
        )

        try:
            if intent.type == IntentType.NAVIGATE:
                return navigate(page, base_url, intent.target or "")

            elif intent.type == IntentType.CLICK:
                return click(page, description=intent.target or "")

            elif intent.type == IntentType.FILL:
                return fill(
                    page,
                    description=intent.target or "",
                    text=intent.value or "",
                )

            elif intent.type == IntentType.WAIT:
                seconds = float(intent.value or 1)
                return wait(page, seconds)

            elif intent.type == IntentType.SCROLL:
                return scroll(page, "down", 300)

            elif intent.type == IntentType.ASSERT_VISIBLE:
                return assert_element_visible(page, description=intent.target or "")

            elif intent.type == IntentType.ASSERT_TEXT:
                return assert_text_present(page, intent.target or "")

            else:
                return {
                    "ok": False,
                    "error": {"code": "UNKNOWN_INTENT", "message": f"无法执行: {intent.description}"},
                }

        except Exception as e:
            return {
                "ok": False,
                "error": {"code": "EXECUTION_ERROR", "message": str(e)},
            }


# 便捷函数
def create_intent_engine() -> IntentEngine:
    """创建意图引擎"""
    return IntentEngine()


def interpret_steps(steps: List[str]) -> List[Intent]:
    """解释步骤为意图列表"""
    engine = create_intent_engine()
    return engine.parse_steps(steps)