"""
CLI browser tool helper tests.
"""

from src.cli.tools import _summarize_load_samples, _summarize_quality


def test_summarize_load_samples_reports_latency_and_errors():
    summary = _summarize_load_samples(
        [
            {"ok": True, "status": 200, "duration": 100},
            {"ok": True, "status": 200, "duration": 200},
            {"ok": False, "status": 0, "duration": 300, "error": "timeout"},
        ],
        started_at=0,
        finished_at=1,
    )

    assert summary["total"] == 3
    assert summary["failed"] == 1
    assert summary["p95"] == 300
    assert summary["errors"]["timeout"] == 1


def test_summarize_quality_penalizes_basic_issues():
    summary = _summarize_quality({
        "title": "",
        "lang": "",
        "hasViewport": False,
        "h1Count": 0,
        "duplicateIds": ["app"],
        "images": {"missingAlt": 1},
        "forms": {"missingNames": 1, "passwordAutocompleteMissing": 1, "insecureActions": 0},
        "buttons": {"empty": 1},
        "links": {"empty": 1, "javascriptHref": 1, "targetBlankUnsafe": 1},
        "mixedContent": 0,
    })

    assert summary["score"] < 100
    assert summary["issues"]
