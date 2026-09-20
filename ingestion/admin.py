from django.contrib import admin
from import_export.admin import ExportMixin

from ingestion.models import IngestedRow
from ingestion.resources import IngestedRowResource


@admin.register(IngestedRow)
class IngestedRowAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [IngestedRowResource]
    list_display = ('id', 'event_type', 'external_id', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('external_id',)
    readonly_fields = ('created_at',)
