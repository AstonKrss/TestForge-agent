"""
Task state for interactive CLI testing.

The planner can be fuzzy, but execution needs a crisp view of which user goals
are still pending. This module tracks those sub-goals across re-plans.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


PENDING = "pending"
DONE = "done"
BLOCKED = "blocked"
FAILED = "failed"


@dataclass
class TaskGoal:
    """A structured sub-goal inside a user task."""

    type: str
    label: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = PENDING
    reason: str = ""

    @property
    def done(self) -> bool:
        return self.status == DONE


@dataclass
class TaskState:
    """State machine for one high-level CLI task."""

    original: str
    goals: List[TaskGoal] = field(default_factory=list)

    @classmethod
    def from_user_input(cls, text: str) -> "TaskState":
        goals: List[TaskGoal] = []
        keyword = extract_search_keyword(text)
        comment = extract_comment_text(text)
        lower = (text or "").lower()
        conditional_login = is_conditional_login(text)
        explicit_login = is_explicit_login_test(text)

        if explicit_login or (
            any(term in lower for term in ["login", "sign in", "signin"])
            and not conditional_login
        ):
            goals.append(TaskGoal("login", "登录"))

        if any(term in lower for term in ["搜索", "search", "查询"]):
            goals.append(TaskGoal("search", f"搜索 {keyword or '指定关键词'}", {"keyword": keyword}))

        wants_article = any(term in lower for term in ["文章", "详情", "全文", "第一篇"]) or any(
            term in lower for term in ["点赞", "赞", "like", "评论", "留言", "comment"]
        )
        if wants_article:
            goals.append(TaskGoal("open_article", "进入文章详情页"))

        if any(term in lower for term in ["点赞", "点一个赞", "赞", "like"]):
            goals.append(TaskGoal("like", "点赞文章"))

        if any(term in lower for term in ["评论", "留言", "comment"]):
            goals.append(TaskGoal("comment", f"发表评论 {comment or ''}".strip(), {"text": comment}))

        if not goals:
            goals.append(TaskGoal("generic", "执行用户请求"))

        return cls(original=text, goals=goals)

    def update_from_snapshot(self, snapshot: Dict[str, Any]) -> None:
        text = (snapshot.get("text") or "").lower()
        url = (snapshot.get("url") or "").lower()
        elements = snapshot.get("elements") or []
        auth_artifacts = snapshot.get("auth_artifacts") or {}

        for goal in self.goals:
            if goal.status == DONE:
                continue
            if goal.type == "search":
                keyword = (goal.params.get("keyword") or "").lower()
                if keyword and (keyword in text or keyword in url):
                    goal.status = DONE
                elif "/search" in url and ("q=" in url or keyword):
                    goal.reason = "已在搜索页，但未确认关键词结果"
            elif goal.type == "open_article":
                if "/blog/" in url and "/search" not in url:
                    goal.status = DONE
                else:
                    goal.reason = "尚未进入文章详情页"
            elif goal.type == "like":
                if has_auth_required(text, elements):
                    goal.status = BLOCKED
                    goal.reason = "需要先登录"
                elif any(term in text for term in ["已赞", "已点赞", "取消赞", "unlike", "liked"]):
                    goal.status = DONE
                else:
                    goal.reason = "尚未确认点赞成功"
            elif goal.type == "comment":
                comment = (goal.params.get("text") or "").lower()
                if has_auth_required(text, elements):
                    goal.status = BLOCKED
                    goal.reason = "需要先登录"
                elif comment and comment in text:
                    goal.status = DONE
                else:
                    goal.reason = "尚未确认评论出现"
            elif goal.type == "login":
                if auth_artifacts.get("has_auth_artifact") or has_logged_in_signal(text, elements):
                    goal.status = DONE
                elif has_auth_required(text, elements):
                    goal.reason = "页面仍提示需要登录"

    def is_done(self) -> bool:
        return all(goal.done for goal in self.goals)

    def remaining_goals(self) -> List[TaskGoal]:
        return [goal for goal in self.goals if not goal.done]

    def remaining_text(self) -> str:
        parts = []
        for goal in self.remaining_goals():
            if goal.status == BLOCKED and goal.reason:
                parts.append(f"{goal.label}（{goal.reason}）")
            else:
                parts.append(goal.label)
        return "，然后".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "goals": [
                {
                    "type": goal.type,
                    "label": goal.label,
                    "params": dict(goal.params),
                    "status": goal.status,
                    "reason": goal.reason,
                }
                for goal in self.goals
            ],
        }


def extract_search_keyword(task: str) -> str:
    patterns = [
        r"搜索一下\s*([A-Za-z0-9_\-]+)",
        r"搜索\s*([A-Za-z0-9_\-]+)",
        r"search\s+([A-Za-z0-9_\-]+)",
        r"搜索一下\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)",
        r"搜索\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, task or "", re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip()
        value = re.split(r"(?:试试看|然后|并|给|点|，|,|。|；|;|\s)", value)[0].strip()
        if value and value not in {"功能", "一下", "试试看"}:
            return value
    return ""


def extract_comment_text(task: str) -> str:
    patterns = [
        r"评论一个\s*([^\s，,。；;]+)",
        r"评论\s*([^\s，,。；;]+)",
        r"留言\s*([^\s，,。；;]+)",
        r"comment\s+([^\s，,。；;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, task or "", re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value and value not in {"功能", "一下"}:
                return value
    return ""


def is_conditional_login(text: str) -> bool:
    lower = (text or "").lower()
    return bool(
        ("如果" in (text or "") and "登录" in (text or "") and any(term in (text or "") for term in ["需要", "才能", "就"]))
        or re.search(r"\bif\b.*\b(log ?in|sign ?in)\b", lower)
    )


def is_explicit_login_test(text: str) -> bool:
    lower = (text or "").lower()
    terms = [
        "登录功能",
        "测试登录",
        "登录系统",
        "登录流程",
        "login function",
        "test login",
        "login flow",
    ]
    return any(term in lower or term in (text or "") for term in terms)


def has_auth_required(text: str, elements: List[Dict[str, Any]] = None) -> bool:
    terms = [
        "请登录",
        "请先登录",
        "登录后",
        "点击登录",
        "未登录",
        "需要登录",
        "重新登录",
        "请重新登录",
        "login required",
        "please login",
        "please log in",
    ]
    lower = (text or "").lower()
    if any(term.lower() in lower for term in terms):
        return True
    for element in elements or []:
        blob = " ".join(str(element.get(key, "")) for key in ("text", "placeholder", "label", "ariaLabel", "href")).lower()
        if any(term.lower() in blob for term in terms):
            return True
    return False


def has_logged_in_signal(text: str, elements: List[Dict[str, Any]] = None) -> bool:
    if has_auth_required(text, elements):
        return False
    terms = ["退出", "注销", "logout", "sign out", "dashboard", "个人中心", "用户中心"]
    lower = (text or "").lower()
    if any(term.lower() in lower for term in terms):
        return True
    for element in elements or []:
        blob = " ".join(str(element.get(key, "")) for key in ("text", "label", "ariaLabel", "href")).lower()
        if any(term.lower() in blob for term in terms):
            return True
    return False


__all__ = [
    "BLOCKED",
    "DONE",
    "FAILED",
    "PENDING",
    "TaskGoal",
    "TaskState",
    "extract_comment_text",
    "extract_search_keyword",
    "has_auth_required",
    "has_logged_in_signal",
    "is_conditional_login",
    "is_explicit_login_test",
]
