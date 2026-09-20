from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0017_storeprofile_logo"),
    ]

    operations = [
        migrations.CreateModel(
            name="KioskSessionConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "auto_logout_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="When enabled, users are logged out after a period of inactivity on the kiosk.",
                    ),
                ),
                (
                    "inactivity_minutes",
                    models.PositiveIntegerField(
                        default=50,
                        help_text="Minutes without keyboard, mouse, touch, or scroll activity before logout.",
                    ),
                ),
                (
                    "warning_seconds",
                    models.PositiveIntegerField(
                        default=30,
                        help_text="How many seconds before logout to show the inactivity warning.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Kiosk Session Config",
                "verbose_name_plural": "Kiosk Session Config",
            },
        ),
    ]
