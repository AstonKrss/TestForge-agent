"""
MainAgent - 主 Agent (AI 驱动的智能测试)
========================================

核心：所有决策由 AI 模型做出，不硬编码功能名

用户说"测试笔记"、"测试发帖"、"测试写文章" ->
AI 理解意图 -> 映射到页面元素 -> 执行
"""

import asyncio
import sys
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from src.ai_client import create_ai_client, AIClient


def safe_input(prompt: str = "") -> str:
    """安全的 input"""
    try:
        return input(prompt).strip()
    except (EOFError, IOError):
        return ""


@dataclass
class PageSnapshot:
    """页面快照"""
    url: str = ""
    title: str = ""
    elements: List[Dict] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"URL: {self.url}", f"标题: {self.title}", ""]
        if self.elements:
            lines.append(f"页面元素 ({len(self.elements)} 个):")
            for e in self.elements[:40]:
                info = f"  - <{e['tag']}>"
                if e.get('text'):
                    info += f" '{e['text'][:30]}'"
                if e.get('placeholder'):
                    info += f" placeholder='{e['placeholder']}'"
                if e.get('id'):
                    info += f" #{e['id']}"
                if e.get('type') and e.get('type') not in ('', 'submit', 'button'):
                    info += f" type={e['type']}"
                if e.get('href'):
                    info += f" -> {e['href'][:50]}"
                lines.append(info)
        else:
            lines.append("(无可交互元素)")
        return "\n".join(lines)


@dataclass
class SessionState:
    """会话状态"""
    is_logged_in: bool = False
    logged_in_at: Optional[str] = None
    logged_in_user: Optional[str] = None
    current_page: str = ""
    current_url: str = ""
    tested_features: List[str] = field(default_factory=list)
    page_history: List[str] = field(default_factory=list)
    credentials: Dict[str, str] = field(default_factory=dict)

    def remember_login(self, username: str):
        self.is_logged_in = True
        self.logged_in_at = datetime.now().strftime("%H:%M:%S")
        self.logged_in_user = username

    def add_page(self, url: str, description: str = ""):
        self.current_url = url
        if url not in self.page_history:
            self.page_history.append(url)
        if description:
            self.current_page = description

    def add_tested_feature(self, feature: str):
        if feature not in self.tested_features:
            self.tested_features.append(feature)

    def to_text(self) -> str:
        lines = ["[会话状态]"]
        lines.append(f"  登录状态: {'已登录' if self.is_logged_in else '未登录'}")
        if self.is_logged_in:
            lines.append(f"  登录用户: {self.logged_in_user} ({self.logged_in_at})")
        lines.append(f"  当前页面: {self.current_page or self.current_url}")
        if self.tested_features:
            lines.append(f"  已测试: {', '.join(self.tested_features)}")
        return "\n".join(lines)


