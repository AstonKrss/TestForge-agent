"""
QA workbench helper tests.
"""

import json
import shutil
import uuid
from pathlib import Path

from src.cli.qa_workbench import (
    DefectManager,
    JMeterExporter,
    PostmanCollectionRunner,
    RegressionComparer,
    SQLWorkbench,
    TestCaseManager as QATestCaseManager,
)


def _local_tmp() -> Path:
    path = Path("tests") / ".tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_test_case_manager_exports_json_markdown_and_csv():
    tmp_path = _local_tmp()
    manager = QATestCaseManager(tmp_path)
    cases = manager.from_plan([
        {
            "feature": "Login",
            "precondition": "Open login page",
            "steps": ["fill username", "submit"],
            "expected": "Login succeeds",
            "risk": "high",
            "needs_login": False,
        }
    ])

    paths = manager.save("login-cases", cases)

    try:
        assert set(paths) == {"json", "markdown", "csv", "xlsx"}
        assert "Login" in (tmp_path / "login-cases.md").read_text(encoding="utf-8")
        assert json.loads((tmp_path / "login-cases.json").read_text(encoding="utf-8"))["total"] == 1
        assert (tmp_path / "login-cases.xlsx").read_bytes().startswith(b"PK")
        assert manager.load("login-cases")["total"] == 1
        assert manager.list_cases()[0]["name"] == "login-cases"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_test_case_manager_generates_cases_from_requirement_text():
    tmp_path = _local_tmp()
    manager = QATestCaseManager(tmp_path)
    cases = manager.from_requirements("""
# Login
- 用户可以输入账号密码登录
- 必须校验错误密码
""")

    try:
        assert cases
        assert cases[0].module == "Login"
        assert cases[0].priority == "P1"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_defect_manager_creates_markdown_ticket():
    tmp_path = _local_tmp()
    manager = DefectManager(tmp_path)
    defect = manager.create({
            "session_name": "demo",
            "current_url": "http://example.com/login",
            "events": [{"text": "登录失败", "data": {"result_type": "failure"}}],
            "artifacts": ["failure.png"],
        })

    try:
        assert defect["id"].startswith("BUG-")
        assert "登录失败" in defect["actual"]
        assert "failure.png" in Path(defect["path"]).read_text(encoding="utf-8")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_postman_collection_runner_flattens_nested_requests():
    tmp_path = _local_tmp()
    collection = tmp_path / "collection.json"
    collection.write_text(json.dumps({
        "info": {"name": "Demo"},
        "item": [
            {"name": "Folder", "item": [
                {"name": "Ping", "request": {"method": "GET", "url": "http://example.com/ping"}}
            ]}
        ],
    }), encoding="utf-8")
    runner = PostmanCollectionRunner(tmp_path)
    payload = json.loads(collection.read_text(encoding="utf-8"))
    flattened = runner._flatten_items(payload["item"])

    try:
        assert len(flattened) == 1
        assert runner._url_to_string(flattened[0]["request"]["url"]) == "http://example.com/ping"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_postman_collection_runner_substitutes_collection_and_environment_variables():
    tmp_path = _local_tmp()
    collection = tmp_path / "collection.json"
    env = tmp_path / "env.json"
    collection.write_text(json.dumps({
        "variable": [{"key": "base_url", "value": "http://from-collection"}],
        "item": [
            {"name": "Ping", "request": {
                "method": "POST",
                "url": "{{base_url}}/ping",
                "header": [{"key": "X-Token", "value": "{{token}}"}],
                "body": {"mode": "raw", "raw": "{\"token\":\"{{token}}\"}"},
            }}
        ],
    }), encoding="utf-8")
    env.write_text(json.dumps({"values": [
        {"key": "base_url", "value": "http://from-env"},
        {"key": "token", "value": "abc"},
    ]}), encoding="utf-8")
    runner = PostmanCollectionRunner(tmp_path)
    payload = json.loads(collection.read_text(encoding="utf-8"))
    variables = runner._variables_from_payload(payload)
    variables.update(runner._variables_from_environment(str(env)))
    item = runner._flatten_items(payload["item"])[0]

    try:
        assert runner._substitute(runner._url_to_string(item["request"]["url"]), variables) == "http://from-env/ping"
        assert runner._body_bytes(item["request"]["body"], variables) == b'{"token":"abc"}'
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_sql_workbench_builds_templates_and_passes_raw_sql():
    workbench = SQLWorkbench()

    assert workbench.build("select * from users")["sql"] == "select * from users;"
    assert workbench.build("查询 表 users")["sql"] == "SELECT * FROM users LIMIT 20;"
    assert workbench.build("更新 table orders")["sql"].startswith("UPDATE orders")


def test_jmeter_exporter_writes_jmx():
    tmp_path = _local_tmp()
    exporter = JMeterExporter(tmp_path)
    path = exporter.export("http://example.com/api/login", name="api-login", threads=5, loops=3)

    try:
        text = path.read_text(encoding="utf-8")
        assert "HTTPSampler.domain" in text
        assert "example.com" in text
        assert "ResponseAssertion" in text
        assert "api-login" in str(path)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_regression_comparer_counts_failure_delta():
    comparer = RegressionComparer()
    result = comparer.compare(
        {"session_name": "old", "events": [{"text": "failed", "data": {"result_type": "failure"}}], "tested_features": ["A"], "page_history": ["http://x/a"]},
        {"session_name": "new", "events": [], "tested_features": ["A", "B"], "page_history": ["http://x/a", "http://x/b"]},
    )

    assert result["fixed_failures"] == 1
    assert result["new_tested_features"] == ["B"]
    assert result["new_pages"] == ["http://x/b"]


def test_environment_logs_builds_safe_docker_command():
    from src.cli.qa_workbench import EnvironmentInspector

    inspector = EnvironmentInspector()
    inspector._run = lambda command, cwd: {"command": " ".join(command), "ok": True, "stdout": "ok"}

    result = inspector.logs("web", kind="docker")

    assert result["results"][0]["command"] == "docker logs --tail 120 web"
