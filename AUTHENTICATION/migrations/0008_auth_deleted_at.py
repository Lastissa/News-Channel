from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('AUTHENTICATION', '0007_auth_is_ads_staff'),
    ]

    operations = [
        migrations.AddField(
            model_name='auth',
            name='deleted_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
