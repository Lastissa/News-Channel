import re
import secrets

from django.db import models
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

ADVERT_REFERENCE_LENGTH = 16
_REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _reference_email_prefix(email):
    """The first five letters/digits of the email local part, uppercased.

    The reference is shown in WhatsApp and read over the phone, so it stays
    short and unambiguous: no 0/O or 1/I in the random half, and a padded
    prefix when the email local part is shorter than five characters.
    """
    local = (email or "").split("@", 1)[0]
    letters = re.sub(r"[^A-Za-z0-9]", "", local).upper()
    return (letters[:5] or "ADVRT").ljust(5, "X")


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


class AdvertLead(models.Model):
    """A business enquiry sent from the public partner page.

    This is deliberately a lead, not an advertiser account: it catches the
    business details before the ads team replies on WhatsApp. A signed-in
    reader's account is attached when one exists, so the enquiry can later be
    matched to the same account that will own the advert reference.
    """

    PLAN_REGULAR = "regular"
    PLAN_PRO = "pro"
    PLAN_ADVANCE = "advance"
    PLAN_CHOICES = (
        (PLAN_REGULAR, "Regular"),
        (PLAN_PRO, "Pro"),
        (PLAN_ADVANCE, "Advance"),
    )

    user = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advert_leads",
    )
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    business_name = models.CharField(max_length=120)
    contact_email = models.EmailField()
    whatsapp_number = models.CharField(max_length=32, blank=True, default="")
    business_details = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.business_name} - {self.get_plan_display()} enquiry"


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


class AdvertPage(models.Model):
    """One extra page of an advert's site, such as /about/ (Advance plan).

    The HTML is stored in Cloudinary the same way as the landing page. The
    page is shown only while its last writer is still an active admin, the
    advert's plan still includes extra pages, and the reference is live.
    """

    advert = models.ForeignKey(AdvertImage, on_delete=models.CASCADE, related_name="pages")
    path = models.CharField(max_length=80, help_text="For example about or about/team")
    html_public_id = models.CharField(max_length=255, blank=True, default="")
    html_bytes = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    author = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advert_pages",
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("path",)
        constraints = [
            models.UniqueConstraint(fields=["advert", "path"], name="unique_advert_page_path"),
        ]

    def __str__(self):
        return f"/{self.path}/ of advert #{self.advert_id}"

    @property
    def author_is_trusted(self):
        author = self.author
        return bool(author and author.is_active and (author.is_admin or author.is_superuser))

    @property
    def is_deliverable(self):
        return bool(self.is_published and self.html_public_id and self.author_is_trusted)


class AdvertReference(models.Model):
    """The permanent key an advertiser uses to reach their advert's data.

    One row is issued per advert, not per account: a business that buys a
    second advert gets a second reference. The reference itself never expires;
    the paid period lives in ``expires_at`` so a renewal changes the period
    without changing the key the advertiser saved.

    ``reference`` is stored plaintext on purpose. It is a customer-facing key
    (read over WhatsApp, pasted into the dashboard), not a password. Only the
    owner and ads staff ever see it. The row is tied to an existing Auth
    account selected by email at issuance, and the dashboard filters on that
    owner before it shows analytics.
    """

    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_EXPIRED, "Expired"),
    )

    reference = models.CharField(
        max_length=ADVERT_REFERENCE_LENGTH,
        unique=True,
        db_index=True,
        editable=False,
    )
    user = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.CASCADE,
        related_name="advert_references",
    )
    #   Keep the address the reference was issued against. Account emails can
    #   change later; staff still need to know which address was used.
    email_used = models.EmailField(blank=True, default="")
    plan = models.CharField(max_length=20, choices=AdvertLead.PLAN_CHOICES)
    business_name = models.CharField(max_length=120)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    public_url = models.URLField(max_length=500, blank=True, default="")
    #   One manager-assigned host label, e.g. "newads" -> newads.<base>. It is
    #   unique across every advert so two campaigns can never share a URL.
    subdomain = models.CharField(
        max_length=63,
        unique=True,
        null=True,
        blank=True,
        help_text="Optional label for this advert's own subdomain.",
    )
    advert = models.OneToOneField(
        AdvertImage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reference",
    )
    issued_by = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_advert_references",
    )
    notes = models.TextField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    @classmethod
    def build_reference(cls, email, when=None):
        """``<first 5 email chars><DDMMYY><5 random chars>``.

        A date part keeps the key readable in a chat, and the random part is
        checked against the table before it is returned. A collision is
        vanishingly unlikely, but the loop costs nothing and means issuance
        never fails because of it.
        """
        day = when or timezone.localdate()
        date_part = day.strftime("%d%m%y")
        prefix = _reference_email_prefix(email)
        for _attempt in range(100):
            suffix = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(5))
            code = f"{prefix}{date_part}{suffix}"
            if not cls.objects.filter(reference=code).exists():
                return code
        raise RuntimeError("Could not generate a unique advert reference.")

    def save(self, *args, **kwargs):
        if self.user_id and not self.email_used:
            self.email_used = self.user.email
        if not self.reference:
            self.reference = self.build_reference(self.email_used)
        self.subdomain = (self.subdomain or "").strip().lower() or None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.email_used or self.user_id}"

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < timezone.now())

    @property
    def is_live(self):
        if self.status != self.STATUS_ACTIVE or self.is_expired:
            return False
        return not self.starts_at or self.starts_at <= timezone.now()

    @property
    def plan_name(self):
        return dict(AdvertLead.PLAN_CHOICES).get(self.plan, self.plan)

    @property
    def public_target(self):
        """Where a tracked click should send the reader.

        Pro/Advance adverts open on their own subdomain first; the "Learn more"
        link on that page carries the destination (Public page URL, else the
        advert link). A paid reference with neither a subdomain nor a public
        URL is a setup error: the click endpoint reports it instead of guessing.

        Regular adverts open their /ads/ page first. An empty string is only
        returned for a misconfigured paid reference -- the on-site click
        handler turns that into a toast, never a raw JSON page.
        """
        from Partner.landing import advert_landing_url
        from Partner.plans import plan_allows

        public_url = (self.public_url or "").strip()
        if plan_allows(self.plan, "subdomain"):
            if self.public_page_url:
                return self.public_page_url
            #   Legacy/external-only paid adverts are allowed to skip the
            #   subdomain, but only when a destination link exists. The ads
            #   desk Public page URL outranks the advert's own link.
            if public_url:
                return public_url
            advert = self.advert
            if advert and (advert.url or "").strip():
                return advert.url.strip()
            return ""
        advert = self.advert
        if advert:
            return advert_landing_url(advert)
        return public_url

    @property
    def public_host(self):
        """The manager-assigned advert host, or "" when none was chosen."""
        from SERVICE_INTERNAL.hosts import advert_host

        return advert_host(self.subdomain)

    @property
    def public_page_url(self):
        """Absolute URL for the advert's own subdomain, when one is set."""
        from Partner.plans import plan_allows

        host = self.public_host
        if not host or not plan_allows(self.plan, "subdomain"):
            return ""
        from SERVICE_INTERNAL.hosts import advert_origin

        return f"{advert_origin(self.subdomain)}/"

    @property
    def public_link(self):
        """The best public link to show: custom host first, then target."""
        return self.public_page_url or self.public_target


