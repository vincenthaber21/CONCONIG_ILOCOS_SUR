from __future__ import annotations

from typing import Any

from rest_framework import serializers


class IngestRowSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')
    event_type = serializers.CharField(max_length=64, required=False, default='generic')
    payload = serializers.JSONField(required=False, default=dict)

    def validate_payload(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('payload must be a JSON object.')
        return value


class IngestBatchSerializer(serializers.ListSerializer):
    child = IngestRowSerializer()
    max_length = 10000
    min_length = 1
