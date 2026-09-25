"""Backfill slug for every Blog row that existed before the slug field was
enforced (see 0010_blog_slug). New rows get their slug from Blog.save();
this one-off migration gives already-published stories the same
/blog/<slug>-<id>/ URL shape instead of leaving them on the old numeric
path, so nothing already indexed or shared 404s after this deploy.
"""
from django.db import migrations
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    Blog = apps.get_model("BLOG", "Blog")
    for blog in Blog.objects.filter(slug__isnull=True).only("id", "heading"):
        base = slugify(blog.heading)[:340] or "story"
        Blog.objects.filter(pk=blog.pk).update(slug=f"{base}-{blog.pk}")


def noop_reverse(apps, schema_editor):
    """Slugs are additive; nothing to undo on rollback."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("BLOG", "0010_blog_slug"),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, noop_reverse),
    ]
