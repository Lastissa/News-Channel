from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ARCHIVE', '0002_archiveimage_width_height'),
    ]

    operations = [
        migrations.AddField(
            model_name='archiveimage',
            name='kind',
            field=models.CharField(choices=[('image', 'Image'), ('file', 'File')], default='image', max_length=5),
        ),
        migrations.AddField(
            model_name='archiveimage',
            name='original_filename',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='archiveimage',
            name='file_size',
            field=models.PositiveIntegerField(default=0, help_text='Bytes. Only set for kind=FILE.'),
        ),
        migrations.AddField(
            model_name='archiveimage',
            name='public_id',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='archiveimage',
            name='resource_type',
            field=models.CharField(default='image', max_length=10),
        ),
        #   width/height were required (no default) since 0002 -- existing
        #   rows already all have real numbers, but new FILE rows need to
        #   be able to save 0/0, so a default is added going forward.
        migrations.AlterField(
            model_name='archiveimage',
            name='width',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='archiveimage',
            name='height',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
