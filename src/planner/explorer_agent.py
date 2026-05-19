"""
Explorer Agent - Agent驱动的探索
=================================

使用 AI Agent 探索 Web 应用结构
"""

import json
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from .explore import explore as basic_explore, ExplorationResult


@dataclass
class PageNode:
    """页面节点"""
    id: str
    url: str
    title: str = ""
    depth: int = 0
    element_summary: List[Dict] = field(default_factory=list)
    forms: List[Dict] = field(default_factory=list)
    links: List[Dict] = field(default_factory=list)
    snapshot_ref: Optional[str] = None


@dataclass
class NavigationEdge:
    """导航边"""
    from_page: str
    to_page: str
    trigger: str  # click, fill, etc.
    element_ref: Optional[str] = None


@dataclass
class TranscriptEntry:
    """转录条目"""
    timestamp: str
    run_id: str
    type: str  # agent_prompt, tool_call, tool_result, agent_thinking, guardrail_triggered
    tool_name: Optional[str] = None
    tool_input: Optional[Dict] = None
    thinking: Optional[str] = None
    guardrail: Optional[Dict] = None
    prompt: Optional[str] = None


@dataclass
class GuardrailTrigger:
    """Guardrail 触发"""
    code: str
    limit: int
    actual: int
    triggered_at: str


@dataclass
class ExplorationResult:
    """探索结果"""
    ok: bool
    run_id: str
    start_url: str
    started_at: str = ""
    finished_at: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)
    graph: Dict[str, Any] = field(default_factory=dict)
    transcript: List[TranscriptEntry] = field(default_factory=list)
    login: Optional[Dict] = None
    error: Optional[Dict] = None
    guardrail_triggered: Optional[GuardrailTrigger] = None


EXPLORE_ALLOWED_TOOLS = [
    "mcp__browser__snapshot",
    "mcp__browser__navigate",
    "mcp__browser__click",
    "mcp__browser__fill",
    "mcp__browser__select_option",
    "mcp__browser__scroll",
    "mcp__browser__wait",
]


