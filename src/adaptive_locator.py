"""
TestForge Adaptive Locator - 自适应定位器
========================================

记录定位成功率，自动优先使用最佳定位器

核心创新:
1. 成功率追踪 - 记录每个定位器的成功/失败
2. 智能排序 - 按成功率排序候选
3. 自动演化 - 失败后尝试替代方案
4. 学习曲线 - 越用越准确
"""

import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from threading import Lock


@dataclass
class LocatorAttempt:
    """定位器尝试记录"""
    locator_type: str      # "css", "role", "label", "text", etc.
    value: str            # 定位器值
    success: bool         # 是否成功
    duration_ms: float   # 耗时
    timestamp: float      # 时间戳


@dataclass
class LocatorStats:
    """定位器统计"""
    locator_type: str
    value: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_duration_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts

    @property
    def avg_duration_ms(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.total_duration_ms / self.attempts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.locator_type,
            "value": self.value,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "successRate": round(self.success_rate, 3),
            "avgDuration": round(self.avg_duration_ms, 1),
        }


class AdaptiveLocator:
    """
    自适应定位器

    通过学习历史成功率，智能选择最佳定位器
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        max_history: int = 1000,
    ):
        self._cache_dir = cache_dir
        self._max_history = max_history

        # 全局统计 (按类型和值)
        self._global_stats: Dict[str, LocatorStats] = {}

        # 元素特定统计 (针对特定页面元素)
        self._element_stats: Dict[str, Dict[str, LocatorStats]] = defaultdict(dict)

        # 历史记录
        self._history: List[LocatorAttempt] = []

        # 锁
        self._lock = Lock()

        # 加载缓存
        self._load_cache()

    def _get_key(self, element_id: str, locator_type: str, value: str) -> str:
        """生成唯一键"""
        return f"{element_id}:{locator_type}:{value}"

    def record_attempt(
        self,
        element_id: str,
        locator_type: str,
        value: str,
        success: bool,
        duration_ms: float = 0,
    ):
        """
        记录定位器尝试

        Args:
            element_id: 元素标识 (如 "登录按钮", "用户名输入框")
            locator_type: 定位器类型
            value: 定位器值
            success: 是否成功
            duration_ms: 耗时
        """
        with self._lock:
            key = self._get_key(element_id, locator_type, value)

            # 记录尝试
            attempt = LocatorAttempt(
                locator_type=locator_type,
                value=value,
                success=success,
                duration_ms=duration_ms,
                timestamp=time.time(),
            )
            self._history.append(attempt)

            # 限制历史长度
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

            # 更新统计
            stats = self._global_stats.get(key)
            if not stats:
                stats = LocatorStats(locator_type=locator_type, value=value)
                self._global_stats[key] = stats

            stats.attempts += 1
            if success:
                stats.successes += 1
            else:
                stats.failures += 1
            stats.total_duration_ms += duration_ms

            # 更新元素特定统计
            if element_id not in self._element_stats:
                self._element_stats[element_id] = {}
            self._element_stats[element_id][key] = stats

    def get_best_locator(
        self,
        element_id: str,
        candidates: List[tuple],
    ) -> Optional[tuple]:
        """
        获取最佳定位器

        Args:
            element_id: 元素标识
            candidates: 候选列表 [(type, value), ...]

        Returns:
            最佳 (type, value) 或 None
        """
        with self._lock:
            if not candidates:
                return None

            # 按成功率排序
            def get_score(candidate: tuple) -> float:
                locator_type, value = candidate
                key = self._get_key(element_id, locator_type, value)
                stats = self._global_stats.get(key)

                if not stats:
                    return 0.5  # 默认分数

                # 综合评分: 成功率 * 0.7 + 速度分数 * 0.3
                speed_score = max(0, 1 - stats.avg_duration_ms / 5000)  # 假设5秒是慢的
                return stats.success_rate * 0.7 + speed_score * 0.3

            # 排序
            ranked = sorted(candidates, key=get_score, reverse=True)

            # 只返回成功率超过阈值的
            best = ranked[0]
            best_key = self._get_key(element_id, best[0], best[1])
            best_stats = self._global_stats.get(best_key)

            if best_stats and best_stats.success_rate >= 0.3:
                return best

            # 如果所有都失败过，返回最佳尝试
            return ranked[0]

    def get_success_rate(self, element_id: str, locator_type: str, value: str) -> float:
        """获取特定定位器的成功率"""
        key = self._get_key(element_id, locator_type, value)
        stats = self._global_stats.get(key)
        return stats.success_rate if stats else 0.0

    def get_stats(self, element_id: str) -> Dict[str, Any]:
        """获取元素的所有统计"""
        with self._lock:
            if element_id not in self._element_stats:
                return {}

            stats = self._element_stats[element_id]
            return {
                key: stat.to_dict()
                for key, stat in stats.items()
            }

    def evolve_locator(
        self,
        failed_locator: tuple,
        element_id: str,
    ) -> List[tuple]:
        """
        演化定位器 - 从失败中学习

        尝试生成替代定位器方案

        Args:
            failed_locator: 失败的定位器
            element_id: 元素标识

        Returns:
            替代定位器列表
        """
        locator_type, value = failed_locator
        alternatives = []

        # CSS ID 失败 -> 尝试其他方式
        if locator_type == "css_id":
            if value.startswith("#"):
                id_val = value[1:]
                alternatives.extend([
                    ("data_test", f"[data-test='{id_val}']"),
                    ("role", f"[role=button]"),
                    ("text", id_val),
                ])

        # Role 失败 -> 尝试其他 role
        elif locator_type == "role":
            alternatives.extend([
                ("text", value),
                ("css_attr", f"[aria-label='{value}']"),
            ])

        # Text 失败 -> 尝试模糊匹配
        elif locator_type == "text":
            alternatives.extend([
                ("fuzzy_text", value.lower()),
                ("partial_text", value[:10]),
            ])

        # 如果没有替代方案，生成默认方案
        if not alternatives:
            alternatives = [
                ("css_id", f"#{element_id}"),
                ("data_test", f"[data-test='{element_id}']"),
                ("role", "button"),
                ("text", element_id),
            ]

        # 按成功率过滤
        best = self.get_best_locator(element_id, alternatives)

        return alternatives if not best else alternatives

    def reset_stats(self, element_id: Optional[str] = None):
        """重置统计"""
        with self._lock:
            if element_id:
                if element_id in self._element_stats:
                    del self._element_stats[element_id]
            else:
                self._element_stats.clear()
                self._global_stats.clear()
                self._history.clear()

    def _load_cache(self):
        """加载缓存"""
        if not self._cache_dir:
            return

        cache_file = Path(self._cache_dir) / ".testforge" / "locator_stats.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, stat_data in data.get("global", {}).items():
                        self._global_stats[key] = LocatorStats(**stat_data)
            except Exception:
                pass

    def _save_cache(self):
        """保存缓存"""
        if not self._cache_dir:
            return

        cache_file = Path(self._cache_dir) / ".testforge" / "locator_stats.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = {
                "global": {
                    key: asdict(stat)
                    for key, stat in self._global_stats.items()
                }
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def __del__(self):
        """析构时保存缓存"""
        self._save_cache()


class LocatorRegistry:
    """
    定位器注册表

    管理不同类型元素的定位器模板
    """

    # 常见元素的定位器模板
    TEMPLATES = {
        "button": [
            ("role", "button"),
            ("text", None),  # None 表示需要填充
            ("data_test", None),
        ],
        "input": [
            ("label", None),
            ("placeholder", None),
            ("name", None),
        ],
        "link": [
            ("role", "link"),
            ("text", None),
            ("href", None),
        ],
        "form": [
            ("css", "form"),
            ("role", "form"),
        ],
    }

    def __init__(self):
        self._custom_templates: Dict[str, List[tuple]] = {}

    def register_template(self, element_type: str, locators: List[tuple]):
        """注册定位器模板"""
        self._custom_templates[element_type] = locators

    def get_template(self, element_type: str) -> List[tuple]:
        """获取定位器模板"""
        return self._custom_templates.get(
            element_type,
            self.TEMPLATES.get(element_type, [])
        )

    def resolve_template(self, element_type: str, **kwargs) -> List[tuple]:
        """解析模板，填充参数"""
        template = self.get_template(element_type)
        resolved = []

        for locator_type, value in template:
            if value is None:
                value = kwargs.get(locator_type, kwargs.get("name", ""))
            resolved.append((locator_type, value))

        return resolved


# 全局实例
_adaptive_locator: Optional[AdaptiveLocator] = None


def get_adaptive_locator(cache_dir: Optional[str] = None) -> AdaptiveLocator:
    """获取全局自适应定位器"""
    global _adaptive_locator
    if _adaptive_locator is None:
        _adaptive_locator = AdaptiveLocator(cache_dir)
    return _adaptive_locator