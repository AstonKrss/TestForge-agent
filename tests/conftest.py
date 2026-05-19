"""
Pytest 配置和 Fixtures
=====================
"""

import pytest
import sys

# 确保 src 在路径中
sys.path.insert(0, 'src')


@pytest.fixture
def sample_memory_entry():
    """样本记忆条目"""
    import time
    from agent import MemoryEntry
    return MemoryEntry(
        timestamp=time.time(),
        action="click",
        target="登录按钮",
        success=True,
        page_url="https://example.com/login"
    )


@pytest.fixture
def sample_page_mock():
    """模拟的 Page 对象"""
    from unittest.mock import AsyncMock, MagicMock

    page = MagicMock()
    page.goto = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake_screenshot")
    page.title = AsyncMock(return_value="Test Page")
    page.url = "https://example.com"
    page.content = AsyncMock(return_value="<html>Test</html>")

    return page


@pytest.fixture
def sample_step():
    """样本步骤"""
    from agent import Step, StepStatus
    return Step(index=1, action="click", target="按钮")