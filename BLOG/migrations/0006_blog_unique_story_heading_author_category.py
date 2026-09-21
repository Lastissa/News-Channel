# Hand written (makemigrations is not to be run in this project, per AGENT.MD).
# Adds the author + case insensitive heading + category uniqueness constraint
# for Blog. NOTE: applying this fails while duplicate rows exist - as of
# writing author 1 has two 'HEADING' posts in GENERAL that must be resolved
# first (delete or rename one).

from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0005_alter_blog_author'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='blog',
            constraint=models.UniqueConstraint(
                Lower('heading'),
                'category',
                'author',
                name='unique_story_heading_author_category',
            ),
        ),
    ]
