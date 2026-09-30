# Hand written (makemigrations is not to be run in this project, per AGENT.MD).
"""Insert the ten categories that used to be hardcoded as CATEGORY in
BLOG/models.py, in their original order (the navbar shows them in id order),
so nothing changes for readers or writers the moment this deploys.

The list is copied here on purpose instead of imported: a migration must keep
producing the same result even after the live code has moved on. Stories that
sit under a category NOT in this list (e.g. SECURITY) are left alone; they
were already "retired" and keep working exactly as before.
"""
from django.db import migrations

ORIGINAL_CATEGORIES = [
    'UNIVERSITY',
    'POLYTECHNIC',
    'ORGANIZATION',
    'JAMB',
    'WAEC',
    'NECO',
    'POSTUTME',
    'SCHOLARSHIP',
    'TECHNOLOGY',
    'GENERAL',
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model('BLOG', 'Category')
    manager = Category.objects.using(schema_editor.connection.alias)
    for name in ORIGINAL_CATEGORIES:
        #   get_or_create: safe to re-run and never duplicates a row an admin already added
        manager.get_or_create(name=name)


def noop_reverse(apps, schema_editor):
    """Reversing 0015 drops the whole table, nothing to undo here."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0015_category'),
    ]

    operations = [
        migrations.RunPython(seed_categories, noop_reverse),
    ]
