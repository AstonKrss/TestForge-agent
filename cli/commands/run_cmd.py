"""
run command - 运行 Markdown 测试规范
"""

import argparse
import os
import sys
import json
import uuid
import re
from pathlib import Path

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.parser import parse_spec, Spec
from src.runner import run_specs
from src.agent import create_mcp_server
from src.browser import create_browser
from src.config import load_config, resolve_guardrails
from src.env import load_env_files
from src.logging import create_logger


TEMPLATE_VAR_PATTERN = r"\{\{\s*([A-Z0-9_]+)\s*\}\}"


def extract_template_vars(text: str) -> list:
    """提取模板变量"""
    vars = []
    pattern = re.compile(TEMPLATE_VAR_PATTERN)
    for match in pattern.finditer(text):
        var_name = match.group(1).strip()
        if var_name and var_name not in vars:
            vars.append(var_name)
    return vars


def render_template(text: str, vars: dict) -> str:
    """渲染模板变量"""
    pattern = re.compile(TEMPLATE_VAR_PATTERN)

    def replacer(match):
        var_name = match.group(1).strip()
        return vars.get(var_name, match.group(0))

    return pattern.sub(replacer, text)


def discover_markdown_specs(path: str) -> list:
    """发现 Markdown 规范"""
    path = os.path.abspath(path)

    if os.path.isfile(path):
        if path.endswith(".md"):
            return [path]
        return []

    if os.path.isdir(path):
        specs = []
        for root, dirs, files in os.walk(path):
            for f in files:
                if f.endswith(".md"):
                    specs.append(os.path.join(root, f))
        return sorted(specs)

    return []


def validate_args(url: str = None, debug: bool = False, headless: bool = False) -> dict:
    """验证参数"""
    if not url and not os.environ.get("TF_BASE_URL"):
        return {"ok": False, "message": "Missing --url 参数或 TF_BASE_URL 环境变量"}

    if debug and headless:
        return {"ok": False, "message": "不能同时使用 --debug 和 --headless"}

    return {
        "ok": True,
        "value": {
            "base_url": url or os.environ.get("TF_BASE_URL", ""),
            "headless": not debug and (headless or os.environ.get("TF_HEADLESS", "true").lower() != "false"),
            "debug": debug or os.environ.get("TF_DEBUG", "0") == "1",
        },
    }


async def run_single_spec_agent(run_id: str, base_url: str, spec_path: str, spec: Spec, page, logger, guardrails: dict, step_vars_map: dict = None, ir_recorder=None):
    """运行单个规范 - 使用 AI Agent"""
    from src.ai_agent import AIAgent, build_tools_description
    from src.agent import GuardrailCounters, GuardrailLimits, update_counters_on_tool_call, update_counters_on_tool_result, check_guardrails

    # 构建提示
    preconditions = "\n".join([f"- {p}" for p in spec.preconditions])
    steps_text = "\n".join([f"{s.index}. {s.text}" + (f"\n   - Expected: {s.expected}" if s.expected else "") for s in spec.steps])

    prompt = f"""You are a TestForge AI Agent.

Base URL: {base_url}
Spec Path: {spec_path}

## Preconditions:
{preconditions}

## Steps:
{steps_text}

## Rules:
- Use ONLY the provided tools (snapshot/navigate/click/fill/select_option/scroll/wait/assert_text_present/assert_element_visible).
- Execute steps in order.
- Start with Step 1 - MUST call navigate() first.
- Include stepIndex parameter (1-indexed) for EVERY tool call.
- Ref-First execution:
  - Before each interaction, call snapshot() to get element refs like e15.
  - Use ref (preferred) instead of targetDescription.
  - Only if ref not found, fall back to targetDescription.
- Assertions: After actions with Expected: clauses, MUST call assert_text_present or assert_element_visible.
"""

    # 创建 MCP 服务器
    mcp_server = create_mcp_server(page, base_url, run_id, debug=False)

    # 创建 AI 客户端
    from src.ai_client import create_ai_client, AIConfig
    config = AIConfig.from_env()
    ai_client = create_ai_client(config)

    # 创建 Guardrails
    guardrail_limits = GuardrailLimits(
        max_tool_calls=guardrails.get("maxToolCallsPerSpec", 200),
        max_consecutive_errors=guardrails.get("maxConsecutiveErrors", 5),
        max_retries_per_step=guardrails.get("maxRetriesPerStep", 3),
    )
    guardrail_counters = GuardrailCounters()

    # 创建 AI Agent
    agent = AIAgent(
        page=page,
        base_url=base_url,
        ai_client=ai_client,
        mcp_server=mcp_server,
        ir_recorder=ir_recorder,
        guardrail_counters=guardrail_counters,
        guardrail_limits=guardrail_limits,
    )

    # 运行
    return await agent.run(prompt, spec)


