"""
AI Agent - LLM驱动的Agent执行
=============================

参考 AutoQA-Agent 的架构:
1. 使用 LLM 决定工具调用
2. MCP Server 提供浏览器工具
3. Ref-First 执行策略
4. IR 录制系统
5. Guardrails 机制
"""

import asyncio
import json
import re
import sys
from typing import Optional, Dict, Any, List

# 强制刷新输出
def flush_print(*args, **kwargs):
    print(*args, **kwargs)
    sys.stdout.flush()

from .ai_client import create_ai_client, AIClient


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
        input_schema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="navigate",
        description="导航到 URL 或相对路径",
        input_schema={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL 或路径"}},
            "required": ["url"],
        },
    ),
    Tool(
        name="click",
        description="点击元素（用 ref 引用或 targetDescription）",
        input_schema={
            "type": "object",
            "properties": {
                "targetDescription": {"type": "string", "description": "元素描述"},
                "ref": {"type": "string", "description": "元素引用如 e15"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": [],
        },
    ),
    Tool(
        name="fill",
        description="填写表单字段",
        input_schema={
            "type": "object",
            "properties": {
                "targetDescription": {"type": "string", "description": "元素描述"},
                "ref": {"type": "string", "description": "元素引用如 e15"},
                "text": {"type": "string", "description": "要填入的值"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="select_option",
        description="选择下拉选项",
        input_schema={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "元素引用"},
                "label": {"type": "string", "description": "选项标签"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": ["ref", "label"],
        },
    ),
    Tool(
        name="scroll",
        description="滚动页面",
        input_schema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "方向: up/down"},
                "amount": {"type": "number", "description": "像素数量"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": [],
        },
    ),
    Tool(
        name="wait",
        description="等待指定秒数",
        input_schema={
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "等待秒数"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": ["seconds"],
        },
    ),
    Tool(
        name="assertTextPresent",
        description="断言页面包含指定文本",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要查找的文本"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="assertElementVisible",
        description="断言元素可见",
        input_schema={
            "type": "object",
            "properties": {
                "targetDescription": {"type": "string", "description": "元素描述"},
                "ref": {"type": "string", "description": "元素引用"},
                "stepIndex": {"type": "number", "description": "步骤索引"},
            },
            "required": [],
        },
    ),
]


# ==================== AIAgent ====================

class AIAgent:
    """
    AI 驱动的 Agent - LLM 决定工具调用

    核心流程:
    1. 构建提示 (工具列表 + 页面状态 + 目标)
    2. LLM 决定调用哪个工具
    3. 执行工具并返回结果
    4. 重复直到完成

    支持:
    - IR 录制
    - Guardrails 机制
    """

    def __init__(
        self,
        page,
        base_url: str,
        ai_client: AIClient = None,
        mcp_server=None,
        ir_recorder=None,
        guardrail_counters=None,
        guardrail_limits=None,
    ):
        self.page = page
        self.base_url = base_url
        self.ai_client = ai_client or create_ai_client()
        self.mcp_server = mcp_server

        # IR 录制器
        self._ir_recorder = ir_recorder

        # Guardrails
        self._guardrail_counters = guardrail_counters
        self._guardrail_limits = guardrail_limits

        # 元素引用映射: ref -> element info
        self._element_refs: Dict[str, Dict] = {}

        # 执行统计
        self._tool_calls: List[Dict] = []
        self._max_turns = 50

    async def run(self, prompt: str, spec=None) -> Dict[str, Any]:
        """运行 Agent 执行目标"""
        print("\n" + "=" * 60)
        print("TestForge AI Agent")
        print("=" * 60)
        sys.stdout.flush()

        # 解析输入
        task = prompt.strip()
        url = self.base_url
        username = None
        password = None

        # 如果是 URL，提取出来
        if task.startswith("http"):
            url = task
            task = ""

        # 询问任务
        if not task:
            print("\n请描述您想执行的任务：")
            print("  例如：")
            print("  - 浏览博客首页")
            print("  - 登录网站")
            print("  - 点击留言板")
            print("  - 搜索文章")
            task = input("\n任务> ").strip()
            if not task:
                task = "浏览页面"

        # 如果是登录任务，询问账号密码
        is_login_task = "登录" in task
        if is_login_task:
            if not username:
                username = input("用户名> ").strip()
            if not password:
                password = input("密码> ").strip()
            if not username or not password:
                print("需要用户名和密码才能登录")
                return {"success": False, "error": "missing credentials"}

        turn = 0
        max_turns = 15

        # 导航
        print(f"\n[导航] {url}")
        sys.stdout.flush()
        result = await self._execute_tool("navigate", {"url": url}, 0)
        if result.get("ok"):
            print(f"    ✓ 已打开: {self.page.url}")
        sys.stdout.flush()

        # 登录流程（独立的确定性流程）
        if is_login_task and username and password:
            login_success = await self._run_login_flow(username, password)
            return {
                "success": login_success,
                "url": self.page.url,
            }

        # 非登录任务：使用 AI 分析循环
        url_before = self.page.url
        system_prompt = self._build_system_prompt()

        while turn < max_turns:
            turn += 1
            sys.stdout.flush()

            # 获取页面元素
            snapshot_result = await self._execute_tool("snapshot", {}, 0)
            if not snapshot_result.get("ok"):
                print(f"    ✗ 获取元素失败")
                break

            elements = snapshot_result.get("data", {}).get("elements", [])
            print(f"\n[Step {turn}] 页面元素: {len(elements)} 个")
            sys.stdout.flush()

            # 构建消息给 AI
            user_msg = f"""任务: {task}
当前页面: {self.page.url}

页面元素:
"""
            for e in elements:
                text = e.get('text', '')[:40]
                tag = e.get('tag')
                id_attr = e.get('id', '')
                placeholder = e.get('placeholder', '')
                role = e.get('role', '')
                elem_type = e.get('type', '')

                desc = f"<{tag}>"
                if text:
                    desc += f" '{text}'"
                if placeholder:
                    desc += f" placeholder='{placeholder}'"
                if id_attr:
                    desc += f" #{id_attr}"
                if role:
                    desc += f" role={role}"
                if elem_type:
                    desc += f" type={elem_type}"
                user_msg += f"- {desc}\n"

            user_msg += f"\n任务: {task}\n输出一个 JSON 工具调用。"

            print(f"    AI 分析中...")
            sys.stdout.flush()
            response = await self.ai_client.complete(user_msg, system_prompt)
            sys.stdout.flush()

            # 解析工具调用
            tool_calls = self._parse_tool_calls(response)
            if not tool_calls:
                print(f"    ⚠ 无法理解 AI 回复")
                continue

            tool_call = tool_calls[0]
            tool_name = tool_call.get("tool")
            tool_input = tool_call.get("input", {})

            # 跳过非实际操作
            if tool_name in ("done", "ask_user", "claude_action", "snapshot"):
                continue

            # 执行
            desc = tool_input.get('targetDescription', '')
            print(f"    → {tool_name}: '{desc or tool_input.get('text', '')}'")
            sys.stdout.flush()
            result = await self._execute_tool(tool_name, tool_input, turn)

            if result.get("ok"):
                print(f"    ✓ 成功")
            else:
                print(f"    ✗ {str(result.get('error', ''))[:60]}")
            sys.stdout.flush()

        print("\n" + "=" * 60)
        print(f"结果: 完成")
        print(f"URL: {self.page.url}")
        print("=" * 60)
        sys.stdout.flush()
        return {"success": True, "turns": turn}

    async def _run_login_flow(self, username: str, password: str) -> bool:
        """
        独立的登录流程
        1. 获取页面元素
        2. 找到用户名输入框 → fill
        3. 找到密码输入框 → fill
        4. 找到登录按钮 → click
        5. 检测页面变化 → 判断成功
        """
        print(f"\n[登录流程]")
        print(f"    用户名: {username}")
        print(f"    密码: {'*' * len(password)}")
        sys.stdout.flush()

        url_before = self.page.url
        username_filled = False
        password_filled = False
        login_clicked = False
        login_success = False

        for step in range(1, 8):
            # 获取当前页面元素
            snapshot = await self._execute_tool("snapshot", {}, 0)
            if not snapshot.get("ok"):
                print(f"    ✗ 获取元素失败")
                break

            elements = snapshot.get("data", {}).get("elements", [])
            print(f"\n[登录 Step {step}] 找到 {len(elements)} 个元素")
            sys.stdout.flush()

            # 阶段1: 填写用户名
            if not username_filled:
                # 找用户名输入框
                username_inputs = [
                    e for e in elements
                    if e.get('tag') == 'input' and (
                        'user' in (e.get('placeholder', '') + e.get('id', '') + e.get('name', '')).lower() or
                        e.get('type') in ('text', 'email')
                    )
                ]
                if username_inputs:
                    target = username_inputs[0].get('placeholder', '') or username_inputs[0].get('id', '') or 'username'
                    print(f"    → 填写用户名: {target}")
                    result = await self._execute_tool("fill", {
                        "targetDescription": target,
                        "text": username
                    }, step)
                    if result.get("ok"):
                        username_filled = True
                        print(f"    ✓ 用户名已填写")
                    sys.stdout.flush()
                    continue

            # 阶段2: 填写密码
            if username_filled and not password_filled:
                pwd_inputs = [
                    e for e in elements
                    if e.get('tag') == 'input' and e.get('type') in ('password', '')
                ]
                if pwd_inputs:
                    target = pwd_inputs[0].get('placeholder', '') or 'password'
                    print(f"    → 填写密码: {target}")
                    result = await self._execute_tool("fill", {
                        "targetDescription": target,
                        "text": password
                    }, step)
                    if result.get("ok"):
                        password_filled = True
                        print(f"    ✓ 密码已填写")
                    sys.stdout.flush()
                    continue

            # 阶段3: 点击登录按钮
            if username_filled and password_filled and not login_clicked:
                # 找登录按钮
                login_btns = [
                    e for e in elements
                    if e.get('tag') in ('button', 'input') and
                    e.get('type') in ('submit', 'button', '') and
                    ('登录' in (e.get('text', '') + e.get('placeholder', '')) or
                     'login' in (e.get('text', '') + e.get('placeholder', '')).lower())
                ]
                if login_btns:
                    btn_text = login_btns[0].get('text', '') or login_btns[0].get('placeholder', '') or '登录'
                    print(f"    → 点击登录按钮: '{btn_text}'")
                    sys.stdout.flush()
                    result = await self._execute_tool("click", {
                        "targetDescription": btn_text
                    }, step)
                    login_clicked = True
                    if result.get("ok"):
                        print(f"    ✓ 已点击登录")
                    sys.stdout.flush()
                    await asyncio.sleep(1.5)  # 等待页面响应

                    # 检测登录成功：页面 URL 变化
                    if self.page.url != url_before:
                        login_success = True
                        print(f"    ✓ 登录成功！页面已跳转")
                        print(f"       {url_before} → {self.page.url}")
                    else:
                        # 再次检查页面内容
                        snapshot2 = await self._execute_tool("snapshot", {}, 0)
                        if snapshot2.get("ok"):
                            new_elements = snapshot2.get("data", {}).get("elements", [])
                            if len(new_elements) != len(elements):
                                login_success = True
                                print(f"    ✓ 登录成功！页面内容已变化")
                    break
                else:
                    print(f"    ⚠ 未找到登录按钮，扫描所有按钮:")
                    for e in elements:
                        if e.get('tag') == 'button':
                            print(f"       - '{e.get('text', '')}'")

            # 如果都没找到，滚动页面
            if not (username_filled or password_filled or login_clicked):
                print(f"    滚动页面...")
                await self._execute_tool("scroll", {"direction": "down", "amount": 300}, step)
                sys.stdout.flush()

        # 最终结果报告
        print(f"\n{'='*50}")
        print(f"登录结果:")
        print(f"  用户名: {'✓' if username_filled else '✗'}")
        print(f"  密码:   {'✓' if password_filled else '✗'}")
        print(f"  登录:   {'✓' if login_clicked else '✗'}")
        print(f"  成功:   {'✓' if login_success else '✗'}")
        print(f"  URL:    {self.page.url}")
        print(f"{'='*50}")
        sys.stdout.flush()
        return login_success

    def _build_system_prompt(self) -> str:
        """构建系统提示"""
        return """你是一个网页自动化助手。

## 你的任务:
根据用户要求执行网页操作，如：点击按钮、填写表单、导航等。

## 页面元素格式:
- <input> placeholder='用户名' type='text' #username
- <input> placeholder='密码' type='password'
- <button> '登录' role=button
- <a> '登录' href='/login'

## 工具:
- navigate: 导航到URL
- snapshot: 获取页面元素（不要连续调用）
- click: 点击元素，用 targetDescription 描述要点击的内容
- fill: 填写表单，targetDescription 描述输入框，text 是要填的值
- assertTextPresent: 检查页面是否包含文本

## 操作流程示例:

### 登录流程:
1. {"tool": "click", "input": {"targetDescription": "登录"}}
2. {"tool": "fill", "input": {"targetDescription": "username", "text": "admin"}}
3. {"tool": "fill", "input": {"targetDescription": "password", "text": "pass123"}}
4. {"tool": "click", "input": {"targetDescription": "登录"}}

### 浏览流程:
1. {"tool": "click", "input": {"targetDescription": "博客"}}
2. {"tool": "click", "input": {"targetDescription": "第一篇文章"}}

## 重要:
- 每次只输出一个 JSON
- 不要重复调用 snapshot
- 完成所有操作后输出 {"tool": "done", "input": {}}

只输出 JSON，不要解释。"""

    async def _get_page_state(self) -> str:
        """获取页面状态"""
        try:
            title = await self.page.title()
            url = self.page.url

            # 获取元素列表
            elements = await self.page.evaluate("""
                () => {
                    const result = [];
                    const elems = document.querySelectorAll('a, button, input, select, textarea');
                    let idx = 0;
                    elems.forEach((el) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            result.push({
                                ref: 'e' + idx,
                                tag: el.tagName.toLowerCase(),
                                text: (el.innerText || el.placeholder || el.value || '').trim().slice(0, 30),
                                id: el.id || '',
                                type: el.type || '',
                                placeholder: el.placeholder || '',
                                role: el.role || '',
                                href: el.href || '',
                            });
                            idx++;
                        }
                    });
                    return result;
                }
            """)

            self._element_refs = {e["ref"]: e for e in elements}

            lines = [f"URL: {url}", f"标题: {title}", ""]

            if elements:
                lines.append(f"可交互元素 ({len(elements)} 个):")
                for e in elements[:30]:
                    info = e.get("text") or e.get("placeholder") or ""
                    if e.get("id"):
                        info += f" #{e['id']}"
                    if e.get("type") and e.get("type") != "submit":
                        info += f" type={e['type']}"
                    lines.append(f"  [{e['ref']}] <{e['tag']}> {info[:40]}")

            return "\n".join(lines)

        except Exception as e:
            return f"URL: {self.page.url}\n错误: {e}"

    def _parse_tool_calls(self, response: str) -> List[Dict]:
        """解析工具调用"""
        calls = []

        # 清理响应 - 移除 markdown 代码块
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            response = "\n".join(lines).strip()

        # 尝试解析 JSON 数组格式: [{"tool": ...}, {"tool": ...}]
        try:
            array_match = re.search(r'\[\s*\{[^}]*"tool"[^}]*\}\s*\]', response)
            if array_match:
                arr = json.loads(array_match.group(0))
                if isinstance(arr, list):
                    for obj in arr:
                        if isinstance(obj, dict) and obj.get("tool"):
                            calls.append(obj)
                elif isinstance(arr, dict) and arr.get("tool"):
                    calls.append(arr)
                if calls:
                    return calls
        except (json.JSONDecodeError, Exception):
            pass

        # 尝试解析单个 JSON 对象: {"tool": ...}
        try:
            obj_match = re.search(r'\{[^}]*"tool"\s*:\s*"[^"]+"[^}]*\}', response)
            if obj_match:
                obj = json.loads(obj_match.group(0))
                if obj.get("tool"):
                    calls.append(obj)
                    return calls
        except (json.JSONDecodeError, Exception):
            pass

        # 最后尝试：整个响应直接解析
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and parsed.get("tool"):
                calls.append(parsed)
            elif isinstance(parsed, list):
                for obj in parsed:
                    if isinstance(obj, dict) and obj.get("tool"):
                        calls.append(obj)
        except (json.JSONDecodeError, Exception):
            pass

        return calls

    async def _execute_tool(self, tool_name: str, tool_input: Dict, step_index: int = 0) -> Dict[str, Any]:
        """执行工具"""
        # 过滤 stepIndex 参数（AI 返回的参数可能包含这个）
        clean_input = {k: v for k, v in tool_input.items() if k not in ("stepIndex",)}

        if self.mcp_server:
            # 使用 MCP Server
            try:
                method = getattr(self.mcp_server, tool_name, None)
                if method:
                    result = await method(**clean_input)
                    return result
            except Exception as e:
                return {"ok": False, "error": str(e)}

        # 直接执行
        try:
            if tool_name == "snapshot":
                return await self._tool_snapshot(clean_input)
            elif tool_name == "navigate":
                return await self._tool_navigate(clean_input)
            elif tool_name == "click":
                return await self._tool_click(clean_input, step_index)
            elif tool_name == "fill":
                return await self._tool_fill(clean_input, step_index)
            elif tool_name == "select_option":
                return await self._tool_select_option(clean_input)
            elif tool_name == "scroll":
                return await self._tool_scroll(clean_input)
            elif tool_name == "wait":
                return await self._tool_wait(clean_input)
            elif tool_name == "assertTextPresent":
                return await self._tool_assert_text(clean_input)
            elif tool_name == "assertElementVisible":
                return await self._tool_assert_visible(clean_input, step_index)
            else:
                return {"ok": False, "error": f"未知工具: {tool_name}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_snapshot(self, input_dict: Dict) -> Dict:
        """snapshot: 获取页面快照"""
        try:
            # 使用 JavaScript 获取元素列表
            elements = await self.page.evaluate("""
                () => {
                    const result = [];
                    const elems = document.querySelectorAll('a, button, input, select, textarea');
                    let idx = 0;
                    elems.forEach((el) => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            result.push({
                                ref: 'e' + idx,
                                tag: el.tagName.toLowerCase(),
                                text: (el.innerText || el.placeholder || el.value || '').trim().slice(0, 50),
                                id: el.id || '',
                                type: el.type || '',
                                placeholder: el.placeholder || '',
                                role: el.role || '',
                            });
                            idx++;
                        }
                    });
                    return result;
                }
            """)

            self._element_refs = {e["ref"]: e for e in elements}

            lines = [f"URL: {self.page.url}", f"标题: {await self.page.title()}", ""]
            lines.append(f"可交互元素 ({len(elements)} 个):")
            for e in elements[:30]:
                info = e.get("text") or e.get("placeholder") or ""
                if e.get("id"):
                    info += f" #{e['id']}"
                lines.append(f"  [{e['ref']}] <{e['tag']}> {info[:40]}")

            return {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": False,
                "ok": True,
                "data": {"elements": elements},
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_navigate(self, input_dict: Dict) -> Dict:
        """navigate: 导航"""
        # 支持多种参数名
        url = input_dict.get("url") or input_dict.get("target") or "/"

        if not url.startswith("http"):
            url = self.base_url.rstrip("/") + "/" + url.lstrip("/")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            return {
                "content": [{"type": "text", "text": json.dumps({"ok": True, "url": self.page.url})}],
                "isError": False,
                "ok": True,
                "data": {"url": self.page.url},
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_click(self, input_dict: Dict, step_index: int = 0) -> Dict:
        """click: 点击元素"""
        ref = input_dict.get("ref")
        target = input_dict.get("targetDescription", "")

        try:
            locator = None

            if ref and ref in self._element_refs:
                # 使用 ref
                idx = int(ref[1:])
                locator = self.page.locator("body").locator("> *").nth(idx)

            if not locator and target:
                # 使用 targetDescription
                locators = [
                    self.page.get_by_text(target, exact=False),
                    self.page.get_by_role("button", name=target),
                    self.page.locator(f"#{target}"),
                ]
                for loc in locators:
                    if await loc.count() > 0:
                        locator = loc
                        break

            if locator:
                # IR 录制: prepare_for_action
                pre_result = None
                if self._ir_recorder and self._ir_recorder.is_enabled():
                    pre_result = await self._ir_recorder.prepare_for_action(
                        self.page, "click", locator, "click"
                    )

                await locator.first.click(timeout=5000)
                screenshot = await self.page.screenshot()

                # IR 录制: record_action
                if self._ir_recorder and self._ir_recorder.is_enabled():
                    await self._ir_recorder.record_action(
                        context={
                            "toolName": "click",
                            "toolInput": input_dict,
                            "stepIndex": step_index,
                            "pageUrl": self.page.url,
                        },
                        outcome={"ok": True, "data": {"clicked": True}},
                        pre_result=pre_result,
                    )

                return {
                    "content": [{"type": "text", "text": '{"ok": true}'}],
                    "isError": False,
                    "ok": True,
                    "screenshot": screenshot,
                }

            return {"ok": False, "error": f"找不到元素: {ref or target}"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_fill(self, input_dict: Dict, step_index: int = 0) -> Dict:
        """fill: 填写表单"""
        desc = input_dict.get("targetDescription", "")
        text = input_dict.get("text", "")
        ref = input_dict.get("ref")

        try:
            locator = None

            # 1. 使用 ref
            if ref and ref in self._element_refs:
                idx = int(ref[1:])
                locator = self.page.locator("body").locator("input, textarea").nth(idx)

            # 2. 使用描述查找
            if not locator and desc:
                # 尝试多种方式查找
                strategies = [
                    self.page.get_by_placeholder(desc, exact=False),
                    self.page.get_by_label(desc, exact=False),
                    self.page.locator(f"#{desc}"),
                    self.page.locator(f"[name='{desc}']"),
                    self.page.locator(f"[aria-label*='{desc}']"),
                    self.page.locator(f"input[placeholder*='{desc}']"),
                    self.page.locator(f"textarea[placeholder*='{desc}']"),
                ]

                for loc in strategies:
                    try:
                        if await loc.count() > 0:
                            locator = loc
                            break
                    except:
                        pass

            if locator:
                await locator.first.wait_for(timeout=3000)
                await locator.first.fill(text)

                # IR 录制
                if self._ir_recorder and self._ir_recorder.is_enabled():
                    pre_result = await self._ir_recorder.prepare_for_action(
                        self.page, "fill", locator, "fill"
                    )
                    await self._ir_recorder.record_action(
                        context={"toolName": "fill", "toolInput": input_dict, "stepIndex": step_index},
                        outcome={"ok": True},
                        pre_result=pre_result,
                    )

                return {"ok": True}

            return {"ok": False, "error": f"找不到输入框: {desc}"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_select_option(self, input_dict: Dict) -> Dict:
        """select_option: 选择下拉选项"""
        ref = input_dict.get("ref")
        label = input_dict.get("label", "")

        try:
            if ref and ref in self._element_refs:
                idx = int(ref[1:])
                locator = self.page.locator("select").nth(idx)
                await locator.select_option(label)
                return {"ok": True, "data": {"selected": label}}

            return {"ok": False, "error": "找不到 select 元素"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_scroll(self, input_dict: Dict) -> Dict:
        """scroll: 滚动"""
        direction = input_dict.get("direction", "down")
        amount = input_dict.get("amount", 300)

        try:
            if direction == "down":
                await self.page.evaluate(f"window.scrollBy(0, {amount})")
            else:
                await self.page.evaluate(f"window.scrollBy(0, -{amount})")
            return {"ok": True, "data": {"scrolled": direction}}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_wait(self, input_dict: Dict) -> Dict:
        """wait: 等待"""
        seconds = input_dict.get("seconds", 1)
        await asyncio.sleep(seconds)
        return {"ok": True, "data": {"waited": seconds}}

    async def _tool_assert_text(self, input_dict: Dict) -> Dict:
        """assertTextPresent: 断言文本"""
        text = input_dict.get("text", "")

        try:
            content = await self.page.content()
            if text in content:
                return {"ok": True, "data": {"found": text}}
            return {"ok": False, "error": f"文本未找到: {text}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _tool_assert_visible(self, input_dict: Dict, step_index: int = 0) -> Dict:
        """assertElementVisible: 断言元素可见"""
        ref = input_dict.get("ref")
        target = input_dict.get("targetDescription", "")

        try:
            locator = None

            if ref and ref in self._element_refs:
                idx = int(ref[1:])
                locator = self.page.locator("body").locator("> *").nth(idx)

            if not locator and target:
                locator = self.page.get_by_text(target, exact=False).first

            if locator:
                # IR 录制: prepare_for_action
                pre_result = None
                if self._ir_recorder and self._ir_recorder.is_enabled():
                    pre_result = await self._ir_recorder.prepare_for_action(
                        self.page, "assertElementVisible", locator, "assert"
                    )

                await locator.wait_for(state="visible", timeout=5000)

                # IR 录制: record_action
                if self._ir_recorder and self._ir_recorder.is_enabled():
                    await self._ir_recorder.record_action(
                        context={
                            "toolName": "assertElementVisible",
                            "toolInput": input_dict,
                            "stepIndex": step_index,
                            "pageUrl": self.page.url,
                        },
                        outcome={"ok": True, "data": {"visible": True}},
                        pre_result=pre_result,
                    )

                return {"ok": True, "data": {"visible": True}}

            return {"ok": False, "error": "元素未找到或不可见"}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _show_screenshot_info(self, screenshot: bytes) -> None:
        """显示截图信息"""
        print(f"   截图: {len(screenshot)} bytes")


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


__all__ = ["AIAgent", "TOOLS", "Tool", "build_tools_description"]