from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0022_blog_toc_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='storyview',
            name='source',
            field=models.CharField(blank=True, db_index=True, default='direct', max_length=32),
        ),
    ]
