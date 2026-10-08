from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from SERVICE_INTERNAL.abstract import invalidate_cache

from .models import StaffProfile


@receiver(post_save, sender=StaffProfile, dispatch_uid="staff.profile.saved.invalidate_home_cache")
@receiver(post_delete, sender=StaffProfile, dispatch_uid="staff.profile.deleted.invalidate_home_cache")
def staff_profile_changed(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_cache("home_page_blogs_v2"), robust=True)
