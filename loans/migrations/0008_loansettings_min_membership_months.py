from django.db import migrations, models


def copy_membership_months_from_kiosk(apps, schema_editor):
    LoanSettings = apps.get_model("loans", "LoanSettings")
    KioskConfig = apps.get_model("admin_panel", "KioskConfig")

    config = KioskConfig.objects.filter(pk=1).first()
    months = 3
    if config is not None:
        months = int(getattr(config, "loan_min_membership_months", 3) or 3)

    settings_obj, _ = LoanSettings.objects.get_or_create(
        pk=1,
        defaults={"grace_period_days": 0, "min_membership_months": months},
    )
    if settings_obj.min_membership_months != months:
        settings_obj.min_membership_months = months
        settings_obj.save(update_fields=["min_membership_months"])


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0027_kioskconfig_loan_min_membership_months"),
        ("loans", "0007_loansettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="loansettings",
            name="min_membership_months",
            field=models.PositiveIntegerField(
                default=3,
                help_text=(
                    "Minimum months a member must be registered before they can request a loan. "
                    "Example: 3 means a member who joined only 1 week ago cannot apply yet. "
                    "Set to 0 to allow loan requests immediately."
                ),
            ),
        ),
        migrations.RunPython(
            copy_membership_months_from_kiosk,
            migrations.RunPython.noop,
        ),
    ]
