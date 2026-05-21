"""
Task state tests.
"""

from src.cli.task_state import BLOCKED, DONE, TaskState, extract_search_keyword


def test_task_state_extracts_search_article_like_goals():
    state = TaskState.from_user_input("搜索一下linux试试看 然后点一个赞给文章")

    assert [goal.type for goal in state.goals] == ["search", "open_article", "like"]
    assert extract_search_keyword(state.original) == "linux"


def test_task_state_marks_search_and_article_done_from_snapshot():
    state = TaskState.from_user_input("搜索 linux 然后进入文章")

    state.update_from_snapshot({
        "url": "http://example.com/blog/linux",
        "text": "linux command",
        "elements": [],
    })

    statuses = {goal.type: goal.status for goal in state.goals}
    assert statuses["search"] == DONE
    assert statuses["open_article"] == DONE


def test_task_state_blocks_comment_when_login_required():
    state = TaskState.from_user_input("评论一个666")

    state.update_from_snapshot({
        "url": "http://example.com/blog/post",
        "text": "请登录后发表评论 点击登录",
        "elements": [],
    })

    comment = next(goal for goal in state.goals if goal.type == "comment")
    assert comment.status == BLOCKED
    assert "登录" in comment.reason


def test_task_state_does_not_require_conditional_login_up_front():
    state = TaskState.from_user_input("点一个赞给文章 如果点赞功能需要登录 你就登录")

    assert "login" not in [goal.type for goal in state.goals]
    assert "like" in [goal.type for goal in state.goals]


def test_task_state_blocks_like_when_login_required():
    state = TaskState.from_user_input("点一个赞给文章")

    state.update_from_snapshot({
        "url": "http://example.com/blog/post",
        "text": "请登录后点赞 点击登录",
        "elements": [],
    })

    like = next(goal for goal in state.goals if goal.type == "like")
    assert like.status == BLOCKED
    assert "登录" in like.reason
