"""Reusable abstract base models shared across the credit_service apps."""

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Adds self-updating created_at / updated_at timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    """Uses a UUID primary key instead of the default auto-incrementing int."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    """Standard base model: UUID primary key + created/updated timestamps."""

    class Meta:
        abstract = True
