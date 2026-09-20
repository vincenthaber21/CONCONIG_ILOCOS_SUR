from __future__ import annotations

import logging
import math
import time
from typing import Any

from celery import chord, group, shared_task
from django.conf import settings
from django.db import transaction

from ingestion.db_router import PRIMARY_ALIAS
from ingestion.models import IngestedRow

logger = logging.getLogger('ingestion.metrics')


def _shard_count() -> int:
    return max(1, int(getattr(settings, 'INGESTION_SHARD_COUNT', 4)))


def split_into_shards(rows: list[dict[str, Any]], shard_count: int) -> list[list[dict[str, Any]]]:
    if not rows:
        return []
    shard_count = min(shard_count, len(rows))
    chunk_size = math.ceil(len(rows) / shard_count)
    return [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]


def _rows_to_instances(rows: list[dict[str, Any]]) -> list[IngestedRow]:
    return [
        IngestedRow(
            external_id=row.get('external_id', '') or '',
            event_type=row.get('event_type', 'generic') or 'generic',
            payload=row.get('payload') or {},
        )
        for row in rows
    ]


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def ingest_shard(self, batch_id: str, rows: list[dict[str, Any]]) -> int:
    """Persist one shard via bulk_create on the primary database."""
    if not rows:
        return 0
    instances = _rows_to_instances(rows)
    batch_size = max(len(instances), 1)
    with transaction.atomic(using=PRIMARY_ALIAS):
        IngestedRow.objects.using(PRIMARY_ALIAS).bulk_create(
            instances,
            batch_size=batch_size,
        )
    return len(instances)


@shared_task
def log_batch_metrics(
    shard_results: list[int],
    batch_id: str,
    row_count: int,
    started_at: float,
) -> dict[str, Any]:
    duration = time.perf_counter() - started_at
    inserted = sum(shard_results)
    rows_per_sec = inserted / duration if duration > 0 else float(inserted)
    logger.info(
        'batch_complete batch_id=%s rows=%s inserted=%s duration_sec=%.4f rows_per_sec=%.2f',
        batch_id,
        row_count,
        inserted,
        duration,
        rows_per_sec,
    )
    return {
        'batch_id': batch_id,
        'rows': row_count,
        'inserted': inserted,
        'duration_sec': duration,
        'rows_per_sec': rows_per_sec,
    }


@shared_task
def process_ingest_batch(batch_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Split a batch across Celery workers; each shard bulk_create's inside atomic()."""
    if not rows:
        return {'batch_id': batch_id, 'rows': 0, 'inserted': 0}

    started_at = time.perf_counter()
    shards = split_into_shards(rows, _shard_count())
    header = group(ingest_shard.s(batch_id, shard) for shard in shards)
    callback = log_batch_metrics.s(batch_id, len(rows), started_at)

    if getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        results = [ingest_shard.run(batch_id, shard) for shard in shards]
        return log_batch_metrics.run(results, batch_id, len(rows), started_at)

    if len(shards) == 1:
        inserted = ingest_shard.run(batch_id, shards[0])
        return log_batch_metrics.run([inserted], batch_id, len(rows), started_at)

    chord(header)(callback)
    return {'batch_id': batch_id, 'rows': len(rows), 'status': 'dispatched'}
