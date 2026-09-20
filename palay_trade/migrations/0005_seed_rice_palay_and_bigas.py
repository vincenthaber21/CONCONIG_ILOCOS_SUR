# Seed the fixed catalog: Rice Palay and Bigas only.

from decimal import Decimal

from django.db import migrations
from django.utils import timezone
from django.utils.text import slugify


DEFAULT_PRODUCTS = (
    {
        "code": "rice-palay",
        "name": "Rice Palay",
        "aliases": ("rice-palay", "palay", "rice", "normal-rice", "rice palay"),
        "description": "Unmilled rice (palay) bought from farmers or sold from stock.",
    },
    {
        "code": "bigas",
        "name": "Bigas",
        "aliases": ("bigas", "milled-rice", "milled rice"),
        "description": "Milled rice (bigas) for buy and sell tickets.",
    },
)


def _resolve(apps, spec):
    PalayTradeProduct = apps.get_model("palay_trade", "PalayTradeProduct")
    product = PalayTradeProduct.objects.filter(code=spec["code"]).first()
    if product is None:
        for alias in spec["aliases"]:
            product = (
                PalayTradeProduct.objects.filter(code__iexact=alias).first()
                or PalayTradeProduct.objects.filter(name__iexact=alias).first()
            )
            if product:
                break
    if product is None:
        return PalayTradeProduct.objects.create(
            name=spec["name"],
            code=spec["code"],
            grade="other",
            season="any",
            description=spec["description"],
            buy_price_per_kg=Decimal("0.00"),
            sell_price_per_kg=Decimal("0.00"),
            stock_kg=Decimal("0.00"),
            low_stock_kg=Decimal("0.00"),
            min_quantity_kg=Decimal("0.00"),
            max_quantity_kg=Decimal("0.00"),
            is_active=True,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

    product.name = spec["name"]
    clash = (
        PalayTradeProduct.objects.filter(code=spec["code"]).exclude(pk=product.pk).first()
    )
    if clash is None:
        product.code = spec["code"]
    elif product.code != spec["code"]:
        # Keep existing code if canonical is taken; ensure_default will prefer code match later.
        product.code = slugify(product.code) or product.code
    product.is_active = True
    if not (product.description or "").strip():
        product.description = spec["description"]
    product.updated_at = timezone.now()
    product.save()
    return product


def seed_default_products(apps, schema_editor):
    PalayTradeProduct = apps.get_model("palay_trade", "PalayTradeProduct")
    kept = [_resolve(apps, spec) for spec in DEFAULT_PRODUCTS]
    kept_ids = [p.pk for p in kept]
    PalayTradeProduct.objects.exclude(pk__in=kept_ids).filter(is_active=True).update(
        is_active=False
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("palay_trade", "0004_palayvariety"),
    ]

    operations = [
        migrations.RunPython(seed_default_products, noop_reverse),
    ]
