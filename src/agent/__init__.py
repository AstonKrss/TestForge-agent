"""
TestForge Agent - Agent 编排
=============================

核心架构:
1. MCPServer - 提供工具给 LLM 调用
2. Planner - 把目标拆成执行步骤
3. Executor - 执行每一步操作
4. Reflector - 检查结果，失败时调整策略
5. Memory - 记住之前的操作经验

使用示例:
    agent = Agent(page, base_url="https://example.com")
    result = await agent.run("登录网站，用户名是 admin，密码是 123456")
"""

import os
import sys
import json
import asyncio
import re
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum

if False:
    from playwright.sync_api import Page


# ==================== 核心数据类型 ====================

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Step:
    """执行步骤"""
    index: int
    action: str  # navigate, click, fill, wait, assert
    target: Optional[str] = None
    value: Optional[str] = None
    expected: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict] = None
    error: Optional[str] = None
    attempts: int = 0


@dataclass
class MemoryEntry:
    """记忆条目"""
    timestamp: float
    action: str
    target: str
    success: bool
    error: Optional[str] = None
    page_url: Optional[str] = None
    strategy: Optional[str] = None
    value: Optional[str] = None  # fill 的值会存在这里


@dataclass
class AgentConfig:
    """Agent 配置"""
    max_retries: int = 3
    timeout_ms: int = 30000
    thinking_enabled: bool = True
    reflection_enabled: bool = True
    memory_size: int = 100


@dataclass
class ToolResult:
    """工具执行结果"""
    ok: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    screenshot: Optional[bytes] = None


# ==================== Memory 系统 ====================

