"""
TestForge 快速入门
==================

使用方法:
cd TestForge
python examples/quickstart.py
"""

import sys
sys.path.insert(0, '.')

# ==================== 1. 基础工具使用 ====================

import asyncio
from src.browser import create_browser
from src.tools import click, fill, navigate, assert_element_visible, assert_text_present


async def basic_usage():
    """基础使用"""
    # 创建浏览器
    result = await create_browser(headless=True)
    browser = result["browser"]

    # 创建页面
    ctx = await browser.new_context()
    page = await ctx.new_page()

    # 导航
    await navigate(page, "https://example.com", "/")

    # 点击
    await click(page, description="More information")

    # 填写表单
    await fill(page, description="username", text="testuser")

    # 断言
    await assert_text_present(page, "Example Domain")

    await page.close()
    await ctx.close()


# ==================== 2. SmartWait 智能等待 ====================

from src.smart_wait import create_smart_wait, WaitConfig


async def smart_wait_demo():
    """SmartWait 使用"""
    result = await create_browser(headless=True)
    page = await result["browser"].new_page()

    sw = create_smart_wait(page, WaitConfig(timeout_ms=5000))

    # 等待元素出现
    sw.for_element("#submit-btn").to_appear()

    # 等待文本出现
    sw.for_text("Welcome").to_appear()

    # 等待 URL 变化
    sw.for_url().to_match(r"/dashboard/.*")

    # 等待网络空闲
    sw.for_network_idle().to_idle()


# ==================== 3. Intent Engine 意图推断 ====================

from src.intent_engine import create_intent_engine


def intent_demo():
    """Intent Engine 使用 - 直接写中文"""
    engine = create_intent_engine()

    # 解析中文步骤
    intent = engine.parse("输入用户名 为 testuser")
    print(f"类型: {intent.type.value}")  # fill
    print(f"目标: {intent.target}")  # 用户名
    print(f"值: {intent.value}")  # testuser

    # 支持的动作
    steps = [
        "打开登录页面",
        "输入用户名 为 admin",
        "输入密码 填成 123456",
        "点击登录按钮",
        "等待 3 秒",
        "验证欢迎信息 存在",
    ]

    for step in steps:
        intent = engine.parse(step)
        print(f"{step} → {intent.type.value} ({intent.confidence:.0%})")


# ==================== 4. Adaptive Locator 自适应定位 ====================

from src.adaptive_locator import get_adaptive_locator


def adaptive_locator_demo():
    """自适应定位器 - 记录成功率"""
    al = get_adaptive_locator()

    # 记录定位尝试
    al.record_attempt("登录按钮", "role", "button", success=True, duration_ms=45)
    al.record_attempt("登录按钮", "text", "登录", success=True, duration_ms=50)
    al.record_attempt("登录按钮", "text", "登录", success=False, duration_ms=30)  # 失败

    # 获取最佳定位器
    candidates = [
        ("role", "button"),
        ("text", "登录"),
        ("data_test", "login-btn"),
    ]
    best = al.get_best_locator("登录按钮", candidates)
    print(f"最佳定位器: {best}")  # 返回成功率最高的

    # 获取统计
    stats = al.get_stats("登录按钮")
    for key, stat in stats.items():
        print(f"{stat['type']}: 成功率 {stat['successRate']:.0%}")


# ==================== 5. MultiModal Assert 多模态断言 ====================

from src.multimodal_assert import assert_that


async def multimodal_assert_demo():
    """多模态断言"""
    result = await create_browser(headless=True)
    page = await result["browser"].new_page()
    await page.set_content("<button id='btn' style='background:blue'>Click</button>")

    # 元素状态断言
    result = assert_that(page).element("#btn").is_visible()
    print(f"可见: {result.ok}")

    # 元素尺寸断言
    result = assert_that(page).element("#btn").size_in_range(
        min_width=50, max_width=200,
        min_height=30, max_height=60
    )
    print(f"尺寸符合: {result.ok}")

    # 元素颜色断言
    result = assert_that(page).element("#btn").has_color("blue")
    print(f"蓝色: {result.ok}")


# ==================== 6. Test Evolution 测试演化 ====================

from src.test_evolution import get_evolution, FailureReason


def test_evolution_demo():
    """测试演化 - 从失败中学习"""
    evo = get_evolution()

    # 记录失败，生成替代方案
    alternatives = evo.evolve(
        "登录按钮",
        ("text", "登录"),
        FailureReason.ELEMENT_NOT_FOUND
    )
    print(f"替代方案: {alternatives}")

    # 记录成功
    evo.record_success("登录按钮", ("role", "button"), duration_ms=45)

    # 获取推荐定位器
    recommended = evo.get_recommended_locator("登录按钮")
    print(f"推荐: {recommended}")

    # 查看失败模式
    patterns = evo.get_failure_patterns("登录按钮")
    print(f"失败模式: {patterns}")


# ==================== 7. MCP Server 示例 ====================

"""
MCP 服务器运行方式:

# 启动 MCP 服务器
python -m src.agent

# 或使用 examples/mcp_server.py
"""

from src.agent import MCPServer, create_mcp_server


def mcp_demo():
    """MCP Server 使用"""
    # 创建 MCP 服务器
    server = create_mcp_server(
        page=None,  # 需要传入实际 page
        base_url="https://example.com",
        run_id="test-run",
        debug=True
    )

    # 可用工具:
    # - server.snapshot()   捕获快照
    # - server.navigate()  导航
    # - server.click()       点击
    # - server.fill()        填写
    # - server.scroll()      滚动
    # - server.wait()       等待
    # - server.assert_visible() 断言可见
    # - server.assert_text()     断言文本


# ==================== 主函数 ====================

async def main():
    """运行所有演示"""
    print("=" * 60)
    print("TestForge 快速入门")
    print("=" * 60)

    print("\n[1] Intent Engine 演示...")
    intent_demo()

    print("\n[2] Adaptive Locator 演示...")
    adaptive_locator_demo()

    print("\n[3] Test Evolution 演示...")
    test_evolution_demo()

    print("\n" + "=" * 60)
    print("更多示例请查看 examples/ 目录")
    print("=" * 60)


if __name__ == "__main__":
    # 单独运行各模块测试
    intent_demo()
    adaptive_locator_demo()
    test_evolution_demo()