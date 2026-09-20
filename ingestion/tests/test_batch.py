from __future__ import annotations

import unittest
from unittest.mock import patch

from django.db import connections
from django.test import TestCase, override_settings

from ingestion.db_router import PRIMARY_ALIAS
from ingestion.models import IngestedRow
from ingestion.services.batch_buffer import get_batch_buffer, reset_batch_buffer
from ingestion.tasks import ingest_shard


def _make_rows(count: int) -> list[dict]:
    return [
        {
            'external_id': f'row-{index}',
            'event_type': 'test_event',
            'payload': {'index': index, 'value': 'sample'},
        }
        for index in range(count)
    ]


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://',
    INGESTION_SHARD_COUNT=4,
    INGESTION_API_KEY='',
    INGESTION_BUFFER_FLUSH_SIZE=50_000,
)
class BatchIngestionQueryTest(TestCase):
    databases = {'default', 'primary'}

    def setUp(self) -> None:
        reset_batch_buffer()
        IngestedRow.objects.using(PRIMARY_ALIAS).all().delete()

    def tearDown(self) -> None:
        reset_batch_buffer()

    def test_ten_thousand_rows_under_twenty_five_queries(self) -> None:
        """10k rows via buffer flush; bulk_create stays in few SQL round-trips."""
        rows = _make_rows(10_000)
        buffer = get_batch_buffer()
        buffer.add_rows(rows)
        ops = connections[PRIMARY_ALIAS].ops

        with patch.object(ops, 'bulk_batch_size', return_value=10_000):
            # Four shards × (BEGIN + bulk INSERT + COMMIT) ≈ 12 queries — well under 25.
            with self.assertNumQueries(12, using=PRIMARY_ALIAS):
                flushed = buffer.flush(force=True)

        self.assertEqual(flushed, 10_000)
        self.assertEqual(IngestedRow.objects.using(PRIMARY_ALIAS).count(), 10_000)

    def test_sharded_bulk_create_uses_primary(self) -> None:
        rows = _make_rows(2_000)
        ops = connections[PRIMARY_ALIAS].ops
        with patch.object(ops, 'bulk_batch_size', return_value=2_000):
            with self.assertNumQueries(3, using=PRIMARY_ALIAS):
                inserted = ingest_shard.run('shard-test', rows)
        self.assertEqual(inserted, 2_000)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CELERY_RESULT_BACKEND='cache+memory://',
    INGESTION_SHARD_COUNT=4,
    INGESTION_API_KEY='test-key',
)
class IngestAPITest(TestCase):
    databases = {'default', 'primary'}

    def setUp(self) -> None:
        reset_batch_buffer()
        IngestedRow.objects.using(PRIMARY_ALIAS).all().delete()

    def tearDown(self) -> None:
        reset_batch_buffer()

    def test_api_accepts_json_array(self) -> None:
        payload = _make_rows(100)
        response = self.client.post(
            '/api/ingest/',
            data=payload,
            content_type='application/json',
            HTTP_X_INGESTION_KEY='test-key',
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['accepted'], 100)


@unittest.skipUnless(
    connections[PRIMARY_ALIAS].vendor == 'mysql',
    'MySQL integration query budget (run without coop_kiosk.test_settings)',
)
class BatchIngestionMySQLIntegrationTest(TestCase):
    """Optional: validates <25 queries on real MySQL when the full test DB migrates."""

    databases = {'default', 'primary'}

    def setUp(self) -> None:
        reset_batch_buffer()
        IngestedRow.objects.using(PRIMARY_ALIAS).all().delete()

    def tearDown(self) -> None:
        reset_batch_buffer()

    def test_mysql_ten_thousand_rows_query_budget(self) -> None:
        rows = _make_rows(10_000)
        buffer = get_batch_buffer()
        buffer.add_rows(rows)
        with self.assertNumQueries(12, using=PRIMARY_ALIAS):
            buffer.flush(force=True)
        self.assertEqual(IngestedRow.objects.using(PRIMARY_ALIAS).count(), 10_000)
