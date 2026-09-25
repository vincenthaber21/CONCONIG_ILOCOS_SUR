from django.db import migrations, models


def copy_primary_role_to_assigned(apps, schema_editor):
    Member = apps.get_model("members", "Member")
    Through = Member.roles.through
    rows = [
        Through(member_id=member_id, role_id=role_id)
        for member_id, role_id in Member.objects.exclude(member_role_id=None).values_list(
            "id", "member_role_id"
        )
    ]
    if rows:
        Through.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0035_member_project_categories_to_inventory_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="roles",
            field=models.ManyToManyField(
                blank=True,
                help_text="Every role this person may open after login.",
                related_name="assigned_members",
                to="members.role",
            ),
        ),
        migrations.AlterField(
            model_name="memberedithistory",
            name="role",
            field=models.CharField(
                blank=True,
                help_text="Comma-separated role slugs at the time of the edit.",
                max_length=128,
            ),
        ),
        migrations.RunPython(copy_primary_role_to_assigned, noop_reverse),
    ]
