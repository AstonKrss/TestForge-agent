"""
Structured plans for the interactive CLI agents.

The main model is allowed to think in natural language, but the CLI only
executes a small, explicit action schema. This keeps the browser worker
ref-first and makes model fallbacks safer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentAction:
    """One executable browser action."""

    type: str
    description: str = ""
    url: str = ""
    target_ref: str = ""
    target_desc: str = ""
    fill_value: str = ""
    text: str = ""
    expected: str = ""
    direction: str = "down"
    amount: int = 300
    seconds: float = 1.0
    ask_fields: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentAction":
        action_type = _as_str(data.get("type") or data.get("action")).strip().lower()
        description = _as_str(
            data.get("description")
            or data.get("target_desc")
            or data.get("targetDescription")
            or data.get("target")
        )
        fill_value = _as_str(
            data.get("fill_value")
            or data.get("value")
            or data.get("input")
            or data.get("content")
        )
        target_ref = _as_str(data.get("target_ref") or data.get("ref"))
        target_desc = _as_str(data.get("target_desc") or data.get("target") or description)
        ask_fields = data.get("ask_fields") or data.get("need_fields") or []
        if isinstance(ask_fields, str):
            ask_fields = [ask_fields]
        if not isinstance(ask_fields, list):
            ask_fields = []

        return cls(
            type=action_type,
            description=description,
            url=_as_str(data.get("url")),
            target_ref=target_ref,
            target_desc=target_desc,
            fill_value=fill_value,
            text=_as_str(data.get("text")),
            expected=_as_str(data.get("expected")),
            direction=_as_str(data.get("direction") or "down") or "down",
            amount=_as_int(data.get("amount"), 300),
            seconds=_as_float(data.get("seconds"), 1.0),
            ask_fields=[_as_str(field) for field in ask_fields if _as_str(field)],
        )


@dataclass
class AgentPlan:
    """Normalized main-agent plan."""

    intent: str = "chat"
    response: str = ""
    actions: List[AgentAction] = field(default_factory=list)
    ask_fields: List[str] = field(default_factory=list)
    reason: str = ""
    needs_replan_after_navigation: bool = False
    post_navigation_task: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.actions and not self.response and self.intent in ("", "chat")


def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first valid JSON object from a model response."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.splitlines() if not line.strip().startswith("```")
        ).strip()

    try:
        loaded = json.loads(cleaned)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : index + 1]
                try:
                    loaded = json.loads(candidate)
                    if isinstance(loaded, dict):
                        return loaded
                except json.JSONDecodeError:
                    return None
    return None


def normalize_agent_plan(raw: Dict[str, Any]) -> AgentPlan:
    """Coerce old and new model schemas into AgentPlan."""
    if not raw:
        return AgentPlan(intent="chat", response="")

    intent = _as_str(raw.get("intent") or raw.get("type") or raw.get("action")).strip().lower()
    if intent == "action":
        intent = _as_str(raw.get("action")).strip().lower()
    response = _as_str(raw.get("response") or raw.get("message"))
    reason = _as_str(raw.get("reason"))

    actions_data = raw.get("actions")
    actions: List[AgentAction] = []
    if isinstance(actions_data, list):
        actions = [AgentAction.from_dict(item) for item in actions_data if isinstance(item, dict)]
    elif intent in {
        "navigate",
        "click",
        "fill",
        "assert_text",
        "assert_visible",
        "scroll",
        "wait",
        "analyze",
        "test_login",
        "test_register",
    }:
        actions = [AgentAction.from_dict({**raw, "type": intent})]

    ask_fields = raw.get("ask_fields") or raw.get("need_fields") or []
    if isinstance(ask_fields, str):
        ask_fields = [ask_fields]
    if not isinstance(ask_fields, list):
        ask_fields = []

    if actions and intent in ("", "action"):
        intent = "execute"
    if not intent:
        intent = "chat"

    return AgentPlan(
        intent=intent,
        response=response,
        actions=actions,
        ask_fields=[_as_str(field) for field in ask_fields if _as_str(field)],
        reason=reason,
        needs_replan_after_navigation=bool(raw.get("needs_replan_after_navigation")),
        post_navigation_task=_as_str(raw.get("post_navigation_task")),
    )


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "AgentAction",
    "AgentPlan",
    "extract_json_payload",
    "normalize_agent_plan",
]
