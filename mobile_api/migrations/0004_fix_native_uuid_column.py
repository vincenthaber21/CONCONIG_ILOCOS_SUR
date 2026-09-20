from django.db import migrations


def use_native_uuid_column(apps, schema_editor):
    """
    Keep the physical column in sync with the UUID representation selected by
    Django's database backend.

    MariaDB 10.7+ has a native UUID type.  A database upgraded from an older
    version can still have the CHAR(32) column created by the original
    migration, while Django sends native 36-character UUID values.
    """
    connection = schema_editor.connection
    if connection.vendor != "mysql" or not connection.features.has_native_uuid_field:
        return

    table = schema_editor.quote_name("mobile_api_memberqrcode")
    column = schema_editor.quote_name("qr_token")
    with connection.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} MODIFY COLUMN {column} UUID NOT NULL")


class Migration(migrations.Migration):
    dependencies = [
        ("mobile_api", "0003_qr_feature"),
    ]

    operations = [
        migrations.RunPython(
            use_native_uuid_column,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
