"""
TestForge - AI驱动的Web测试自动化框架
====================================

你的智能测试伙伴

核心创新:
- SmartWait - DOM变化感知的智能等待
- Intent Engine - 中文意图推断
- Adaptive Locator - 学习型定位器
- MultiModal Assert - 多模态断言
- Test Evolution - 从失败中学习
"""

__version__ = "0.3.0"

from .src.smart_wait import SmartWait, create_smart_wait, WaitConfig, WaitStrategy
from .src.intent_engine import IntentEngine, Intent, IntentType, create_intent_engine
from .src.adaptive_locator import AdaptiveLocator, get_adaptive_locator, LocatorRegistry
from .src.multimodal_assert import MultiModalAssert, AssertResult, AssertThat, assert_that
from .src.test_evolution import TestEvolution, AutoFixer, get_evolution

__all__ = [
    # SmartWait
    "SmartWait",
    "create_smart_wait",
    "WaitConfig",
    "WaitStrategy",
    # Intent Engine
    "IntentEngine",
    "Intent",
    "IntentType",
    "create_intent_engine",
    # Adaptive Locator
    "AdaptiveLocator",
    "get_adaptive_locator",
    "LocatorRegistry",
    # MultiModal Assert
    "MultiModalAssert",
    "AssertResult",
    "AssertThat",
    "assert_that",
    # Test Evolution
    "TestEvolution",
    "AutoFixer",
    "get_evolution",
]
