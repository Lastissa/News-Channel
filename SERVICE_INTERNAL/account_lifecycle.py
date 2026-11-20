"""Account hibernation and true-delete helpers.

Self-service deletion and admin "delete author" both hibernate an account:
the login and private controls are disabled, but public content stays up and
anonymized so an admin can still restore the real account later. The only
irreversible path is the off-grid superuser endpoint.
"""

from __future__ import annotations

import random
import string

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from SERVICE_INTERNAL.abstract import info_logger
from SERVICE_INTERNAL.sessions import drop_sessions_for

HIBERNATE_NOTICE_SUBJECT = "Account deactivation started"

DELETE_CODE_TTL_SECONDS = 20 * 60
DELETE_CODE_MAX_SENDS = 3
DELETE_CODE_SEND_WINDOW_SECONDS = 10 * 60
DELETE_CODE_MAX_WRONG_ATTEMPTS = 5
DELETE_CODE_LOCKOUT_SECONDS = 10 * 60

NO_PASSWORD_MESSAGE = "Reset password first before trying to delete account."


def _acct_cache_key(user_id: int, suffix: str) -> str:
    return f"acctdel:{user_id}:{suffix}"


def user_has_preservable_content(user) -> bool:
    """True when the account owns anything a password must protect."""
    from ARCHIVE.models import ArchiveImage
    from BLOG.models import Blog, Comment
    from Partner.models import AdvertImage, AdvertReference
    from STAFF.models import StoryDraft

    return any(
        (
            Blog.all_objects.filter(author=user).exists(),
            Comment.all_objects.filter(author=user).exists(),
            StoryDraft.objects.filter(author=user).exists(),
            ArchiveImage.objects.filter(author=user).exists(),
            AdvertImage.objects.filter(author=user).exists(),
            AdvertReference.objects.filter(user=user).exists(),
        )
    )


def user_requires_password_for_delete(user) -> bool:
    return user_has_preservable_content(user)


def is_author_like_for_adverts(user) -> bool:
    """Author hibernation deletes their adverts; a pure advert owner pauses."""
    from BLOG.models import Blog

    return Blog.all_objects.filter(author=user).exists()


def _owned_advert_ids(user):
    """Every advert the account owns outright: authored, or reached through
    one of its references. A true delete removes these before the Auth row is
    cascaded, because an advert FK is SET_NULL and would otherwise survive
    with no owner."""
    from Partner.models import AdvertImage, AdvertReference

    advert_ids = set(
        AdvertImage.objects.filter(author=user).values_list("id", flat=True)
    )
    advert_ids.update(
        AdvertReference.objects.filter(user=user, advert_id__isnull=False)
        .values_list("advert_id", flat=True)
    )
    return advert_ids


def _collect_all_account_assets(user):
    """Everything Cloudinary-owned to release on a true delete."""
    from ARCHIVE.models import ArchiveImage
    from ARCHIVE.views import _public_id_from_url
    from BLOG.models import Blog
    from Partner.models import AdvertImage, AdvertLandingPage, AdvertPage
    from SERVICE_INTERNAL.images import _avatar_public_id

    story_image_ids = set(
        Blog.all_objects.filter(author=user)
        .exclude(image_public_id="")
        .values_list("image_public_id", flat=True)
    )
    advert_ids = _owned_advert_ids(user)
    advert_images = AdvertImage.objects.filter(id__in=advert_ids)
    advert_image_ids = set(
        advert_images.exclude(image_public_id="").values_list("image_public_id", flat=True)
    )
    landing_public_ids = set(
        AdvertLandingPage.objects.filter(advert_id__in=advert_ids)
        .exclude(html_public_id="")
        .values_list("html_public_id", flat=True)
    )
    page_public_ids = set(
        AdvertPage.objects.filter(advert_id__in=advert_ids)
        .exclude(html_public_id="")
        .values_list("html_public_id", flat=True)
    )
    archive_assets = []
    for item in ArchiveImage.objects.filter(author=user):
        public_id = item.public_id or _public_id_from_url(
            item.url, getattr(item, "resource_type", "image")
        )
        if public_id:
            archive_assets.append((public_id, getattr(item, "resource_type", "image")))
    avatar_public_id = _avatar_public_id(user.pk) if getattr(user, "profile_img", "") else ""
    return {
        "story_image_ids": story_image_ids,
        "advert_image_ids": advert_image_ids,
        "landing_public_ids": landing_public_ids,
        "page_public_ids": page_public_ids,
        "archive_assets": archive_assets,
        "avatar_public_id": avatar_public_id,
    }


