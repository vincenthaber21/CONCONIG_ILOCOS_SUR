from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0019_alter_kiosksessionconfig_auto_logout_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="PrinterSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "printer_name",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text=(
                            "Exact printer name in Windows (for example: XP-58 or EPSON TM-T88V). "
                            "Leave blank to use the Windows default printer."
                        ),
                        max_length=120,
                    ),
                ),
                (
                    "paper_size",
                    models.CharField(
                        choices=[
                            ("58mm", "58 mm (narrow roll)"),
                            ("80mm", "80 mm (standard roll)"),
                            ("A4", "A4 (full page)"),
                        ],
                        default="58mm",
                        help_text="Paper size loaded in the receipt printer.",
                        max_length=10,
                    ),
                ),
                (
                    "auto_print_on_load",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "When enabled, receipt pages auto-open the print dialog so staff can print faster."
                        ),
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Printer Settings",
                "verbose_name_plural": "Printer Settings",
            },
        ),
    ]
