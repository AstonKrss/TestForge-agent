"""
TestForge AI Agent - LLM驱动的工具调用
========================================

参考 AutoQA-Agent 架构:
1. 定义工具规范 (name, description, input schema)
2. LLM 决定调用哪个工具
3. Ref-First: 先 snapshot 获取元素引用，再执行操作
"""

import asyncio
import json
import re
import time
from typing import Optional, Dict, Any, List

from .client import create_ai_client, AIClient, AIConfig


# ==================== 工具定义 ====================

class Tool:
    """工具定义"""
    def __init__(self, name: str, description: str, input_schema: Dict):
        self.name = name
        self.description = description
        self.input_schema = input_schema


TOOLS = [
    Tool(
        name="snapshot",
        description="获取页面快照（元素引用和可交互性信息）。每个元素有引用如 e15，用于后续操作。",
        input_schema={
            "type": "object",
            "properties": {},
            "required": []
        }
    ),
    Tool(
        name="navigate",
        description="导航到 URL 或相对路径",
        input_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "URL 或路径如 /login"}
            },
            "required": ["target"]
        }
    ),
    Tool(
        name="click",
        description="点击元素（用 ref 引用或 targetDescription）",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "元素引用如 e15"},
                "targetDescription": {"type": "string", "description": "元素描述"}
            },
            "required": []
        }
    ),
    Tool(
        name="fill",
        description="填写表单字段",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "元素引用如 e15"},
                "targetDescription": {"type": "string", "description": "元素描述"},
                "value": {"type": "string", "description": "要填入的值"}
            },
            "required": ["value"]
        }
    ),
    Tool(
        name="select_option",
        description="选择下拉选项",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "元素引用如 e15"},
                "targetDescription": {"type": "string", "description": "元素描述"},
                "value": {"type": "string", "description": "选项值"}
            },
            "required": ["value"]
        }
    ),
    Tool(
        name="scroll",
        description="滚动页面或元素",
        input_schema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "up/down/left/right"},
                "amount": {"type": "string", "description": "像素数量如 300"}
            },
            "required": []
        }
    ),
    Tool(
        name="wait",
        description="等待指定秒数",
        input_schema={
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "等待秒数"}
            },
            "required": []
        }
    ),
    Tool(
        name="assert_text_present",
        description="断言页面包含指定文本",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要查找的文本"}
            },
            "required": ["text"]
        }
    ),
    Tool(
        name="assert_element_visible",
        description="断言元素可见",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "元素引用"},
                "targetDescription": {"type": "string", "description": "元素描述"}
            },
            "required": []
        }
    ),
]


def build_tools_description() -> str:
    """生成工具描述文本"""
    lines = ["你可用的工具:\n"]
    for tool in TOOLS:
        lines.append(f"## {tool.name}")
        lines.append(f"描述: {tool.description}")
        if tool.input_schema.get("properties"):
            lines.append("参数:")
            for name, prop in tool.input_schema["properties"].items():
                desc = prop.get("description", "")
                lines.append(f"  - {name}: {desc}")
        lines.append("")
    return "\n".join(lines)


# ==================== AIAgent ====================

