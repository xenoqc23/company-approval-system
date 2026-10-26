from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('purchasing', '0010_payment_tracking')]
    operations = [
        migrations.AddField(model_name='purchasereport', name='representative_viewed_at', field=models.DateTimeField(blank=True, null=True)),
    ]
