"""
ExecutorAgent - 浏览器执行 Agent
================================

职责：
- 管理浏览器生命周期（page、context、browser）
- 接收 MainAgent 的任务指令
- 调用工具执行操作
- 返回结构化结果

与 MainAgent 的通信协议：
- MainAgent → ExecutorAgent：下达任务（如"导航到某 URL"、"点击登录按钮"）
- ExecutorAgent → MainAgent：返回结果（成功/失败/需要用户提供信息）

Result 类型：
- success(data)          操作成功
- failure(code, reason)  操作失败，需要重试
- ask_user(fields)        需要用户提供信息（如账号密码）
- no_auth_needed()       不需要登录/凭证
- done(summary)           任务完成
"""

import asyncio
import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

from ..ai_client import create_ai_client
from . import tools
from .agent_plan import AgentAction


# ─────────────────────────────────────────────────────────────────────────────
# 结果类型
# ─────────────────────────────────────────────────────────────────────────────

class ResultType(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    ASK_USER = "ask_user"
    NO_AUTH_NEEDED = "no_auth_needed"
    DONE = "done"


@dataclass
class ExecutorResult:
    """ExecutorAgent 返回结果"""
    type: ResultType
    data: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    summary: str = ""

    @property
    def ok(self) -> bool:
        return self.type in (ResultType.SUCCESS, ResultType.DONE, ResultType.NO_AUTH_NEEDED)


# ─────────────────────────────────────────────────────────────────────────────
# ExecutorAgent
# ─────────────────────────────────────────────────────────────────────────────

class ExecutorAgent:
    """
    浏览器执行 Agent

    使用方式：
        executor = ExecutorAgent(page=page, ai_client=ai_client)
        result = await executor.navigate("http://47.242.21.40/")
        result = await executor.execute_task("点击登录按钮")
        result = await executor.find_login_form()
    """

    def __init__(self, page, ai_client=None):
        self.page = page
        self.ai_client = ai_client or create_ai_client()
        self._page_history: List[str] = []
        self._current_url: str = ""
        self._is_logged_in: bool = False
        self._login_detected: bool = False

    LOGIN_SUCCESS_TERMS = [
        "退出", "注销", "logout", "sign out",
        "个人中心", "用户中心", "dashboard", "profile",
        "管理后台", "写文章", "发布文章",
    ]
    AUTH_REQUIRED_TERMS = [
        "请登录", "请先登录", "登录后", "点击登录", "未登录",
        "需要登录", "登录才能", "重新登录", "请重新登录", "login required", "please log in",
        "please login", "sign in to",
    ]
    LOGIN_FAILURE_TERMS = [
        "登录失败", "登陆失败", "认证失败", "验证失败",
        "密码错误", "密码不正确", "账号或密码", "用户名或密码",
        "用户名错误", "账号错误", "无效", "错误", "失败",
        "invalid", "incorrect", "failed", "login failed", "error",
    ]

    # ─── 基础操作 ────────────────────────────────────────────────────────────

    async def navigate(self, url: str) -> ExecutorResult:
        """导航到 URL"""
        result = await tools.navigate(self.page, url)
        if result.ok:
            self._page_history.append(url)
            self._current_url = self.page.url
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data={"url": self.page.url, "title": await self.page.title()},
                summary=f"已打开 {self.page.url}",
            )
        return ExecutorResult(
            type=ResultType.FAILURE,
            reason=result.error or "导航失败",
        )

    async def get_snapshot(self) -> ExecutorResult:
        """获取当前页面快照"""
        result = await tools.snapshot(self.page)
        if result.ok:
            result.data["auth_artifacts"] = await self._read_auth_artifacts()
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def get_screenshot_base64(self) -> str:
        """获取截图（base64）"""
        result = await tools.screenshot(self.page)
        if result.ok:
            return result.data.get("screenshot", "")
        return ""

    async def extract_search_results(self) -> ExecutorResult:
        result = await tools.extract_search_results(self.page)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data)
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def extract_links(self) -> ExecutorResult:
        result = await tools.extract_links(self.page)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data)
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def extract_like_buttons(self) -> ExecutorResult:
        result = await tools.extract_like_buttons(self.page)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data)
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def extract_auth_requirements(self) -> ExecutorResult:
        result = await tools.extract_auth_requirements(self.page)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data)
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def extract_forms(self) -> ExecutorResult:
        result = await tools.extract_forms(self.page)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data)
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def extract_article_content(self) -> ExecutorResult:
        result = await tools.extract_article_content(self.page)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data)
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def performance_audit(self, runs: int = 1, reload: bool = False) -> ExecutorResult:
        result = await tools.performance_audit(self.page, runs=runs, reload=reload)
        if result.ok:
            summary = result.data.get("summary", {})
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
                summary=f"性能评分 {summary.get('score', 0)}/100 ({summary.get('rating', 'unknown')})",
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def load_test(
        self,
        url: str = "",
        requests: int = 20,
        concurrency: int = 2,
        method: str = "GET",
        timeout: float = 10.0,
    ) -> ExecutorResult:
        result = await tools.load_test(
            self.page,
            url=url,
            requests=requests,
            concurrency=concurrency,
            method=method,
            timeout=timeout,
        )
        if result.ok:
            summary = result.data.get("summary", {})
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
                summary=f"压测完成: {summary.get('total', 0)} 请求, P95 {summary.get('p95', 0)}ms",
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def quality_audit(self) -> ExecutorResult:
        result = await tools.quality_audit(self.page)
        if result.ok:
            summary = result.data.get("summary", {})
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
                summary=f"页面质量评分 {summary.get('score', 0)}/100",
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def security_audit(self) -> ExecutorResult:
        result = await tools.security_audit(self.page)
        if result.ok:
            summary = result.data.get("summary", {})
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
                summary=f"安全检查评分 {summary.get('score', 0)}/100",
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def accessibility_audit(self) -> ExecutorResult:
        result = await tools.accessibility_audit(self.page)
        if result.ok:
            summary = result.data.get("summary", {})
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
                summary=f"无障碍检查评分 {summary.get('score', 0)}/100",
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    # ─── 登录结果判定 ────────────────────────────────────────────────────────

    def _snapshot_text(self, snapshot: ExecutorResult) -> str:
        return (snapshot.data.get("text") or "").lower()

    def _login_failure_reason(self, text: str) -> str:
        """Return a concise failure line if the page text contains one."""
        lower = text.lower()
        for term in self.LOGIN_FAILURE_TERMS:
            needle = term.lower()
            if needle not in lower:
                continue
            for line in re.split(r"[\r\n。；;]", text):
                if needle in line.lower():
                    return line.strip()[:160] or "页面出现登录失败提示"
            return "页面出现登录失败提示"
        return ""

    def _has_logged_in_indicator(self, elements: List[Dict[str, Any]], text: str) -> bool:
        lower = text.lower()
        if self._has_auth_required_indicator(text, elements):
            return False
        strong_text_terms = ["退出", "注销", "logout", "sign out", "dashboard"]
        if any(term.lower() in lower for term in strong_text_terms):
            return True
        for element in elements:
            blob = self._element_blob(element)
            if any(term.lower() in blob for term in self.LOGIN_SUCCESS_TERMS):
                return True
        return False

    def _has_auth_required_indicator(self, text: str, elements: List[Dict[str, Any]] = None) -> bool:
        lower = (text or "").lower()
        if any(term.lower() in lower for term in self.AUTH_REQUIRED_TERMS):
            return True
        for element in elements or []:
            blob = self._element_blob(element)
            if any(term.lower() in blob for term in self.AUTH_REQUIRED_TERMS):
                return True
        return False

    def _has_password_form(self, elements: List[Dict[str, Any]]) -> bool:
        return any(
            e.get("tag") == "input" and (e.get("type") or "").lower() == "password"
            for e in elements
        )

    async def _read_auth_artifacts(self) -> Dict[str, Any]:
        """Detect auth-like browser storage without exposing secret values."""
        try:
            return await self.page.evaluate("""
                () => {
                    const authPattern = /(token|auth|jwt|session|user|login|access|refresh)/i;
                    const storageKeys = [];
                    const collect = (storage, prefix) => {
                        try {
                            for (let i = 0; i < storage.length; i++) {
                                const key = storage.key(i) || '';
                                const value = storage.getItem(key) || '';
                                if (authPattern.test(key) || authPattern.test(value)) {
                                    storageKeys.push(`${prefix}:${key}`);
                                }
                            }
                        } catch (_) {}
                    };
                    collect(window.localStorage, 'localStorage');
                    collect(window.sessionStorage, 'sessionStorage');

                    const cookieNames = (document.cookie || '')
                        .split(';')
                        .map((part) => part.trim().split('=')[0])
                        .filter((name) => authPattern.test(name));

                    return {
                        has_auth_artifact: storageKeys.length > 0 || cookieNames.length > 0,
                        storage_keys: storageKeys.slice(0, 10),
                        cookie_names: cookieNames.slice(0, 10),
                    };
                }
            """)
        except Exception:
            return {"has_auth_artifact": False, "storage_keys": [], "cookie_names": []}

    def _url_looks_like_auth(self, url: str) -> bool:
        try:
            path = urlparse(url).path.lower()
        except Exception:
            return False
        return any(token in path for token in ["login", "signin", "sign-in", "auth", "register", "signup"])

    def _classify_login_result(
        self,
        snapshot: ExecutorResult,
        url_before: str = "",
        submitted: bool = False,
    ) -> ExecutorResult:
        """Classify login result from page text, elements, and URL."""
        elements = snapshot.data.get("elements", [])
        text = self._snapshot_text(snapshot)
        url_after = snapshot.data.get("url") or getattr(self.page, "url", "")
        auth_artifacts = snapshot.data.get("auth_artifacts") or {}

        failure_reason = self._login_failure_reason(text)
        if failure_reason:
            return ExecutorResult(
                type=ResultType.FAILURE,
                reason=f"检测到登录失败提示: {failure_reason}",
                data={"url": url_after},
            )

        if self._has_auth_required_indicator(text, elements):
            return ExecutorResult(
                type=ResultType.FAILURE,
                reason="页面提示仍需要登录，未检测到已登录状态",
                data={"url": url_after},
            )

        if auth_artifacts.get("has_auth_artifact"):
            self._is_logged_in = True
            return ExecutorResult(
                type=ResultType.DONE,
                summary="登录成功（检测到认证 token/cookie，未读取敏感值）",
                data={"url": url_after, "auth_artifacts": auth_artifacts},
            )

        if self._has_logged_in_indicator(elements, text):
            self._is_logged_in = True
            return ExecutorResult(
                type=ResultType.DONE,
                summary="登录成功（检测到登录后标识）",
                data={"url": url_after},
            )

        has_password_form = self._has_password_form(elements)
        if submitted and url_before and url_after != url_before and not self._url_looks_like_auth(url_after):
            self._is_logged_in = True
            return ExecutorResult(
                type=ResultType.DONE,
                summary=f"登录后页面已跳转: {url_after}",
                data={"url": url_after},
            )

        if submitted:
            if has_password_form:
                return ExecutorResult(
                    type=ResultType.FAILURE,
                    reason="登录后仍停留在登录表单，未检测到成功标识",
                    data={"url": url_after},
                )
            return ExecutorResult(
                type=ResultType.DONE,
                summary="登录已提交，登录表单已消失且未检测到失败/需登录提示",
                data={"url": url_after},
            )

        return ExecutorResult(
            type=ResultType.FAILURE,
            reason="未检测到登录成功标识",
            data={"url": url_after},
        )

    async def verify_login_result(self, url_before: str = "") -> ExecutorResult:
        """Verify login after a click/fill/click action sequence."""
        snapshot = await self.get_snapshot()
        if snapshot.type != ResultType.SUCCESS:
            return ExecutorResult(type=ResultType.FAILURE, reason="无法获取登录后的页面状态")
        snapshot.data["auth_artifacts"] = await self._read_auth_artifacts()
        return self._classify_login_result(snapshot, url_before=url_before, submitted=True)

    # ─── 查找元素 ────────────────────────────────────────────────────────────

    async def find_elements(self, description: str) -> ExecutorResult:
        """搜索匹配描述的元素，返回候选列表"""
        result = await tools.find_elements(self.page, description)
        if result.ok:
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data=result.data,
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def select_best_match(
        self,
        candidates: List[Dict],
        goal: str,
    ) -> Optional[Dict]:
        """
        让 AI 从多个候选元素中选出最符合目标的一个。

        Args:
            candidates: find_elements 返回的候选列表
            goal: 目标描述（如"登录按钮"）

        Returns:
            最佳匹配元素，或 None
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        candidates_text = "\n".join([
            f"- ref={c['ref']} tag={c['tag']} text='{c.get('text','')}' "
            f"placeholder='{c.get('placeholder','')}' score={c.get('score',0)}"
            for c in candidates
        ])

        prompt = f"""从以下候选元素中，选出最符合目标「{goal}」的一个。

