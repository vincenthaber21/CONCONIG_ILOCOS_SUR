from django.db import migrations


def enable_palay_utang_defaults(apps, schema_editor):
    PalayCreditSettings = apps.get_model("palay_trade", "PalayCreditSettings")
    PalayTradeProduct = apps.get_model("palay_trade", "PalayTradeProduct")

    settings_obj, _ = PalayCreditSettings.objects.get_or_create(pk=1)
    settings_obj.is_enabled = True
    settings_obj.allow_credit_on_sell = True
    settings_obj.save(update_fields=["is_enabled", "allow_credit_on_sell"])

    PalayTradeProduct.objects.filter(code__in=("rice-palay", "bigas")).update(credit_enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ("palay_trade", "0006_palay_credit"),
    ]

    operations = [
        migrations.RunPython(enable_palay_utang_defaults, migrations.RunPython.noop),
    ]
