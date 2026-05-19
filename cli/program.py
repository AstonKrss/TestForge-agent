"""
CLI Program - 命令行程序
=========================

注册所有子命令:
- init
- run
- plan (plan, plan-explore, plan-generate)
"""

import argparse
import sys
import os
import asyncio

from commands.init_cmd import register_init_command, do_init
from commands.run_cmd import register_run_command, do_run


def register_plan_command(parser: argparse.ArgumentParser) -> None:
    """注册 plan 命令"""
    from commands.plan_cmd import register_plan_command as _register_plan_command
    _register_plan_command(parser)


def create_program() -> argparse.ArgumentParser:
    """创建 CLI 程序"""
    parser = argparse.ArgumentParser(
        prog="testforge",
        description="TestForge - AI驱动的Web测试自动化框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 版本
    parser.add_argument(
        "-V", "--version",
        action="version",
        version="TestForge v0.3.0",
    )

    # 子命令
    register_init_command(parser)
    register_run_command(parser)
    register_plan_command(parser)

    return parser


async def do_plan_async(args: argparse.Namespace) -> int:
    """执行 plan 命令"""
    from commands.plan_cmd import do_plan
    return await do_plan(args)


def main():
    """主入口"""
    parser = create_program()
    args = parser.parse_args(sys.argv[1:])

    # 根据命令执行
    if hasattr(args, 'func'):
        exit_code = args.func(args)
        sys.exit(exit_code if exit_code else 0)
    elif args.command == "init":
        exit_code = do_init(args)
        sys.exit(exit_code if exit_code else 0)
    elif args.command == "run":
        exit_code = asyncio.run(do_run(args))
        sys.exit(exit_code if exit_code else 0)
    elif args.command == "plan":
        # 处理 plan 子命令
        plan_command = getattr(args, 'plan_command', None)
        if plan_command in ("plan-explore", "plan-generate", None):
            exit_code = asyncio.run(do_plan_async(args))
            sys.exit(exit_code if exit_code else 0)
        else:
            parser.print_help()
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()