def build_explore_prompt(config: Dict[str, Any]) -> str:
    """构建探索提示"""

    auth_section = ""
    if config.get("auth"):
        auth = config["auth"]
        auth_section = f"""
Login Credentials:
- Login URL: {auth.get('loginUrl', '')}
- Username: {auth.get('username', '')}
- Password: {auth.get('password', '')[:3]}***

IMPORTANT: You MUST complete login first before exploring. After navigating to the login URL:
1. Call snapshot() to see the login form
2. Use fill() to enter the username and password
3. Use click() to submit the login form
4. Call snapshot() to verify login succeeded
5. If login fails, report the error and stop exploration
"""

    guardrail_section = ""
    if config.get("guardrails"):
        g = config["guardrails"]
        guardrail_section = f"""
Guardrails (stop exploration when any limit is reached):
- Maximum pages to visit: {g.get('maxPagesPerRun', 50)}
- Maximum tool calls: {g.get('maxAgentTurnsPerRun', 200)}
- Maximum snapshots: {g.get('maxSnapshotsPerRun', 100)}
"""

    explore_scope = config.get("exploreScope", "site")
    base_url = config.get("baseUrl", config.get("base_url", ""))
    max_depth = config.get("maxDepth", 3)

    url_scope_section = ""
    if explore_scope == "focused":
        include_patterns = config.get("includePatterns", [])
        exclude_patterns = config.get("excludePatterns", [])

        url_scope_section = f"""
## URL Scope Constraints (Focused Mode)

You are operating in FOCUSED exploration mode. Only explore pages that match the URL scope:

**In-Scope URL Definition:**
- A URL is in-scope if its relative path matches at least one include pattern
- AND does not match any exclude pattern

**Include Patterns (whitelist):**
{chr(10).join(['- ' + p for p in include_patterns]) if include_patterns else '- (none specified)'}

**Exclude Patterns (blacklist):**
{chr(10).join(['- ' + p for p in exclude_patterns]) if exclude_patterns else '- (none)'}

**Exploration Strategy:**
- Prioritize exploring pages that match the include patterns
- Avoid clicking on navigation links that lead to excluded modules
"""

    elif explore_scope == "single_page":
        include_patterns = config.get("includePatterns", [])

        url_scope_section = f"""
## URL Scope Constraints (Single Page Mode)

You are operating in SINGLE PAGE exploration mode. Focus on the current page's interactions:

**Allowed URL Changes:**
- Hash-based sub-routes within the same page (e.g., #/tab1, #/tab2)
- URLs explicitly allowed in include patterns: {', '.join(include_patterns) if include_patterns else '(none)'}

**Exploration Strategy:**
- Focus on interactions within the current page: search, filtering, sorting, pagination
- Avoid clicking global navigation links that lead to different modules
"""

    return f"""You are a TestForge Exploration Agent. Your task is to explore a web application and document its structure.

Base URL: {base_url}
Maximum Depth: {max_depth}
{auth_section}
{guardrail_section}
{url_scope_section}

## Your Mission

Systematically explore the web application to discover:
1. All navigable pages and their URLs
2. Interactive elements on each page (buttons, links, inputs, forms)
3. Navigation relationships between pages
4. Form structures and their fields

## Exploration Strategy

1. **Start**: Navigate to the base URL
2. **On each page**:
   - Call snapshot() to capture the page structure
   - Analyze the snapshot to identify:
     - Clickable elements (buttons, links)
     - Form inputs (text fields, dropdowns, checkboxes)
     - Navigation links to other pages
   - Record the page URL, title, and all interactive elements
3. **Navigate**: Click on internal links to discover new pages (stay within the same domain)
4. **Depth control**: Track how many clicks deep you are from the start page. Stop exploring paths deeper than {max_depth} levels.
5. **Avoid duplicates**: Don't revisit pages you've already explored

## IMPORTANT: Final Output Required

You MUST end your exploration by providing a JSON summary in this EXACT format:

```json
{{
  "pages": [
    {{
      "id": "p1",
      "url": "https://example.com/",
      "title": "Home Page",
      "depth": 0,
      "elements": [
        {{"id": "e1", "kind": "button", "text": "Login", "selector": "button.login"}},
        {{"id": "e2", "kind": "link", "text": "About", "href": "/about"}}
      ],
      "forms": [
        {{"id": "f1", "action": "/search", "fields": [{{"name": "q", "type": "text"}}]}}
      ]
    }}
  ],
  "edges": [
    {{"from": "p1", "to": "p2", "trigger": "click", "elementRef": "e2"}}
  ],
  "loginStatus": {{
    "attempted": true,
    "ok": true
  }}
}}
```

ALWAYS provide the JSON output at the end of your response, even if you encountered errors.

## Rules

- Use ONLY the provided browser tools (snapshot/navigate/click/fill/select_option/scroll/wait)
- Always call snapshot() before interacting with a page to understand its structure
- Stay within the same domain - don't follow external links
- Be thorough but efficient - don't click the same element twice
- If you encounter an error, note it and continue exploring other paths
- When you've explored all reachable pages up to the depth limit, output your findings in the required JSON format

## Begin Exploration

Start by navigating to {base_url} and calling snapshot() to see the initial page structure.
"""


