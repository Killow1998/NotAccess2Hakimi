"""Small, bounded, privacy-safe JSONL diagnostic journal."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any


_ALLOWED_FIELDS = frozenset({
    "method",
    "route",
    "status",
    "duration_ms",
    "version",
    "proxy_source",
    "aistudio_credentials",
    "antigravity_credentials",
    "total_credentials",
})


class DiagnosticJournal:
    """Append allowlisted operational facts to private, rotating JSONL files."""

    def __init__(
        self,
        path: str | Path = "state/diagnostics.jsonl",
        *,
        max_bytes: int = 2 * 1024 * 1024,
        backup_count: int = 4,
    ) -> None:
        self.path = Path(path)
        self.max_bytes = max(1024, int(max_bytes))
        self.backup_count = max(1, int(backup_count))
        self._lock = Lock()
        self.enabled = self._prepare_path()

    @property
    def display_path(self) -> str:
        return str(self.path)

    def _prepare_path(self) -> bool:
        try:
            parent = self.path.parent
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if parent.is_symlink() or self.path.is_symlink():
                return False
            parent.chmod(0o700)
            if self.path.exists():
                self.path.chmod(0o600)
            return True
        except OSError:
            return False

    def record(self, event: str, *, level: str = "info", **fields: Any) -> None:
        if not self.enabled:
            return
        safe_fields = {
            key: value
            for key, value in fields.items()
            if key in _ALLOWED_FIELDS and isinstance(value, (str, int, float, bool))
        }
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level if level in {"info", "warning", "error"} else "info",
            "event": str(event)[:80],
            **safe_fields,
        }
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > 16 * 1024:
            return
        try:
            with self._lock:
                self._rotate_if_needed(len(line))
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(self.path, flags, 0o600)
                try:
                    os.fchmod(fd, 0o600)
                    remaining = memoryview(line)
                    while remaining:
                        written = os.write(fd, remaining)
                        remaining = remaining[written:]
                finally:
                    os.close(fd)
        except OSError:
            self.enabled = False

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists() or self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backup_count}")
        if oldest.exists() and not oldest.is_symlink():
            oldest.unlink()
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            target = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists() and not source.is_symlink():
                source.replace(target)
        if not self.path.is_symlink():
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
