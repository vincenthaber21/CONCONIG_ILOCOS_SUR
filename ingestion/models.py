from __future__ import annotations

from django.db import models


class IngestedRow(models.Model):
    """Durable store for rows accepted via the ingest API pipeline."""

    external_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    event_type = models.CharField(max_length=64, default='generic', db_index=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.event_type}:{self.external_id or self.pk}'
