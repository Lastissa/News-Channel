from django.contrib import admin

from .models import Auth, KnownDevice, PasswordResetKey, UserSession


class AuthAdmin(admin.ModelAdmin):
    """Deleting an account here cascades through its stories, image adverts and
    archive uploads. Release those Cloudinary assets too, exactly like
    HOME.views.ProfileDeleteAccountView, so _admin/ cannot orphan them."""

    def delete_model(self, request, obj):
        from HOME.views import _collect_account_assets, _release_account_assets

        account_assets = _collect_account_assets(obj)
        super().delete_model(request, obj)
        _release_account_assets(account_assets)

    def delete_queryset(self, request, queryset):
        from HOME.views import _collect_account_assets, _release_account_assets

        collected = [_collect_account_assets(account) for account in queryset]
        super().delete_queryset(request, queryset)
        for account_assets in collected:
            _release_account_assets(account_assets)


admin.site.register([PasswordResetKey, UserSession, KnownDevice])
admin.site.register(Auth, AuthAdmin)
