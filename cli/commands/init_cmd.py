"""
init command - 初始化项目配置
"""

import argparse
import os
import json
from pathlib import Path


CONFIG_FILE = "testforge.config.json"
SPECS_DIR = "specs"
STEPS_DIR = "steps"


def write_default_config(cwd: str) -> None:
    """写入默认配置文件"""
    config_path = os.path.join(cwd, CONFIG_FILE)

    if os.path.exists(config_path):
        print(f"{CONFIG_FILE} 已存在，跳过")
        return

    config = {
        "schemaVersion": 1,
        "guardrails": {
            "maxToolCallsPerSpec": 200,
            "maxConsecutiveErrors": 8,
            "maxRetriesPerStep": 5,
        },
        "exportDir": "tests/autoqa",
        "plan": {
            "maxDepth": 3,
            "maxPages": 50,
            "includePatterns": [],
            "excludePatterns": [],
            "exploreScope": "site",
            "testTypes": ["functional", "form", "navigation", "responsive", "boundary", "security"],
            "guardrails": {
                "maxAgentTurnsPerRun": 1000,
                "maxSnapshotsPerRun": 500,
                "maxPagesPerRun": 100,
            },
        },
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"创建 {CONFIG_FILE}")


def write_example_spec(cwd: str) -> None:
    """写入示例规范"""
    specs_path = os.path.join(cwd, SPECS_DIR)
    os.makedirs(specs_path, exist_ok=True)

    example_path = os.path.join(specs_path, "login-example.md")

    if os.path.exists(example_path):
        print(f"{SPECS_DIR}/login-example.md 已存在，跳过")
        return

    example_md = """# 登录测试 (Auto-generated)

Type: functional | Priority: P1

## Preconditions
- 基础 URL 可访问: {{BASE_URL}}
- 登录页面可访问: {{BASE_URL}}/login

## Steps
1. Navigate to {{BASE_URL}}/login
2. Fill the 'username' input with {{USERNAME}}
3. Fill the 'password' input with {{PASSWORD}}
4. Click the '登录' button
5. Verify the page shows 'Dashboard' or 'Welcome'
"""

    with open(example_path, "w", encoding="utf-8") as f:
        f.write(example_md)

    print(f"创建 {SPECS_DIR}/login-example.md")


def write_login_steps(cwd: str) -> None:
    """写入登录步骤库"""
    steps_path = os.path.join(cwd, STEPS_DIR)
    os.makedirs(steps_path, exist_ok=True)

    login_path = os.path.join(steps_path, "login.md")

    if os.path.exists(login_path):
        print(f"{STEPS_DIR}/login.md 已存在，跳过")
        return

    login_md = """# 登录步骤 (共享)

## Steps
1. Navigate to {{LOGIN_BASE_URL}}
2. Fill the 'username' input with {{USERNAME}}
3. Fill the 'password' input with {{PASSWORD}}
4. Click the '登录' button
"""

    with open(login_path, "w", encoding="utf-8") as f:
        f.write(login_md)

    print(f"创建 {STEPS_DIR}/login.md")


def write_test_helpers(cwd: str) -> None:
    """写入测试辅助文件"""
    helpers_dir = os.path.join(cwd, "tests", "helpers")
    os.makedirs(helpers_dir, exist_ok=True)

    env_path = os.path.join(helpers_dir, "autoqa-env.ts")

    if os.path.exists(env_path):
        print(f"tests/helpers/autoqa-env.ts 已存在，跳过")
        return

    env_ts = '''import { test, expect } from "@playwright/test";

/**
 * TestForge Environment Helper
 * Loads environment variables for test execution
 */

async function loadEnvFiles(): Promise<void> {
  // In real implementation, load .env and .env.* files
  // For now, use process.env directly
}

function getEnvVar(key: string, defaultValue?: string): string {
  const value = process.env[key];
  if (value === undefined && defaultValue === undefined) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value ?? defaultValue ?? "";
}

export { loadEnvFiles, getEnvVar };
'''

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_ts)

    print(f"创建 tests/helpers/autoqa-env.ts")


def register_init_command(parser: argparse.ArgumentParser) -> None:
    """注册 init 命令"""
    subparsers = parser.add_subparsers(dest="command", help="命令")
    init_parser = subparsers.add_parser("init", help="初始化 TestForge 项目配置")

    init_parser.set_defaults(func=lambda args: do_init(args))


def do_init(args: argparse.Namespace) -> int:
    """执行 init 命令"""
    cwd = os.getcwd()

    print("\n初始化 TestForge 项目...")
    print("=" * 50)

    write_default_config(cwd)
    write_example_spec(cwd)
    write_login_steps(cwd)
    write_test_helpers(cwd)

    print("\n初始化完成!")
    print("\n运行命令:")
    print(f"  testforge run {SPECS_DIR}/login-example.md --url http://localhost:3000")

    return 0