# Hand written (makemigrations is not to be run in this project, per AGENT.MD).
# Blog.category no longer lists its choices inline: they come from
# BLOG.models.get_category_choices (the cached Category table). The column
# itself is unchanged, so this touches no data. It is also the LAST time the
# category list can require a migration: adding or removing a category is now
# a row change made from PANEL.

import BLOG.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0016_seed_categories'),
    ]

    operations = [
        migrations.AlterField(
            model_name='blog',
            name='category',
            field=models.CharField(choices=BLOG.models.get_category_choices, max_length=20),
        ),
    ]
