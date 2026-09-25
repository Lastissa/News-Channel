from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ARCHIVE', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='archiveimage',
            name='width',
            #   default only backfills any row created before this field
            #   existed; every new row must pass a real value (see the view).
            field=models.PositiveIntegerField(default=0),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='archiveimage',
            name='height',
            field=models.PositiveIntegerField(default=0),
            preserve_default=False,
        ),
    ]
