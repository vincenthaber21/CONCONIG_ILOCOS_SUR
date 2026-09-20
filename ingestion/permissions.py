from __future__ import annotations

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class HasIngestionApiKey(BasePermission):
    """Require X-Ingestion-Key when INGESTION_API_KEY is configured."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        expected = getattr(settings, 'INGESTION_API_KEY', '') or ''
        if not expected:
            return True
        provided = request.headers.get('X-Ingestion-Key', '')
        return provided == expected
