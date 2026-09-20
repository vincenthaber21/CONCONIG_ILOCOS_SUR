from django.db import migrations


def seed_regular_savings_product(apps, schema_editor):
    SavingsProduct = apps.get_model("savings", "SavingsProduct")
    if SavingsProduct.objects.filter(
        is_active=True,
        product_type="regular",
    ).exists():
        return

    product = SavingsProduct.objects.filter(code="regular-savings").first()
    if product is None:
        product = (
            SavingsProduct.objects.filter(product_type="regular")
            .order_by("created_at")
            .first()
        )

    if product is None:
        SavingsProduct.objects.create(
            name="Regular Savings",
            code="regular-savings",
            product_type="regular",
            description="Passbook regular savings for cooperative members.",
            interest_rate="5.000",
            compounding="annually",
            min_opening_deposit="1000.00",
            max_balance="1000000.00",
            term_months=0,
            min_maintaining_balance="0.00",
            min_additional_deposit="0.00",
            allows_withdrawal=True,
            withdrawal_notice_days=0,
            max_free_withdrawals_per_month=0,
            early_withdrawal_penalty_percent="0.000",
            dividend_eligible=False,
            required_for_membership=False,
            is_active=True,
        )
        return

    product.is_active = True
    product.product_type = "regular"
    product.save(update_fields=["is_active", "product_type", "updated_at"])


def noop_reverse(apps, schema_editor):
    # Keep the product — accounts may already reference it.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0005_membersavingsaccount_product_cascade"),
    ]

    operations = [
        migrations.RunPython(seed_regular_savings_product, noop_reverse),
    ]
