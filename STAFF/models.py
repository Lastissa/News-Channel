from django.db import models
from django.utils.text import slugify

GENDER_CHOICES = [
    ('M', 'Male'),
    ('F', 'Female'),
    ('O', 'Other'),
]
STAFF_ROLE = [
    ('FOUNDER','Founder'),
    ('SNR-JOURNALIST', 'Snr-Journalist'),
    ('JOURNALIST', 'Journalist'),
]


class StaffProfile(models.Model):
    auth = models.OneToOneField("AUTHENTICATION.Auth", on_delete=models.CASCADE, related_name="staffprofile")
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    full_name = models.CharField(max_length=100, blank=True)
    #   SEO/GEO URL SLUG. BUILT FROM `full_name` WHEN THIS PROFILE IS FIRST SAVED
    #   AND REBUILT WHENEVER `full_name` CHANGES (SEE save() BELOW), SO THE
    #   /portfolio/<full-name>/ PATH ALWAYS MATCHES THE CURRENT NAME.
    slug = models.SlugField(max_length=150, blank=True, null=True, unique=True)
    twitter_handle = models.URLField(blank=True, null=True)
    whatsapp_handle = models.URLField(blank=True, null=True)
    facebook_handle = models.URLField(blank=True, null=True)
    # subsequent handle can be added in the future
    speciality = models.JSONField(default=list, blank=True, null=True, help_text="CSV. IF THE STAFF HAVE A SPECIAL NICHE ABOUT POST THEY LOVE MAKING")
    bio = models.TextField(blank=True, default="")
    role = models.CharField(max_length=20, choices=STAFF_ROLE, blank=True, default="JOURNALIST")
    tribute_bio = models.TextField(blank=True, null=True, help_text="DIFFERENT FROM BIO AS THIS ONE, THE ADMINS WRITE IT FOR THE STAFF")
    last_promotion = models.DateField(blank=True, null=True, help_text="DIFFERENT FROM THEN THEY CREATED ACCOUNT, THIS CAN BE USED TO SHOW THEY HAVE BEEN PROMOTED WITHING A TIME SPA")
    get_blog_notification = models.BooleanField(default=True, help_text="WETHER TO BEEP THE STAFF WHEN THEIR BLOG GET VIEWWED") #   
    get_follower_notification = models.BooleanField(default=True, help_text="WETHER TO EMAIL THE AUTHOR WHEN SOMEONE STARTS FOLLOWING THEM")

    class Meta:
        verbose_name = "Staff profile"
        verbose_name_plural = "Staff profiles"

    def _build_unique_slug(self):
        """`slugify(full_name)`, with a short numeric suffix ("jane-doe-2") when
        another staff member already holds it, so every profile keeps a
        working, unique URL. This profile's own current slug never counts as
        taken, so renaming to something that slugifies the same keeps it."""
        base = slugify(self.full_name) or f"staff-{self.pk}"
        candidate = base
        suffix = 2
        while StaffProfile.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def save(self, *args, **kwargs):
        """Keep `slug` in step with `full_name`.

        The slug is generated the first time the profile is saved and is
        rebuilt whenever a save changes `full_name` (e.g. "portfolio/jane-doe/"
        becomes "portfolio/jane-smith/"). A save that does not change the name,
        or one restricted with update_fields that leaves full_name out, never
        touches the slug. The slug is written with a queryset update, so it is
        saved even when the caller used update_fields.

        The old portfolio address stops working after a rename, because the
        slug is the address.
        """
        is_new = self._state.adding
        update_fields = kwargs.get("update_fields")
        name_changed = False
        if not is_new and self.pk and (update_fields is None or "full_name" in update_fields):
            previous = StaffProfile.objects.filter(pk=self.pk).values_list("full_name", flat=True).first()
            name_changed = previous is not None and previous != self.full_name
        super().save(*args, **kwargs)
        if (is_new and not self.slug) or name_changed:
            candidate = self._build_unique_slug()
            if candidate != self.slug:
                StaffProfile.objects.filter(pk=self.pk).update(slug=candidate)
                self.slug = candidate

    def __str__(self):
        return f"{self.auth.email} + {self.full_name}"


class FollowRelationship(models.Model):
    """Track who follows which staff profile and when the relationship started."""

    follower = models.ForeignKey("STAFF.StaffProfile", on_delete=models.CASCADE, related_name="following")
    followee = models.ForeignKey("STAFF.StaffProfile", on_delete=models.CASCADE, related_name="followers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "followee"], name="unique_staff_follow_relation")
        ]

    def __str__(self):
        return f"{self.follower} follows {self.followee}"


class AuthorFollow(models.Model):
    """Reader facing follow of an author, any signed in account included.

    FollowRelationship above only works between staff profiles, so a plain
    member could never follow anybody. This model powers the follow button
    on stories and the follower count on the author portfolio, and it is
    what the author newsletter will read when post alerts ship: following
    means personally receiving the newsletter when this author posts.
    """

    follower = models.ForeignKey("AUTHENTICATION.Auth", on_delete=models.CASCADE, related_name="author_follows")
    author = models.ForeignKey("AUTHENTICATION.Auth", on_delete=models.CASCADE, related_name="author_followers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "author"], name="unique_author_follow")
        ]

    def __str__(self):
        return f"{self.follower.email} follows author {self.author.email}"