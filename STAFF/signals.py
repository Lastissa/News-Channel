from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from SERVICE_INTERNAL.abstract import invalidate_cache
from SERVICE_INTERNAL.cache_keys import HOME_BLOGS_CACHE_KEY

from .models import StaffProfile


@receiver(post_save, sender=StaffProfile, dispatch_uid="staff.profile.saved.invalidate_home_cache")
@receiver(post_delete, sender=StaffProfile, dispatch_uid="staff.profile.deleted.invalidate_home_cache")
def staff_profile_changed(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_cache(HOME_BLOGS_CACHE_KEY), robust=True)
