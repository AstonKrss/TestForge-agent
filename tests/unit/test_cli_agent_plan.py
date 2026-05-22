"""
Structured CLI plan tests.
"""

from src.cli.agent_plan import extract_json_payload, normalize_agent_plan


def test_extracts_fenced_json_payload():
    payload = extract_json_payload("""```json
{"intent": "execute", "actions": [{"type": "click", "target_ref": "e1"}]}
```""")

    assert payload["intent"] == "execute"
    assert payload["actions"][0]["target_ref"] == "e1"


def test_normalizes_action_list_plan():
    plan = normalize_agent_plan({
        "intent": "execute",
        "actions": [
            {"type": "fill", "target_ref": "e2", "fill_value": "admin"},
            {"type": "click", "target_ref": "e3"},
        ],
    })

    assert plan.intent == "execute"
    assert [action.type for action in plan.actions] == ["fill", "click"]
    assert plan.actions[0].fill_value == "admin"


def test_normalizes_legacy_single_step_plan():
    plan = normalize_agent_plan({
        "type": "fill",
        "description": "搜索框",
        "target_ref": "e10",
        "fill_value": "天气",
    })

    assert plan.intent == "fill"
    assert len(plan.actions) == 1
    assert plan.actions[0].target_ref == "e10"
    assert plan.actions[0].fill_value == "天气"


def test_normalizes_replan_metadata():
    plan = normalize_agent_plan({
        "intent": "execute",
        "needs_replan_after_navigation": True,
        "post_navigation_task": "搜索 linux 并点赞文章",
        "actions": [{"type": "navigate", "url": "http://example.com"}],
    })

    assert plan.needs_replan_after_navigation is True
    assert plan.post_navigation_task == "搜索 linux 并点赞文章"


def test_normalizes_performance_audit_action():
    plan = normalize_agent_plan({
        "intent": "performance_audit",
        "runs": 3,
        "reload": True,
    })

    assert plan.actions[0].type == "performance_audit"
    assert plan.actions[0].runs == 3
    assert plan.actions[0].reload is True


def test_normalizes_load_and_quality_actions():
    load_plan = normalize_agent_plan({
        "intent": "load_test",
        "requests": 50,
        "concurrency": 5,
        "method": "HEAD",
        "timeout": 3,
    })
    quality_plan = normalize_agent_plan({"intent": "quality_audit"})

    assert load_plan.actions[0].type == "load_test"
    assert load_plan.actions[0].requests == 50
    assert load_plan.actions[0].concurrency == 5
    assert load_plan.actions[0].method == "HEAD"
    assert load_plan.actions[0].timeout == 3
    assert quality_plan.actions[0].type == "quality_audit"


def test_normalizes_known_feature_suite_action():
    plan = normalize_agent_plan({"intent": "known_feature_suite"})

    assert plan.actions[0].type == "known_feature_suite"


def test_normalizes_full_test_suite_action():
    plan = normalize_agent_plan({"intent": "full_test_suite"})

    assert plan.actions[0].type == "full_test_suite"
