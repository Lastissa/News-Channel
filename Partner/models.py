from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.text import slugify


class Announcement(models.Model):
    """A short text announcement that scrolls across the top bar of the home
    page (HOME.views._announcement_items). Managed from PANEL
    ("Announcements")."""
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=False, blank=False)
    content = models.CharField(max_length=400, default="")
    url = models.URLField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return str(self.author) + " ---Expiry: " + str(self.expiry_date.strftime("%d of %b, %Y"))
    

class AdvertImage(models.Model):
    """AN IMAGE ADVERT SHOWN IN THE HERO SIDE CAROUSEL ON THE HOME PAGE
    (HOME.views._teaser_items). Managed from PANEL ("Image adverts"). Mobile
    shows the picture only, desktop also shows heading + body under it.
    `url` is where a click on the picture goes, empty means not clickable.
    `image_public_id` is the Cloudinary asset, kept so an edit overwrites it
    in place and a delete removes it."""
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=False, blank=False)
    heading = models.CharField(max_length=90, blank=True, default="")
    body = models.CharField(max_length=200, blank=True, default="")
    image_url = models.URLField(max_length=500)
    image_public_id = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return (self.heading or "Image advert") + " ---Expiry: " + str(self.expiry_date.strftime("%d of %b, %Y"))


class AdvertLandingPage(models.Model):
    """The full, off-grid page an image advert opens on this domain.

    The HTML itself lives in Cloudinary as an authenticated raw asset. This
    row intentionally keeps only the identifying/editorial metadata: the
    Cloudinary public id (so an edit can overwrite the same asset and a delete
    can remove it), the robots/meta values, and who last wrote the file. The
    URL slug is derived from ``advert.heading`` every request, so renaming an
    advert never leaves a stale slug behind -- old links still resolve by the
    numeric id and are redirected to the current heading.

    ``author`` is the last admin who saved the HTML, not the advert's creator.
    The public view refuses to render the file unless that account still
    exists, is active, and is still an admin/superuser.
    """

    ROBOTS_NOINDEX = "noindex, nofollow"
    ROBOTS_CHOICES = (
        (ROBOTS_NOINDEX, "noindex, nofollow (default)"),
        ("noindex, follow", "noindex, follow"),
        ("index, nofollow", "index, nofollow"),
        ("index, follow", "index, follow"),
    )

    advert = models.OneToOneField(
        AdvertImage,
        on_delete=models.CASCADE,
        related_name="landing_page",
    )
    meta_title = models.CharField(max_length=120, blank=True, default="")
    meta_description = models.CharField(max_length=320, blank=True, default="")
    og_image = models.URLField(max_length=500, blank=True, default="")
    robots = models.CharField(max_length=32, choices=ROBOTS_CHOICES, default=ROBOTS_NOINDEX)

    html_public_id = models.CharField(max_length=255, blank=True, default="")
    html_bytes = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    author = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advert_landing_pages",
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_updated",)

    def __str__(self):
        return f"Landing page for {self.advert.heading or 'image advert'} (#{self.advert_id})"

    @property
    def slug(self):
        """Current heading as a URL slug. The id is appended by the route, so
        two adverts with the same heading still get distinct URLs."""
        return slugify(self.advert.heading or "") or "advert"

    def get_absolute_url(self):
        return reverse(
            "partner:advert_landing",
            kwargs={"slug": self.slug, "pk": self.advert_id},
        )

    @property
    def author_label(self):
        if not self.author_id:
            return ""
        profile = getattr(self.author, "staffprofile", None)
        return (getattr(profile, "full_name", "") or self.author.email or "").strip()

    @property
    def author_is_trusted(self):
        """A page may only run while its last writer is still a live admin."""
        author = self.author
        return bool(
            author
            and author.is_active
            and (author.is_admin or author.is_superuser)
        )

    @property
    def is_deliverable(self):
        return bool(
            self.is_published
            and self.html_public_id
            and self.author_is_trusted
        )

    @property
    def title_value(self):
        return (self.meta_title or self.advert.heading or "Advert").strip()

    @property
    def description_value(self):
        return (self.meta_description or self.advert.body or "").strip()

    @property
    def og_image_value(self):
        return (self.og_image or self.advert.image_url or "").strip()


@receiver(post_delete, sender=AdvertLandingPage)
def _release_landing_html(sender, instance, **kwargs):
    """Deleting the row (from PANEL, Django admin, or an advert cascade) also
    removes the Cloudinary HTML file. Imported lazily so models stay importable
    before the service module finishes loading."""
    if not instance.html_public_id:
        return
    from SERVICE_INTERNAL.images import destroy_advert_landing_html

    destroy_advert_landing_html(instance.html_public_id)
