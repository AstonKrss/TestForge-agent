# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

**TestForge** - AI驱动的Web测试自动化框架 v0.2.0

核心理念:
- **Stable First** - 稳定性优先，优雅降级
- **A11y-First** - 无障碍优先，语义化定位
- **Security by Default** - 安全内建，敏感信息脱敏
- **Learning** - 从执行中学习，越用越聪明

## 项目结构

```
TestForge/
├── __init__.py              # 包入口 (所有创新模块导出)
├── setup.py                 # 初始化入口: python setup.py
├── src/
│   ├── init.py              # 配置向导 (8个AI厂商 + 模型选择)
│   ├── ai_client/           # AI客户端 (Codex/GPT/Gemini/DeepSeek/Qwen/Kimi/MiniMax/本地)
│   ├── tools/               # 9个浏览器自动化工具
│   │   ├── click.py        # Ref-First 智能点击
│   │   ├── fill.py         # 表单填充 (密码脱敏)
│   │   ├── navigate.py     # 导航 + wait + scroll
│   │   ├── assertions.py   # 断言工具
│   │   └── error.py        # 错误处理
│   ├── browser/             # 浏览器生命周期管理
│   ├── agent/               # Agent编排 (Planner/Executor/Reflector/Memory)
│   ├── ir/                  # 中间表示层 (元素指纹/定位器生成)
│   ├── parser/              # Markdown规范解析
│   ├── runner/              # 测试执行引擎
│   │
│   │  ★ 原创创新模块 ★
│   │
│   ├── smart_wait.py        # DOM变化感知的智能等待
│   ├── intent_engine.py     # 中文意图推断引擎
│   ├── adaptive_locator.py # 自适应定位器 (学习成功率)
│   ├── multimodal_assert.py# 多模态断言 (截图对比)
│   └── test_evolution.py   # 测试演化引擎 (自动修复)
│
└── examples/                # 示例代码
    ├── ai_demo.py           # AI客户端演示
    ├── agent_demo.py        # Agent演示
    └── interactive.py       # 交互式测试工具
```

## 初始化配置

```bash
python setup.py
```

向导步骤:
1. 选择AI厂商 (Codex/GPT/Gemini/DeepSeek/Qwen/Kimi/MiniMax/本地Ollama)
2. 选择模型
3. 输入API Key
4. 选择浏览器
5. 测试连接
6. 保存配置

配置保存到 `~/.testforge/config.json`

## 原创创新模块

### 1. SmartWait - 智能等待
```python
from src.smart_wait import create_smart_wait

sw = create_smart_wait(page)
sw.for_element("#submit").to_appear()
sw.for_text("登录成功").to_appear()
sw.for_network_idle().to_idle()
```

### 2. Intent Engine - 意图推断
```python
from src.intent_engine import create_intent_engine

engine = create_intent_engine()
intent = engine.parse("输入用户名 为 testuser")
# -> Intent(type=FILL, target="用户名", value="testuser")
```

### 3. Adaptive Locator - 自适应定位
```python
from src.adaptive_locator import get_adaptive_locator

al = get_adaptive_locator()
al.record_attempt("登录按钮", "role", "button", success=True)
best = al.get_best_locator("登录按钮", [("role", "button"), ("text", "登录")])
```

### 4. MultiModal Assert - 多模态断言
```python
from src.multimodal_assert import assert_that

assert_that(page).element("#submit").is_visible()
assert_that(page).screenshot().matches("期望界面.png", threshold=0.95)
```

### 5. Test Evolution - 测试演化
```python
from src.test_evolution import get_evolution, FailureReason

evo = get_evolution()
alts = evo.evolve("按钮", ("text", "X"), FailureReason.ELEMENT_NOT_FOUND)
```

## 9层定位优先级

| 层级 | 方法 | 说明 |
|------|------|------|
| 1 | TEST_ID | data-test属性 |
| 2 | ROLE | 语义化角色 |
| 3 | LABEL | 表单标签 |
| 4 | PLACEHOLDER | 占位符 |
| 5 | CSS_ID | #ID |
| 6 | CSS_ATTR | 属性选择器 |
| 7 | CSS_SELECTOR | 组合选择器 |
| 8 | TEXT_EXACT | 精确文本 |
| 9 | TEXT_FUZZY | 模糊文本 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| TF_AI_PROVIDER | AI厂商 | Codex |
| TF_AI_MODEL | 模型 | Codex-3-5-sonnet-20241022 |
| TF_BASE_URL | 基础URL | http://localhost:3000 |
| TF_HEADLESS | 无头模式 | true |
| TF_DEBUG | 调试模式 | 0 |
| ANTHROPIC_API_KEY | Codex密钥 | - |
| OPENAI_API_KEY | OpenAI密钥 | - |
| GOOGLE_API_KEY | Gemini密钥 | - |
| DEEPSEEK_API_KEY | DeepSeek密钥 | - |
| DASHSCOPE_API_KEY | Qwen密钥 | - |
| MOONSHOT_API_KEY | Kimi密钥 | - |
| MINIMAX_API_KEY | MiniMax密钥 | - |

## 安装依赖

```bash
pip install playwright Pillow httpx
playwright install chromium
```

## 运行示例

```bash
python examples/ai_demo.py       # AI客户端演示
python examples/agent_demo.py     # Agent演示
python examples/interactive.py    # 交互式测试
```

## 测试

```bash
# 运行所有单元测试
python -m pytest tests/unit/ -v

# 运行特定测试
python -m pytest tests/unit/test_agent.py -v
python -m pytest tests/unit/test_tools.py -v
```

测试覆盖:
- **Agent 组件**: Guardrails, Memory, Planner, Executor, Reflector
- **工具函数**: click.py, assertions.py, error.py
- 参考 AutoQA-Agent 测试架构设计