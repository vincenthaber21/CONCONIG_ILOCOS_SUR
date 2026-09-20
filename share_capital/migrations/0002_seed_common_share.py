from decimal import Decimal

from django.db import migrations


def seed_common_share(apps, schema_editor):
    ShareCapitalProduct = apps.get_model("share_capital", "ShareCapitalProduct")
    if ShareCapitalProduct.objects.exists():
        return
    ShareCapitalProduct.objects.create(
        name="Common Share Capital",
        code="common-share",
        description="Paid-up common shares for cooperative members.",
        par_value=Decimal("100.00"),
        min_shares=1,
        max_shares=0,
        min_contribution=Decimal("0.00"),
        dividend_rate=Decimal("0.000"),
        allows_withdrawal=False,
        required_for_membership=True,
        is_active=True,
    )


def unseed_common_share(apps, schema_editor):
    ShareCapitalProduct = apps.get_model("share_capital", "ShareCapitalProduct")
    ShareCapitalProduct.objects.filter(code="common-share").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("share_capital", "0001_share_capital_product_and_audit"),
    ]

    operations = [
        migrations.RunPython(seed_common_share, unseed_common_share),
    ]
