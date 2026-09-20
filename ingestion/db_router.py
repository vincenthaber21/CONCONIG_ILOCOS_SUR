from __future__ import annotations

from typing import Any

PRIMARY_ALIAS = 'primary'


class PrimaryReplicaRouter:
    """
    Route ingestion model writes to the primary database.
    Reads for IngestedRow may use the default (replica) alias when configured.
    """

    ingestion_labels = {'ingestion'}

    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        if model._meta.app_label in self.ingestion_labels:
            return 'default'
        return None

    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        if model._meta.app_label in self.ingestion_labels:
            return PRIMARY_ALIAS
        return None

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        return None

    def allow_migrate(
        self,
        db: str,
        app_label: str,
        model_name: str | None = None,
        **hints: Any,
    ) -> bool | None:
        if app_label in self.ingestion_labels:
            return db in ('default', PRIMARY_ALIAS)
        return None
