"""
QA workbench helpers for test engineers.

This module keeps practical testing-tool integrations separate from the
interactive MainAgent loop. The first versions are intentionally lightweight:
they generate durable local artifacts and run only safe/read-only checks unless
the user explicitly provides executable input such as a Postman collection.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .engineering_tools import TESTFORGE_HOME


def _safe_name(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value or "", flags=re.UNICODE).strip("-")
    return value[:80] or "testforge"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class ManagedTestCase:
    module: str
    feature: str
    precondition: str
    steps: List[str]
    expected: str
    priority: str = "P2"
    case_type: str = "functional"
    needs_login: bool = False
    automated: bool = False
    execution_result: str = "not_run"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TestCaseManager:
    """Persist and export test cases as JSON, Markdown, CSV, and XLSX."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "cases"

    def from_plan(self, plan_items: List[Dict[str, Any]], module: str = "Web") -> List[ManagedTestCase]:
        cases: List[ManagedTestCase] = []
        for item in plan_items or []:
            steps = item.get("steps") or []
            if isinstance(steps, str):
                steps = [part.strip() for part in re.split(r"->|;|\n", steps) if part.strip()]
            risk = str(item.get("risk") or "").lower()
            priority = "P1" if any(token in risk for token in ["high", "高"]) else "P2"
            cases.append(ManagedTestCase(
                module=module,
                feature=str(item.get("feature") or "未命名功能"),
                precondition=str(item.get("precondition") or "已打开目标页面"),
                steps=[str(step) for step in steps],
                expected=str(item.get("expected") or "功能表现符合预期"),
                priority=priority,
                needs_login=bool(item.get("needs_login")),
            ))
        return cases

    def from_requirements(self, text: str, module: str = "需求") -> List[ManagedTestCase]:
        lines = [line.strip() for line in (text or "").splitlines()]
        cases: List[ManagedTestCase] = []
        current_module = module
        bullets: List[str] = []

        def flush(feature: str, items: List[str]) -> None:
            clean_items = [item for item in items if item]
            if not feature and not clean_items:
                return
            expected = "需求功能按文档描述正确实现，异常输入有合理提示"
            cases.append(ManagedTestCase(
                module=current_module,
                feature=feature or (clean_items[0][:40] if clean_items else "需求功能"),
                precondition="需求已评审，测试环境可访问",
                steps=[
                    "根据需求文档准备测试数据",
                    *(clean_items[:5] or ["执行需求中的核心业务流程"]),
                    "检查页面/接口/数据库结果是否符合预期",
                ],
                expected=expected,
                priority="P1" if any("必须" in item or "核心" in item for item in clean_items) else "P2",
                case_type="requirement",
            ))

        heading = ""
        for line in lines:
            if not line:
                continue
            if line.startswith("#"):
                if heading or bullets:
                    flush(heading, bullets)
                heading = line.lstrip("#").strip()
                current_module = heading or module
                bullets = []
            elif re.match(r"^[-*]\s+", line) or re.match(r"^\d+[.)、]\s+", line):
                bullets.append(re.sub(r"^[-*]\s+|^\d+[.)、]\s+", "", line).strip())
            elif any(keyword in line for keyword in ["需求", "功能", "规则", "流程", "校验", "权限"]):
                bullets.append(line)
        if heading or bullets:
            flush(heading, bullets)

        if not cases and text.strip():
            flush(module, [text.strip()[:300]])
        return cases

    def save(self, name: str, cases: List[ManagedTestCase]) -> Dict[str, str]:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        base = self.base_dir / _safe_name(name)
        payload = {
            "name": name,
            "created_at": _now(),
            "total": len(cases),
            "cases": [case.to_dict() for case in cases],
        }
        json_path = base.with_suffix(".json")
        md_path = base.with_suffix(".md")
        csv_path = base.with_suffix(".csv")
        xlsx_path = base.with_suffix(".xlsx")

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(self._markdown(payload), encoding="utf-8")
        fieldnames = [
            "module",
            "feature",
            "precondition",
            "steps",
            "expected",
            "priority",
            "case_type",
            "needs_login",
            "automated",
            "execution_result",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for case in payload["cases"]:
                row = dict(case)
                row["steps"] = "\n".join(row.get("steps") or [])
                writer.writerow(row)
        self._write_xlsx(xlsx_path, fieldnames, payload["cases"])
        return {"json": str(json_path), "markdown": str(md_path), "csv": str(csv_path), "xlsx": str(xlsx_path)}

    def load(self, name_or_path: str) -> Dict[str, Any]:
        path = Path(name_or_path).expanduser()
        if not path.exists():
            path = self.base_dir / f"{_safe_name(name_or_path)}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["path"] = str(path)
        return payload

    def list_cases(self) -> List[Dict[str, Any]]:
        if not self.base_dir.exists():
            return []
        items = []
        for path in sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                items.append({
                    "name": payload.get("name") or path.stem,
                    "total": payload.get("total", 0),
                    "path": str(path),
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
                })
            except Exception:
                continue
        return items

    def _markdown(self, payload: Dict[str, Any]) -> str:
        lines = [f"# Test Cases - {payload.get('name')}", "", f"- Total: {payload.get('total', 0)}", ""]
        for index, case in enumerate(payload.get("cases") or [], 1):
            lines.append(f"## TC-{index:03d} {case.get('feature')}")
            lines.append(f"- Module: {case.get('module')}")
            lines.append(f"- Priority: {case.get('priority')}")
            lines.append(f"- Type: {case.get('case_type')}")
            lines.append(f"- Needs login: {case.get('needs_login')}")
            lines.append(f"- Precondition: {case.get('precondition')}")
            lines.append("- Steps:")
            for step_index, step in enumerate(case.get("steps") or [], 1):
                lines.append(f"  {step_index}. {step}")
            lines.append(f"- Expected: {case.get('expected')}")
            lines.append("")
        return "\n".join(lines)

    def _write_xlsx(self, path: Path, headers: List[str], cases: List[Dict[str, Any]]) -> None:
        rows = [headers]
        for case in cases:
            rows.append([
                "\n".join(case.get(header) or []) if isinstance(case.get(header), list) else str(case.get(header, ""))
                for header in headers
            ])

        def cell_ref(row_index: int, col_index: int) -> str:
            name = ""
            col = col_index
            while col:
                col, rem = divmod(col - 1, 26)
                name = chr(65 + rem) + name
            return f"{name}{row_index}"

        def escape(value: Any) -> str:
            return (
                str(value)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        sheet_rows = []
        for row_index, row in enumerate(rows, 1):
            cells = []
            for col_index, value in enumerate(row, 1):
                cells.append(
                    f'<c r="{cell_ref(row_index, col_index)}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                )
            sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

        sheet_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(sheet_rows)}</sheetData>'
            '</worksheet>'
        )
        workbook_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="TestCases" sheetId="1" r:id="rId1"/></sheets></workbook>'
        )
        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>'
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", rels_xml)
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)


