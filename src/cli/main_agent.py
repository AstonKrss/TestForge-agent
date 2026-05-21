"""
MainAgent - 主对话 Agent
=========================

职责：
- 与用户进行自然语言对话
- 理解用户意图
- 协调 ExecutorAgent 执行操作
- 管理会话上下文和状态
- 询问用户缺失信息（如账号密码）
- 展示结果

核心流程：
用户 → MainAgent → ExecutorAgent → 工具执行
                  ↓
            返回结果/询问用户
                  ↓
用户 ← MainAgent ←
"""

import asyncio
import re
import getpass
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from ..ai_client import create_ai_client, AIClient
from .executor_agent import ExecutorAgent, ExecutorResult, ResultType
from .agent_plan import AgentAction, AgentPlan, extract_json_payload, normalize_agent_plan
from .planning_agent import PlanningAgent
from .task_state import TaskState, extract_comment_text, extract_search_keyword
from .verifier_agent import VerifierAgent


# ─────────────────────────────────────────────────────────────────────────────
# 会话上下文
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionContext:
    """会话上下文"""
    # 页面状态
    current_url: str = ""
    current_title: str = ""
    page_history: List[str] = field(default_factory=list)

    # 认证状态
    is_logged_in: bool = False
    logged_in_user: Optional[str] = None

    # 已测试的功能
    tested_features: List[str] = field(default_factory=list)

    # 已发现的页面功能
    discovered_features: List[str] = field(default_factory=list)

    # 凭证
    credentials: Dict[str, str] = field(default_factory=dict)

    # 分层记忆
    current_task_state: Dict[str, Any] = field(default_factory=dict)
    last_failed_action: Dict[str, Any] = field(default_factory=dict)
    known_feature_map: Dict[str, Any] = field(default_factory=dict)
    known_selectors: Dict[str, str] = field(default_factory=dict)

    def add_page(self, url: str, title: str = ""):
        self.current_url = url
        if title:
            self.current_title = title
        if url and url not in self.page_history:
            self.page_history.append(url)

    def set_credentials(self, username: str = "", password: str = ""):
        if username:
            self.credentials["username"] = username
        if password:
            self.credentials["password"] = password

    def add_tested_feature(self, feature: str):
        if feature and feature not in self.tested_features:
            self.tested_features.append(feature)

    def add_discovered_feature(self, feature: str):
        if feature and feature not in self.discovered_features:
            self.discovered_features.append(feature)

    def to_summary(self) -> str:
        lines = []
        lines.append(f"当前页面: {self.current_url or '(未打开)'}")
        if self.is_logged_in:
            lines.append(f"登录状态: 已登录 {self.logged_in_user or ''}")
        if self.discovered_features:
            lines.append(f"发现功能: {', '.join(self.discovered_features)}")
        if self.tested_features:
            lines.append(f"已测试: {', '.join(self.tested_features)}")
        return " | ".join(lines)


@dataclass
class DelegatedStep:
    """A visible plan step assigned by MainAgent to a logical sub-agent."""

    agent: str
    task: str


# ─────────────────────────────────────────────────────────────────────────────
# MainAgent
# ─────────────────────────────────────────────────────────────────────────────

