"""
CLI ExecutorAgent tests.
"""

from src.cli.executor_agent import ExecutorAgent, ExecutorResult, ResultType


def test_choose_login_submit_prefers_button_below_password():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    elements = [
        {
            "ref": "e1",
            "tag": "a",
            "text": "登录",
            "href": "http://example.com/login",
            "y": 20,
            "formIndex": -1,
        },
        {
            "ref": "e2",
            "tag": "input",
            "type": "password",
            "placeholder": "请输入密码",
            "y": 220,
            "formIndex": 0,
        },
        {
            "ref": "e3",
            "tag": "button",
            "text": "登录",
            "y": 270,
            "formIndex": 0,
        },
    ]

    assert executor._choose_login_submit(elements, "e2") == "e3"


def test_classify_login_result_rejects_failure_text():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    snapshot = ExecutorResult(
        type=ResultType.SUCCESS,
        data={
            "url": "http://example.com/login",
            "text": "登录失败：用户名或密码错误",
            "elements": [],
        },
    )

    result = executor._classify_login_result(snapshot, submitted=True)

    assert result.type == ResultType.FAILURE
    assert "登录失败" in result.reason


def test_classify_login_result_does_not_treat_missing_form_as_success():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    snapshot = ExecutorResult(
        type=ResultType.SUCCESS,
        data={
            "url": "http://example.com/login",
            "text": "请重新登录",
            "elements": [],
        },
    )

    result = executor._classify_login_result(snapshot, submitted=True)

    assert result.type == ResultType.FAILURE
    assert "需要登录" in result.reason


def test_classify_login_result_accepts_auth_artifacts():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    snapshot = ExecutorResult(
        type=ResultType.SUCCESS,
        data={
            "url": "http://example.com/login",
            "text": "首页",
            "elements": [],
            "auth_artifacts": {"has_auth_artifact": True, "storage_keys": ["localStorage:token"]},
        },
    )

    result = executor._classify_login_result(snapshot, submitted=True)

    assert result.type == ResultType.DONE
    assert "token" in result.summary


def test_classify_login_result_accepts_form_disappeared_without_failure():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    snapshot = ExecutorResult(
        type=ResultType.SUCCESS,
        data={
            "url": "http://example.com/login",
            "text": "个人资料",
            "elements": [],
        },
    )

    result = executor._classify_login_result(snapshot, submitted=True)

    assert result.type == ResultType.DONE


def test_classify_login_result_accepts_logged_in_indicator():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    snapshot = ExecutorResult(
        type=ResultType.SUCCESS,
        data={
            "url": "http://example.com/admin",
            "text": "欢迎 admin 退出",
            "elements": [],
        },
    )

    result = executor._classify_login_result(snapshot, submitted=True)

    assert result.type == ResultType.DONE


def test_auth_required_text_never_counts_as_logged_in():
    executor = ExecutorAgent.__new__(ExecutorAgent)
    snapshot = ExecutorResult(
        type=ResultType.SUCCESS,
        data={
            "url": "http://example.com/blog/post",
            "text": "请登录后发表评论 点击登录 欢迎阅读本文",
            "elements": [
                {"ref": "e1", "tag": "a", "text": "点击登录", "href": "/login"},
            ],
        },
    )

    result = executor._classify_login_result(snapshot, submitted=True)

    assert result.type == ResultType.FAILURE
    assert "需要登录" in result.reason
