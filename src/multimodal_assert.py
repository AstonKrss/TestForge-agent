"""
TestForge MultiModal Assert - 多模态断言
=======================================

不仅断言文本，还支持截图对比、视觉元素检测

核心创新:
1. 截图对比 - 像素级差异检测
2. 视觉元素检测 - 识别按钮颜色、大小等
3. 状态断言 - 验证元素状态
4. 组合断言 - 多个条件同时验证
"""

import io
import time
import hashlib
from typing import Optional, Dict, Any, List, Callable, Union
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class AssertMode(Enum):
    """断言模式"""
    TEXT = "text"
    VISIBLE = "visible"
    ENABLED = "enabled"
    SCREENSHOT = "screenshot"
    VISUAL_ELEMENT = "visual_element"
    COMBO = "combo"


@dataclass
class AssertResult:
    """断言结果"""
    ok: bool
    mode: AssertMode
    message: str
    details: Optional[Dict[str, Any]] = None
    screenshot_path: Optional[str] = None


@dataclass
class ScreenshotDiff:
    """截图差异"""
    identical: bool
    diff_ratio: float  # 0-1, 差异比例
    diff_pixels: int
    expected_hash: str
    actual_hash: str


class MultiModalAssert:
    """
    多模态断言

    支持多种断言模式的组合使用
    """

    def __init__(self, page):
        self.page = page
        self._last_screenshot: Optional[bytes] = None

    # ==================== 元素状态断言 ====================

    async def is_visible(self, selector: str) -> AssertResult:
        """断言元素可见"""
        try:
            locator = self.page.locator(selector)
            count = await locator.count()
            if count <= 0:
                return AssertResult(
                    ok=False,
                    mode=AssertMode.VISIBLE,
                    message=f"Element not found: {selector}",
                )

            is_visible = await locator.first.is_visible()
            return AssertResult(
                ok=is_visible,
                mode=AssertMode.VISIBLE,
                message=f"Element {'visible' if is_visible else 'not visible'}: {selector}",
                details={"selector": selector, "count": count},
            )
        except Exception as e:
            return AssertResult(
                ok=False,
                mode=AssertMode.VISIBLE,
                message=str(e),
            )

    async def is_enabled(self, selector: str) -> AssertResult:
        """断言元素启用"""
        try:
            locator = self.page.locator(selector)
            is_enabled = await locator.first.is_enabled()
            return AssertResult(
                ok=is_enabled,
                mode=AssertMode.ENABLED,
                message=f"Element {'enabled' if is_enabled else 'disabled'}: {selector}",
            )
        except Exception as e:
            return AssertResult(
                ok=False,
                mode=AssertMode.ENABLED,
                message=str(e),
            )

    async def has_text(self, text: str, exact: bool = False) -> AssertResult:
        """断言包含文本"""
        try:
            locator = self.page.get_by_text(text, exact=exact)
            count = await locator.count()

            if count > 0:
                visible_count = 0
                limit = min(count, 5)
                for i in range(limit):
                    if await locator.nth(i).is_visible():
                        visible_count += 1

                return AssertResult(
                    ok=visible_count > 0,
                    mode=AssertMode.TEXT,
                    message=f"Text {'found' if visible_count > 0 else 'not found'}: {text}",
                    details={"text": text, "matches": visible_count},
                )

            return AssertResult(
                ok=False,
                mode=AssertMode.TEXT,
                message=f"Text not found: {text}",
            )
        except Exception as e:
            return AssertResult(
                ok=False,
                mode=AssertMode.TEXT,
                message=str(e),
            )

    # ==================== 截图断言 ====================

    async def screenshot_matches(
        self,
        expected_path: str,
        threshold: float = 0.95,
    ) -> AssertResult:
        """
        断言截图匹配

        Args:
            expected_path: 期望截图路径
            threshold: 相似度阈值 (0-1)

        Returns:
            AssertResult
        """
        if not PIL_AVAILABLE:
            return AssertResult(
                ok=False,
                mode=AssertMode.SCREENSHOT,
                message="PIL not available, install with: pip install Pillow",
            )

        try:
            # 加载期望截图
            expected_img = Image.open(expected_path)
            expected_hash = self._image_hash(expected_img)

            # 捕获当前截图
            current_screenshot = await self.page.screenshot()
            current_img = Image.open(io.BytesIO(current_screenshot))
            current_hash = self._image_hash(current_img)

            # 计算差异
            diff = self._compute_diff(expected_img, current_img)

            if diff.identical:
                return AssertResult(
                    ok=True,
                    mode=AssertMode.SCREENSHOT,
                    message="Screenshots match",
                    details={"diffRatio": diff.diff_ratio},
                )

            # 如果不匹配，检查是否超过阈值
            if diff.diff_ratio <= (1 - threshold):
                return AssertResult(
                    ok=True,
                    mode=AssertMode.SCREENSHOT,
                    message=f"Screenshots similar ({diff.diff_ratio:.1%})",
                    details={
                        "diffRatio": diff.diff_ratio,
                        "diffPixels": diff.diff_pixels,
                    },
                )
            else:
                return AssertResult(
                    ok=False,
                    mode=AssertMode.SCREENSHOT,
                    message=f"Screenshots differ ({diff.diff_ratio:.1%})",
                    details={
                        "diffRatio": diff.diff_ratio,
                        "diffPixels": diff.diff_pixels,
                        "expectedHash": diff.expected_hash,
                        "actualHash": diff.actual_hash,
                    },
                )
        except FileNotFoundError:
            return AssertResult(
                ok=False,
                mode=AssertMode.SCREENSHOT,
                message=f"Expected screenshot not found: {expected_path}",
            )
        except Exception as e:
            return AssertResult(
                ok=False,
                mode=AssertMode.SCREENSHOT,
                message=str(e),
            )

    def _image_hash(self, img: Image.Image) -> str:
        """计算图片哈希"""
        img = img.resize((100, 100))
        data = list(img.getdata())
        return hashlib.md5(bytes(data)).hexdigest()

    def _compute_diff(self, img1: Image.Image, img2: Image.Image) -> ScreenshotDiff:
        """计算两张图片的差异"""
        # 调整大小一致
        if img1.size != img2.size:
            img2 = img2.resize(img1.size)

        # 转灰度
        gray1 = img1.convert("L")
        gray2 = img2.convert("L")

        # 获取像素数据
        pixels1 = list(gray1.getdata())
        pixels2 = list(gray2.getdata())

        # 计算差异像素
        diff_pixels = 0
        total_pixels = len(pixels1)

        for p1, p2 in zip(pixels1, pixels2):
            if abs(p1 - p2) > 10:  # 容差
                diff_pixels += 1

        diff_ratio = diff_pixels / total_pixels if total_pixels > 0 else 0

        return ScreenshotDiff(
            identical=diff_pixels == 0,
            diff_ratio=diff_ratio,
            diff_pixels=diff_pixels,
            expected_hash=self._image_hash(img1),
            actual_hash=self._image_hash(img2),
        )

    # ==================== 视觉元素断言 ====================

    async def element_has_color(
        self,
        selector: str,
        expected_color: str,
        tolerance: int = 30,
    ) -> AssertResult:
        """
        断言元素具有指定颜色

        Args:
            selector: CSS 选择器
            expected_color: 期望颜色 (如 "#FF0000" 或 "red")
            tolerance: 容差
        """
        try:
            # 获取元素背景色
            color = await self.page.locator(selector).evaluate("""
                (selector) => {
                    const el = document.querySelector(selector);
                    if (!el) return null;
                    const style = getComputedStyle(el);
                    return style.backgroundColor || style.color;
                }
            """, selector)

            if not color:
                return AssertResult(
                    ok=False,
                    mode=AssertMode.VISUAL_ELEMENT,
                    message=f"No color found for: {selector}",
                )

            # 简化比较 (实际应用中需要更精确的颜色转换)
            color_match = expected_color.lower() in color.lower()

            return AssertResult(
                ok=color_match,
                mode=AssertMode.VISUAL_ELEMENT,
                message=f"Color {'matched' if color_match else 'mismatched'}: {color}",
                details={
                    "expected": expected_color,
                    "actual": color,
                    "selector": selector,
                },
            )
        except Exception as e:
            return AssertResult(
                ok=False,
                mode=AssertMode.VISUAL_ELEMENT,
                message=str(e),
            )

    async def element_size_in_range(
        self,
        selector: str,
        min_width: Optional[int] = None,
        max_width: Optional[int] = None,
        min_height: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> AssertResult:
        """断言元素尺寸在范围内"""
        try:
            bbox = await self.page.locator(selector).bounding_box()

            if not bbox:
                return AssertResult(
                    ok=False,
                    mode=AssertMode.VISUAL_ELEMENT,
                    message=f"Element not found: {selector}",
                )

            width_ok = True
            height_ok = True

            if min_width and bbox["width"] < min_width:
                width_ok = False
            if max_width and bbox["width"] > max_width:
                width_ok = False
            if min_height and bbox["height"] < min_height:
                height_ok = False
            if max_height and bbox["height"] > max_height:
                height_ok = False

            ok = width_ok and height_ok

            return AssertResult(
                ok=ok,
                mode=AssertMode.VISUAL_ELEMENT,
                message=f"Element size {'OK' if ok else 'out of range'}",
                details={
                    "actual": {"width": bbox["width"], "height": bbox["height"]},
                    "expected": {
                        "min_width": min_width,
                        "max_width": max_width,
                        "min_height": min_height,
                        "max_height": max_height,
                    },
                },
            )
        except Exception as e:
            return AssertResult(
                ok=False,
                mode=AssertMode.VISUAL_ELEMENT,
                message=str(e),
            )

    # ==================== 组合断言 ====================

    async def assert_all(
        self,
        conditions: List[Callable],
    ) -> AssertResult:
        """
        组合断言 - 所有条件都满足

        Args:
            conditions: 条件函数列表
        """
        results = []
        failed = []

        for i, condition in enumerate(conditions):
            if callable(condition):
                result = await condition()
            else:
                result = condition

            results.append((i, result))

            if isinstance(result, AssertResult) and not result.ok:
                failed.append(i)

        if not failed:
            return AssertResult(
                ok=True,
                mode=AssertMode.COMBO,
                message=f"All {len(conditions)} assertions passed",
            )
        else:
            return AssertResult(
                ok=False,
                mode=AssertMode.COMBO,
                message=f"Failed assertions at indices: {failed}",
                details={"failed": failed, "total": len(conditions)},
            )

    async def assert_any(
        self,
        conditions: List[Callable],
    ) -> AssertResult:
        """
        组合断言 - 任一条件满足

        Args:
            conditions: 条件函数列表
        """
        for i, condition in enumerate(conditions):
            if callable(condition):
                result = await condition()
            else:
                result = condition

            if isinstance(result, AssertResult) and result.ok:
                return AssertResult(
                    ok=True,
                    mode=AssertMode.COMBO,
                    message=f"Condition {i} passed",
                )

        return AssertResult(
            ok=False,
            mode=AssertMode.COMBO,
            message="No condition passed",
        )


class AssertThat:
    """
    断言构建器

    使用流畅接口构建断言
    """

    def __init__(self, page):
        self._page = page
        self._assert = MultiModalAssert(page)

    def element(self, selector: str) -> "ElementAssertBuilder":
        """获取元素断言构建器"""
        return ElementAssertBuilder(self._page, self._assert, selector)

    def page(self) -> "PageAssertBuilder":
        """获取页面断言构建器"""
        return PageAssertBuilder(self._page, self._assert)


class ElementAssertBuilder:
    """元素断言构建器"""

    def __init__(self, page, assert_instance: MultiModalAssert, selector: str):
        self._page = page
        self._assert = assert_instance
        self._selector = selector

    def is_visible(self) -> AssertResult:
        """可见断言"""
        return self._assert.is_visible(self._selector)

    def is_enabled(self) -> AssertResult:
        """启用断言"""
        return self._assert.is_enabled(self._selector)

    def has_color(self, color: str, tolerance: int = 30) -> AssertResult:
        """颜色断言"""
        return self._assert.element_has_color(self._selector, color, tolerance)

    def size_in_range(
        self,
        min_width: Optional[int] = None,
        max_width: Optional[int] = None,
        min_height: Optional[int] = None,
        max_height: Optional[int] = None,
    ) -> AssertResult:
        """尺寸断言"""
        return self._assert.element_size_in_range(
            self._selector, min_width, max_width, min_height, max_height
        )


class PageAssertBuilder:
    """页面断言构建器"""

    def __init__(self, page, assert_instance: MultiModalAssert):
        self._page = page
        self._assert = assert_instance

    def screenshot(self) -> "ScreenshotAssertBuilder":
        """截图断言"""
        return ScreenshotAssertBuilder(self._page, self._assert)


class ScreenshotAssertBuilder:
    """截图断言构建器"""

    def __init__(self, page, assert_instance: MultiModalAssert):
        self._page = page
        self._assert = assert_instance
        self._threshold = 0.95

    def matches(self, expected_path: str, threshold: float = 0.95) -> AssertResult:
        """匹配断言"""
        self._threshold = threshold
        return self._assert.screenshot_matches(expected_path, threshold)


# 便捷函数
def assert_that(page) -> AssertThat:
    """创建断言构建器"""
    return AssertThat(page)