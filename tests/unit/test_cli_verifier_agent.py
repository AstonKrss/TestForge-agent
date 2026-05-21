"""
VerifierAgent tests.
"""

from src.cli.agent_plan import AgentAction
from src.cli.task_state import TaskState
from src.cli.verifier_agent import VerifierAgent


def test_verifier_rejects_article_click_without_article_url():
    verifier = VerifierAgent()

    result = verifier.verify_action(
        AgentAction(type="click", target_desc="搜索结果页的第一篇文章"),
        {"url": "http://example.com/search?q=linux"},
        {"url": "http://example.com/search?q=linux", "text": ""},
    )

    assert result.ok is False
    assert result.needs_replan is True


def test_verifier_accepts_article_click_with_blog_url():
    verifier = VerifierAgent()

    result = verifier.verify_action(
        AgentAction(type="click", target_desc="搜索结果页的第一篇文章"),
        {"url": "http://example.com/search?q=linux"},
        {"url": "http://example.com/blog/linux", "text": ""},
    )

    assert result.ok is True


def test_verifier_evaluates_task_state():
    verifier = VerifierAgent()
    state = TaskState.from_user_input("搜索 linux 然后点一个赞给文章")

    result = verifier.evaluate_task(state, {
        "url": "http://example.com/search?q=linux",
        "text": "linux result",
        "elements": [],
    })

    assert result["done"] is False
    assert "点赞" in result["remaining"]
