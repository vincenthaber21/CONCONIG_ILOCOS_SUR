from django.db import migrations, models


def set_57mm_for_existing_58mm(apps, schema_editor):
    PrinterSettings = apps.get_model("admin_panel", "PrinterSettings")
    PrinterSettings.objects.filter(paper_size="58mm").update(paper_size="57mm")


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0023_kioskconfig_member_max_credit"),
    ]

    operations = [
        migrations.AlterField(
            model_name="printersettings",
            name="paper_size",
            field=models.CharField(
                choices=[
                    ("57mm", "57 mm (narrow roll)"),
                    ("58mm", "58 mm (narrow roll)"),
                    ("80mm", "80 mm (standard roll)"),
                    ("A4", "A4 (full page)"),
                ],
                default="57mm",
                help_text="Paper size loaded in the receipt printer.",
                max_length=10,
            ),
        ),
        migrations.RunPython(set_57mm_for_existing_58mm, migrations.RunPython.noop),
    ]
