from django.db import models


class SiteSettings(models.Model):
    """Single row holding the site-wide socials and contact addresses that
    used to be hardcoded in SERVICE_INTERNAL.config.About. Editable from the
    PANEL page instead of a code deploy.

    Only one row is ever meant to exist -- get_solo() below is the only way
    the rest of the codebase should ever touch this model.
    """

    twitter_handle = models.URLField(blank=True, default="", help_text="X / Twitter profile or page URL.")
    facebook_handle = models.URLField(blank=True, default="", help_text="Facebook page URL.")
    promotion_email = models.EmailField(blank=True, default="", help_text="For partnership / advertising inquiries.")
    tech_expert_email = models.EmailField(blank=True, default="", help_text="For reporting glitches / bugs in the system.")
    support_email = models.EmailField(blank=True, default="", help_text="For customer / usage problems, not software bugs.")
    whatsapp_channel = models.URLField(blank=True, default="", help_text="WhatsApp channel invite / URL.")
    customer_support_mobile = models.CharField(
        max_length=32, blank=True, default="", help_text="Customer support phone / WhatsApp number shown to readers."
    )
    ads_whatsapp_support = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="WhatsApp number for advertising and partnership enquiries.",
    )
    #   ARCHIVE UPLOAD ALERTS: a superuser turns this on from their profile.
    #   While it is on, every new item added to the /archive/ gallery emails
    #   ARCHIVE_UPLOAD_ALERT_EMAIL with who uploaded it and what kind of file
    #   it was (see ARCHIVE.views.ArchiveUploadView). Off by default so a fresh
    #   install never emails anyone without being asked to.
    archive_upload_alerts = models.BooleanField(
        default=False,
        help_text="Email the owner every time a new item is uploaded to the archive gallery.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Site settings"
        verbose_name_plural = "Site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def get_solo(cls):
        """Returns the one settings row, creating an empty one the first
        time this is ever called so every caller can rely on a row existing
        without special-casing None."""
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class AccountActionLog(models.Model):
    """Admin-visible audit trail for account lifecycle actions.

    Self-service hibernations, admin restores, and other lifecycle operations
    are recorded here so the panel can show real identity/date information
    even when the public site renders the account as "Unknown".
    """

    ACTION_HIBERNATED = "hibernated"
    ACTION_RESTORED = "restored"
    ACTION_CHOICES = (
        (ACTION_HIBERNATED, "Hibernated"),
        (ACTION_RESTORED, "Restored"),
    )

    account = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_action_logs",
    )
    account_email = models.EmailField(blank=True, default="")
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    actor = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="performed_account_actions",
    )
    actor_email = models.EmailField(blank=True, default="")
    actor_name = models.CharField(max_length=255, blank=True, default="")
    details = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=None, null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = "Account action log"
        verbose_name_plural = "Account action logs"

    def __str__(self):
        return f"{self.account_email} {self.action}"
