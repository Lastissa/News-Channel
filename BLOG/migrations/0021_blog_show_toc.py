# Written by hand (not generated) because AGENT.MD forbids running makemigrations.
# Run `python manage.py migrate` yourself to apply it.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0020_storyview'),
    ]

    operations = [
        migrations.AddField(
            model_name='blog',
            name='show_toc',
            field=models.BooleanField(default=False, help_text='Show a table of contents jump list on the story page'),
        ),
    ]
