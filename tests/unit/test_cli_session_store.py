"""
SessionStore tests.
"""

from src.cli.session_store import SessionStore


def test_session_store_redacts_secret_payload():
    store = SessionStore()

    data = store._redact({
        "current_url": "http://example.com",
        "credentials": {"username": "admin", "password": "secret"},
        "nested": [{"token": "abc"}],
    })

    assert data["credentials"]["username"] == "admin"
    assert data["credentials"]["password"] == "***"
    assert data["nested"][0]["token"] == "***"


def test_session_store_safe_name_removes_path_chars():
    assert SessionStore.safe_name('a/b:c*?') == "a_b_c"
