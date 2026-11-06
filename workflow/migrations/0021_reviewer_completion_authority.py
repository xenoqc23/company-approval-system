from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('workflow', '0020_completion_leave_corrections_purchase_hints'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='ReviewerCompletionAuthority',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField(default=1)),
                ('leave_users', models.ManyToManyField(blank=True, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
