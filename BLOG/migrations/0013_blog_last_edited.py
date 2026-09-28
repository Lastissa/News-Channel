# Written by hand (not generated) because AGENT.MD forbids running makemigrations.
# Run `python manage.py migrate` yourself to apply it.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0012_blog_image_public_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='blog',
            name='last_edited',
            field=models.DateTimeField(blank=True, help_text='SET ONLY WHEN STAFF EDIT THE STORY AFTER PUBLISHING, NULL IF NEVER EDITED', null=True),
        ),
    ]
