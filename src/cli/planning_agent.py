"""
PlanningAgent - turns user goals into executable agent plans.

This is the only component that should interpret the user's testing goal.
Regex helpers in MainAgent are guardrails/fallbacks, not the planner.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..ai_client import AIClient
from .agent_plan import AgentPlan, extract_json_payload, normalize_agent_plan


class PlanningAgent:
    """AI planning agent for the interactive CLI."""

    def __init__(self, ai_client: AIClient):
        self.ai_client = ai_client

    async def plan(
        self,
        user_input: str,
        *,
        current_url: str = "",
        current_title: str = "",
        elements: List[Dict[str, Any]] = None,
        context_summary: str = "",
    ) -> AgentPlan:
        elements = elements or []
        prompt = self._build_prompt(
            user_input=user_input,
            current_url=current_url,
            current_title=current_title,
            elements=elements,
            context_summary=context_summary,
        )
        response = await self.ai_client.complete(prompt, "")
        payload = extract_json_payload(response)
        if not payload:
            raise ValueError(f"PlanningAgent JSON 解析失败: {response[:160]}")
        return normalize_agent_plan(payload)

    def _build_prompt(
        self,
        *,
        user_input: str,
        current_url: str,
        current_title: str,
        elements: List[Dict[str, Any]],
        context_summary: str,
    ) -> str:
        elements_text = self._format_elements(elements)
        return f"""你是 TestForge 的 PlanningAgent。你的职责是理解用户测试需求，拆成可执行步骤，并分配给下层 Agent。

当前页面: {current_url or "(未打开)"}
页面标题: {current_title or "(未知)"}
会话状态: {context_summary or "(无)"}
当前页面元素:
{elements_text}

用户需求:
{user_input}

可用下层能力:
- BrowserAgent: navigate/click/fill/scroll/wait
- ExplorerAgent: extract_links/extract_search_results/extract_forms/extract_article_content/extract_auth_requirements/extract_like_buttons
- PerformanceAgent: performance_audit，用浏览器 Performance API 采集页面加载、资源体积、慢资源
- LoadTestAgent: load_test，对单个 URL 做受控 HTTP 并发请求，输出吞吐、P95、错误率
- QualityAuditAgent: quality_audit，检查无障碍、基础 SEO、安全链接/表单问题
- SecurityAgent: security_audit，检查安全响应头、混合内容、危险链接、表单安全
- AccessibilityAgent: accessibility_audit，检查 alt/label/lang/H1/空按钮等基础无障碍
- SuiteAgent: full_test_suite，一键执行测试计划、站点地图、质量、安全、无障碍、性能、低压压测、网络/API摘要和报告
- FeatureTestAgent: known_feature_suite，安全测试当前页面/站点已发现的所有功能入口，不自动删除、退出、发布或付款
- AuthAgent: test_login/test_register，并可请求 username/password/captcha
- VerifierAgent: 验证 URL 变化、文本出现、登录状态、搜索结果、点赞/评论是否完成

你只能输出 JSON，schema 如下:
{{
  "intent": "execute|navigate|test_login|test_register|analyze|ask_user|chat",
  "response": "需要给用户看的说明，可为空",
  "needs_replan_after_navigation": true,
  "post_navigation_task": "打开页面后要继续完成的任务，可为空",
  "ask_fields": ["username", "password"],
  "actions": [
    {{
      "type": "navigate|test_login|test_register|analyze|generate_test_plan|full_test_suite|known_feature_suite|performance_audit|load_test|quality_audit|security_audit|accessibility_audit|extract_search_results|extract_forms|extract_article_content|extract_auth_requirements|extract_like_buttons|click|fill|assert_text|assert_visible|scroll|wait|ask_user",
      "description": "动作说明",
      "url": "只在 navigate 时填写",
      "target_ref": "当前页面元素 ref，例如 e12。没有当前页面元素时留空",
      "target_desc": "元素描述，例如 搜索框/登录按钮/点赞按钮",
      "fill_value": "fill 动作的值",
      "expected": "验证文本",
      "runs": 1,
      "reload": false,
      "requests": 20,
      "concurrency": 2,
      "method": "GET",
      "timeout": 10,
      "ask_fields": ["username", "password"]
    }}
  ]
}}

