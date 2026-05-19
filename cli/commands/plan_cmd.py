"""
plan command - 智能测试规划
"""

import argparse
import os
import sys
import uuid
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.browser import create_browser
from src.config import load_config, load_plan_config
from src.logging import create_logger
from src.planner.explore import explore
from src.planner.output import write_exploration_result, write_plan_summary
from src.planner.generate import generate_test_plan


GUARDRAIL_EXIT_CODE = 10
CONFIG_ERROR_EXIT_CODE = 2
RUNTIME_ERROR_EXIT_CODE = 1


def sanitize_error_message(error: Exception) -> str:
    """清理错误消息中的敏感信息"""
    import re
    message = str(error)
    patterns = [
        (r'password[=:]\s*[^\s&]+', 'password=***'),
        (r'token[=:]\s*[^\s&]+', 'token=***'),
        (r'api[_-]?key[=:]\s*[^\s&]+', 'apikey=***'),
        (r'secret[=:]\s*[^\s&]+', 'secret=***'),
        (r'bearer\s+[A-Za-z0-9._-]+', 'bearer ***'),
    ]
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
    return message


def validate_url(value: str) -> str:
    """验证 URL 格式"""
    import re
    url_pattern = re.compile(r'^https?://')
    if not url_pattern.match(value):
        raise argparse.ArgumentTypeError(f"Invalid URL: {value}")
    return value


def validate_positive_int(value: str) -> int:
    """验证正整数"""
    try:
        parsed = int(value)
        if parsed < 0:
            raise argparse.ArgumentTypeError(f"Must be a positive number, got {value}")
        return parsed
    except ValueError:
        raise argparse.ArgumentTypeError(f"Must be a number, got {value}")


def validate_explore_scope(value: str) -> str:
    """验证探索范围"""
    valid = ["site", "focused", "single_page"]
    if value not in valid:
        raise argparse.ArgumentTypeError(f"Invalid scope: {value}. Valid: {', '.join(valid)}")
    return value


def register_plan_command(parser: argparse.ArgumentParser) -> None:
    """注册 plan 命令及其子命令"""

    plan_subparsers = parser.add_subparsers(dest="plan_command", help="plan 子命令")

    # plan - 完整规划 (探索 + 生成)
    plan_parser = plan_subparsers.add_parser("plan", help="完整测试规划 (探索 + 生成)")
    _add_common_options(plan_parser)

    # plan-explore - 仅探索
    explore_parser = plan_subparsers.add_parser("plan-explore", help="探索应用 (仅探索阶段)")
    explore_parser.add_argument(
        "-u", "--url",
        required=True,
        help="目标应用 URL",
        type=validate_url,
    )
    _add_common_options(explore_parser)

    # plan-generate - 仅生成
    generate_parser = plan_subparsers.add_parser("plan-generate", help="生成测试计划 (从探索结果)")
    generate_parser.add_argument(
        "--run-id",
        required=True,
        help="探索运行 ID",
    )
    generate_parser.add_argument(
        "-u", "--url",
        help="目标应用 URL (从配置加载)",
        type=validate_url,
    )
    generate_parser.add_argument(
        "--test-types",
        help="测试类型 (逗号分隔): functional,form,navigation,responsive,boundary,security",
    )
    generate_parser.add_argument(
        "--max-agent-turns",
        type=validate_positive_int,
        help="最大 Agent 调用次数",
    )
    generate_parser.add_argument(
        "--config",
        help="配置文件路径 (默认: ./testforge.config.json)",
    )

    # 设置默认函数
    plan_parser.set_defaults(func=lambda args: asyncio.run(do_plan(args)))
    explore_parser.set_defaults(func=lambda args: asyncio.run(do_plan(args)))
    generate_parser.set_defaults(func=lambda args: asyncio.run(do_plan(args)))


