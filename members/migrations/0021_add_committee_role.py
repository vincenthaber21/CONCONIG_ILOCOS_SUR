from django.db import migrations


def seed_committee_role(apps, schema_editor):
    Role = apps.get_model("members", "Role")
    Role.objects.get_or_create(
        slug="committee",
        defaults={
            "name": "Credit Committee",
            "sort_order": 25,
            "is_active": True,
        },
    )


def remove_committee_role(apps, schema_editor):
    Role = apps.get_model("members", "Role")
    Role.objects.filter(slug="committee").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0020_segment_discount_group_fk"),
    ]

    operations = [
        migrations.RunPython(seed_committee_role, remove_committee_role),
    ]
