from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('purchasing', '0009_reviewer_completion_authority'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='purchasereport', name='payment_tracking', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='purchasereportitem', name='processed_by', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name='purchasereportitem', name='processed_at', field=models.DateTimeField(blank=True, null=True)),
    ]
