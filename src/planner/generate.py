"""
Generate - 生成测试计划
========================

从探索结果生成测试计划
"""

import json
import os
import time
from typing import Dict, Any, Optional, List
from pathlib import Path


async def generate_test_plan(
    run_id: str,
    config: Dict[str, Any],
    logger,
    cwd: str = ".",
) -> Dict[str, Any]:
    """
    生成测试计划

    Args:
        run_id: 运行 ID
        config: 配置
        logger: 日志器
        cwd: 工作目录

    Returns:
        测试计划和输出信息
    """

    # 读取探索图
    graph = await _read_exploration_graph(cwd, run_id)

    if not graph or not graph.get("pages"):
        return {
            "ok": False,
            "error": "No exploration graph found",
            "plan": None,
            "output": {"errors": ["No pages found in exploration graph"]},
        }

    # 获取 AI 客户端
    from ...ai_client import create_ai_client, AIConfig
    config_ai = AIConfig.from_env()
    ai_client = create_ai_client(config_ai)

    # 构建提示
    base_url = config.get("baseUrl", config.get("base_url", ""))
    test_types = config.get("testTypes", ["functional", "form", "navigation", "boundary"])

    # 构建页面摘要
    pages_summary = "\n".join([
        f"- [{p.get('id', 'p')}] {p.get('url', '')} (depth={p.get('depth', 0)})"
        for p in graph.get("pages", [])[:20]
    ])

    system_prompt = f"""You are a TestForge Test Planner.

Based on the exploration results, generate a comprehensive test plan.

## Pages Discovered:
{pages_summary}

## Test Types to Generate:
{', '.join(test_types)}

## Requirements:
1. For each key behavior, generate BOTH happy path AND boundary/negative cases
2. Each test case must include:
   - id: unique identifier
   - name: descriptive name
   - type: test type
   - priority: p0/p1/p2
   - requiresLogin: boolean
   - preconditions: list of conditions
   - steps: list of action descriptions
   - markdownPath: relative path for spec file

3. Use template variables for URLs:
   - {{BASE_URL}} for base URL
   - {{LOGIN_BASE_URL}} for login page
   - {{USERNAME}}, {{PASSWORD}} for credentials

4. Output JSON with:
   - flows: navigation flows
   - cases: test cases

## Output Format:
{{
  "flows": [
    {{"id": "flow-1", "name": "Login Flow", "pagePath": ["p1", "p2"]}}
  ],
  "cases": [
    {{
      "id": "case-1",
      "name": "Valid Login",
      "type": "functional",
      "priority": "p1",
      "requiresLogin": false,
      "relatedPageIds": ["p1"],
      "markdownPath": "valid-login.md",
      "preconditions": ["User is logged out"],
      "steps": [
        {{"description": "Navigate to {{BASE_URL}}/login"}},
        {{"description": "Fill username with {{USERNAME}}"}},
        {{"description": "Fill password with {{PASSWORD}}"}},
        {{"description": "Click login button"}}
      ]
    }}
  ]
}}

Only output JSON, no other text.
"""

    user_msg = f"Generate test plan for {base_url} with {len(graph.get('pages', []))} pages."

    try:
        response = await ai_client.complete(user_msg, system_prompt)

        # 解析 JSON
        plan = _extract_json_plan(response)

        if not plan:
            return {
                "ok": False,
                "error": "Failed to parse test plan JSON",
                "plan": None,
                "output": {"errors": ["Failed to parse test plan"]},
            }

        # 写入结果
        output = await _write_test_plan(plan, run_id, cwd, config)

        return {
            "ok": True,
            "plan": plan,
            "output": output,
        }

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "plan": None,
            "output": {"errors": [str(e)]},
        }


async def _read_exploration_graph(cwd: str, run_id: str) -> Optional[Dict]:
    """读取探索图"""
    graph_path = Path(cwd) / ".testforge" / "runs" / run_id / "plan-explore" / "explore-graph.json"

    if not graph_path.exists():
        # 尝试在 .autoqa 目录下 (兼容)
        graph_path = Path(cwd) / ".autoqa" / "runs" / run_id / "plan-explore" / "explore-graph.json"

    if not graph_path.exists():
        return None

    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


async def _write_test_plan(
    plan: Dict[str, Any],
    run_id: str,
    cwd: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """写入测试计划"""

    base_dir = Path(cwd) / ".testforge" / "runs" / run_id / "plan"
    specs_dir = base_dir / "specs"

    errors = []
    spec_paths = []

    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        specs_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        errors.append(f"Failed to create directories: {e}")
        return {"errors": errors}

    # 写入 test-plan.json
    try:
        plan_path = base_dir / "test-plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
    except Exception as e:
        errors.append(f"Failed to write test-plan.json: {e}")

    # 写入每个测试用例的规范
    cases = plan.get("cases", [])
    for case in cases:
        markdown_path = case.get("markdownPath", "")
        if not markdown_path:
            # 生成默认路径
            case_id = case.get("id", "unknown")
            case_type = case.get("type", "functional")
            markdown_path = f"{case_type}-{case_id}.md"

        # 确保文件名安全
        markdown_path = markdown_path.replace("/", "_").replace("\\", "_")
        if not markdown_path.endswith(".md"):
            markdown_path += ".md"

        spec_path = specs_dir / markdown_path

        # 确保目录存在
        try:
            spec_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errors.append(f"Failed to create directory for {markdown_path}: {e}")
            continue

        # 生成 Markdown
        markdown = _build_markdown_spec(case, config)

        try:
            with open(spec_path, "w", encoding="utf-8") as f:
                f.write(markdown)
            spec_paths.append(str(spec_path.relative_to(Path(cwd))))
        except Exception as e:
            errors.append(f"Failed to write {markdown_path}: {e}")

    return {
        "planPath": str(base_dir / "test-plan.json"),
        "specPaths": spec_paths,
        "errors": errors,
    }


def _build_markdown_spec(case: Dict[str, Any], config: Dict[str, Any]) -> str:
    """构建 Markdown 规范"""

    name = case.get("name", "Test Case")
    case_type = case.get("type", "functional")
    priority = case.get("priority", "p1").upper()

    lines = [
        f"# {name} (Auto-generated)",
        "",
        f"Type: {case_type} | Priority: {priority}",
        "",
        "## Preconditions",
    ]

    # 前置条件
    preconditions = case.get("preconditions", [])
    if preconditions:
        for pre in preconditions:
            lines.append(f"- {pre}")
    else:
        lines.append(f"- Base URL accessible: {{BASE_URL}}")

    lines.append("")
    lines.append("## Steps")

    # 步骤
    steps = case.get("steps", [])
    if not steps:
        lines.append("1. Navigate to {{BASE_URL}}/")
    else:
        for i, step in enumerate(steps, 1):
            description = step.get("description", "")
            lines.append(f"{i}. {description}")

    lines.append("")
    return "\n".join(lines)


def _extract_json_plan(text: str) -> Optional[Dict]:
    """从文本中提取 JSON 测试计划"""
    import re

    # 尝试找 JSON 代码块
    match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass

    # 尝试找原始 JSON
    match = re.search(r'\{[\s\S]*"flows"[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass

    match = re.search(r'\{[\s\S]*"cases"[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass

    return None