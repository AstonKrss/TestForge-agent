# TestForge 测试套件

## 概述

参考 AutoQA-Agent 的测试架构，为 TestForge 创建了完整的单元测试套件。

## 测试结构

```
tests/
├── conftest.py              # Pytest 配置和共享 fixtures
├── helpers/                # 辅助函数
│   └── __init__.py
└── unit/                   # 单元测试
    ├── __init__.py
    ├── test_agent.py       # Agent 组件测试 (Guardrails/Memory/Planner/Executor/Reflector)
    └── test_tools.py       # 工具函数测试 (click/assertions/error)
```

## 运行测试

```bash
# 运行所有单元测试
python -m pytest tests/unit/ -v

# 运行特定测试文件
python -m pytest tests/unit/test_agent.py -v

# 运行特定测试类
python -m pytest tests/unit/test_agent.py::TestGuardrailError -v

# 带详细输出
python -m pytest tests/unit/ -v --tb=short
```

## 测试覆盖

### Agent 组件测试 (`test_agent.py`)

| 测试类 | 测试内容 |
|--------|----------|
| `TestGuardrailError` | GuardrailError 异常创建和属性 |
| `TestGuardrailCounters` | 计数器初始化和更新 |
| `TestCheckGuardrails` | 防护栏检查逻辑 |
| `TestGuardrailIntegration` | 集成场景模拟 |
| `TestMemory` | 记忆系统存取和统计 |
| `TestPlanner` | 目标解析为步骤 |
| `TestToolResult` | 工具结果创建 |
| `TestStep` | 步骤状态转换 |
| `TestAgentConfig` | Agent 配置默认值 |
| `TestReflector` | 失败分析和修复建议 |

### 工具函数测试 (`test_tools.py`)

| 测试类 | 测试内容 |
|--------|----------|
| `TestIsValidRef` | ref 格式验证 (如 e15) |
| `TestNormalizeInput` | 输入规范化处理 |
| `TestNormalizeForMatching` | 匹配文本规范化 |
| `TestExtractSelectors` | CSS 选择器提取 |
| `TestBuildFuzzyRegex` | 模糊匹配正则构建 |
| `TestErrorCode` | 错误代码常量 |
| `TestToolError` | 工具错误类 |
| `TestIsTimeoutError` | 超时错误检测 |
| `TestToToolError` | 异常到工具错误的映射 |
| `TestOk` | 成功结果创建 |
| `TestFail` | 失败结果创建 |

## 参考 AutoQA-Agent 的测试模式

1. **Mock 外部依赖** - 使用 `vi.mock()` 模拟 SDK 调用
2. **异步迭代器模拟** - 创建假的 async iterable 来模拟流
3. **单元测试优先** - 纯函数逻辑优先测试
4. **集成场景测试** - 模拟完整执行流程
5. **边界条件测试** - 测试极限情况和错误处理

## 添加新测试

```python
# tests/unit/test_new_module.py
import pytest
import sys
sys.path.insert(0, 'src')

class TestNewFeature:
    def test_feature_basic(self):
        from new_module import some_function
        result = some_function()
        assert result is not None

    def test_feature_with_input(self):
        result = some_function("test input")
        assert result == expected
```