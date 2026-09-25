from django.db import migrations, models


def set_apply_months_from_compounding(apps, schema_editor):
    Product = apps.get_model("savings", "SavingsProduct")
    mapping = {
        "monthly": 1,
        "quarterly": 3,
        "annually": 12,
        "none": 12,
    }
    for product in Product.objects.all():
        product.interest_apply_months = mapping.get(product.compounding or "annually", 12)
        product.save(update_fields=["interest_apply_months"])


class Migration(migrations.Migration):

    dependencies = [
        ("savings", "0007_joint_savings_account"),
    ]

    operations = [
        migrations.AddField(
            model_name="savingsproduct",
            name="interest_apply_months",
            field=models.PositiveIntegerField(
                default=12,
                help_text=(
                    "Credit interest this many months after opening, then on each "
                    "anniversary. 1 = every month, 12 = once a year."
                ),
            ),
        ),
        migrations.RunPython(
            set_apply_months_from_compounding,
            migrations.RunPython.noop,
        ),
    ]
