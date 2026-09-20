from __future__ import annotations

from django.core.management.base import BaseCommand

from ingestion.services.batch_buffer import get_batch_buffer


class Command(BaseCommand):
    help = 'Force-flush any rows still held in the in-memory ingestion buffer.'

    def handle(self, *args, **options) -> None:
        flushed = get_batch_buffer().flush(force=True)
        self.stdout.write(self.style.SUCCESS(f'Flushed {flushed} row(s) from buffer.'))
