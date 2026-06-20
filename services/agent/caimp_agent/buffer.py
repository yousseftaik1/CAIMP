"""
SQLite offline buffer.

When the OTel Collector is unreachable, metric batches are serialised to JSON
and stored locally.  A background task replays them when connectivity returns.

Caps: 50 MB OR 24 h (oldest records pruned first).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS metric_batches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at REAL    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    payload     TEXT    NOT NULL,
    replayed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_captured ON metric_batches (captured_at);
"""


class SQLiteBuffer:
    def __init__(self, path: Path, max_mb: int = 50, max_hours: int = 24) -> None:
        self._path = path
        self._max_bytes = max_mb * 1024 * 1024
        self._max_age = max_hours * 3600
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(self, payload: list[dict]) -> None:
        """Persist a list of metric records to the buffer."""
        blob = json.dumps(payload)
        size = len(blob.encode())
        now = time.time()

        self._conn.execute(
            "INSERT INTO metric_batches (captured_at, size_bytes, payload) VALUES (?,?,?)",
            (now, size, blob),
        )
        self._conn.commit()
        self._enforce_caps()
        log.debug("Buffered %d bytes (batch of %d metrics)", size, len(payload))

    # ------------------------------------------------------------------
    # Read / replay
    # ------------------------------------------------------------------

    def pending_batches(self) -> Iterator[tuple[int, list[dict]]]:
        """Yield (id, payload) tuples for all un-replayed batches, oldest first."""
        rows = self._conn.execute(
            "SELECT id, payload FROM metric_batches "
            "WHERE replayed_at IS NULL ORDER BY captured_at ASC"
        ).fetchall()
        for row_id, blob in rows:
            try:
                yield row_id, json.loads(blob)
            except json.JSONDecodeError:
                self.mark_replayed(row_id)  # discard corrupt record

    def mark_replayed(self, batch_id: int) -> None:
        self._conn.execute(
            "UPDATE metric_batches SET replayed_at=? WHERE id=?",
            (time.time(), batch_id),
        )
        self._conn.commit()

    def pending_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM metric_batches WHERE replayed_at IS NULL"
        ).fetchone()[0]

    # ------------------------------------------------------------------
    # Cap enforcement
    # ------------------------------------------------------------------

    def _enforce_caps(self) -> None:
        now = time.time()
        # Age cap: delete records older than max_hours
        self._conn.execute(
            "DELETE FROM metric_batches WHERE captured_at < ?",
            (now - self._max_age,),
        )
        # Size cap: delete oldest records until total size is within limit
        while True:
            total = self._conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM metric_batches"
            ).fetchone()[0]
            if total <= self._max_bytes:
                break
            oldest_id = self._conn.execute(
                "SELECT id FROM metric_batches ORDER BY captured_at ASC LIMIT 1"
            ).fetchone()
            if oldest_id is None:
                break
            self._conn.execute("DELETE FROM metric_batches WHERE id=?", oldest_id)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
