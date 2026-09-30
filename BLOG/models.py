import logging
import re

from django.core.cache import cache
from django.core.validators import RegexValidator
from django.db import DatabaseError, models
from django.db.models.functions import Lower
from django.utils.text import slugify

logger = logging.getLogger(__name__)


#   -------------------------------------------------------------------------
#   NEWS CATEGORIES
#   -------------------------------------------------------------------------
#   These used to be a hardcoded CATEGORY list in this file. Every category is
#   now a row in Category, added and removed by admins / superusers from the
#   PANEL page (ADMIN.views.PanelCategoryCreateView / PanelCategoryDeleteView).
#   The ten original categories are inserted by migration 0016_seed_categories.
#
#   Nothing outside this file should ever query Category to build a menu,
#   a dropdown or a validation set. Call get_category_choices() instead: it
#   reads ONE cache entry that has NO TTL, and that entry is rebuilt from the
#   table (BLOG/signals.py) the moment a Category is added, changed or removed.
#
#   THE CACHE KEY BELOW IS OWNED BY THIS FEATURE ALONE. Do not reuse the
#   string, do not build another key that could equal it, and do not change
#   what is stored under it without bumping the trailing version (v1 -> v2):
#   Redis keeps a no-TTL value across deploys, so a new shape stored under an
#   old key would be served to the new code forever.
CATEGORY_CACHE_KEY = "BLOG.Category::choices::v1"

_CACHE_MISS = object()

category_name_validator = RegexValidator(
    regex=r"^[A-Za-z0-9]+(?:[ -][A-Za-z0-9]+)*$",
    message="Use letters, numbers, single spaces or hyphens only.",
)


class Category(models.Model):
    """One news category. `name` is BOTH the value stored on Blog.category and
    the label readers see (templates title-case it), which is exactly how the
    old hardcoded list behaved: ('JAMB', 'JAMB').

    Stored in capitals and unique regardless of case. Deliberately NOT
    renamable from PANEL: stories keep this text in Blog.category, so a rename
    would orphan them or collide with the unique story constraint. Removing a
    category only retires it (existing stories stay published, see
    HOME.views.EditNewsView `legacy_category`).

    Changes made with QuerySet.update() or bulk_create() bypass the signals
    that refresh the cache. Use save() / delete(), or call
    refresh_category_cache() yourself afterwards.
    """

    #   max_length MUST stay equal to Blog.category.max_length
    name = models.CharField(
        max_length=20,
        validators=[category_name_validator],
        help_text="Letters, numbers, single spaces or hyphens. Saved in capitals.",
    )

    class Meta:
        ordering = ["id"]   #   MENU ORDER = THE ORDER THEY WERE ADDED
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="unique_category_name_lower",
                violation_error_message="That category already exists.",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = " ".join((self.name or "").split()).upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


def _load_category_choices():
    """The only place the Category table is read to build the choices list."""
    return [(name, name) for name in Category.objects.values_list("name", flat=True)]


def _is_choices_list(value):
    return isinstance(value, list) and all(isinstance(item, tuple) and len(item) == 2 for item in value)


def refresh_category_cache():
    """Invalidate the cached categories and store the current ones. Runs after
    every committed Category change (BLOG/signals.py). The stale entry is
    deleted BEFORE the table is read, so if that read ever failed the cache
    would be left empty (the next reader rebuilds it) rather than stale."""
    cache.delete(CATEGORY_CACHE_KEY)
    choices = _load_category_choices()
    cache.set(CATEGORY_CACHE_KEY, choices, timeout=None)   #   timeout=None: NEVER EXPIRES
    return choices


def get_category_choices():
    """[(value, label), ...] for every current category, in menu order.

    Served from the cache; built from the table once when the cache is empty.
    Safe to call while the table does not exist yet (system checks call it
    through Blog.category before `migrate` has created the table): that
    returns [] and, importantly, is NOT cached, otherwise a no-TTL cache would
    remember the empty answer forever.
    """
    cached = cache.get(CATEGORY_CACHE_KEY, _CACHE_MISS)
    #   A value of the wrong shape (foreign write, older version) is treated as a miss and healed.
    if _is_choices_list(cached):
        return cached
    try:
        return refresh_category_cache()
    except DatabaseError:
        logger.warning("BLOG categories could not be read from the database; returning none, nothing cached.")
        return []