候选元素：
{candidates_text}

要求：
1. 忽略 score，只根据元素文本和标签判断
2. 输出 JSON: {{"ref": "eX", "reason": "为什么选这个"}}
3. 如果所有候选都不合适，输出 {{"ref": null, "reason": "..."}}

只输出 JSON。"""

        try:
            response = await self.ai_client.complete(prompt, "")
            match = re.search(r'\{"ref":\s*"([^"]+)"', response)
            if match:
                ref = match.group(1)
                for c in candidates:
                    if c["ref"] == ref:
                        reason_match = re.search(r'"reason":\s*"([^"]+)"', response)
                        reason = reason_match.group(1) if reason_match else ""
                        return {**c, "ai_reason": reason}
        except Exception:
            pass

        # AI 失败时返回最高分
        return candidates[0] if candidates else None

    # ─── 点击 ────────────────────────────────────────────────────────────────

    async def click(
        self,
        description: str = "",
        ref: str = "",
        candidates: List[Dict] = None,
    ) -> ExecutorResult:
        """
        点击元素。

        策略：
        1. 如果有多个候选，让 AI 选最优
        2. 按优先级尝试各候选
        3. 都失败后用 description 模糊匹配
        """
        special = await self._try_specialized_click(description)
        if special:
            return special

        # 如果有多个候选，先选最优
        if candidates and len(candidates) > 1:
            best = await self.select_best_match(candidates, description)
            if best:
                result = await tools.click(self.page, ref=best["ref"])
            else:
                result = await tools.click(self.page, description=description)
        elif ref:
            result = await tools.click(self.page, ref=ref)
            if not result.ok and description:
                recovered = await self._recover_stale_ref(description)
                if recovered:
                    result = recovered
        else:
            # 先搜索
            find_result = await tools.find_elements(self.page, description)
            if find_result.ok and find_result.data.get("candidates"):
                cands = find_result.data["candidates"]
                best = await self.select_best_match(cands, description)
                if best:
                    result = await tools.click(self.page, ref=best["ref"])
                else:
                    return ExecutorResult(
                        type=ResultType.FAILURE,
                        reason="未找到合适的元素",
                    )
            else:
                result = await tools.click(self.page, description=description)

        if result.ok:
            await asyncio.sleep(1)
            self._current_url = self.page.url
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data={"url": self.page.url, "title": await self.page.title()},
                summary=f"点击成功，页面: {self.page.url}",
            )

        # 点击失败，尝试其他候选
        if candidates and len(candidates) > 1:
            for cand in candidates:
                if cand.get("ref") == ref:
                    continue
                res = await tools.click(self.page, ref=cand["ref"])
                if res.ok:
                    await asyncio.sleep(1)
                    self._current_url = self.page.url
                    return ExecutorResult(
                        type=ResultType.SUCCESS,
                        data={"url": self.page.url},
                        summary=f"点击成功（第2+候选），页面: {self.page.url}",
                    )

        return ExecutorResult(
            type=ResultType.FAILURE,
            reason=result.error or "点击失败",
        )

    async def _try_specialized_click(self, description: str = "") -> Optional[ExecutorResult]:
        desc = (description or "").lower()
        if any(term in desc for term in ["搜索结果", "第一篇", "文章标题", "文章详情", "查看全文"]):
            result = await tools.extract_search_results(self.page)
            if result.ok and result.data.get("results"):
                target = result.data["results"][0]
                href = target.get("href")
                if href:
                    nav = await tools.navigate(self.page, href)
                    if nav.ok:
                        self._current_url = self.page.url
                        return ExecutorResult(
                            type=ResultType.SUCCESS,
                            data={"url": self.page.url, "title": await self.page.title(), "href": href},
                            summary=f"已打开搜索结果文章: {target.get('text', href)[:40]}",
                        )

        if any(term in desc for term in ["点赞", "点一个赞", "赞按钮", "like"]):
            result = await tools.extract_like_buttons(self.page)
            if result.ok and result.data.get("buttons"):
                button = result.data["buttons"][0]
                clicked = await tools.click(self.page, ref=button.get("ref", ""), description=description)
                if clicked.ok:
                    await asyncio.sleep(0.6)
                    return ExecutorResult(
                        type=ResultType.SUCCESS,
                        data={"url": self.page.url, "ref": button.get("ref")},
                        summary="已点击点赞候选按钮",
                    )
        return None

    async def _recover_stale_ref(self, description: str) -> Optional[tools.ToolResult]:
        """Re-snapshot and retry by description when an old ref disappeared."""
        find_result = await tools.find_elements(self.page, description)
        if find_result.ok and find_result.data.get("candidates"):
            best = await self.select_best_match(find_result.data["candidates"], description)
            if best:
                return await tools.click(self.page, ref=best.get("ref", ""))
        return await tools.click(self.page, description=description)

    # ─── 填写表单 ────────────────────────────────────────────────────────────

    async def fill(
        self,
        description: str = "",
        ref: str = "",
        text: str = "",
        candidates: List[Dict] = None,
    ) -> ExecutorResult:
        """填写表单字段"""
        if candidates:
            # 用 ref 匹配
            matched = next((c for c in candidates if c.get("ref") == ref), candidates[0])
            result = await tools.fill(self.page, ref=matched["ref"], text=text)
        elif ref:
            result = await tools.fill(self.page, ref=ref, text=text)
        else:
            result = await tools.fill(self.page, description=description, text=text)

        if result.ok:
            return ExecutorResult(
                type=ResultType.SUCCESS,
                data={"field": description or ref, "text_len": len(text)},
                summary=f"已填写: {description or ref}",
            )
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def assert_text(self, text: str) -> ExecutorResult:
        """断言当前页面包含文本"""
        result = await tools.assert_text(self.page, text)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data, summary=f"断言通过: {text}")
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def assert_visible(self, description: str = "", ref: str = "") -> ExecutorResult:
        """断言元素可见"""
        result = await tools.assert_visible(self.page, description=description, ref=ref)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data, summary=f"元素可见: {description or ref}")
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def scroll(self, direction: str = "down", amount: int = 300) -> ExecutorResult:
        """滚动页面"""
        result = await tools.scroll(self.page, direction=direction, amount=amount)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data, summary=f"已滚动 {direction} {amount}px")
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def wait(self, seconds: float = 1.0) -> ExecutorResult:
        """等待"""
        result = await tools.wait(seconds)
        if result.ok:
            return ExecutorResult(type=ResultType.SUCCESS, data=result.data, summary=f"等待 {seconds:g} 秒")
        return ExecutorResult(type=ResultType.FAILURE, reason=result.error)

    async def execute_actions(self, actions: List[AgentAction]) -> ExecutorResult:
        """按顺序执行主 Agent 规划出的动作列表。"""
        last_result = ExecutorResult(type=ResultType.DONE, summary="没有需要执行的动作")
        for index, action in enumerate(actions, 1):
            action_type = action.type
            if action_type == "navigate":
                last_result = await self.navigate(action.url)
            elif action_type == "click":
                last_result = await self.click(
                    ref=action.target_ref,
                    description=action.target_desc or action.description,
                )
            elif action_type == "fill":
                last_result = await self.fill(
                    ref=action.target_ref,
                    description=action.target_desc or action.description,
                    text=action.fill_value or action.text,
                )
            elif action_type == "assert_text":
                last_result = await self.assert_text(action.expected or action.text or action.description)
            elif action_type == "assert_visible":
                last_result = await self.assert_visible(
                    ref=action.target_ref,
                    description=action.target_desc or action.description,
                )
            elif action_type == "scroll":
                last_result = await self.scroll(action.direction, action.amount)
            elif action_type == "wait":
                last_result = await self.wait(action.seconds)
            else:
                return ExecutorResult(
                    type=ResultType.FAILURE,
                    reason=f"未知动作: {action_type}",
                    data={"step": index},
                )

            if not last_result.ok:
                last_result.data["failed_step"] = index
                last_result.data["failed_action"] = action_type
                return last_result

        return last_result

    # ─── 登录流程 ────────────────────────────────────────────────────────────

    async def detect_login_page(self) -> ExecutorResult:
        """
        检测当前页面是否为登录页。

        返回：
        - NO_AUTH_NEEDED: 不需要登录（已登录、免登录页等）
        - ASK_USER: 需要凭证（username + password）
        - DONE: 成功进入
        """
        snapshot = await self.get_snapshot()
        if snapshot.type != ResultType.SUCCESS:
            return ExecutorResult(type=ResultType.FAILURE, reason="无法获取页面快照")

        elements = snapshot.data.get("elements", [])
        url = self.page.url
        text = self._snapshot_text(snapshot)

        # 检测已登录状态
        if self._has_auth_required_indicator(text, elements):
            return ExecutorResult(
                type=ResultType.FAILURE,
                reason="页面提示需要登录",
                data={"reason": "auth_required"},
            )

        if self._has_logged_in_indicator(elements, text):
            self._is_logged_in = True
            self._login_detected = False
            return ExecutorResult(
                type=ResultType.NO_AUTH_NEEDED,
                summary="检测到已登录状态",
                data={"reason": "logged_in"},
            )

        # 分析表单字段，判断需要哪些凭证
        has_username = False
        has_password = False
        has_email = False
        has_captcha = False

        for e in elements:
            tag = e.get("tag")
            if tag != "input":
                continue
            placeholder = (e.get("placeholder") or "").lower()
            name = (e.get("name") or "").lower()
            id_attr = (e.get("id") or "").lower()
            input_type = (e.get("type") or "").lower()

            all_attrs = placeholder + " " + name + " " + id_attr

            if input_type == "password" or "pass" in all_attrs:
                has_password = True
            elif input_type == "email" or "mail" in all_attrs:
                has_email = True
            elif input_type in ("text", "") or "user" in all_attrs or "账号" in all_attrs or "用户名" in all_attrs or "name" in all_attrs:
                has_username = True
            elif "captcha" in all_attrs or "验证码" in all_attrs:
                has_captcha = True

        # 没有表单，可能是错误页
        if not (has_username or has_email or has_password):
            return ExecutorResult(
                type=ResultType.FAILURE,
                reason="页面没有找到登录表单，可能是点击错误或页面跳转异常",
            )

        # 需要凭证
        fields = []
        if has_username or has_email:
            fields.append("username")
        if has_password:
            fields.append("password")
        if has_captcha:
            fields.append("captcha")

        return ExecutorResult(
            type=ResultType.ASK_USER,
            data={"required_fields": fields},
            summary=f"需要凭证: {', '.join(fields)}",
        )

    async def find_best_entry(self, descriptions: List[str]) -> Optional[Dict]:
        """按多个同义描述查找最佳入口。"""
        seen = {}
        for desc in descriptions:
            result = await self.find_elements(desc)
            if result.type == ResultType.SUCCESS:
                for cand in result.data.get("candidates", []):
                    key = cand.get("ref")
                    if key and key not in seen:
                        seen[key] = cand

        candidates = list(seen.values())
        if not candidates:
            return None
        goal = "/".join(descriptions[:3])
        return await self.select_best_match(candidates, goal)

    def _element_blob(self, element: Dict[str, Any]) -> str:
        return " ".join([
            str(element.get("text", "")),
            str(element.get("placeholder", "")),
            str(element.get("label", "")),
            str(element.get("ariaLabel", "")),
            str(element.get("id", "")),
            str(element.get("name", "")),
            str(element.get("type", "")),
            str(element.get("role", "")),
            str(element.get("className", "")),
            str(element.get("href", "")),
        ]).lower()

    def _choose_login_submit(self, elements: List[Dict[str, Any]], password_ref: Optional[str]) -> Optional[str]:
        """
        Pick the real login submit button.

        Login pages often have both a nav/login entry and a form submit button.
        Prefer buttons/submit inputs near or in the same form as the password
        field, especially below it.
        """
        if not elements:
            return None

        by_ref = {e.get("ref"): e for e in elements}
        password_el = by_ref.get(password_ref or "")
        password_y = float(password_el.get("y", 0)) if password_el else 0.0
        password_form = password_el.get("formIndex", -1) if password_el else -1

        candidates = []
        submit_terms = ["登录", "登入", "登陆", "login", "sign in", "signin", "提交", "submit"]

        for e in elements:
            tag = (e.get("tag") or "").lower()
            input_type = (e.get("type") or "").lower()
            role = (e.get("role") or "").lower()
            blob = self._element_blob(e)

            clickable = tag in ("button", "a") or role in ("button", "link") or input_type in ("submit", "button")
            if not clickable:
                continue
            if not any(term in blob for term in submit_terms):
                continue

            score = 0.0
            if tag == "button":
                score += 50
            if input_type in ("submit", "button"):
                score += 45
            if role == "button":
                score += 25
            if any(term in blob for term in ["登录", "login", "signin", "sign in"]):
                score += 35

            form_index = e.get("formIndex", -1)
            if password_form != -1 and form_index == password_form:
                score += 80

            if password_el:
                y_delta = float(e.get("y", 0)) - password_y
                if -20 <= y_delta <= 280:
                    score += 60
                if y_delta < -40:
                    score -= 80
                score -= min(abs(y_delta) / 20, 30)

            href = (e.get("href") or "").lower()
            if tag == "a" and ("login" in href or "登录" in blob):
                score -= 30

            candidates.append((score, e))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1].get("ref")

    async def login(self, username: str, password: str) -> ExecutorResult:
        """
        执行登录流程。

        返回 DONE（成功）或 FAILURE。
        不调用 ask_user —— 凭证由 MainAgent 传入。
        """
        url_before = self.page.url

        # 找到输入框
        username_found = False
        password_found = False

        snapshot = await self.get_snapshot()
        if snapshot.type != ResultType.SUCCESS:
            return ExecutorResult(type=ResultType.FAILURE, reason="无法获取页面")

        elements = snapshot.data.get("elements", [])
        username_ref = None
        password_ref = None
        submit_ref = None

        for e in elements:
            tag = e.get("tag")
            if tag != "input":
                continue
            placeholder = (e.get("placeholder") or "").lower()
            name = (e.get("name") or "").lower()
            id_attr = (e.get("id") or "").lower()
            input_type = (e.get("type") or "").lower()
            all_attrs = placeholder + " " + name + " " + id_attr

            if not username_found and (
                input_type in ("text", "email", "")
                or "user" in all_attrs
                or "账号" in all_attrs
                or "用户名" in all_attrs
                or "name" in all_attrs
            ):
                if not username_ref:
                    username_ref = e["ref"]
                    username_found = True

            if not password_found and input_type == "password":
                if not password_ref:
                    password_ref = e["ref"]
                    password_found = True

        submit_ref = self._choose_login_submit(elements, password_ref)

        # 填写用户名
        if username_ref:
            r = await self.fill(ref=username_ref, text=username)
            if r.type == ResultType.SUCCESS:
                username_found = True

        # 填写密码
        if password_ref:
            r = await self.fill(ref=password_ref, text=password)
            if r.type == ResultType.SUCCESS:
                password_found = True

        # 点击提交
        if submit_ref:
            await self.click(ref=submit_ref)
            await asyncio.sleep(1.5)
        elif password_ref:
            try:
                await self.page.keyboard.press("Enter")
                await asyncio.sleep(1.5)
            except Exception:
                pass

        try:
            await self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        # 检测登录结果
        self._current_url = self.page.url
        snapshot2 = await self.get_snapshot()
        if snapshot2.type == ResultType.SUCCESS:
            snapshot2.data["auth_artifacts"] = await self._read_auth_artifacts()
            return self._classify_login_result(
                snapshot2,
                url_before=url_before,
                submitted=True,
            )

        return ExecutorResult(
            type=ResultType.FAILURE,
            reason="登录后无法获取页面结果，不能确认登录成功",
        )

    # ─── AI 任务执行 ─────────────────────────────────────────────────────────

    async def execute_task(self, task: str, context: Dict[str, Any] = None) -> ExecutorResult:
        """
        AI 驱动的任务执行。

        将任务 + 页面状态发给 AI，AI 返回操作步骤，Executor 执行。
        """
        context = context or {}
        snapshot = await self.get_snapshot()
        if snapshot.type != ResultType.SUCCESS:
            return ExecutorResult(type=ResultType.FAILURE, reason="无法获取页面")

        elements = snapshot.data.get("elements", [])
        elements_text = "\n".join([
            f"- <{e['tag']}> text='{e.get('text','')[:30]}' "
            f"placeholder='{e.get('placeholder','')}' ref={e['ref']}"
            for e in elements[:30]
        ])

        prompt = f"""你是浏览器自动化执行 Agent。根据用户任务和当前页面状态，决定下一步操作。