def _release_collected_assets(assets):
    from HOME.views import _release_story_image
    from SERVICE_INTERNAL.images import destroy_advert_landing_html, destroy_archive_asset

    for public_id in assets.get("story_image_ids", set()):
        _release_story_image(public_id)
    for public_id in assets.get("advert_image_ids", set()):
        try:
            destroy_archive_asset(public_id, "image")
        except Exception:
            info_logger(msg=f"ACCOUNT CLEANUP: could not delete advert image {public_id}")
    for field in ("landing_public_ids", "page_public_ids"):
        for public_id in assets.get(field, set()):
            try:
                destroy_advert_landing_html(public_id)
            except Exception:
                info_logger(msg=f"ACCOUNT CLEANUP: could not delete advert HTML {public_id}")
    for public_id, resource_type in assets.get("archive_assets", []):
        try:
            destroy_archive_asset(public_id, resource_type)
        except Exception:
            info_logger(msg=f"ACCOUNT CLEANUP: could not delete archive asset {public_id}")
    avatar = assets.get("avatar_public_id")
    if avatar:
        try:
            destroy_archive_asset(avatar, "image")
        except Exception:
            info_logger(msg=f"ACCOUNT CLEANUP: could not delete avatar {avatar}")


def invalidate_account_caches():
    """Best-effort invalidation through the regular Django cache flow."""
    try:
        from SERVICE_INTERNAL.cache_keys import HOME_BLOGS_CACHE_KEY, HOME_PAGE_HTML_CACHE_KEY

        cache.delete(HOME_BLOGS_CACHE_KEY)
        cache.delete(HOME_PAGE_HTML_CACHE_KEY)
    except Exception:
        pass
    for key in (
        "most-viewed-popular-stories",
        "home-teaser-items",
        "archive-uploaders",
    ):
        try:
            cache.delete(key)
        except Exception:
            pass
    # Story detail pages are cached by slug, so drop those keys too when the
    # cache backend supports iteration (LocMemCache does; some Redis setups
    # disable it, in which case the 100s TTL is the acceptable fallback).
    try:
        keys = getattr(cache, "_cache", None)
        if keys is not None and hasattr(keys, "_cache"):
            for key in list(keys._cache.keys()):
                if str(key).startswith("blog-"):
                    cache.delete(key)
    except Exception:
        pass


def _delete_follows_for(user):
    from STAFF.models import AuthorFollow, FollowRelationship

    AuthorFollow.objects.filter(Q(follower=user) | Q(author=user)).delete()
    FollowRelationship.objects.filter(Q(follower__auth=user) | Q(followee__auth=user)).delete()


def _delete_drafts_and_announcements(user):
    from Partner.models import Announcement
    from STAFF.models import StoryDraft

    StoryDraft.objects.filter(author=user).delete()
    Announcement.objects.filter(author=user).delete()


def _pause_adverts_for_user(user):
    from Partner.models import AdvertImage, AdvertLandingPage, AdvertReference

    now = timezone.now()
    refs = list(AdvertReference.objects.filter(user=user))
    AdvertReference.objects.filter(user=user).update(
        status=AdvertReference.STATUS_PAUSED, updated_at=now
    )
    advert_ids = [ref.advert_id for ref in refs if ref.advert_id]
    if advert_ids:
        AdvertImage.objects.filter(id__in=advert_ids).update(is_active=False)
        AdvertLandingPage.objects.filter(advert_id__in=advert_ids).update(is_published=False)


def _resume_adverts_for_user(user):
    from Partner.models import AdvertImage, AdvertLandingPage, AdvertReference

    now = timezone.now()
    refs = list(AdvertReference.objects.filter(user=user, status=AdvertReference.STATUS_PAUSED))
    resumable_ids = []
    for ref in refs:
        if ref.expires_at and ref.expires_at <= now:
            continue
        resumable_ids.append(ref.advert_id)
        AdvertReference.objects.filter(pk=ref.pk).update(
            status=AdvertReference.STATUS_ACTIVE, updated_at=now
        )
    resumable_ids = [advert_id for advert_id in resumable_ids if advert_id]
    if resumable_ids:
        AdvertImage.objects.filter(id__in=resumable_ids).update(is_active=True)
        AdvertLandingPage.objects.filter(advert_id__in=resumable_ids).update(is_published=True)


