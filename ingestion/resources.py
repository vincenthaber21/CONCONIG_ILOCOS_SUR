"""Import/export for ingestion admin models."""

from import_export import resources

from .models import IngestedRow


class IngestedRowResource(resources.ModelResource):
    class Meta:
        model = IngestedRow
        fields = ('id', 'external_id', 'event_type', 'payload', 'created_at')
        export_order = fields
        import_id_fields = ('external_id',)
