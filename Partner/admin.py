from django.contrib import admin

from Partner.models import AdvertImage, Announcement
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


admin.site.register([Announcement])
admin.site.register(AdvertImage, AdvertImageAdmin)