当前页面: {self.page.url}
页面元素:
{elements_text}

用户任务: {task}

可用工具:
- find_elements(description): 搜索元素候选列表
- click(ref): 点击元素
- fill(ref, text): 填写表单
- scroll(direction, amount): 滚动

分析步骤：
1. 理解用户任务
2. 在页面元素中找出相关元素
3. 如果需要凭证（username/password）且未提供，返回需要用户提供

输出 JSON 格式:
{{
  "action": "click" | "fill" | "navigate" | "need_credentials" | "done",
  "description": "操作描述（给用户看）",
  "target_ref": "e15（可选）",
  "target_desc": "点击/填写什么",
  "fill_value": "填写值（仅 fill 时）",
  "need_fields": ["username", "password"]（仅 need_credentials 时）
}}

只输出 JSON，不要其他内容。"""

        try:
            response = await self.ai_client.complete(prompt, "")
        except Exception as e:
            return ExecutorResult(type=ResultType.FAILURE, reason=f"AI 调用失败: {e}")

        # 解析响应
        match = re.search(r'\{.+\}', response, re.DOTALL)
        if not match:
            return ExecutorResult(type=ResultType.FAILURE, reason="AI 响应格式错误")

        import json
        try:
            plan = json.loads(match.group())
        except json.JSONDecodeError:
            return ExecutorResult(type=ResultType.FAILURE, reason="AI 响应 JSON 解析失败")

        action = plan.get("action", "")

        if action == "need_credentials":
            fields = plan.get("need_fields", [])
            return ExecutorResult(
                type=ResultType.ASK_USER,
                data={"required_fields": fields},
                summary=f"需要用户提供: {', '.join(fields)}",
            )

        if action == "click":
            ref = plan.get("target_ref", "")
            desc = plan.get("target_desc", "")
            return await self.click(ref=ref, description=desc)

        if action == "fill":
            ref = plan.get("target_ref", "")
            text = plan.get("fill_value", "")
            return await self.fill(ref=ref, text=text)

        if action == "navigate":
            url = plan.get("url", "")
            if url:
                return await self.navigate(url)
            return ExecutorResult(type=ResultType.FAILURE, reason="AI 未提供 URL")

        if action == "done":
            return ExecutorResult(type=ResultType.DONE, summary=plan.get("description", "任务完成"))

        return ExecutorResult(type=ResultType.DONE, summary="任务完成")

    # ─── 上下文 ──────────────────────────────────────────────────────────────

    def get_context(self) -> Dict[str, Any]:
        """获取当前上下文（供 MainAgent 使用）"""
        return {
            "url": self._current_url,
            "is_logged_in": self._is_logged_in,
            "page_history": list(self._page_history),
        }


__all__ = ["ExecutorAgent", "ExecutorResult", "ResultType"]