class Memory:
    """记忆系统 - 记住之前的操作经验"""

    def __init__(self, max_size: int = 100):
        self.entries: List[MemoryEntry] = []
        self.max_size = max_size

    def add(self, entry: MemoryEntry):
        """添加记忆"""
        self.entries.append(entry)
        if len(self.entries) > self.max_size:
            self.entries = self.entries[-self.max_size:]

    def get_similar(self, action: str, target: str, limit: int = 5) -> List[MemoryEntry]:
        """获取相似的成功经验"""
        matches = [e for e in self.entries
                   if e.success and e.action == action and target.lower() in e.target.lower()]
        return matches[-limit:]

    def get_failed_patterns(self, limit: int = 10) -> List[MemoryEntry]:
        """获取失败模式"""
        return [e for e in self.entries if not e.success][-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        if not self.entries:
            return {"total": 0, "success_rate": 0, "actions": {}}

        total = len(self.entries)
        successes = sum(1 for e in self.entries if e.success)

        actions = {}
        for e in self.entries:
            if e.action not in actions:
                actions[e.action] = {"total": 0, "success": 0}
            actions[e.action]["total"] += 1
            if e.success:
                actions[e.action]["success"] += 1

        for action in actions.values():
            action["rate"] = action["success"] / action["total"] if action["total"] > 0 else 0

        return {
            "total": total,
            "success_rate": successes / total,
            "actions": actions
        }


# ==================== Planner - 规划器 ====================

class Planner:
    """规划器 - 把自然语言目标拆成步骤"""

    # 动作模式匹配 - 按优先级排序
    ACTION_PATTERNS = [
        # 填充 - 支持 #selector 格式
        (r"^input\s+#(\S+)\s+(.+)$", "fill", 2),     # input #username admin
        (r"^input\s+(\S+)\s+(.+)$", "fill", 2),      # input username admin
        (r"^fill\s+#(\S+)\s+(.+)$", "fill", 2),      # fill #username admin
        (r"^fill\s+(\S+)\s+(.+)$", "fill", 2),       # fill username admin
        # 点击
        (r"^click\s+#(.+)$", "click", 1),            # click #btn
        (r"^click\s+(.+)$", "click", 1),             # click 登录
        # 导航
        (r"^go\s+(.+)$", "navigate", 1),             # go http://x.com
        (r"^open\s+(.+)$", "navigate", 1),           # open http://x.com
        (r"^(https?://\S+)$", "navigate", 1),        # 直接URL
        # 等待
        (r"^wait\s+(\d+)$", "wait", 1),              # wait 2
        (r"等待\s*(\d+)\s*秒", "wait", 1),
        # 断言
        (r"^verify\s+(.+)$", "assert_text", 1),      # verify 成功
        (r"验证\s+(.+)", "assert_text", 1),
        (r"断言\s+(.+)", "assert_text", 1),
    ]

    @classmethod
    def parse_goal(cls, goal: str) -> List[Step]:
        """把目标解析成步骤"""
        steps = []
        lines = goal.replace("\n", ";").split(";")

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            step = cls._parse_line(line, i + 1)
            if step:
                steps.append(step)

        return steps

    @classmethod
    def _parse_line(cls, line: str, index: int) -> Optional[Step]:
        """解析单行指令"""
        for pattern, action, target_group in cls.ACTION_PATTERNS:
            match = re.search(pattern, line)
            if match:
                groups = match.groups()

                if action == "wait":
                    return Step(index=index, action=action, value=groups[0])

                if action in ("fill",):
                    if len(groups) >= 2:
                        return Step(index=index, action=action, target=groups[0], value=groups[1])
                    return Step(index=index, action=action, target=groups[0], value="")

                if action in ("click", "navigate", "assert_visible", "assert_text"):
                    target = groups[0] if groups else ""
                    return Step(index=index, action=action, target=target)

        return None


# ==================== Executor - 执行器 ====================

class Executor:
    """执行器 - 执行每个步骤"""

    def __init__(self, page, base_url: str, memory: Memory):
        self.page = page
        self.base_url = base_url
        self.memory = memory

    async def execute_step(self, step: Step, config: AgentConfig) -> ToolResult:
        """执行单个步骤"""
        action = step.action
        target = step.target or ""
        value = step.value or ""

        try:
            if action == "navigate":
                return await self._navigate(target, config)
            elif action == "click":
                return await self._click(target, config)
            elif action == "fill":
                return await self._fill(target, value, config)
            elif action == "wait":
                return await self._wait(int(value), config)
            elif action in ("assert_visible", "assert_element"):
                return await self._assert_visible(target, config)
            elif action == "assert_text":
                return await self._assert_text(target, config)
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def _navigate(self, url: str, config: AgentConfig) -> ToolResult:
        """导航到 URL"""
        if not url.startswith("http"):
            url = self.base_url.rstrip("/") + "/" + url.lstrip("/")

        await self.page.goto(url, wait_until="domcontentloaded", timeout=config.timeout_ms)
        screenshot = await self.page.screenshot()

        self.memory.add(MemoryEntry(
            timestamp=time.time(),
            action="navigate",
            target=url,
            success=True,
            page_url=self.page.url
        ))

        return ToolResult(
            ok=True,
            data={"url": self.page.url, "title": await self.page.title()},
            screenshot=screenshot
        )

    async def _click(self, target: str, config: AgentConfig) -> ToolResult:
        """点击元素 - 智能定位"""
        strategies = []

        # 1. 直接用 CSS 选择器 (如果是 #id 形式)
        if target.startswith("#"):
            strategies.append(("css", target))

        # 2. 中文按钮映射
        btn_map = {
            "登录": ["登录", "login", "signin", "sign in", "登录", "登入"],
            "注册": ["注册", "register", "sign up", "sign-up"],
            "提交": ["提交", "submit", "确认"],
            "取消": ["取消", "cancel"],
            "关闭": ["关闭", "close"],
            "下一步": ["下一步", "next"],
            "上一步": ["上一步", "back"],
            "确定": ["确定", "ok", "confirm"],
        }

        # 3. 文本匹配 (按钮、链接等)
        strategies.append(("text", target))

        # 4. role 属性 (button, link等)
        strategies.append(("role", target))

        # 5. 尝试各种可能的按钮文本
        for eng, cn_opts in btn_map.items():
            if target in cn_opts:
                for opt in cn_opts:
                    strategies.append(("text", opt))
                break

        # 6. 表单相关的 placeholder 或 name
        strategies.append(("placeholder", target))
        strategies.append(("name", target))

        for strategy, selector in strategies:
            try:
                if strategy == "css":
                    locator = self.page.locator(selector)
                elif strategy == "text":
                    locator = self.page.get_by_text(selector, exact=False)
                elif strategy == "role":
                    locator = self.page.get_by_role(strategy.split(":")[1], name=selector)
                elif strategy == "placeholder":
                    locator = self.page.get_by_placeholder(selector)
                elif strategy == "name":
                    locator = self.page.locator(f"[name='{selector}']")
                else:
                    continue

                if await locator.count() > 0:
                    await locator.first.click(timeout=3000)
                    screenshot = await self.page.screenshot()
                    self.memory.add(MemoryEntry(
                        timestamp=time.time(),
                        action="click",
                        target=target,
                        success=True,
                        strategy=strategy,
                        page_url=self.page.url
                    ))
                    return ToolResult(ok=True, screenshot=screenshot)

            except Exception:
                continue

        # 回退: 尝试 role=button
        try:
            locator = self.page.get_by_role("button")
            if await locator.count() > 0:
                await locator.first.click(timeout=3000)
                return ToolResult(ok=True)
        except Exception:
            pass

        error_msg = f"Click failed: cannot find '{target}'"
        self.memory.add(MemoryEntry(
            timestamp=time.time(),
            action="click",
            target=target,
            success=False,
            error=error_msg,
            page_url=self.page.url
        ))
        return ToolResult(ok=False, error=error_msg)

    async def _fill(self, target: str, value: str, config: AgentConfig) -> ToolResult:
        """填写表单 - 智能定位"""
        strategies = []

        # 中文标签映射
        label_map = {
            "用户名": "username",
            "用户名称": "username",
            "账号": "username",
            "账户": "username",
            "密码": "password",
            "确认密码": "password",
            "邮箱": "email",
            "手机": "phone",
            "电话": "phone",
            "验证码": "code",
            "搜索": "search",
            "关键词": "keyword",
            "留言": "message",
            "描述": "description",
        }

        # 转换中文标签为英文字段名
        field_key = label_map.get(target, target)

        # 1. CSS 选择器
        if target.startswith("#"):
            strategies.append(("css", target))

        # 2. name 属性 (用中文标签映射后的)
        strategies.append(("name", field_key))

        # 3. id 属性
        strategies.append(("id", field_key))

        # 4. placeholder (原始 target)
        strategies.append(("placeholder", target))
        strategies.append(("placeholder", field_key))

        # 5. label 关联 (中文)
        strategies.append(("label", target))

        # 6. 英文字段名
        strategies.append(("name", target))

        # 7. aria-label
        strategies.append(("aria", target))

        for strategy, selector in strategies:
            try:
                if strategy == "css":
                    locator = self.page.locator(selector)
                elif strategy == "name":
                    locator = self.page.locator(f"[name='{selector}']")
                elif strategy == "id":
                    locator = self.page.locator(f"#{selector}")
                elif strategy == "placeholder":
                    locator = self.page.get_by_placeholder(selector)
                elif strategy == "label":
                    locator = self.page.get_by_label(selector)
                elif strategy == "aria":
                    locator = self.page.locator(f"[aria-label*='{selector}']")

                if await locator.count() > 0:
                    await locator.first.wait_for(timeout=3000)
                    await locator.first.fill(value)
                    screenshot = await self.page.screenshot()

                    self.memory.add(MemoryEntry(
                        timestamp=time.time(),
                        action="fill",
                        target=target,
                        value=value,
                        success=True,
                        strategy=strategy,
                        page_url=self.page.url
                    ))
                    return ToolResult(ok=True, screenshot=screenshot)

            except Exception:
                continue

        # 回退：尝试第一个 input
        try:
            locator = self.page.locator("input[type='text'], input:not([type])").first
            if await locator.count() > 0:
                await locator.fill(value)
                return ToolResult(ok=True)
        except Exception:
            pass

        error_msg = f"Fill failed: cannot find '{target}' (tried: {field_key})"
        self.memory.add(MemoryEntry(
            timestamp=time.time(),
            action="fill",
            target=target,
            value=value,
            success=False,
            error=error_msg,
            page_url=self.page.url
        ))
        return ToolResult(ok=False, error=error_msg)

    async def _wait(self, seconds: int, config: AgentConfig) -> ToolResult:
        """等待"""
        await asyncio.sleep(seconds)
        return ToolResult(ok=True, data={"waited": seconds})

    async def _assert_visible(self, target: str, config: AgentConfig) -> ToolResult:
        """断言元素可见"""
        try:
            locator = self.page.get_by_text(target, exact=False).first
            is_visible = await locator.is_visible(timeout=5000)

            if is_visible:
                return ToolResult(ok=True, data={"visible": True})
            else:
                return ToolResult(ok=False, error=f"Element not visible: {target}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    async def _assert_text(self, text: str, config: AgentConfig) -> ToolResult:
        """断言文本存在"""
        try:
            content = await self.page.content()
            if text in content:
                return ToolResult(ok=True, data={"found": True})
            else:
                return ToolResult(ok=False, error=f"Text not found: {text}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


# ==================== Reflector - 反思器 ====================

class Reflector:
    """反思器 - 检查结果，失败时提出修复建议"""

    @staticmethod
    def analyze_failure(step: Step, memory: Memory) -> List[str]:
        """分析失败原因，返回修复建议"""
        suggestions = []

        failed = memory.get_failed_patterns()
        for entry in failed:
            if entry.action == step.action:
                suggestions.append(f"之前 '{entry.target}' 失败: {entry.error}")

        if step.error:
            error_lower = step.error.lower()

            if "not found" in error_lower or "not visible" in error_lower:
                suggestions.append("1. 先截图看看页面当前状态")
                suggestions.append("2. 等待元素加载，使用 wait()")
                suggestions.append("3. 可能页面已跳转，尝试重新定位")

            if "timeout" in error_lower:
                suggestions.append("1. 增加等待时间")
                suggestions.append("2. 先滚动页面")
                suggestions.append("3. 检查网络是否加载完成")

        return suggestions[:3]


# ==================== Agent 主类 ====================

class Agent:
    """
    TestForge Agent
    ================

    用自然语言描述目标，Agent 自动规划并执行。
    """

    def __init__(
        self,
        page,
        base_url: str,
        config: Optional[AgentConfig] = None,
        logger: Optional[Callable] = None
    ):
        self.page = page
        self.base_url = base_url
        self.config = config or AgentConfig()
        self.logger = logger or (lambda x: print(f"   [LOG] {x}"))

        self.memory = Memory(max_size=self.config.memory_size)
        self.planner = Planner()
        self.executor = Executor(page, base_url, self.memory)
        self.reflector = Reflector()

        self.steps: List[Step] = []

    async def run(self, goal: str) -> Dict[str, Any]:
        """
        执行目标

        Args:
            goal: 自然语言目标，如 "登录网站，用户名是 admin，密码是 123456"

        Returns:
            {success, steps, memory_stats, message}
        """
        print("\n" + "=" * 60)
        print("TestForge Agent 开始执行")
        print("=" * 60)
        print(f"\n目标: {goal}")

        # 1. 规划
        print("\n[规划中...]")
        self.steps = self.planner.parse_goal(goal)
        print(f"分解为 {len(self.steps)} 个步骤:")
        for step in self.steps:
            print(f"  {step.index}. {step.action} -> {step.target or step.value}")

        # 2. 执行
        print("\n[开始执行...]")
        import sys
        for step in self.steps:
            sys.stdout.flush()
            result = await self._execute_with_retry(step)

            step.result = {"ok": result.ok, "data": result.data}
            step.error = result.error

            if result.ok:
                step.status = StepStatus.SUCCESS
                detail = f"{step.target or step.value}" if step.action == "fill" else ""
                print(f"  [{step.index}] {step.action.upper()} {detail} -> 成功")
            else:
                step.status = StepStatus.FAILED
                print(f"  [{step.index}] {step.action.upper()} {step.target or ''} -> 失败: {result.error}")
            sys.stdout.flush()

        # 3. 汇总
        success_count = sum(1 for s in self.steps if s.status == StepStatus.SUCCESS)
        total = len(self.steps)

        print("\n" + "=" * 60)
        print("执行完成")
        print("=" * 60)
        print(f"成功: {success_count}/{total}")

        stats = self.memory.get_stats()
        print(f"记忆统计: 成功率 {stats['success_rate']:.0%}")

        return {
            "success": success_count == total,
            "steps": [
                {"index": s.index, "action": s.action, "status": s.status.value, "error": s.error}
                for s in self.steps
            ],
            "memory_stats": stats,
            "message": f"完成 {success_count}/{total} 个步骤"
        }

    async def _execute_with_retry(self, step: Step) -> ToolResult:
        """带重试的执行"""
        attempts = 0
        max_attempts = self.config.max_retries

        while attempts < max_attempts:
            attempts += 1
            step.attempts = attempts

            if attempts > 1:
                print(f"  重试 {attempts}/{max_attempts}...")
                await asyncio.sleep(0.5)

            result = await self.executor.execute_step(step, self.config)

            if result.ok:
                return result

            if self.config.reflection_enabled:
                suggestions = self.reflector.analyze_failure(step, self.memory)
                if suggestions:
                    print(f"  反思: {suggestions[0]}")

        return result


# ==================== Guardrails ====================

class GuardrailCode:
    MAX_TOOL_CALLS = "GUARDRAIL_MAX_TOOL_CALLS"
    MAX_CONSECUTIVE_ERRORS = "GUARDRAIL_MAX_CONSECUTIVE_ERRORS"
    MAX_RETRIES_PER_STEP = "GUARDRAIL_MAX_RETRIES_PER_STEP"


class GuardrailError(Exception):
    def __init__(self, code: str, limit: int, actual: int, step: Optional[int] = None):
        self.code = code
        self.limit = limit
        self.actual = actual
        self.step = step
        info = f" step={step}" if step else ""
        super().__init__(f"{code}: limit={limit} actual={actual}{info}")


class GuardrailCounters:
    def __init__(self):
        self.tool_calls = 0
        self.consecutive_errors = 0
        self.retries_per_step: Dict[int, int] = {}


class GuardrailLimits:
    def __init__(
        self,
        max_tool_calls: int = 200,
        max_consecutive_errors: int = 5,
        max_retries_per_step: int = 3,
    ):
        self.max_tool_calls = max_tool_calls
        self.max_consecutive_errors = max_consecutive_errors
        self.max_retries_per_step = max_retries_per_step


def check_guardrails(
    counters: GuardrailCounters,
    limits: GuardrailLimits,
    step: Optional[int] = None,
) -> Optional[GuardrailError]:
    """检查防护栏"""
    if counters.tool_calls > limits.max_tool_calls:
        return GuardrailError(GuardrailCode.MAX_TOOL_CALLS, limits.max_tool_calls, counters.tool_calls)

    if counters.consecutive_errors > limits.max_consecutive_errors:
        return GuardrailError(GuardrailCode.MAX_CONSECUTIVE_ERRORS, limits.max_consecutive_errors, counters.consecutive_errors)

    if step is not None:
        retries = counters.retries_per_step.get(step, 0)
        if retries > limits.max_retries_per_step:
            return GuardrailError(GuardrailCode.MAX_RETRIES_PER_STEP, limits.max_retries_per_step, retries, step)

    return None


def update_counters_on_tool_call(counters: GuardrailCounters) -> None:
    """
    工具调用后更新计数器

    参考 AutoQA-Agent updateCountersOnToolCall()
    """
    counters.tool_calls += 1


def update_counters_on_tool_result(
    counters: GuardrailCounters,
    step_index: Optional[int],
    is_error: bool,
) -> None:
    """
    工具结果后更新计数器

    参考 AutoQA-Agent updateCountersOnToolResult()

    - 错误时: consecutiveErrors++，step retries++
    - 成功时: consecutiveErrors = 0 (重置)
    """
    if is_error:
        counters.consecutive_errors += 1
        if step_index is not None:
            counters.retries_per_step[step_index] = counters.retries_per_step.get(step_index, 0) + 1
    else:
        counters.consecutive_errors = 0  # 成功后归零


# ==================== MCP Server ====================

class MCPServer:
    """
    MCP 工具服务器

    暴露以下工具:
    - snapshot: 捕获快照
    - navigate: 导航
    - click: 点击
    - fill: 填写
    - scroll: 滚动
    - wait: 等待
    - assert_visible: 断言可见
    - assert_text: 断言文本
    """

    def __init__(
        self,
        page: "Page",
        base_url: str,
        run_id: str,
        debug: bool = False,
    ):
        self.page = page
        self.base_url = base_url
        self.run_id = run_id
        self.debug = debug
        self._counter = 0

    def _name(self, tool: str) -> str:
        """生成文件基础名"""
        self._counter += 1
        return f"{tool}-{self._counter}"

    def _debug(self, msg: str):
        if self.debug:
            print(f"[TF] {msg}", file=__import__("sys").stderr)

    async def snapshot(self, step: Optional[int] = None) -> Dict[str, Any]:
        """捕获快照"""
        from ..browser import capture_aria_snapshot, capture_ax_snapshot

        self._debug(f"snapshot step={step}")
        aria = await capture_aria_snapshot(self.page)
        ax = await capture_ax_snapshot(self.page)

        content = []
        if not aria.get("ok"):
            content.append({"type": "text", "text": f"ARIA_FAILED: {aria.get('error', 'unknown')}"})
        else:
            content.append({"type": "text", "text": aria.get("data", {}).get("yaml", "")})

        if ax.get("ok"):
            ax_json = ax.get("data", {}).get("json", {})
            if isinstance(ax_json, dict):
                content.append({"type": "text", "text": ax_json.get("full", "NO_AX")})

        return {"content": content, "isError": False}

    async def navigate(self, url: str, step: Optional[int] = None) -> Dict[str, Any]:
        """导航"""
        from ..tools.navigate import navigate

        self._debug(f"navigate url={url} step={step}")
        result = await navigate(self.page, self.base_url, url)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }

    async def click(
        self,
        description: str = "",
        ref: str = "",
        step: Optional[int] = None,
    ) -> Dict[str, Any]:
        """点击"""
        from ..tools.click import click

        self._debug(f"click desc={description[:50]} ref={ref} step={step}")
        result = await click(self.page, description, ref, step)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }

    async def fill(
        self,
        description: str = "",
        ref: str = "",
        text: str = "",
        step: Optional[int] = None,
    ) -> Dict[str, Any]:
        """填写"""
        from ..tools.fill import fill

        self._debug(f"fill desc={description[:50]} ref={ref} text={text[:20]} step={step}")
        result = await fill(self.page, description, ref, text, step)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }

    async def scroll(
        self,
        direction: str,
        amount: float,
        step: Optional[int] = None,
    ) -> Dict[str, Any]:
        """滚动"""
        from ..tools.navigate import scroll

        self._debug(f"scroll {direction} {amount} step={step}")
        result = await scroll(self.page, direction, amount)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }

    async def wait(self, seconds: float, step: Optional[int] = None) -> Dict[str, Any]:
        """等待"""
        from ..tools.navigate import wait

        self._debug(f"wait {seconds}s step={step}")
        result = await wait(self.page, seconds)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }

    async def assert_visible(
        self,
        description: str = "",
        ref: str = "",
        step: Optional[int] = None,
    ) -> Dict[str, Any]:
        """断言可见"""
        from ..tools.assertions import assert_element_visible

        self._debug(f"assert_visible desc={description[:50]} ref={ref} step={step}")
        result = await assert_element_visible(self.page, description, ref)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }

    async def assert_text(self, text: str, step: Optional[int] = None) -> Dict[str, Any]:
        """断言文本"""
        from ..tools.assertions import assert_text_present

        self._debug(f"assert_text text={text[:30]} step={step}")
        result = await assert_text_present(self.page, text)

        return {
            "content": [{"type": "text", "text": json.dumps(result)}],
            "isError": not result.get("ok"),
        }


def create_mcp_server(
    page: "Page",
    base_url: str,
    run_id: str,
    debug: bool = False,
) -> MCPServer:
    """创建 MCP 服务器"""
    return MCPServer(page=page, base_url=base_url, run_id=run_id, debug=debug)