class AIAgent:
    """
    AI 驱动的 Agent - LLM 决定工具调用

    核心流程:
    1. 构建提示 (页面状态 + 工具列表 + 目标)
    2. LLM 决定调用哪个工具
    3. 执行工具并返回结果
    4. 重复直到完成
    """

    def __init__(
        self,
        page,
        base_url: str,
        ai_client: Optional[AIClient] = None,
        config: Optional[AIConfig] = None,
    ):
        self.page = page
        self.base_url = base_url
        self.ai_client = ai_client or create_ai_client(config)

        # 元素引用映射: ref -> element info
        self._element_refs: Dict[str, Dict] = {}

        # 执行统计
        self._tool_calls: List[Dict] = []
        self._max_turns = 50

    async def run(self, goal: str) -> Dict[str, Any]:
        """
        运行 Agent 执行目标

        流程:
        1. 解析 URL 和凭证
        2. 一次性获取页面状态
        3. LLM 生成完整计划
        4. 按计划执行
        """
        print("\n" + "=" * 60)
        print("TestForge AI Agent")
        print("=" * 60)
        print(f"\n目标: {goal}")

        # 解析目标
        url_match = re.search(r'(https?://[\w\.-]+(?:/[\w\.-]*)*)', goal)
        target_url = url_match.group(1) if url_match else None

        if target_url:
            task_text = goal.replace(target_url, '').strip()
            if task_text:
                goal = task_text

        # 提取凭证
        creds = self._extract_credentials(goal)

        print(f"   目标 URL: {target_url or '无'}")
        print(f"   任务: {goal}")
        print(f"   用户名: {creds.get('username', '无')}")
        print(f"   密码: {'有' if creds.get('password') else '无'}")

        # 访问页面
        if target_url:
            print(f"\n访问: {target_url}")
            result = await self._tool_navigate(target_url)
            if not result.get("success"):
                print(f"   导航失败: {result}")
                return {"success": False, "error": "导航失败"}

        # 获取页面状态
        print("\n[1] 获取页面状态...")
        page_state = await self._get_page_state()
        print(f"   页面: {self.page.url}")

        # 发送完整信息给 LLM，生成计划
        print("\n[2] LLM 分析并生成计划...")
        plan = await self._generate_plan(goal, page_state, creds)

        if not plan:
            print("   无法生成计划")
            return {"success": False, "error": "无法生成计划"}

        print(f"   计划步骤: {len(plan)}")

        # 按计划执行
        print("\n[3] 执行计划")
        print("-" * 40)

        for i, step in enumerate(plan):
            print(f"\n   步骤 {i+1}: {step['描述']}")

            result = await self._execute_step(step, creds)
            print(f"   结果: {result}")

            # 如果失败，询问用户
            if not result.get("success"):
                user_input = input("\n   步骤失败，如何继续? ").strip()
                if user_input.lower() in ('q', 'quit', 'exit', 'n', '否'):
                    break
                # 继续下一轮

        print("\n[完成]")
        return {"success": True, "steps": len(plan)}

    async def _generate_plan(self, goal: str, page_state: str, creds: Dict) -> List[Dict]:
        """让 LLM 生成完整执行计划"""
        system = """你是一个 Web 自动化测试规划助手。

根据用户目标和页面状态，生成具体的执行计划。
必须用 JSON 数组格式输出计划步骤。

每个步骤包含:
- action: 操作类型 (click, fill, wait, submit, navigate)
- target: 目标元素描述或选择器
- value: 填写值（如果需要）
- 描述: 中文描述步骤

示例计划:
[
  {"action": "click", "target": "登录", "描述": "点击登录链接"},
  {"action": "fill", "target": "#username", "value": "admin", "描述": "填写用户名"},
  {"action": "fill", "target": "#password", "value": "xxx", "描述": "填写密码"},
  {"action": "submit", "target": "登录", "描述": "点击登录按钮"}
]

如果缺少信息（如密码），用 "__NEED_INPUT__" 标记，程序会询问用户。

只输出 JSON，不要其他内容。"""

        user_msg = f"""任务: {goal}

页面状态:
{page_state}

凭证:
- 用户名: {creds.get('username', '未提供')}
- 密码: {'已提供' if creds.get('password') else '未提供'}

请生成执行计划（JSON数组）:
"""

        try:
            response = await self.ai_client.complete(user_msg, system)

            # 解析 JSON
            start = response.find('[')
            end = response.rfind(']') + 1
            if start >= 0 and end > start:
                plan = json.loads(response[start:end])
                return plan

        except Exception as e:
            print(f"   计划生成失败: {e}")

        return []

    async def _execute_step(self, step: Dict, creds: Dict) -> Dict:
        """执行单个步骤"""
        action = step.get('action', '')
        target = step.get('target', '')
        value = step.get('value', '')

        try:
            if action == 'click':
                return await self._step_click(target)

            elif action == 'fill':
                # 检查是否需要用户输入
                if value == '__NEED_INPUT__':
                    field_name = target.replace('#', '').replace('[', '').replace(']', '')
                    print(f"   [需要输入] {field_name}")
                    value = input(f"   请输入 {field_name}: ").strip()
                    if not value:
                        return {"success": False, "message": "用户取消"}
                return await self._step_fill(target, value)

            elif action == 'wait':
                seconds = int(value) if value else 1
                await asyncio.sleep(seconds)
                return {"success": True, "message": f"等待{seconds}秒"}

            elif action == 'submit':
                return await self._step_submit()

            elif action == 'navigate':
                return await self._tool_navigate(target)

            else:
                return {"success": False, "message": f"未知操作: {action}"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _step_click(self, target: str) -> Dict:
        """点击元素"""
        try:
            # 如果是选择器
            if target.startswith('#') or target.startswith('['):
                await self.page.click(target, timeout=5000)
                return {"success": True, "message": f"点击 {target}"}

            # 如果是文本，查找并点击
            loc = self.page.get_by_text(target, exact=False)
            count = await loc.count()
            if count > 0:
                await loc.first.click(timeout=3000)
                return {"success": True, "message": f"点击 '{target}'"}

            return {"success": False, "message": f"未找到: {target}"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _step_fill(self, target: str, value: str) -> Dict:
        """填写表单"""
        try:
            if target.startswith('#') or target.startswith('['):
                await self.page.fill(target, value, timeout=5000)
                masked = value[:3] + "***" if len(value) > 3 else "***"
                return {"success": True, "message": f"填写 {target} = {masked}"}

            return {"success": False, "message": f"无效选择器: {target}"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _step_submit(self) -> Dict:
        """提交表单"""
        selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('登录')",
            "button:has-text('提交')",
        ]
        for sel in selectors:
            try:
                if await self.page.locator(sel).count() > 0:
                    await self.page.click(sel, timeout=3000)
                    return {"success": True, "message": f"提交: {sel}"}
            except:
                pass
        return {"success": False, "message": "未找到提交按钮"}

    async def _execute_llm_decision(self, decision: str, creds: Dict) -> str:
        """执行 LLM 的自然语言决策"""
        decision = decision.strip().lower()

        # 导航
        if '访问' in decision or '打开' in decision or 'goto' in decision:
            match = re.search(r'https?://[\w\.-]+(?:/[\w\.-]*)*', decision)
            if match:
                result = await self._tool_navigate(match.group(0))
                return str(result)

        # 点击
        if '点击' in decision or 'click' in decision:
            # 提取要点击的文本
            text_match = re.search(r'["\'""]?([^\s"\'""]+)["\'""]?', decision.replace('点击', ''))
            if text_match:
                text = text_match.group(1).strip()
                if text and len(text) > 0:
                    return await self._tool_click_by_text(text)

        # 填写/输入
        if any(k in decision for k in ['填写', '填入', '输入', 'fill', 'input', 'type']):
            # 尝试解析字段和值
            # 例如: "在用户名输入框填入admin" 或 "用户名填admin"
            for field, selector in [('用户名', '#username'), ('密码', '#password'), ('用户名', 'input[type=text]')]:
                if field in decision:
                    # 提取值
                    val_match = re.search(r'[:：为=\s]+([^\s]+)', decision)
                    if val_match:
                        value = val_match.group(1)
                    else:
                        # 尝试从 creds 获取
                        value = creds.get('username' if field == '用户名' else 'password', '')
                    if value:
                        return await self._tool_fill(selector, value)

        # 等待
        if '等待' in decision or 'wait' in decision:
            match = re.search(r'(\d+)', decision)
            seconds = int(match.group(1)) if match else 1
            return await self._tool_wait(seconds)

        # 提交/登录
        if any(k in decision for k in ['提交', '登录', 'submit', 'login']):
            return await self._try_submit()

        return f"无法理解: {decision[:50]}"

    async def _try_submit(self) -> str:
        """尝试提交表单"""
        selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button:has-text('登录')",
            "button:has-text('提交')",
            "button:has-text('确定')",
            "#login-btn",
            ".login-btn"
        ]
        for sel in selectors:
            try:
                if await self.page.locator(sel).count() > 0:
                    await self.page.click(sel, timeout=3000)
                    return f"已提交: {sel}"
            except:
                pass
        return "未找到提交按钮"

    def _build_system_prompt(self, creds: Dict) -> str:
        """构建系统提示 - 自然语言风格"""
        return f"""你是一个 Web 自动化测试助手。

你的任务是根据用户的目标，描述应该执行什么操作。
页面上的元素使用自然语言描述，如"登录按钮"、"用户名输入框"等。

## 可用操作
1. 访问/打开页面 - 直接说"访问 http://xxx"
2. 点击元素 - 说"点击登录按钮"
3. 填写表单 - 说"在用户名输入框填入admin"
4. 等待 - 说"等待2秒"
5. 提交/登录 - 说"点击提交按钮"或"登录"

## 凭证信息
用户名: {creds.get('username', '未提供')}
密码: {'已提供' if creds.get('password') else '未提供'}

## 规则
1. 用中文描述操作，自然语言即可
2. 如果缺少密码等关键信息，说明"需要用户提供密码"
3. 尽量使用页面上的实际文本（如"登录"、"提交"）
4. 不要猜测元素，选择页面上明确存在的

## 示例
用户目标: 测试登录功能
LLM: 首先点击页面上标有"登录"的链接进入登录页面
LLM: 在用户名输入框填入admin
LLM: 在密码输入框填入密码（需要用户提供）"""

    async def _get_page_state(self) -> str:
        """获取页面状态（包含 ref 映射）"""
        try:
            title = await self.page.title()
            url = self.page.url

            # 获取元素列表（用于 ref 映射）
            elements = []
            all_elements = await self.page.evaluate("""
                () => {
                    const result = [];
                    const elems = document.querySelectorAll('a, button, input, select, textarea');
                    elems.forEach((el, i) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            result.push({
                                ref: 'e' + i,
                                tag: el.tagName.toLowerCase(),
                                text: (el.innerText || el.placeholder || el.value || '').trim().slice(0, 30),
                                id: el.id || '',
                                href: el.href || '',
                                type: el.type || '',
                                placeholder: el.placeholder || ''
                            });
                        }
                    });
                    return result;
                }
            """)

            self._element_refs = {e["ref"]: e for e in elements}

            # 格式化输出
            lines = [f"URL: {url}", f"标题: {title}", ""]

            if elements:
                lines.append("可交互元素:")
                for e in elements[:20]:
                    tag = e["tag"]
                    info = e.get("text") or e.get("placeholder") or ""
                    if e.get("id"):
                        info += f" #{e['id']}"
                    if e.get("type") and e.get("type") != "submit":
                        info += f" type={e['type']}"
                    lines.append(f"  [{e['ref']}] <{tag}> {info[:40]}")

            return "\n".join(lines)

        except Exception as e:
            return f"URL: {self.page.url}\n错误: {e}"

    def _parse_tool_call(self, response: str) -> Dict:
        """解析 LLM 响应，提取工具调用"""
        # 尝试找 JSON
        start = response.find("{")
        end = response.rfind("}") + 1

        if start >= 0 and end > start:
            try:
                data = json.loads(response[start:end])
                tool = data.get("tool") or data.get("action") or data.get("name")
                input_data = data.get("input") or data.get("args") or {}

                if tool and tool != "none":
                    return {"tool": tool, "input": input_data}

                return {"tool": "none", "reason": data.get("reason", "无操作")}

            except json.JSONDecodeError:
                pass

        # 尝试解析简单格式
        if "snapshot" in response.lower():
            return {"tool": "snapshot", "input": {}}
        if "navigate" in response.lower():
            # 提取 URL
            match = re.search(r'["\'](https?://[^"\']+)["\']', response)
            target = match.group(1) if match else "/"
            return {"tool": "navigate", "input": {"target": target}}

        return {"tool": "none", "reason": "无法解析响应"}

    async def _execute_tool(self, tool_name: str, tool_input: Dict) -> Dict[str, Any]:
        """执行工具"""
        try:
            if tool_name == "snapshot":
                return await self._tool_snapshot()

            elif tool_name == "navigate":
                return await self._tool_navigate(tool_input.get("target", "/"))

            elif tool_name == "click":
                ref = tool_input.get("ref")
                desc = tool_input.get("targetDescription", "")
                return await self._tool_click(ref, desc)

            elif tool_name == "fill":
                ref = tool_input.get("ref")
                desc = tool_input.get("targetDescription", "")
                value = tool_input.get("value", "")
                return await self._tool_fill(ref, desc, value)

            elif tool_name == "select_option":
                ref = tool_input.get("ref")
                desc = tool_input.get("targetDescription", "")
                value = tool_input.get("value", "")
                return await self._tool_select_option(ref, desc, value)

            elif tool_name == "scroll":
                direction = tool_input.get("direction", "down")
                amount = tool_input.get("amount", "300")
                return await self._tool_scroll(direction, amount)

            elif tool_name == "wait":
                seconds = tool_input.get("seconds", 1)
                return await self._tool_wait(seconds)

            elif tool_name == "assert_text_present":
                text = tool_input.get("text", "")
                return await self._tool_assert_text(text)

            elif tool_name == "assert_element_visible":
                ref = tool_input.get("ref")
                desc = tool_input.get("targetDescription", "")
                return await self._tool_assert_visible(ref, desc)

            else:
                return {"success": False, "message": f"未知工具: {tool_name}"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    # ==================== 工具实现 ====================

    async def _tool_snapshot(self) -> Dict:
        """snapshot: 获取页面快照"""
        elements = []
        try:
            all_elements = await self.page.evaluate("""
                () => {
                    const result = [];
                    const elems = document.querySelectorAll('a, button, input, select, textarea');
                    elems.forEach((el, i) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            result.push({
                                ref: 'e' + i,
                                tag: el.tagName.toLowerCase(),
                                role: el.role || '',
                                text: (el.innerText || el.placeholder || el.value || '').trim().slice(0, 40),
                                id: el.id || '',
                                name: el.name || '',
                                type: el.type || '',
                                placeholder: el.placeholder || '',
                                href: el.href || '',
                                ariaLabel: el.getAttribute('aria-label') || ''
                            });
                        }
                    });
                    return result;
                }
            """)

            self._element_refs = {e["ref"]: e for e in elements}
            return {
                "success": True,
                "count": len(elements),
                "elements": elements[:30]
            }

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_navigate(self, target: str) -> Dict:
        """navigate: 导航"""
        try:
            if target.startswith("http"):
                url = target
            elif target.startswith("/"):
                url = self.base_url.rstrip("/") + target
            else:
                url = self.base_url.rstrip("/") + "/" + target.lstrip("/")

            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(1)

            return {"success": True, "url": self.page.url}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_click_by_text(self, text: str) -> str:
        """根据文本点击元素 - 自然语言"""
        try:
            print(f"   搜索: '{text}'")

            # 精确匹配
            loc = self.page.get_by_text(text, exact=True)
            count = await loc.count()
            if count > 0:
                await loc.first.click(timeout=3000)
                return f"点击 [{text}] (精确)"

            # 模糊匹配
            loc = self.page.get_by_text(text, exact=False)
            count = await loc.count()
            if count > 0:
                for i in range(count):
                    el = loc.nth(i)
                    in_content = await el.evaluate("""
                        el => {
                            let p = el.parentElement;
                            while(p) {
                                if(p.tagName === 'MAIN' || p.tagName === 'FORM') return true;
                                p = p.parentElement;
                            }
                            return false;
                        }
                    """)
                    if in_content:
                        await el.click(timeout=3000)
                        return f"点击 [{text}] (模糊+内容区)"
                await loc.first.click(timeout=3000)
                return f"点击 [{text}] (模糊)"

            # 尝试链接
            locators = self.page.locator(f'a:has-text("{text}")')
            count = await locators.count()
            if count > 0:
                await locators.first.click(timeout=3000)
                return f"点击链接 [{text}]"

            return f"未找到: '{text}'"

        except Exception as e:
            return f"点击失败: {e}"

    async def _tool_fill_by_text(self, field_name: str, value: str) -> str:
        """根据字段名填写 - 自然语言"""
        try:
            field_map = {
                '用户名': ['#username', '[name="username"]', 'input[type=text]'],
                '密码': ['#password', '[name="password"]', 'input[type=password]'],
                'email': ['#email', '[name="email"]'],
                '账号': ['#username', '#account', '[name="username"]'],
            }
            selectors = field_map.get(field_name, [f'#{field_name}', f'[name="{field_name}"]'])
            for sel in selectors:
                try:
                    if await self.page.locator(sel).count() > 0:
                        await self.page.fill(sel, value, timeout=3000)
                        return f"填写 {sel} = {value[:3]}***"
                except:
                    pass
            return f"未找到字段: {field_name}"
        except Exception as e:
            return f"填写失败: {e}"

    async def _tool_click(self, ref: Optional[str], desc: str) -> Dict:
        """click: 点击元素"""
        try:
            element = None

            # 优先用 ref
            if ref and ref in self._element_refs:
                info = self._element_refs[ref]
                elem_idx = int(ref[1:])
                elements = await self.page.evaluate("""
                    () => {
                        const elems = document.querySelectorAll('a, button, input, select, textarea');
                        return Array.from(elems).filter(el => {
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        });
                    }
                """)
                if elem_idx < len(elements):
                    element = elements[elem_idx]

            # fallback 到 desc
            if not element and desc:
                locators = self.page.get_by_text(desc, exact=False)
                count = await locators.count()
                if count > 0:
                    element = locators.first

            if element:
                await element.click(timeout=5000)
                return {"success": True, "action": "clicked"}

            return {"success": False, "message": "找不到元素"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_fill(self, ref: Optional[str], desc: str, value: str) -> Dict:
        """fill: 填写表单"""
        try:
            # 用 ref 找元素
            if ref and ref in self._element_refs:
                idx = int(ref[1:])
                selector = f"*:nth-of-type({idx})"  # 简单近似

                # 实际用 JS 找到元素并 fill
                filled = await self.page.evaluate(f"""
                    () => {{
                        const elems = document.querySelectorAll('input, textarea');
                        const visible = Array.from(elems).filter(el => {{
                            const rect = el.getBoundingClientRect();
                            return rect.width > 0 && rect.height > 0;
                        }});
                        if (elems[{idx}]) {{
                            elems[{idx}].value = '{value.replace("'", "\\'")}';
                            elems[{idx}].dispatchEvent(new Event('input', {{ bubbles: true }}));
                            return true;
                        }}
                        return false;
                    }}
                """)
                if filled:
                    return {"success": True, "action": "filled"}

            # fallback 到选择器
            if desc:
                for sel in [f"#{desc}", f"[name='{desc}']", desc]:
                    try:
                        await self.page.fill(sel, value, timeout=2000)
                        return {"success": True, "action": f"filled({sel})"}
                    except:
                        pass

            # 尝试填充所有可见 input
            inputs = await self.page.query_selector_all("input:not([type='hidden'])")
            for inp in inputs:
                try:
                    await inp.fill(value, timeout=1000)
                    return {"success": True, "action": "filled by index"}
                except:
                    pass

            return {"success": False, "message": "无法填写"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_select_option(self, ref: Optional[str], desc: str, value: str) -> Dict:
        """select_option: 选择下拉选项"""
        try:
            loc = None
            if ref and ref in self._element_refs:
                idx = int(ref[1:])
                loc = self.page.locator(f"select").nth(idx)
            elif desc:
                loc = self.page.locator(desc)

            if loc:
                await loc.select_option(value, timeout=5000)
                return {"success": True, "action": "selected", "value": value}

            return {"success": False, "message": "找不到 select 元素"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_scroll(self, direction: str, amount: str) -> Dict:
        """scroll: 滚动"""
        try:
            amount_px = int(amount) if amount.isdigit() else 300
            if direction == "down":
                await self.page.evaluate(f"window.scrollBy(0, {amount_px})")
            elif direction == "up":
                await self.page.evaluate(f"window.scrollBy(0, -{amount_px})")
            elif direction == "left":
                await self.page.evaluate(f"window.scrollBy(-{amount_px}, 0)")
            elif direction == "right":
                await self.page.evaluate(f"window.scrollBy({amount_px}, 0)")
            return {"success": True, "action": f"scrolled {direction}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_wait(self, seconds: float) -> Dict:
        """wait: 等待"""
        await asyncio.sleep(seconds)
        return {"success": True, "action": f"waited {seconds}s"}

    async def _tool_assert_text(self, text: str) -> Dict:
        """assert_text_present: 断言文本存在"""
        try:
            content = await self.page.content()
            if text in content:
                return {"success": True, "message": f"找到文本: {text[:30]}"}
            return {"success": False, "message": f"未找到文本: {text[:30]}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def _tool_assert_visible(self, ref: Optional[str], desc: str) -> Dict:
        """assert_element_visible: 断言元素可见"""
        try:
            loc = None
            if ref and ref in self._element_refs:
                idx = int(ref[1:])
                loc = self.page.locator("body").locator("> *").nth(idx)
            elif desc:
                loc = self.page.get_by_text(desc, exact=False).first

            if loc:
                await loc.wait_for(state="visible", timeout=5000)
                return {"success": True, "message": "元素可见"}
            return {"success": False, "message": "找不到元素"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ==================== 辅助方法 ====================

    def _extract_credentials(self, goal: str) -> Dict[str, str]:
        """从目标中提取凭证"""
        creds = {}
        patterns_user = [
            r'用户名[是为=\s]+([^\s]+)',
            r'username[是为=\s]+([^\s]+)',
            r'user[是为=\s]+([^\s]+)',
            r'账号[是为=\s]+([^\s]+)',
        ]
        patterns_pass = [
            r'密码[是为=\s]+([^\s]+)',
            r'password[是为=\s]+([^\s]+)',
            r'pwd[是为=\s]+([^\s]+)',
        ]

        for p in patterns_user:
            m = re.search(p, goal, re.IGNORECASE)
            if m:
                creds['username'] = m.group(1).strip()
                break

        for p in patterns_pass:
            m = re.search(p, goal, re.IGNORECASE)
            if m:
                creds['password'] = m.group(1).strip()
                break

        return creds

    def get_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        return {
            "tool_calls": len(self._tool_calls),
            "turns": len(self._tool_calls),
            "refs_mapped": len(self._element_refs),
        }


# ==================== 导出 ====================

__all__ = ["AIAgent", "TOOLS", "Tool", "build_tools_description"]