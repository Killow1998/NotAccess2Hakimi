"""Web UI assets for hakimi-proxy."""
"""Web UI assets for hakimi-proxy."""

from pathlib import Path

_index_path = Path(__file__).parent / "index.html"
index_html = _index_path.read_text(encoding="utf-8")
