# Renames the legacy AdvertText model to Announcement and its ad_content
# field to content, preserving the rows. Hand-written because an automatic
# makemigrations run cannot detect a rename non-interactively and would emit
# a destructive DeleteModel + CreateModel instead.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Partner", "0003_advertimage"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="AdvertText",
            new_name="Announcement",
        ),
        migrations.RenameField(
            model_name="announcement",
            old_name="ad_content",
            new_name="content",
        ),
        migrations.AlterField(
            model_name="announcement",
            name="content",
            field=models.CharField(default="", max_length=400),
        ),
    ]