def _delete_author_adverts_for_user(user):
    """A hibernated author loses the adverts they authored or own outright."""
    from Partner.models import AdvertImage, AdvertLandingPage, AdvertPage, AdvertReference
    from SERVICE_INTERNAL.images import destroy_advert_landing_html, destroy_archive_asset

    refs = list(AdvertReference.objects.filter(user=user).select_related("advert"))
    advert_ids = [ref.advert_id for ref in refs if ref.advert_id]
    for advert in AdvertImage.objects.filter(author=user):
        if advert.id not in advert_ids:
            advert_ids.append(advert.id)

    for advert_id in advert_ids:
        for landing in AdvertLandingPage.objects.filter(advert_id=advert_id):
            if landing.html_public_id:
                try:
                    destroy_advert_landing_html(landing.html_public_id)
                except Exception:
                    pass
        for page in AdvertPage.objects.filter(advert_id=advert_id):
            if page.html_public_id:
                try:
                    destroy_advert_landing_html(page.html_public_id)
                except Exception:
                    pass
    for public_id in (
        AdvertImage.objects.filter(id__in=advert_ids)
        .exclude(image_public_id="")
        .values_list("image_public_id", flat=True)
    ):
        try:
            destroy_archive_asset(public_id, "image")
        except Exception:
            pass

    AdvertReference.objects.filter(user=user).delete()
    if advert_ids:
        AdvertImage.objects.filter(id__in=advert_ids).delete()


def _editorial_admin_emails():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return list(
        User.everyone.filter(
            is_admin=True, is_active=True, deleted_at__isnull=True
        )
        .exclude(email="")
        .values_list("email", flat=True)
    )


def _staff_display_name(user):
    try:
        profile = getattr(user, "staffprofile", None)
        if profile and getattr(profile, "full_name", ""):
            return profile.full_name.strip()
    except Exception:
        pass
    return ""


def _write_audit_log(user, action, details, actor=None):
    """DB-backed audit trail shown in the admin UI. Cache/email failures must
    never block an account state change, so this is best effort too."""
    actor = actor or user
    actor_name = _staff_display_name(actor) or actor.email
    try:
        from ADMIN.models import AccountActionLog

        AccountActionLog.objects.create(
            account=user,
            account_email=user.email,
            action=action,
            actor=actor if actor.pk else None,
            actor_email=actor.email,
            actor_name=actor_name,
            details=details,
            created_at=timezone.now(),
        )
    except Exception as exc:
        info_logger(msg=f"ACCOUNT AUDIT: could not write {action} log for {user.email}: {exc}")


def notify_admins_deactivation_started(user, when=None, actor=None):
    """Email active editorial admins and write the PANEL-visible audit row."""
    from SERVICE_INTERNAL.config import About
    from SERVICE_INTERNAL.email_single import _build_email_html, _dispatch_email

    when = when or timezone.now()
    real_name = _staff_display_name(user) or user.email
    date_str = timezone.localtime(when).strftime("%d %b %Y, %H:%M")
    detail_lines = [
        f"Real identity: {real_name}",
        f"Email: {user.email}",
        f"Date: {date_str}",
    ]
    body = "\n".join(detail_lines)
    try:
        html_message = _build_email_html(
            title=HIBERNATE_NOTICE_SUBJECT,
            main_content="<p>An account deactivation (hibernation) was confirmed.</p><p>"
            + "<br>".join(detail_lines)
            + "</p>",
            end_note=About.project_name,
            unsubscribe_query=None,
        )
        for recipient in _editorial_admin_emails():
            try:
                _dispatch_email(recipient, HIBERNATE_NOTICE_SUBJECT, html_message)
            except Exception:
                info_logger(msg=f"HIBERNATE NOTICE: failed emailing admin {recipient}")
    except Exception:
        info_logger(msg="HIBERNATE NOTICE: failed to dispatch admin emails")

    _write_audit_log(user, "hibernated", body, actor=actor)
    info_logger(msg=f"ACCOUNT HIBERNATED: {user.email} ({real_name})")


def hibernate_account(user, *, actor=None):
    """Disable login, preserve private data, and leave public content visible."""
    from AUTHENTICATION.models import Auth

    now = timezone.now()
    account = Auth.everyone.get(pk=user.pk)
    try:
        drop_sessions_for(account)
    except Exception:
        pass

    with transaction.atomic():
        _delete_follows_for(account)
        _delete_drafts_and_announcements(account)
        if is_author_like_for_adverts(account):
            _delete_author_adverts_for_user(account)
        else:
            _pause_adverts_for_user(account)
        account.deleted_at = now
        account.is_active = False
        account.save(update_fields=["deleted_at", "is_active"])

    notify_admins_deactivation_started(account, when=now, actor=actor)
    invalidate_account_caches()
    return account