class AdvertReferenceFile(models.Model):
    """A file kept in one reference's Ads desk storage.

    This is deliberately NOT an ArchiveImage: it is private to the ads team,
    belongs to one reference, and is never offered to story tokens or the
    public /archive/ gallery. Cloudinary keeps the bytes; this row keeps the
    public id needed to preview, share (signed link) and delete them again.
    """

    reference = models.ForeignKey(
        AdvertReference,
        on_delete=models.CASCADE,
        related_name="storage_files",
    )
    uploaded_by = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advert_storage_files",
    )
    original_filename = models.CharField(max_length=255)
    note = models.CharField(max_length=240, blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="")
    resource_type = models.CharField(max_length=10, default="image")
    public_id = models.CharField(max_length=255)
    secure_url = models.URLField(max_length=500)
    file_size = models.PositiveIntegerField(default=0)
    date_uploaded = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date_uploaded",)

    def __str__(self):
        return f"{self.reference_id} - {self.original_filename}"


class AdvertEvent(models.Model):
    """One tracked view or click for an advert reference.

    Events are append-only and never exposed publicly. Views are deduplicated
    for an hour per browser session/IP so a refresh does not inflate the
    advertiser dashboard; clicks use a five-second window so a double click
    still counts as one intentional action.
    """

    EVENT_VIEW = "view"
    EVENT_CLICK = "click"
    EVENT_CHOICES = (
        (EVENT_VIEW, "View"),
        (EVENT_CLICK, "Click"),
    )

    SOURCE_ABUREPORT = "abureport"
    SOURCE_EXTERNAL = "external"
    SOURCE_DIRECT = "direct"
    SOURCE_CHOICES = (
        (SOURCE_ABUREPORT, "From Abureport"),
        (SOURCE_EXTERNAL, "External"),
        (SOURCE_DIRECT, "Direct"),
    )

    reference = models.ForeignKey(
        AdvertReference,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=8, choices=EVENT_CHOICES, db_index=True)
    source = models.CharField(
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_DIRECT,
        db_index=True,
    )
    target_url = models.URLField(max_length=1000, blank=True, default="")
    path = models.CharField(max_length=500, blank=True, default="")
    referrer = models.URLField(max_length=1000, blank=True, default="")
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    session_key = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(
                fields=("reference", "event_type", "created_at"),
                name="partner_ref_event_idx",
            ),
        )

    def __str__(self):
        return f"{self.reference_id} - {self.event_type} - {self.created_at:%Y-%m-%d %H:%M}"


@receiver(post_delete, sender=AdvertLandingPage)
def _release_landing_html(sender, instance, **kwargs):
    """Deleting the row (from PANEL, Django admin, or an advert cascade) also
    removes the Cloudinary HTML file. Imported lazily so models stay importable
    before the service module finishes loading."""
    if not instance.html_public_id:
        return
    from SERVICE_INTERNAL.images import destroy_advert_landing_html

    destroy_advert_landing_html(instance.html_public_id)


@receiver(pre_delete, sender=AdvertReference)
def _release_reference_storage(sender, instance, **kwargs):
    """A deleted reference takes its uploaded storage files with it.

    Runs on pre_delete because Django's cascade removes the child rows before
    this parent's post_delete fires. The linked advert picture/HTML is left
    alone unless the Ads desk delete dialog explicitly asked for it.
    """
    from SERVICE_INTERNAL.images import destroy_archive_asset

    for row in instance.storage_files.all():
        if row.public_id:
            destroy_archive_asset(row.public_id, row.resource_type or "image")
