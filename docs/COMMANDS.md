# TestForge Command Guide

This page lists practical CLI commands you can use inside TestForge.

## Startup

```bash
python run_cli.py
```

Startup menu:

```text
1. 配置 API
2. 进入 CLI 测试
3. 运行测试用例
4. 加载会话
0. 退出
```

## Open And Explore

```text
帮我测试一下http://example.com这个网站
打开 https://example.com
现在页面有什么功能？
文章内容有什么，当前页面可以测试什么？
```

## Functional Testing

```text
测试登录功能 账号是admin 密码是********
测试搜索功能 搜索 linux
搜索 linux，打开第一篇文章，然后点赞
测试评论功能 评论一个666，如果需要登录就先登录
点击登录按钮
填写用户名 admin
填写密码 ********
```

## Full Suite

```text
完整测试 对http://example.com这个网站完整测试产出报告
全量测试 http://example.com
把这个网站全部都测试一遍并生成报告
full suite test https://example.com and generate report
```

Full suite includes:

- test plan
- sitemap
- known feature smoke test
- executable safe functional flows such as search, article reading, login verification, and comment prerequisites
- deep checks for discovered sections such as archive, tags, friends, projects, tools, games, photos, resources, RSS, register, and guestbook
- quality audit
- security audit
- accessibility audit
- performance audit
- low-pressure load test
- network/API summary
- HTML and JSON report export

## Known Feature Smoke Test

Use this when you want TestForge to test every safe feature entry it already knows from the current page, session memory, or sitemap, without running the heavier audits.

```text
测试当前页面所有已知功能
把页面能看到的功能都测一遍
test all functions
```

This is intentionally safer and narrower than the full suite: it opens discovered same-origin entries, checks for 404/blank/broken states, and skips logout/delete/pay/upload style actions.

## Engineering Commands

```text
测试计划
生成测试用例
用例列表
运行用例 login-case
根据需求文档 docs/login.md 生成测试用例
生成缺陷
运行Postman collection.json 环境 env.json
配置MySQL host=127.0.0.1 port=3306 user=root password=xxx database=test
执行SQL select * from users limit 10
导出 Playwright 用例
运行pytest 回归 tests/testforge
生成JMeter脚本 http://example.com 线程10 循环20 状态码200
环境检查
docker检查
k8s检查
docker日志 web
k8s日志 pod-name
回归对比 blog-test
站点地图
探索站点 http://example.com 深度2 页面20
探索站点 http://example.com 聚焦 include:/blog* exclude:/admin*
页面质量检查 当前页面
安全检查 当前页面
无障碍检查 当前页面
性能测试 当前页面 3次
压力测试 http://example.com 20次 并发2
网络日志
API测试
导出 Playwright 用例
生成报告 html
生成报告 json
生成报告 junit
生成报告 all
```

## QA Workbench

These commands turn TestForge into a broader testing engineer workbench:

- `生成测试用例`: converts the current test plan into JSON, Markdown, CSV, and XLSX files under `~/.testforge/cases`.
- `用例列表` / `运行用例 login-case`: lists saved cases and replays their natural-language steps through the agent planner.
- `根据需求文档 docs/a.md 生成测试用例`: parses Markdown/TXT requirements into test cases.
- `生成缺陷`: creates a local defect ticket from the latest failure, artifacts, and network summary.
- `运行Postman collection.json 环境 env.json`: executes a dependency-free subset of Postman Collection v2 format with `{{variables}}` substitution and saves an API report.
- `执行SQL select ...`: builds or optionally executes SQL checks. Real execution requires `~/.testforge/mysql.json` or `配置MySQL ...`.
- `导出 Playwright 用例` / `运行pytest 回归`: turns interaction IR into pytest-compatible Playwright skeletons and runs pytest.
- `生成JMeter脚本 URL 线程10 循环20 状态码200`: exports a `.jmx` file with thread group, HTTP sampler, response-code assertion, optional CSV data set, and summary listener.
- `环境检查` / `docker日志 web` / `k8s日志 pod`: runs safe read-only Linux/Docker/K8S/Git inspection or tail logs.
- `回归对比 session-name`: compares current session results with a saved session, including failures, tested features, pages, and performance metric deltas.

## Plan Explore

`探索站点` is inspired by AutoQA-Agent's `plan-explore` workflow. It performs bounded same-origin crawling and writes exploration artifacts.

```text
探索站点 http://example.com 深度2 页面20
探索站点 http://example.com 聚焦 include:/blog* exclude:/admin*
探索站点 http://example.com 单页
```

Supported options:

- `深度2` or `depth:2`
- `页面20` or `pages:20`
- `聚焦` / `focused`
- `单页` / `single_page`
- `include:/path*`
- `exclude:/admin*`

Artifacts:

```text
~/.testforge/runs/<session>-<runId>/plan-explore/
  navigation-graph.json
  elements.json
  transcript.jsonl
  summary.json
```

## Export Recorded Actions

Interactive CLI actions are recorded as IR. You can export them as a Playwright Python test skeleton:

```text
导出 Playwright 用例
导出 Playwright 用例 到 tests/generated
```

## Sessions

```text
保存会话 blog-test
加载会话 blog-test
会话列表
新建会话 temp-test
回归测试 blog-test
```

Saved sessions live under:

```text
~/.testforge/sessions/
```

## Visual Regression

```text
保存基线 homepage
视觉对比 homepage
```

Baselines live under:

```text
~/.testforge/visual-baselines/
```

## Test Data

```text
测试数据 用户
测试数据 评论
测试数据 文章
```

## Markdown Test Cases

From the startup menu choose:

```text
3. 运行测试用例
```

Or inside the CLI:

```text
运行 specs/login.md
```

## Useful Debug Commands

```text
status
截图
locator
Agent分工
help
q
```