规划规则:
1. 你是规划者，不要闲聊，不要解释，只输出 JSON。
2. 如果用户给了 URL，第一步通常是 navigate。URL 必须只包含真实地址，不要包含“这个网站的登录功能/这个页面的搜索功能/试试看”等自然语言。
3. 例: “帮我测试 http://47.242.21.40/这个网站的登录功能” 的 url 必须是 “http://47.242.21.40/”。
4. 合法中文路径要保留，例如 “http://host/blog/linux运维” 不能被截断。
5. 如果用户明确要求测试登录/登录功能，actions 应包含 navigate（如有 URL）和 test_login。账号密码由 MainAgent 记录，不要写进 response。
5.1 如果用户只是说“如果点赞/评论需要登录就登录”，这是条件登录，不要一开始就 test_login；先完成搜索/进入文章/尝试受保护动作，只有页面提示需要登录时再规划登录。
6. 如果用户要求打开网站后再搜索、点赞、写文章等，而当前还没有打开目标页面: 先输出 navigate，并设置 needs_replan_after_navigation=true，post_navigation_task 写剩余任务。
7. 如果当前页面已有元素 ref，则 click/fill 必须优先使用 target_ref；如果没有把握，用 target_desc。
8. 搜索任务要看当前页面元素：如果只有“搜索”入口/链接，没有搜索输入框，先 click 搜索入口，并设置 needs_replan_after_navigation=true，post_navigation_task 写“输入关键词并提交搜索，之后继续用户剩余任务”。
9. 如果当前页已经有搜索输入框，才规划 fill 搜索框，然后 click 搜索按钮。
10. 如果缺少账号、密码、验证码等必要信息，intent=ask_user，并填写 ask_fields。
11. 点赞任务通常需要先进入文章详情，再点击点赞/like 按钮；如果当前只在搜索结果页，先打开最相关的文章，再继续规划点赞。
12. 如果页面文字或元素出现“请登录/请先登录/登录后/点击登录”，并且用户任务是评论、点赞、发文章等受保护操作，必须先规划 test_login 或 click “点击登录”，不要直接 fill 评论框。
13. 如果评论框提示“请登录后发表评论”，当前状态就是未登录；不要把页面上的“登录/欢迎/后台”等普通文本当成已登录。
14. 如果用户要求性能测试、加载速度、performance、测速，规划 performance_audit；如果用户给了 URL 且未打开目标页，先 navigate，再 performance_audit。
15. 如果用户要求压力测试/压测/负载测试/load test/stress test，规划 load_test。默认 requests=20、concurrency=2；如果用户指定并发/次数，填入对应字段。
16. 如果用户要求页面质量/无障碍/a11y/SEO/基础安全检查，规划 quality_audit；如有 URL 先 navigate。
17. 如果用户明确要求安全检查，规划 security_audit；要求无障碍/可访问性时规划 accessibility_audit。
18. 如果用户要求测试计划/测试矩阵，规划 generate_test_plan。
19. 如果用户要求“完整测试/全量测试/全套测试/一键测试/生成完整报告”，规划 full_test_suite；如果用户给了 URL 且未打开目标页，先 navigate，再 full_test_suite。
20. 如果用户要求“测试所有功能/全部功能/当前页面所有已知功能/能看到的功能都测一遍”，规划 known_feature_suite；如果用户给了 URL 且未打开目标页，先 navigate，再 known_feature_suite。
"""

    def _format_elements(self, elements: List[Dict[str, Any]], limit: int = 40) -> str:
        if not elements:
            return "(当前无元素快照)"
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


__all__ = ["PlanningAgent"]
