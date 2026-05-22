"""
Regression tests for interactive CLI agent behavior.
"""

import asyncio

from src.cli.agent_plan import AgentAction
from src.cli.engineering_tools import NetworkRecorder
from src.cli.executor_agent import ExecutorResult, ResultType
from src.cli.main_agent import MainAgent, SessionContext
from src.cli.task_state import TaskState


def test_network_recorder_clear_resets_records_and_pending_starts():
    recorder = NetworkRecorder()
    request = object()
    recorder.records.append({"url": "https://example.com"})
    recorder._starts[request] = 1.0

    recorder.clear()

    assert recorder.records == []
    assert recorder._starts == {}


def test_task_state_marks_write_article_editor_as_done():
    state = TaskState.from_user_input("测试写文章")

    state.update_from_snapshot({
        "url": "http://example.com/dashboard/write",
        "text": "输入文章标题 预览 发布",
        "elements": [],
    })

    assert state.is_done()


def test_publish_click_is_blocked_without_explicit_confirmation():
    agent = MainAgent.__new__(MainAgent)
    agent.context = type("Context", (), {"current_url": "http://example.com/dashboard/write"})()
    agent.page = type("Page", (), {"url": "http://example.com/dashboard/write"})()
    agent._current_user_task_text = "测试写文章"

    result = asyncio.run(agent._guard_risky_click(AgentAction(type="click", target_desc="发布")))

    assert result is not None
    assert result.type == ResultType.DONE
    assert result.data["publish_blocked"] is True


def test_publish_click_allowed_with_explicit_confirmation():
    agent = MainAgent.__new__(MainAgent)
    agent.context = type("Context", (), {"current_url": "http://example.com/dashboard/write"})()
    agent.page = type("Page", (), {"url": "http://example.com/dashboard/write"})()
    agent._current_user_task_text = "确认发布测试文章"

    result = asyncio.run(agent._guard_risky_click(AgentAction(type="click", target_desc="发布")))

    assert result is None


def test_site_root_url_preserves_scheme_host_and_port():
    agent = MainAgent.__new__(MainAgent)

    assert agent._site_root_url("http://example.com:8080/login") == "http://example.com:8080/"


def test_load_test_supports_inverted_phrase_and_intensity():
    agent = MainAgent.__new__(MainAgent)

    assert agent._looks_like_load_test_request("进行测试压力 加大力度")
    medium = agent._extract_load_test_params("进行压力测试 加大力度")
    assert medium["requests"] == 50
    assert medium["concurrency"] == 5

    high = agent._extract_load_test_params("进行压力测试 拉满")
    assert high["requests"] == 100
    assert high["concurrency"] == 10


def test_load_test_task_completion_stops_replanning_after_success():
    agent = MainAgent.__new__(MainAgent)
    agent.context = type("Context", (), {"tested_features": ["压力测试"]})()

    status = asyncio.run(agent._evaluate_task_completion("进行测试压力 加大力度"))

    assert status["done"] is True
    assert "压力测试" in status["summary"]


def test_task_state_recognizes_load_test_without_generic_goal():
    state = TaskState.from_user_input("进行测试压力 加大力度")

    assert [goal.type for goal in state.goals] == ["load_test"]


def test_ladder_load_test_request_detection():
    agent = MainAgent.__new__(MainAgent)

    assert agent._looks_like_load_ladder_request("进行阶梯压力测试")
    assert agent._looks_like_load_ladder_request("自动加压直到失败")


def test_feature_map_remembers_write_article_entry():
    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.page = type("Page", (), {"url": "http://example.com/dashboard/admin"})()

    agent._remember_page_features({
        "url": "http://example.com/dashboard/admin",
        "elements": [
            {"text": "写文章", "href": "http://example.com/dashboard/write"},
        ],
    })

    assert agent._feature_href("write_article") == "http://example.com/dashboard/write"


def test_feature_map_does_not_store_current_page_for_hrefless_feature_buttons():
    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.page = type("Page", (), {"url": "http://example.com/dashboard/admin"})()

    agent._remember_page_features({
        "url": "http://example.com/dashboard/admin",
        "elements": [
            {"text": "write article"},
        ],
    })

    assert agent._feature_href("write_article") == ""


class _FakeExecutor:
    async def navigate(self, url):
        return ExecutorResult(
            type=ResultType.SUCCESS,
            data={"url": url, "title": "Write"},
            summary=f"opened {url}",
        )


def test_repeated_write_article_action_recovers_to_editor_url():
    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.context.add_page("http://example.com/dashboard/admin")
    agent.page = type("Page", (), {"url": "http://example.com/dashboard/admin"})()
    agent.executor = _FakeExecutor()
    agent._current_task_state = TaskState.from_user_input("测试写文章")
    agent._action_repeat_counts = {}
    agent._used_recoveries = set()

    action = AgentAction(type="click", target_desc="管理")
    assert asyncio.run(agent._maybe_recover_repeated_action(action)) is None
    assert asyncio.run(agent._maybe_recover_repeated_action(action)) is None
    result = asyncio.run(agent._maybe_recover_repeated_action(action))

    assert result.type == ResultType.SUCCESS
    assert result.data["url"] == "http://example.com/dashboard/write"


def test_all_known_feature_request_detection():
    agent = MainAgent.__new__(MainAgent)

    assert agent._looks_like_all_known_feature_request("测试当前页面所有已知功能")
    assert agent._looks_like_all_known_feature_request("把页面能看到的功能都测一遍")
    assert not agent._looks_like_all_known_feature_request("测试登录功能")


