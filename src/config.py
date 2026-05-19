"""
Config - 配置管理
==================

配置加载、合并、验证
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


CONFIG_FILE = "testforge.config.json"


DEFAULT_GUARDRAILS = {
    "maxToolCallsPerSpec": 200,
    "maxConsecutiveErrors": 8,
    "maxRetriesPerStep": 5,
}

DEFAULT_PLAN_GUARDRAILS = {
    "maxAgentTurnsPerRun": 1000,
    "maxSnapshotsPerRun": 500,
    "maxPagesPerRun": 100,
}

DEFAULT_PLAN_CONFIG = {
    "maxDepth": 3,
    "maxPages": 50,
    "includePatterns": [],
    "excludePatterns": [],
    "exploreScope": "site",
    "testTypes": ["functional", "form", "navigation", "responsive", "boundary", "security"],
}


def load_config(cwd: Optional[str] = None) -> Dict[str, Any]:
    """
    加载配置文件

    Args:
        cwd: 工作目录

    Returns:
        配置结果 {"ok": bool, "config": dict, "error": str}
    """
    cwd = cwd or os.getcwd()
    config_path = Path(cwd) / CONFIG_FILE

    # 尝试 testforge.config.json
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {"ok": True, "config": config}
        except Exception as e:
            return {"ok": False, "error": f"Failed to parse {CONFIG_FILE}: {e}"}

    # 尝试 autoqa.config.json (兼容)
    autoqa_path = Path(cwd) / "autoqa.config.json"
    if autoqa_path.exists():
        try:
            with open(autoqa_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {"ok": True, "config": config}
        except Exception as e:
            return {"ok": False, "error": f"Failed to parse autoqa.config.json: {e}"}

    # 返回默认配置
    return {
        "ok": True,
        "config": {
            "schemaVersion": 1,
            "guardrails": DEFAULT_GUARDRAILS,
            "exportDir": "tests/autoqa",
            "plan": DEFAULT_PLAN_CONFIG,
        },
    }


def resolve_guardrails(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析 guardrails 配置

    Args:
        config: 完整配置

    Returns:
        Guardrails 配置
    """
    guardrails = config.get("guardrails", {})

    return {
        "maxToolCallsPerSpec": guardrails.get("maxToolCallsPerSpec", DEFAULT_GUARDRAILS["maxToolCallsPerSpec"]),
        "maxConsecutiveErrors": guardrails.get("maxConsecutiveErrors", DEFAULT_GUARDRAILS["maxConsecutiveErrors"]),
        "maxRetriesPerStep": guardrails.get("maxRetriesPerStep", DEFAULT_GUARDRAILS["maxRetriesPerStep"]),
    }


def load_plan_config(config: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    加载并合并计划配置

    Args:
        config: 完整配置
        options: 命令行选项

    Returns:
        计划配置
    """
    plan = config.get("plan", {})

    result = {
        "baseUrl": options.get("url") if options else None,
        "maxDepth": plan.get("maxDepth", DEFAULT_PLAN_CONFIG["maxDepth"]),
        "maxPages": plan.get("maxPages", DEFAULT_PLAN_CONFIG["maxPages"]),
        "includePatterns": plan.get("includePatterns", []),
        "excludePatterns": plan.get("excludePatterns", []),
        "exploreScope": plan.get("exploreScope", DEFAULT_PLAN_CONFIG["exploreScope"]),
        "testTypes": plan.get("testTypes", DEFAULT_PLAN_CONFIG["testTypes"]),
    }

    # 从环境变量覆盖
    if not result["baseUrl"]:
        result["baseUrl"] = os.environ.get("TF_BASE_URL", os.environ.get("AUTOQA_BASE_URL"))

    # 从命令行选项覆盖
    if options:
        if options.get("depth") is not None:
            result["maxDepth"] = options["depth"]
        if options.get("max_pages"):
            result["maxPages"] = options["max_pages"]
        if options.get("max_agent_turns"):
            result.setdefault("guardrails", {})["maxAgentTurnsPerRun"] = options["max_agent_turns"]
        if options.get("max_snapshots"):
            result.setdefault("guardrails", {})["maxSnapshotsPerRun"] = options["max_snapshots"]
        if options.get("explore_scope"):
            result["exploreScope"] = options["explore_scope"]
        if options.get("test_types"):
            # 解析逗号分隔的测试类型
            test_types = [t.strip() for t in options["test_types"].split(",")]
            result["testTypes"] = test_types

    # 认证配置
    if plan.get("auth") or options.get("login_url"):
        auth = plan.get("auth", {})
        result["auth"] = {
            "loginUrl": options.get("login_url") or auth.get("loginUrl"),
            "username": options.get("username") or auth.get("username") or os.environ.get("TF_USERNAME"),
            "password": options.get("password") or auth.get("password") or os.environ.get("TF_PASSWORD"),
        }

    # Guardrails
    plan_guardrails = plan.get("guardrails", {})
    result["guardrails"] = {
        "maxAgentTurnsPerRun": plan_guardrails.get("maxAgentTurnsPerRun", DEFAULT_PLAN_GUARDRAILS["maxAgentTurnsPerRun"]),
        "maxSnapshotsPerRun": plan_guardrails.get("maxSnapshotsPerRun", DEFAULT_PLAN_GUARDRAILS["maxSnapshotsPerRun"]),
        "maxPagesPerRun": plan_guardrails.get("maxPagesPerRun", DEFAULT_PLAN_GUARDRAILS["maxPagesPerRun"]),
    }

    return result


def validate_url(url: str) -> bool:
    """验证 URL"""
    try:
        from urllib.parse import urlparse
        result = urlparse(url)
        return bool(result.scheme and result.netloc)
    except:
        return False


__all__ = [
    "CONFIG_FILE",
    "DEFAULT_GUARDRAILS",
    "DEFAULT_PLAN_GUARDRAILS",
    "DEFAULT_PLAN_CONFIG",
    "load_config",
    "resolve_guardrails",
    "load_plan_config",
    "validate_url",
]