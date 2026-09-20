from django.db import migrations


def seed_loan_officer_role(apps, schema_editor):
    Role = apps.get_model("members", "Role")
    Role.objects.get_or_create(
        slug="loan_officer",
        defaults={
            "name": "Loan Officer",
            "sort_order": 15,
            "is_active": True,
        },
    )


def remove_loan_officer_role(apps, schema_editor):
    Role = apps.get_model("members", "Role")
    Role.objects.filter(slug="loan_officer").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0023_member_date_joined_editable"),
    ]

    operations = [
        migrations.RunPython(seed_loan_officer_role, remove_loan_officer_role),
    ]
