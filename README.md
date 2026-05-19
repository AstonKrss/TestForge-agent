# TestForge

AI 驱动的 Web 测试自动化框架

## 特性

- **AI 智能理解** - 输入自然语言，自动理解测试意图
- **无需脚本** - 直接描述测试步骤，AI 执行
- **多 AI 支持** - Claude / GPT / Gemini / DeepSeek / Qwen / Kimi / MiniMax
- **Playwright 驱动** - 稳定可靠的浏览器自动化

## 安装

```bash
pip install playwright
playwright install chromium
```

## 配置

```bash
python setup.py
```

选择 1 配置 AI（Claude / GPT / Gemini 等）

## 使用

```bash
python setup.py
```

选择 2 启动 CLI，然后：

```
(TestForge) > 测试一下 http://47.242.21.40/
(TestForge) > 测试登录功能
(TestForge) > 帮我填表
```

## 项目结构

```
TestForge/
├── setup.py          # 入口
├── src/
│   ├── cli/          # CLI 主程序
│   ├── ai_client/    # AI 客户端
│   ├── browser/      # 浏览器管理
│   └── tools/        # 自动化工具
└── examples/         # 示例
```

## License

MIT