def register_run_command(parser: argparse.ArgumentParser) -> None:
    """注册 run 命令"""
    # 使用 subparsers
    subparsers = parser.add_subparsers(dest="command", help="命令")
    run_parser = subparsers.add_parser("run", help="运行 Markdown 测试规范")

    run_parser.add_argument(
        "file_or_dir",
        help="Markdown 规范文件或目录",
    )
    run_parser.add_argument(
        "--env",
        dest="env",
        help="环境名称，用于加载 .env.<name> 文件",
    )
    run_parser.add_argument(
        "--url",
        dest="url",
        help="基础 URL (如 http://localhost:3000)",
    )
    run_parser.add_argument(
        "--login-url",
        dest="login_url",
        help="登录页 URL",
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="调试模式 (显示浏览器 + 额外日志)",
    )
    run_parser.add_argument(
        "--headless",
        action="store_true",
        help="强制无头模式 (与 --debug 冲突)",
    )
    run_parser.add_argument(
        "--export",
        action="store_true",
        help="运行后导出 IR 为 Playwright 测试",
    )
    run_parser.add_argument(
        "--export-dir",
        dest="export_dir",
        help="导出目录 (默认: tests/testforge)",
    )

    run_parser.set_defaults(func=lambda args: asyncio.run(do_run(args)))


import asyncio


