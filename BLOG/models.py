import re

from django.db import models
from django.db.models.functions import Lower
from django.utils.text import slugify


CATEGORY = [
    ('UNIVERSITY', 'UNIVERSITY'),
    ('POLYTECHNIC', 'POLYTECHNIC'),
    ('ORGANIZATION', 'ORGANIZATION'),
    ('JAMB', 'JAMB'),
    ('WAEC', 'WAEC'),
    ('POSTUTME', 'POSTUTME'),
    ('SCHOLARSHIP', 'SCHOLARSHIP'),
    ('TECHNOLOGY', 'TECHNOLOGY'),
    ('SECURITY', 'SECURITY'),
    ('GENERAL', 'GENERAL'),
]
class Blog(models.Model):
    image_1 = models.URLField(blank=True, null=True)
    image_info = models.CharField(max_length=100, default="The image is self explanatory.")    #   THE ABOUT PICTURE THHAT WILL SHOW SLIGHTLY BELOW THE PICTURE IN IMAGE 
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='blogs', limit_choices_to= {'is_staff':True})
    category = models.CharField(max_length=20, choices=CATEGORY, blank=False, null=False)
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
        return f"{self.author.email} {self.views} + {self.heading[:20]}"
    
class Comment(models.Model):
    """Comment / Feedback under the blog post"""
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='comments')
    content = models.TextField(blank=False, null=False)
    likes = models.PositiveIntegerField(default=0)
    date_created = models.DateTimeField(auto_now_add=True)    #   NEEDED FOR THE COMMENT TIMESTAMP ("x days ago") SHOWN IN THE UI