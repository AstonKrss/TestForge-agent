"""
TestForge CLI - 命令行入口
===========================

支持命令:
- init: 初始化项目配置
- run: 运行 Markdown 测试规范
- plan: 智能测试规划 (探索 + 生成)
"""

import sys
import os

# 确保 src 在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli.program import create_program


def main():
    """CLI 主入口"""
    program = create_program()
    program.parse_args(sys.argv[1:])


if __name__ == "__main__":
    main()