def restore_account(user, *, actor=None):
    """Admin-only undo. No email is sent to the account owner."""
    from AUTHENTICATION.models import Auth

    account = Auth.everyone.get(pk=user.pk)
    with transaction.atomic():
        account.deleted_at = None
        account.is_active = True
        account.save(update_fields=["deleted_at", "is_active"])
        _resume_adverts_for_user(account)

    actor = actor or account
    actor_name = _staff_display_name(actor) or actor.email
    _write_audit_log(
        account,
        "restored",
        f"Real identity: {actor_name}\nRestored email: {account.email}",
        actor=actor,
    )
    info_logger(msg=f"ACCOUNT RESTORED: {account.email} by {actor.email}")
    invalidate_account_caches()
    return account


def true_delete_account(user, *, reason="true_delete"):
    """Irreversible full delete used only by the superuser backdoor."""
    from AUTHENTICATION.models import Auth
    from Partner.models import AdvertImage

    account = Auth.everyone.get(pk=user.pk)
    email = account.email
    advert_ids = _owned_advert_ids(account)
    assets = _collect_all_account_assets(account)
    try:
        drop_sessions_for(account)
    except Exception:
        pass
    with transaction.atomic():
        #   Reference-owned adverts would survive the Auth cascade (their FK
        #   is SET_NULL), so remove them explicitly as part of total removal.
        if advert_ids:
            AdvertImage.objects.filter(id__in=advert_ids).delete()
        account.delete()
    _release_collected_assets(assets)
    invalidate_account_caches()
    info_logger(msg=f"ACCOUNT TRUE DELETE ({reason}): completed for {email}")
    return True


# --- Cache-backed deletion verification ---------------------------------


def _code_key(user_id):
    return _acct_cache_key(user_id, "code")


def _sends_key(user_id):
    return _acct_cache_key(user_id, "sends")


def _wrong_key(user_id):
    return _acct_cache_key(user_id, "wrong")


def _lock_key(user_id):
    return _acct_cache_key(user_id, "lock")


def delete_code_lock_remaining_seconds(user_id):
    locked_until = cache.get(_lock_key(user_id))
    if not locked_until:
        return 0
    return max(1, int(float(locked_until) - timezone.now().timestamp()))


def delete_code_locked_until(user_id):
    return cache.get(_lock_key(user_id))


def can_send_delete_code(user_id):
    if delete_code_locked_until(user_id):
        return False, "locked"
    if (cache.get(_sends_key(user_id)) or 0) >= DELETE_CODE_MAX_SENDS:
        return False, "send_limit"
    return True, ""


def issue_delete_code(user_id):
    """Create a single-use 5-digit code. Max three sends per ten minutes."""
    ok, reason = can_send_delete_code(user_id)
    if not ok:
        return None, reason

    code = "".join(random.SystemRandom().choice(string.digits) for _ in range(5))
    cache.set(_code_key(user_id), {"code": code}, timeout=DELETE_CODE_TTL_SECONDS)

    sends_key = _sends_key(user_id)
    sends = cache.get(sends_key)
    if sends is None:
        cache.set(sends_key, 1, timeout=DELETE_CODE_SEND_WINDOW_SECONDS)
    else:
        try:
            ttl = cache.ttl(sends_key)
        except Exception:
            ttl = None
        cache.set(
            sends_key,
            int(sends) + 1,
            timeout=max(1, int(ttl)) if ttl and int(ttl) > 0 else DELETE_CODE_SEND_WINDOW_SECONDS,
        )
    return code, ""


def verify_delete_code(user_id, submitted_code):
    if delete_code_locked_until(user_id):
        return False, "locked"
    payload = cache.get(_code_key(user_id))
    if not payload or not payload.get("code"):
        return False, "missing"
    if str(submitted_code or "").strip() != str(payload["code"]):
        wrong = (cache.get(_wrong_key(user_id)) or 0) + 1
        if wrong >= DELETE_CODE_MAX_WRONG_ATTEMPTS:
            cache.set(
                _lock_key(user_id),
                timezone.now().timestamp() + DELETE_CODE_LOCKOUT_SECONDS,
                timeout=DELETE_CODE_LOCKOUT_SECONDS,
            )
            cache.delete(_wrong_key(user_id))
            cache.delete(_code_key(user_id))
            return False, "locked"
        cache.set(_wrong_key(user_id), wrong, timeout=DELETE_CODE_LOCKOUT_SECONDS)
        return False, "invalid"
    cache.delete(_code_key(user_id))
    cache.delete(_wrong_key(user_id))
    cache.delete(_lock_key(user_id))
    return True, ""


def clear_delete_code_state(user_id):
    for key in (_code_key(user_id), _sends_key(user_id), _wrong_key(user_id), _lock_key(user_id)):
        cache.delete(key)
