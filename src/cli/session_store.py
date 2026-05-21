"""
Local session persistence for the interactive CLI.

Sessions are stored under ~/.testforge/sessions as JSON. Passwords and other
secret-looking values are redacted before writing to disk.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


SECRET_KEYS = {"password", "pass", "token", "access_token", "refresh_token", "secret", "api_key", "apikey"}


class SessionStore:
    """Read/write TestForge CLI sessions."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else Path.home() / ".testforge" / "sessions"

    def save(self, name: str, payload: Dict[str, Any]) -> Path:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self.safe_name(name)
        data = self._redact(payload)
        data["session_name"] = name or safe_name
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = self.path_for(safe_name)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, name: str) -> Dict[str, Any]:
        path = self.path_for(self.safe_name(name))
        if not path.exists():
            raise FileNotFoundError(f"会话不存在: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> List[Dict[str, Any]]:
        if not self.base_dir.exists():
            return []
        items: List[Dict[str, Any]] = []
        for path in sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            items.append({
                "name": data.get("session_name") or path.stem,
                "file": str(path),
                "updated_at": data.get("updated_at") or "",
                "current_url": data.get("current_url") or "",
                "tested_features": data.get("tested_features") or [],
            })
        return items

    def path_for(self, safe_name: str) -> Path:
        return self.base_dir / f"{safe_name}.json"

    @staticmethod
    def safe_name(name: str) -> str:
        cleaned = (name or "").strip() or datetime.now().strftime("session-%Y%m%d-%H%M%S")
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", cleaned)
        cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
        return cleaned[:80] or "session"

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: Dict[str, Any] = {}
            for key, item in value.items():
                if str(key).lower() in SECRET_KEYS:
                    redacted[key] = "***"
                else:
                    redacted[key] = self._redact(item)
            return redacted
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value


__all__ = ["SessionStore"]
