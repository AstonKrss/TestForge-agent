"""
TestForge Test Evolution - 测试演化引擎
=====================================

从失败中学习，自动修复失败的测试

核心创新:
1. 失败分析 - 诊断失败原因
2. 智能修复 - 自动尝试替代方案
3. 学习曲线 - 越用越聪明
4. 历史记忆 - 记住之前的修复
"""

import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from threading import Lock


class FailureReason(Enum):
    """失败原因"""
    ELEMENT_NOT_FOUND = "element_not_found"
    ELEMENT_NOT_VISIBLE = "element_not_visible"
    ELEMENT_NOT_ENABLED = "element_not_enabled"
    STALE_ELEMENT = "stale_element"
    TIMEOUT = "timeout"
    WRONG_VALUE = "wrong_value"
    ASSERTION_FAILED = "assertion_failed"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


@dataclass
class EvolutionAttempt:
    """演化尝试记录"""
    timestamp: float
    original_locator: tuple
    new_locator: Optional[tuple]
    success: bool
    failure_reason: FailureReason
    duration_ms: float


@dataclass
class FixStrategy:
    """修复策略"""
    name: str
    apply: Callable  # (failed_locator, context) -> new_locator
    priority: int = 0  # 优先级，数字越大优先级越高
    description: str = ""


