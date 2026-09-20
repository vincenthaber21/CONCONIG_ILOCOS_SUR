import django.db.models.deletion
from django.db import migrations, models


def seed_roles_and_migrate_members(apps, schema_editor):
    Role = apps.get_model("members", "Role")
    Member = apps.get_model("members", "Member")

    defaults = [
        ("member", "Member", 0),
        ("staff", "Staff", 1),
        ("cashier", "Cashier", 2),
        ("admin", "Admin", 3),
    ]
    slug_to_id = {}
    for slug, name, sort_order in defaults:
        obj, _ = Role.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "sort_order": sort_order, "is_active": True},
        )
        slug_to_id[slug] = obj.pk

    member_fallback_id = slug_to_id["member"]
    for m in Member.objects.all().iterator():
        raw = (m.role or "member").strip().lower()
        rid = slug_to_id.get(raw, member_fallback_id)
        Member.objects.filter(pk=m.pk).update(member_role_id=rid)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("members", "0011_alter_deletedmember_rfid_card_number"),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
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
                ("slug", models.SlugField(max_length=32, unique=True)),
                ("name", models.CharField(max_length=50)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "verbose_name": "Role",
                "verbose_name_plural": "Roles",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AddField(
            model_name="member",
            name="member_role",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="members",
                to="members.role",
            ),
        ),
        migrations.RunPython(seed_roles_and_migrate_members, noop_reverse),
        migrations.RemoveField(
            model_name="member",
            name="role",
        ),
        migrations.AlterField(
            model_name="member",
            name="member_role",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="members",
                to="members.role",
            ),
        ),
    ]