async def run_explore_agent(
    run_id: str,
    config: Dict[str, Any],
    page,
    cwd: str,
    logger,
) -> ExplorationResult:
    """
    运行探索 Agent

    Args:
        run_id: 运行 ID
        config: 探索配置
        page: Playwright page
        cwd: 工作目录
        logger: 日志器

    Returns:
        ExplorationResult
    """

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    transcript = []

    # Guardrails
    guardrail_limits = {
        "maxAgentTurns": config.get("guardrails", {}).get("maxAgentTurnsPerRun", 200),
        "maxSnapshots": config.get("guardrails", {}).get("maxSnapshotsPerRun", 100),
        "maxPages": config.get("guardrails", {}).get("maxPagesPerRun", 50),
    }

    turn_count = 0
    snapshot_count = 0
    guardrail_triggered = None

    # 记录提示
    prompt = build_explore_prompt(config)
    transcript.append(TranscriptEntry(
        timestamp=started_at,
        run_id=run_id,
        type="agent_prompt",
        prompt=prompt,
    ))

    # 获取 AI 客户端
    from ...ai_client import create_ai_client, AIConfig
    config_ai = AIConfig.from_env()
    ai_client = create_ai_client(config_ai)

    # 创建 MCP 服务器
    from ...agent import create_mcp_server
    mcp_server = create_mcp_server(page, config.get("baseUrl", ""), run_id, debug=False)

    # 构建系统提示
    system_prompt = f"""You are a TestForge Exploration Agent.

Your task is to explore the web application and document its structure.

## Available Tools (via MCP):
- snapshot: Get page snapshot with element refs
- navigate(url, stepIndex): Navigate to URL
- click(targetDescription, ref, stepIndex): Click element
- fill(targetDescription, ref, text, stepIndex): Fill input
- scroll(direction, amount, stepIndex): Scroll page
- wait(seconds, stepIndex): Wait

## Rules:
1. Call snapshot() before each interaction
2. Use ref (from snapshot) when possible
3. Stay within the same domain
4. Track depth (max {config.get('maxDepth', 3)} levels)
5. Output JSON summary when done

## Output Format:
When exploration is complete, output a JSON object with:
- pages: array of page objects
- edges: array of navigation edges
- loginStatus: login attempt result
"""

    user_msg = f"Start exploring {config.get('baseUrl', '')}. Call snapshot() first to see the page structure."

    agent_output = ""
    last_error = None

    try:
        # 调用 AI
        response = await ai_client.complete(user_msg, system_prompt)
        agent_output = response

        # 解析探索结果
        parsed = _parse_exploration_result(response)

        if not parsed:
            # 尝试使用基本探索
            result = await basic_explore(config, page.browser, logger, run_id, cwd)
            return ExplorationResult(
                ok=True,
                run_id=run_id,
                start_url=config.get("baseUrl", ""),
                started_at=started_at,
                finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                stats=result.get("stats", {}),
                graph=result.get("graph", {"pages": [], "edges": []}),
                transcript=transcript,
            )

        # 构建结果
        result = ExplorationResult(
            ok=True,
            run_id=run_id,
            start_url=config.get("baseUrl", ""),
            started_at=started_at,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            stats={
                "pagesVisited": len(parsed.get("pages", [])),
                "elementsFound": sum(len(p.get("elements", [])) for p in parsed.get("pages", [])),
                "formsFound": sum(len(p.get("forms", [])) for p in parsed.get("pages", [])),
                "linksFound": len(parsed.get("edges", [])),
                "maxDepthReached": max([p.get("depth", 0) for p in parsed.get("pages", [])] or [0]),
                "configuredDepth": config.get("maxDepth", 3),
            },
            graph={
                "pages": parsed.get("pages", []),
                "edges": parsed.get("edges", []),
            },
            transcript=transcript,
        )

        # 处理登录状态
        if config.get("auth"):
            login_status = parsed.get("loginStatus", {"attempted": False, "ok": False})
            result.login = login_status
            if not login_status.get("ok"):
                result.error = {"message": "Login failed", "stage": "login"}

        return result

    except Exception as e:
        last_error = str(e)
        return ExplorationResult(
            ok=False,
            run_id=run_id,
            start_url=config.get("baseUrl", ""),
            started_at=started_at,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            stats={"pagesVisited": 0},
            graph={"pages": [], "edges": []},
            transcript=transcript,
            error={"message": last_error, "stage": "exploration"},
        )


def _parse_exploration_result(output: str) -> Optional[Dict]:
    """解析探索结果 JSON"""
    import re

    # 尝试找 JSON
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', output)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except:
            pass

    # 尝试找原始 JSON
    raw_match = re.search(r'\{[\s\S]*"pages"[\s\S]*\}', output)
    if raw_match:
        try:
            return json.loads(raw_match.group(0))
        except:
            pass

    return None