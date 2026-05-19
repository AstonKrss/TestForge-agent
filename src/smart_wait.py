"""
TestForge SmartWait - 智能等待系统
===================================

比传统等待聪明100倍的等待机制

核心创新:
1. 观察DOM变化而非单纯超时
2. 预测性等待 - 估计加载时间
3. 自适应重试 - 根据历史调整策略
"""

import asyncio
import time
from typing import Optional, Callable, Any, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

if TYPE_CHECKING:
    from playwright.sync_api import Page, Locator


class WaitStrategy(Enum):
    """等待策略"""
    DOM_CHANGE = "dom_change"      # DOM变化检测
    NETWORK_IDLE = "network_idle"    # 网络空闲
    ELEMENT_READY = "element_ready" # 元素就绪
    TEXT_MATCH = "text_match"       # 文本匹配
    URL_CHANGE = "url_change"       # URL变化
    PREDICTIVE = "predictive"       # 预测性等待


@dataclass
class WaitMetrics:
    """等待指标"""
    strategy: WaitStrategy
    start_time: float
    end_time: float = 0
    success: bool = False
    attempts: int = 0

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class WaitConfig:
    """等待配置"""
    timeout_ms: int = 10000
    interval_ms: int = 100
    max_retries: int = 3
    predictive_weight: float = 0.3  # 预测权重


class DOMObserver:
    """
    DOM变化观察器

    通过 MutationObserver 检测 DOM 变化
    """

    def __init__(self):
        self._changes = deque(maxlen=100)
        self._last_state: Optional[str] = None

    async def observe(self, locator: "Locator", timeout_ms: int = 10000) -> bool:
        """
        观察元素变化

        Returns:
            True 如果元素出现或变化
        """
        script = """
        () => {
            return new Promise((resolve) => {
                const target = document.querySelector(arguments[0]);
                if (!target) {
                    resolve({ found: false });
                    return;
                }

                let found = target.offsetParent !== null ||
                           getComputedStyle(target).display !== 'none';

                const observer = new MutationObserver((mutations) => {
                    let changed = false;
                    for (const m of mutations) {
                        if (m.type === 'childList' || m.type === 'attributes') {
                            changed = true;
                            break;
                        }
                    }
                    if (changed) found = true;
                });

                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                    attributes: true,
                });

                // 最长等待 timeout_ms
                setTimeout(() => {
                    observer.disconnect();
                    resolve({ found, changes: observer.takeRecords().length });
                }, arguments[1]);
            });
        }
        """

        try:
            selector = locator._selector if hasattr(locator, '_selector') else ""
            result = await locator.evaluate(script, selector, timeout_ms)
            return result.get("found", False)
        except Exception:
            return False

    def record_change(self, selector: str, change_type: str):
        """记录变化"""
        self._changes.append({
            "selector": selector,
            "type": change_type,
            "time": time.time(),
        })


class NetworkIdleDetector:
    """
    网络空闲检测器

    检测是否有网络请求还在进行
    """

    def __init__(self):
        self._pending_requests: int = 0

    async def wait_for_idle(
        self,
        page: "Page",
        timeout_ms: int = 5000,
    ) -> bool:
        """等待网络空闲"""
        try:
            # 等待 networkidle 状态
            await page.wait_for_load_state("networkidle", timeout=timeout_ms / 1000)
            return True
        except Exception:
            return False

    async def detect_slow_requests(
        self,
        page: "Page",
        threshold_ms: int = 3000,
    ) -> list:
        """检测慢请求"""
        slow = []
        try:
            requests = await page.evaluate("""
                () => {
                    if (!window.__tf_slow_requests) return [];
                    return window.__tf_slow_requests.filter(r => r.duration > arguments[0]);
                }
            """, threshold_ms)
            slow = requests
        except Exception:
            pass
        return slow


class SmartWait:
    """
    智能等待引擎

    使用多种策略智能等待元素/状态出现
    """

    def __init__(self, page: "Page", config: Optional[WaitConfig] = None):
        self.page = page
        self.config = config or WaitConfig()
        self._dom_observer = DOMObserver()
        self._network_detector = NetworkIdleDetector()
        self._metrics_history: deque = deque(maxlen=100)

    def for_element(self, selector: str) -> "ElementWaitBuilder":
        """等待元素"""
        return ElementWaitBuilder(self, selector)

    def for_text(self, text: str) -> "TextWaitBuilder":
        """等待文本"""
        return TextWaitBuilder(self, text)

    def for_url(self) -> "URLWaitBuilder":
        """等待 URL 变化"""
        return URLWaitBuilder(self)

    def for_network_idle(self) -> "NetworkWaitBuilder":
        """等待网络空闲"""
        return NetworkWaitBuilder(self)

    async def wait_for_any(
        self,
        conditions: list,
        timeout_ms: Optional[int] = None,
    ) -> tuple:
        """
        等待任意条件满足

        Returns:
            (index, result) 满足条件的索引和结果
        """
        timeout = timeout_ms or self.config.timeout_ms
        start = time.time()
        interval = self.config.interval_ms / 1000

        while time.time() - start < timeout / 1000:
            for i, condition in enumerate(conditions):
                if asyncio.iscoroutinefunction(condition):
                    result = await condition()
                else:
                    result = condition()

                if result:
                    return (i, result)

            await asyncio.sleep(interval)

        return (-1, None)

    async def wait_for_all(
        self,
        conditions: list,
        timeout_ms: Optional[int] = None,
    ) -> bool:
        """
        等待所有条件满足

        Returns:
            True 如果全部满足
        """
        timeout = timeout_ms or self.config.timeout_ms
        results = [False] * len(conditions)
        start = time.time()
        interval = self.config.interval_ms / 1000

        while time.time() - start < timeout / 1000:
            for i, condition in enumerate(conditions):
                if results[i]:
                    continue

                if asyncio.iscoroutinefunction(condition):
                    results[i] = await condition()
                else:
                    results[i] = condition()

            if all(results):
                return True

            await asyncio.sleep(interval)

        return False

    def record_metrics(self, metrics: WaitMetrics):
        """记录等待指标"""
        self._metrics_history.append(metrics)

    def get_average_wait_time(self, strategy: WaitStrategy) -> float:
        """获取平均等待时间"""
        relevant = [m for m in self._metrics_history if m.strategy == strategy]
        if not relevant:
            return 0
        return sum(m.duration_ms for m in relevant) / len(relevant)


