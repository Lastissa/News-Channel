#   HAND WRITTEN MIGRATION (AGENT.MD forbids running makemigrations).
#   Mirrors what Django 6.1.1 generates for the AuthorFollow model added to
#   STAFF.models. Applied manually against db.sqlite3 through
#   django.db.migrations.executor.MigrationExecutor, so it is recorded in
#   django_migrations like any applied migration and must never run again.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('STAFF', '0006_alter_staffprofile_gender'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthorFollow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='author_followers', to='AUTHENTICATION.auth')),
                ('follower', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='author_follows', to='AUTHENTICATION.auth')),
            ],
            options={
                'verbose_name': 'Author follow',
                'verbose_name_plural': 'Author follows',
            },
        ),
        migrations.AddConstraint(
            model_name='authorfollow',
            constraint=models.UniqueConstraint(fields=('follower', 'author'), name='unique_author_follow'),
        ),
    ]
