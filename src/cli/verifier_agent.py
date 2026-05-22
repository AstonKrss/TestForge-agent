"""
VerifierAgent - validates action effects and high-level task completion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .agent_plan import AgentAction
from .task_state import TaskState


@dataclass
class VerificationResult:
    ok: bool
    reason: str = ""
    needs_replan: bool = False
    suggestion: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


class VerifierAgent:
    """Independent verifier for browser actions and task state."""

    def verify_action(
        self,
        action: AgentAction,
        before: Dict[str, Any],
        after: Dict[str, Any],
    ) -> VerificationResult:
        action_type = action.type
        before_url = before.get("url", "")
        after_url = after.get("url", "")
        desc = " ".join([action.description, action.target_desc, action.text, action.expected]).lower()

        if action_type == "navigate":
            if after_url and after_url != "about:blank":
                return VerificationResult(True)
            return VerificationResult(False, "导航后没有有效页面", needs_replan=True)

        if action_type == "click":
            if any(term in desc for term in ["搜索结果", "第一篇", "文章标题", "文章详情", "查看全文"]):
                if "/blog/" in after_url and "/search" not in after_url:
                    return VerificationResult(True)
                return VerificationResult(
                    False,
                    "点击文章候选后仍未进入文章详情页",
                    needs_replan=True,
                    suggestion="改用 extract_search_results 中 href 指向 /blog/ 的第一条结果",
                )
            if any(term in desc for term in ["搜索", "search", "查询"]):
                if "/search" in after_url or before_url != after_url:
                    return VerificationResult(True)
                return VerificationResult(False, "点击搜索后页面没有进入搜索状态", needs_replan=True)
            if any(term in desc for term in ["点赞", "赞", "like"]):
                text = (after.get("text") or "").lower()
                if self._has_auth_required(text, after.get("elements") or []):
                    return VerificationResult(
                        False,
                        "点赞动作被登录要求阻塞",
                        needs_replan=True,
                        suggestion="先执行登录，登录后回到原文章继续点赞",
                    )
                if any(term in text for term in ["已赞", "已点赞", "取消赞", "unlike", "liked"]):
                    return VerificationResult(True)
                return VerificationResult(False, "点击点赞后没有检测到点赞成功标识", needs_replan=True)
            if any(term in desc for term in ["评论", "留言", "comment", "提交"]):
                text = (after.get("text") or "").lower()
                if self._has_auth_required(text, after.get("elements") or []):
                    return VerificationResult(
                        False,
                        "评论动作被登录要求阻塞",
                        needs_replan=True,
                        suggestion="先执行登录，登录后回到原页面继续评论",
                    )

        if action_type == "fill":
            text = (after.get("text") or "").lower()
            if any(term in desc for term in ["评论", "留言", "comment"]) and self._has_auth_required(text, after.get("elements") or []):
                return VerificationResult(
                    False,
                    "评论输入框需要登录后才能使用",
                    needs_replan=True,
                    suggestion="点击页面登录入口并在登录后继续原评论任务",
                )
            return VerificationResult(True)

        if action_type in {"assert_text", "assert_visible"}:
            return VerificationResult(True)

        return VerificationResult(True)

    def _has_auth_required(self, text: str, elements: List[Dict[str, Any]]) -> bool:
        terms = [
            "请登录",
            "请先登录",
            "登录后",
            "点击登录",
            "需要登录",
            "未登录",
            "login required",
            "please login",
            "please log in",
            "sign in to",
        ]
        lower = (text or "").lower()
        if any(term.lower() in lower for term in terms):
            return True
        for element in elements or []:
            blob = " ".join(str(element.get(key, "")) for key in ("text", "label", "ariaLabel", "placeholder", "href")).lower()
            if any(term.lower() in blob for term in terms):
                return True
        return False

    def evaluate_task(self, state: TaskState, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        state.update_from_snapshot(snapshot)
        if state.is_done():
            return {
                "done": True,
                "summary": "用户要求的测试动作已完成或页面已出现预期结果",
                "state": state.to_dict(),
            }

        remaining = state.remaining_text()
        blocked = any(goal.status == "blocked" for goal in state.remaining_goals())
        return {
            "done": False,
            "should_continue": not blocked or bool(remaining),
            "remaining": remaining,
            "summary": f"任务还未确认完成，剩余: {remaining}",
            "state": state.to_dict(),
        }


__all__ = ["VerificationResult", "VerifierAgent"]