def _add_common_options(sub_parser) -> None:
    """添加通用选项"""
    sub_parser.add_argument(
        "--config",
        help="配置文件路径 (默认: ./testforge.config.json)",
    )
    sub_parser.add_argument(
        "-u", "--url",
        help="目标应用 URL",
    )
    sub_parser.add_argument(
        "-d", "--depth",
        type=int,
        help="最大探索深度 (0-10)",
    )
    sub_parser.add_argument(
        "--max-pages",
        type=int,
        help="最大访问页面数",
    )
    sub_parser.add_argument(
        "--max-agent-turns",
        type=int,
        help="最大 Agent 调用次数 (guardrail)",
    )
    sub_parser.add_argument(
        "--max-snapshots",
        type=int,
        help="最大快照数 (guardrail)",
    )
    sub_parser.add_argument(
        "--explore-scope",
        choices=["site", "focused", "single_page"],
        help="探索范围模式",
    )
    sub_parser.add_argument(
        "--test-types",
        help="测试类型 (逗号分隔)",
    )
    sub_parser.add_argument(
        "--login-url",
        help="登录页 URL",
    )
    sub_parser.add_argument(
        "--username",
        help="登录用户名",
    )
    sub_parser.add_argument(
        "--password",
        help="登录密码",
    )
    sub_parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式运行浏览器",
    )


