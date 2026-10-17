# Written by hand (not generated) because AGENT.MD forbids running makemigrations.
# Run `python manage.py migrate` yourself to apply it.
#
# Replaces the boolean Blog.show_toc with the choosable Blog.toc_mode. The old
# field only had two meanings (off / a list fully collapsed), so a story that
# had show_toc=True is carried over to TOC_FULL (3), the level that shows the
# whole list open; False (and the field default) maps to TOC_OFF (0).

from django.db import migrations, models


def show_toc_to_mode(apps, schema_editor):
    Blog = apps.get_model('BLOG', 'Blog')
    Blog.objects.filter(show_toc=True).update(toc_mode=3)


class Migration(migrations.Migration):

    dependencies = [
        ('BLOG', '0021_blog_show_toc'),
    ]

    operations = [
        migrations.AddField(
            model_name='blog',
            name='toc_mode',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, 'Off - no contents list'),
                    (1, 'Level 1 - title only'),
                    (2, 'Level 2 - top sections'),
                    (3, 'Level 3 - fully open'),
                ],
                default=0,
                help_text="How the story's table of contents starts out (Off or one of three collapse levels)",
            ),
        ),
        migrations.RunPython(show_toc_to_mode, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='blog',
            name='show_toc',
        ),
    ]
