from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from django.conf import settings

logger = logging.getLogger('ingestion.metrics')

_buffer_singleton: BatchBuffer | None = None
_buffer_lock = threading.Lock()


class BatchBuffer:
    """
    Thread-safe in-memory buffer. Flushes at FLUSH_SIZE rows or every FLUSH_INTERVAL seconds.
    """

    FLUSH_SIZE: int = 1000
    FLUSH_INTERVAL: float = 3.0

    def __init__(self) -> None:
        self.FLUSH_SIZE = int(getattr(settings, 'INGESTION_BUFFER_FLUSH_SIZE', self.FLUSH_SIZE))
        self.FLUSH_INTERVAL = float(
            getattr(settings, 'INGESTION_BUFFER_FLUSH_INTERVAL', self.FLUSH_INTERVAL)
        )
        self._lock = threading.Lock()
        self._rows: list[dict[str, Any]] = []
        self._timer: threading.Timer | None = None
        self._closed = False
        self._schedule_timer()

    def _schedule_timer(self) -> None:
        if self._closed:
            return
        self._timer = threading.Timer(self.FLUSH_INTERVAL, self._on_timer)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_timer(self) -> None:
        try:
            self.flush(force=True)
        finally:
            if not self._closed:
                self._schedule_timer()

    def add_rows(self, rows: list[dict[str, Any]]) -> int:
        """Append rows; flush automatically when the buffer reaches FLUSH_SIZE."""
        if not rows:
            return 0
        with self._lock:
            self._rows.extend(rows)
            if len(self._rows) >= self.FLUSH_SIZE:
                return self._flush_locked()
        return 0

    def flush(self, *, force: bool = False) -> int:
        """Flush buffered rows. When force=True, flush even if below FLUSH_SIZE."""
        with self._lock:
            if not self._rows:
                return 0
            if not force and len(self._rows) < self.FLUSH_SIZE:
                return 0
            return self._flush_locked()

    def _flush_locked(self) -> int:
        batch = self._rows
        self._rows = []
        self._cancel_timer()
        if not self._closed:
            self._schedule_timer()
        if not batch:
            return 0
        self._dispatch(batch)
        return len(batch)

    def _dispatch(self, rows: list[dict[str, Any]]) -> None:
        from ingestion.tasks import process_ingest_batch

        batch_id = str(uuid.uuid4())
        row_count = len(rows)
        started = time.perf_counter()

        process_ingest_batch.delay(batch_id, rows)

        duration = time.perf_counter() - started
        rows_per_sec = row_count / duration if duration > 0 else float(row_count)
        logger.info(
            'batch_dispatched batch_id=%s rows=%s duration_sec=%.4f rows_per_sec=%.2f',
            batch_id,
            row_count,
            duration,
            rows_per_sec,
        )

    def close(self) -> None:
        """Stop the periodic timer (used in tests)."""
        self._closed = True
        self._cancel_timer()


def get_batch_buffer() -> BatchBuffer:
    global _buffer_singleton
    if _buffer_singleton is None:
        with _buffer_lock:
            if _buffer_singleton is None:
                _buffer_singleton = BatchBuffer()
    return _buffer_singleton


def reset_batch_buffer() -> None:
    """Replace the global buffer (tests only)."""
    global _buffer_singleton
    with _buffer_lock:
        if _buffer_singleton is not None:
            _buffer_singleton.close()
        _buffer_singleton = None
