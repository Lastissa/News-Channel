# Hand written to avoid running makemigrations on the project database.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('AUTHENTICATION', '0004_auth_receive_like_alert'),
    ]

    operations = [
        migrations.AddField(
            model_name='usersession',
            name='is_suspicious',
            field=models.BooleanField(db_index=True, default=False, help_text='Login came from a device the account had not used before.'),
        ),
        migrations.CreateModel(
            name='KnownDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fingerprint', models.CharField(db_index=True, help_text='SHA-256 of the login IP + user agent.', max_length=64)),
                ('ip', models.CharField(blank=True, default='', max_length=45)),
                ('user_agent', models.CharField(blank=True, default='', max_length=255)),
                ('first_seen', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('last_seen', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='known_devices', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-last_seen'],
                'unique_together': {('user', 'fingerprint')},
            },
        ),
    ]
