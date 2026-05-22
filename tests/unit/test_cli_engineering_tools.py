"""
Engineering helper tests.
"""

from src.cli.engineering_tools import (
    ReportGenerator,
    TestDataManager,
    TestPlanGenerator,
    UrlScope,
    extract_relative_url,
    is_url_in_scope,
)


def test_test_plan_generator_detects_common_features():
    plan = TestPlanGenerator().generate({
        "url": "http://example.com",
        "text": "搜索 登录 评论 点赞",
        "elements": [
            {"tag": "input", "placeholder": "搜索"},
            {"tag": "a", "text": "登录"},
        ],
    })

    features = [item.feature for item in plan]
    assert "搜索功能" in features
    assert "登录/认证" in features
    assert "评论/留言" in features


def test_test_plan_generator_derives_site_specific_link_items():
    plan = TestPlanGenerator().generate({
        "url": "http://example.com",
        "text": "博客 标签 归档 项目 工具箱",
        "elements": [
            {"tag": "a", "text": "博客", "href": "http://example.com/blog"},
            {"tag": "a", "text": "留言", "href": "http://example.com/guestbook"},
            {"tag": "a", "text": "工具箱", "href": "http://example.com/tools"},
        ],
    })

    features = [item.feature for item in plan]
    assert "博客入口" in features
    assert "留言入口" in features
    assert "专题入口/工具页面" in features
    assert next(item for item in plan if item.feature == "留言入口").needs_login is True


def test_test_data_manager_generates_user_data():
    data = TestDataManager().generate("用户")

    assert data["kind"] == "user"
    assert data["username"].startswith("tf_user_")
    assert data["email"].endswith("@example.com")


def test_url_scope_filters_same_origin_and_patterns():
    scope = UrlScope(
        base_url="https://example.com/blog",
        mode="focused",
        include_patterns=["/blog*"],
        exclude_patterns=["/blog/admin*"],
    )

    assert extract_relative_url("https://example.com/blog/linux?q=1#top") == "/blog/linux?q=1#top"
    assert is_url_in_scope("https://example.com/blog/linux", scope)
    assert not is_url_in_scope("https://example.com/blog/admin/settings", scope)
    assert not is_url_in_scope("https://other.example.com/blog/linux", scope)


def test_single_page_scope_allows_same_path_hash_changes():
    scope = UrlScope(base_url="https://example.com/app#/dashboard", mode="single_page")

    assert is_url_in_scope("https://example.com/app#/dashboard/settings", scope)
    assert not is_url_in_scope("https://example.com/other#/dashboard", scope)


def test_report_generator_markdown_contains_events():
    reporter = ReportGenerator()
    text = reporter._markdown({
        "session_name": "demo",
        "current_url": "http://example.com",
        "events": [{"time": "now", "role": "user", "text": "测试"}],
        "test_plan": [{"feature": "搜索", "risk": "高", "needs_login": False, "precondition": "打开页面", "expected": "成功"}],
    })

    assert "TestForge Report" in text
    assert "**user**" in text


def test_report_generator_markdown_accepts_site_map_nodes_shape():
    reporter = ReportGenerator()
    text = reporter._markdown({
        "session_name": "demo",
        "current_url": "http://example.com",
        "events": [{"time": "now", "role": "user", "text": "测试"}],
        "site_map": {
            "nodes": [
                {"text": "Blog", "href": "http://example.com/blog"},
            ],
        },
    })

    assert "Blog -> http://example.com/blog" in text
    assert "测试" in text
