"""
Output - 输出探索结果和计划摘要
================================

写入三个文件:
- explore-graph.json: 页面节点 + 导航边
- explore-elements.json: 每个页面的交互元素
- explore-transcript.jsonl: Agent 工具调用和思考过程
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List


def sanitize_path_segment(value: str) -> str:
    """清理路径段"""
    cleaned = (value or "").replace(r"[^a-zA-Z0-9._-]+", "_").replace(r"\.{2,}", "_").replace("^_+|_+$", "")
    if cleaned in (".", ".."):
        return "unknown"
    return cleaned if cleaned else "unknown"


async def write_exploration_result(
    result: Any,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    写入探索结果

    Args:
        result: 探索结果 (ExplorationResult 或类似对象)
        options: 选项 {"run_id": str, "cwd": str}

    Returns:
        输出信息 {graphPath, elementsPath, transcriptPath, errors}
    """
    run_id = options.get("run_id", "unknown") if options else "unknown"
    cwd = options.get("cwd", ".") if options else "."

    errors = []
    output = {
        "graphPath": None,
        "elementsPath": None,
        "transcriptPath": None,
        "errors": errors,
    }

    # 安全化 run_id
    safe_run_id = sanitize_path_segment(run_id)
    dir_path = Path(cwd) / ".testforge" / "runs" / safe_run_id / "plan-explore"

    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"Failed to create directory: {e}")
        return output

    # 获取 graph 数据
    graph = getattr(result, "graph", None) or result.get("graph", {"pages": [], "edges": []}) or {"pages": [], "edges": []}
    pages = graph.get("pages", []) if isinstance(graph, dict) else []
    edges = graph.get("edges", []) if isinstance(graph, dict) else []

    # 写入 explore-graph.json
    graph_data = {"pages": pages, "edges": edges}
    graph_path = dir_path / "explore-graph.json"
    try:
        with open(graph_path, "w", encoding="utf-8") as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
        output["graphPath"] = f".testforge/runs/{safe_run_id}/plan-explore/explore-graph.json"
    except Exception as e:
        errors.append(f"Failed to write explore-graph.json: {e}")

    # 写入 explore-elements.json
    result_run_id = getattr(result, "run_id", run_id)
    result_finished_at = getattr(result, "finished_at", "") or result.get("finishedAt", "")

    elements = {
        "runId": result_run_id,
        "generatedAt": result_finished_at or "",
        "pages": [
            {
                "pageId": p.get("id", ""),
                "pageUrl": p.get("url", ""),
                "elements": p.get("elementSummary", []) or p.get("elements", []),
                "forms": p.get("forms", []),
            }
            for p in pages
        ],
    }
    elements_path = dir_path / "explore-elements.json"
    try:
        with open(elements_path, "w", encoding="utf-8") as f:
            json.dump(elements, f, indent=2, ensure_ascii=False)
        output["elementsPath"] = f".testforge/runs/{safe_run_id}/plan-explore/explore-elements.json"
    except Exception as e:
        errors.append(f"Failed to write explore-elements.json: {e}")

    # 写入 explore-transcript.jsonl
    transcript = getattr(result, "transcript", []) or result.get("transcript", [])
    transcript_path = dir_path / "explore-transcript.jsonl"
    try:
        lines = []
        for entry in transcript:
            if hasattr(entry, "__dict__"):
                # dataclass -> dict
                lines.append(json.dumps(entry.__dict__, ensure_ascii=False))
            else:
                lines.append(json.dumps(entry, ensure_ascii=False))
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        output["transcriptPath"] = f".testforge/runs/{safe_run_id}/plan-explore/explore-transcript.jsonl"
    except Exception as e:
        errors.append(f"Failed to write explore-transcript.jsonl: {e}")

    return output


async def write_plan_summary(
    run_id: str,
    cwd: str,
    exploration: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
    guardrail_triggered: bool = False,
    exit_code: int = 0,
) -> Dict[str, Any]:
    """
    写入计划摘要

    Args:
        run_id: 运行 ID
        cwd: 工作目录
        exploration: 探索结果 (可选)
        plan: 测试计划 (可选)
        guardrail_triggered: Guardrail 是否触发
        exit_code: 退出码

    Returns:
        输出信息
    """

    # 探索统计
    if exploration:
        exploration_stats = exploration.get("stats", {})
        pages_visited = exploration_stats.get("pagesVisited", 0)
        elements_found = exploration_stats.get("elementsFound", 0)
        forms_found = exploration_stats.get("formsFound", 0)
        links_found = exploration_stats.get("linksFound", 0)
        max_depth_reached = exploration_stats.get("maxDepthReached", 0)
        configured_depth = exploration_stats.get("configuredDepth", 0)
    else:
        pages_visited = elements_found = forms_found = links_found = 0
        max_depth_reached = configured_depth = 0

    # 测试计划统计
    if plan:
        cases = plan.get("cases", [])
        cases_generated = len(cases)

        type_set = set()
        priorities = {"p0": 0, "p1": 0, "p2": 0}

        for case in cases:
            type_set.add(case.get("type", "functional"))
            priority = case.get("priority", "p1")
            if priority in priorities:
                priorities[priority] += 1

        test_types = list(type_set)
    else:
        cases_generated = 0
        test_types = []
        priorities = {"p0": 0, "p1": 0, "p2": 0}

    # Guardrail 信息
    guardrail_info = None
    if guardrail_triggered and exploration:
        triggered = exploration.get("guardrailTriggered")
        if triggered:
            guardrail_info = {
                "code": triggered.get("code", ""),
                "limit": triggered.get("limit", 0),
                "actual": triggered.get("actual", 0),
                "triggeredAt": triggered.get("triggeredAt", ""),
            }

    # 构建摘要
    summary = {
        "runId": run_id,
        "generatedAt": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "baseUrl": (exploration or {}).get("startUrl", (plan or {}).get("configSnapshot", {}).get("baseUrl", "unknown")),
        "exploration": {
            "pagesVisited": pages_visited,
            "elementsFound": elements_found,
            "formsFound": forms_found,
            "linksFound": links_found,
            "maxDepthReached": max_depth_reached,
            "configuredDepth": configured_depth,
        },
        "testPlan": {
            "casesGenerated": cases_generated,
            "testTypes": test_types,
            "priorities": priorities,
        },
    }

    if guardrail_info:
        summary["guardrailTriggered"] = guardrail_info

    # 写入文件
    base_dir = Path(cwd) / ".testforge" / "runs" / run_id / "plan"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    summary_path = base_dir / "plan-summary.json"
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        return {"path": f".testforge/runs/{run_id}/plan/plan-summary.json"}
    except Exception as e:
        return {"error": f"Failed to write plan-summary.json: {e}"}


def sanitize_path_segment(value: str) -> str:
    """清理路径段"""
    cleaned = (value or "").replace(r"[^a-zA-Z0-9._-]+", "_").replace(r"\.{2,}", "_").replace("^_+|_+$", "")
    if cleaned in (".", ".."):
        return "unknown"
    return cleaned if cleaned else "unknown"