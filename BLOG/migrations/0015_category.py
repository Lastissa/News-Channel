# Hand written (makemigrations is not to be run in this project, per AGENT.MD).
# Creates the Category table that replaces the hardcoded CATEGORY list in
# BLOG/models.py. The table is empty here on purpose: 0016_seed_categories
# fills it, and 0017_alter_blog_category then points Blog.category at it.

import django.core.validators
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0014_alter_blog_category'),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(
                    help_text='Letters, numbers, single spaces or hyphens. Saved in capitals.',
                    max_length=20,
                    validators=[
                        django.core.validators.RegexValidator(
                            message='Use letters, numbers, single spaces or hyphens only.',
                            regex='^[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*$',
                        ),
                    ],
                )),
            ],
            options={
                'verbose_name_plural': 'categories',
                'ordering': ['id'],
                'constraints': [
                    models.UniqueConstraint(
                        Lower('name'),
                        name='unique_category_name_lower',
                        violation_error_message='That category already exists.',
                    ),
                ],
            },
        ),
    ]
