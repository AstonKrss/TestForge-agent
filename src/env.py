"""
Env - 环境变量加载
===================

加载 .env 和 .env.<name> 文件
"""

import os
import re
from typing import Dict, Any


def strip_quotes(value: str) -> str:
    """去除引号"""
    s = value.strip()
    if len(s) >= 2:
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
    return s


def parse_dotenv(content: str) -> Dict[str, str]:
    """解析 .env 内容"""
    out = {}
    lines = (content or "").split("\n")

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # 移除 export 前缀
        without_export = line
        if line.startswith("export "):
            without_export = line[7:].strip()

        # 查找等号
        eq_idx = without_export.find("=")
        if eq_idx <= 0:
            continue

        key = without_export[:eq_idx].strip()
        if not key:
            continue

        raw_value = without_export[eq_idx + 1:]
        value = strip_quotes(raw_value)

        out[key] = value

    return out


def load_env_file(file_path: str) -> Dict[str, str]:
    """加载单个 .env 文件"""
    if not os.path.exists(file_path):
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return parse_dotenv(content)
    except Exception:
        return {}


def load_env_files(env_name: str = None, cwd: str = None) -> Dict[str, Any]:
    """
    加载环境变量文件

    Args:
        env_name: 环境名称 (如 "test", "prod")
        cwd: 工作目录

    Returns:
        {"ok": bool, "loadedFiles": list, "message": str}
    """
    cwd = cwd or os.getcwd()
    loaded_files = []
    initial_keys = set(os.environ.keys())

    # 加载 .env
    env_path = os.path.join(cwd, ".env")
    if os.path.exists(env_path):
        parsed = load_env_file(env_path)
        for k, v in parsed.items():
            if k not in initial_keys:
                os.environ[k] = v
        loaded_files.append(env_path)

    # 加载 .env.<name>
    if env_name:
        name_env_path = os.path.join(cwd, f".env.{env_name}")
        if os.path.exists(name_env_path):
            parsed = load_env_file(name_env_path)
            for k, v in parsed.items():
                os.environ[k] = v
            loaded_files.append(name_env_path)
        elif env_name:
            return {
                "ok": False,
                "message": f"Env file not found: {name_env_path}",
                "loadedFiles": loaded_files,
            }

    return {
        "ok": True,
        "loadedFiles": loaded_files,
    }


__all__ = ["load_env_files", "load_env_file", "parse_dotenv"]