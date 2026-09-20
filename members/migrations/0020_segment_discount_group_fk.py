# Link segment rules to inventory.ProductDiscountGroup (editable display name).

import django.db.models.deletion
from django.db import migrations, models


def map_segment_discount_group_to_fk(apps, schema_editor):
    Rule = apps.get_model('members', 'SegmentProductGroupDiscount')
    Group = apps.get_model('inventory', 'ProductDiscountGroup')
    lookup = {g.code: g.pk for g in Group.objects.all()}
    for row in Rule.objects.iterator():
        code = (getattr(row, 'discount_group', None) or '').strip()
        gid = lookup.get(code)
        if gid is None:
            raise RuntimeError(
                f'SegmentProductGroupDiscount id={row.pk} has unknown discount_group code={code!r}. '
                'Fix data or add a matching ProductDiscountGroup row.'
            )
        row.discount_group_new_id = gid
        row.save(update_fields=['discount_group_new_id'])


def noop_reverse(apps, schema_editor):
    pass



class Migration(migrations.Migration):

    dependencies = [
        ('members', '0019_segment_discount_groups'),
        ('inventory', '0008_product_discount_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='segmentproductgroupdiscount',
            name='discount_group_new',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='segment_discount_rules_new',
                to='inventory.productdiscountgroup',
            ),
        ),
        migrations.RunPython(map_segment_discount_group_to_fk, noop_reverse),
        # Drop unique_together first: MariaDB errors with
        # "Key column 'discount_group' doesn't exist" if DROP COLUMN runs while
        # the composite unique index still references the CharField.
        migrations.AlterUniqueTogether(
            name='segmentproductgroupdiscount',
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name='segmentproductgroupdiscount',
            name='discount_group',
        ),
        migrations.RenameField(
            model_name='segmentproductgroupdiscount',
            old_name='discount_group_new',
            new_name='discount_group',
        ),
        migrations.AlterField(
            model_name='segmentproductgroupdiscount',
            name='discount_group',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='segment_discount_rules',
                to='inventory.productdiscountgroup',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='segmentproductgroupdiscount',
            unique_together={('segment', 'discount_group')},
        ),
    ]
