"""
CLI MainAgent tests.
"""

from src.cli.agent_plan import AgentAction, AgentPlan
from src.cli.main_agent import MainAgent


class TestMainAgentUrlExtraction:
    def test_extracts_bare_domain_before_chinese_suffix(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._extract_url("测试一下www.baidu.com这个网站")

        assert url == "https://www.baidu.com"

    def test_extracts_absolute_url_before_chinese_suffix(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._extract_url("帮我测试http://47.242.21.40/这个网站")

        assert url == "http://47.242.21.40/"

    def test_preserves_chinese_url_path(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._extract_url("帮我测试http://47.242.21.40/blog/linux运维")

        assert url == "http://47.242.21.40/blog/linux运维"

    def test_canonicalizes_common_bare_domain(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._extract_url("帮我测试一下baidu.com 这个网站")

        assert url == "https://www.baidu.com"

    def test_prepare_url_cleans_model_suffix(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._prepare_url("https://www.baidu.com这个网站")

        assert url == "https://www.baidu.com"

    def test_extracts_root_url_before_root_level_task_suffix(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._extract_url("帮我测试一下http://47.242.21.40/这个网站的登录功能")

        assert url == "http://47.242.21.40/"

    def test_extracts_root_url_before_search_task_suffix(self):
        agent = MainAgent.__new__(MainAgent)

        url = agent._extract_url("帮我测试一下http://47.242.21.40/这个网站的搜索功能 搜索linux")

        assert url == "http://47.242.21.40/"


class TestMainAgentCredentialExtraction:
    def test_extracts_chinese_username_and_password(self):
        agent = MainAgent.__new__(MainAgent)

        creds = agent._extract_credentials("密码是Chuyangqi123@@ 账号是admin")

        assert creds == {"username": "admin", "password": "Chuyangqi123@@"}

    def test_extracts_credentials_without_separator(self):
        agent = MainAgent.__new__(MainAgent)

        creds = agent._extract_credentials("如果需要登录 账号admin 密码Chuyangqi123@@")

        assert creds == {"username": "admin", "password": "Chuyangqi123@@"}

    def test_extracts_english_username_and_password(self):
        agent = MainAgent.__new__(MainAgent)

        creds = agent._extract_credentials("username=admin password=secret123")

        assert creds == {"username": "admin", "password": "secret123"}

    def test_does_not_extract_credentials_from_explanation(self):
        agent = MainAgent.__new__(MainAgent)

        creds = agent._extract_credentials("密码就是正确的 是你没有点击登录账号密码下面的功能")

        assert creds == {}

    def test_conditional_login_is_not_explicit_login_test(self):
        agent = MainAgent.__new__(MainAgent)

        assert agent._looks_like_conditional_login("如果点赞功能需要登录 你就登录")
        assert not agent._looks_like_explicit_login_test("如果点赞功能需要登录 你就登录")
        assert agent._looks_like_explicit_login_test("测试一下登录功能")


class TestMainAgentRequestHelpers:
    def test_detects_combined_login_request(self):
        agent = MainAgent.__new__(MainAgent)

        assert agent._looks_like_login_request("帮我测试一下http://x.com的登录功能")

    def test_has_open_page_rejects_blank_page(self):
        agent = MainAgent.__new__(MainAgent)
        agent.context = type("Context", (), {"current_url": ""})()
        agent.page = type("Page", (), {"url": "about:blank"})()

        assert agent._has_open_page() is False

    def test_has_open_page_accepts_context_url(self):
        agent = MainAgent.__new__(MainAgent)
        agent.context = type("Context", (), {"current_url": "http://example.com"})()
        agent.page = type("Page", (), {"url": "about:blank"})()

        assert agent._has_open_page() is True

    def test_build_initial_request_plan_lists_sub_agents(self):
        agent = MainAgent.__new__(MainAgent)

        steps = agent._build_initial_request_plan(
            "帮我测试http://example.com的登录功能 账号是admin 密码是secret",
            "http://example.com",
            {"username": "admin", "password": "secret"},
        )

        agents = [step.agent for step in steps]
        assert agents == [
            "MainAgent",
            "BrowserAgent",
            "ExplorerAgent",
            "AuthAgent",
            "AuthAgent",
            "AuthAgent",
            "VerifierAgent",
            "ExplorerAgent",
        ]

    def test_build_plan_steps_for_model_actions(self):
        agent = MainAgent.__new__(MainAgent)
        plan = AgentPlan(
            intent="execute",
            actions=[
                AgentAction(type="fill", target_desc="搜索框", fill_value="天气"),
                AgentAction(type="click", target_desc="搜索按钮"),
                AgentAction(type="assert_text", expected="天气"),
            ],
        )

        steps = agent._build_plan_steps(plan)

        assert [step.agent for step in steps] == ["BrowserAgent", "BrowserAgent", "VerifierAgent"]

    def test_build_plan_steps_for_performance_action(self):
        agent = MainAgent.__new__(MainAgent)
        plan = AgentPlan(
            intent="execute",
            actions=[AgentAction(type="performance_audit", runs=3)],
        )

        steps = agent._build_plan_steps(plan)

        assert steps[0].agent == "PerformanceAgent"

    def test_detects_performance_request_and_runs(self):
        agent = MainAgent.__new__(MainAgent)

        assert agent._looks_like_performance_request("性能测试当前页面 3 次")
        assert agent._extract_performance_runs("性能测试当前页面 3 次") == 3

    def test_extract_search_keyword(self):
        agent = MainAgent.__new__(MainAgent)

        keyword = agent._extract_search_keyword("搜索一下linux试试看 然后点一个赞")

        assert keyword == "linux"

    def test_extract_comment_text(self):
        agent = MainAgent.__new__(MainAgent)

        text = agent._extract_comment_text("测试一下评论功能 评论一个666")

        assert text == "666"
