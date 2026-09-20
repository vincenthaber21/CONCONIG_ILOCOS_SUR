"""Shared import-export widgets for bulk data transfer."""

from django.core.exceptions import ObjectDoesNotExist
from import_export.widgets import ForeignKeyWidget


class LenientForeignKeyWidget(ForeignKeyWidget):
    """
    Like ForeignKeyWidget, but missing related rows become None
    instead of raising DoesNotExist (so imports continue).
    """

    def clean(self, value, row=None, **kwargs):
        if value is None or str(value).strip() == '':
            return None
        try:
            return super().clean(value, row=row, **kwargs)
        except ObjectDoesNotExist:
            return None
