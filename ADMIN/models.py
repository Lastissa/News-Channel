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
