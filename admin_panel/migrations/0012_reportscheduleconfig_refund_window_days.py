from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0011_alter_storeprofile_latitude_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportscheduleconfig',
            name='refund_window_days',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Number of days after purchase that a customer is allowed to request a refund (e.g. 1 = within 24 hours, 3 = within 3 days).',
            ),
        ),
    ]
