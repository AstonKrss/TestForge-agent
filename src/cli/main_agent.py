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
import json
import re
import getpass
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from ..ai_client import create_ai_client, AIClient
from .executor_agent import ExecutorAgent, ExecutorResult, ResultType
from .agent_plan import AgentAction, AgentPlan, extract_json_payload, normalize_agent_plan
from .engineering_tools import (
    EvidenceCollector,
    LocatorMemory,
    NetworkRecorder,
    ReportGenerator,
    TestDataManager,
    TestPlanGenerator,
    UrlScope,
    VisualRegression,
    build_site_map,
    explore_site_map,
    write_exploration_artifacts,
)
from .qa_workbench import (
    DefectManager,
    EnvironmentInspector,
    JMeterExporter,
    PostmanCollectionRunner,
    RegressionComparer,
    SQLWorkbench,
    TestCaseManager,
)
from ..ir.writer import IRWriter
from .planning_agent import PlanningAgent
from .session_store import SessionStore
from .task_state import TaskState, extract_comment_text, extract_search_keyword
from .verifier_agent import VerifierAgent


# ─────────────────────────────────────────────────────────────────────────────
# 会话上下文
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionContext:
    """会话上下文"""
    # 会话元信息
    session_name: str = "default"
    run_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d-%H%M%S"))
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)

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
    test_plan: List[Dict[str, Any]] = field(default_factory=list)
    generated_data: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    reports: List[str] = field(default_factory=list)
    site_map: Dict[str, Any] = field(default_factory=dict)
    visual_results: List[Dict[str, Any]] = field(default_factory=list)
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    defects: List[Dict[str, Any]] = field(default_factory=list)
    api_runs: List[Dict[str, Any]] = field(default_factory=list)
    sql_checks: List[Dict[str, Any]] = field(default_factory=list)
    jmeter_plans: List[Dict[str, Any]] = field(default_factory=list)
    environment_checks: List[Dict[str, Any]] = field(default_factory=list)
    regression_results: List[Dict[str, Any]] = field(default_factory=list)

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

    def add_event(self, role: str, text: str, data: Optional[Dict[str, Any]] = None):
        self.events.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "role": role,
            "text": text,
            "data": data or {},
        })
        self.events = self.events[-200:]

    def to_dict(self, redact: bool = True) -> Dict[str, Any]:
        credentials = dict(self.credentials)
        if redact and credentials.get("password"):
            credentials["password"] = "***"
        return {
            "session_name": self.session_name,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "current_url": self.current_url,
            "current_title": self.current_title,
            "page_history": list(self.page_history),
            "is_logged_in": self.is_logged_in,
            "logged_in_user": self.logged_in_user,
            "tested_features": list(self.tested_features),
            "discovered_features": list(self.discovered_features),
            "credentials": credentials,
            "current_task_state": dict(self.current_task_state),
            "last_failed_action": dict(self.last_failed_action),
            "known_feature_map": dict(self.known_feature_map),
            "known_selectors": dict(self.known_selectors),
            "test_plan": list(self.test_plan),
            "generated_data": list(self.generated_data),
            "artifacts": list(self.artifacts),
            "reports": list(self.reports),
            "site_map": dict(self.site_map),
            "visual_results": list(self.visual_results),
            "test_cases": list(self.test_cases),
            "defects": list(self.defects),
            "api_runs": list(self.api_runs),
            "sql_checks": list(self.sql_checks),
            "jmeter_plans": list(self.jmeter_plans),
            "environment_checks": list(self.environment_checks),
            "regression_results": list(self.regression_results),
            "events": list(self.events),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        context = cls()
        for key in (
            "session_name",
            "run_id",
            "created_at",
            "updated_at",
            "current_url",
            "current_title",
            "page_history",
            "is_logged_in",
            "logged_in_user",
            "tested_features",
            "discovered_features",
            "credentials",
            "current_task_state",
            "last_failed_action",
            "known_feature_map",
            "known_selectors",
            "test_plan",
            "generated_data",
            "artifacts",
            "reports",
            "site_map",
            "visual_results",
            "test_cases",
            "defects",
            "api_runs",
            "sql_checks",
            "jmeter_plans",
            "environment_checks",
            "regression_results",
            "events",
        ):
            if key in data:
                setattr(context, key, data[key])
        if context.credentials.get("password") == "***":
            context.credentials.pop("password", None)
        return context

    def to_summary(self) -> str:
        lines = []
        lines.append(f"会话: {self.session_name}")
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
        self.session_store = SessionStore()
        self.test_plan_generator = TestPlanGenerator()
        self.reporter = ReportGenerator()
        self.network_recorder = NetworkRecorder()
        self.evidence = EvidenceCollector()
        self.data_manager = TestDataManager()
        self.visual = VisualRegression()
        self.locator_memory = LocatorMemory()
        self.case_manager = TestCaseManager()
        self.defect_manager = DefectManager()
        self.postman_runner = PostmanCollectionRunner()
        self.sql_workbench = SQLWorkbench()
        self.jmeter_exporter = JMeterExporter()
        self.environment_inspector = EnvironmentInspector()
        self.regression_comparer = RegressionComparer()
        self.context = SessionContext()
        self.ir_writer = IRWriter(str(Path.cwd()), self.context.run_id)
        self._running = False
        self._last_action_requested_replan = False
        self._current_task_state: Optional[TaskState] = None
        self._current_user_task_text = ""
        self._pending_resume: Dict[str, str] = {}
        self._action_repeat_counts: Dict[str, int] = {}
        self._used_recoveries: set = set()
        self._trace_started = False
        self._suppress_auto_plan = False
        self._task_action_count = 0
        self._task_consecutive_failures = 0
        self._max_actions_per_task = 40
        self._max_consecutive_failures = 5
        self.network_recorder.attach(page)

    # ─── 对话入口 ─────────────────────────────────────────────────────────────

    async def run(self):
        """运行主对话循环"""
        self._running = True
        await self._start_trace()

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

            if await self._handle_session_command(user_input):
                continue

            if await self._handle_engineering_command(user_input):
                continue

            if self._is_page_closed():
                print("  浏览器页面已经关闭，本次 CLI 会话已停止。请重新进入 CLI 后继续测试。")
                self._running = False
                break

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

    async def _start_trace(self):
        if self._trace_started:
            return
        try:
            await self.page.context.tracing.start(screenshots=True, snapshots=True, sources=True)
            self._trace_started = True
        except Exception:
            self._trace_started = False

    async def _save_trace_to(self, directory: Path):
        if not self._trace_started:
            return
        try:
            trace_path = directory / "trace.zip"
            await self.page.context.tracing.stop(path=str(trace_path))
            self._trace_started = False
            self.context.artifacts.append(str(trace_path))
        except Exception:
            self._trace_started = False
        finally:
            await self._start_trace()

    def _is_page_closed(self) -> bool:
        try:
            return bool(getattr(self.page, "is_closed")())
        except Exception:
            return False

    def _reset_ir_writer(self):
        if not getattr(self.context, "run_id", ""):
            self.context.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.ir_writer = IRWriter(str(Path.cwd()), self.context.run_id)

    # ─── 命令处理 ──────────────────────────────────────────────────────────────

    async def _handle_session_command(self, user_input: str) -> bool:
        """Handle local session/project commands before normal planning."""
        text = user_input.strip()
        lower = text.lower()

        if lower in ("sessions", "session list", "list sessions", "会话列表", "列出会话"):
            sessions = self.session_store.list()
            if not sessions:
                print("  暂无本地会话")
                return True
            print("\n[会话列表]")
            for item in sessions[:20]:
                features = ", ".join(item.get("tested_features") or [])
                print(f"  - {item['name']} | {item.get('updated_at', '')} | {item.get('current_url', '')}")
                if features:
                    print(f"    已测: {features}")
            return True

        if self._starts_with_any(text, ["保存会话", "保存项目", "save session", "session save"]):
            name = self._session_name_after_command(text) or self.context.session_name
            path = self.session_store.save(name, self.context.to_dict(redact=True))
            self.context.session_name = name
            self.context.add_event("system", f"保存会话 {name}", {"path": str(path)})
            print(f"  ✓ 会话已保存: {path}")
            print("  提醒: 密码/token 不会明文保存，下次加载后如需登录会重新询问或使用新输入的凭证。")
            return True

        if self._starts_with_any(text, ["加载会话", "打开会话", "load session", "session load"]):
            name = self._session_name_after_command(text)
            if not name:
                print("  请指定会话名，例如: 加载会话 blog-test")
                return True
            try:
                data = self.session_store.load(name)
            except FileNotFoundError as e:
                print(f"  ✗ {e}")
                return True
            self.context = SessionContext.from_dict(data)
            self.context.session_name = data.get("session_name") or name
            self._reset_ir_writer()
            self.network_recorder.clear()
            self._pending_resume = {}
            self._action_repeat_counts = {}
            self._used_recoveries = set()
            self.context.add_event("system", f"加载会话 {self.context.session_name}")
            print(f"  ✓ 已加载会话: {self.context.session_name}")
            print(f"  {self.context.to_summary()}")
            if self.context.current_url:
                await self._handle_navigate(self.context.current_url)
            return True

        if self._starts_with_any(text, ["新建会话", "新开会话", "new session", "session new"]):
            name = self._session_name_after_command(text) or datetime.now().strftime("session-%Y%m%d-%H%M%S")
            self.context = SessionContext(session_name=name)
            self._reset_ir_writer()
            self._current_task_state = None
            self._current_user_task_text = ""
            self._last_action_requested_replan = False
            self._pending_resume = {}
            self._action_repeat_counts = {}
            self._used_recoveries = set()
            self.network_recorder.clear()
            print(f"  ✓ 已新建会话: {name}")
            return True

        return False

    def _starts_with_any(self, text: str, prefixes: List[str]) -> bool:
        lower = text.lower().strip()
        return any(lower.startswith(prefix.lower()) for prefix in prefixes)

    def _session_name_after_command(self, text: str) -> str:
        patterns = [
            r"^(?:保存会话|保存项目|加载会话|打开会话|新建会话|新开会话)\s*[:：]?\s*(.+)$",
            r"^(?:save session|session save|load session|session load|new session|session new)\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, text.strip(), re.IGNORECASE)
            if match:
                return match.group(1).strip().strip('"\'')
        return ""

    def _name_after_keyword(self, text: str, keywords: List[str]) -> str:
        for keyword in keywords:
            index = text.lower().find(keyword.lower())
            if index >= 0:
                value = text[index + len(keyword):].strip().strip('"\'')
                value = re.sub(r"^(为|叫|命名为|name)\s*", "", value, flags=re.I).strip()
                if value and not self._extract_url(value):
                    return value[:80]
        return ""

    def _extract_any_file_path(self, text: str, suffixes: List[str]) -> Optional[str]:
        suffix_pattern = "|".join(re.escape(suffix.lstrip(".")) for suffix in suffixes)
        candidates = re.findall(
            rf'(?:"([^"]+\.({suffix_pattern}))"|\'([^\']+\.({suffix_pattern}))\'|(\S+\.({suffix_pattern})))',
            text,
            re.IGNORECASE,
        )
        for groups in candidates:
            raw = ""
            for group in groups:
                if group and Path(group).suffix.lower() in suffixes:
                    raw = group
                    break
            if not raw:
                continue
            path = Path(raw)
            if not path.is_absolute():
                path = Path.cwd() / path
            if path.exists() and path.is_file():
                return str(path)
        return None

    def _extract_env_file_path(self, text: str) -> Optional[str]:
        match = re.search(r"(?:环境|env|environment)\s*[:：]?\s*([^\s]+\.json)", text, re.I)
        if not match:
            return None
        path = Path(match.group(1).strip().strip('"\''))
        if not path.is_absolute():
            path = Path.cwd() / path
        return str(path) if path.exists() and path.is_file() else None

    def _extract_severity(self, text: str) -> str:
        match = re.search(r"(?:severity|严重级别|优先级|级别)\s*[:：]?\s*(P[0-4]|S[0-4]|blocker|critical|major|minor)", text, re.I)
        if match:
            return match.group(1).upper()
        if any(term in text for term in ["严重", "阻塞", "崩溃", "critical", "blocker"]):
            return "P1"
        if any(term in text for term in ["轻微", "minor"]):
            return "P3"
        return "P2"

    def _parse_key_values(self, text: str, keys: List[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key in keys:
            match = re.search(rf"{re.escape(key)}\s*=\s*([^\s]+)", text, re.I)
            if match:
                result[key] = match.group(1).strip().strip('"\'')
        return result

    def _extract_number_after(self, text: str, keys: List[str], default: int = 1) -> int:
        for key in keys:
            match = re.search(rf"{re.escape(key)}\s*[:：]?\s*(\d+)", text, re.I)
            if match:
                return max(1, int(match.group(1)))
        return default

    async def _handle_engineering_command(self, user_input: str) -> bool:
        """Handle testing-engineering commands that do not need model planning."""
        text = user_input.strip()
        lower = text.lower()

        if self._looks_like_full_test_request(text):
            await self._run_full_test_suite(text)
            return True

        if self._looks_like_all_known_feature_request(text):
            await self._run_known_feature_suite(text)
            return True

        if any(term in lower for term in ["测试计划", "测试矩阵", "生成计划", "test plan"]):
            await self._generate_and_show_test_plan()
            return True

        if any(term in lower for term in ["运行用例", "执行用例", "run case"]):
            await self._run_managed_test_case(text)
            return True

        if any(term in lower for term in ["用例列表", "查看用例", "case list"]):
            self._list_managed_test_cases()
            return True

        if any(term in lower for term in ["生成测试用例", "保存测试用例", "导出测试用例", "用例中心", "test case", "testcase"]):
            await self._generate_test_cases(text)
            return True

        if any(term in lower for term in ["需求文档", "根据需求", "导入需求", "requirement"]):
            await self._generate_cases_from_requirement(text)
            return True

        if any(term in lower for term in ["生成缺陷", "创建缺陷", "提bug", "提 bug", "bug单", "defect"]):
            self._create_defect_ticket(text)
            return True

        if any(term in lower for term in ["运行pytest", "pytest回归", "pytest 回归", "run pytest"]):
            self._run_pytest_regression(text)
            return True

        if any(term in lower for term in ["导入postman", "运行postman", "postman collection", "postman"]):
            self._run_postman_collection(text)
            return True

        if any(term in lower for term in ["mysql", "sql", "数据库校验", "查库", "数据校验"]):
            self._handle_sql_check(text)
            return True

        if any(term in lower for term in ["生成jmeter", "导出jmx", "jmeter脚本", "jmeter"]):
            self._export_jmeter_plan(text)
            return True

        if any(term in lower for term in ["docker日志", "docker logs", "k8s日志", "kubectl logs", "查看最近日志"]):
            self._run_environment_logs(text)
            return True

        if any(term in lower for term in ["环境检查", "linux检查", "docker检查", "k8s检查", "检查docker", "检查k8s", "env check"]):
            self._run_environment_check(text)
            return True

        if any(term in lower for term in ["回归对比", "对比上次", "对比会话", "compare regression", "regression compare"]):
            self._compare_regression(text)
            return True

        if any(term in lower for term in ["生成报告", "测试报告", "导出报告", "report"]):
            await self._generate_report(text)
            return True

        if any(term in lower for term in ["网络日志", "接口日志", "api测试", "api 测试", "接口检查", "network"]):
            self._show_network_report()
            return True

        if any(term in lower for term in ["测试数据", "生成数据", "造数据", "test data"]):
            self._generate_test_data(text)
            return True

        if any(term in lower for term in ["站点地图", "功能图", "页面地图", "sitemap"]):
            await self._generate_site_map()
            return True

        if any(term in lower for term in ["探索站点", "深度探索", "plan-explore", "plan explore", "探索页面"]):
            await self._run_plan_explore(text)
            return True

        if any(term in lower for term in ["导出playwright", "导出 playwright", "导出用例", "export playwright", "export test"]):
            self._export_interactive_ir(text)
            return True

        if self._starts_with_any(text, ["保存基线", "保存视觉基线", "visual baseline", "save baseline"]):
            await self._save_visual_baseline(text)
            return True

        if self._starts_with_any(text, ["视觉对比", "视觉回归", "compare baseline", "visual compare"]):
            await self._compare_visual_baseline(text)
            return True

        if any(term in lower for term in ["安全基础测试", "安全检查", "security audit", "security"]):
            await self._run_security_audit(text)
            return True

        if any(term in lower for term in ["无障碍", "可访问性", "a11y", "accessibility"]):
            await self._run_accessibility_audit(text)
            return True

        if any(term in lower for term in ["locator", "定位器记忆", "定位记忆"]):
            self._show_locator_memory()
            return True

        if any(term in lower for term in ["agent分工", "agent 角色", "agent roles", "角色分工"]):
            self._show_agent_roles()
            return True

        if any(term in lower for term in ["生成ci", "生成 ci", "ci配置", "github actions", "cicd", "ci/cd"]):
            self._write_ci_template()
            return True

        if any(term in lower for term in ["回归测试", "回归执行", "regression"]):
            await self._run_regression(text)
            return True

        return False

    async def _handle_user_input(self, user_input: str):
        """处理用户输入：统一交给 AI 分析意图"""
        print()
        print(f"[用户] {user_input}")
        self.context.add_event("user", user_input)

        if self._looks_like_load_test_request(user_input):
            await self._run_load_test(user_input)
            return

        if self._looks_like_quality_request(user_input):
            await self._run_quality_audit(user_input)
            return

        if self._looks_like_performance_request(user_input):
            await self._run_performance_audit(user_input)
            return

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
        self._current_user_task_text = task
        self._current_task_state = TaskState.from_user_input(task)
        self.context.current_task_state = self._current_task_state.to_dict()
        self._task_action_count = 0
        self._task_consecutive_failures = 0
        self._action_repeat_counts = {}
        self._used_recoveries = set()

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
            elif action.type == "performance_audit":
                steps.append(DelegatedStep("PerformanceAgent", f"采集页面性能指标（{action.runs} 次）"))
            elif action.type == "load_test":
                steps.append(DelegatedStep("LoadTestAgent", f"压测 {action.url or '当前页面'}（{action.requests} 请求 / 并发 {action.concurrency}）"))
            elif action.type == "quality_audit":
                steps.append(DelegatedStep("QualityAuditAgent", "检查页面质量、无障碍和基础安全"))
            elif action.type == "security_audit":
                steps.append(DelegatedStep("SecurityAgent", "检查安全响应头、混合内容和危险链接"))
            elif action.type == "accessibility_audit":
                steps.append(DelegatedStep("AccessibilityAgent", "检查基础无障碍语义"))
            elif action.type == "generate_test_plan":
                steps.append(DelegatedStep("PlanningAgent", "生成测试矩阵"))
            elif action.type == "full_test_suite":
                steps.append(DelegatedStep("SuiteAgent", "运行一键全量测试并生成报告"))
            elif action.type == "known_feature_suite":
                steps.append(DelegatedStep("FeatureTestAgent", "测试当前页面已知功能入口"))
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
      "type": "navigate|click|fill|assert_text|assert_visible|scroll|wait|full_test_suite|known_feature_suite",
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
9. 如果用户要求“完整测试/全量测试/全套测试/一键测试/生成完整报告”，规划 full_test_suite；如果有 URL，先 navigate，再 full_test_suite。
10. 如果用户要求“测试当前页面所有已知功能/所有功能/能看到的功能/全部功能”，规划 known_feature_suite；如果有 URL，先 navigate，再 known_feature_suite。
11. 不要重复规划同一个无进展动作；如果已经在管理页还找不到写文章，要换策略为点击具体“写文章/新增/发布文章”入口，或让 ExplorerAgent 抽取链接。
12. 对“评论/点赞/写文章”等受保护操作，如果页面提示需要登录，先规划登录，再回到原任务继续。
13. 点击动作必须写 expected_state 思路到 description 中，例如“点击第一篇文章，预期进入 /blog/ 详情页”。
14. 只输出 JSON，不要 Markdown，不要解释。"""

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

    def _looks_like_performance_request(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(term in lower for term in ["性能", "性能测试", "performance", "测速", "加载速度", "页面速度"])

    def _looks_like_load_test_request(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(term in lower for term in ["压力测试", "测试压力", "压测", "负载测试", "并发测试", "load test", "stress test"])

    def _looks_like_quality_request(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(term in lower for term in ["页面质量", "质量检查", "无障碍", "可访问性", "a11y", "seo", "基础安全", "安全检查"])

    def _looks_like_full_test_request(self, text: str) -> bool:
        lower = (text or "").lower()
        suite_terms = [
            "全量",
            "完整",
            "全套",
            "一键",
            "全站",
            "everything",
            "full",
        ]
        if ("测试" in lower or "test" in lower) and any(
            term in lower for term in suite_terms
        ):
            return True
        return any(term in lower for term in [
            "全部测试",
            "全量测试",
            "一键测试",
            "完整测试",
            "全部都测试",
            "所有都测试",
            "跑全套",
            "full test",
            "full suite",
            "test everything",
        ])

    def _looks_like_all_known_feature_request(self, text: str) -> bool:
        lower = (text or "").lower()
        if self._looks_like_full_test_request(text):
            return False
        has_test = any(term in lower for term in ["测试", "测一遍", "跑一遍", "检查", "test", "check"])
        has_features = any(term in lower for term in [
            "所有功能",
            "全部功能",
            "已知功能",
            "页面功能",
            "当前页面功能",
            "能看到的功能",
            "发现的功能",
            "可测试功能",
            "all functions",
            "known functions",
        ])
        return has_test and has_features

    async def _run_full_test_suite(self, user_input: str):
        """Run a safe one-command full test suite and export a report."""
        self.network_recorder.clear()
        url = self._extract_url(user_input)
        if url:
            previous_auto_plan = self._suppress_auto_plan
            self._suppress_auto_plan = True
            try:
                nav_result = await self._handle_navigate(url)
            finally:
                self._suppress_auto_plan = previous_auto_plan
            if not nav_result or not nav_result.ok:
                print("  全量测试停止：目标页面无法打开，后续审计不会继续使用旧页面。")
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：全量测试 http://example.com")
            return

        print("\n[一键全量测试]")
        print("  范围: 测试计划、站点地图、入口冒烟、可执行功能流、质量、安全、无障碍、性能、低压压测、网络/API摘要、报告")
        print("  安全策略: 可安全验证的功能会实际执行；发文章/评论等会创建数据的动作默认只做到提交前")

        await self._generate_and_show_test_plan()
        await self._generate_site_map()
        suite_root_url = self.context.current_url or getattr(self.page, "url", "")
        await self._run_known_feature_suite("", from_full_suite=True)
        await self._run_functional_flow_suite(suite_root_url)
        await self._run_quality_audit("")
        await self._run_security_audit("")
        await self._run_accessibility_audit("")
        await self._run_performance_audit("性能测试 当前页面 2次")

        current_url = self.context.current_url or getattr(self.page, "url", "")
        if current_url and current_url != "about:blank":
            await self._run_load_test(f"压力测试 {current_url} 20次 并发2")

        self._show_network_report()
        await self._generate_report("生成报告 html")
        await self._generate_report("生成报告 json")
        print("  ✓ 一键全量测试完成")

    async def _run_load_test(self, user_input: str):
        """Run a bounded HTTP load test."""
        url = self._extract_url(user_input) or self.context.current_url or getattr(self.page, "url", "")
        if not url or url == "about:blank":
            print("  请指定压测 URL，或先打开一个页面。例如: 压力测试 http://example.com 20次 并发2")
            return

        if self._looks_like_load_ladder_request(user_input):
            await self._run_load_test_ladder(url)
            return

        params = self._extract_load_test_params(user_input)
        print("\n[压力测试]")
        print("  LoadTestAgent: 受控 HTTP 并发探测，默认低压并带硬上限")
        print(
            f"  目标: {url} | 请求: {params['requests']} | 并发: {params['concurrency']} | "
            f"方法: {params['method']} | 超时: {params['timeout']}s"
        )
        result = await self.executor.load_test(url=url, **params)
        if result.type != ResultType.SUCCESS:
            print(f"  ✗ 压力测试失败: {result.reason}")
            return

        self.context.add_tested_feature("压力测试")
        self.context.add_event("agent", result.summary, {"tool": "load_test", "url": url})
        self._print_load_test_report(result.data)

    def _looks_like_load_ladder_request(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(term in lower for term in ["阶梯", "逐步加压", "自动加压", "持续加压", "直到失败", "ramp", "step load", "ladder"])

    async def _run_load_test_ladder(self, url: str):
        """Run controlled step-load testing and stop when the target shows stress."""
        tiers = [
            {"requests": 20, "concurrency": 2, "method": "GET", "timeout": 10.0, "name": "低压"},
            {"requests": 50, "concurrency": 5, "method": "GET", "timeout": 15.0, "name": "中压"},
            {"requests": 100, "concurrency": 10, "method": "GET", "timeout": 20.0, "name": "高压"},
        ]
        print("\n[阶梯压力测试]")
        print("  LoadTestAgent: 20x2 -> 50x5 -> 100x10，错误率或 P95 过高时自动停止")
        ladder_results = []
        for tier in tiers:
            name = tier.pop("name")
            print(f"\n  [{name}] 请求 {tier['requests']} / 并发 {tier['concurrency']}")
            result = await self.executor.load_test(url=url, **tier)
            if result.type != ResultType.SUCCESS:
                print(f"  ✗ {name}失败: {result.reason}")
                self.context.add_event("agent", f"阶梯压测{name}失败: {result.reason}", {"tool": "load_test_ladder", "url": url})
                break
            summary = result.data.get("summary", {})
            ladder_results.append(summary)
            self._print_load_test_report(result.data)
            if float(summary.get("errorRate") or 0) > 5 or float(summary.get("p95") or 0) > 5000:
                print("  ! 已达到停止条件：错误率超过 5% 或 P95 超过 5s，停止继续加压")
                break

        self.context.add_tested_feature("阶梯压力测试")
        self.context.add_event("agent", "阶梯压力测试完成", {
            "tool": "load_test_ladder",
            "url": url,
            "tiers": ladder_results,
        })

    def _extract_load_test_params(self, text: str) -> Dict[str, Any]:
        requests = 20
        concurrency = 2
        timeout = 10.0
        method = "HEAD" if re.search(r"\bHEAD\b|head请求", text or "", re.IGNORECASE) else "GET"
        text_lower = (text or "").lower()

        if any(term in text_lower for term in ["加大力度", "加压", "更大压力", "提高压力", "中压", "medium"]):
            requests = 50
            concurrency = 5
        if any(term in text_lower for term in ["高压", "强压", "极限", "拉满", "最大", "max", "high stress"]):
            requests = 100
            concurrency = 10

        request_match = re.search(r"(\d+)\s*(?:次|个请求|请求|requests?)", text or "", re.IGNORECASE)
        if request_match:
            requests = int(request_match.group(1))
        concurrency_match = re.search(r"(?:并发|concurrency|users?)\s*[:：=]?\s*(\d+)", text or "", re.IGNORECASE)
        if not concurrency_match:
            concurrency_match = re.search(r"(\d+)\s*(?:并发|用户)", text or "", re.IGNORECASE)
        if concurrency_match:
            concurrency = int(concurrency_match.group(1))
        timeout_match = re.search(r"(?:超时|timeout)\s*[:：=]?\s*(\d+(?:\.\d+)?)", text or "", re.IGNORECASE)
        if timeout_match:
            timeout = float(timeout_match.group(1))

        return {
            "requests": max(1, min(requests, 100)),
            "concurrency": max(1, min(concurrency, 10)),
            "method": method,
            "timeout": max(1.0, min(timeout, 30.0)),
        }

    def _print_load_test_report(self, data: Dict[str, Any]):
        summary = data.get("summary", {})
        print(f"  总请求: {summary.get('total', 0)}")
        print(f"  成功/失败: {summary.get('ok', 0)} / {summary.get('failed', 0)}")
        print(f"  错误率: {summary.get('errorRate', 0)}%")
        print(f"  吞吐: {summary.get('rps', 0)} req/s")
        print(
            f"  延迟: avg {summary.get('avg', 0)} ms | "
            f"P50 {summary.get('p50', 0)} ms | P90 {summary.get('p90', 0)} ms | "
            f"P95 {summary.get('p95', 0)} ms | max {summary.get('max', 0)} ms"
        )
        print(f"  状态码: {summary.get('statusCounts', {})}")
        errors = summary.get("errors") or {}
        if errors:
            print("  错误 Top:")
            for error, count in list(errors.items())[:5]:
                print(f"    - {count}x {error}")
        print("  建议:")
        for recommendation in summary.get("recommendations", []):
            print(f"    - {recommendation}")

    async def _run_known_feature_suite(self, user_input: str, from_full_suite: bool = False):
        """Safely smoke-test every known page feature/entry without destructive submits."""
        url = self._extract_url(user_input)
        if url:
            previous_auto_plan = self._suppress_auto_plan
            self._suppress_auto_plan = True
            try:
                nav_result = await self._handle_navigate(url)
            finally:
                self._suppress_auto_plan = previous_auto_plan
            if not nav_result or not nav_result.ok:
                print("  已知功能测试停止：目标页面无法打开。")
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：测试 http://example.com 所有功能")
            return

        print("\n[已知功能冒烟测试]")
        print("  安全策略: 只打开入口、检查页面状态和表单字段，不自动删除/退出/发布/付款")

        original_url = self.context.current_url or getattr(self.page, "url", "")
        snapshot = await self.executor.get_snapshot()
        if snapshot.type == ResultType.SUCCESS:
            self._remember_page_features(snapshot.data)

        site_map = await build_site_map(self.page, max_links=80)
        self.context.site_map = site_map
        candidates = self._known_feature_candidates(site_map)
        if not candidates:
            print("  暂时没有发现可安全冒烟测试的功能入口")
            return

        results = []
        for candidate in candidates[:12]:
            result = await self._smoke_test_feature_candidate(candidate)
            results.append(result)

        await self._smoke_test_search_entry(results)
        await self._smoke_test_login_entry(results)

        current_url = getattr(self.page, "url", "")
        if original_url and current_url != original_url:
            try:
                await self.executor.navigate(original_url)
                self.context.add_page(original_url)
            except Exception:
                pass

        passed = sum(1 for item in results if item.get("ok"))
        failed = len(results) - passed
        self.context.add_tested_feature("已知功能冒烟测试")
        self.context.add_event("agent", "已知功能冒烟测试完成", {
            "result_type": "success" if failed == 0 else "partial",
            "passed": passed,
            "failed": failed,
            "results": results,
        })
        print(f"  ✓ 已知功能冒烟测试完成: 通过 {passed} / 失败 {failed}")
        if (user_input or "").lower().find("报告") >= 0 and not from_full_suite:
            await self._generate_report("生成报告 html")

    async def _run_functional_flow_suite(self, original_url: str = ""):
        """Run concrete non-destructive business flows for discovered features."""
        print("\n[业务功能流测试]")
        print("  FunctionalFlowAgent: 对可安全执行的功能做真实操作；需要凭证或会创建数据的步骤会标记为阻塞")

        results: List[Dict[str, Any]] = []
        await self._run_search_functional_flow(results)
        await self._run_article_functional_flow(results)
        await self._run_login_functional_flow(results)
        await self._run_comment_functional_probe(results)
        await self._run_discovered_feature_detail_flows(results)

        if original_url and getattr(self.page, "url", "") != original_url:
            try:
                await self.executor.navigate(original_url)
                self.context.add_page(original_url)
            except Exception:
                pass

        passed = sum(1 for item in results if item.get("status") == "passed")
        blocked = sum(1 for item in results if item.get("status") == "blocked")
        failed = sum(1 for item in results if item.get("status") == "failed")
        self.context.add_tested_feature("业务功能流测试")
        self.context.add_event("agent", "业务功能流测试完成", {
            "result_type": "success" if failed == 0 else "partial",
            "passed": passed,
            "blocked": blocked,
            "failed": failed,
            "results": results,
        })
        print(f"  ✓ 业务功能流测试完成: 通过 {passed} / 阻塞 {blocked} / 失败 {failed}")

    async def _run_search_functional_flow(self, results: List[Dict[str, Any]]) -> None:
        href = self._feature_or_common_href("search", ["/search"])
        if not href:
            self._append_flow_result(results, "搜索功能", "blocked", "未发现搜索入口")
            return

        print("  SearchFlowAgent: 搜索功能 - 输入关键词并校验结果")
        nav = await self.executor.navigate(href)
        if not nav.ok:
            self._append_flow_result(results, "搜索功能", "failed", nav.reason, {"href": href})
            print(f"    ✗ 搜索页打开失败: {nav.reason}")
            return

        keyword = await self._infer_search_keyword()
        fill = await self.executor.fill(description="搜索输入框", text=keyword)
        if not fill.ok:
            fill = await self.executor.fill(description="输入关键词搜索...", text=keyword)
        if not fill.ok:
            self._append_flow_result(results, "搜索功能", "failed", f"找不到搜索输入框: {fill.reason}", {"href": href})
            print(f"    ✗ 找不到搜索输入框: {fill.reason}")
            return

        clicked = await self.executor.click(description="搜索按钮")
        if not clicked.ok:
            clicked = await self.executor.click(description="搜索")
        await self.executor.wait(0.6)

        snapshot = await self.executor.get_snapshot()
        page_text = (snapshot.data.get("text") or "").lower() if snapshot.ok else ""
        current_url = getattr(self.page, "url", "")
        extracted = await self.executor.extract_search_results()
        total = extracted.data.get("total", 0) if extracted.ok else 0
        ok = keyword.lower() in (current_url + " " + page_text).lower() or total > 0
        status = "passed" if ok else "failed"
        reason = f"关键词 {keyword} 搜索完成，结果 {total} 条" if ok else f"搜索后未观察到关键词 {keyword} 或结果列表"
        self._append_flow_result(results, "搜索功能", status, reason, {
            "keyword": keyword,
            "url": current_url,
            "result_count": total,
            "submit_clicked": clicked.ok,
        })
        print(f"    {'✓' if ok else '✗'} {reason}")

        if extracted.ok and total > 0:
            opened = await self._open_first_extracted_search_result(extracted)
            if opened and opened.ok:
                self._append_flow_result(results, "搜索结果文章打开", "passed", opened.summary, opened.data)
                print(f"    ✓ {opened.summary}")
            elif opened:
                self._append_flow_result(results, "搜索结果文章打开", "failed", opened.reason)

    async def _run_article_functional_flow(self, results: List[Dict[str, Any]]) -> None:
        print("  ArticleFlowAgent: 文章阅读 - 打开文章并检查正文")
        current_url = getattr(self.page, "url", "")
        if "/blog/" not in current_url:
            list_href = self._feature_or_common_href("article_list", ["/blog"])
            if not list_href:
                self._append_flow_result(results, "文章阅读", "blocked", "未发现文章列表入口")
                return
            nav = await self.executor.navigate(list_href)
            if not nav.ok:
                self._append_flow_result(results, "文章阅读", "failed", nav.reason, {"href": list_href})
                print(f"    ✗ 文章列表打开失败: {nav.reason}")
                return
            extracted = await self.executor.extract_search_results()
            if not extracted.ok or not extracted.data.get("results"):
                self._append_flow_result(results, "文章阅读", "failed", "文章列表中未提取到文章链接")
                print("    ✗ 文章列表中未提取到文章链接")
                return
            opened = await self._open_first_extracted_search_result(extracted)
            if not opened or not opened.ok:
                self._append_flow_result(results, "文章阅读", "failed", opened.reason if opened else "没有可打开的文章链接")
                print(f"    ✗ 文章打开失败: {opened.reason if opened else '没有可打开的文章链接'}")
                return

        article = await self.executor.extract_article_content()
        data = article.data if article.ok else {}
        text = data.get("text") or ""
        headings = data.get("headings") or []
        ok = bool(data.get("title")) and len(text) >= 80
        status = "passed" if ok else "failed"
        reason = f"文章正文可读取，标题: {data.get('title', '')[:40]}，标题层级 {len(headings)} 个" if ok else "文章标题或正文为空，疑似详情页内容不完整"
        self._append_flow_result(results, "文章阅读", status, reason, {
            "url": data.get("url") or getattr(self.page, "url", ""),
            "title": data.get("title", ""),
            "heading_count": len(headings),
            "text_length": len(text),
        })
        print(f"    {'✓' if ok else '✗'} {reason}")

    async def _run_login_functional_flow(self, results: List[Dict[str, Any]]) -> None:
        href = self._feature_or_common_href("login", ["/login"])
        if not href:
            self._append_flow_result(results, "登录/认证", "blocked", "未发现登录入口")
            return

        print("  AuthFlowAgent: 登录/认证 - 检查字段，若已有凭证则提交并验证")
        nav = await self.executor.navigate(href)
        if not nav.ok:
            self._append_flow_result(results, "登录/认证", "failed", nav.reason, {"href": href})
            print(f"    ✗ 登录页打开失败: {nav.reason}")
            return

        detect = await self.executor.detect_login_page()
        if detect.type == ResultType.NO_AUTH_NEEDED:
            self.context.is_logged_in = True
            self._append_flow_result(results, "登录/认证", "passed", detect.summary or "已检测到登录状态")
            print(f"    ✓ {detect.summary or '已检测到登录状态'}")
            return

        if detect.type != ResultType.ASK_USER:
            self._append_flow_result(results, "登录/认证", "failed", detect.reason or "未识别登录表单")
            print(f"    ✗ {detect.reason or '未识别登录表单'}")
            return

        fields = detect.data.get("required_fields", [])
        probed_register = await self._run_register_probe_from_current_page(results)
        username = self.context.credentials.get("username", "")
        password = self.context.credentials.get("password", "")
        if not (username and password):
            self._append_flow_result(results, "登录/认证", "blocked", f"识别到字段 {', '.join(fields)}，但缺少账号或密码", {"fields": fields})
            print(f"    ! 已识别登录字段: {', '.join(fields)}；缺少凭证，未提交登录")
            return

        if probed_register:
            await self.executor.navigate(href)
        login = await self.executor.login(username, password)
        if login.ok:
            self.context.is_logged_in = True
            self.context.logged_in_user = username
            self._append_flow_result(results, "登录/认证", "passed", login.summary, {"fields": fields})
            print(f"    ✓ {login.summary}")
        else:
            self.context.is_logged_in = False
            self._append_flow_result(results, "登录/认证", "failed", login.reason, {"fields": fields})
            print(f"    ✗ 登录失败: {login.reason}")

    async def _run_comment_functional_probe(self, results: List[Dict[str, Any]]) -> None:
        href = self._feature_or_common_href("comment", ["/guestbook"])
        if not href:
            self._append_flow_result(results, "评论/留言", "blocked", "未发现评论或留言入口")
            return

        print("  CommentFlowAgent: 评论/留言 - 检查前置条件和表单，不自动发布真实评论")
        nav = await self.executor.navigate(href)
        if not nav.ok:
            self._append_flow_result(results, "评论/留言", "failed", nav.reason, {"href": href})
            print(f"    ✗ 评论/留言页打开失败: {nav.reason}")
            return

        auth = await self.executor.extract_auth_requirements()
        forms = await self.executor.extract_forms()
        form_count = forms.data.get("total", 0) if forms.ok else 0
        auth_required = bool(auth.ok and auth.data.get("auth_required"))
        if auth_required and not self.context.is_logged_in:
            self._append_flow_result(results, "评论/留言", "blocked", "页面提示需要登录；未发布评论", {"form_count": form_count})
            print("    ! 页面提示需要登录；未发布评论")
            return
        if form_count > 0:
            self._append_flow_result(results, "评论/留言", "passed", "评论/留言表单存在；已停在提交前，避免创建真实数据", {"form_count": form_count})
            print("    ✓ 评论/留言表单存在；已停在提交前")
            return
        self._append_flow_result(results, "评论/留言", "blocked", "未发现可填写的评论/留言表单", {"form_count": form_count})
        print("    ! 未发现可填写的评论/留言表单")

    async def _run_register_probe_from_current_page(self, results: List[Dict[str, Any]]) -> bool:
        """Probe register links exposed from the current login/auth page."""
        snapshot = await self.executor.get_snapshot()
        if not snapshot.ok:
            return False
        current_url = getattr(self.page, "url", "") or self.context.current_url
        for element in snapshot.data.get("elements") or []:
            href = element.get("href") or ""
            blob = " ".join(str(element.get(key, "")) for key in ("text", "ariaLabel", "label", "href", "id", "name")).lower()
            if not href or not any(term in blob for term in ["注册", "立即注册", "register", "signup", "sign up"]):
                continue
            if href.startswith("/"):
                href = self._join_origin(current_url, href)
            print(f"    RegisterFlowAgent: 注册入口 -> {href}")
            nav = await self.executor.navigate(href)
            if not nav.ok:
                self._append_flow_result(results, "注册入口", "failed", nav.reason, {"href": href})
                print(f"      ✗ 注册入口打开失败: {nav.reason}")
                return True

            register_snapshot = await self.executor.get_snapshot()
            snapshot_data = register_snapshot.data if register_snapshot.ok else {}
            broken_reason = self._page_broken_reason(snapshot_data)
            if broken_reason:
                self._append_flow_result(results, "注册入口", "failed", broken_reason, {"href": href})
                print(f"      ✗ 注册页异常: {broken_reason}")
                return True

            forms = await self.executor.extract_forms()
            fields = [
                field
                for form in (forms.data.get("forms", []) if forms.ok else [])
                for field in form.get("fields", [])
            ]
            input_count = len(fields) or len([
                e for e in snapshot_data.get("elements", [])
                if e.get("tag") in ("input", "textarea", "select")
            ])
            status = "passed" if input_count else "blocked"
            reason = "注册入口可访问，已识别注册表单/输入字段，未提交注册" if input_count else "注册入口可访问，但未发现输入字段"
            self._append_flow_result(results, "注册入口", status, reason, {"href": href, "input_count": input_count})
            print(f"      {'✓' if status == 'passed' else '!'} {reason}")
            return True
        return False

    async def _run_discovered_feature_detail_flows(self, results: List[Dict[str, Any]]) -> None:
        """Visit discovered feature pages and run page-specific assertions."""
        candidates = self._deep_feature_candidates()
        if not candidates:
            return

        print("  DiscoveredFeatureAgent: 发现功能深度测试 - 逐个进入主要功能页并断言页面特征")
        self._nested_feature_seen = set()
        for candidate in candidates:
            label = candidate.get("label", "")
            href = candidate.get("href", "")
            feature = candidate.get("feature", "功能页")
            print(f"    - {feature}: {label} -> {href}")
            nav = await self.executor.navigate(href)
            if not nav.ok:
                self._append_flow_result(results, feature, "failed", nav.reason, {"href": href})
                print(f"      ✗ 打开失败: {nav.reason}")
                continue

            snapshot = await self.executor.get_snapshot()
            snapshot_data = snapshot.data if snapshot.ok else {}
            broken_reason = self._page_broken_reason(snapshot_data)
            if broken_reason:
                self._append_flow_result(results, feature, "failed", broken_reason, {"href": href})
                print(f"      ✗ 页面异常: {broken_reason}")
                continue

            verdict = await self._inspect_deep_feature_page(candidate, snapshot_data)
            self._append_flow_result(results, feature, verdict["status"], verdict["reason"], verdict.get("data", {}))
            marker = "✓" if verdict["status"] == "passed" else ("!" if verdict["status"] == "blocked" else "✗")
            print(f"      {marker} {verdict['reason']}")
            await self._run_nested_feature_checks(candidate, snapshot_data, results)

    def _deep_feature_candidates(self) -> List[Dict[str, str]]:
        site_map = self.context.site_map or {}
        nodes = site_map.get("nodes") or site_map.get("links") or []
        selected: List[Dict[str, str]] = []
        seen: set[str] = set()

        for node in nodes:
            if not node.get("same_origin", True):
                continue
            href = node.get("href", "")
            if not href:
                continue
            label = node.get("text") or self._label_from_href(href)
            if self._is_unsafe_feature_href(label, href):
                continue
            feature = self._classify_deep_feature(label, href)
            if not feature:
                continue
            key = href.split("#")[0]
            if key in seen:
                continue
            seen.add(key)
            selected.append({"label": label[:80], "href": href, "feature": feature})

        priority = {
            "搜索功能": 0,
            "登录/认证": 1,
            "注册入口": 2,
            "留言/评论": 3,
            "博客列表": 4,
            "归档": 5,
            "标签": 6,
            "友链": 7,
            "项目": 8,
            "安全工具": 9,
            "工具箱": 10,
            "游戏": 11,
            "相册": 12,
            "旅行": 13,
            "关于": 14,
            "资源": 15,
            "时间线": 16,
            "碎碎念": 17,
            "RSS": 18,
            "终端/全屏": 19,
        }
        selected.sort(key=lambda item: (priority.get(item["feature"], 99), item["href"]))
        return selected[:24]

    def _classify_deep_feature(self, label: str, href: str) -> str:
        try:
            path = urlparse(href).path.lower()
        except Exception:
            path = href.lower()
        blob = f"{label} {path}".lower()
        checks = [
            ("搜索功能", ["搜索", "search", "/search"]),
            ("登录/认证", ["登录", "login", "signin", "/login"]),
            ("注册入口", ["注册", "register", "signup", "/register"]),
            ("留言/评论", ["留言", "评论", "guestbook", "comment", "/guestbook"]),
            ("博客列表", ["博客", "blog", "/blog"]),
            ("归档", ["归档", "archive", "/archive"]),
            ("标签", ["标签", "tag", "/tags"]),
            ("友链", ["友链", "friends", "/friends"]),
            ("项目", ["项目", "project", "/projects"]),
            ("资源", ["资源", "实用资源", "resource", "/resources"]),
            ("安全工具", ["安全工具", "security tool", "security-tools", "/security"]),
            ("工具箱", ["工具箱", "工具", "tool", "/tools"]),
            ("游戏", ["游戏", "game", "/games"]),
            ("相册", ["相册", "photo", "/photos"]),
            ("旅行", ["旅行", "travel", "/travel"]),
            ("关于", ["关于", "about", "/about"]),
            ("时间线", ["时间线", "成长轨迹", "timeline", "/timeline"]),
            ("碎碎念", ["碎碎念", "notes", "/notes"]),
            ("RSS", ["rss", "/rss"]),
            ("终端/全屏", ["终端", "全屏", "terminal", "/terminal"]),
        ]
        for feature, terms in checks:
            if any(term in blob for term in terms):
                if feature == "博客列表" and "/blog/" in path:
                    return ""
                return feature
        return ""

    def _label_from_href(self, href: str) -> str:
        try:
            path = urlparse(href).path.strip("/")
        except Exception:
            path = href.strip("/")
        return path or "首页"

    async def _run_nested_feature_checks(
        self,
        parent: Dict[str, str],
        snapshot: Dict[str, Any],
        results: List[Dict[str, Any]],
    ) -> None:
        """Open second-level feature entries found inside a discovered feature page."""
        nested = self._nested_feature_candidates(parent, snapshot)
        if not nested:
            return

        print(f"      NestedFeatureAgent: 发现 {len(nested)} 个二级功能入口，继续验证")
        parent_feature = parent.get("feature", "功能页")
        for child in nested:
            label = child.get("label", "")
            href = child.get("href", "")
            feature = child.get("feature", "二级功能")
            print(f"        - {feature}: {label} -> {href}")
            nav = await self.executor.navigate(href)
            if not nav.ok:
                self._append_flow_result(results, f"{parent_feature}/{feature}", "failed", nav.reason, {"href": href})
                print(f"          ✗ 打开失败: {nav.reason}")
                continue

            child_snapshot = await self.executor.get_snapshot()
            child_data = child_snapshot.data if child_snapshot.ok else {}
            broken_reason = self._page_broken_reason(child_data)
            if broken_reason:
                self._append_flow_result(results, f"{parent_feature}/{feature}", "failed", broken_reason, {"href": href})
                print(f"          ✗ 页面异常: {broken_reason}")
                continue

            verdict = await self._inspect_deep_feature_page(child, child_data)
            self._append_flow_result(results, f"{parent_feature}/{feature}", verdict["status"], verdict["reason"], verdict.get("data", {}))
            marker = "✓" if verdict["status"] == "passed" else ("!" if verdict["status"] == "blocked" else "✗")
            print(f"          {marker} {verdict['reason']}")

    def _nested_feature_candidates(self, parent: Dict[str, str], snapshot: Dict[str, Any]) -> List[Dict[str, str]]:
        parent_feature = parent.get("feature", "")
        parent_href = parent.get("href", "")
        parent_path = urlparse(parent_href).path.rstrip("/")
        elements = snapshot.get("elements") or []
        candidates: List[Dict[str, str]] = []
        seen = getattr(self, "_nested_feature_seen", set())

        deep_parent_features = {
            "工具箱", "安全工具", "资源", "项目", "游戏", "相册", "旅行",
            "归档", "标签", "友链", "终端/全屏",
        }
        if parent_feature not in deep_parent_features:
            return []

        for element in elements:
            href = element.get("href") or ""
            label = self._clean_nested_label(element)
            if not href or not label:
                continue
            if href.startswith("#") or href.startswith(("javascript:", "mailto:", "tel:")):
                continue
            resolved = urljoin(parent_href, href)
            if not self._same_origin(parent_href, resolved):
                continue
            parsed = urlparse(resolved)
            if (parsed.path or "/") == "/":
                continue
            child_key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
            if not child_key or child_key == f"{urlparse(parent_href).scheme}://{urlparse(parent_href).netloc}{parent_path}":
                continue
            if child_key in seen:
                continue
            if self._is_unsafe_feature_href(label, resolved):
                continue

            feature = self._classify_deep_feature(label, resolved) or self._classify_nested_feature(parent_feature, label, resolved)
            if not feature:
                continue
            if feature in {"搜索功能", "登录/认证", "博客列表", "留言/评论"} and parent_feature in deep_parent_features:
                continue

            seen.add(child_key)
            candidates.append({"label": label[:80], "href": resolved, "feature": feature})

        self._nested_feature_seen = seen
        limit = 6 if parent_feature in {"工具箱", "安全工具", "资源", "项目", "游戏"} else 3
        candidates.sort(key=lambda item: (self._nested_priority(item), item["href"]))
        return candidates[:limit]

    def _clean_nested_label(self, element: Dict[str, Any]) -> str:
        raw = " ".join(str(element.get(key, "")) for key in ("text", "ariaLabel", "label", "title", "placeholder")).strip()
        raw = re.sub(r"\s+", " ", raw)
        if not raw:
            raw = self._label_from_href(element.get("href", ""))
        return raw[:120]

    def _same_origin(self, left: str, right: str) -> bool:
        try:
            a = urlparse(left)
            b = urlparse(right)
            return bool(a.netloc and b.netloc and a.netloc == b.netloc and a.scheme == b.scheme)
        except Exception:
            return False

    def _classify_nested_feature(self, parent_feature: str, label: str, href: str) -> str:
        path = urlparse(href).path.lower()
        blob = f"{label} {path}".lower()
        if any(term in blob for term in ["安全", "security", "xss", "sql", "jwt", "hash", "加密", "解密", "编码", "解码"]):
            return "安全工具"
        if parent_feature == "工具箱" or "/tools/" in path:
            return "工具子功能"
        if parent_feature == "资源" or "/resources/" in path:
            return "资源子功能"
        if parent_feature == "项目" or "/projects/" in path:
            return "项目子功能"
        if parent_feature == "游戏" or "/games/" in path:
            return "游戏子功能"
        if parent_feature in {"相册", "旅行", "友链", "标签", "归档"}:
            return f"{parent_feature}子功能"
        return ""

    def _nested_priority(self, item: Dict[str, str]) -> int:
        feature = item.get("feature", "")
        label = item.get("label", "")
        blob = f"{feature} {label}".lower()
        if any(term in blob for term in ["安全", "security", "xss", "sql", "jwt"]):
            return 0
        if any(term in blob for term in ["资源", "resource"]):
            return 1
        if "工具" in blob or "tool" in blob:
            return 2
        return 9

    async def _inspect_deep_feature_page(self, candidate: Dict[str, str], snapshot: Dict[str, Any]) -> Dict[str, Any]:
        feature = candidate.get("feature", "")
        elements = snapshot.get("elements") or []
        text = snapshot.get("text") or ""
        href = candidate.get("href", "")
        links = [e for e in elements if e.get("href")]
        inputs = [e for e in elements if e.get("tag") in ("input", "textarea", "select")]
        buttons = [e for e in elements if e.get("tag") == "button" or e.get("role") == "button"]
        blog_links = [
            e for e in links
            if "/blog/" in str(e.get("href", "")) and not str(e.get("href", "")).rstrip("/").endswith("/blog")
        ]
        external_links = [
            e for e in links
            if str(e.get("href", "")).startswith(("http://", "https://"))
            and urlparse(str(e.get("href", ""))).netloc != urlparse(href).netloc
        ]
        data = {
            "href": href,
            "title": snapshot.get("title", ""),
            "text_length": len(text),
            "link_count": len(links),
            "input_count": len(inputs),
            "button_count": len(buttons),
            "blog_link_count": len(blog_links),
            "external_link_count": len(external_links),
        }

        if feature == "登录/认证":
            detect = await self.executor.detect_login_page()
            if detect.type == ResultType.NO_AUTH_NEEDED:
                return {"status": "passed", "reason": detect.summary or "已检测到登录状态", "data": data}
            fields = detect.data.get("required_fields", []) if detect.type == ResultType.ASK_USER else []
            if fields:
                data["fields"] = fields
                return {"status": "passed", "reason": f"登录页字段识别成功: {', '.join(fields)}", "data": data}
            return {"status": "failed", "reason": detect.reason or "登录页未识别账号密码字段", "data": data}

        if feature == "注册入口":
            forms = await self.executor.extract_forms()
            form_count = forms.data.get("total", 0) if forms.ok else 0
            data["form_count"] = form_count
            if form_count or inputs:
                return {"status": "passed", "reason": "注册入口可访问，已识别表单/输入字段，未提交注册", "data": data}
            return {"status": "blocked", "reason": "注册入口可访问，但未发现可填写表单", "data": data}

        if feature == "搜索功能":
            if inputs:
                return {"status": "passed", "reason": f"搜索页可访问，发现 {len(inputs)} 个输入字段", "data": data}
            return {"status": "failed", "reason": "搜索页可访问，但没有搜索输入框", "data": data}

        if feature in {"归档", "标签", "博客列表"}:
            if blog_links:
                return {"status": "passed", "reason": f"{feature}可访问，发现 {len(blog_links)} 个文章链接", "data": data}
            if len(text.strip()) >= 80:
                return {"status": "passed", "reason": f"{feature}可访问，页面内容非空，但未提取到文章链接", "data": data}
            return {"status": "failed", "reason": f"{feature}页面内容过少或无结果", "data": data}

        if feature == "留言/评论":
            auth = await self.executor.extract_auth_requirements()
            forms = await self.executor.extract_forms()
            form_count = forms.data.get("total", 0) if forms.ok else 0
            data["form_count"] = form_count
            data["auth_required"] = bool(auth.ok and auth.data.get("auth_required"))
            if data["auth_required"]:
                return {"status": "passed", "reason": "留言/评论页可访问，正确提示需要登录", "data": data}
            if form_count or inputs:
                return {"status": "passed", "reason": "留言/评论表单存在，未自动提交真实内容", "data": data}
            return {"status": "blocked", "reason": "留言/评论页可访问，但未发现表单或登录提示", "data": data}

        if feature == "友链":
            if external_links:
                return {"status": "passed", "reason": f"友链页可访问，发现 {len(external_links)} 个外部链接", "data": data}
            return {"status": "blocked", "reason": "友链页可访问，但未发现外部链接", "data": data}

        if feature in {
            "安全工具", "工具子功能", "资源子功能", "项目子功能", "游戏子功能",
            "相册子功能", "旅行子功能", "友链子功能", "标签子功能", "归档子功能",
        }:
            enabled_inputs = [item for item in inputs if not item.get("disabled")]
            enabled_buttons = [item for item in buttons if not item.get("disabled")]
            data["enabled_input_count"] = len(enabled_inputs)
            data["enabled_button_count"] = len(enabled_buttons)
            if feature in {"安全工具", "工具子功能"}:
                probe = await self._safe_tool_interaction_probe(enabled_inputs, enabled_buttons)
                if probe:
                    data.update(probe.get("data", {}))
                    return {
                        "status": probe["status"],
                        "reason": probe["reason"],
                        "data": data,
                    }
            if enabled_inputs or enabled_buttons:
                return {
                    "status": "passed",
                    "reason": f"{feature}可访问，发现 {len(enabled_inputs)} 个可用输入框 / {len(enabled_buttons)} 个可用按钮；未提交高风险动作",
                    "data": data,
                }
            if len(text.strip()) >= 40 or links:
                return {"status": "passed", "reason": f"{feature}可访问，页面内容/链接非空", "data": data}
            return {"status": "failed", "reason": f"{feature}页面内容过少，疑似空页面", "data": data}

        if feature in {"项目", "工具箱", "游戏", "相册", "旅行", "关于", "资源", "时间线", "碎碎念", "终端/全屏", "RSS"}:
            if len(text.strip()) >= 40 or links or buttons:
                return {
                    "status": "passed",
                    "reason": f"{feature}页可访问，内容/链接/按钮检查通过",
                    "data": data,
                }
            return {"status": "failed", "reason": f"{feature}页内容过少，疑似空页面", "data": data}

        if len(text.strip()) >= 40:
            return {"status": "passed", "reason": f"{feature}可访问，页面内容非空", "data": data}
        return {"status": "failed", "reason": f"{feature}页面内容过少", "data": data}

    async def _safe_tool_interaction_probe(self, inputs: List[Dict[str, Any]], buttons: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Try a non-destructive interaction on local utility pages."""
        if not inputs or not buttons:
            return None
        button = next((item for item in buttons if self._is_safe_tool_button(item)), None)
        if not button:
            return None

        target_input = inputs[0]
        fill = await self.executor.fill(ref=target_input.get("ref", ""), description="工具输入框", text="test")
        if not fill.ok:
            return {
                "status": "blocked",
                "reason": f"工具页控件存在，但安全测试值填写失败: {fill.reason}",
                "data": {"tool_probe": "fill_failed"},
            }

        click = await self.executor.click(ref=button.get("ref", ""), description=button.get("text") or "工具按钮")
        if not click.ok:
            return {
                "status": "blocked",
                "reason": f"工具页输入框可填写，但安全按钮点击失败: {click.reason}",
                "data": {"tool_probe": "click_failed"},
            }

        await self.executor.wait(0.4)
        snapshot = await self.executor.get_snapshot()
        text_length = len(snapshot.data.get("text", "")) if snapshot.ok else 0
        return {
            "status": "passed",
            "reason": "工具页可交互：已填入安全测试值 test 并触发安全本地按钮",
            "data": {
                "tool_probe": "clicked_safe_button",
                "button_text": button.get("text", ""),
                "post_action_text_length": text_length,
            },
        }

    def _is_safe_tool_button(self, button: Dict[str, Any]) -> bool:
        blob = " ".join(str(button.get(key, "")) for key in ("text", "ariaLabel", "label", "title", "id", "name")).lower()
        unsafe_terms = [
            "扫描", "检测站点", "请求", "发送", "提交", "爆破", "攻击", "删除",
            "上传", "发布", "支付", "scan", "request", "send", "submit",
            "attack", "brute", "delete", "upload", "publish", "pay",
        ]
        if any(term in blob for term in unsafe_terms):
            return False
        safe_terms = [
            "编码", "解码", "转换", "生成", "计算", "解析", "格式化", "复制",
            "加密", "解密", "hash", "base64", "url", "json", "format",
            "convert", "encode", "decode", "generate", "calculate", "parse",
        ]
        return any(term in blob for term in safe_terms)

    def _append_flow_result(
        self,
        results: List[Dict[str, Any]],
        feature: str,
        status: str,
        reason: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        results.append({
            "feature": feature,
            "status": status,
            "ok": status == "passed",
            "reason": reason,
            "data": data or {},
        })

    def _feature_or_common_href(self, feature: str, common_paths: List[str]) -> str:
        href = self._feature_href(feature)
        if href:
            return href
        current_url = self.context.current_url or getattr(self.page, "url", "")
        for path in common_paths:
            joined = self._join_origin(current_url, path)
            if joined:
                return joined
        return ""

    async def _infer_search_keyword(self) -> str:
        snapshot = await self.executor.get_snapshot()
        text = (snapshot.data.get("text") or "").lower() if snapshot.ok else ""
        for candidate in ["linux", "数据库", "python", "test"]:
            if candidate.lower() in text:
                return candidate
        return "test"

    def _known_feature_candidates(self, site_map: Dict[str, Any]) -> List[Dict[str, str]]:
        current_url = self.context.current_url or getattr(self.page, "url", "")
        host = urlparse(current_url or "").netloc or "unknown"
        candidates: List[Dict[str, str]] = []
        seen = set()

        host_map = self.context.known_feature_map.get(host, {})
        for feature, item in host_map.items():
            if not isinstance(item, dict):
                continue
            href = item.get("href", "")
            label = item.get("label") or feature
            self._append_feature_candidate(candidates, seen, label, href, feature)

        for node in site_map.get("nodes") or site_map.get("links") or []:
            if not node.get("same_origin", True):
                continue
            label = node.get("text") or "(无文本入口)"
            href = node.get("href", "")
            feature = self._classify_feature_label(label, href)
            self._append_feature_candidate(candidates, seen, label, href, feature)

        candidates.sort(key=lambda item: self._feature_priority(item.get("feature", ""), item.get("label", ""), item.get("href", "")))
        return candidates

    def _append_feature_candidate(self, candidates: List[Dict[str, str]], seen: set, label: str, href: str, feature: str) -> None:
        if href.startswith("/"):
            href = self._join_origin(self.context.current_url or getattr(self.page, "url", ""), href)
        if not href or self._is_unsafe_feature_href(label, href):
            return
        key = href.split("#")[0]
        if key in seen:
            return
        seen.add(key)
        candidates.append({"label": label[:80], "href": href, "feature": feature})

    def _classify_feature_label(self, label: str, href: str) -> str:
        blob = f"{label} {href}".lower()
        if any(term in blob for term in ["搜索", "search", "查询"]):
            return "search"
        if any(term in blob for term in ["登录", "login", "sign in", "signin"]):
            return "login"
        if any(term in blob for term in ["写文章", "发文章", "write", "new post"]):
            return "write_article"
        if any(term in blob for term in ["评论", "留言", "guestbook", "comment"]):
            return "comment"
        if any(term in blob for term in ["博客", "文章", "blog", "post"]):
            return "article_list"
        if any(term in blob for term in ["管理", "后台", "dashboard", "admin"]):
            return "admin"
        return "navigation"

    def _feature_priority(self, feature: str, label: str, href: str) -> int:
        order = {
            "search": 0,
            "article_list": 1,
            "login": 2,
            "comment": 3,
            "write_article": 4,
            "admin": 5,
            "navigation": 9,
        }
        return order.get(feature, 9)

    def _is_unsafe_feature_href(self, label: str, href: str) -> bool:
        blob = f"{label} {href}".lower()
        unsafe_terms = [
            "logout",
            "退出",
            "注销",
            "delete",
            "remove",
            "删除",
            "支付",
            "付款",
            "pay",
            "order",
            "下单",
            "购买",
            "上传",
            "upload",
            "javascript:",
            "mailto:",
        ]
        return any(term in blob for term in unsafe_terms)

    async def _smoke_test_feature_candidate(self, candidate: Dict[str, str]) -> Dict[str, Any]:
        label = candidate.get("label") or candidate.get("feature") or candidate.get("href")
        href = candidate.get("href", "")
        feature = candidate.get("feature", "navigation")
        print(f"  FeatureTestAgent: {label} -> {href}")
        result = await self.executor.navigate(href)
        if result.type != ResultType.SUCCESS:
            print(f"    ✗ 打开失败: {result.reason}")
            self.context.add_event("agent", f"功能入口失败: {label}", {"result_type": "failure", "href": href, "reason": result.reason})
            return {"feature": feature, "label": label, "href": href, "ok": False, "reason": result.reason}

        snapshot = await self.executor.get_snapshot()
        snapshot_data = snapshot.data if snapshot.type == ResultType.SUCCESS else {}
        broken_reason = self._page_broken_reason(snapshot_data)
        if broken_reason:
            print(f"    ✗ 页面异常: {broken_reason}")
            self.context.add_event("agent", f"功能入口异常: {label}", {"result_type": "failure", "href": href, "reason": broken_reason})
            return {"feature": feature, "label": label, "href": href, "ok": False, "reason": broken_reason}

        print(f"    ✓ 可访问，标题: {snapshot_data.get('title') or result.data.get('title', '')}")
        self.context.add_event("agent", f"功能入口通过: {label}", {"result_type": "success", "href": href, "feature": feature})
        return {"feature": feature, "label": label, "href": href, "ok": True}

    def _page_broken_reason(self, snapshot: Dict[str, Any]) -> str:
        title = (snapshot.get("title") or "").lower()
        text = (snapshot.get("text") or "").lower()
        elements = snapshot.get("elements") or []
        if "404" in title or "not found" in title:
            return "标题显示 404/not found"
        if any(term in text for term in ["404: this page could not be found", "page could not be found", "页面不存在"]):
            return "页面正文显示不存在"
        if not text.strip() and len(elements) == 0:
            return "页面内容为空"
        return ""

    async def _smoke_test_search_entry(self, results: List[Dict[str, Any]]) -> None:
        search_href = self._feature_href("search")
        if not search_href:
            return
        print("  FeatureTestAgent: 搜索功能字段检查")
        nav = await self.executor.navigate(search_href)
        if not nav.ok:
            results.append({"feature": "search", "label": "搜索", "href": search_href, "ok": False, "reason": nav.reason})
            return
        snapshot = await self.executor.get_snapshot()
        elements = snapshot.data.get("elements", []) if snapshot.type == ResultType.SUCCESS else []
        has_input = any(
            e.get("tag") in ("input", "textarea")
            and any(term in " ".join(str(e.get(key, "")) for key in ("placeholder", "label", "ariaLabel", "name", "id")).lower() for term in ["搜索", "search", "查询"])
            for e in elements
        )
        results.append({"feature": "search", "label": "搜索字段", "href": search_href, "ok": has_input, "reason": "" if has_input else "未找到搜索输入框"})
        print("    ✓ 搜索输入框存在" if has_input else "    ✗ 未找到搜索输入框")

    async def _smoke_test_login_entry(self, results: List[Dict[str, Any]]) -> None:
        login_href = self._feature_href("login")
        if not login_href:
            return
        print("  FeatureTestAgent: 登录功能字段检查")
        nav = await self.executor.navigate(login_href)
        if not nav.ok:
            results.append({"feature": "login", "label": "登录", "href": login_href, "ok": False, "reason": nav.reason})
            return
        auth = await self.executor.detect_login_page()
        if auth.type == ResultType.NO_AUTH_NEEDED:
            fields = ["已登录"]
        elif auth.type == ResultType.ASK_USER:
            fields = auth.data.get("required_fields", [])
        else:
            fields = []
        ok = bool(fields)
        results.append({"feature": "login", "label": "登录字段", "href": login_href, "ok": ok, "fields": fields, "reason": "" if ok else "未识别登录字段"})
        print(f"    ✓ 登录字段: {', '.join(fields)}" if ok else "    ✗ 未识别登录字段")

    async def _run_quality_audit(self, user_input: str):
        """Run page quality/a11y/basic safety audit."""
        url = self._extract_url(user_input)
        if url:
            nav_result = await self._handle_navigate(url)
            if not nav_result or not nav_result.ok:
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：页面质量检查 http://example.com")
            return

        print("\n[页面质量检查]")
        print("  QualityAuditAgent: 检查无障碍、基础 SEO、链接和表单安全")
        result = await self.executor.quality_audit()
        if result.type != ResultType.SUCCESS:
            print(f"  ✗ 页面质量检查失败: {result.reason}")
            return

        self.context.add_tested_feature("页面质量检查")
        self.context.add_event("agent", result.summary, {"tool": "quality_audit"})
        self._print_quality_report(result.data)

    def _print_quality_report(self, data: Dict[str, Any]):
        summary = data.get("summary", {})
        raw = data.get("raw", {})
        print(f"  评分: {summary.get('score', 0)}/100")
        print(f"  Title: {raw.get('title') or '(缺失)'}")
        print(f"  lang: {raw.get('lang') or '(缺失)'} | viewport: {'有' if raw.get('hasViewport') else '缺失'}")
        issues = summary.get("issues") or []
        if issues:
            print("  问题:")
            for issue in issues[:12]:
                print(f"    - {issue}")
        else:
            print("  未发现基础质量问题")
        print("  建议:")
        for recommendation in summary.get("recommendations", []):
            print(f"    - {recommendation}")

    async def _run_performance_audit(self, user_input: str):
        """Run a deterministic performance audit tool."""
        url = self._extract_url(user_input)
        if url:
            nav_result = await self._handle_navigate(url)
            if not nav_result or not nav_result.ok:
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：性能测试 http://example.com")
            return

        runs = self._extract_performance_runs(user_input)
        reload = any(term in user_input.lower() for term in ["reload", "刷新", "重新加载", "冷启动"])

        print("\n[性能测试]")
        print("  PerformanceAgent: 采集 Navigation Timing / Paint / Resource 指标")
        result = await self.executor.performance_audit(runs=runs, reload=reload)
        if result.type != ResultType.SUCCESS:
            print(f"  ✗ 性能测试失败: {result.reason}")
            return

        self.context.add_tested_feature("性能测试")
        self.context.add_event("agent", result.summary, {"tool": "performance_audit"})
        self._print_performance_report(result.data)

    def _extract_performance_runs(self, text: str) -> int:
        match = re.search(r"(\d+)\s*(?:次|遍|轮|runs?)", text or "", re.IGNORECASE)
        if not match:
            return 1
        return max(1, min(int(match.group(1)), 5))

    def _print_performance_report(self, data: Dict[str, Any]):
        summary = data.get("summary", {})
        average = summary.get("average", {})
        rating_map = {
            "good": "良好",
            "needs_attention": "需要关注",
            "poor": "较差",
        }
        print(f"  评分: {summary.get('score', 0)}/100 ({rating_map.get(summary.get('rating'), summary.get('rating', 'unknown'))})")
        print(f"  平均 TTFB: {average.get('ttfb', 0)} ms")
        print(f"  DOMContentLoaded: {average.get('domContentLoaded', 0)} ms")
        print(f"  Load: {average.get('load', 0)} ms")
        fcp = summary.get("firstContentfulPaint") or 0
        if fcp:
            print(f"  FCP: {fcp} ms")
        print(f"  资源请求: {summary.get('resourceCount', 0)} 个")
        print(f"  传输体积: {self._format_bytes(summary.get('transferSize', 0))}")

        slow = summary.get("slowResources") or []
        if slow:
            print("  慢资源 Top:")
            for item in slow[:5]:
                name = item.get("name", "")
                short = name[-80:] if len(name) > 80 else name
                print(f"    - {item.get('duration', 0)} ms | {item.get('initiatorType', 'other')} | {short}")

        print("  建议:")
        for recommendation in summary.get("recommendations", []):
            print(f"    - {recommendation}")

    def _format_bytes(self, value: Any) -> str:
        size = float(value or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{size:.1f} GB"

    async def _generate_and_show_test_plan(self, auto: bool = False):
        if not self._has_open_page():
            print("  请先打开一个网站，再生成测试计划。")
            return
        snapshot = await self.executor.get_snapshot()
        if snapshot.type != ResultType.SUCCESS:
            print(f"  ✗ 无法获取页面快照: {snapshot.reason}")
            return
        source = "AI"
        plan = await self._generate_ai_test_plan(snapshot.data)
        if not plan:
            source = "页面结构规则"
            plan = [item.to_dict() for item in self.test_plan_generator.generate(snapshot.data)]
        self.context.test_plan = plan
        self.context.add_event("agent", "生成测试计划", {"items": len(plan), "source": source})
        title = "[自动测试计划]" if auto else "[测试计划]"
        print(f"\n{title} ({source})")
        print("  功能点 | 前置条件 | 步骤 | 预期结果 | 风险 | 需登录")
        for index, item in enumerate(plan, 1):
            steps = " -> ".join(item.get("steps") or [])
            print(
                f"  {index}. {item.get('feature')} | {item.get('precondition')} | "
                f"{steps} | {item.get('expected')} | {item.get('risk')} | "
                f"{'是' if item.get('needs_login') else '否'}"
            )

    async def _generate_ai_test_plan(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ask the model for a site-specific test matrix. Falls back on failure."""
        prompt = f"""你是资深软件测试工程师。请基于当前页面快照，为这个具体网站生成测试矩阵。

要求:
1. 不要输出通用模板，要结合页面标题、URL、文本和元素判断业务类型。
2. 每条用例必须包含: feature, precondition, steps, expected, risk, needs_login。
3. risk 只能是: 高/中/低。
4. steps 是字符串数组，3-6 步。
5. 只输出 JSON，不要 Markdown。

当前页面快照:
{self._format_snapshot_for_test_plan(snapshot)}

输出 JSON schema:
{{
  "items": [
    {{
      "feature": "功能点名称",
      "precondition": "前置条件",
      "steps": ["步骤1", "步骤2", "步骤3"],
      "expected": "预期结果",
      "risk": "高",
      "needs_login": false
    }}
  ]
}}
"""
        try:
            response = await self.ai_client.complete(prompt, "")
            payload = extract_json_payload(response)
            return self._normalize_test_plan_items((payload or {}).get("items", []))
        except Exception:
            return []

    def _format_snapshot_for_test_plan(self, snapshot: Dict[str, Any]) -> str:
        elements = snapshot.get("elements") or []
        lines = [
            f"URL: {snapshot.get('url', '')}",
            f"标题: {snapshot.get('title', '')}",
            f"可见文本摘要: {(snapshot.get('text') or '')[:1200]}",
            "可交互元素:",
        ]
        for element in elements[:60]:
            bits = [
                f"- {element.get('ref', '')} <{element.get('tag', '')}>",
                f"text='{(element.get('text') or '')[:80]}'",
            ]
            for key in ("placeholder", "label", "ariaLabel", "href", "type", "role"):
                value = element.get(key)
                if value:
                    bits.append(f"{key}='{str(value)[:100]}'")
            lines.append(" ".join(bits))
        return "\n".join(lines)

    def _normalize_test_plan_items(self, items: Any) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            return []
        normalized = []
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            feature = str(item.get("feature") or item.get("功能点") or "").strip()
            if not feature:
                continue
            steps = item.get("steps") or item.get("测试步骤") or []
            if isinstance(steps, str):
                steps = [part.strip() for part in re.split(r"->|;|；|\n", steps) if part.strip()]
            if not isinstance(steps, list):
                steps = []
            risk = str(item.get("risk") or item.get("风险") or "中").strip()
            if risk not in {"高", "中", "低"}:
                risk = "中"
            needs_login = item.get("needs_login", item.get("是否需要登录", False))
            if isinstance(needs_login, str):
                needs_login = needs_login.strip().lower() in {"true", "yes", "y", "1", "是", "需要"}
            normalized.append({
                "feature": feature,
                "precondition": str(item.get("precondition") or item.get("前置条件") or "已打开目标页面").strip(),
                "steps": [str(step).strip() for step in steps if str(step).strip()][:6],
                "expected": str(item.get("expected") or item.get("预期结果") or "功能表现符合预期").strip(),
                "risk": risk,
                "needs_login": bool(needs_login),
            })
        return normalized

    async def _generate_report(self, text: str):
        fmt = "markdown"
        for candidate in ("html", "json", "junit", "markdown", "md"):
            if re.search(rf"\b{candidate}\b", text, re.IGNORECASE):
                fmt = candidate
                break
        context_data = self.context.to_dict(redact=True)
        context_data["network"] = self.network_recorder.summary()
        if "all" in text.lower() or "全部" in text:
            paths = []
            for item in ("markdown", "html", "json", "junit"):
                paths.append(self.reporter.write(context_data, item, self.context.session_name))
            self.context.reports.extend(str(path) for path in paths)
            print("  ✓ 已生成全部报告:")
            for path in paths:
                print(f"    - {path}")
            return
        path = self.reporter.write(context_data, fmt, self.context.session_name)
        self.context.reports.append(str(path))
        self.context.add_event("agent", f"生成报告 {fmt}", {"path": str(path)})
        print(f"  ✓ 报告已生成: {path}")

    async def _generate_test_cases(self, text: str):
        if not self.context.test_plan:
            await self._generate_and_show_test_plan()
        if not self.context.test_plan:
            return
        name = self._name_after_keyword(text, ["保存测试用例", "导出测试用例", "生成测试用例", "test case"]) or self.context.session_name
        cases = self.case_manager.from_plan(self.context.test_plan, module=self.context.current_title or "Web")
        paths = self.case_manager.save(name, cases)
        record = {"name": name, "total": len(cases), "paths": paths, "created_at": datetime.now().isoformat(timespec="seconds")}
        self.context.test_cases.append(record)
        self.context.artifacts.extend(paths.values())
        self.context.add_event("agent", "生成测试用例", record)
        print("\n[测试用例中心]")
        print(f"  ✓ 已生成 {len(cases)} 条测试用例")
        print(f"  JSON: {paths['json']}")
        print(f"  Markdown: {paths['markdown']}")
        print(f"  CSV/Excel: {paths['csv']}")
        print(f"  Excel: {paths['xlsx']}")

    def _list_managed_test_cases(self):
        items = self.case_manager.list_cases()
        print("\n[用例列表]")
        if not items:
            print("  暂无本地用例。可以先说：生成测试用例")
            return
        for index, item in enumerate(items[:30], 1):
            print(f"  {index}. {item['name']} | {item['total']} 条 | {item['updated_at']} | {item['path']}")

    async def _run_managed_test_case(self, text: str):
        name = self._name_after_keyword(text, ["运行用例", "执行用例", "run case"]) or self._extract_any_file_path(text, [".json"]) or ""
        if not name:
            print("  请指定用例名或 JSON 路径，例如：运行用例 login-case")
            return
        try:
            payload = self.case_manager.load(name)
        except Exception as e:
            print(f"  ✗ 加载用例失败: {e}")
            return
        cases = payload.get("cases") or []
        print(f"\n[运行测试用例] {payload.get('name')} | {len(cases)} 条")
        executed = 0
        for case in cases:
            steps = case.get("steps") or []
            if not steps:
                continue
            task = "，然后".join(str(step) for step in steps[:6])
            print(f"  Case: {case.get('feature')} -> {task}")
            await self._run_planned_task(task)
            case["execution_result"] = "executed"
            executed += 1
        record = {"name": payload.get("name"), "executed": executed, "path": payload.get("path")}
        self.context.test_cases.append(record)
        self.context.add_event("agent", "运行测试用例", record)
        print(f"  ✓ 用例执行完成: {executed}/{len(cases)}")

    async def _generate_cases_from_requirement(self, text: str):
        path = self._extract_any_file_path(text, [".md", ".txt"])
        if not path:
            print("  请提供需求文档路径，例如：根据需求文档 docs/login.md 生成测试用例")
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
        except Exception as e:
            print(f"  ✗ 读取需求文档失败: {e}")
            return
        name = Path(path).stem + "-cases"
        cases = self.case_manager.from_requirements(content, module=Path(path).stem)
        paths = self.case_manager.save(name, cases)
        record = {"name": name, "source": path, "total": len(cases), "paths": paths}
        self.context.test_cases.append(record)
        self.context.artifacts.extend(paths.values())
        self.context.add_event("agent", "根据需求文档生成测试用例", record)
        print("\n[需求文档 -> 测试用例]")
        print(f"  ✓ 已从需求文档生成 {len(cases)} 条用例")
        print(f"  Markdown: {paths['markdown']}")
        print(f"  CSV/Excel: {paths['csv']}")
        print(f"  Excel: {paths['xlsx']}")

    def _create_defect_ticket(self, text: str):
        context_data = self.context.to_dict(redact=True)
        context_data["network"] = self.network_recorder.summary()
        severity = self._extract_severity(text)
        title = self._name_after_keyword(text, ["生成缺陷", "创建缺陷", "提bug", "提 bug", "bug单", "defect"])
        defect = self.defect_manager.create(context_data, title=title, severity=severity)
        self.context.defects.append(defect)
        self.context.artifacts.append(defect["path"])
        self.context.add_event("agent", "生成缺陷单", defect)
        print("\n[缺陷单]")
        print(f"  ✓ 已生成 {defect['id']}: {defect['title']}")
        print(f"  严重级别: {defect['severity']}")
        print(f"  路径: {defect['path']}")

    def _run_postman_collection(self, text: str):
        path = self._extract_any_file_path(text, [".json"])
        if not path:
            print("  请提供 Postman Collection JSON，例如：运行Postman ./collection.json")
            return
        try:
            env_path = self._extract_env_file_path(text)
            result = self.postman_runner.run(path, env_path=env_path or "")
        except Exception as e:
            print(f"  ✗ Postman Collection 执行失败: {e}")
            return
        self.context.api_runs.append(result)
        self.context.artifacts.append(result["report_path"])
        self.context.add_event("agent", "运行 Postman Collection", result)
        print("\n[Postman/API 测试]")
        print(f"  Collection: {result['name']}")
        print(f"  总数: {result['total']} | 通过: {result['passed']} | 失败: {result['failed']} | 耗时: {result['duration_ms']} ms")
        print(f"  报告: {result['report_path']}")
        if result.get("variables"):
            print(f"  变量: {', '.join(result['variables'])}")

    def _run_pytest_regression(self, text: str):
        path = self._extract_any_file_path(text, [".py"]) or "tests"
        if not Path(path).exists():
            print(f"  ✗ pytest 路径不存在: {path}")
            return
        command = ["python", "-B", "-m", "pytest", path, "-q"]
        print("\n[pytest 回归]")
        print(f"  执行: {' '.join(command)}")
        try:
            completed = subprocess.run(command, cwd=str(Path.cwd()), capture_output=True, text=True, timeout=120, check=False)
        except Exception as e:
            print(f"  ✗ pytest 执行失败: {e}")
            return
        result = {
            "command": " ".join(command),
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "")[-4000:],
            "stderr": (completed.stderr or "")[-2000:],
        }
        self.context.add_event("agent", "运行 pytest 回归", result)
        print(f"  {'✓' if completed.returncode == 0 else '✗'} returncode={completed.returncode}")
        output = (completed.stdout or completed.stderr or "").strip()
        if output:
            print("  输出摘要:")
            for line in output.splitlines()[-12:]:
                print(f"    {line[:180]}")

    def _handle_sql_check(self, text: str):
        if "配置" in text and "mysql" in text.lower():
            config = self._parse_key_values(text, ["host", "port", "user", "password", "database"])
            if not config:
                print("  配置格式示例: 配置MySQL host=127.0.0.1 port=3306 user=root password=xxx database=test")
                return
            config_path = Path.home() / ".testforge" / "mysql.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ MySQL 配置已保存: {config_path}")
            return

        built = self.sql_workbench.build(text)
        result = {"sql": built["sql"], "readonly": built["readonly"], "executed": False}
        if any(term in text for term in ["执行", "运行", "execute"]):
            config_path = Path.home() / ".testforge" / "mysql.json"
            if config_path.exists():
                config = json.loads(config_path.read_text(encoding="utf-8"))
                exec_result = self.sql_workbench.execute(built["sql"], config)
                result.update(exec_result)
                result["executed"] = True
            else:
                result["warning"] = "未找到 ~/.testforge/mysql.json，仅生成 SQL"
        self.context.sql_checks.append(result)
        self.context.add_event("agent", "SQL/数据库校验", result)
        print("\n[MySQL/SQL 校验]")
        print(f"  SQL: {built['sql']}")
        if result.get("executed"):
            if result.get("ok"):
                print(f"  ✓ 执行成功，影响/返回行数: {result.get('rowcount', 0)}")
            else:
                print(f"  ✗ 执行失败: {result.get('error')}")
        else:
            print("  提示: 如需真实执行，先配置 MySQL，然后说：执行SQL select ...")

    def _export_jmeter_plan(self, text: str):
        url = self._extract_url(text) or self.context.current_url or getattr(self.page, "url", "")
        if not url or url == "about:blank":
            print("  请指定 URL，例如：生成JMeter脚本 http://example.com 线程10 循环20")
            return
        threads = self._extract_number_after(text, ["线程", "threads"], default=10)
        loops = self._extract_number_after(text, ["循环", "loops"], default=10)
        name = self._name_after_keyword(text, ["生成jmeter", "导出jmx", "jmeter脚本", "jmeter"]) or self.context.session_name
        expected_status = self._extract_number_after(text, ["状态码", "status"], default=200)
        csv_path = self._extract_any_file_path(text, [".csv"]) or ""
        path = self.jmeter_exporter.export(
            url,
            name=name,
            threads=threads,
            loops=loops,
            expected_status=expected_status,
            csv_path=csv_path,
        )
        record = {"url": url, "threads": threads, "loops": loops, "expected_status": expected_status, "csv": csv_path, "path": str(path)}
        self.context.jmeter_plans.append(record)
        self.context.artifacts.append(str(path))
        self.context.add_event("agent", "生成 JMeter JMX", record)
        print("\n[JMeter 脚本]")
        print(f"  ✓ 已导出 JMX: {path}")
        print(f"  线程: {threads} | 循环: {loops} | 状态码断言: {expected_status} | URL: {url}")
        if csv_path:
            print(f"  CSV 数据集: {csv_path}")

    def _run_environment_check(self, text: str):
        scope = "all"
        lower = text.lower()
        if "docker" in lower:
            scope = "docker"
        elif "k8s" in lower or "kubectl" in lower:
            scope = "k8s"
        elif "linux" in lower:
            scope = "linux"
        elif "git" in lower:
            scope = "git"
        result = self.environment_inspector.inspect(scope=scope, cwd=str(Path.cwd()))
        self.context.environment_checks.append(result)
        self.context.add_event("agent", "环境检查", result)
        print("\n[环境检查]")
        for item in result["results"]:
            status = "✓" if item.get("ok") else "✗"
            print(f"  {status} {item.get('command')}")
            output = (item.get("stdout") or item.get("stderr") or item.get("error") or "").strip()
            if output:
                first_line = output.splitlines()[0][:180]
                print(f"    {first_line}")

    def _run_environment_logs(self, text: str):
        lower = text.lower()
        kind = "k8s" if "k8s" in lower or "kubectl" in lower else "docker"
        target = self._name_after_keyword(text, ["docker日志", "docker logs", "k8s日志", "kubectl logs", "查看最近日志"])
        if not target:
            print("  请指定日志目标，例如：docker日志 container_name 或 k8s日志 pod_name")
            return
        result = self.environment_inspector.logs(target, kind=kind, cwd=str(Path.cwd()))
        self.context.environment_checks.append(result)
        self.context.add_event("agent", "环境日志检查", result)
        print("\n[环境日志]")
        for item in result["results"]:
            status = "✓" if item.get("ok") else "✗"
            print(f"  {status} {item.get('command')}")
            output = (item.get("stdout") or item.get("stderr") or item.get("error") or "").strip()
            if output:
                for line in output.splitlines()[-10:]:
                    print(f"    {line[:180]}")

    def _compare_regression(self, text: str):
        name = self._session_name_after_command(text) or self._name_after_keyword(text, ["回归对比", "对比会话", "compare regression"])
        if not name:
            sessions = self.session_store.list()
            name = next((item["name"] for item in sessions if item["name"] != self.context.session_name), "")
        if not name:
            print("  请指定要对比的会话，例如：回归对比 blog-test")
            return
        try:
            previous = self.session_store.load(name)
        except FileNotFoundError as e:
            print(f"  ✗ {e}")
            return
        result = self.regression_comparer.compare(previous, self.context.to_dict(redact=True))
        self.context.regression_results.append(result)
        self.context.add_event("agent", "回归对比", result)
        print("\n[回归对比]")
        print(f"  基线会话: {result['previous_session']} -> 当前会话: {result['current_session']}")
        print(f"  失败数: {result['previous_failures']} -> {result['current_failures']}")
        print(f"  新增失败: {result['new_failures']} | 已修复失败: {result['fixed_failures']}")
        if result["new_tested_features"]:
            print(f"  新增已测功能: {', '.join(result['new_tested_features'][:8])}")
        if result.get("new_pages"):
            print(f"  新增页面: {len(result['new_pages'])}")
        if result.get("performance_delta"):
            print(f"  性能差异: {result['performance_delta']}")

    def _show_network_report(self):
        summary = self.network_recorder.summary()
        self.context.add_event("agent", "查看网络/API日志", summary)
        print("\n[网络/API 检查]")
        print(f"  请求总数: {summary['total']} | API-like: {summary['api_like']} | 失败: {summary['failed']}")
        print(f"  状态码: {summary['status_counts']}")
        if summary["slow"]:
            print("  慢请求 Top:")
            for record in summary["slow"][:8]:
                print(f"    - {record.get('duration')} ms | {record.get('status')} | {record.get('method')} {record.get('url')}")
        if summary["recent_api"]:
            print("  最近接口:")
            for record in summary["recent_api"][-8:]:
                print(f"    - {record.get('status')} | {record.get('duration')} ms | {record.get('url')}")

    def _generate_test_data(self, text: str):
        kind = "comment"
        if any(term in text for term in ["用户", "账号", "username", "user"]):
            kind = "user"
        elif any(term in text for term in ["邮箱", "email"]):
            kind = "email"
        elif any(term in text for term in ["文章", "article"]):
            kind = "article"
        data = self.data_manager.generate(kind)
        self.context.generated_data.append(data)
        self.context.add_event("agent", f"生成测试数据 {kind}", data)
        print("\n[测试数据]")
        for key, value in data.items():
            print(f"  {key}: {value}")

    async def _generate_site_map(self):
        if not self._has_open_page():
            print("  请先打开一个页面，再生成站点地图。")
            return
        site_map = await build_site_map(self.page)
        self.context.site_map = site_map
        self.context.add_event("agent", "生成站点地图", {"total": site_map.get("total", 0)})
        print("\n[站点地图]")
        print(f"  Root: {site_map.get('root')}")
        for node in site_map.get("nodes", [])[:30]:
            marker = "站内" if node.get("same_origin") else "站外"
            print(f"  - [{marker}] {node.get('text') or '(无文本)'} -> {node.get('href')}")

    async def _run_plan_explore(self, text: str):
        url = self._extract_url(text)
        if url:
            nav_result = await self._handle_navigate(url)
            if not nav_result or not nav_result.ok:
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：探索站点 http://example.com 深度2 页面20")
            return

        current_url = self.context.current_url or getattr(self.page, "url", "")
        depth, max_pages, mode, include_patterns, exclude_patterns = self._parse_explore_options(text, current_url)
        scope = UrlScope(
            base_url=current_url,
            mode=mode,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )

        print("\n[站点深度探索]")
        print(f"  ExploreAgent: URL Scope={scope.mode} | 深度={depth} | 页面上限={max_pages}")
        if scope.include_patterns:
            print(f"  Include: {', '.join(scope.include_patterns)}")
        if scope.exclude_patterns:
            print(f"  Exclude: {', '.join(scope.exclude_patterns)}")

        result = await explore_site_map(self.page, scope=scope, max_depth=depth, max_pages=max_pages)
        artifact_dir = write_exploration_artifacts(result, self.context.session_name)
        self.context.site_map = result.get("graph", {})
        self.context.artifacts.append(str(artifact_dir))
        self.context.add_event("agent", "站点深度探索", {"stats": result.get("stats", {}), "artifactDir": str(artifact_dir)})

        stats = result.get("stats", {})
        print(f"  页面: {stats.get('pagesVisited', 0)} | 链接: {stats.get('linksFound', 0)} | 表单: {stats.get('formsFound', 0)} | 元素: {stats.get('elementsFound', 0)}")
        print(f"  最大深度: {stats.get('maxDepthReached', 0)}")
        print(f"  ✓ 探索产物已保存: {artifact_dir}")
        for page_node in result.get("graph", {}).get("pages", [])[:10]:
            print(f"  - d{page_node.get('depth', 0)} {page_node.get('title') or '(无标题)'} -> {page_node.get('url')}")

    def _parse_explore_options(self, text: str, current_url: str):
        depth = 2
        max_pages = 20
        mode = "site"

        depth_match = re.search(r"(?:深度|depth)\s*[:：=]?\s*(\d+)", text, re.I)
        if depth_match:
            depth = int(depth_match.group(1))

        page_match = re.search(r"(?:页面|pages?|max-pages|max pages)\s*[:：=]?\s*(\d+)", text, re.I)
        if page_match:
            max_pages = int(page_match.group(1))

        lower = text.lower()
        if "single_page" in lower or "single-page" in lower or "单页" in lower:
            mode = "single_page"
        elif "focused" in lower or "聚焦" in lower:
            mode = "focused"

        include_patterns = self._extract_scope_patterns(text, ["include", "包含", "白名单"])
        exclude_patterns = self._extract_scope_patterns(text, ["exclude", "排除", "黑名单"])

        if mode in {"focused", "single_page"} and not include_patterns:
            parsed = urlparse(current_url)
            relative = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "") + (f"#{parsed.fragment}" if parsed.fragment else "")
            include_patterns = [relative.rstrip("*") + "*"]

        return max(0, min(depth, 5)), max(1, min(max_pages, 100)), mode, include_patterns, exclude_patterns

    def _extract_scope_patterns(self, text: str, keys: List[str]) -> List[str]:
        patterns: List[str] = []
        for key in keys:
            for match in re.finditer(rf"{re.escape(key)}\s*[:：=]\s*([^\s]+)", text, re.I):
                raw = match.group(1).strip().strip('"\'')
                patterns.extend([part.strip() for part in raw.split(",") if part.strip()])
        return patterns[:20]

    def _export_interactive_ir(self, text: str):
        from ..runner.exporter import export_from_ir

        export_dir = "tests/testforge"
        dir_match = re.search(r"(?:到|to|dir|目录)\s*[:：=]?\s*([^\s]+)", text, re.I)
        if dir_match:
            export_dir = dir_match.group(1).strip().strip('"\'')

        result = export_from_ir(
            cwd=str(Path.cwd()),
            run_id=self.context.run_id,
            spec_path="interactive",
            export_dir=export_dir,
            base_url=self._infer_base_url(),
        )
        if result.get("ok"):
            self.context.artifacts.append(result["path"])
            self.context.add_event("agent", "导出 Playwright 用例", {"path": result["path"]})
            print(f"  ✓ 已导出 Playwright 用例: {result['path']}")
        else:
            print(f"  ✗ 导出失败: {result.get('message')}")
            print(f"  IR 路径: {self.ir_writer.path}")

    async def _save_visual_baseline(self, text: str):
        if not self._has_open_page():
            print("  请先打开一个页面，再保存视觉基线。")
            return
        name = self._name_after_visual_command(text) or self.context.session_name
        path = await self.visual.save_baseline(self.page, name)
        self.context.visual_results.append({"action": "baseline", "name": name, "path": str(path)})
        self.context.add_event("agent", f"保存视觉基线 {name}", {"path": str(path)})
        print(f"  ✓ 视觉基线已保存: {path}")

    async def _compare_visual_baseline(self, text: str):
        if not self._has_open_page():
            print("  请先打开一个页面，再做视觉对比。")
            return
        name = self._name_after_visual_command(text) or self.context.session_name
        try:
            result = await self.visual.compare(self.page, name)
        except FileNotFoundError as e:
            print(f"  ✗ {e}")
            return
        self.context.visual_results.append(result)
        self.context.add_event("agent", f"视觉回归对比 {name}", result)
        print("\n[视觉回归]")
        print(f"  基线: {result.get('baseline')}")
        print(f"  当前: {result.get('current')}")
        print(f"  差异: {result.get('diff_percent')}% | {'通过' if result.get('passed') else '不通过'}")

    def _name_after_visual_command(self, text: str) -> str:
        cleaned = re.sub(r"^(保存基线|保存视觉基线|视觉对比|视觉回归|visual baseline|save baseline|compare baseline|visual compare)\s*[:：]?", "", text.strip(), flags=re.I)
        return cleaned.strip().strip('"\'')

    async def _run_security_audit(self, text: str):
        url = self._extract_url(text)
        if url:
            nav_result = await self._handle_navigate(url)
            if not nav_result or not nav_result.ok:
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：安全检查 http://example.com")
            return
        print("\n[安全基础测试]")
        result = await self.executor.security_audit()
        if not result.ok:
            print(f"  ✗ 安全检查失败: {result.reason}")
            return
        self.context.add_tested_feature("安全基础测试")
        self.context.add_event("agent", result.summary, {"tool": "security_audit"})
        self._print_audit_summary(result.data)

    async def _run_accessibility_audit(self, text: str):
        url = self._extract_url(text)
        if url:
            nav_result = await self._handle_navigate(url)
            if not nav_result or not nav_result.ok:
                return
        elif not self._has_open_page():
            print("  请先打开一个页面，或直接说：无障碍检查 http://example.com")
            return
        print("\n[无障碍检查]")
        result = await self.executor.accessibility_audit()
        if not result.ok:
            print(f"  ✗ 无障碍检查失败: {result.reason}")
            return
        self.context.add_tested_feature("无障碍检查")
        self.context.add_event("agent", result.summary, {"tool": "accessibility_audit"})
        self._print_audit_summary(result.data)

    def _print_audit_summary(self, data: Dict[str, Any]):
        summary = data.get("summary", {})
        print(f"  评分: {summary.get('score', 0)}/100")
        issues = summary.get("issues") or []
        if issues:
            print("  问题:")
            for issue in issues[:12]:
                print(f"    - {issue}")
        else:
            print("  未发现基础问题")
        print("  建议:")
        for recommendation in summary.get("recommendations", []):
            print(f"    - {recommendation}")

    def _show_locator_memory(self):
        host = urlparse(self.context.current_url or getattr(self.page, "url", "") or "").netloc or "unknown"
        data = self.locator_memory.data.get(host, {})
        print(f"\n[Locator 学习] {host}")
        if not data:
            print("  暂无成功定位记录")
            return
        for key, value in list(data.items())[:20]:
            print(f"  - {value.get('description')}: <{value.get('tag')}> {value.get('text') or value.get('href')}")

    def _show_agent_roles(self):
        roles = [
            ("MainAgent", "对话、上下文、任务协调"),
            ("PlanningAgent", "理解用户需求并拆分步骤"),
            ("ExplorerAgent", "抽取页面结构、表单、文章、搜索结果、登录要求"),
            ("BrowserAgent", "执行点击、填写、导航、滚动、等待"),
            ("VerifierAgent", "验证动作结果和高层任务是否完成"),
            ("DataAgent", "生成测试数据并记录清理线索"),
            ("ReporterAgent", "生成 Markdown/HTML/JSON/JUnit 报告"),
            ("SecurityAgent", "低风险安全响应头/表单/混合内容检查"),
            ("LoadTestAgent", "受控 HTTP 压测"),
            ("RegressionAgent", "加载历史会话并重跑用户任务"),
        ]
        print("\n[Agent 分工]")
        for name, task in roles:
            print(f"  - {name}: {task}")

    def _write_ci_template(self):
        path = Path.cwd() / ".github" / "workflows" / "testforge.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = """name: TestForge

on:
  workflow_dispatch:
  push:
    branches: [ main ]

jobs:
  testforge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt || pip install playwright Pillow httpx pytest
      - run: python -m playwright install chromium
      - run: python -m pytest tests/unit/ -q
      # Example future regression entry:
      # - run: python run_cli.py --session blog-test --report html
"""
        path.write_text(content, encoding="utf-8")
        self.context.add_event("agent", "生成 CI 配置", {"path": str(path)})
        print(f"  ✓ CI 配置已生成: {path}")

    async def _run_regression(self, text: str):
        name = re.sub(r"^(回归测试|回归执行|regression)\s*[:：]?", "", text.strip(), flags=re.I).strip()
        if not name:
            name = self.context.session_name
        try:
            data = self.session_store.load(name)
        except FileNotFoundError as e:
            print(f"  ✗ {e}")
            return
        events = [event for event in data.get("events", []) if event.get("role") == "user"]
        if not events:
            print("  该会话没有可回放的用户任务")
            return
        print(f"\n[回归测试] {name}")
        self.context.add_event("agent", f"开始回归测试 {name}", {"steps": len(events)})
        for index, event in enumerate(events[:20], 1):
            task = event.get("text", "")
            if not task or any(term in task for term in ["保存会话", "加载会话", "回归测试"]):
                continue
            print(f"\n  [回归 {index}] {task}")
            await self._handle_user_input(task)

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
            r"^(https?://[^/\s?#]+)/(这个网站|这个页面|这个网页|这个地址|该网站|该页面|此网站|此页面)(?:的.*|.*(?:测试|报告|检查|分析|压测|性能|质量|安全).*)?$",
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
            if not self._suppress_auto_plan:
                await self._generate_and_show_test_plan(auto=True)

        else:
            print(f"  ✗ 导航失败: {result.reason}")

        return result

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

        self._remember_page_features(snapshot_result.data)
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
            await self._resume_after_login_if_needed()
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
                print("  ✗ 登录测试暂停：缺少用户名或密码，我不会提交空凭证。")
                # 保存凭证供下次使用
                if username:
                    self.context.set_credentials(username=username)
                print("  你可以直接说：账号是admin 密码是xxxx")
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
                await self._resume_after_login_if_needed()
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
                self._task_action_count += 1
                guardrail = self._check_task_guardrails()
                if guardrail:
                    print(f"  ✗ Guardrail 触发: {guardrail}")
                    await self._capture_failure_evidence(guardrail)
                    return False
                before = await self.executor.get_snapshot()
                result = await self._execute_action(action)
                if result is not None:
                    self._annotate_result_semantics(action, result)
                    self._record_action_ir(action, result)
                    await self._handle_executor_result(result)
                    self._task_consecutive_failures = 0 if result.ok else self._task_consecutive_failures + 1
                    after = await self.executor.get_snapshot()
                    if before.type == ResultType.SUCCESS and after.type == ResultType.SUCCESS:
                        verification = self.verifier.verify_action(action, before.data, after.data)
                        if not verification.ok:
                            print(f"  ! 动作验证未通过: {verification.reason}")
                            if verification.suggestion:
                                print(f"  建议: {verification.suggestion}")
                            recovered = await self._recover_failed_verification(action, verification)
                            if recovered is not None:
                                result = recovered
                                self._record_action_ir(action, result)
                                await self._handle_executor_result(result)
                                self._task_consecutive_failures = 0 if result.ok else self._task_consecutive_failures + 1
                            elif verification.needs_replan:
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
        if self._is_page_closed():
            self._running = False
            return ExecutorResult(type=ResultType.FAILURE, reason="浏览器页面已经关闭，无法继续执行当前任务")

        action_type = action.type
        repeated = await self._maybe_recover_repeated_action(action)
        if repeated is not None:
            return repeated

        if action_type == "navigate":
            if not action.url:
                return ExecutorResult(type=ResultType.FAILURE, reason="未提供 URL")
            result = await self._handle_navigate(action.url)
            if result:
                self._record_action_ir(action, result)
            if result and not result.ok:
                return result
            return None

        if action_type == "click":
            guarded = await self._guard_risky_click(action)
            if guarded is not None:
                return guarded
            result = await self.executor.click(
                ref=action.target_ref,
                description=action.target_desc or action.description,
            )
            if result.ok:
                self._record_locator_success(action)
            return result

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
            if result.type == ResultType.FAILURE and self._action_looks_like_protected_input(action):
                recovered = await self._recover_auth_required_action(action)
                if recovered:
                    return recovered
            if result.ok:
                self._record_locator_success(action)
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

        if action_type == "extract_links":
            result = await self.executor.extract_links()
            if result.ok:
                print(f"  ✓ 已提取链接: {result.data.get('total', 0)} 条")
            return result

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

        if action_type == "performance_audit":
            result = await self.executor.performance_audit(runs=action.runs, reload=action.reload)
            if result.ok:
                self.context.add_tested_feature("性能测试")
                self._print_performance_report(result.data)
            return result

        if action_type == "load_test":
            target = action.url or self.context.current_url or getattr(self.page, "url", "")
            result = await self.executor.load_test(
                url=target,
                requests=action.requests,
                concurrency=action.concurrency,
                method=action.method,
                timeout=action.timeout,
            )
            if result.ok:
                self.context.add_tested_feature("压力测试")
                self._print_load_test_report(result.data)
            return result

        if action_type == "quality_audit":
            result = await self.executor.quality_audit()
            if result.ok:
                self.context.add_tested_feature("页面质量检查")
                self._print_quality_report(result.data)
            return result

        if action_type == "security_audit":
            result = await self.executor.security_audit()
            if result.ok:
                self.context.add_tested_feature("安全基础测试")
                self._print_audit_summary(result.data)
            return result

        if action_type == "accessibility_audit":
            result = await self.executor.accessibility_audit()
            if result.ok:
                self.context.add_tested_feature("无障碍检查")
                self._print_audit_summary(result.data)
            return result

        if action_type == "generate_test_plan":
            await self._generate_and_show_test_plan()
            return None

        if action_type == "full_test_suite":
            await self._run_full_test_suite(action.url or "")
            return ExecutorResult(type=ResultType.DONE, summary="已完成一键全量测试")

        if action_type == "known_feature_suite":
            await self._run_known_feature_suite("")
            return ExecutorResult(type=ResultType.DONE, summary="已完成已知功能冒烟测试")

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

    async def _recover_failed_verification(self, action: AgentAction, verification) -> Optional[ExecutorResult]:
        """Execute a concrete self-healing path when VerifierAgent knows the fix."""
        hint = f"{verification.reason} {verification.suggestion}".lower()
        should_open_article = (
            "extract_search_results" in hint
            or "文章详情" in hint
            or ("article" in hint and self._task_needs_open_article())
        )
        if not should_open_article:
            if any(term in hint for term in ["登录", "login", "auth", "sign in"]):
                return await self._recover_auth_required_action(action)
            return None

        print("  VerifierAgent: 改用结构化搜索结果链接恢复...")
        result = await self.executor.extract_search_results()
        if not result.ok:
            return None
        print(f"  ✓ 已提取搜索结果: {result.data.get('total', 0)} 条")
        return await self._open_first_extracted_search_result(result)

    async def _guard_risky_click(self, action: AgentAction) -> Optional[ExecutorResult]:
        """Prevent accidental destructive actions during exploratory testing."""
        if not self._is_publish_click(action):
            return None

        current_url = (self.context.current_url or getattr(self.page, "url", "") or "").lower()
        if not any(path in current_url for path in ["/dashboard/write", "/write", "/editor"]):
            return None

        if self._current_task_confirms_real_publish():
            return None

        return ExecutorResult(
            type=ResultType.DONE,
            data={"publish_blocked": True},
            summary="已完成写文章发布前流程验证；为避免创建真实内容，已拦截“发布”动作。若要真正发布，请明确说“确认发布测试文章”。",
        )

    def _is_publish_click(self, action: AgentAction) -> bool:
        if action.type != "click":
            return False
        text = " ".join([
            action.description,
            action.target_desc,
            action.target_ref,
            action.text,
            action.expected,
        ]).lower()
        return any(term in text for term in ["发布", "提交", "提交文章", "publish", "submit post", "post article"])

    def _current_task_confirms_real_publish(self) -> bool:
        text = (getattr(self, "_current_user_task_text", "") or "").lower()
        return any(term in text for term in [
            "确认发布",
            "真的发布",
            "可以发布",
            "允许发布",
            "直接发布测试文章",
            "publish for real",
            "confirm publish",
        ])

    async def _maybe_recover_repeated_action(self, action: AgentAction) -> Optional[ExecutorResult]:
        """Detect loops like clicking the same dashboard card forever and switch strategy."""
        if action.type not in {"click", "fill", "navigate"}:
            return None

        signature = self._action_signature(action)
        counts = getattr(self, "_action_repeat_counts", {})
        counts[signature] = counts.get(signature, 0) + 1
        self._action_repeat_counts = counts
        if counts[signature] < 3:
            return None

        if signature in getattr(self, "_used_recoveries", set()):
            return ExecutorResult(
                type=ResultType.FAILURE,
                reason=f"重复执行同一动作仍未达成目标，已停止: {signature}",
                data={"repeat_count": counts[signature], "signature": signature},
            )
        self._used_recoveries.add(signature)

        if self._task_has_goal("write_article"):
            recovered = await self._recover_write_article_entry()
            if recovered is not None:
                return recovered

        if self._task_has_goal("open_article"):
            result = await self.executor.extract_search_results()
            if result.ok:
                print("  重复动作检测: 改用搜索结果中的文章链接")
                opened = await self._open_first_extracted_search_result(result)
                if opened is not None:
                    return opened

        return ExecutorResult(
            type=ResultType.FAILURE,
            reason=f"检测到重复动作没有推进页面，已停止避免空转: {signature}",
            data={"repeat_count": counts[signature], "signature": signature},
        )

    def _action_signature(self, action: AgentAction) -> str:
        current_url = self.context.current_url or getattr(self.page, "url", "")
        try:
            parsed = urlparse(current_url)
            location = f"{parsed.netloc}{parsed.path}"
        except Exception:
            location = current_url
        target = action.target_ref or action.target_desc or action.description or action.url or action.type
        return f"{action.type}|{location}|{target}".lower()

    def _task_has_goal(self, goal_type: str) -> bool:
        state = getattr(self, "_current_task_state", None)
        return bool(state and any(goal.type == goal_type and not goal.done for goal in state.goals))

    async def _recover_write_article_entry(self) -> Optional[ExecutorResult]:
        """Use remembered or conventional editor URL when the planner loops in admin/blog pages."""
        current_url = self.context.current_url or getattr(self.page, "url", "")
        remembered = self._feature_href("write_article")
        target = remembered or self._join_origin(current_url, "/dashboard/write")
        if target.startswith("/"):
            target = self._join_origin(current_url, target)
        if not target:
            return None

        print("  重复动作检测: 直接尝试进入写文章编辑页")
        nav_result = await self.executor.navigate(target)
        if nav_result.ok:
            self.context.add_page(nav_result.data.get("url", target), nav_result.data.get("title", ""))
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data={"url": nav_result.data.get("url", target), "recovered_by": "write_article_direct_url"},
                summary=f"已切换到写文章入口: {nav_result.data.get('url', target)}",
            )
        return nav_result

    def _feature_href(self, feature: str) -> str:
        current_url = self.context.current_url or getattr(self.page, "url", "")
        host = urlparse(current_url or "").netloc or "unknown"
        host_map = self.context.known_feature_map.get(host, {})
        item = host_map.get(feature) or {}
        return item.get("href", "") if isinstance(item, dict) else ""

    def _join_origin(self, url: str, path: str) -> str:
        try:
            parsed = urlparse(url or "")
        except Exception:
            return ""
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def _remember_page_features(self, snapshot: Dict[str, Any]) -> None:
        """Keep a small site feature map so future plans can use known good paths."""
        url = snapshot.get("url") or self.context.current_url or getattr(self.page, "url", "")
        host = urlparse(url or "").netloc or "unknown"
        host_map = self.context.known_feature_map.setdefault(host, {})
        for element in snapshot.get("elements") or []:
            href = element.get("href") or ""
            label = " ".join(str(element.get(key, "")) for key in ("text", "placeholder", "label", "ariaLabel", "id", "name")).strip()
            blob = f"{label} {href}".lower()
            resolved_href = href
            if any(term in blob for term in ["搜索", "search", "查询"]):
                self._record_feature_candidate(host_map, "search", label, resolved_href)
            if any(term in blob for term in ["登录", "login", "sign in", "signin", "登入", "登陆"]):
                self._record_feature_candidate(host_map, "login", label, resolved_href)
            if any(term in blob for term in ["写文章", "发文章", "添加文章", "新增文章", "write", "new post", "editor"]):
                self._record_feature_candidate(host_map, "write_article", label, resolved_href)
            if any(term in blob for term in ["评论", "留言", "comment", "guestbook"]):
                self._record_feature_candidate(host_map, "comment", label, resolved_href)
            if any(term in blob for term in ["管理", "后台", "dashboard", "admin"]):
                self._record_feature_candidate(host_map, "admin", label, resolved_href)
            if any(term in blob for term in ["博客", "文章", "blog", "post"]):
                self._record_feature_candidate(host_map, "article_list", label, resolved_href)

    def _record_feature_candidate(self, host_map: Dict[str, Any], feature: str, label: str, href: str) -> None:
        if not href:
            return
        current = host_map.get(feature) or {}
        if current.get("href"):
            return
        host_map[feature] = {
            "label": label[:80],
            "href": href,
            "last_seen": datetime.now().isoformat(timespec="seconds"),
        }

    def _check_task_guardrails(self) -> str:
        if self._task_action_count > self._max_actions_per_task:
            return f"单个任务动作数超过上限 {self._max_actions_per_task}，已停止以避免无限循环"
        if self._task_consecutive_failures > self._max_consecutive_failures:
            return f"连续失败超过上限 {self._max_consecutive_failures}，已停止并保存证据"
        return ""

    def _record_action_ir(self, action: AgentAction, result: ExecutorResult):
        """Record interactive CLI actions as AutoQA-style IR for later export."""
        try:
            tool_name = self._ir_tool_name(action.type)
            if not tool_name:
                return
            tool_input = self._ir_tool_input(action)
            element = self._ir_element_record(action)
            self.ir_writer.append_action(
                run_id=self.context.run_id,
                spec_path="interactive",
                step_index=self._task_action_count or None,
                step_text=action.description or action.target_desc or action.text or action.url or action.type,
                tool_name=tool_name,
                tool_input=tool_input,
                outcome={"ok": result.ok, "errorMessage": result.reason or ""},
                page_url=self.context.current_url or getattr(self.page, "url", ""),
                element=element,
            )
        except Exception:
            pass

    def _annotate_result_semantics(self, action: AgentAction, result: ExecutorResult) -> None:
        """Attach testing-oriented meaning to low-level tool results."""
        result.data.setdefault("action_type", action.type)
        result.data.setdefault("action_ok", result.ok)
        result.data.setdefault("goal_hint", self._goal_hint_for_action(action))
        if result.type == ResultType.FAILURE:
            result.data.setdefault("goal_ok", False)
        elif result.data.get("needs_replan"):
            result.data.setdefault("goal_ok", False)
        else:
            result.data.setdefault("goal_ok", True)

    def _goal_hint_for_action(self, action: AgentAction) -> str:
        text = " ".join([
            action.description,
            action.target_desc,
            action.target_ref,
            action.text,
            action.expected,
            action.url,
        ]).lower()
        if any(term in text for term in ["搜索", "search", "查询"]):
            return "search"
        if any(term in text for term in ["登录", "login", "sign in", "signin"]):
            return "login"
        if any(term in text for term in ["点赞", "赞", "like"]):
            return "like"
        if any(term in text for term in ["评论", "留言", "comment"]):
            return "comment"
        if any(term in text for term in ["写文章", "发布", "文章", "write", "post"]):
            return "article"
        return action.type

    def _ir_tool_name(self, action_type: str) -> str:
        mapping = {
            "navigate": "navigate",
            "click": "click",
            "fill": "fill",
            "assert_text": "assertTextPresent",
            "assert_visible": "assertElementVisible",
            "wait": "wait",
            "scroll": "scroll",
        }
        return mapping.get(action_type, "")

    def _ir_tool_input(self, action: AgentAction) -> Dict[str, Any]:
        if action.type == "navigate":
            return {"url": action.url or ""}
        if action.type == "click":
            return {"ref": action.target_ref, "targetDescription": action.target_desc or action.description}
        if action.type == "fill":
            text = action.fill_value or action.text or ""
            return {
                "ref": action.target_ref,
                "targetDescription": action.target_desc or action.description,
                "text": text,
                "fillValue": {"kind": "literal", "value": text},
            }
        if action.type == "assert_text":
            return {"text": action.expected or action.text or action.description}
        if action.type == "assert_visible":
            return {"ref": action.target_ref, "targetDescription": action.target_desc or action.description}
        if action.type == "wait":
            return {"seconds": action.seconds}
        if action.type == "scroll":
            return {"direction": action.direction, "amount": action.amount}
        return {}

    def _ir_element_record(self, action: AgentAction) -> Optional[Dict[str, Any]]:
        desc = action.target_desc or action.description or action.target_ref
        if action.type not in {"click", "fill", "assert_visible"} or not desc:
            return None
        locator_code = ""
        if action.target_ref:
            locator_code = f"page.locator('[data-testforge-ref=\"{self._escape_locator(action.target_ref)}\"]')"
        else:
            locator_code = f"page.get_by_text('{self._escape_locator(desc)}')"
        return {
            "fingerprint": {
                "textSnippet": desc[:120],
                "tagName": "",
            },
            "locatorCandidates": [{"kind": "testforge", "code": locator_code}],
            "chosenLocator": {"kind": "testforge", "code": locator_code},
        }

    def _escape_locator(self, text: str) -> str:
        return str(text or "").replace("\\", "\\\\").replace("'", "\\'")

    def _action_looks_like_search_fill(self, action: AgentAction) -> bool:
        text = " ".join([
            action.description,
            action.target_desc,
            action.target_ref,
            action.text,
        ]).lower()
        return action.type == "fill" and any(term in text for term in ["搜索", "search", "查询"])

    def _record_locator_success(self, action: AgentAction):
        desc = action.target_desc or action.description or action.target_ref
        if not desc:
            return
        self.locator_memory.record(
            self.context.current_url or getattr(self.page, "url", ""),
            desc,
            {
                "tag": action.type,
                "text": action.target_desc or action.description,
                "href": action.url,
                "role": "",
            },
        )

    def _action_looks_like_protected_input(self, action: AgentAction) -> bool:
        text = " ".join([
            action.description,
            action.target_desc,
            action.target_ref,
            action.text,
        ]).lower()
        return action.type == "fill" and any(
            term in text for term in ["评论", "留言", "comment", "点赞", "like", "发文章", "发布"]
        )

    async def _recover_auth_required_action(self, action: AgentAction) -> Optional[ExecutorResult]:
        """When a protected input is blocked, click login and re-plan."""
        auth = await self.executor.extract_auth_requirements()
        if not auth.ok or not auth.data.get("auth_required"):
            return None

        print("  页面提示需要登录，先进入登录流程...")
        if self._current_user_task_text and not self._looks_like_explicit_login_test(self._current_user_task_text):
            self._pending_resume = {
                "task": self._current_user_task_text,
                "url": self.context.current_url or getattr(self.page, "url", ""),
            }
        links = auth.data.get("login_links") or []
        if links:
            first = links[0]
            click_result = await self.executor.click(
                ref=first.get("ref", ""),
                description=first.get("text") or "点击登录",
            )
        else:
            best = await self.executor.find_best_entry(["点击登录", "请登录", "登录", "login", "sign in"])
            if not best:
                return ExecutorResult(type=ResultType.FAILURE, reason="页面需要登录，但找不到登录入口")
            click_result = await self.executor.click(ref=best["ref"], description="点击登录")

        if click_result.ok:
            click_result.summary = "已进入登录入口，继续规划登录后再执行原任务"
            click_result.data["needs_replan"] = True
        return click_result

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
        if self._looks_like_load_test_request(task):
            load_done = any(
                "压力" in feature or "压测" in feature or "load" in feature.lower()
                for feature in self.context.tested_features
            )
            if load_done:
                return {"done": True, "summary": "压力测试已完成"}

        if any(term in task_lower for term in ["性能测试", "页面质量", "质量检查", "安全检查", "安全基础测试", "无障碍", "可访问性", "performance", "audit", "security", "a11y"]):
            audit_done = any(
                term in feature
                for feature in self.context.tested_features
                for term in ["性能", "质量", "安全", "无障碍"]
            )
            if audit_done:
                return {"done": True, "summary": "工程审计已完成"}

        if any(term in task_lower for term in ["生成报告", "测试报告", "导出报告", "report"]):
            if self.context.reports:
                return {"done": True, "summary": "测试报告已生成"}

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
            await self._resume_after_login_if_needed()
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
        await self._stabilize_after_login_page()
        print("  登录后可以继续测试的功能如下：")
        await self._analyze_and_report_page()
        print("  你可以直接说：测试搜索、测试写文章、测试留言、测试后台入口，或导入 Markdown 用例。")

    async def _stabilize_after_login_page(self):
        """After auth redirects, move from a thin auth landing page to site root."""
        try:
            await asyncio.sleep(0.5)
            snapshot = await self.executor.get_snapshot()
        except Exception:
            return
        if snapshot.type != ResultType.SUCCESS:
            return

        elements = snapshot.data.get("elements") or []
        current_url = snapshot.data.get("url") or self.context.current_url or getattr(self.page, "url", "")
        if len(elements) > 5 and not self._url_looks_like_auth_page(current_url):
            return

        root = self._site_root_url(current_url)
        if not root or root == current_url:
            return

        nav_result = await self.executor.navigate(root)
        if nav_result.ok:
            self.context.add_page(nav_result.data.get("url", root), nav_result.data.get("title", ""))
            print(f"  已回到站点首页继续分析: {self.context.current_url}")

    def _site_root_url(self, url: str) -> str:
        try:
            parsed = urlparse(url or "")
        except Exception:
            return ""
        if not parsed.scheme or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _url_looks_like_auth_page(self, url: str) -> bool:
        try:
            path = urlparse(url or "").path.lower()
        except Exception:
            return False
        return any(token in path for token in ["login", "signin", "sign-in", "auth"])

    async def _resume_after_login_if_needed(self):
        """Return to the blocked page and continue the original user task after login."""
        pending = getattr(self, "_pending_resume", {}) or {}
        task = pending.get("task", "")
        if not task:
            return
        self._pending_resume = {}
        resume_url = pending.get("url", "")
        if resume_url and resume_url != getattr(self.page, "url", ""):
            print(f"  登录完成，回到原页面继续任务: {resume_url}")
            nav_result = await self.executor.navigate(resume_url)
            if nav_result.ok:
                self.context.add_page(nav_result.data.get("url", resume_url), nav_result.data.get("title", ""))
            else:
                print(f"  回到原页面失败: {nav_result.reason}")
        print("  登录完成，继续执行原任务...")
        await self._run_planned_task(task)

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
            self.context.add_event("agent", result.summary or "动作成功", {"result_type": "success", "data": dict(result.data)})
            # 更新上下文
            if result.data.get("url"):
                self.context.add_page(result.data["url"])

        elif result.type == ResultType.FAILURE:
            print(f"  ✗ {result.reason}")
            self.context.last_failed_action = {
                "reason": result.reason,
                "data": dict(result.data),
            }
            self.context.add_event("agent", result.reason or "动作失败", {"result_type": "failure", "data": dict(result.data)})
            await self._capture_failure_evidence(result.reason)
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
            self.context.add_event("agent", result.summary or "任务完成", {"result_type": "done", "data": dict(result.data)})
            if result.data.get("url"):
                self.context.add_page(result.data["url"])

    async def _capture_failure_evidence(self, reason: str):
        if self._is_page_closed():
            return
        try:
            snapshot = await self.executor.get_snapshot()
            snapshot_data = snapshot.data if snapshot.type == ResultType.SUCCESS else {}
            path = await self.evidence.capture_failure(
                self.page,
                self.context.session_name,
                reason,
                snapshot_data,
                self.network_recorder.records,
            )
            await self._save_trace_to(path)
            self.context.artifacts.append(str(path))
            print(f"  失败证据已保存: {path}")
        except Exception:
            pass

    async def _suggest_recovery(self, reason: str):
        """给出失败恢复建议"""
        reason_lower = reason.lower()
        if "not found" in reason_lower or "找不到" in reason_lower:
            print("  提示: 尝试用更具体的描述，如'点击蓝色登录按钮'")
            print("  或先输入'截图'看看当前页面")

    # ─── 帮助与状态 ────────────────────────────────────────────────────────────

    def _show_help(self):
        print("""
TestForge CLI 使用指南

新手三步:
  1. 打开网站:
     帮我测试一下 http://example.com 这个网站
  2. 看功能:
     现在页面有什么功能？可以测试什么？
  3. 全量测试并生成报告:
     对 http://example.com 进行全部功能测试！全套包括功能测试、性能测试、压力测试、安全测试、无障碍测试，并生成报告

常用功能测试:
  测试登录功能 账号是admin 密码是********
  测试搜索功能 搜索 linux，打开第一篇文章
  测试评论功能 评论一个666，如果需要登录就先登录
  测试点赞功能，如果点赞需要登录就使用账号密码登录
  测试当前页面所有已知功能

  全量测试会做:
  测试计划、站点地图、入口冒烟、发现功能深度检查、二级功能入口检查、安全本地工具交互探针、搜索/文章/登录/评论前置流、
  页面质量、安全、无障碍、性能、低压压测、网络/API摘要、HTML/JSON报告。
  默认不会自动提交注册、评论、发文章、删除、支付等会产生真实数据或风险的动作。

测试工程师工具:
  测试计划                         - 生成测试矩阵
  生成测试用例                     - 导出 JSON/Markdown/CSV/XLSX
  用例列表 / 运行用例 login-case   - 管理并执行沉淀用例
  根据需求文档 docs/a.md 生成测试用例
  生成缺陷 / 提Bug                 - 根据失败、截图、网络日志生成缺陷单
  运行Postman collection.json 环境 env.json
  配置MySQL host=... / 执行SQL select ...
  生成JMeter脚本 URL 线程10 循环20 状态码200
  导出 Playwright 用例 / 运行pytest 回归 tests/testforge

审计与定位:
  页面质量检查 当前页面/URL
  安全检查 当前页面/URL
  无障碍检查 当前页面/URL
  性能测试 当前页面/URL 3次
  压力测试 URL 50次 并发5
  网络日志 / API测试
  截图 / locator / Agent分工

会话与回归:
  保存会话 blog-test
  加载会话 blog-test
  会话列表 / 新建会话 name
  回归测试 blog-test
  回归对比 blog-test
  生成报告 html/json/junit/all

其他:
  运行 specs/login.md              - 导入并执行 Markdown 测试用例
  探索站点 URL 深度2 页面20        - 深度探索并保存 graph/elements/transcript
  保存基线 homepage / 视觉对比 homepage
  测试数据 用户/评论/文章
  status                           - 查看当前状态
  help                             - 显示此帮助
  q                                - 退出
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
        video_dir = Path.home() / ".testforge" / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(video_dir),
        )
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