class MainAgent:
    """
    主 Agent - AI 驱动的智能测试

    核心思想：
    1. 用户说"测试xxx" -> 不管xxx是什么，都交给 AI 理解
    2. AI 分析当前页面元素，决定要点击哪个
    3. AI 执行操作，返回结果
    4. 循环直到任务完成或用户停止
    """

    def __init__(self, page):
        self.page = page
        self.ai_client = create_ai_client()
        self.current_snapshot = PageSnapshot()
        self.state = SessionState()
        self.max_turns = 30

    async def run(self):
        """运行主循环"""
        print("[TestForge CLI]")
        print("输入网站地址，AI 会帮你分析并测试")
        print("输入 q 退出, help 查看帮助, status 查看状态")
        print()

        while True:
            try:
                user_input = safe_input("(TestForge) > ")
            except (EOFError, IOError):
                break

            if not user_input:
                continue

            cmd = user_input.lower().strip()

            if cmd in ('q', 'quit', 'exit'):
                print("再见!")
                print("\n" + self.state.to_text())
                break

            if cmd in ('help', 'h', '?'):
                self._show_help()
                continue

            if cmd in ('status', 'state', '状态'):
                print("\n" + self.state.to_text())
                continue

            await self._handle_user_input(user_input)

    def _show_help(self):
        print("""
命令:
  http://xxx.com              - 访问网站
  测试登录 / 测试笔记 / 测试发帖  - 测试任意功能
  我已经登录了               - 标记已登录
  状态                      - 查看状态
  截图                      - 截图
  q                         - 退出
        """)

    async def _handle_user_input(self, user_input: str):
        """处理用户输入 - 直接丢给 AI 分析"""
        print()

        # 直接丢给 AI 处理
        await self._ai_universal_handler(user_input)

    async def _ai_universal_handler(self, user_input: str):
        """
        AI 通用处理器 - 把用户输入原封不动丢给 AI

        AI 会：
        1. 理解用户想要什么
        2. 如果有 URL，导航到那里
        3. 分析页面
        4. 决定下一步操作
        """
        print("=" * 55)
        print(f"[AI 理解中...]")
        print(f"  用户说: {user_input}")

        # 刷新页面
        await self._capture_page()
        current_url = self.current_snapshot.url
        elements = self.current_snapshot.elements

        print(f"  当前页面: {current_url}")
        print(f"  元素数: {len(elements)}")

        # 构建页面元素描述
        if elements:
            elem_list = []
            for e in elements[:20]:
                text = e.get('text', '') or e.get('placeholder', '')
                tag = e.get('tag')
                if text or tag in ('button', 'a'):
                    elem_list.append(f"- {tag}: '{text[:30]}'")
            elements_text = "\n".join(elem_list) if elem_list else "(无)"
        else:
            elements_text = "(页面还没加载)"

        # 账号信息
        cred = self.state.credentials
        username = cred.get('username', '') if cred else ''
        password = cred.get('password', '') if cred else '(已保存)'

        prompt = f"""用户说: {user_input}

当前页面: {current_url}
页面元素:
{elements_text}

用户状态: {'已登录' if self.state.is_logged_in else '未登录'}
保存的账号: {username}

请理解用户想要什么，然后执行操作。

重要:
1. 如果用户提到网址（如 www.baidu.com），自动加上 http:// 变成 http://www.baidu.com
2. 如果页面没加载，先导航到用户提到的页面
3. 分析页面元素
4. 如果用户说要测试什么，执行测试
5. 如果用户只是访问网站，分析页面后告诉用户可以测试什么

输出 JSON 格式:
{{"action": "navigate", "url": "http://www.baidu.com"}} 或
{{"action": "analyze"}} 或
{{"action": "test", "steps": [{{"action": "click", "target": "登录"}}]}}

只输出 JSON，不要解释。"""

        try:
            sys.stdout.flush()
            response = await self.ai_client.complete(prompt, "")
            print(f"\n  AI 回应: {response.strip()[:200]}")

            # 解析 AI 回应
            action_data = self._parse_ai_response(response)
            action_type = action_data.get('action', '')

            print(f"\n  执行: {action_type}")

            # 执行 AI 的决定
            if action_type == 'navigate' and action_data.get('url'):
                url = action_data['url']
                print(f"\n[导航] {url}")
                try:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # 等待更长时间让页面加载
                    await asyncio.sleep(3)
                    await self._capture_page()
                    print(f"  完成: {self.current_snapshot.url}")
                    print(f"  元素: {len(self.current_snapshot.elements)} 个")

                    # 导航后分析页面
                    if self.current_snapshot.elements:
                        await self._analyze_page_ai()
                    else:
                        print("  ⚠ 页面元素为空，可能还在加载")
                except Exception as e:
                    print(f"  ✗ 导航失败: {e}")

            elif action_type == 'analyze' or not action_data.get('steps'):
                await self._analyze_page_ai()
                await self._ask_what_to_test()

            elif action_type == 'ask_credentials':
                await self._ask_for_credentials()

            elif action_data.get('steps'):
                # 执行测试步骤
                for step in action_data['steps']:
                    act = step.get('action', '')
                    target = step.get('target', '')
                    value = step.get('value', '')

                    if act == 'click' and target:
                        print(f"\n  → 点击: {target}")
                        await self._ai_click(target)
                    elif act == 'fill' and target:
                        v = value or username or safe_input(f"  输入 {target}: ").strip()
                        print(f"\n  → 填写: {target} = {v[:10]}***")
                        await self._ai_fill(target, v)

                    await asyncio.sleep(1)
                    await self._capture_page()

        except Exception as e:
            print(f"  AI 处理失败: {e}")

    def _parse_ai_response(self, response: str) -> dict:
        """解析 AI 的 JSON 回应"""
        import json

        response = response.strip()

        # 去掉 markdown 代码块
        if response.startswith("```"):
            lines = response.split("\n")
            lines = [l for l in lines if not l.startswith("```") and not l.startswith("json")]
            response = "\n".join(lines).strip()

        # 找 JSON 对象（支持嵌套）
        start = response.find('{')
        if start == -1:
            return {}

        # 找配对的括号
        depth = 0
        end = start
        for i, c in enumerate(response[start:], start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        json_str = response[start:end]
        try:
            return json.loads(json_str)
        except:
            return {}

    def _extract_url(self, text: str) -> Optional[str]:
        match = re.search(r'https?://[^\s<>"\']+', text)
        return match.group(0) if match else None

    async def _handle_state_update(self, user_input: str):
        """处理状态更新"""
        print("[状态更新]")
        self.state.is_logged_in = True
        self.state.logged_in_at = datetime.now().strftime("%H:%M:%S")
        self.state.logged_in_user = "用户"

        await self._capture_page()
        print(f"  ✓ 已标记为已登录")
        print(f"  当前URL: {self.current_snapshot.url}")
        await self._describe_current_page()

    async def _describe_current_page(self):
        """描述当前页面"""
        buttons = [e.get('text', '')[:25] for e in self.current_snapshot.elements if e.get('tag') == 'button' and e.get('text')]
        links = [e.get('text', '')[:25] for e in self.current_snapshot.elements if e.get('tag') == 'a' and e.get('text')]

        if buttons:
            print(f"  按钮: {', '.join(buttons[:5])}")
        if links:
            print(f"  链接: {', '.join(links[:5])}")

    async def _goto_and_analyze(self, url: str):
        """导航到网站"""
        print("=" * 55)
        print(f"[1] 导航到 {url}")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # 等待更长时间让页面完全加载
            await asyncio.sleep(2)

            await self._capture_page()
            self.state.add_page(self.current_snapshot.url)

            print(f"  标题: {self.current_snapshot.title}")
            print(f"  网址: {self.current_snapshot.url}")
            print(f"  元素: {len(self.current_snapshot.elements)} 个")

            # 如果元素太少，尝试滚动页面后再捕获
            if len(self.current_snapshot.elements) < 5:
                print(f"  元素较少，尝试滚动页面...")
                await self.page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(0.5)
                await self._capture_page()
                print(f"  刷新后元素: {len(self.current_snapshot.elements)} 个")

            await self._analyze_page_ai()

        except Exception as e:
            print(f"  ✗ 导航失败: {e}")

    async def _capture_page(self):
        """捕获页面"""
        try:
            self.current_snapshot.url = self.page.url
            self.current_snapshot.title = await self.page.title()

            elements = await self.page.evaluate("""
                () => {
                    const result = [];
                    // 扩大选择器范围
                    const selectors = 'a, button, input, select, textarea, [role="button"], [role="link"]';
                    document.querySelectorAll(selectors).forEach((el, idx) => {
                        // 检查元素是否可见
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const isVisible = rect.width > 0 && rect.height > 0 &&
                                         style.display !== 'none' && style.visibility !== 'hidden';

                        if (isVisible) {
                            result.push({
                                ref: idx,
                                tag: el.tagName.toLowerCase(),
                                text: (el.innerText || el.placeholder || el.value || '').trim().slice(0, 50),
                                id: el.id || '',
                                name: el.name || '',
                                placeholder: el.placeholder || '',
                                type: el.type || '',
                                href: el.href || (el.closest('a')?.href || ''),
                                role: el.role || '',
                                className: el.className || '',
                            });
                        }
                    });
                    return result;
                }
            """)
            self.current_snapshot.elements = elements
        except Exception as e:
            print(f"  捕获元素失败: {e}")
            self.current_snapshot.elements = []

    async def _analyze_page_ai(self):
        """AI 分析页面"""
        print()
        print("[2] AI 分析页面...")

        state_context = f"\n用户状态: {'已登录' if self.state.is_logged_in else '未登录'}"
        context = self.current_snapshot.to_text() + state_context

        prompt = f"""你是 TestForge AI 助手。你要做的是自动测试功能。首先分析当前页面，理解它的功能和结构。
才能根据用户的测试需求，建议可以测试什么功能。然后根据用户的测试需求，分析页面上有哪些功能入口可以测试，并建议用户可以测试什么。
并理解用户测试需求做出规划用中文回答:

{context}

请输出:
1. 页面功能: (登录/注册/搜索/博客/电商/笔记/发帖等)
2. 可操作的功能入口
3. 根据用户状态建议可以测试什么

只输出简短分析，3-5行。"""

        try:
            sys.stdout.flush()
            response = await self.ai_client.complete(prompt, "")
            for line in response.strip().split('\n')[:5]:
                if line.strip():
                    print(f"  {line.strip()}")
        except Exception as e:
            print(f"  分析失败")

        print()

    async def _ask_what_to_test(self):
        """询问要测试什么"""
        print("-" * 55)
        print(self.state.to_text())
        answer = safe_input("请问要测试什么功能?\n  > ").strip()
        if answer:
            await self._ai_driven_test(answer)

    async def _ai_driven_test(self, task: str):
        """
        AI 驱动的测试 - 核心功能

        用户说"测试一下这个网站" -> AI 分析页面 -> 列出可测试功能
        """
        print("=" * 55)

        # 刷新页面状态
        await self._capture_page()
        print(f"  当前: {self.current_snapshot.url}")
        print(f"  元素: {len(self.current_snapshot.elements)} 个")

        # 如果任务模糊，询问用户要测试什么
        vague_keywords = ['测试一下', '测试', '看看', '浏览', '探索']
        if any(kw in task.lower() for kw in vague_keywords) or not task:
            print(f"\n[AI 分析页面功能]")
            await self._analyze_page_ai()
            print()
            answer = safe_input("请告诉我你想测试什么功能?\n  > ").strip()
            if answer:
                await self._ai_driven_test(answer)
            return

        print(f"[AI 测试] {task}")

        # 询问账号密码（如果需要）
        needs_auth = await self._check_needs_credentials(task)
        if needs_auth and not self.state.credentials:
            await self._ask_for_credentials()

        # AI 规划测试步骤
        plan = await self._ai_plan_test(task)

        if not plan:
            print("  ✗ AI 无法理解测试任务")
            print("  请告诉我更具体的测试内容，比如：")
            print("  - 测试登录功能")
            print("  - 测试搜索功能")
            print("  - 点击文章")
            return

        # 执行计划
        for i, step in enumerate(plan):
            print()
            print(f"[Step {i+1}] {step['action']}: {step.get('target', '')}")

            try:
                await self._execute_step(step)

                await asyncio.sleep(1)
                await self._capture_page()
                print(f"  ✓ 完成")
                print(f"  当前: {self.current_snapshot.url}")

            except Exception as e:
                print(f"  ✗ 失败: {e}")

        print()
        self.state.add_tested_feature(task[:20])

    async def _check_needs_credentials(self, task: str) -> bool:
        """检查任务是否需要认证"""
        task_lower = task.lower()

        # 需要登录的任务
        auth_keywords = ['登录', 'login', '注册', 'register', '写', '发布', 'post', 'create',
                        '管理', 'admin', 'dashboard', '设置', 'setting']

        for kw in auth_keywords:
            if kw in task_lower:
                return True

        # 如果任务要求已登录状态
        if self.state.is_logged_in:
            return False

        return False

    async def _ask_for_credentials(self):
        """询问账号密码"""
        print()
        print("[需要登录]")
        username = safe_input("  用户名: ").strip()
        password = safe_input("  密码: ").strip()

        if username and password:
            self.state.credentials['username'] = username
            self.state.credentials['password'] = password
            print("  ✓ 已记录")
        else:
            print("  ✗ 需要用户名和密码")

    async def _ai_plan_test(self, task: str) -> List[Dict]:
        """
        AI 规划测试步骤

        核心：让 AI 理解任务，分析页面元素，决定操作
        """
        await self._capture_page()

        # 构建元素描述
        key_elements = []
        for e in self.current_snapshot.elements[:25]:
            text = e.get('text', '') or e.get('placeholder', '')
            tag = e.get('tag')
            elem_type = e.get('type', '')
            elem_id = e.get('id', '')
            placeholder = e.get('placeholder', '')

            info = f"<{tag}"
            if elem_type and elem_type not in ('submit', 'button', ''):
                info += f" type={elem_type}"
            if placeholder:
                info += f" placeholder='{placeholder}'"
            if elem_id:
                info += f" #{elem_id}"
            if text and text != placeholder:
                info += f" text='{text[:25]}'"
            info += ">"
            key_elements.append(info)

        elements_desc = "\n".join(key_elements) if key_elements else "(无可交互元素)"

        # 用户账号
        cred = self.state.credentials
        username = cred.get('username', '') if cred else ''
        password = cred.get('password', '') if cred else ''

        prompt = f"""你是 TestForge 自动化测试 Agent。你需要分析用户需求，结合当前页面元素，制定测试计划。

【你的工具】
- click: 点击按钮或链接，target 是按钮上的文字
- fill: 填写表单，target 是输入框的 placeholder 或 id，value 是填写的内容
- navigate: 导航到新页面

【当前页面元素】
{elements_desc}

【用户任务】
{task}

【账号信息】
用户名: {username}
密码: {password}

【任务分析过程】
1. 理解用户想要测试什么功能
2. 在页面元素中找出相关元素：
   - 找登录按钮: 搜索"登录"、"login"、"sign"等
   - 找输入框: 看 placeholder 是 "username"、"password"、"账号"、"密码" 等
   - 找提交按钮: type=submit 的按钮
3. 如果元素不明显，尝试模糊匹配（如 placeholder 包含"user"可能是用户名）
4. 制定步骤：通常是 click 按钮 → fill 输入框 → fill 密码 → click 提交

【输出格式】
输出 JSON 数组，每步包含:
- action: "click" 或 "fill"
- target: 元素的精确文本（按钮文字或 placeholder）
- value: 填写值（仅 fill 需要）

【示例】
用户任务: 测试登录
输出: [{{"action": "click", "target": "登录"}}, {{"action": "fill", "target": "username", "value": "{username}"}}, {{"action": "fill", "target": "password", "value": "{password}"}}, {{"action": "click", "target": "登录"}}]

用户任务: 测试搜索
页面有 placeholder="搜索" 的输入框和 "搜索" 按钮
输出: [{{"action": "click", "target": "搜索"}}, {{"action": "fill", "target": "搜索", "value": "关键词"}}]

只输出 JSON，不要其他内容。"""

        try:
            sys.stdout.flush()
            response = await self.ai_client.complete(prompt, "")
            print(f"  AI 规划中...")
            plan = self._parse_plan(response)
            if plan:
                print(f"  计划 {len(plan)} 步")
            return plan
        except Exception as e:
            print(f"  规划失败: {e}")
            return []

    def _parse_plan(self, response: str) -> List[Dict]:
        """解析 AI 计划"""
        import json

        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            response = "\n".join(lines).strip()

        match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass

        return []

    async def _execute_step(self, step: Dict):
        """执行单个测试步骤"""
        action = step.get('action', '')
        target = step.get('target', '')
        value = step.get('value', '')

        if action == 'click':
            await self._ai_click(target)
        elif action == 'fill':
            await self._ai_fill(target, value)
        elif action == 'navigate':
            await self._ai_navigate(target)
        elif action == 'ask_user':
            return step  # 让调用者处理

    async def _ai_click(self, target: str):
        """
        AI 点击 - 智能匹配元素

        1. 先精确匹配
        2. 再模糊匹配
        3. 最后让 AI 选择
        """
        if not target:
            return

        elements = self.current_snapshot.elements
        if not elements:
            print(f"  页面无元素")
            return

        target_clean = target.strip()
        target_lower = target_clean.lower()

        # 1. 精确匹配文本
        for e in elements:
            text = (e.get('text', '') + e.get('placeholder', '')).strip()
            if text and text.lower() == target_lower:
                print(f"  点击: '{text}'")
                await self._click_element(e)
                return

        # 2. placeholder/id 包含匹配
        for e in elements:
            placeholder = e.get('placeholder', '').lower()
            elem_id = e.get('id', '').lower()
            text = e.get('text', '').lower()

            # target 包含在 placeholder/id/文本 中
            if (placeholder and target_lower in placeholder) or \
               (elem_id and target_lower in elem_id) or \
               (text and target_lower in text):
                display = e.get('text') or e.get('placeholder') or f"#{e.get('id')}"
                print(f"  点击: '{display}'")
                await self._click_element(e)
                return

        # 3. 反向包含 (元素文本在 target 中)
        for e in elements:
            text = (e.get('text', '') or e.get('placeholder', '')).strip().lower()
            if text and len(text) > 1 and text in target_lower:
                display = e.get('text') or e.get('placeholder')
                print(f"  点击: '{display}'")
                await self._click_element(e)
                return

        # 4. 都没找到，列出可用元素
        print(f"  ✗ 未找到: '{target}'")
        print(f"  页面元素:")

        buttons = [e for e in elements if e.get('tag') in ('button', 'a')]
        inputs = [e for e in elements if e.get('tag') == 'input' and e.get('type') != 'submit']

        if buttons[:5]:
            print(f"    按钮/链接:")
            for e in buttons[:5]:
                text = e.get('text', '') or e.get('placeholder', '')
                print(f"      - '{text}'")
        if inputs[:3]:
            print(f"    输入框:")
            for e in inputs[:3]:
                ph = e.get('placeholder', '')
                tid = e.get('id', '')
                print(f"      - placeholder='{ph}' #{tid}")

    async def _ai_fill(self, target: str, value: str):
        """AI 填写表单"""
        # 获取默认值
        if not value:
            target_lower = target.lower()
            if 'user' in target_lower or 'name' in target_lower or '账号' in target_lower:
                value = self.state.credentials.get('username', '')
            elif 'pass' in target_lower or '密码' in target_lower:
                value = self.state.credentials.get('password', '')

        if not value:
            value = safe_input(f"  输入 {target}: ").strip()

        print(f"  填写: {target} = {value[:10]}***")

        # 找到输入框
        target_lower = target.lower()
        elements = self.current_snapshot.elements

        # 策略1: placeholder 精确匹配
        for e in elements:
            if e.get('tag') != 'input':
                continue
            placeholder = e.get('placeholder', '').lower()
            if placeholder and target_lower in placeholder:
                elem_id = e.get('id')
                if elem_id:
                    await self.page.locator(f"#{elem_id}").fill(value)
                    return

        # 策略2: id 精确匹配
        for e in elements:
            if e.get('tag') != 'input':
                continue
            elem_id = e.get('id', '').lower()
            if elem_id and (target_lower in elem_id or elem_id in target_lower):
                elem_id = e.get('id')
                await self.page.locator(f"#{elem_id}").fill(value)
                return

        # 策略3: name 属性匹配
        for e in elements:
            if e.get('tag') != 'input':
                continue
            name = e.get('name', '').lower()
            if name and target_lower in name:
                elem_id = e.get('id')
                if elem_id:
                    await self.page.locator(f"#{elem_id}").fill(value)
                    return
                name = e.get('name')
                await self.page.locator(f"[name='{name}']").fill(value)
                return

        # 策略4: 类型匹配（password 字段）
        for e in elements:
            if e.get('tag') != 'input':
                continue
            if e.get('type') == 'password':
                elem_id = e.get('id')
                if elem_id:
                    await self.page.locator(f"#{elem_id}").fill(value)
                    return

        print(f"  ✗ 未找到输入框: {target}")

    async def _ai_navigate(self, url: str):
        """AI 导航"""
        if not url.startswith('http'):
            url = self.state.current_url.rsplit('/', 1)[0] + '/' + url

        await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)

    async def _click_element(self, elem: Dict):
        """点击元素"""
        tag = elem.get('tag')
        text = elem.get('text', '') or elem.get('placeholder', '')
        elem_id = elem.get('id', '')

        try:
            if tag == 'a' and elem_id:
                await self.page.locator(f"#{elem_id}").click(timeout=5000)
            elif text:
                locators = [
                    self.page.get_by_text(text, exact=False),
                    self.page.get_by_role('button', name=text),
                ]
                for loc in locators:
                    if await loc.count() > 0:
                        await loc.first.click(timeout=5000)
                        return
        except Exception as e:
            raise Exception(f"点击失败: {e}")


__all__ = ["MainAgent", "PageSnapshot", "SessionState"]