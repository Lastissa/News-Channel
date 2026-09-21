#   HAND WRITTEN MIGRATION (AGENT.MD forbids running makemigrations).
#   Mirrors exactly what Django 6.1.1 generates for the PasswordResetKey
#   model added to AUTHENTICATION.models. It was applied manually against
#   db.sqlite3 through django.db.migrations.executor.MigrationExecutor,
#   so it is recorded in django_migrations like any applied migration and
#   must never be run again.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('AUTHENTICATION', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PasswordResetKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=6)),
                ('sign', models.CharField(max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='password_reset_key', to='AUTHENTICATION.auth')),
            ],
        ),
    ]
