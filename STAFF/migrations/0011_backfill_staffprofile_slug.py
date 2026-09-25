"""Backfill slug for every StaffProfile row that existed before the slug
field was enforced (see 0010_staffprofile_slug). New rows get their slug
from StaffProfile.save(); this one-off migration gives already-created
staff their /portfolio/<full-name>/ URL instead of leaving them on the
old numeric path, so nothing already indexed or shared 404s after this
deploy. Collisions (two staff sharing a slugified name) get a numeric
suffix, same rule as save().
"""
from django.db import migrations
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    StaffProfile = apps.get_model("STAFF", "StaffProfile")
    taken = set(
        StaffProfile.objects.exclude(slug__isnull=True)
        .exclude(slug="")
        .values_list("slug", flat=True)
    )
    for profile in StaffProfile.objects.filter(slug__isnull=True).only("id", "full_name"):
        base = slugify(profile.full_name) or f"staff-{profile.pk}"
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        taken.add(candidate)
        StaffProfile.objects.filter(pk=profile.pk).update(slug=candidate)


def noop_reverse(apps, schema_editor):
    """Slugs are additive; nothing to undo on rollback."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("STAFF", "0010_staffprofile_slug"),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, noop_reverse),
    ]