class Blog(models.Model):
    image_1 = models.URLField(blank=True, null=True)
    #   THE EXACT CLOUDINARY ASSET `image_1` LIVES AT (blank when image_1 is
    #   a pasted external URL, not an uploaded file -- see AddNewsView).
    #   Kept so a FUTURE "edit story" upload can overwrite THIS SAME asset
    #   in place (SERVICE_INTERNAL.images.upload_news_image `public_id=`)
    #   instead of leaving it behind as an orphan while a brand new file
    #   gets created for the replacement picture -- same pattern already
    #   used by upload_profile_image for avatars.
    image_public_id = models.CharField(max_length=255, blank=True, default="")
    image_info = models.CharField(max_length=100, default="The image is self explanatory.")    #   THE ABOUT PICTURE THHAT WILL SHOW SLIGHTLY BELOW THE PICTURE IN IMAGE 
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='blogs', limit_choices_to= {'is_staff':True})
    category = models.CharField(max_length=20, choices=get_category_choices, blank=False, null=False)
    #   SEO/GEO URL SLUG. GENERATED ONCE FROM `heading` THE FIRST TIME THE STORY
    #   IS SAVED (SEE save() BELOW) AND NEVER TOUCHED AGAIN. IT REPLACES THE OLD
    #   /blog/<id>/ NUMERIC PATH WITH A DESCRIPTIVE /blog/<slug>-<id>/ PATH.
    slug = models.SlugField(max_length=350, blank=True, null=True, unique=True)

    #   -----------------------------------------------------------------
    #   NEVER ALLOW THIS FIELD TO BE EDITED AFTER THE STORY IS PUBLISHED.
    #   ------------------------------------------------------------------
    #   `slug` above is derived from `heading` exactly once, on first save,
    #   and the public story URL is built from that slug (e.g.
    #   /blog/how-to-pass-jamb-2026-104/). If `heading` is changed later:
    #     1. The slug stays stale and the URL no longer describes the
    #        story, which is the exact opposite of the SEO improvement
    #        this field exists for.
    #     2. Every already-indexed search result, shared social link and
    #        external backlink pointing at the old slug still resolves
    #        (the id suffix keeps it working), but now shows a title that
    #        no longer matches the story, hurting click-through rate and
    #        trust signals for both classic SEO and GEO (generative
    #        engines quoting a title that no longer matches the page).
    #     3. Silently regenerating the slug on every title edit is worse:
    #        it breaks every previously shared/indexed link outright.
    #   So: do NOT add an admin action, view, form field or API endpoint
    #   that lets `heading` be edited once a story has a slug. If the
    #   heading truly has a typo, that is a deliberate delete-and-repost
    #   decision, not a quiet edit.
    heading = models.CharField(max_length=100, blank=False, null=False)
    content = models.TextField(blank=False, null=False)
    views = models.PositiveIntegerField(default=0, db_index=True)
    likes = models.PositiveIntegerField(default=0)
    non_anonymous_viewer = models.ManyToManyField("AUTHENTICATION.Auth", related_name="non_anonymous_viewer", blank=True)   #   TRACKIG THE PEOPLE WHO VEIWED SO I CAN CREATE THEIR HISTORY
    last_updated = models.DateTimeField(auto_now=True, blank=True, null=True, help_text="CHANGES ANYTIME UPDATES IS MADE")
    #   SET ONLY BY HOME.views.EditNewsView WHEN A STAFF MEMBER ACTUALLY EDITS A
    #   PUBLISHED STORY, AND NULL FOR A STORY THAT WAS NEVER EDITED. `last_updated`
    #   above cannot answer "was this story edited?" because auto_now fills it in
    #   at creation too (and the migration that added it stamped every older row
    #   with one shared timestamp), so it is never null. The "this post was last
    #   updated ..." notice on the story page keys off this field instead.
    last_edited = models.DateTimeField(blank=True, null=True, help_text="SET ONLY WHEN STAFF EDIT THE STORY AFTER PUBLISHING, NULL IF NEVER EDITED")
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [

            models.UniqueConstraint(
                Lower("heading"),
                "category",
                "author",
                name="unique_story_heading_author_category",
            ),
        ]
    
    def save(self, *args, **kwargs):
        """Generate `slug` once, the first time the story is saved.

        The slug is `slugify(heading)` plus the row's own id
        (story/slug-slug-slug-<id>), so it is always unique without a
        collision-retry loop and it is stable forever: the id half never
        changes, so an old shared/indexed link never breaks. Existing rows
        already have a slug and are left untouched, and this never re-runs
        just because `heading` was edited (see the note on `heading`
        above for why title edits should not happen at all).
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.slug:
            base = slugify(self.heading)[:340] or "story"
            Blog.objects.filter(pk=self.pk).update(slug=f"{base}-{self.pk}")
            self.slug = f"{base}-{self.pk}"

    @property
    def edited_gap_label(self):
        """How long after first publication the last edit happened, worded for
        the story page notice: "5 minutes", "3 hours", "2 days", "1 week".
        Under a week it is minutes / hours / days, from a week on it is whole
        weeks. Empty string when the story was never edited."""
        if not self.last_edited or not self.date_created:
            return ""

        seconds = max(int((self.last_edited - self.date_created).total_seconds()), 0)

        def plural(amount, unit):
            return f"{amount} {unit}{'' if amount == 1 else 's'}"

        if seconds < 60:
            return "less than a minute"
        if seconds < 3600:
            return plural(seconds // 60, "minute")
        if seconds < 86400:
            return plural(seconds // 3600, "hour")
        days = seconds // 86400
        if days < 7:
            return plural(days, "day")
        return plural(days // 7, "week")

    def get_category_display(self):
        """Category.name is both value and label, so the label IS the stored
        value. Defined here so Django does not generate the choices-based one,
        which would read the category cache once per story card on listing
        pages (a network round trip each on Redis)."""
        return self.category

    @property
    def word_count(self):
        text = self.content or ""
        return len(re.findall(r"\b\S+\b", text))

    from functools import cached_property
    @cached_property
    def author_name(self):
        from STAFF.models import StaffProfile

        profile = StaffProfile.objects.filter(auth=self.author).first()
        if profile and profile.full_name:
            return profile.full_name
        return self.author.email.split("@")[0].title()

    def __str__(self):
        return f"{self.author.email.split("@")[0]}. {self.views} Views. {self.heading[:20]}"
    
class Comment(models.Model):
    """Comment / Feedback under the blog post"""
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='comments')
    content = models.TextField(blank=False, null=False)
    likes = models.PositiveIntegerField(default=0)
    date_created = models.DateTimeField(auto_now_add=True)    #   NEEDED FOR THE COMMENT TIMESTAMP ("x days ago") SHOWN IN THE UI