async def run_explore_command(args: argparse.Namespace) -> int:
    """执行探索命令"""
    run_id = str(uuid.uuid4())
    cwd = os.getcwd()
    logger = create_logger(run_id, cwd, debug=False)

    # 加载配置
    config_result = load_config(cwd)
    if not config_result["ok"]:
        print(f"配置错误: {config_result['error']}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE

    try:
        config = load_plan_config(config_result["config"], args)
    except Exception as e:
        print(f"配置错误: {sanitize_error_message(e)}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE

    # 创建浏览器
    browser_result = await create_browser(headless=args.headless)
    if not browser_result.get("ok"):
        print(f"浏览器启动失败: {browser_result.get('error')}", file=sys.stderr)
        return RUNTIME_ERROR_EXIT_CODE

    browser = browser_result["browser"]

    try:
        print(f"\n开始探索...")
        result = await explore(
            config=config,
            browser=browser,
            logger=logger,
            run_id=run_id,
            cwd=cwd,
        )

        # 写入结果
        output = await write_exploration_result(result, {"run_id": run_id, "cwd": cwd})

        print(f"\n探索完成!")
        print(f"  访问页面数: {result.stats['pagesVisited']}")
        print(f"  最大深度: {result.stats['maxDepthReached']}")
        print(f"  结果目录: .testforge/runs/{run_id}/plan-explore/")

        if output["errors"]:
            print(f"\n警告:")
            for e in output["errors"]:
                print(f"  - {e}")

        # 写入摘要
        await write_plan_summary(run_id, cwd, exploration=result, exit_code=0)

        return 0

    except Exception as e:
        logger.log({"event": "testforge.plan.explore.failed", "run_id": run_id, "error": sanitize_error_message(e)})
        print(f"探索失败: {sanitize_error_message(e)}", file=sys.stderr)
        return RUNTIME_ERROR_EXIT_CODE

    finally:
        await browser.close()


async def run_generate_command(args: argparse.Namespace) -> int:
    """执行生成命令"""
    run_id = args.run_id
    cwd = os.getcwd()
    logger = create_logger(run_id, cwd, debug=False)

    # 加载配置
    config_result = load_config(cwd)
    if not config_result["ok"]:
        print(f"配置错误: {config_result['error']}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE

    try:
        config = load_plan_config(config_result["config"], args)
    except Exception as e:
        print(f"配置错误: {sanitize_error_message(e)}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE

    try:
        print(f"\n生成测试计划...")

        result = await generate_test_plan(
            run_id=run_id,
            config=config,
            logger=logger,
            cwd=cwd,
        )

        print(f"\n测试计划生成完成!")
        print(f"  测试用例数: {len(result['plan']['cases'])}")
        print(f"  规范文件数: {len(result['output']['spec_paths'])}")

        # 写入摘要
        await write_plan_summary(run_id, cwd, plan=result["plan"], exit_code=0)

        return 0

    except Exception as e:
        logger.log({"event": "testforge.plan.generate.failed", "run_id": run_id, "error": sanitize_error_message(e)})
        print(f"测试计划生成失败: {sanitize_error_message(e)}", file=sys.stderr)
        return RUNTIME_ERROR_EXIT_CODE


async def run_full_plan_command(args: argparse.Namespace) -> int:
    """执行完整规划命令"""
    run_id = str(uuid.uuid4())
    cwd = os.getcwd()
    logger = create_logger(run_id, cwd, debug=False)

    # 加载配置
    config_result = load_config(cwd)
    if not config_result["ok"]:
        print(f"配置错误: {config_result['error']}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE

    try:
        config = load_plan_config(config_result["config"], args)
    except Exception as e:
        print(f"配置错误: {sanitize_error_message(e)}", file=sys.stderr)
        return CONFIG_ERROR_EXIT_CODE

    browser_result = await create_browser(headless=args.headless)
    if not browser_result.get("ok"):
        print(f"浏览器启动失败: {browser_result.get('error')}", file=sys.stderr)
        return RUNTIME_ERROR_EXIT_CODE

    browser = browser_result["browser"]

    try:
        # 阶段 1: 探索
        print(f"\n阶段 1: 探索应用...")
        exploration_result = await explore(
            config=config,
            browser=browser,
            logger=logger,
            run_id=run_id,
            cwd=cwd,
        )

        exploration_output = await write_exploration_result(exploration_result, {"run_id": run_id, "cwd": cwd})

        print(f"\n探索完成!")
        print(f"  访问页面数: {exploration_result.stats['pagesVisited']}")
        print(f"  结果目录: .testforge/runs/{run_id}/plan-explore/")

        if exploration_output["errors"]:
            print(f"\n探索警告:")
            for e in exploration_output["errors"]:
                print(f"  - {e}")

        # 阶段 2: 生成
        print(f"\n阶段 2: 生成测试计划...")

        # 需要重新加载配置（因为 explore 可能修改了它）
        config_result = load_config(cwd)
        config = load_plan_config(config_result["config"], args)

        plan_result = await generate_test_plan(
            run_id=run_id,
            config=config,
            logger=logger,
            cwd=cwd,
        )

        print(f"\n测试计划生成完成!")
        print(f"  测试用例数: {len(plan_result['plan']['cases'])}")
        print(f"  规范文件数: {len(plan_result['output']['spec_paths'])}")

        # 写入摘要
        await write_plan_summary(
            run_id, cwd,
            exploration=exploration_result,
            plan=plan_result["plan"],
            exit_code=0,
        )

        print(f"\n完整规划完成!")
        print(f"Run ID: {run_id}")
        print(f"\n生成的文件:")
        print(f"  - 探索图: .testforge/runs/{run_id}/plan-explore/explore-graph.json")
        print(f"  - 测试计划: .testforge/runs/{run_id}/plan/test-plan.json")
        print(f"  - 测试规范: {len(plan_result['output']['spec_paths'])} 个文件")

        return 0

    except Exception as e:
        error_msg = sanitize_error_message(e)
        logger.log({"event": "testforge.plan.failed", "run_id": run_id, "error": error_msg})
        print(f"规划失败: {error_msg}", file=sys.stderr)
        return RUNTIME_ERROR_EXIT_CODE

    finally:
        await browser.close()


async def do_plan(args: argparse.Namespace) -> int:
    """执行 plan 命令"""
    command = getattr(args, 'plan_command', None)

    if command == "plan-explore":
        return await run_explore_command(args)
    elif command == "plan-generate":
        return await run_generate_command(args)
    else:
        # plan - 完整规划
        return await run_full_plan_command(args)