class TestEvolution:
    """
    测试演化引擎

    通过分析和学习，自动化修复失败的测试
    """

    # 默认修复策略
    DEFAULT_STRATEGIES = [
        # 策略1: 尝试 id 的不同变体
        FixStrategy(
            name="id_variants",
            priority=100,
            description="尝试ID的不同变体",
            apply=lambda loc, ctx: (
                ("css_id", f"#{loc[1].lstrip('#')}") if loc[0] in ("css", "css_id") else None
            ) or (
                ("css_id", f"#{loc[1]}") if loc[0] in ("text", "role") else None
            ),
        ),

        # 策略2: 尝试 data-test 属性
        FixStrategy(
            name="data_test_id",
            priority=90,
            description="尝试 data-test 属性",
            apply=lambda loc, ctx: (
                ("data_test", f"[data-test='{loc[1]}']") if loc[0] in ("text", "role") else None
            ),
        ),

        # 策略3: 尝试 role 的不同组合
        FixStrategy(
            name="role_combination",
            priority=80,
            description="尝试 role + name 组合",
            apply=lambda loc, ctx: (
                ("role", loc[1]) if loc[0] == "text" else None
            ),
        ),

        # 策略4: 模糊文本匹配
        FixStrategy(
            name="fuzzy_text",
            priority=70,
            description="尝试模糊文本匹配",
            apply=lambda loc, ctx: (
                ("partial_text", loc[1][:min(10, len(loc[1]))]) if loc[0] == "text" else None
            ),
        ),

        # 策略5: 父元素查找
        FixStrategy(
            name="parent_element",
            priority=60,
            description="尝试父元素",
            apply=lambda loc, ctx: (
                ("css", f"{loc[1]}") if loc[0] == "css" else None
            ),
        ),

        # 策略6: 兄弟元素查找
        FixStrategy(
            name="sibling_element",
            priority=50,
            description="尝试兄弟元素",
            apply=lambda loc, ctx: (
                ("css", f"{loc[1]}") if loc[0] == "css" else None
            ),
        ),

        # 策略7: 等待后重试
        FixStrategy(
            name="wait_and_retry",
            priority=40,
            description="等待后重试",
            apply=lambda loc, ctx: loc,  # 返回原定位器，等待后重试
        ),

        # 策略8: 滚动后查找
        FixStrategy(
            name="scroll_and_find",
            priority=30,
            description="滚动后查找",
            apply=lambda loc, ctx: (
                ("scroll", loc[1]) if loc[0] in ("text", "role") else None
            ),
        ),
    ]

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        max_history: int = 500,
    ):
        self._cache_dir = cache_dir
        self._max_history = max_history

        # 策略列表
        self._strategies: List[FixStrategy] = list(self.DEFAULT_STRATEGIES)

        # 失败历史 (按元素标识)
        self._failure_history: Dict[str, List[EvolutionAttempt]] = defaultdict(list)

        # 成功映射 (曾经成功的定位器)
        self._success_map: Dict[str, List[tuple]] = defaultdict(list)

        # 锁
        self._lock = Lock()

        # 加载缓存
        self._load_cache()

    def register_strategy(self, strategy: FixStrategy):
        """注册修复策略"""
        self._strategies.append(strategy)
        self._strategies.sort(key=lambda s: s.priority, reverse=True)

    def analyze_failure(
        self,
        error: Exception,
        locator: Optional[tuple] = None,
    ) -> FailureReason:
        """
        分析失败原因

        Args:
            error: 异常
            locator: 使用的定位器

        Returns:
            FailureReason
        """
        msg = str(error).lower()

        if "not found" in msg or "not found in" in msg:
            return FailureReason.ELEMENT_NOT_FOUND
        elif "not visible" in msg or "is hidden" in msg:
            return FailureReason.ELEMENT_NOT_VISIBLE
        elif "not enabled" in msg or "disabled" in msg:
            return FailureReason.ELEMENT_NOT_ENABLED
        elif "stale element" in msg or "detached" in msg:
            return FailureReason.STALE_ELEMENT
        elif "timeout" in msg or "timed out" in msg:
            return FailureReason.TIMEOUT
        elif "assertion" in msg or "expected" in msg:
            return FailureReason.ASSERTION_FAILED
        elif "network" in msg or "net::err" in msg:
            return FailureReason.NETWORK_ERROR

        return FailureReason.UNKNOWN

    def evolve(
        self,
        element_id: str,
        failed_locator: tuple,
        failure_reason: FailureReason,
        context: Optional[Dict] = None,
    ) -> List[tuple]:
        """
        演化定位器

        从失败中学习，生成替代方案

        Args:
            element_id: 元素标识
            failed_locator: 失败的定位器 (type, value)
            failure_reason: 失败原因
            context: 上下文信息

        Returns:
            替代定位器列表
        """
        with self._lock:
            alternatives = []

            # 记录失败
            attempt = EvolutionAttempt(
                timestamp=time.time(),
                original_locator=failed_locator,
                new_locator=None,
                success=False,
                failure_reason=failure_reason,
                duration_ms=0,
            )
            self._failure_history[element_id].append(attempt)

            # 限制历史长度
            if len(self._failure_history[element_id]) > self._max_history:
                self._failure_history[element_id] = self._failure_history[element_id][-self._max_history:]

            # 检查是否曾经成功过
            previous_successes = self._success_map.get(element_id, [])
            if previous_successes:
                # 返回之前成功过的定位器
                return previous_successes

            # 根据失败原因应用策略
            for strategy in self._strategies:
                try:
                    new_locator = strategy.apply(failed_locator, context or {})
                    if new_locator and new_locator != failed_locator:
                        alternatives.append(new_locator)
                except Exception:
                    pass

            return alternatives

    def record_success(
        self,
        element_id: str,
        locator: tuple,
        duration_ms: float = 0,
    ):
        """
        记录成功

        Args:
            element_id: 元素标识
            locator: 成功的定位器
            duration_ms: 耗时
        """
        with self._lock:
            # 添加到成功映射
            if locator not in self._success_map[element_id]:
                self._success_map[element_id].insert(0, locator)

            # 限制数量
            if len(self._success_map[element_id]) > 10:
                self._success_map[element_id] = self._success_map[element_id][:10]

            # 标记之前失败的尝试为成功
            if element_id in self._failure_history:
                for attempt in reversed(self._failure_history[element_id]):
                    if not attempt.success and attempt.original_locator == locator:
                        attempt.success = True
                        attempt.new_locator = locator
                        attempt.duration_ms = duration_ms

    def get_recommended_locator(self, element_id: str) -> Optional[tuple]:
        """
        获取推荐定位器

        根据历史成功率推荐最佳定位器
        """
        with self._lock:
            # 优先返回曾经成功的
            successes = self._success_map.get(element_id, [])
            if successes:
                return successes[0]

            # 分析失败历史，找成功率最高的
            history = self._failure_history.get(element_id, [])
            if not history:
                return None

            # 统计每个定位器的成功率
            locator_stats = defaultdict(lambda: {"success": 0, "total": 0})
            for attempt in history:
                key = attempt.original_locator
                locator_stats[key]["total"] += 1
                if attempt.success:
                    locator_stats[key]["success"] += 1

            # 找成功率最高的
            best = None
            best_rate = 0
            for locator, stats in locator_stats.items():
                rate = stats["success"] / stats["total"] if stats["total"] > 0 else 0
                if rate > best_rate and stats["success"] > 0:
                    best_rate = rate
                    best = locator

            return best

    def get_failure_patterns(self, element_id: str) -> Dict[str, int]:
        """
        获取失败模式统计

        Returns:
            {reason: count}
        """
        with self._lock:
            patterns = defaultdict(int)
            history = self._failure_history.get(element_id, [])

            for attempt in history:
                patterns[attempt.failure_reason.value] += 1

            return dict(patterns)

    def reset(self, element_id: Optional[str] = None):
        """重置历史"""
        with self._lock:
            if element_id:
                if element_id in self._failure_history:
                    del self._failure_history[element_id]
                if element_id in self._success_map:
                    del self._success_map[element_id]
            else:
                self._failure_history.clear()
                self._success_map.clear()

    def _load_cache(self):
        """加载缓存"""
        if not self._cache_dir:
            return

        cache_file = Path(self._cache_dir) / ".testforge" / "evolution_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # 加载成功映射
                    for element_id, locators in data.get("success_map", {}).items():
                        self._success_map[element_id] = [
                            tuple(l) for l in locators
                        ]
            except Exception:
                pass

    def _save_cache(self):
        """保存缓存"""
        if not self._cache_dir:
            return

        cache_file = Path(self._cache_dir) / ".testforge" / "evolution_cache.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = {
                "success_map": {
                    element_id: [list(loc) for loc in locators]
                    for element_id, locators in self._success_map.items()
                }
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def __del__(self):
        """析构时保存缓存"""
        self._save_cache()


