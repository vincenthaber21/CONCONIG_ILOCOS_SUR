from django.db import migrations, models


def copy_product_interest_rates(apps, schema_editor):
    LoanApplication = apps.get_model("loans", "LoanApplication")
    for application in LoanApplication.objects.select_related("loan_product").iterator():
        product = application.loan_product
        if product is None:
            continue
        application.interest_rate = product.interest_rate
        application.save(update_fields=["interest_rate"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("loans", "0012_loandocumentation_signed_hard_copy"),
    ]

    operations = [
        migrations.AddField(
            model_name="loanapplication",
            name="interest_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                help_text=(
                    "Late-payment interest rate (annual %) for this application. "
                    "Set at apply time; falls back to the loan product rate when blank."
                ),
                max_digits=6,
                null=True,
            ),
        ),
        migrations.RunPython(copy_product_interest_rates, noop_reverse),
    ]
