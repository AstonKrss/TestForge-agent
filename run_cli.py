#!/usr/bin/env python
"""
TestForge CLI - 统一入口
=======================

运行此文件启动 TestForge CLI：
    python run_cli.py
"""

import sys
import os

# 添加项目路径
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)


def main():
    """主入口"""
    from src.cli.startup_menu import run

    try:
        run()
    except KeyboardInterrupt:
        print("\n\n  已退出\n")


if __name__ == "__main__":
    main()
