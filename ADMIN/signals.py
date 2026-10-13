from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from SERVICE_INTERNAL.abstract import invalidate_cache
from SERVICE_INTERNAL.cache_keys import HOME_BLOGS_CACHE_KEY

from .models import SiteSettings


@receiver(post_save, sender=SiteSettings, dispatch_uid="admin.site_settings.saved.invalidate_caches")
@receiver(post_delete, sender=SiteSettings, dispatch_uid="admin.site_settings.deleted.invalidate_caches")
def site_settings_changed(sender, **kwargs):
    def invalidate_caches():
        invalidate_cache("site_settings_socials")
        invalidate_cache(HOME_BLOGS_CACHE_KEY)

    transaction.on_commit(invalidate_caches, robust=True)
