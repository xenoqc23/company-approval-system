from django.db import migrations


def create_policy(apps,schema_editor):
    # No guessed employee IDs, permission grants or historical document edits.
    apps.get_model('purchasing','PurchasePolicy').objects.using(schema_editor.connection.alias).get_or_create(pk=1)

class Migration(migrations.Migration):
    dependencies=[('purchasing','0007_department_routes')]
    operations=[migrations.RunPython(create_policy,migrations.RunPython.noop)]
