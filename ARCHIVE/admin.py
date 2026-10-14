from django.contrib import admin

from ARCHIVE.models import ArchiveImage
from SERVICE_INTERNAL.images import destroy_archive_asset


def _asset_for(row):
    """The Cloudinary (public_id, resource_type) for an archive row, using the
    legacy URL fallback when the bookkeeping column predates the row.

    ARCHIVE.views is imported lazily because it imports HOME.views."""
    from ARCHIVE.views import _public_id_from_url

    return (row.public_id or _public_id_from_url(row.url, row.resource_type), row.resource_type)


def _release(assets):
    for public_id, resource_type in assets:
        if public_id:
            destroy_archive_asset(public_id, resource_type)


class ArchiveImageAdmin(admin.ModelAdmin):
    """The public /archive/ delete keeps an item whose asset cannot be removed
    (ARCHIVE.views.ArchiveItemDeleteView). From the Django admin the row is
    already gone, so this releases the Cloudinary asset best effort afterwards,
    so the _admin/ backdoor cannot leave an orphan either."""

    def delete_model(self, request, obj):
        assets = [_asset_for(obj)]
        super().delete_model(request, obj)
        _release(assets)

    def delete_queryset(self, request, queryset):
        assets = [_asset_for(row) for row in queryset]
        super().delete_queryset(request, queryset)
        _release(assets)


admin.site.register(ArchiveImage, ArchiveImageAdmin)
