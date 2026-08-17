"""SQLite-based usage store for traffic metering."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hakimi_proxy.metering.models import UsageRecord


class UsageStore:
    """Thread-safe SQLite store for aggregated usage data."""

    def __init__(self, db_path: str | Path = "hakimi.db") -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS usage ("
                    "  date TEXT NOT NULL,"
                    "  credential_id TEXT NOT NULL,"
                    "  model TEXT NOT NULL,"
                    "  upstream TEXT NOT NULL,"
                    "  input_tokens INTEGER DEFAULT 0,"
                    "  output_tokens INTEGER DEFAULT 0,"
                    "  cache_read_tokens INTEGER DEFAULT 0,"
                    "  cache_write_tokens INTEGER DEFAULT 0,"
                    "  reasoning_tokens INTEGER DEFAULT 0,"
                    "  cost_usd REAL DEFAULT 0.0,"
                    "  request_count INTEGER DEFAULT 0,"
                    "  PRIMARY KEY (date, credential_id, model, upstream)"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS usage_log ("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  ts TEXT NOT NULL,"
                    "  credential_id TEXT NOT NULL,"
                    "  model TEXT NOT NULL,"
                    "  upstream TEXT NOT NULL,"
                    "  input_tokens INTEGER DEFAULT 0,"
                    "  output_tokens INTEGER DEFAULT 0,"
                    "  cache_read_tokens INTEGER DEFAULT 0,"
                    "  cache_write_tokens INTEGER DEFAULT 0,"
                    "  reasoning_tokens INTEGER DEFAULT 0,"
                    "  cost_usd REAL DEFAULT 0.0"
                    ")"
                )
                conn.commit()
            finally:
                conn.close()

    def record(self, rec: UsageRecord) -> None:
        """Upsert a usage record into the aggregated table and log."""
        date_str = rec.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        t = rec.tokens
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO usage (date, credential_id, model, upstream,"
                    "  input_tokens, output_tokens, cache_read_tokens,"
                    "  cache_write_tokens, reasoning_tokens, cost_usd, request_count)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(date, credential_id, model, upstream)"
                    " DO UPDATE SET"
                    "  input_tokens = input_tokens + excluded.input_tokens,"
                    "  output_tokens = output_tokens + excluded.output_tokens,"
                    "  cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens,"
                    "  cache_write_tokens = cache_write_tokens + excluded.cache_write_tokens,"
                    "  reasoning_tokens = reasoning_tokens + excluded.reasoning_tokens,"
                    "  cost_usd = cost_usd + excluded.cost_usd,"
                    "  request_count = request_count + excluded.request_count",
                    (date_str, rec.credential_id, rec.model, rec.upstream,
                     t.input, t.output, t.cache_read, t.cache_write, t.reasoning,
                     rec.cost_usd, rec.request_count),
                )
                conn.execute(
                    "INSERT INTO usage_log (ts, credential_id, model, upstream,"
                    "  input_tokens, output_tokens, cache_read_tokens,"
                    "  cache_write_tokens, reasoning_tokens, cost_usd)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), rec.credential_id,
                     rec.model, rec.upstream, t.input, t.output, t.cache_read,
                     t.cache_write, t.reasoning, rec.cost_usd),
                )
                conn.commit()
            finally:
                conn.close()

    def get_usage(
        self,
        *,
        credential_id: str | None = None,
        model: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query aggregated usage with optional filters."""
        query = "SELECT * FROM usage WHERE 1=1"
        params: list[Any] = []
        if credential_id:
            query += " AND credential_id = ?"
            params.append(credential_id)
        if model:
            query += " AND model = ?"
            params.append(model)
        if start_date:
            query += " AND date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date <= ?"
            params.append(end_date)
        query += " ORDER BY date DESC, credential_id, model"

        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(query, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def get_usage_log(
        self,
        *,
        credential_id: str | None = None,
        model: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query individual usage log entries."""
        query = "SELECT * FROM usage_log WHERE 1=1"
        params: list[Any] = []
        if credential_id:
            query += " AND credential_id = ?"
            params.append(credential_id)
        if model:
            query += " AND model = ?"
            params.append(model)
        if start_date:
            query += " AND ts >= ?"
            params.append(start_date)
        if end_date:
            query += " AND ts <= ?"
            params.append(end_date)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(query, params).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def close(self) -> None:
        pass
