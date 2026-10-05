"""Keeps the no-TTL category cache (BLOG.models.CATEGORY_CACHE_KEY) in step with
the Category table. Wired up in BLOG.apps.BlogConfig.ready().

The refresh is queued with transaction.on_commit, not run immediately:
  * a rolled back change never reaches the cache, and
  * a reader can never re-fill the cache with the OLD list in the gap between
    "the row was saved" and "the row was committed", which with no TTL would
    stay wrong until the next edit.
Outside a transaction (the normal request path here) Django runs the callback
straight away, so the cache is current as soon as save()/delete() returns.
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.core.cache import cache

from .models import Blog, Category, refresh_category_cache


@receiver(post_save, sender=Category, dispatch_uid="blog.category.saved.refresh_cache")
@receiver(post_delete, sender=Category, dispatch_uid="blog.category.deleted.refresh_cache")
def category_changed(sender, **kwargs):
    #   robust=True: a failing cache backend is logged instead of turning an
    #   already committed admin change into a 500
    transaction.on_commit(refresh_category_cache, robust=True)


@receiver(post_save, sender=Blog, dispatch_uid="blog.story.saved.invalidate_home_cache")
@receiver(post_delete, sender=Blog, dispatch_uid="blog.story.deleted.invalidate_home_cache")
def story_changed(sender, **kwargs):
    transaction.on_commit(lambda: cache.delete("home_page_blogs_v2"), robust=True)