class AutoFixer:
    """
    自动修复器

    封装测试演化，提供自动修复功能
    """

    def __init__(
        self,
        evolution: Optional[TestEvolution] = None,
        max_retries: int = 3,
    ):
        self._evolution = evolution or TestEvolution()
        self._max_retries = max_retries

    async def execute_with_auto_fix(
        self,
        page,
        element_id: str,
        action: Callable,
        locator: tuple,
    ) -> Dict[str, Any]:
        """
        执行带自动修复的操作

        Args:
            page: Playwright Page
            element_id: 元素标识
            action: 要执行的动作 (locator) -> result
            locator: 初始定位器

        Returns:
            执行结果
        """
        current_locator = locator
        attempts = 0

        while attempts < self._max_retries:
            try:
                # 执行动作
                result = await action(page, current_locator)

                if result.get("ok"):
                    # 成功，记录
                    self._evolution.record_success(element_id, current_locator)
                    return result

                # 失败，分析并演化
                error = Exception(result.get("error", {}).get("message", "Unknown error"))
                reason = self._evolution.analyze_failure(error, current_locator)

                # 获取替代定位器
                alternatives = self._evolution.evolve(
                    element_id, current_locator, reason
                )

                if not alternatives:
                    # 没有替代方案
                    return result

                # 使用第一个替代方案
                current_locator = alternatives[0]
                attempts += 1

            except Exception as e:
                # 异常，记录并尝试修复
                reason = self._evolution.analyze_failure(e, current_locator)
                alternatives = self._evolution.evolve(
                    element_id, current_locator, reason
                )

                if not alternatives:
                    return {
                        "ok": False,
                        "error": {"code": "FIX_FAILED", "message": str(e)},
                    }

                current_locator = alternatives[0]
                attempts += 1

        # 达到最大重试次数
        return {
            "ok": False,
            "error": {
                "code": "MAX_RETRIES_EXCEEDED",
                "message": f"Failed after {self._max_retries} attempts",
                "last_locator": current_locator,
            },
        }


# 全局实例
_evolution: Optional[TestEvolution] = None


def get_evolution(cache_dir: Optional[str] = None) -> TestEvolution:
    """获取全局测试演化引擎"""
    global _evolution
    if _evolution is None:
        _evolution = TestEvolution(cache_dir)
    return _evolution