async def do_run(args: argparse.Namespace) -> int:
    """执行 run 命令"""
    # 加载环境变量
    env_result = load_env_files(args.env if hasattr(args, 'env') else None)
    if not env_result["ok"]:
        print(f"错误: {env_result['message']}", file=sys.stderr)
        return 2

    # 验证参数
    url = getattr(args, 'url', None)
    debug = getattr(args, 'debug', False)
    headless = getattr(args, 'headless', False)

    validated = validate_args(url, debug, headless)
    if not validated["ok"]:
        print(f"错误: {validated['message']}", file=sys.stderr)
        return 2

    base_url = validated["value"]["base_url"]
    headless = validated["value"]["headless"]
    debug = validated["value"]["debug"]

    # 发现规范
    input_path = os.path.abspath(args.file_or_dir)
    specs = discover_markdown_specs(input_path)

    if not specs:
        print(f"错误: 未找到 Markdown 规范文件", file=sys.stderr)
        return 2

    # 加载配置
    config_result = load_config()
    guardrails = resolve_guardrails(config_result.get("config"))

    # 生成 Run ID
    run_id = str(uuid.uuid4())
    cwd = os.getcwd()

    print(f"\nrunId={run_id}")
    print(f"baseUrl={base_url}")
    if hasattr(args, 'login_url') and args.login_url:
        print(f"loginUrl={args.login_url}")
    print(f"headless={headless}")
    print(f"debug={debug}")
    print(f"specs={len(specs)}")

    # 创建日志器
    logger = create_logger(run_id, cwd, debug)

    logger.log({
        "event": "testforge.run.started",
        "run_id": run_id,
        "base_url": base_url,
        "headless": headless,
        "debug": debug,
        "spec_count": len(specs),
    })

    # 创建浏览器
    browser_result = await create_browser(headless=headless, slow_mo=75 if debug else None)
    if not browser_result.get("ok"):
        print(f"错误: 浏览器启动失败: {browser_result.get('error')}", file=sys.stderr)
        return 2

    browser = browser_result["browser"]

    specs_passed = 0
    specs_failed = 0
    run_start_time = __import__("time").time()

    try:
        for spec_index, spec_path in enumerate(specs):
            print(f"\n运行规范: {spec_path}")

            # 读取并解析 Markdown
            try:
                with open(spec_path, "r", encoding="utf-8") as f:
                    markdown = f.read()
            except Exception as e:
                print(f"错误: 无法读取规范文件: {e}", file=sys.stderr)
                return 2

            result = parse_spec(markdown)
            if not result.ok:
                print(f"错误: 规范解析失败: {result.error}", file=sys.stderr)
                return 2

            spec = result.spec

            # 渲染模板变量
            template_vars = {
                "BASE_URL": base_url,
                "LOGIN_BASE_URL": getattr(args, 'login_url', None) or base_url,
                "ENV": getattr(args, 'env', None) or os.environ.get("TF_ENV", ""),
                "USERNAME": os.environ.get("TF_USERNAME", ""),
                "PASSWORD": os.environ.get("TF_PASSWORD", ""),
            }

            # 解析步骤变量
            step_vars_map = {}
            for step in spec.steps:
                vars = extract_template_vars(step.text)
                if vars:
                    step_vars_map[step.index] = {"vars": vars, "raw_text": step.text}

                # 渲染步骤文本
                step.text = render_template(step.text, template_vars)

            # 渲染前置条件
            for i, pre in enumerate(spec.preconditions):
                spec.preconditions[i] = render_template(pre, template_vars)

            # 创建浏览器上下文和页面
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900} if not debug else None,
            )
            page = await context.new_page()

            # 创建 IR 录制器
            ir_recorder = None
            if getattr(args, 'export', False):
                from src.ir import IRRecorder
                ir_recorder = IRRecorder(
                    cwd=cwd,
                    run_id=run_id,
                    spec_path=spec_path,
                    enabled=True,
                    write_to_file=True,
                )

            try:
                # 使用 AI Agent 运行规范
                await run_single_spec_agent(
                    run_id=run_id,
                    base_url=base_url,
                    spec_path=spec_path,
                    spec=spec,
                    page=page,
                    logger=logger,
                    guardrails=guardrails,
                    step_vars_map=step_vars_map,
                    ir_recorder=ir_recorder,
                )
                specs_passed += 1
                print(f"  ✓ 规范通过")

            except Exception as e:
                specs_failed += 1
                print(f"  ✗ 规范失败: {e}")

                # 捕获失败截图
                try:
                    screenshot = await page.screenshot()
                    artifacts_dir = os.path.join(cwd, ".testforge", "runs", run_id, "screenshots")
                    os.makedirs(artifacts_dir, exist_ok=True)
                    screenshot_path = os.path.join(artifacts_dir, f"failure-{spec_index}.png")
                    with open(screenshot_path, "wb") as f:
                        f.write(screenshot)
                    print(f"  截图: {screenshot_path}")
                except:
                    pass

            finally:
                await page.close()
                await context.close()

    finally:
        await browser.close()

    duration_ms = int((__import__("time").time() - run_start_time) * 1000)

    # 导出 IR 为 Playwright 测试
    if getattr(args, 'export', False):
        print("\n导出 IR 为 Playwright 测试...")
        try:
            from src.runner.exporter import export_from_ir
            for spec_path in specs:
                result = export_from_ir(
                    cwd=cwd,
                    run_id=run_id,
                    spec_path=spec_path,
                    export_dir=getattr(args, 'export_dir', None),
                    base_url=base_url,
                )
                if result["ok"]:
                    print(f"  ✓ {result['path']}")
                else:
                    print(f"  ✗ {result['message']}")
        except Exception as e:
            print(f"  导出失败: {e}")

    # 记录完成
    logger.log({
        "event": "testforge.run.finished",
        "run_id": run_id,
        "exit_code": 0 if specs_failed == 0 else 1,
        "duration_ms": duration_ms,
        "specs_passed": specs_passed,
        "specs_failed": specs_failed,
    })

    await logger.flush()

    print(f"\n运行完成:")
    print(f"  通过: {specs_passed}")
    print(f"  失败: {specs_failed}")
    print(f"  耗时: {duration_ms}ms")

    return 0 if specs_failed == 0 else 1