class MainAgent:
    """
    主对话 Agent

    使用方式：
        main_agent = MainAgent(page=page, ai_client=ai_client)
        await main_agent.run()
    """

    MAX_REPLAN_ROUNDS = 10

    def __init__(self, page, ai_client: AIClient = None):
        self.page = page
        self.ai_client = ai_client or create_ai_client()
        self.executor = ExecutorAgent(page, self.ai_client)
        self.planning_agent = PlanningAgent(self.ai_client)
        self.verifier = VerifierAgent()
        self.context = SessionContext()
        self._running = False
        self._last_action_requested_replan = False
        self._current_task_state: Optional[TaskState] = None

    # ─── 对话入口 ─────────────────────────────────────────────────────────────

    async def run(self):
        """运行主对话循环"""
        self._running = True

        print()
        print("=" * 60)
        print("  TestForge CLI - AI 自动化测试")
        print("=" * 60)
        print()
        print("  输入网站地址，AI 帮你分析并测试")
        print("  输入 help 查看帮助，status 查看状态，q 退出")
        print()

        while self._running:
            try:
                user_input = self._safe_input("(TestForge) > ")
            except (EOFError, IOError):
                break

            if not user_input.strip():
                continue

            cmd = user_input.strip().lower()
            if cmd in ("q", "quit", "exit", "退出"):
                self._running = False
                self._show_summary()
                break

            if cmd in ("help", "h", "帮助"):
                self._show_help()
                continue

            if cmd in ("status", "state", "状态"):
                print()
                print(f"  {self.context.to_summary()}")
                continue

            if cmd in ("screenshot", "截图"):
                b64 = await self.executor.get_screenshot_base64()
                if b64:
                    print(f"  截图已获取 ({len(b64)} bytes)")
                continue

            # 处理用户输入
            await self._handle_user_input(user_input)

    def _safe_input(self, prompt: str = "") -> str:
        try:
            return input(prompt).strip()
        except (EOFError, IOError):
            return "q"

    # ─── 命令处理 ──────────────────────────────────────────────────────────────

    async def _handle_user_input(self, user_input: str):
        """处理用户输入：统一交给 AI 分析意图"""
        print()
        print(f"[用户] {user_input}")

        # 测试用例文件是本地路径，先确定性处理；其它自然语言交给主 Agent 规划。
        spec_path = self._extract_spec_path(user_input)
        if spec_path:
            await self._run_spec_file(spec_path)
            return

        credentials = self._extract_credentials(user_input)
        if not credentials and await self._handle_credential_or_retry(user_input):
            return

        await self._run_planned_task(user_input, credentials=credentials)

    async def _ask_planning_agent(self, user_input: str) -> Optional[AgentPlan]:
        """Ask PlanningAgent for the next structured plan."""
        snapshot_result = await self.executor.get_snapshot()
        elements = snapshot_result.data.get("elements", []) if snapshot_result.type == ResultType.SUCCESS else []

        try:
            return await self.planning_agent.plan(
                user_input,
                current_url=self.context.current_url or getattr(self.page, "url", ""),
                current_title=self.context.current_title,
                elements=elements,
                context_summary=self.context.to_summary(),
            )
        except Exception as e:
            fallback = self._fallback_plan(user_input)
            if fallback:
                print(f"  PlanningAgent 暂时失败，使用安全兜底计划: {e}")
                return normalize_agent_plan(fallback)
            print(f"  PlanningAgent 规划失败: {e}")
            return None

    async def _run_planned_task(self, task: str, credentials: Optional[Dict[str, str]] = None):
        """Run a user task with observe-plan-act-verify-replan loop."""
        remaining_task = task
        creds_to_record = credentials
        self._current_task_state = TaskState.from_user_input(task)
        self.context.current_task_state = self._current_task_state.to_dict()

        for round_index in range(1, self.MAX_REPLAN_ROUNDS + 1):
            if round_index > 1:
                print("\n[PlanningAgent] 任务还没完成，基于当前页面继续规划...")

            plan = await self._ask_planning_agent(remaining_task)
            if not plan:
                return

            plan = self._apply_plan_guardrails(plan, remaining_task)
            ok = await self._execute_plan(plan, credentials=creds_to_record)
            creds_to_record = None

            status = await self._evaluate_task_completion(task)
            if status.get("state"):
                self.context.current_task_state = status["state"]
            if status.get("done"):
                print(f"  ✓ {status.get('summary', '任务已完成')}")
                return

            if not ok:
                if self._last_action_requested_replan:
                    remaining_task = status.get("remaining") or remaining_task
                    continue
                return

            if plan.needs_replan_after_navigation or self._last_action_requested_replan or status.get("should_continue"):
                remaining_task = plan.post_navigation_task or status.get("remaining") or remaining_task
                continue

            break

        status = await self._evaluate_task_completion(task)
        if not status.get("done") and status.get("summary"):
            print(f"  ! {status['summary']}")

    def _apply_plan_guardrails(self, plan: AgentPlan, user_input: str) -> AgentPlan:
        """
        Apply safety guardrails to a PlanningAgent plan.

        This is not the planner. It only validates and repairs dangerous/invalid
        plan details such as a URL that accidentally includes natural language.
        """
        fallback_url = self._extract_url(user_input)
        conditional_login = self._looks_like_conditional_login(user_input)
        explicit_login = self._looks_like_explicit_login_test(user_input)
        if conditional_login and not explicit_login:
            plan.actions = [action for action in plan.actions if action.type != "test_login"]

        has_navigate = False
        for action in plan.actions:
            if action.type == "navigate":
                has_navigate = True
                action.url = self._prepare_url(action.url or fallback_url or "")

        if fallback_url and not has_navigate and not self._has_open_page():
            plan.actions.insert(0, AgentAction(type="navigate", url=fallback_url, description="打开目标网站"))

        if fallback_url and self._looks_like_login_request(user_input) and not (conditional_login and not explicit_login):
            if not any(action.type == "test_login" for action in plan.actions):
                plan.actions.append(AgentAction(type="test_login", description="测试登录功能"))

        return plan

    def _print_delegation_plan(self, steps: List[DelegatedStep]):
        """Show the user how MainAgent will delegate the work."""
        if not steps:
            return
        if steps[0].agent != "PlanningAgent":
            steps = [
                DelegatedStep("PlanningAgent", "理解用户需求，拆分步骤，并分配给下层 agent"),
                *steps,
            ]
        print("\n[主Agent规划]")
        for index, step in enumerate(steps, 1):
            print(f"  {index}. {step.agent}: {step.task}")
        print("\n[开始执行]")

    def _build_initial_request_plan(
        self,
        user_input: str,
        url: Optional[str],
        credentials: Dict[str, str],
    ) -> List[DelegatedStep]:
        """Build a visible plan for deterministic high-signal inputs."""
        steps: List[DelegatedStep] = []

        if credentials:
            fields = []
            if credentials.get("username"):
                fields.append("账号")
            if credentials.get("password"):
                fields.append("密码")
            steps.append(DelegatedStep("MainAgent", f"记录用户提供的{'+'.join(fields)}，后续提交时使用"))

        if url:
            steps.append(DelegatedStep("BrowserAgent", f"打开目标网站 {url}"))
            steps.append(DelegatedStep("ExplorerAgent", "读取页面标题、URL、可交互元素和功能入口"))

        if self._looks_like_login_request(user_input):
            steps.append(DelegatedStep("AuthAgent", "定位登录入口；如果不在登录页就进入登录页"))
            steps.append(DelegatedStep("AuthAgent", "识别用户名、密码、验证码等必填字段"))
            if credentials:
                steps.append(DelegatedStep("AuthAgent", "使用已记录凭证填写并提交登录表单"))
            else:
                steps.append(DelegatedStep("MainAgent", "向用户询问缺失的账号、密码或验证码"))
            steps.append(DelegatedStep("VerifierAgent", "检查错误提示、登录后标识和 URL，确认登录是否成功"))
            steps.append(DelegatedStep("ExplorerAgent", "登录成功后重新分析可继续测试的功能"))
        elif url and self._has_post_navigation_task(user_input):
            steps.append(DelegatedStep("PlanningAgent", "基于打开后的页面快照，继续规划用户要求的功能测试"))
            steps.append(DelegatedStep("BrowserAgent", "按规划执行点击、填写、搜索、点赞等页面动作"))
            steps.append(DelegatedStep("VerifierAgent", "检查关键动作是否完成，并报告结果"))

        return steps

    def _build_plan_steps(self, plan: AgentPlan, credentials: Optional[Dict[str, str]] = None) -> List[DelegatedStep]:
        """Convert a normalized model plan into visible delegated steps."""
        steps: List[DelegatedStep] = []
        credentials = credentials or {}

        if credentials:
            fields = []
            if credentials.get("username"):
                fields.append("账号")
            if credentials.get("password"):
                fields.append("密码")
            steps.append(DelegatedStep("MainAgent", f"记录用户提供的{'+'.join(fields)}，后续提交时使用"))

        if plan.intent == "test_login":
            steps.extend(self._build_initial_request_plan("登录", "", {}))
            return steps
        if plan.intent == "test_register":
            steps.extend([
                DelegatedStep("AuthAgent", "查找并进入注册入口"),
                DelegatedStep("ExplorerAgent", "识别注册表单字段"),
                DelegatedStep("MainAgent", "询问用户缺失的注册信息"),
                DelegatedStep("VerifierAgent", "检查注册结果或错误提示"),
            ])
            return steps
        if plan.intent == "analyze" and not plan.actions:
            steps.append(DelegatedStep("ExplorerAgent", "读取当前页面元素并总结可测试功能"))
            return steps
        if plan.intent == "ask_user":
            steps.append(DelegatedStep("MainAgent", f"向用户询问缺失信息: {', '.join(plan.ask_fields) or '未知字段'}"))
            return steps

        for action in plan.actions:
            if action.type == "navigate":
                steps.append(DelegatedStep("BrowserAgent", f"打开 {action.url}"))
                steps.append(DelegatedStep("ExplorerAgent", "读取页面状态并返回元素快照"))
            elif action.type == "click":
                target = action.target_desc or action.description or action.target_ref
                steps.append(DelegatedStep("BrowserAgent", f"点击 {target}"))
            elif action.type == "fill":
                target = action.target_desc or action.description or action.target_ref
                steps.append(DelegatedStep("BrowserAgent", f"填写 {target}"))
            elif action.type in ("assert_text", "assert_visible"):
                target = action.expected or action.description or action.target_desc or action.target_ref
                steps.append(DelegatedStep("VerifierAgent", f"验证 {target}"))
            elif action.type == "scroll":
                steps.append(DelegatedStep("BrowserAgent", f"滚动页面 {action.direction} {action.amount}px"))
            elif action.type == "wait":
                steps.append(DelegatedStep("BrowserAgent", f"等待 {action.seconds:g} 秒"))
            elif action.type == "analyze":
                steps.append(DelegatedStep("ExplorerAgent", "分析当前页面可测试功能"))
            elif action.type.startswith("extract_"):
                steps.append(DelegatedStep("ExplorerAgent", f"抽取页面结构: {action.type}"))
            elif action.type == "test_login":
                steps.extend(self._build_initial_request_plan("登录", "", {}))
            elif action.type == "ask_user":
                steps.append(DelegatedStep("MainAgent", f"向用户询问缺失信息: {', '.join(action.ask_fields) or '未知字段'}"))

        if plan.needs_replan_after_navigation:
            task = plan.post_navigation_task or "剩余用户任务"
            steps.append(DelegatedStep("PlanningAgent", f"页面打开后继续规划: {task}"))

        return steps

    def _format_elements_for_prompt(self, elements: List[Dict[str, Any]], limit: int = 40) -> str:
        """Format a ref-first page snapshot for the main planner."""
        if not elements:
            return "(当前无页面或页面暂无可操作元素)"

        lines = []
        for e in elements[:limit]:
            bits = [
                f"{e.get('ref')}: <{e.get('tag', '')}>",
                f"text='{(e.get('text') or '')[:60]}'",
            ]
            for key in ("placeholder", "label", "ariaLabel", "id", "name", "type", "role"):
                value = e.get(key)
                if value:
                    bits.append(f"{key}='{str(value)[:40]}'")
            lines.append("  " + " ".join(bits))
        return "\n".join(lines)

    def _build_planning_prompt(self, user_input: str, elements: List[Dict[str, Any]]) -> str:
        """Build the main-agent planning prompt."""
        elements_text = self._format_elements_for_prompt(elements)
        return f"""你是 TestForge 的主 Agent，负责和用户对话、做测试规划，并把具体浏览器动作交给 ExecutorAgent。

当前页面: {self.context.current_url or '(未打开任何页面)'}
页面标题: {self.context.current_title or '(未知)'}
页面元素（必须优先使用 ref 操作）:
{elements_text}

会话上下文:
- 登录状态: {'已登录' if self.context.is_logged_in else '未登录'}
- 已保存账号: {'有' if self.context.credentials.get('username') else '无'}
- 已保存密码: {'有' if self.context.credentials.get('password') else '无'}
- 已测试: {', '.join(self.context.tested_features) or '无'}
- 发现功能: {', '.join(self.context.discovered_features) or '无'}

用户说: {user_input}

你要先规划，不要直接闲聊式回答。输出严格 JSON，使用下面 schema:
{{
  "intent": "navigate|analyze|test_login|test_register|execute|ask_user|chat",
  "response": "chat 或 ask_user 时给用户看的话",
  "ask_fields": ["username", "password"],
  "actions": [
    {{
      "type": "navigate|click|fill|assert_text|assert_visible|scroll|wait",
      "description": "动作说明",
      "url": "导航时填写",
      "target_ref": "元素 ref，例如 e12",
      "target_desc": "没有 ref 时的元素描述",
      "fill_value": "fill 时填写内容",
      "expected": "断言文本"
    }}
  ]
}}

规划规则:
1. 用户提到网址时，intent=navigate，actions 里只放 navigate。URL 可以包含中文路径，例如 http://host/blog/linux运维 必须完整保留。
2. URL 后面的自然语言说明不要放进 URL，例如“这个网站/这个页面/先测试一下”要去掉。
3. 裸域名默认补 https://。知名需要 www 的域名要规范化，例如 baidu.com -> https://www.baidu.com。
4. 用户说“测试某网站”时先打开并分析，不要凭空假设页面类型。
5. 用户说“测试登录/注册”时输出 intent=test_login 或 test_register，不要自己编账号密码。
6. 如果当前页已有 ref，点击/填写必须优先使用 target_ref；多个候选看文本、placeholder、label、位置语义选择最可能的。
7. 搜索/提交这类任务通常需要多个 actions，例如先 fill 搜索框，再 click 搜索按钮。
8. 缺账号、密码、验证码等用户信息时，intent=ask_user 并列出 ask_fields。
9. 只输出 JSON，不要 Markdown，不要解释。"""

    def _fallback_plan(self, user_input: str) -> Optional[Dict[str, Any]]:
        """模型输出不可解析时的保底规划。"""
        url = self._extract_url(user_input)
        if url:
            return {"type": "navigate", "url": url}

        lower = user_input.lower()
        if any(kw in lower for kw in ["登录", "login", "sign in"]):
            return {"type": "test_login"}
        if any(kw in lower for kw in ["注册", "register", "sign up"]):
            return {"type": "test_register"}
        if any(kw in lower for kw in ["分析", "看看", "页面", "功能", "入口", "analyze"]):
            return {"type": "analyze"}
        return None

    def _looks_like_login_request(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(keyword in lower for keyword in ["登录", "登陆", "登入", "login", "sign in", "signin"])

    def _looks_like_conditional_login(self, text: str) -> bool:
        lower = (text or "").lower()
        return bool(
            ("如果" in text and "登录" in text and any(term in text for term in ["需要", "才能", "就"]))
            or re.search(r"\bif\b.*\b(log ?in|sign ?in)\b", lower)
        )

    def _looks_like_explicit_login_test(self, text: str) -> bool:
        lower = (text or "").lower()
        explicit_terms = [
            "登录功能",
            "测试登录",
            "登录系统",
            "登录流程",
            "login function",
            "test login",
            "login flow",
        ]
        return any(term in lower or term in text for term in explicit_terms)

    def _has_post_navigation_task(self, text: str) -> bool:
        lower = (text or "").lower()
        keywords = [
            "登录", "注册", "搜索", "查询", "点赞", "赞", "评论", "留言",
            "写文章", "发布", "测试", "试试看", "click", "search", "like",
        ]
        return any(keyword in lower for keyword in keywords)

    def _has_open_page(self) -> bool:
        url = self.context.current_url or getattr(self.page, "url", "") or ""
        return bool(url and url != "about:blank")

    def _record_credentials(self, credentials: Dict[str, str]):
        """Record credentials with safe console output."""
        if credentials.get("username"):
            self.context.set_credentials(username=credentials["username"])
            print(f"  ✓ 已记录账号: {credentials['username']}")
        if credentials.get("password"):
            self.context.set_credentials(password=credentials["password"])
            print("  ✓ 已记录密码: ******")

    async def _handle_credential_or_retry(self, user_input: str) -> bool:
        """处理账号/密码修正和继续登录这类会话状态指令。"""
        text = user_input.strip()
        lower = text.lower()

        if any(kw in text for kw in ["密码错了", "密码错误", "密码不对"]):
            self.context.credentials.pop("password", None)
            print("  好，我把旧密码清掉了。")
            return True

        if any(kw in text for kw in ["重新配置密码", "重新输入密码", "修改密码"]):
            password = getpass.getpass("  新密码: ").strip()
            if password:
                self.context.set_credentials(password=password)
                print("  ✓ 已更新密码")
                await self._test_login("测试登录")
            return True

        credentials = self._extract_credentials(text)
        if credentials:
            self._record_credentials(credentials)

            if self.context.credentials.get("username") and self.context.credentials.get("password") and self._has_open_page():
                await self._test_login("测试登录")
            elif self.context.credentials.get("username") and self.context.credentials.get("password"):
                print("  凭证已记录。请再给我一个网站地址，或先打开登录页。")
            return True

        retry_phrases = [
            "再登录",
            "登录一次",
            "重新登录",
            "重试登录",
            "再试",
            "快测试",
            "继续测试",
        ]
        if any(phrase in text for phrase in retry_phrases) or (
            "login" in lower and any(k in lower for k in ["retry", "again"])
        ):
            if self.context.credentials.get("username") and self.context.credentials.get("password"):
                await self._test_login("测试登录")
            else:
                print("  还缺账号或密码。你可以说：账号是admin 密码是xxxx")
            return True

        return False

    def _extract_credentials(self, text: str) -> Dict[str, str]:
        """从自然语言中提取账号和密码。"""
        result: Dict[str, str] = {}
        patterns = {
            "username": [
                r"(?:账号|帐号|用户名|用户|账户)\s*(?:是|为|=|:|：)\s*([^\s，,。；;]+)",
                r"(?:账号|帐号|用户名|用户|账户)\s*([A-Za-z0-9_.@-]+)(?=\s|$|，|,|。|；|;)",
                r"(?:user(?:name)?|account)\s*(?:is|=|:|：)\s*([^\s，,。；;]+)",
                r"(?:user(?:name)?|account)\s+([A-Za-z0-9_.@-]+)(?=\s|$|，|,|。|；|;)",
            ],
            "password": [
                r"(?:密码|口令)\s*(?:是|为|=|:|：)\s*([^\s，,。；;]+)",
                r"(?:密码|口令)\s*([A-Za-z0-9_@#$%^&*+\-=.!?~]+)(?=\s|$|，|,|。|；|;)",
                r"(?:password|pass)\s*(?:is|=|:|：)\s*([^\s，,。；;]+)",
                r"(?:password|pass)\s+([A-Za-z0-9_@#$%^&*+\-=.!?~]+)(?=\s|$|，|,|。|；|;)",
            ],
        }
        for key, pats in patterns.items():
            for pat in pats:
                match = re.search(pat, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip().strip('"\'')
                    if value:
                        result[key] = value
                        break
        return result

    def _extract_url(self, text: str) -> Optional[str]:
        """从文本中提取 URL"""
        patterns = [
            r'https?://[^\s<>"\']+',
            r'(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?(?:/[A-Za-z0-9\-._~:/?#\[\]@!$&()*+,;=%]*)?',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                url = match.group(0)
                return self._prepare_url(url)
        return None

    def _prepare_url(self, url: str) -> str:
        """Normalize a URL coming from either user text or model output."""
        url = self._clean_url_candidate(url)
        # 去掉末尾的标点
        url = re.sub(r'[.,;:)\]}>\'"]+$', '', url)
        if url and not url.startswith("http"):
            url = "https://" + url
        return self._canonicalize_known_url(url)

    def _clean_url_candidate(self, url: str) -> str:
        """清理从自然语言中截出的 URL 候选，保留合法中文路径。"""
        url = (url or "").strip()
        # Absolute URL regex may capture Chinese natural-language suffixes.
        # Only strip root-level phrases like /这个网站的登录功能; keep legitimate
        # paths such as /blog/linux运维.
        root_phrase_match = re.match(
            r"^(https?://[^/\s?#]+)/(这个网站|这个页面|这个网页|这个地址|该网站|该页面|此网站|此页面)(?:的.*)?$",
            url,
            re.IGNORECASE,
        )
        if root_phrase_match:
            return root_phrase_match.group(1) + "/"

        trailing_phrases = [
            "这个网站",
            "这个页面",
            "这个网页",
            "这个地址",
            "网站",
            "页面",
            "网页",
        ]
        changed = True
        while changed:
            changed = False
            for phrase in trailing_phrases:
                if url.endswith(phrase):
                    url = url[: -len(phrase)]
                    changed = True
        return url

    def _canonicalize_known_url(self, url: str) -> str:
        """对少数常见裸域名做规范化，避免模型失败时走错入口。"""
        try:
            parsed = urlparse(url)
        except Exception:
            return url
        hostname = (parsed.hostname or "").lower()
        if hostname in {"baidu.com"}:
            netloc = "www.baidu.com"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return parsed._replace(netloc=netloc).geturl()
        return url

    def _extract_spec_path(self, text: str) -> Optional[str]:
        """从用户输入中提取 Markdown 测试用例路径"""
        candidates = re.findall(r'(?:"([^"]+\.md)"|\'([^\']+\.md)\'|(\S+\.md))', text, re.IGNORECASE)
        for groups in candidates:
            raw = next((g for g in groups if g), "")
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = Path.cwd() / path
            if path.exists() and path.is_file():
                return str(path)
        return None

    async def _run_spec_file(self, spec_path: str) -> bool:
        """在当前 CLI 浏览器会话中导入并执行 Markdown 测试用例"""
        path = Path(spec_path)
        print(f"\n[测试用例] {path}")
        if not path.exists():
            print("  ✗ 文件不存在")
            return False

        try:
            from ..parser import parse_spec_with_includes, render_spec_with_vars
            markdown = path.read_text(encoding="utf-8")
            parsed = parse_spec_with_includes(markdown, str(path.parent))
        except Exception as e:
            print(f"  ✗ 读取/解析失败: {e}")
            return False

        if not parsed.ok:
            print(f"  ✗ 解析失败: {parsed.error}")
            return False

        vars_map = await self._collect_spec_vars(parsed.spec)
        rendered = render_spec_with_vars(parsed.spec, vars_map)
        if not rendered.ok:
            print(f"  ✗ 模板渲染失败: {rendered.error}")
            return False

        spec = rendered.spec
        total = len(spec.steps)
        passed = 0
        print(f"  共 {total} 个步骤")

        for step in spec.steps:
            print(f"\n  [{step.index}] {step.text}")
            result = await self._execute_spec_step(step.text)
            if result.ok:
                passed += 1
                print(f"      ✓ {result.summary or '完成'}")
            else:
                print(f"      ✗ {result.reason}")
                break

            if step.expected:
                assertion = await self.executor.assert_text(step.expected)
                if assertion.ok:
                    print(f"      ✓ Expected: {step.expected}")
                else:
                    print(f"      ✗ Expected 未满足: {step.expected}")
                    break

        self.context.add_tested_feature(path.name)
        print(f"\n  用例结果: {passed}/{total} 步通过")
        return passed == total

    async def _collect_spec_vars(self, spec) -> Dict[str, str]:
        """Collect template variables for imported Markdown specs."""
        from ..parser.template import get_template_vars

        needed = get_template_vars(spec)
        values: Dict[str, str] = {}
        base_url = self._infer_base_url()

        for name in sorted(needed):
            upper = name.upper()
            if upper in {"BASE_URL", "LOGIN_BASE_URL"}:
                if not base_url:
                    base_url = self._safe_input(f"  {upper}: ").strip()
                values[upper] = base_url.rstrip("/")
            elif upper in {"USERNAME", "USER", "ACCOUNT"}:
                username = self.context.credentials.get("username")
                if not username:
                    username = self._safe_input("  用户名: ").strip()
                    self.context.set_credentials(username=username)
                values[upper] = username
            elif upper in {"PASSWORD", "PASS"}:
                password = self.context.credentials.get("password")
                if not password:
                    password = getpass.getpass("  密码: ").strip()
                    self.context.set_credentials(password=password)
                values[upper] = password
            else:
                values[upper] = self._safe_input(f"  {upper}: ").strip()

        return values

    def _infer_base_url(self) -> str:
        """Infer the origin for {{BASE_URL}} from the current browser state."""
        url = self.context.current_url or getattr(self.page, "url", "") or ""
        if url and url != "about:blank":
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"

        try:
            from ..config_loader import load

            config = load()
            base_url = getattr(config, "base_url", "") if config else ""
            if base_url:
                return base_url.rstrip("/")
        except Exception:
            pass

        return ""

    async def _execute_spec_step(self, text: str) -> ExecutorResult:
        """执行单条 Markdown 步骤，优先规则解析，复杂步骤交给 Executor AI。"""
        from ..intent_engine import create_intent_engine, IntentType

        rendered = text
        if "{{USERNAME}}" in rendered and "username" not in self.context.credentials:
            self.context.set_credentials(username=self._safe_input("  用户名: "))
        if "{{PASSWORD}}" in rendered and "password" not in self.context.credentials:
            self.context.set_credentials(password=getpass.getpass("  密码: "))

        replacements = {
            "{{BASE_URL}}": self._infer_base_url(),
            "{{USERNAME}}": self.context.credentials.get("username", ""),
            "{{PASSWORD}}": self.context.credentials.get("password", ""),
        }
        for key, value in replacements.items():
            rendered = rendered.replace(key, value)

        engine = create_intent_engine()
        intent = engine.parse(rendered)

        if intent.type == IntentType.NAVIGATE:
            url = intent.target or self._extract_url(rendered) or rendered
            if url and not url.startswith("http") and self.context.current_url:
                base = self.context.current_url.rstrip("/")
                url = f"{base}/{url.lstrip('/')}"
            return await self.executor.navigate(url)

        if intent.type == IntentType.CLICK:
            return await self.executor.click(description=intent.target or rendered)

        if intent.type == IntentType.FILL:
            return await self.executor.fill(description=intent.target or "", text=intent.value or "")

        if intent.type == IntentType.WAIT:
            seconds = float(intent.value or 1)
            await asyncio.sleep(seconds)
            return ExecutorResult(type=ResultType.SUCCESS, summary=f"等待 {seconds:g} 秒")

        if intent.type == IntentType.ASSERT_TEXT:
            return await self.executor.assert_text(intent.target or rendered)

        if intent.type == IntentType.ASSERT_VISIBLE:
            return await self.executor.assert_visible(description=intent.target or rendered)

        return await self.executor.execute_task(rendered)

    # ─── 导航 ─────────────────────────────────────────────────────────────────

    async def _handle_navigate(self, url: str):
        """处理导航请求"""
        url = self._prepare_url(url)
        print(f"\n[导航] {url}")

        result = await self.executor.navigate(url)

        if result.type == ResultType.SUCCESS:
            self.context.add_page(result.data.get("url", url))

            print(f"  ✓ 已打开: {self.context.current_url}")
            print(f"  标题: {result.data.get('title', '')}")

            # 分析页面
            await self._analyze_and_report_page()

        else:
            print(f"  ✗ 导航失败: {result.reason}")

    # ─── 页面分析 ─────────────────────────────────────────────────────────────

    async def _analyze_and_report_page(self):
        """分析当前页面，报告发现的功能"""
        snapshot_result = await self.executor.get_snapshot()
        if snapshot_result.type != ResultType.SUCCESS:
            print("  无法获取页面信息")
            return

        elements = snapshot_result.data.get("elements", [])
        if not elements:
            print("  页面元素为空，可能还在加载")
            return

        print(f"\n  页面元素: {len(elements)} 个")

        # AI 分析页面功能
        elements_text = "\n".join([
            f"- <{e['tag']}> '{e.get('text','')[:30]}' placeholder='{e.get('placeholder','')}'"
            for e in elements[:25]
        ])

        prompt = f"""分析以下页面，识别可测试的功能。

页面: {self.context.current_url}
元素:
{elements_text}

请输出：
1. 页面类型（登录/注册/博客/电商/管理等）
2. 发现的功能入口列表
3. 建议优先测试的功能

中文回答，简洁明了，3-5行。"""

        try:
            response = await self.ai_client.complete(prompt, "")
            print()
            for line in response.strip().split("\n")[:6]:
                if line.strip():
                    print(f"  {line.strip()}")
        except Exception as e:
            print(f"  AI 分析失败: {e}")

        # 记录发现的登录功能
        for e in elements:
            text = (e.get("text") or "").lower()
            if any(kw in text for kw in ["登录", "login", "注册", "register"]):
                self.context.add_discovered_feature("登录/注册")
                break
            if any(kw in text for kw in ["博客", "blog", "文章", "post"]):
                self.context.add_discovered_feature("博客/文章")
                break
            if any(kw in text for kw in ["搜索", "search"]):
                self.context.add_discovered_feature("搜索")
                break

        print()

    # ─── 测试任务 ─────────────────────────────────────────────────────────────

    async def _handle_test_task(self, task: str):
        """处理测试任务"""
        # 检查是否需要导航
        if not self.context.current_url:
            url = self._extract_url(task)
            if url:
                await self._handle_navigate(url)
            else:
                print("  请先打开一个网站，输入网址即可")
                return

        # 分析测试意图
        print(f"\n[测试] {task}")

        task_lower = task.lower()

        # 登录测试
        if any(kw in task_lower for kw in ["登录", "login"]):
            await self._test_login(task)
            return

        # 注册测试
        if any(kw in task_lower for kw in ["注册", "register", "sign up"]):
            await self._test_register(task)
            return

        # 其他测试任务：让 AI 驱动
        result = await self.executor.execute_task(task)
        await self._handle_executor_result(result)
        self.context.add_tested_feature(task[:20])

    async def _test_login(self, task: str):
        """测试登录功能"""
        print("\n[测试登录]")

        if not self._has_open_page():
            print("  请先打开一个网站或登录页，再执行登录测试。")
            return

        # 如果当前页面已经有登录表单
        login_detect = await self.executor.detect_login_page()

        if login_detect.type == ResultType.NO_AUTH_NEEDED:
            # 已登录
            print(f"  ✓ {login_detect.summary}")
            self.context.is_logged_in = True
            self.context.logged_in_user = self.context.credentials.get("username")
            await self._after_login_success()
            return

        if login_detect.type == ResultType.FAILURE:
            # 尝试找登录按钮
            print("  正在查找登录入口...")
            best = await self.executor.find_best_entry(["点击登录", "请登录", "登录", "login", "sign in", "登入", "登陆"])
            if best:
                click_result = await self.executor.click(ref=best["ref"])
                if click_result.type == ResultType.SUCCESS:
                    print(f"  点击了: {best.get('text') or best.get('placeholder') or best['ref']}")
                    # 再次检测登录页
                    login_detect = await self.executor.detect_login_page()

        if login_detect.type == ResultType.ASK_USER:
            # 需要凭证
            required = login_detect.data.get("required_fields", [])
            print(f"\n  需要以下信息: {', '.join(required)}")

            # 检查是否已有凭证
            creds = self.context.credentials
            username = creds.get("username", "")
            password = creds.get("password", "")

            if required and "username" in required and not username:
                print()
                username = self._safe_input("  用户名: ").strip()
            if required and "password" in required and not password:
                import getpass
                password = getpass.getpass("  密码: ").strip()

            if not username or not password:
                print("  ✗ 需要用户名和密码")
                # 保存凭证供下次使用
                if username:
                    self.context.set_credentials(username=username)
                return

            # 保存凭证
            self.context.set_credentials(username=username, password=password)

            # 执行登录
            print("\n  正在登录...")
            login_result = await self.executor.login(username, password)

            if login_result.type == ResultType.DONE:
                print(f"  ✓ {login_result.summary}")
                self.context.is_logged_in = True
                self.context.logged_in_user = username
                self.context.add_tested_feature("登录")
                await self._after_login_success()
            else:
                print(f"  ✗ 登录失败: {login_result.reason}")
                print("  请检查用户名和密码是否正确")
                self.context.credentials.pop("password", None)
                print("  我已清掉旧密码。你可以直接说：密码是xxxx 账号是admin")

    async def _test_register(self, task: str):
        """测试注册功能"""
        print("\n[测试注册]")

        find_result = await self.executor.find_elements("注册")
        if find_result.ok and find_result.data.get("candidates"):
            cands = find_result.data["candidates"]
            best = await self.executor.select_best_match(cands, "注册")
            if best:
                result = await self.executor.click(ref=best["ref"])
                await self._handle_executor_result(result)
                self.context.add_tested_feature("注册")
        else:
            print("  未找到注册入口")

    # ─── AI 对话 ──────────────────────────────────────────────────────────────

    async def _handle_ai_conversation(self, user_input: str):
        """处理通用 AI 对话（需要理解意图并执行操作）"""
        snapshot_result = await self.executor.get_snapshot()
        if snapshot_result.type != ResultType.SUCCESS:
            print("  请先打开一个网站")
            return

        elements = snapshot_result.data.get("elements", [])
        elements_text = "\n".join([
            f"- <{e['tag']}> '{e.get('text','')[:25]}' ref={e['ref']}"
            for e in elements[:20]
        ])

        prompt = f"""你是 TestForge 智能助手。用户正在使用 AI 自动化测试工具测试网页。

当前页面: {self.context.current_url}
页面元素:
{elements_text}

会话上下文:
- {'已登录' if self.context.is_logged_in else '未登录'}
- 已测试: {', '.join(self.context.tested_features) or '无'}
- 发现功能: {', '.join(self.context.discovered_features) or '无'}

用户说: {user_input}

请理解用户意图：
- 如果用户想做浏览器操作（点击/填写/导航），输出 action plan
- 如果用户只是闲聊或询问，直接回答

输出 JSON 格式:
{{
  "type": "action" | "chat",
  "response": "直接回复用户的内容（chat 时）",
  "action": "click" | "fill" | "navigate" | "done"（action 时）,
  "target_desc": "操作描述",
  "target_ref": "ref（可选）",
  "fill_value": "填写值（fill 时）",
  "url": "URL（navigate 时）"
}}

只输出 JSON。"""

        try:
            response = await self.ai_client.complete(prompt, "")
            match = re.search(r'\{.+\}', response, re.DOTALL)
            if not match:
                print(f"  AI: {response[:200]}")
                return

            import json
            plan = json.loads(match.group())

            if plan.get("type") == "chat":
                print(f"  {plan.get('response', '')}")
                return

            action = plan.get("action", "")

            if action == "click":
                desc = plan.get("target_desc", "")
                ref = plan.get("target_ref", "")
                result = await self.executor.click(ref=ref, description=desc)
                await self._handle_executor_result(result)

            elif action == "fill":
                ref = plan.get("target_ref", "")
                text = plan.get("fill_value", "")
                if not text:
                    text = self._safe_input(f"  输入内容: ").strip()
                result = await self.executor.fill(ref=ref, text=text)
                await self._handle_executor_result(result)

            elif action == "navigate":
                url = plan.get("url", "")
                if url:
                    await self._handle_navigate(url)

            else:
                print(f"  {response[:200]}")

        except Exception as e:
            print(f"  AI 处理失败: {e}")

    # ─── 统一计划执行 ───────────────────────────────────────────────────────────

    async def _execute_plan(self, plan, credentials: Optional[Dict[str, str]] = None):
        """执行主 Agent 返回的结构化计划（统一入口）"""
        self._last_action_requested_replan = False
        normalized = plan if isinstance(plan, AgentPlan) else normalize_agent_plan(plan)
        self._print_delegation_plan(self._build_plan_steps(normalized, credentials))

        if credentials:
            self._record_credentials(credentials)

        if normalized.intent == "test_login":
            await self._handle_test_task("测试登录")
            return True

        if normalized.intent == "test_register":
            await self._handle_test_task("测试注册")
            return True

        if normalized.intent == "analyze" and not normalized.actions:
            await self._analyze_and_report_page()
            return True

        if normalized.intent == "ask_user":
            await self._ask_for_fields(normalized.ask_fields)
            if normalized.response:
                print(f"  {normalized.response}")
            return True

        if normalized.actions:
            for action in normalized.actions:
                before = await self.executor.get_snapshot()
                result = await self._execute_action(action)
                if result is not None:
                    await self._handle_executor_result(result)
                    after = await self.executor.get_snapshot()
                    if before.type == ResultType.SUCCESS and after.type == ResultType.SUCCESS:
                        verification = self.verifier.verify_action(action, before.data, after.data)
                        if not verification.ok:
                            print(f"  ! 动作验证未通过: {verification.reason}")
                            if verification.suggestion:
                                print(f"  建议: {verification.suggestion}")
                            if verification.needs_replan:
                                result.data["needs_replan"] = True
                    if result.data.get("needs_replan"):
                        self._last_action_requested_replan = True
                        return True
                    if not result.ok:
                        return False
            await self._maybe_report_after_login_action(normalized.actions)
            return True

        if normalized.intent == "chat":
            print(f"  {normalized.response or '我在。你可以给我一个网址，或说要测试哪个功能。'}")
            return True

        print(f"  暂时无法执行这个计划: {normalized.intent or normalized.reason}")
        return False

    async def _execute_action(self, action: AgentAction) -> Optional[ExecutorResult]:
        """执行单个 AgentAction。"""
        action_type = action.type

        if action_type == "navigate":
            if not action.url:
                return ExecutorResult(type=ResultType.FAILURE, reason="未提供 URL")
            await self._handle_navigate(action.url)
            return None

        if action_type == "click":
            return await self.executor.click(
                ref=action.target_ref,
                description=action.target_desc or action.description,
            )

        if action_type == "fill":
            text = action.fill_value or action.text
            desc = action.target_desc or action.description
            if not text:
                text = self._safe_input(f"  输入 {desc or action.target_ref}: ").strip()
            result = await self.executor.fill(
                ref=action.target_ref,
                description=desc,
                text=text,
            )
            if result.type == ResultType.FAILURE and self._action_looks_like_search_fill(action):
                return await self._recover_missing_search_input(action)
            return result

        if action_type == "assert_text":
            text = action.expected or action.text or action.description
            return await self.executor.assert_text(text)

        if action_type == "assert_visible":
            return await self.executor.assert_visible(
                ref=action.target_ref,
                description=action.target_desc or action.description,
            )

        if action_type == "scroll":
            return await self.executor.scroll(action.direction, action.amount)

        if action_type == "wait":
            return await self.executor.wait(action.seconds)

        if action_type == "analyze":
            await self._analyze_and_report_page()
            return None

        if action_type == "extract_search_results":
            result = await self.executor.extract_search_results()
            if result.ok:
                total = result.data.get("total", 0)
                print(f"  ✓ 已提取搜索结果: {total} 条")
                if self._task_needs_open_article():
                    opened = await self._open_first_extracted_search_result(result)
                    if opened is not None:
                        return opened
            return result

        if action_type == "extract_like_buttons":
            result = await self.executor.extract_like_buttons()
            if result.ok:
                total = result.data.get("total", 0)
                print(f"  ✓ 已提取点赞候选: {total} 个")
            return result

        if action_type == "extract_forms":
            result = await self.executor.extract_forms()
            if result.ok:
                print(f"  ✓ 已提取表单: {result.data.get('total', 0)} 个")
            return result

        if action_type == "extract_article_content":
            result = await self.executor.extract_article_content()
            if result.ok:
                title = result.data.get("title", "")
                print(f"  ✓ 已提取文章内容: {title[:40]}")
            return result

        if action_type == "extract_auth_requirements":
            result = await self.executor.extract_auth_requirements()
            if result.ok and result.data.get("auth_required"):
                print("  页面提示需要登录")
            return result

        if action_type == "test_login":
            await self._handle_test_task("测试登录")
            return None

        if action_type == "test_register":
            await self._handle_test_task("测试注册")
            return None

        if action_type == "ask_user":
            await self._ask_for_fields(action.ask_fields)
            return None

        return ExecutorResult(type=ResultType.FAILURE, reason=f"未知动作: {action_type}")

    def _action_looks_like_search_fill(self, action: AgentAction) -> bool:
        text = " ".join([
            action.description,
            action.target_desc,
            action.target_ref,
            action.text,
        ]).lower()
        return action.type == "fill" and any(term in text for term in ["搜索", "search", "查询"])

    def _task_needs_open_article(self) -> bool:
        if not self._current_task_state:
            return False
        return any(goal.type == "open_article" and not goal.done for goal in self._current_task_state.goals)

    async def _open_first_extracted_search_result(self, result: ExecutorResult) -> Optional[ExecutorResult]:
        """Turn ExplorerAgent search results into the next BrowserAgent action."""
        results = result.data.get("results") or []
        for item in results:
            href = item.get("href") or ""
            if not href:
                continue
            try:
                path = urlparse(href).path.lower()
            except Exception:
                path = ""
            if "/blog/" not in path:
                continue

            print("  BrowserAgent: 根据搜索结果打开第一篇文章")
            nav_result = await self.executor.navigate(href)
            if nav_result.ok:
                self.context.add_page(nav_result.data.get("url", href))
                title = item.get("text") or href
                return ExecutorResult(
                    type=ResultType.SUCCESS,
                    data={
                        "url": nav_result.data.get("url", href),
                        "opened_result": item,
                        "needs_replan": True,
                    },
                    summary=f"已打开搜索结果文章: {title[:40]}",
                )
            return nav_result

        result.data["needs_replan"] = True
        return None

    async def _recover_missing_search_input(self, action: AgentAction) -> ExecutorResult:
        """If there is no search input yet, open the search entry and re-plan."""
        print("  搜索框暂时不可见，尝试先进入搜索页面...")
        best = await self.executor.find_best_entry(["搜索", "search", "查询"])
        if not best:
            return ExecutorResult(type=ResultType.FAILURE, reason="找不到搜索入口或搜索框")

        click_result = await self.executor.click(ref=best["ref"], description="搜索")
        if click_result.ok:
            click_result.summary = "已进入搜索入口，继续规划搜索输入"
            click_result.data["needs_replan"] = True
        return click_result

    async def _evaluate_task_completion(self, task: str) -> Dict[str, Any]:
        """Check whether the high-level user task is complete enough."""
        task_lower = (task or "").lower()
        if not self._has_post_navigation_task(task):
            return {"done": True, "summary": "当前任务已执行"}

        snapshot = await self.executor.get_snapshot()
        if snapshot.type != ResultType.SUCCESS:
            return {
                "done": False,
                "should_continue": False,
                "summary": "无法获取页面状态，不能确认任务是否完成",
            }

        if self._current_task_state:
            return self.verifier.evaluate_task(self._current_task_state, snapshot.data)

        page_text = (snapshot.data.get("text") or "").lower()
        current_url = snapshot.data.get("url") or self.context.current_url or getattr(self.page, "url", "")
        elements = snapshot.data.get("elements", [])

        remaining = []
        search_keyword = self._extract_search_keyword(task)
        if any(term in task_lower for term in ["搜索", "search", "查询"]):
            keyword_ok = bool(search_keyword and search_keyword.lower() in (page_text + " " + current_url.lower()))
            if not keyword_ok:
                remaining.append(f"搜索 {search_keyword or '指定关键词'}")

        if any(term in task_lower for term in ["点赞", "点一个赞", "赞", "like"]):
            liked_terms = ["已赞", "已点赞", "取消赞", "unlike", "liked"]
            like_done = any(term in page_text for term in liked_terms)
            if not like_done:
                remaining.append("进入文章详情并点赞")

        if any(term in task_lower for term in ["评论", "留言", "comment"]):
            comment_text = self._extract_comment_text(task)
            auth_required = any(
                term in page_text
                for term in ["请登录", "请先登录", "登录后", "点击登录", "需要登录", "未登录"]
            )
            if auth_required:
                remaining.append("先登录，再发表评论")
            elif comment_text and comment_text.lower() not in page_text:
                remaining.append(f"发表评论 {comment_text}")
            elif comment_text:
                return {"done": True, "summary": "评论内容已出现在页面中"}

        if not remaining:
            return {"done": True, "summary": "用户要求的测试动作已完成或页面已出现预期结果"}

        visible_search_input = any(
            e.get("tag") in ("input", "textarea")
            and any(term in " ".join([
                str(e.get("text", "")),
                str(e.get("placeholder", "")),
                str(e.get("label", "")),
                str(e.get("ariaLabel", "")),
                str(e.get("id", "")),
                str(e.get("name", "")),
            ]).lower() for term in ["搜索", "search", "查询"])
            for e in elements
        )
        should_continue = bool(remaining)
        if visible_search_input and search_keyword:
            should_continue = True

        return {
            "done": False,
            "should_continue": should_continue,
            "remaining": "，然后".join(remaining),
            "summary": f"任务还未确认完成，剩余: {'，'.join(remaining)}",
        }

    def _extract_search_keyword(self, task: str) -> str:
        return extract_search_keyword(task)

    def _extract_comment_text(self, task: str) -> str:
        return extract_comment_text(task)

    async def _maybe_report_after_login_action(self, actions: List[AgentAction]):
        """After a planned login click, refresh state and tell the user what is next."""
        if not any(self._action_looks_like_login_submit(action) for action in actions):
            return

        await asyncio.sleep(0.8)
        result = await self.executor.verify_login_result()
        if result.type == ResultType.DONE:
            print(f"  ✓ {result.summary}")
            self.context.is_logged_in = True
            self.context.logged_in_user = self.context.credentials.get("username")
            self.context.add_tested_feature("登录")
            if result.data.get("url"):
                self.context.add_page(result.data["url"])
            await self._after_login_success()
            return

        print(f"  ✗ {result.reason}")
        print("  登录动作已经执行，但我不会把未确认的结果当成成功。")

    def _action_looks_like_login_submit(self, action: AgentAction) -> bool:
        if action.type != "click":
            return False
        text = " ".join([
            action.description,
            action.target_desc,
            action.text,
            action.expected,
        ]).lower()
        return any(keyword in text for keyword in ["登录", "登入", "登陆", "login", "sign in", "signin"])

    async def _after_login_success(self):
        """Analyze the page after login so the conversation keeps moving."""
        print("  登录后可以继续测试的功能如下：")
        await self._analyze_and_report_page()
        print("  你可以直接说：测试搜索、测试写文章、测试留言、测试后台入口，或导入 Markdown 用例。")

    async def _ask_for_fields(self, fields: List[str]):
        """Ask and store fields requested by the plan or executor."""
        for field in fields:
            normalized = field.lower()
            if normalized in ("password", "密码"):
                val = getpass.getpass("  密码: ").strip()
            else:
                val = self._safe_input(f"  {field}: ").strip()

            if normalized in ("username", "user", "account", "用户名", "账号", "帐号"):
                self.context.set_credentials(username=val)
            elif normalized in ("password", "pass", "密码"):
                self.context.set_credentials(password=val)

    # ─── 结果处理 ─────────────────────────────────────────────────────────────

    async def _handle_executor_result(self, result: ExecutorResult):
        """处理 ExecutorAgent 返回的结果"""
        if result.type == ResultType.SUCCESS:
            if result.summary:
                print(f"  ✓ {result.summary}")
            # 更新上下文
            if result.data.get("url"):
                self.context.add_page(result.data["url"])

        elif result.type == ResultType.FAILURE:
            print(f"  ✗ {result.reason}")
            self.context.last_failed_action = {
                "reason": result.reason,
                "data": dict(result.data),
            }
            # 提供恢复建议
            await self._suggest_recovery(result.reason)

        elif result.type == ResultType.ASK_USER:
            fields = result.data.get("required_fields", [])
            print(f"\n  需要用户提供: {', '.join(fields)}")
            await self._ask_for_fields(fields)

        elif result.type == ResultType.NO_AUTH_NEEDED:
            print(f"  ✓ {result.summary}")
            self.context.is_logged_in = True

        elif result.type == ResultType.DONE:
            print(f"  ✓ {result.summary}")
            if result.data.get("url"):
                self.context.add_page(result.data["url"])

    async def _suggest_recovery(self, reason: str):
        """给出失败恢复建议"""
        reason_lower = reason.lower()
        if "not found" in reason_lower or "找不到" in reason_lower:
            print("  提示: 尝试用更具体的描述，如'点击蓝色登录按钮'")
            print("  或先输入'截图'看看当前页面")

    # ─── 帮助与状态 ────────────────────────────────────────────────────────────

    def _show_help(self):
        print("""
命令:
  http://xxx.com            - 访问网站
  测试登录 / 测试注册        - 测试对应功能
  运行 specs/login.md       - 导入并执行 Markdown 测试用例
  帮我看看这个页面           - AI 分析当前页面
  点击[按钮名]               - 点击按钮
  截图                      - 获取当前页面截图
  状态                      - 查看当前状态
  help                     - 显示此帮助
  q                        - 退出
""")

    def _show_summary(self):
        print()
        print("=" * 60)
        print("  会话总结")
        print("=" * 60)
        print(f"  {self.context.to_summary()}")
        print("=" * 60)


async def run_spec_file_once(spec_path: str) -> bool:
    """启动一次浏览器并运行单个 Markdown 用例，供启动菜单调用。"""
    from ..browser import create_browser
    from ..ai_client import create_ai_client
    from ..config_loader import get_ai_config_for_client

    browser_result = await create_browser(headless=False)
    if not browser_result.get("ok"):
        print(f"  ✗ 浏览器启动失败: {browser_result.get('error')}")
        return False

    browser = browser_result["browser"]
    playwright = browser_result.get("playwright")
    context = browser_result.get("context")
    if context is None:
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
    page = await context.new_page()

    try:
        ai_client = create_ai_client(get_ai_config_for_client())
        agent = MainAgent(page=page, ai_client=ai_client)
        return await agent._run_spec_file(spec_path)
    finally:
        for closeable in (context, browser):
            try:
                await closeable.close()
            except BaseException:
                pass
        if playwright:
            try:
                await playwright.stop()
            except BaseException:
                pass
        try:
            await asyncio.sleep(0.2)
        except BaseException:
            pass


__all__ = ["MainAgent", "SessionContext", "run_spec_file_once"]
