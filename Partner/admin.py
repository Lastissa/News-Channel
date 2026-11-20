from django.contrib import admin

from Partner.models import (
    AdvertEvent,
    AdvertImage,
    AdvertLandingPage,
    AdvertLead,
    AdvertPage,
    AdvertReference,
    Announcement,
)
from SERVICE_INTERNAL.images import destroy_archive_asset


class AdvertImageAdmin(admin.ModelAdmin):
    """Releases the Cloudinary picture when an advert is deleted from the
    Django admin too, so the _admin/ backdoor cannot orphan it (PANEL already
    does this in ADMIN.views.PanelImageAdvertDeleteView)."""

    def delete_model(self, request, obj):
        public_id = obj.image_public_id
        super().delete_model(request, obj)
        if public_id:
            destroy_archive_asset(public_id)

    def delete_queryset(self, request, queryset):
        public_ids = set(
            queryset.exclude(image_public_id="").values_list("image_public_id", flat=True)
        )
        super().delete_queryset(request, queryset)
        for public_id in public_ids:
            destroy_archive_asset(public_id)


class AdvertLandingPageAdmin(admin.ModelAdmin):
    """The panel is the normal editor; this exists so every project model is
    registered and a superuser can inspect/recover a row from _admin/. The
    Cloudinary id is read-only because editing it would orphan the HTML file;
    the post_delete signal handles removal when a row is deleted here."""

    list_display = ("advert", "is_published", "robots", "author", "date_updated")
    list_filter = ("is_published", "robots")
    search_fields = ("advert__heading", "meta_title", "author__email")
    readonly_fields = ("html_public_id", "html_bytes", "date_created", "date_updated")


class AdvertLeadAdmin(admin.ModelAdmin):
    """Inspection for superusers. The normal ads team view lives in PANEL,
    where the enquiry details are shown in one list."""

    list_display = ("business_name", "plan", "contact_email", "created_at", "user")
    list_filter = ("plan",)
    search_fields = ("business_name", "contact_email", "business_details", "user__email")
    readonly_fields = ("created_at",)


class AdvertReferenceAdmin(admin.ModelAdmin):
    """Inspection/recovery for superusers. Issuance and lifecycle actions are
    in PANEL's ads control page so the normal ads team never needs _admin/."""

    list_display = (
        "reference",
        "subdomain",
        "email_used",
        "plan",
        "status",
        "expires_at",
        "created_at",
    )
    list_filter = ("plan", "status")
    search_fields = (
        "reference",
        "subdomain",
        "email_used",
        "business_name",
        "user__email",
        "issued_by__email",
    )
    readonly_fields = ("reference", "created_at", "updated_at")


class AdvertEventAdmin(admin.ModelAdmin):
    list_display = ("reference", "event_type", "source", "created_at")
    list_filter = ("event_type", "source")
    search_fields = ("reference__reference", "reference__email_used")
    readonly_fields = (
        "reference",
        "event_type",
        "source",
        "target_url",
        "path",
        "referrer",
        "ip_hash",
        "user_agent",
        "session_key",
        "created_at",
    )


admin.site.register([Announcement])
admin.site.register(AdvertImage, AdvertImageAdmin)
admin.site.register(AdvertLandingPage, AdvertLandingPageAdmin)
admin.site.register(AdvertLead, AdvertLeadAdmin)
admin.site.register(AdvertReference, AdvertReferenceAdmin)
admin.site.register(AdvertEvent, AdvertEventAdmin)


class AdvertPageAdmin(admin.ModelAdmin):
    list_display = ("advert", "path", "is_published", "author", "date_updated")
    list_filter = ("is_published",)
    search_fields = ("path", "advert__heading")
    raw_id_fields = ("advert", "author")


admin.site.register(AdvertPage, AdvertPageAdmin)