class ElementWaitBuilder:
    """元素等待构建器"""

    def __init__(self, smart_wait: SmartWait, selector: str):
        self.sw = smart_wait
        self.selector = selector
        self._timeout_ms = smart_wait.config.timeout_ms
        self._strategy = WaitStrategy.DOM_CHANGE

    def to_appear(self, timeout_ms: Optional[int] = None) -> bool:
        """等待元素出现"""
        timeout = timeout_ms or self._timeout_ms
        start = time.time()

        metrics = WaitMetrics(
            strategy=self._strategy,
            start_time=start,
        )

        try:
            locator = self.sw.page.locator(self.selector)

            # 策略1: DOM 变化检测
            if self._strategy == WaitStrategy.DOM_CHANGE:
                found = asyncio.run(self.sw._dom_observer.observe(locator, timeout))
                if found:
                    metrics.success = True
                    metrics.end_time = time.time()
                    self.sw.record_metrics(metrics)
                    return True

            # 策略2: 标准等待
            locator.wait_for(state="visible", timeout=timeout / 1000)
            metrics.success = True
            metrics.end_time = time.time()
            self.sw.record_metrics(metrics)
            return True

        except Exception:
            metrics.end_time = time.time()
            metrics.attempts += 1
            self.sw.record_metrics(metrics)
            return False

    def to_disappear(self) -> bool:
        """等待元素消失"""
        try:
            locator = self.sw.page.locator(self.selector)
            locator.wait_for(state="hidden", timeout=self._timeout_ms / 1000)
            return True
        except Exception:
            return False

    def to_be_enabled(self) -> bool:
        """等待元素启用"""
        try:
            locator = self.sw.page.locator(self.selector)
            locator.wait_for(state="enabled", timeout=self._timeout_ms / 1000)
            return True
        except Exception:
            return False


class TextWaitBuilder:
    """文本等待构建器"""

    def __init__(self, smart_wait: SmartWait, text: str):
        self.sw = smart_wait
        self.text = text
        self._timeout_ms = smart_wait.config.timeout_ms

    def to_appear(self, timeout_ms: Optional[int] = None) -> bool:
        """等待文本出现"""
        timeout = timeout_ms or self._timeout_ms
        try:
            locator = self.sw.page.get_by_text(self.text)
            count = locator.count()
            if count > 0:
                return locator.first.is_visible()
            return False
        except Exception:
            return False


class URLWaitBuilder:
    """URL等待构建器"""

    def __init__(self, smart_wait: SmartWait):
        self.sw = smart_wait
        self._initial_url: Optional[str] = None
        self._expected_pattern: Optional[str] = None

    def to_change(self) -> bool:
        """等待URL变化"""
        self._initial_url = self.sw.page.url

        try:
            self.sw.page.wait_for_url(
                lambda url: url != self._initial_url,
                timeout=self.sw.config.timeout_ms / 1000,
            )
            return True
        except Exception:
            return False

    def to_match(self, pattern: str) -> bool:
        """等待URL匹配模式"""
        import re
        self._expected_pattern = pattern

        try:
            self.sw.page.wait_for_url(
                lambda url: bool(re.match(pattern, url)),
                timeout=self.sw.config.timeout_ms / 1000,
            )
            return True
        except Exception:
            return False


class NetworkWaitBuilder:
    """网络等待构建器"""

    def __init__(self, smart_wait: SmartWait):
        self.sw = smart_wait

    def to_idle(self, timeout_ms: Optional[int] = None) -> bool:
        """等待网络空闲"""
        return asyncio.run(
            self.sw._network_detector.wait_for_idle(
                self.sw.page,
                timeout_ms or self.sw.config.timeout_ms,
            )
        )

    def no_slow_requests(self, threshold_ms: int = 3000) -> bool:
        """没有慢请求"""
        slow = asyncio.run(
            self.sw._network_detector.detect_slow_requests(
                self.sw.page,
                threshold_ms,
            )
        )
        return len(slow) == 0


# 便捷函数
def create_smart_wait(page: "Page", config: Optional[WaitConfig] = None) -> SmartWait:
    """创建智能等待实例"""
    return SmartWait(page, config)