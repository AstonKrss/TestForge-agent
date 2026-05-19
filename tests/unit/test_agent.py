"""
Agent 组件单元测试
================

参考 AutoQA-Agent 测试模式，测试 Agent 各组件：
1. Guardrails - 防护栏
2. Memory - 记忆系统
3. Planner - 规划器
4. Executor - 执行器
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time

import sys
sys.path.insert(0, 'src')

from agent import (
    AgentConfig,
    GuardrailCode,
    GuardrailError,
    GuardrailCounters,
    GuardrailLimits,
    check_guardrails,
    Memory,
    MemoryEntry,
    Planner,
    Step,
    StepStatus,
    ToolResult,
    Executor,
    Reflector,
)


# ==================== Guardrails Tests ====================

class TestGuardrailError:
    """测试 GuardrailError"""

    def test_creates_error_with_max_tool_calls(self):
        error = GuardrailError(GuardrailCode.MAX_TOOL_CALLS, 100, 101)

        assert error.code == "GUARDRAIL_MAX_TOOL_CALLS"
        assert error.limit == 100
        assert error.actual == 101
        assert error.step is None
        assert "limit=100" in str(error)
        assert "actual=101" in str(error)

    def test_creates_error_with_step_index(self):
        error = GuardrailError(GuardrailCode.MAX_RETRIES_PER_STEP, 5, 6, step=3)

        assert error.code == "GUARDRAIL_MAX_RETRIES_PER_STEP"
        assert error.limit == 5
        assert error.actual == 6
        assert error.step == 3
        assert "step=3" in str(error)


class TestGuardrailCounters:
    """测试 GuardrailCounters"""

    def test_initializes_counters_to_zero(self):
        counters = GuardrailCounters()

        assert counters.tool_calls == 0
        assert counters.consecutive_errors == 0
        assert counters.retries_per_step == {}

    def test_tracks_tool_calls(self):
        counters = GuardrailCounters()

        counters.tool_calls += 1
        counters.tool_calls += 1

        assert counters.tool_calls == 2


class TestCheckGuardrails:
    """测试 check_guardrails 函数"""

    def setup_method(self):
        self.limits = GuardrailLimits(
            max_tool_calls=10,
            max_consecutive_errors=3,
            max_retries_per_step=2,
        )

    def test_returns_none_when_within_limits(self):
        counters = GuardrailCounters()
        counters.tool_calls = 5
        counters.consecutive_errors = 1

        result = check_guardrails(counters, self.limits, step=None)

        assert result is None

    def test_returns_max_tool_calls_violation(self):
        counters = GuardrailCounters()
        counters.tool_calls = 11

        result = check_guardrails(counters, self.limits, step=None)

        assert result is not None
        assert result.code == "GUARDRAIL_MAX_TOOL_CALLS"
        assert result.limit == 10
        assert result.actual == 11

    def test_returns_max_consecutive_errors_violation(self):
        counters = GuardrailCounters()
        counters.consecutive_errors = 4

        result = check_guardrails(counters, self.limits, step=None)

        assert result is not None
        assert result.code == "GUARDRAIL_MAX_CONSECUTIVE_ERRORS"
        assert result.limit == 3
        assert result.actual == 4

    def test_returns_max_retries_per_step_violation(self):
        counters = GuardrailCounters()
        counters.retries_per_step[2] = 3

        result = check_guardrails(counters, self.limits, step=2)

        assert result is not None
        assert result.code == "GUARDRAIL_MAX_RETRIES_PER_STEP"
        assert result.limit == 2
        assert result.actual == 3
        assert result.step == 2

    def test_does_not_check_step_retries_when_step_is_none(self):
        counters = GuardrailCounters()
        counters.retries_per_step[2] = 10

        result = check_guardrails(counters, self.limits, step=None)

        assert result is None

    def test_prioritizes_max_tool_calls_over_others(self):
        counters = GuardrailCounters()
        counters.tool_calls = 11
        counters.consecutive_errors = 4
        counters.retries_per_step[1] = 3

        result = check_guardrails(counters, self.limits, step=1)

        assert result is not None
        assert result.code == "GUARDRAIL_MAX_TOOL_CALLS"

    def test_prioritizes_consecutive_errors_over_retries(self):
        counters = GuardrailCounters()
        counters.tool_calls = 5
        counters.consecutive_errors = 4
        counters.retries_per_step[1] = 3

        result = check_guardrails(counters, self.limits, step=1)

        assert result is not None
        assert result.code == "GUARDRAIL_MAX_CONSECUTIVE_ERRORS"


class TestGuardrailIntegration:
    """测试 guardrails 集成场景"""

    def test_simulates_agent_hitting_max_tool_calls(self):
        limits = GuardrailLimits(max_tool_calls=5, max_consecutive_errors=10, max_retries_per_step=10)
        counters = GuardrailCounters()

        for i in range(5):
            counters.tool_calls += 1
            assert check_guardrails(counters, limits, step=1) is None

        counters.tool_calls += 1
        violation = check_guardrails(counters, limits, step=1)

        assert violation is not None
        assert violation.code == "GUARDRAIL_MAX_TOOL_CALLS"
        assert violation.actual == 6

    def test_simulates_consecutive_errors_resetting_on_success(self):
        limits = GuardrailLimits(max_tool_calls=100, max_consecutive_errors=3, max_retries_per_step=10)
        counters = GuardrailCounters()

        # 3 errors
        counters.consecutive_errors = 3
        assert check_guardrails(counters, limits, step=1) is None

        # 4th error - should trigger
        counters.consecutive_errors = 4
        assert check_guardrails(counters, limits, step=1) is not None

        # Reset after success
        counters.consecutive_errors = 0
        assert check_guardrails(counters, limits, step=1) is None


# ==================== Memory Tests ====================

class TestMemory:
    """测试记忆系统"""

    def test_initializes_empty(self):
        memory = Memory(max_size=10)

        assert len(memory.entries) == 0

    def test_adds_entries(self):
        memory = Memory(max_size=10)

        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn", success=True))
        memory.add(MemoryEntry(timestamp=time.time(), action="fill", target="name", success=True))

        assert len(memory.entries) == 2

    def test_limits_size(self):
        memory = Memory(max_size=3)

        for i in range(5):
            memory.add(MemoryEntry(timestamp=time.time(), action="click", target=f"btn{i}", success=True))

        assert len(memory.entries) == 3
        # 应该保留最新的
        assert memory.entries[-1].target == "btn4"

    def test_get_similar_returns_matching_entries(self):
        memory = Memory(max_size=10)

        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="登录按钮", success=True))
        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="注册按钮", success=True))
        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="登录表单", success=False))
        memory.add(MemoryEntry(timestamp=time.time(), action="fill", target="用户名", success=True))

        results = memory.get_similar("click", "登录")

        assert len(results) <= 5
        for entry in results:
            assert entry.action == "click"
            assert entry.success

    def test_get_failed_patterns(self):
        memory = Memory(max_size=10)

        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn1", success=True))
        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn2", success=False))
        memory.add(MemoryEntry(timestamp=time.time(), action="fill", target="name", success=False))

        failed = memory.get_failed_patterns()

        assert len(failed) == 2
        for entry in failed:
            assert not entry.success

    def test_get_stats(self):
        memory = Memory(max_size=10)

        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn1", success=True))
        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn2", success=True))
        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn3", success=False))

        stats = memory.get_stats()

        assert stats["total"] == 3
        assert stats["success_rate"] == pytest.approx(2/3)
        assert "click" in stats["actions"]


# ==================== Planner Tests ====================

class TestPlanner:
    """测试规划器"""

    def test_parses_click_command(self):
        steps = Planner.parse_goal("click 登录")

        assert len(steps) == 1
        assert steps[0].action == "click"
        assert steps[0].target == "登录"
        assert steps[0].index == 1

    def test_parses_click_with_hash(self):
        steps = Planner.parse_goal("click #submit-btn")

        assert len(steps) == 1
        assert steps[0].action == "click"
        assert steps[0].target == "submit-btn"

    def test_parses_fill_command(self):
        steps = Planner.parse_goal("fill 用户名 testuser")

        assert len(steps) == 1
        assert steps[0].action == "fill"
        assert steps[0].target == "用户名"
        assert steps[0].value == "testuser"

    def test_parses_fill_with_hash(self):
        steps = Planner.parse_goal("fill #username admin")

        assert len(steps) == 1
        assert steps[0].action == "fill"
        assert steps[0].target == "username"
        assert steps[0].value == "admin"

    def test_parses_navigate_command(self):
        steps = Planner.parse_goal("go https://example.com")

        assert len(steps) == 1
        assert steps[0].action == "navigate"
        assert steps[0].target == "https://example.com"

    def test_parses_wait_command(self):
        steps = Planner.parse_goal("wait 2")

        assert len(steps) == 1
        assert steps[0].action == "wait"
        assert steps[0].value == "2"

    def test_parses_verify_command(self):
        steps = Planner.parse_goal("verify 登录成功")

        assert len(steps) == 1
        assert steps[0].action == "assert_text"
        assert steps[0].target == "登录成功"

    def test_parses_chinese_verify_command(self):
        steps = Planner.parse_goal("验证 操作完成")

        assert len(steps) == 1
        assert steps[0].action == "assert_text"
        assert steps[0].target == "操作完成"

    def test_parses_multiple_steps(self):
        steps = Planner.parse_goal("fill 用户名 admin; click 登录; verify 成功")

        assert len(steps) == 3
        assert steps[0].action == "fill"
        assert steps[1].action == "click"
        assert steps[2].action == "assert_text"

    def test_parses_newline_separated_steps(self):
        steps = Planner.parse_goal("go https://example.com\nwait 1\nclick 按钮")

        assert len(steps) == 3
        assert steps[0].action == "navigate"
        assert steps[1].action == "wait"
        assert steps[2].action == "click"

    def test_skips_empty_lines(self):
        steps = Planner.parse_goal("click 按钮1\n\nclick 按钮2")

        assert len(steps) == 2

    def test_returns_empty_for_invalid_goal(self):
        steps = Planner.parse_goal("")

        assert len(steps) == 0

    def test_handles_input_prefix(self):
        steps = Planner.parse_goal("input 用户名 testuser")

        assert len(steps) == 1
        assert steps[0].action == "fill"


# ==================== ToolResult Tests ====================

class TestToolResult:
    """测试工具结果"""

    def test_creates_success_result(self):
        result = ToolResult(ok=True, data={"url": "http://example.com"})

        assert result.ok is True
        assert result.data == {"url": "http://example.com"}
        assert result.error is None

    def test_creates_error_result(self):
        result = ToolResult(ok=False, error="Element not found")

        assert result.ok is False
        assert result.error == "Element not found"


# ==================== Step Tests ====================

class TestStep:
    """测试步骤"""

    def test_creates_step_with_defaults(self):
        step = Step(index=1, action="click", target="btn")

        assert step.index == 1
        assert step.action == "click"
        assert step.target == "btn"
        assert step.status == StepStatus.PENDING
        assert step.result is None
        assert step.error is None
        assert step.attempts == 0

    def test_step_status_transitions(self):
        step = Step(index=1, action="click")

        step.status = StepStatus.RUNNING
        assert step.status == StepStatus.RUNNING

        step.status = StepStatus.SUCCESS
        assert step.status == StepStatus.SUCCESS


# ==================== AgentConfig Tests ====================

class TestAgentConfig:
    """测试 Agent 配置"""

    def test_creates_config_with_defaults(self):
        config = AgentConfig()

        assert config.max_retries == 3
        assert config.timeout_ms == 30000
        assert config.thinking_enabled is True
        assert config.reflection_enabled is True
        assert config.memory_size == 100

    def test_creates_config_with_custom_values(self):
        config = AgentConfig(max_retries=5, timeout_ms=60000)

        assert config.max_retries == 5
        assert config.timeout_ms == 60000


# ==================== Reflector Tests ====================

class TestReflector:
    """测试反思器"""

    def test_analyze_failure_returns_suggestions(self):
        memory = Memory(max_size=10)
        memory.add(MemoryEntry(timestamp=time.time(), action="click", target="btn", success=False, error="not found"))

        step = Step(index=1, action="click", target="btn", error="not found")

        suggestions = Reflector.analyze_failure(step, memory)

        assert len(suggestions) > 0
        assert any("not found" in s.lower() or "截图" in s for s in suggestions)

    def test_analyze_failure_for_timeout(self):
        memory = Memory()
        step = Step(index=1, action="navigate", target="https://example.com", error="timeout")

        suggestions = Reflector.analyze_failure(step, memory)

        assert len(suggestions) > 0
        assert any("超时" in s or "等待" in s for s in suggestions)