def test_full_suite_phrase_wins_over_known_feature_suite_detection():
    agent = MainAgent.__new__(MainAgent)

    assert agent._looks_like_all_known_feature_request("test all functions")
    assert agent._looks_like_full_test_request("full suite test all functions and generate report")
    assert not agent._looks_like_all_known_feature_request("full suite test all functions and generate report")
    assert not agent._looks_like_full_test_request("test all functions")


def test_build_plan_steps_for_known_feature_suite():
    agent = MainAgent.__new__(MainAgent)
    plan = type("Plan", (), {
        "intent": "execute",
        "actions": [AgentAction(type="known_feature_suite")],
        "needs_replan_after_navigation": False,
        "post_navigation_task": "",
    })()

    steps = agent._build_plan_steps(plan)

    assert steps[0].agent == "FeatureTestAgent"


def test_build_plan_steps_for_full_test_suite():
    agent = MainAgent.__new__(MainAgent)
    plan = type("Plan", (), {
        "intent": "execute",
        "actions": [AgentAction(type="full_test_suite")],
        "needs_replan_after_navigation": False,
        "post_navigation_task": "",
    })()

    steps = agent._build_plan_steps(plan)

    assert steps[0].agent == "SuiteAgent"


def test_known_feature_candidates_skip_unsafe_links():
    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.context.add_page("http://example.com/")
    agent.page = type("Page", (), {"url": "http://example.com/"})()

    candidates = agent._known_feature_candidates({
        "nodes": [
            {"text": "搜索", "href": "http://example.com/search", "same_origin": True},
            {"text": "退出", "href": "http://example.com/logout", "same_origin": True},
            {"text": "删除文章", "href": "http://example.com/delete/1", "same_origin": True},
            {"text": "GitHub", "href": "https://github.com/example", "same_origin": False},
        ],
    })

    assert [item["href"] for item in candidates] == ["http://example.com/search"]


def test_page_broken_reason_detects_404():
    agent = MainAgent.__new__(MainAgent)

    reason = agent._page_broken_reason({
        "title": "404: This page could not be found.",
        "text": "",
        "elements": [],
    })

    assert "404" in reason


def test_feature_or_common_href_falls_back_to_site_path():
    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.context.add_page("http://example.com/blog")
    agent.page = type("Page", (), {"url": "http://example.com/blog"})()

    assert agent._feature_or_common_href("search", ["/search"]) == "http://example.com/search"


def test_smoke_login_entry_uses_login_page_detector():
    class FakeExecutor:
        async def navigate(self, href):
            return ExecutorResult(type=ResultType.SUCCESS, data={"url": href})

        async def detect_login_page(self):
            return ExecutorResult(
                type=ResultType.ASK_USER,
                data={"required_fields": ["username", "password"]},
            )

    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.context.add_page("http://example.com/")
    agent.context.known_feature_map = {
        "example.com": {"login": {"href": "http://example.com/login", "label": "登录"}}
    }
    agent.page = type("Page", (), {"url": "http://example.com/"})()
    agent.executor = FakeExecutor()
    results = []

    asyncio.run(agent._smoke_test_login_entry(results))

    assert results[0]["ok"] is True
    assert results[0]["fields"] == ["username", "password"]


def test_deep_feature_classifier_covers_site_sections():
    agent = MainAgent.__new__(MainAgent)

    assert agent._classify_deep_feature("归档", "http://example.com/archive") == "归档"
    assert agent._classify_deep_feature("工具箱", "http://example.com/tools") == "工具箱"
    assert agent._classify_deep_feature("推荐资源 学习平台 AI工具", "http://example.com/resources") == "资源"
    assert agent._classify_deep_feature("安全工具箱", "http://example.com/tools/security") == "安全工具"
    assert agent._classify_deep_feature("趣味游戏", "http://example.com/games") == "游戏"
    assert agent._classify_deep_feature("立即注册", "http://example.com/register") == "注册入口"
    assert agent._classify_deep_feature("文章标题", "http://example.com/blog/post-1") == ""


def test_deep_feature_candidates_use_sitemap_major_sections():
    agent = MainAgent.__new__(MainAgent)
    agent.context = SessionContext()
    agent.context.site_map = {
        "nodes": [
            {"text": "归档", "href": "http://example.com/archive", "same_origin": True},
            {"text": "工具箱", "href": "http://example.com/tools", "same_origin": True},
            {"text": "博客 文章A", "href": "http://example.com/blog/a", "same_origin": True},
            {"text": "GitHub", "href": "https://github.com/example", "same_origin": False},
        ]
    }

    candidates = agent._deep_feature_candidates()

    assert [item["feature"] for item in candidates] == ["归档", "工具箱"]


def test_nested_feature_candidates_find_tools_children():
    agent = MainAgent.__new__(MainAgent)
    agent._nested_feature_seen = set()
    parent = {"feature": "工具箱", "href": "http://example.com/tools", "label": "工具箱"}
    snapshot = {
        "elements": [
            {"text": "首页", "href": "http://example.com/"},
            {"text": "实用资源", "href": "http://example.com/resources"},
            {"text": "安全工具箱", "href": "http://example.com/tools/security"},
            {"text": "删除", "href": "http://example.com/tools/delete"},
            {"text": "外部站点", "href": "https://other.example.com/tool"},
        ]
    }

    candidates = agent._nested_feature_candidates(parent, snapshot)

    assert [(item["feature"], item["href"]) for item in candidates] == [
        ("安全工具", "http://example.com/tools/security"),
        ("资源", "http://example.com/resources"),
    ]


def test_safe_tool_button_filter_allows_local_transform_only():
    agent = MainAgent.__new__(MainAgent)

    assert agent._is_safe_tool_button({"text": "Base64 编码"})
    assert agent._is_safe_tool_button({"text": "JSON 格式化"})
    assert not agent._is_safe_tool_button({"text": "开始扫描"})
    assert not agent._is_safe_tool_button({"text": "提交"})
