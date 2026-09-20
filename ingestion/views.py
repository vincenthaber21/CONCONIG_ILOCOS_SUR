from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from ingestion.permissions import HasIngestionApiKey
from ingestion.serializers import IngestBatchSerializer
from ingestion.services.batch_buffer import get_batch_buffer


@api_view(['POST'])
@authentication_classes([])
@permission_classes([HasIngestionApiKey])
def ingest_rows(request: Request) -> Response:
    """
    POST /api/ingest/
    Body: JSON array of row objects.
    """
    serializer = IngestBatchSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    rows = serializer.validated_data
    accepted = len(rows)
    flushed = get_batch_buffer().add_rows(rows)
    return Response(
        {
            'accepted': accepted,
            'flushed': flushed,
            'buffered': accepted if flushed == 0 else 0,
        },
        status=status.HTTP_202_ACCEPTED,
    )
