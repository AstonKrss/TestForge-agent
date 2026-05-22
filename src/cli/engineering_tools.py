"""
Software-testing engineering helpers for the interactive CLI.

These helpers keep non-browser orchestration concerns out of MainAgent:
test-plan generation, network/API observation, evidence capture, reporting,
test data, visual regression, locator memory, and lightweight site mapping.
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import random
import re
import string
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urljoin, urlunparse


TESTFORGE_HOME = Path.home() / ".testforge"


@dataclass
class UrlScope:
    """Exploration URL scope inspired by AutoQA-Agent plan-explore."""

    base_url: str
    mode: str = "site"  # site | focused | single_page
    include_patterns: List[str] = None
    exclude_patterns: List[str] = None

    def __post_init__(self):
        if self.mode not in {"site", "focused", "single_page"}:
            self.mode = "site"
        self.include_patterns = list(self.include_patterns or [])
        self.exclude_patterns = list(self.exclude_patterns or [])


def extract_relative_url(url: str) -> str:
    """Return pathname + query + hash for scope matching."""
    try:
        parsed = urlparse(url)
        return f"{parsed.path or '/'}{('?' + parsed.query) if parsed.query else ''}{('#' + parsed.fragment) if parsed.fragment else ''}"
    except Exception:
        return url


def _matches_url_pattern(relative_url: str, pattern: str) -> bool:
    if not pattern:
        return False
    if pattern.endswith("*"):
        return relative_url.startswith(pattern[:-1])
    return relative_url == pattern


def is_url_in_scope(url: str, scope: UrlScope) -> bool:
    """Return whether a URL is allowed by same-origin and include/exclude rules."""
    try:
        current = urlparse(url)
        base = urlparse(scope.base_url)
        if current.netloc and base.netloc and current.netloc != base.netloc:
            return False
    except Exception:
        pass

    relative = extract_relative_url(url)
    for pattern in scope.exclude_patterns:
        if _matches_url_pattern(relative, pattern):
            return False

    if scope.mode == "site":
        if not scope.include_patterns:
            return True
        return any(_matches_url_pattern(relative, pattern) for pattern in scope.include_patterns)

    if not scope.include_patterns:
        base_relative = extract_relative_url(scope.base_url)
        if scope.mode == "single_page":
            return relative.split("#")[0] == base_relative.split("#")[0]
        return relative.startswith(base_relative.rstrip("*"))

    return any(_matches_url_pattern(relative, pattern) for pattern in scope.include_patterns)


@dataclass
class TestPlanItem:
    feature: str
    precondition: str
    steps: List[str]
    expected: str
    risk: str
    needs_login: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TestPlanGenerator:
    """Generate a practical test matrix from a page snapshot."""

    def generate(self, snapshot: Dict[str, Any]) -> List[TestPlanItem]:
        elements = snapshot.get("elements") or []
        text = (snapshot.get("text") or "").lower()
        url = snapshot.get("url") or ""
        blob = " ".join(
            " ".join(str(e.get(k, "")) for k in ("text", "placeholder", "label", "ariaLabel", "href", "type"))
            for e in elements
        ).lower()
        combined = f"{text} {blob} {url.lower()}"

        items: List[TestPlanItem] = [
            TestPlanItem(
                feature="核心导航",
                precondition="已打开目标站点首页或当前页面",
                steps=["点击主要导航入口", "检查 URL/标题/页面主要内容是否变化", "返回上一页或继续访问下一个入口"],
                expected="导航可点击，目标页面正常加载，无 404/空白/控制台明显错误",
                risk="中",
            )
        ]

        for dynamic_item in self._items_from_visible_links(elements, combined):
            if all(existing.feature != dynamic_item.feature for existing in items):
                items.append(dynamic_item)

        if any(term in combined for term in ["搜索", "search", "查询"]):
            items.append(TestPlanItem(
                feature="搜索功能",
                precondition="页面存在搜索入口或搜索输入框",
                steps=["进入搜索页或定位搜索框", "输入代表性关键词", "提交搜索", "打开一条结果"],
                expected="结果页包含关键词相关内容，结果链接可打开，空结果有合理提示",
                risk="高",
            ))

        if any(term in combined for term in ["登录", "login", "sign in", "signin"]):
            items.append(TestPlanItem(
                feature="登录/认证",
                precondition="准备有效账号密码；如有验证码需人工提供",
                steps=["进入登录页", "填写账号密码", "提交登录", "检查 token/cookie/退出入口/受保护页面"],
                expected="正确凭证登录成功，错误凭证出现明确提示且不泄露敏感信息",
                risk="高",
                needs_login=False,
            ))

        if any(term in combined for term in ["评论", "留言", "comment", "guestbook"]):
            items.append(TestPlanItem(
                feature="评论/留言",
                precondition="文章详情页或留言页；可能需要登录",
                steps=["进入可评论页面", "尝试未登录评论", "登录后填写评论内容", "提交并检查列表"],
                expected="未登录时提示登录；登录后评论出现在列表，非法内容有校验",
                risk="高",
                needs_login=True,
            ))

        if any(term in combined for term in ["点赞", "赞", "like", "heart", "thumb", "upvote"]):
            items.append(TestPlanItem(
                feature="点赞/互动",
                precondition="进入文章或内容详情页；可能需要登录",
                steps=["记录当前点赞状态/数量", "点击点赞", "刷新或重新进入页面", "检查状态是否保持"],
                expected="点赞状态或数量发生预期变化；重复点击/取消点赞逻辑合理",
                risk="中",
                needs_login=True,
            ))

        forms = [e for e in elements if e.get("tag") in ("input", "textarea", "select")]
        if forms:
            items.append(TestPlanItem(
                feature="表单校验",
                precondition="页面存在输入框/下拉框/文本域",
                steps=["提交空表单", "输入边界值和特殊字符", "输入正常值并提交"],
                expected="必填项、格式、长度、错误提示和成功提示均符合预期",
                risk="高",
            ))

        items.extend([
            TestPlanItem(
                feature="页面性能",
                precondition="目标页面可访问",
                steps=["运行性能测试", "检查 TTFB/FCP/Load/慢资源", "记录优化建议"],
                expected="关键页面指标在可接受范围内，慢资源可定位",
                risk="中",
            ),
            TestPlanItem(
                feature="页面质量/无障碍/基础安全",
                precondition="目标页面可访问",
                steps=["运行页面质量检查", "检查 alt/label/title/lang/viewport/链接安全", "记录问题"],
                expected="无明显可访问性、SEO、混合内容或不安全链接问题",
                risk="中",
            ),
        ])
        return items

    def _items_from_visible_links(self, elements: List[Dict[str, Any]], combined: str) -> List[TestPlanItem]:
        """Derive concrete test-plan rows from the actual page navigation."""
        items: List[TestPlanItem] = []
        seen: set[str] = set()
        skip = {"首页", "home", "rss", "github", "mailto", "全屏模式"}

        for element in elements:
            href = str(element.get("href") or "")
            label = self._clean_link_label(
                element.get("text")
                or element.get("ariaLabel")
                or element.get("label")
                or element.get("placeholder")
                or ""
            )
            if not href or not label:
                continue
            if label.lower() in skip or len(label) > 28:
                continue

            key = f"{label}|{href}"
            if key in seen:
                continue
            seen.add(key)

            if self._is_search_label(label, href) or self._is_auth_label(label, href):
                continue

            risk = "高" if self._is_interactive_label(label, href) else "中"
            needs_login = self._needs_login_label(label, href)
            items.append(TestPlanItem(
                feature=f"{label}入口",
                precondition="已打开当前页面，且该入口在页面上可见",
                steps=[f"点击“{label}”入口", "检查目标 URL、标题和主内容是否正常", "检查是否出现 404、空白页或明显控制台错误"],
                expected=f"“{label}”页面可以正常打开，并展示与入口语义一致的内容",
                risk=risk,
                needs_login=needs_login,
            ))
            if len(items) >= 6:
                break

        if any(term in combined for term in ["blog", "文章", "/blog", "post", "article"]):
            items.append(TestPlanItem(
                feature="文章详情阅读",
                precondition="站点存在文章列表或博客入口",
                steps=["进入文章列表", "打开一篇文章详情", "检查标题、正文、代码块/图片和目录锚点", "返回列表或继续查看下一篇"],
                expected="文章详情页内容完整，链接和锚点可用，正文不空白",
                risk="高",
            ))

        if any(term in combined for term in ["标签", "归档", "tag", "archive"]):
            items.append(TestPlanItem(
                feature="归档/标签筛选",
                precondition="站点存在标签或归档入口",
                steps=["打开标签或归档页", "选择一个分类/月份/标签", "打开筛选后的文章"],
                expected="筛选结果与分类语义一致，结果文章可正常进入详情页",
                risk="中",
            ))

        if any(term in combined for term in ["项目", "工具", "相册", "游戏", "project", "tool", "photo", "game"]):
            items.append(TestPlanItem(
                feature="专题入口/工具页面",
                precondition="站点存在项目、工具、相册或游戏等专题入口",
                steps=["逐个打开主要专题入口", "检查页面主内容和资源加载", "记录失败入口和慢资源"],
                expected="专题页面可访问，资源正常加载，无明显断链或空白模块",
                risk="中",
            ))

        return items

    def _clean_link_label(self, value: str) -> str:
        label = re.sub(r"\s+", " ", str(value or "")).strip()
        label = re.sub(r"^(精选|博客)\s+", "", label)
        return label[:40]

    def _is_search_label(self, label: str, href: str) -> bool:
        blob = f"{label} {href}".lower()
        return any(term in blob for term in ["搜索", "search", "查询"])

    def _is_auth_label(self, label: str, href: str) -> bool:
        blob = f"{label} {href}".lower()
        return any(term in blob for term in ["登录", "注册", "login", "register", "sign in", "signup"])

    def _is_interactive_label(self, label: str, href: str) -> bool:
        blob = f"{label} {href}".lower()
        return any(term in blob for term in ["留言", "评论", "guestbook", "comment", "点赞", "like", "写文章", "发布"])

    def _needs_login_label(self, label: str, href: str) -> bool:
        blob = f"{label} {href}".lower()
        return any(term in blob for term in ["留言", "评论", "guestbook", "comment", "点赞", "like", "写文章", "发布", "后台", "admin"])


class NetworkRecorder:
    """Capture recent browser requests/responses for API-oriented checks."""

    def __init__(self, limit: int = 300):
        self.limit = limit
        self.records: List[Dict[str, Any]] = []
        self._starts: Dict[Any, float] = {}
        self._attached = False

    def attach(self, page) -> None:
        if self._attached:
            return
        self._attached = True
        try:
            page.on("request", self._on_request)
            page.on("response", self._on_response)
            page.on("requestfailed", self._on_request_failed)
        except Exception:
            self._attached = False

    def clear(self) -> None:
        """Start a fresh network window for a new task/report."""
        self.records.clear()
        self._starts.clear()

    def _on_request(self, request) -> None:
        self._starts[request] = time.monotonic()

    def _on_response(self, response) -> None:
        request = response.request
        started = self._starts.pop(request, None)
        duration = round((time.monotonic() - started) * 1000, 2) if started else 0
        self._append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "method": request.method,
            "url": response.url,
            "status": response.status,
            "resource_type": request.resource_type,
            "duration": duration,
            "ok": response.status < 400,
            "error": "",
        })

    def _on_request_failed(self, request) -> None:
        started = self._starts.pop(request, None)
        duration = round((time.monotonic() - started) * 1000, 2) if started else 0
        failure = request.failure or {}
        self._append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "method": request.method,
            "url": request.url,
            "status": 0,
            "resource_type": request.resource_type,
            "duration": duration,
            "ok": False,
            "error": failure.get("errorText") if isinstance(failure, dict) else str(failure),
        })

    def _append(self, record: Dict[str, Any]) -> None:
        self.records.append(record)
        self.records = self.records[-self.limit:]

    def summary(self) -> Dict[str, Any]:
        total = len(self.records)
        failed = [r for r in self.records if not r.get("ok")]
        slow = sorted(self.records, key=lambda r: r.get("duration", 0), reverse=True)[:10]
        api_like = [
            r for r in self.records
            if r.get("resource_type") in {"fetch", "xhr"} or re.search(r"/api/|_rsc=|graphql", r.get("url", ""), re.I)
        ]
        status_counts: Dict[str, int] = {}
        for record in self.records:
            status = str(record.get("status", "ERR"))
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "total": total,
            "api_like": len(api_like),
            "failed": len(failed),
            "status_counts": status_counts,
            "slow": slow,
            "recent_api": api_like[-20:],
        }


class EvidenceCollector:
    """Save screenshot, DOM snapshot, and network records when a step fails."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "artifacts"

    async def capture_failure(
        self,
        page,
        session_name: str,
        reason: str,
        snapshot: Dict[str, Any],
        network_records: List[Dict[str, Any]],
    ) -> Path:
        safe_session = _safe_name(session_name or "default")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        artifact_dir = self.base_dir / safe_session / f"failure-{timestamp}"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        try:
            await page.screenshot(path=str(artifact_dir / "screenshot.png"), full_page=True)
        except Exception:
            pass
        try:
            html_text = await page.content()
            (artifact_dir / "dom.html").write_text(html_text, encoding="utf-8")
        except Exception:
            pass

        (artifact_dir / "snapshot.json").write_text(
            json.dumps(snapshot or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (artifact_dir / "network.json").write_text(
            json.dumps(network_records[-100:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (artifact_dir / "reason.txt").write_text(reason or "", encoding="utf-8")
        return artifact_dir


class ReportGenerator:
    """Write session reports in Markdown, HTML, JSON, or JUnit XML."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "reports"

    def write(self, context: Dict[str, Any], fmt: str = "markdown", name: str = "") -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        fmt = (fmt or "markdown").lower()
        if fmt in {"md", "markdown"}:
            suffix = "md"
            content = self._markdown(context)
        elif fmt == "html":
            suffix = "html"
            content = self._html(context)
        elif fmt == "json":
            suffix = "json"
            content = json.dumps(context, ensure_ascii=False, indent=2)
        elif fmt == "junit":
            suffix = "xml"
            content = self._junit(context)
        else:
            raise ValueError(f"不支持的报告格式: {fmt}")

        base = _safe_name(name or context.get("session_name") or "testforge-report")
        path = self.base_dir / f"{base}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{suffix}"
        path.write_text(content, encoding="utf-8")
        return path

    def _markdown(self, context: Dict[str, Any]) -> str:
        events = context.get("events") or []
        failures = [
            event for event in events
            if event.get("data", {}).get("result_type") == "failure"
            or "失败" in str(event.get("text", ""))
            or "failed" in str(event.get("text", "")).lower()
        ]
        artifacts = context.get("artifacts") or []
        reports = context.get("reports") or []
        lines = [
            f"# TestForge Report - {context.get('session_name', 'default')}",
            "",
            f"- Current URL: {context.get('current_url', '')}",
            f"- Logged in: {context.get('is_logged_in', False)}",
            f"- Tested features: {', '.join(context.get('tested_features') or [])}",
            f"- Events: {len(events)}",
            f"- Failures: {len(failures)}",
            f"- Evidence artifacts: {len(artifacts)}",
            "",
            "## Conclusion",
            "",
            "PASS" if not failures else "ATTENTION REQUIRED",
            "",
            "## Failed Steps",
        ]
        if failures:
            for event in failures[:20]:
                lines.append(f"- `{event.get('time', '')}` {event.get('text', '')}")
        else:
            lines.append("- No failed tool result recorded.")
        lines.extend([
            "",
            "## Test Plan",
        ])
        for item in context.get("test_plan") or []:
            lines.append(f"- **{item.get('feature')}** | risk={item.get('risk')} | login={item.get('needs_login')}")
            lines.append(f"  - Precondition: {item.get('precondition')}")
            lines.append(f"  - Expected: {item.get('expected')}")
        lines.extend(["", "## Site Map"])
        site_map = context.get("site_map") or {}
        for item in (site_map.get("nodes") or site_map.get("links") or [])[:30]:
            lines.append(f"- {item.get('text') or '(no text)'} -> {item.get('href')}")
        lines.extend(["", "## Events"])
        for event in events:
            lines.append(f"- `{event.get('time', '')}` **{event.get('role', '')}**: {event.get('text', '')}")
        lines.extend(["", "## Artifacts"])
        for artifact in artifacts:
            lines.append(f"- {artifact}")
        lines.extend(["", "## Reports"])
        for report in reports:
            lines.append(f"- {report}")
        return "\n".join(lines) + "\n"

    def _html(self, context: Dict[str, Any]) -> str:
        md = self._markdown(context)
        escaped = html.escape(md)
        return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>TestForge Report</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;max-width:980px;margin:32px auto;line-height:1.55}}pre{{white-space:pre-wrap;background:#f6f8fa;padding:16px;border-radius:8px}}</style>
</head>
<body><pre>{escaped}</pre></body></html>
"""

    def _junit(self, context: Dict[str, Any]) -> str:
        events = context.get("events") or []
        failures = [
            event for event in events
            if "失败" in event.get("text", "")
            or "failed" in event.get("text", "").lower()
            or event.get("data", {}).get("result_type") == "failure"
        ]
        cases = []
        for index, event in enumerate(events or [{"text": "session"}], 1):
            name = html.escape((event.get("text") or f"event-{index}")[:120])
            body = ""
            if event in failures:
                body = f'<failure message="{name}">{html.escape(json.dumps(event, ensure_ascii=False))}</failure>'
            cases.append(f'<testcase classname="TestForge" name="{name}">{body}</testcase>')
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<testsuite name="TestForge" tests="{len(cases)}" failures="{len(failures)}">\n'
            + "\n".join(cases)
            + "\n</testsuite>\n"
        )


class TestDataManager:
    """Generate and remember test data created during a session."""

    def generate(self, kind: str = "comment") -> Dict[str, str]:
        suffix = datetime.now().strftime("%Y%m%d%H%M%S") + "".join(random.choices(string.ascii_lowercase, k=4))
        kind = (kind or "comment").lower()
        if any(term in kind for term in ["user", "用户", "账号", "用户名"]):
            return {"kind": "user", "username": f"tf_user_{suffix}", "email": f"tf_{suffix}@example.com"}
        if any(term in kind for term in ["email", "邮箱"]):
            return {"kind": "email", "email": f"tf_{suffix}@example.com"}
        if any(term in kind for term in ["article", "文章"]):
            return {"kind": "article", "title": f"TestForge 自动测试文章 {suffix}", "content": f"自动化测试内容 {suffix}"}
        return {"kind": "comment", "text": f"TestForge 自动测试评论 {suffix}"}


class VisualRegression:
    """Save and compare screenshot baselines."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "visual"

    async def save_baseline(self, page, name: str) -> Path:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(path), full_page=True)
        return path

    async def compare(self, page, name: str) -> Dict[str, Any]:
        baseline = self._path(name)
        if not baseline.exists():
            raise FileNotFoundError(f"视觉基线不存在: {name}")
        current = baseline.with_name(baseline.stem + "-current.png")
        await page.screenshot(path=str(current), full_page=True)
        result = {"baseline": str(baseline), "current": str(current), "diff_percent": None, "passed": False}
        try:
            from PIL import Image, ImageChops, ImageStat

            with Image.open(baseline) as base_img, Image.open(current) as current_img:
                if base_img.size != current_img.size:
                    result["diff_percent"] = 100.0
                    return result
                diff = ImageChops.difference(base_img.convert("RGB"), current_img.convert("RGB"))
                stat = ImageStat.Stat(diff)
                mean = sum(stat.mean) / len(stat.mean)
                percent = round((mean / 255) * 100, 3)
                result["diff_percent"] = percent
                result["passed"] = percent <= 1.0
        except Exception:
            result["passed"] = baseline.read_bytes() == current.read_bytes()
            result["diff_percent"] = 0.0 if result["passed"] else 100.0
        return result

    def _path(self, name: str) -> Path:
        return self.base_dir / f"{_safe_name(name or 'baseline')}.png"


class LocatorMemory:
    """Persist successful locator hints by host and target description."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else TESTFORGE_HOME / "locator-memory.json"
        self.data = self._load()

    def record(self, url: str, description: str, element: Dict[str, Any]) -> None:
        if not description:
            return
        host = urlparse(url or "").netloc or "unknown"
        self.data.setdefault(host, {})[_safe_key(description)] = {
            "description": description,
            "text": element.get("text", ""),
            "href": element.get("href", ""),
            "role": element.get("role", ""),
            "tag": element.get("tag", ""),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save()

    def lookup(self, url: str, description: str) -> Dict[str, Any]:
        host = urlparse(url or "").netloc or "unknown"
        return self.data.get(host, {}).get(_safe_key(description), {})

    def _load(self) -> Dict[str, Any]:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


async def build_site_map(page, max_links: int = 60) -> Dict[str, Any]:
    """Build a lightweight same-page link map without crawling the whole site."""
    try:
        data = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]')).map((a) => ({
                text: (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80),
                href: a.href,
            })).filter((item) => item.href)
        """)
    except Exception:
        data = []
    origin = ""
    try:
        parsed = urlparse(page.url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        pass
    links = []
    seen = set()
    for item in data:
        href = item.get("href", "")
        key = href.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        links.append({**item, "same_origin": href.startswith(origin)})
        if len(links) >= max_links:
            break
    return {"root": page.url, "origin": origin, "nodes": links, "total": len(links)}


async def explore_site_map(
    page,
    scope: UrlScope,
    max_depth: int = 2,
    max_pages: int = 20,
    links_per_page: int = 40,
) -> Dict[str, Any]:
    """Crawl same-origin pages within a bounded URL scope and return exploration artifacts."""
    max_depth = max(0, min(int(max_depth or 0), 5))
    max_pages = max(1, min(int(max_pages or 1), 100))
    links_per_page = max(1, min(int(links_per_page or 1), 100))

    started_at = datetime.now().isoformat(timespec="seconds")
    root_url = scope.base_url or getattr(page, "url", "")
    queue: List[Dict[str, Any]] = [{"url": root_url, "depth": 0, "from": "", "trigger": "start"}]
    visited: set[str] = set()
    pages: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    transcript: List[Dict[str, Any]] = []

    original_url = getattr(page, "url", "")

    while queue and len(pages) < max_pages:
        item = queue.pop(0)
        url = item["url"]
        normalized = _normalize_explore_url(url)
        if normalized in visited:
            continue
        visited.add(normalized)

        if not is_url_in_scope(url, scope):
            transcript.append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "event": "skip_out_of_scope",
                "url": url,
            })
            continue

        try:
            if getattr(page, "url", "") != url:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
        except Exception as e:
            transcript.append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "event": "navigate_failed",
                "url": url,
                "error": str(e)[:300],
            })
            continue

        snapshot = await _extract_exploration_page(page, links_per_page)
        page_id = f"p{len(pages) + 1}"
        page_node = {
            "id": page_id,
            "url": snapshot.get("url", url),
            "title": snapshot.get("title", ""),
            "depth": item["depth"],
            "summary": snapshot.get("summary", ""),
            "links": snapshot.get("links", []),
            "forms": snapshot.get("forms", []),
            "elementSummary": snapshot.get("elements", []),
        }
        pages.append(page_node)
        transcript.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": "page_explored",
            "url": page_node["url"],
            "depth": item["depth"],
            "links": len(page_node["links"]),
            "forms": len(page_node["forms"]),
            "elements": len(page_node["elementSummary"]),
        })

        if item["from"]:
            edges.append({
                "from": item["from"],
                "to": page_id,
                "trigger": item.get("trigger", "link"),
            })

        if item["depth"] >= max_depth or scope.mode == "single_page":
            continue

        for link in snapshot.get("links", [])[:links_per_page]:
            href = link.get("href", "")
            if not href:
                continue
            absolute = urljoin(page_node["url"], href)
            if _normalize_explore_url(absolute) in visited:
                continue
            if not is_url_in_scope(absolute, scope):
                continue
            queue.append({
                "url": absolute,
                "depth": item["depth"] + 1,
                "from": page_id,
                "trigger": link.get("text") or href,
            })

    try:
        if original_url and original_url != "about:blank" and getattr(page, "url", "") != original_url:
            await page.goto(original_url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        pass

    finished_at = datetime.now().isoformat(timespec="seconds")
    stats = {
        "pagesVisited": len(pages),
        "linksFound": sum(len(p.get("links", [])) for p in pages),
        "formsFound": sum(len(p.get("forms", [])) for p in pages),
        "elementsFound": sum(len(p.get("elementSummary", [])) for p in pages),
        "maxDepthReached": max([p.get("depth", 0) for p in pages] or [0]),
        "configuredDepth": max_depth,
    }
    return {
        "runId": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "startUrl": root_url,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "scope": asdict(scope),
        "stats": stats,
        "graph": {"pages": pages, "edges": edges},
        "transcript": transcript,
    }


def write_exploration_artifacts(result: Dict[str, Any], session_name: str = "default") -> Path:
    """Write plan-explore style artifacts under ~/.testforge/runs."""
    run_id = result.get("runId") or datetime.now().strftime("%Y%m%d-%H%M%S")
    base = TESTFORGE_HOME / "runs" / _safe_name(f"{session_name}-{run_id}") / "plan-explore"
    base.mkdir(parents=True, exist_ok=True)

    (base / "navigation-graph.json").write_text(
        json.dumps(result.get("graph", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elements = []
    for page_node in result.get("graph", {}).get("pages", []):
        for element in page_node.get("elementSummary", []):
            elements.append({"pageUrl": page_node.get("url"), **element})
    (base / "elements.json").write_text(
        json.dumps(elements, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with open(base / "transcript.jsonl", "w", encoding="utf-8") as f:
        for entry in result.get("transcript", []):
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    (base / "summary.json").write_text(
        json.dumps({
            "runId": result.get("runId"),
            "startUrl": result.get("startUrl"),
            "startedAt": result.get("startedAt"),
            "finishedAt": result.get("finishedAt"),
            "scope": result.get("scope"),
            "stats": result.get("stats"),
            "artifactDir": str(base),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return base


async def _extract_exploration_page(page, max_links: int) -> Dict[str, Any]:
    return await page.evaluate(
        """(maxLinks) => {
            const clean = (value, max = 120) => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, max);
            const visible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            };
            const links = Array.from(document.querySelectorAll('a[href]'))
                .filter(visible)
                .map((a) => ({ text: clean(a.innerText || a.textContent, 100), href: a.href }))
                .filter((item, index, arr) => item.href && arr.findIndex((x) => x.href === item.href) === index)
                .slice(0, maxLinks);
            const elements = Array.from(document.querySelectorAll('a[href], button, input, textarea, select, [role="button"]'))
                .filter(visible)
                .map((el, index) => ({
                    id: `e${index + 1}`,
                    kind: el.tagName.toLowerCase(),
                    text: clean(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.getAttribute('name'), 100),
                    href: el.href || '',
                    inputType: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                }))
                .slice(0, 80);
            const forms = Array.from(document.forms).map((form, index) => ({
                id: `f${index + 1}`,
                action: form.action || '',
                method: form.method || 'get',
                fields: Array.from(form.querySelectorAll('input, textarea, select')).map((field) => ({
                    name: field.getAttribute('name') || '',
                    type: field.getAttribute('type') || field.tagName.toLowerCase(),
                    placeholder: field.getAttribute('placeholder') || '',
                })),
            })).slice(0, 20);
            return {
                url: location.href,
                title: document.title || '',
                summary: clean(document.body ? document.body.innerText : '', 500),
                links,
                elements,
                forms,
            };
        }""",
        max_links,
    )


def _normalize_explore_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", parsed.query, parsed.fragment))
    except Exception:
        return url


def _safe_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "default"))
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned[:80] or "default"


def _safe_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())[:120]


__all__ = [
    "EvidenceCollector",
    "LocatorMemory",
    "NetworkRecorder",
    "ReportGenerator",
    "TestDataManager",
    "TestPlanGenerator",
    "TestPlanItem",
    "UrlScope",
    "VisualRegression",
    "build_site_map",
    "explore_site_map",
    "extract_relative_url",
    "is_url_in_scope",
    "write_exploration_artifacts",
]