class DefectManager:
    """Create local defect tickets from failures and evidence."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "defects"

    def create(self, context: Dict[str, Any], title: str = "", severity: str = "P2") -> Dict[str, Any]:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        failures = [
            event for event in context.get("events", [])
            if event.get("data", {}).get("result_type") == "failure"
            or "失败" in str(event.get("text", ""))
            or "failed" in str(event.get("text", "")).lower()
        ]
        last_failure = failures[-1] if failures else {}
        title = title or last_failure.get("text") or "自动化测试发现异常"
        defect = {
            "id": f"BUG-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "title": title[:120],
            "severity": severity,
            "status": "open",
            "created_at": _now(),
            "url": context.get("current_url", ""),
            "expected": "页面或接口行为符合测试预期",
            "actual": last_failure.get("text") or "执行结果未达到预期",
            "steps": [event.get("text", "") for event in context.get("events", [])[-8:]],
            "artifacts": context.get("artifacts", [])[-10:],
            "network": context.get("network", {}),
            "api_errors": self._api_errors(context.get("network", {})),
            "console_errors": context.get("console_errors", [])[-20:],
        }
        path = self.base_dir / f"{defect['id']}-{_safe_name(defect['title'])}.md"
        path.write_text(self._markdown(defect), encoding="utf-8")
        defect["path"] = str(path)
        return defect

    def _markdown(self, defect: Dict[str, Any]) -> str:
        lines = [
            f"# {defect['id']} {defect['title']}",
            "",
            f"- Severity: {defect['severity']}",
            f"- Status: {defect['status']}",
            f"- URL: {defect.get('url', '')}",
            f"- Created: {defect['created_at']}",
            "",
            "## Steps",
        ]
        for index, step in enumerate(defect.get("steps") or [], 1):
            lines.append(f"{index}. {step}")
        lines.extend([
            "",
            "## Expected",
            defect.get("expected", ""),
            "",
            "## Actual",
            defect.get("actual", ""),
            "",
            "## Evidence",
        ])
        for artifact in defect.get("artifacts") or []:
            lines.append(f"- {artifact}")
        lines.extend(["", "## API / Console Evidence"])
        for item in defect.get("api_errors") or []:
            lines.append(f"- API: {item}")
        for item in defect.get("console_errors") or []:
            lines.append(f"- Console: {item}")
        lines.extend([
            "",
            "## Copyable Summary",
            f"[{defect['severity']}] {defect['title']} - {defect.get('url', '')}",
        ])
        return "\n".join(lines) + "\n"

    def _api_errors(self, network: Dict[str, Any]) -> List[str]:
        errors = []
        if network.get("failed"):
            errors.append(f"failed requests: {network.get('failed')}")
        for record in network.get("recent_api") or []:
            status = str(record.get("status", ""))
            if status.startswith("4") or status.startswith("5") or status in {"0", "ERR"}:
                errors.append(f"{status} {record.get('method', '')} {record.get('url', '')}")
        return errors[:20]


class PostmanCollectionRunner:
    """Run a small, dependency-free subset of Postman collections."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "api-runs"

    def run(self, path: str, timeout: float = 10.0, max_requests: int = 100, env_path: str = "") -> Dict[str, Any]:
        collection_path = Path(path).expanduser()
        payload = json.loads(collection_path.read_text(encoding="utf-8"))
        variables = self._variables_from_payload(payload)
        if env_path:
            variables.update(self._variables_from_environment(env_path))
        requests = self._flatten_items(payload.get("item") or [])
        results = []
        started = time.time()
        for item in requests[:max_requests]:
            results.append(self._run_one(item, timeout=timeout, variables=variables))
        summary = {
            "collection": str(collection_path),
            "name": payload.get("info", {}).get("name") or collection_path.stem,
            "total": len(results),
            "passed": sum(1 for result in results if result.get("ok")),
            "failed": sum(1 for result in results if not result.get("ok")),
            "duration_ms": round((time.time() - started) * 1000, 1),
            "variables": sorted(variables.keys()),
            "results": results,
        }
        self.base_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.base_dir / f"{_safe_name(summary['name'])}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["report_path"] = str(report_path)
        return summary

    def _flatten_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        flattened: List[Dict[str, Any]] = []
        for item in items:
            if item.get("item"):
                flattened.extend(self._flatten_items(item.get("item") or []))
            elif item.get("request"):
                flattened.append(item)
        return flattened

    def _run_one(self, item: Dict[str, Any], timeout: float, variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        variables = variables or {}
        request = item.get("request") or {}
        method = str(request.get("method") or "GET").upper()
        url = self._substitute(self._url_to_string(request.get("url")), variables)
        headers = {
            self._substitute(header.get("key"), variables): self._substitute(header.get("value", ""), variables)
            for header in request.get("header") or []
            if header.get("key") and not header.get("disabled")
        }
        body = self._body_bytes(request.get("body") or {}, variables)
        started = time.time()
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                response.read(256)
                status = response.getcode()
        except urllib.error.HTTPError as exc:
            status = exc.code
        except Exception as exc:
            return {
                "name": item.get("name", ""),
                "method": method,
                "url": url,
                "ok": False,
                "status": "ERR",
                "duration_ms": round((time.time() - started) * 1000, 1),
                "error": str(exc)[:300],
            }
        return {
            "name": item.get("name", ""),
            "method": method,
            "url": url,
            "ok": 200 <= int(status) < 400,
            "status": int(status),
            "duration_ms": round((time.time() - started) * 1000, 1),
        }

    def _url_to_string(self, url: Any) -> str:
        if isinstance(url, str):
            return url
        if isinstance(url, dict):
            if url.get("raw"):
                return str(url["raw"])
            protocol = url.get("protocol") or "http"
            host = ".".join(url.get("host") or [])
            path = "/".join(url.get("path") or [])
            query = url.get("query") or []
            qs = "&".join(f"{q.get('key')}={q.get('value', '')}" for q in query if q.get("key"))
            return f"{protocol}://{host}/{path}" + (f"?{qs}" if qs else "")
        return ""

    def _body_bytes(self, body: Dict[str, Any], variables: Optional[Dict[str, str]] = None) -> Optional[bytes]:
        mode = body.get("mode")
        if mode == "raw":
            raw = body.get("raw")
            raw = self._substitute(raw, variables or {})
            return raw.encode("utf-8") if raw is not None else None
        return None

    def _variables_from_payload(self, payload: Dict[str, Any]) -> Dict[str, str]:
        variables = {}
        for item in payload.get("variable") or []:
            if item.get("key") and item.get("value") is not None:
                variables[str(item["key"])] = str(item["value"])
        return variables

    def _variables_from_environment(self, path: str) -> Dict[str, str]:
        env_path = Path(path).expanduser()
        payload = json.loads(env_path.read_text(encoding="utf-8"))
        values = payload.get("values") or payload.get("variable") or []
        variables = {}
        for item in values:
            if item.get("key") and item.get("value") is not None and not item.get("disabled"):
                variables[str(item["key"])] = str(item["value"])
        return variables

    def _substitute(self, value: Any, variables: Dict[str, str]) -> str:
        text = "" if value is None else str(value)
        for key, replacement in variables.items():
            text = text.replace("{{" + key + "}}", replacement)
        return text


class SQLWorkbench:
    """Generate and optionally execute SQL checks."""

    def build(self, text: str) -> Dict[str, Any]:
        sql_match = re.search(r"(select|insert|update|delete)\s+.+", text, re.I | re.S)
        if sql_match:
            sql = sql_match.group(0).strip().rstrip(";") + ";"
        else:
            table = self._extract_after(text, ["表", "table"]) or "your_table"
            if any(term in text.lower() for term in ["insert", "新增", "插入"]):
                sql = f"INSERT INTO {table} (column_name) VALUES ('value');"
            elif any(term in text.lower() for term in ["update", "修改", "更新"]):
                sql = f"UPDATE {table} SET column_name='value' WHERE id=1;"
            elif any(term in text.lower() for term in ["delete", "删除"]):
                sql = f"DELETE FROM {table} WHERE id=1;"
            else:
                sql = f"SELECT * FROM {table} LIMIT 20;"
        return {"sql": sql, "readonly": sql.strip().lower().startswith("select")}

    def execute(self, sql: str, config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import pymysql  # type: ignore
        except Exception as exc:
            return {"ok": False, "error": f"pymysql 未安装，无法执行 SQL: {exc}", "sql": sql}
        try:
            conn = pymysql.connect(
                host=config.get("host", "localhost"),
                port=int(config.get("port", 3306)),
                user=config.get("user", "root"),
                password=config.get("password", ""),
                database=config.get("database", ""),
                charset="utf8mb4",
                connect_timeout=5,
            )
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql)
                    rows = cursor.fetchall() if sql.strip().lower().startswith("select") else []
                    if not rows:
                        conn.commit()
                    return {"ok": True, "rows": rows, "rowcount": cursor.rowcount, "sql": sql}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sql": sql}

    def _extract_after(self, text: str, keys: List[str]) -> str:
        for key in keys:
            match = re.search(rf"{re.escape(key)}\s*[:：]?\s*([\w.-]+)", text, re.I)
            if match:
                return match.group(1)
        return ""


class JMeterExporter:
    """Export a practical JMeter JMX load-test plan."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else TESTFORGE_HOME / "jmeter"

    def export(
        self,
        url: str,
        name: str = "load-test",
        threads: int = 10,
        loops: int = 10,
        expected_status: int = 200,
        csv_path: str = "",
        max_duration_ms: int = 5000,
    ) -> Path:
        parsed = urlparse(url)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self.base_dir / f"{_safe_name(name)}.jmx"
        result_path = path.with_suffix(".jtl")
        root = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter="5.6.3")
        root_tree = ET.SubElement(root, "hashTree")

        test_plan = ET.SubElement(
            root_tree,
            "TestPlan",
            guiclass="TestPlanGui",
            testclass="TestPlan",
            testname=name,
            enabled="true",
        )
        self._string(test_plan, "TestPlan.comments", "Generated by TestForge")
        self._bool(test_plan, "TestPlan.functional_mode", False)
        self._bool(test_plan, "TestPlan.tearDown_on_shutdown", True)
        self._bool(test_plan, "TestPlan.serialize_threadgroups", False)
        variables = ET.SubElement(
            test_plan,
            "elementProp",
            name="TestPlan.user_defined_variables",
            elementType="Arguments",
            guiclass="ArgumentsPanel",
            testclass="Arguments",
            testname="User Defined Variables",
            enabled="true",
        )
        ET.SubElement(variables, "collectionProp", name="Arguments.arguments")
        self._string(test_plan, "TestPlan.user_define_classpath", "")
        plan_tree = ET.SubElement(root_tree, "hashTree")

        defaults = ET.SubElement(
            plan_tree,
            "ConfigTestElement",
            guiclass="HttpDefaultsGui",
            testclass="ConfigTestElement",
            testname="HTTP Request Defaults",
            enabled="true",
        )
        self._empty_args(defaults, "HTTPsampler.Arguments")
        self._string(defaults, "HTTPSampler.domain", parsed.hostname or "")
        self._string(defaults, "HTTPSampler.port", str(parsed.port or ""))
        self._string(defaults, "HTTPSampler.protocol", parsed.scheme or "http")
        self._string(defaults, "HTTPSampler.contentEncoding", "UTF-8")
        self._string(defaults, "HTTPSampler.connect_timeout", "10000")
        self._string(defaults, "HTTPSampler.response_timeout", str(max_duration_ms))
        ET.SubElement(plan_tree, "hashTree")

        headers = ET.SubElement(
            plan_tree,
            "HeaderManager",
            guiclass="HeaderPanel",
            testclass="HeaderManager",
            testname="HTTP Header Manager",
            enabled="true",
        )
        header_collection = ET.SubElement(headers, "collectionProp", name="HeaderManager.headers")
        self._header(header_collection, "User-Agent", "TestForge-JMeter/1.0")
        self._header(header_collection, "Accept", "*/*")
        ET.SubElement(plan_tree, "hashTree")

        cookie_manager = ET.SubElement(
            plan_tree,
            "CookieManager",
            guiclass="CookiePanel",
            testclass="CookieManager",
            testname="HTTP Cookie Manager",
            enabled="true",
        )
        ET.SubElement(cookie_manager, "collectionProp", name="CookieManager.cookies")
        self._bool(cookie_manager, "CookieManager.clearEachIteration", False)
        self._bool(cookie_manager, "CookieManager.controlledByThreadGroup", False)
        ET.SubElement(plan_tree, "hashTree")

        cache_manager = ET.SubElement(
            plan_tree,
            "CacheManager",
            guiclass="CacheManagerGui",
            testclass="CacheManager",
            testname="HTTP Cache Manager",
            enabled="true",
        )
        self._bool(cache_manager, "clearEachIteration", False)
        self._bool(cache_manager, "useExpires", True)
        self._bool(cache_manager, "CacheManager.controlledByThread", False)
        ET.SubElement(plan_tree, "hashTree")

        thread_group = ET.SubElement(
            plan_tree,
            "ThreadGroup",
            guiclass="ThreadGroupGui",
            testclass="ThreadGroup",
            testname="Thread Group",
            enabled="true",
        )
        self._string(thread_group, "ThreadGroup.on_sample_error", "continue")
        controller = ET.SubElement(
            thread_group,
            "elementProp",
            name="ThreadGroup.main_controller",
            elementType="LoopController",
            guiclass="LoopControlPanel",
            testclass="LoopController",
            testname="Loop Controller",
            enabled="true",
        )
        self._bool(controller, "LoopController.continue_forever", False)
        self._string(controller, "LoopController.loops", str(loops))
        self._string(thread_group, "ThreadGroup.num_threads", str(threads))
        self._string(thread_group, "ThreadGroup.ramp_time", "5")
        self._bool(thread_group, "ThreadGroup.scheduler", False)
        self._string(thread_group, "ThreadGroup.duration", "")
        self._string(thread_group, "ThreadGroup.delay", "")
        thread_tree = ET.SubElement(plan_tree, "hashTree")

        if csv_path:
            csv_dataset = ET.SubElement(
                thread_tree,
                "CSVDataSet",
                guiclass="TestBeanGUI",
                testclass="CSVDataSet",
                testname="CSV Data Set",
                enabled="true",
            )
            self._string(csv_dataset, "filename", csv_path)
            self._string(csv_dataset, "fileEncoding", "UTF-8")
            self._string(csv_dataset, "variableNames", "value")
            self._bool(csv_dataset, "ignoreFirstLine", False)
            self._string(csv_dataset, "delimiter", ",")
            self._bool(csv_dataset, "quotedData", False)
            self._bool(csv_dataset, "recycle", True)
            self._bool(csv_dataset, "stopThread", False)
            self._string(csv_dataset, "shareMode", "shareMode.all")
            ET.SubElement(thread_tree, "hashTree")

        timer = ET.SubElement(
            thread_tree,
            "ConstantTimer",
            guiclass="ConstantTimerGui",
            testclass="ConstantTimer",
            testname="Think Time 300ms",
            enabled="true",
        )
        self._string(timer, "ConstantTimer.delay", "300")
        ET.SubElement(thread_tree, "hashTree")

        sampler = ET.SubElement(
            thread_tree,
            "HTTPSamplerProxy",
            guiclass="HttpTestSampleGui",
            testclass="HTTPSamplerProxy",
            testname=f"{parsed.path or '/'} GET",
            enabled="true",
        )
        self._empty_args(sampler, "HTTPsampler.Arguments")
        self._string(sampler, "HTTPSampler.domain", parsed.hostname or "")
        self._string(sampler, "HTTPSampler.port", str(parsed.port or ""))
        self._string(sampler, "HTTPSampler.protocol", parsed.scheme or "http")
        self._string(sampler, "HTTPSampler.contentEncoding", "UTF-8")
        self._string(sampler, "HTTPSampler.path", (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else ""))
        self._string(sampler, "HTTPSampler.method", "GET")
        self._bool(sampler, "HTTPSampler.follow_redirects", True)
        self._bool(sampler, "HTTPSampler.auto_redirects", False)
        self._bool(sampler, "HTTPSampler.use_keepalive", True)
        self._bool(sampler, "HTTPSampler.DO_MULTIPART_POST", False)
        self._string(sampler, "HTTPSampler.embedded_url_re", "")
        self._string(sampler, "HTTPSampler.connect_timeout", "10000")
        self._string(sampler, "HTTPSampler.response_timeout", str(max_duration_ms))
        sampler_tree = ET.SubElement(thread_tree, "hashTree")

        assertion = ET.SubElement(
            sampler_tree,
            "ResponseAssertion",
            guiclass="AssertionGui",
            testclass="ResponseAssertion",
            testname=f"Response Code {expected_status}",
            enabled="true",
        )
        collection = ET.SubElement(assertion, "collectionProp", name="Asserion.test_strings")
        ET.SubElement(collection, "stringProp", name=str(expected_status)).text = str(expected_status)
        self._string(assertion, "Assertion.custom_message", "")
        self._string(assertion, "Assertion.test_field", "Assertion.response_code")
        self._bool(assertion, "Assertion.assume_success", False)
        self._int(assertion, "Assertion.test_type", 8)
        ET.SubElement(sampler_tree, "hashTree")

        duration = ET.SubElement(
            sampler_tree,
            "DurationAssertion",
            guiclass="DurationAssertionGui",
            testclass="DurationAssertion",
            testname=f"Duration <= {max_duration_ms}ms",
            enabled="true",
        )
        self._string(duration, "DurationAssertion.duration", str(max_duration_ms))
        ET.SubElement(sampler_tree, "hashTree")

        self._result_collector(thread_tree, "Summary Report", "SummaryReport", "")
        self._result_collector(thread_tree, "Aggregate Report", "StatVisualizer", "")
        self._result_collector(thread_tree, "Simple Data Writer", "SimpleDataWriter", str(result_path))
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        return path

    def _string(self, parent: ET.Element, name: str, value: str) -> ET.Element:
        node = ET.SubElement(parent, "stringProp", name=name)
        node.text = value
        return node

    def _bool(self, parent: ET.Element, name: str, value: bool) -> ET.Element:
        node = ET.SubElement(parent, "boolProp", name=name)
        node.text = "true" if value else "false"
        return node

    def _int(self, parent: ET.Element, name: str, value: int) -> ET.Element:
        node = ET.SubElement(parent, "intProp", name=name)
        node.text = str(value)
        return node

    def _empty_args(self, parent: ET.Element, name: str) -> ET.Element:
        args = ET.SubElement(
            parent,
            "elementProp",
            name=name,
            elementType="Arguments",
            guiclass="HTTPArgumentsPanel",
            testclass="Arguments",
            testname="User Defined Variables",
            enabled="true",
        )
        ET.SubElement(args, "collectionProp", name="Arguments.arguments")
        return args

    def _header(self, collection: ET.Element, name: str, value: str) -> ET.Element:
        header = ET.SubElement(collection, "elementProp", name="", elementType="Header")
        self._string(header, "Header.name", name)
        self._string(header, "Header.value", value)
        return header

    def _result_collector(self, parent: ET.Element, testname: str, guiclass: str, filename: str) -> None:
        collector = ET.SubElement(
            parent,
            "ResultCollector",
            guiclass=guiclass,
            testclass="ResultCollector",
            testname=testname,
            enabled="true",
        )
        self._bool(collector, "ResultCollector.error_logging", False)
        obj = ET.SubElement(collector, "objProp")
        ET.SubElement(obj, "name").text = "saveConfig"
        value = ET.SubElement(obj, "value", attrib={"class": "SampleSaveConfiguration"})
        for prop in (
            "time",
            "latency",
            "timestamp",
            "success",
            "label",
            "code",
            "message",
            "threadName",
            "dataType",
            "encoding",
            "assertions",
            "subresults",
            "responseData",
            "samplerData",
            "xml",
            "fieldNames",
            "responseHeaders",
            "requestHeaders",
            "responseDataOnError",
            "saveAssertionResultsFailureMessage",
            "assertionsResultsToSave",
            "bytes",
            "sentBytes",
            "url",
            "threadCounts",
            "idleTime",
            "connectTime",
        ):
            enabled = prop not in {"responseData", "samplerData", "responseHeaders", "requestHeaders"}
            self._bool(value, prop, enabled)
        self._string(collector, "filename", filename)
        ET.SubElement(parent, "hashTree")


class EnvironmentInspector:
    """Run safe environment discovery commands for test engineers."""

    COMMANDS = {
        "linux": [["uname", "-a"], ["whoami"]],
        "docker": [["docker", "ps"], ["docker", "images"]],
        "k8s": [["kubectl", "get", "nodes"], ["kubectl", "get", "pods", "-A"]],
        "git": [["git", "status", "--short"], ["git", "branch", "--show-current"]],
    }

    def inspect(self, scope: str = "all", cwd: str = ".") -> Dict[str, Any]:
        selected: List[List[str]] = []
        lower = (scope or "all").lower()
        for key, commands in self.COMMANDS.items():
            if lower == "all" or key in lower:
                selected.extend(commands)
        if not selected:
            selected = self.COMMANDS["git"]
        results = []
        for command in selected:
            results.append(self._run(command, cwd=cwd))
        return {"scope": scope, "results": results, "checked_at": _now()}

    def logs(self, target: str, kind: str = "docker", cwd: str = ".") -> Dict[str, Any]:
        target = (target or "").strip()
        if not target:
            return {"scope": kind, "target": target, "results": [{"ok": False, "error": "missing target"}], "checked_at": _now()}
        if (kind or "").lower() in {"k8s", "kubectl", "pod"}:
            command = ["kubectl", "logs", target, "--tail=120"]
        else:
            command = ["docker", "logs", "--tail", "120", target]
        return {"scope": kind, "target": target, "results": [self._run(command, cwd=cwd)], "checked_at": _now()}

    def _run(self, command: List[str], cwd: str) -> Dict[str, Any]:
        started = time.time()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            return {
                "command": " ".join(command),
                "ok": completed.returncode == 0,
                "returncode": completed.returncode,
                "duration_ms": round((time.time() - started) * 1000, 1),
                "stdout": (completed.stdout or "")[-2000:],
                "stderr": (completed.stderr or "")[-1000:],
            }
        except FileNotFoundError:
            return {"command": " ".join(command), "ok": False, "error": "command not found"}
        except Exception as exc:
            return {"command": " ".join(command), "ok": False, "error": str(exc)}


class RegressionComparer:
    """Compare the current session with a saved session snapshot."""

    def compare(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        prev_events = previous.get("events") or []
        curr_events = current.get("events") or []
        prev_failures = self._failures(prev_events)
        curr_failures = self._failures(curr_events)
        prev_features = set(previous.get("tested_features") or [])
        curr_features = set(current.get("tested_features") or [])
        prev_pages = set(previous.get("page_history") or [])
        curr_pages = set(current.get("page_history") or [])
        prev_perf = self._latest_metric(previous, "performance")
        curr_perf = self._latest_metric(current, "performance")
        return {
            "previous_session": previous.get("session_name", ""),
            "current_session": current.get("session_name", ""),
            "previous_failures": len(prev_failures),
            "current_failures": len(curr_failures),
            "new_failures": max(0, len(curr_failures) - len(prev_failures)),
            "fixed_failures": max(0, len(prev_failures) - len(curr_failures)),
            "new_tested_features": sorted(curr_features - prev_features),
            "missing_tested_features": sorted(prev_features - curr_features),
            "new_pages": sorted(curr_pages - prev_pages),
            "missing_pages": sorted(prev_pages - curr_pages),
            "performance_delta": self._metric_delta(prev_perf, curr_perf),
            "compared_at": _now(),
        }

    def _failures(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            event for event in events
            if event.get("data", {}).get("result_type") == "failure"
            or "失败" in str(event.get("text", ""))
            or "failed" in str(event.get("text", "")).lower()
        ]

    def _latest_metric(self, session: Dict[str, Any], kind: str) -> Dict[str, Any]:
        events = session.get("events") or []
        for event in reversed(events):
            data = event.get("data") or {}
            if kind == "performance" and ("performance" in str(event.get("text", "")).lower() or "性能" in str(event.get("text", ""))):
                if isinstance(data, dict):
                    return data
        return {}

    def _metric_delta(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key in ("score", "load_ms", "fcp_ms", "ttfb_ms", "p95_ms"):
            old = previous.get(key)
            new = current.get(key)
            if isinstance(old, (int, float)) and isinstance(new, (int, float)):
                result[key] = {"previous": old, "current": new, "delta": round(new - old, 2)}
        return result


__all__ = [
    "DefectManager",
    "EnvironmentInspector",
    "JMeterExporter",
    "ManagedTestCase",
    "PostmanCollectionRunner",
    "RegressionComparer",
    "SQLWorkbench",
    "TestCaseManager",
]
