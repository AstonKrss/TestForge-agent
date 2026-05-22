"""
Additional verifier regression tests.
"""

from src.cli.agent_plan import AgentAction
from src.cli.verifier_agent import VerifierAgent


def test_verifier_flags_like_blocked_by_auth():
    verifier = VerifierAgent()

    result = verifier.verify_action(
        AgentAction(type="click", target_desc="点赞按钮"),
        {"url": "http://example.com/blog/post", "text": ""},
        {"url": "http://example.com/blog/post", "text": "请先登录后点赞", "elements": []},
    )

    assert result.ok is False
    assert result.needs_replan is True
    assert "登录" in result.suggestion


def test_verifier_flags_comment_blocked_by_auth():
    verifier = VerifierAgent()

    result = verifier.verify_action(
        AgentAction(type="fill", target_desc="评论输入框", fill_value="666"),
        {"url": "http://example.com/blog/post", "text": ""},
        {"url": "http://example.com/blog/post", "text": "登录后发表评论", "elements": []},
    )

    assert result.ok is False
    assert result.needs_replan is True
