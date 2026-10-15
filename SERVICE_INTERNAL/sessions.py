"""Shared session helpers.

The admin suspend control and the user facing "log out all sessions"
control both need to end every session an account holds, so the walk lives
here once instead of being copied per caller.
"""

import time
from django.conf import settings
from django.contrib.sessions.models import Session
from django.utils import timezone


def drop_sessions_for(account):
    """Delete every active session belonging to an account.
    Returns how many sessions were dropped.
    """
    from AUTHENTICATION.models import UserSession

    session_keys = list(UserSession.objects.filter(user=account).values_list("session_key", flat=True))
    if not session_keys:
        return 0

    Session.objects.filter(session_key__in=session_keys).delete()
    UserSession.objects.filter(session_key__in=session_keys).delete()
    return len(session_keys)


def drop_single_session(session_key):
    """End exactly one session (its Django row and its UserSession row).

    Returns True when a UserSession row was found and removed. The session
    flag rides on that row, so ending the session clears the "suspicious"
    mark along with it -- which is the intended "log out deletes the field"
    behaviour.
    """
    from AUTHENTICATION.models import UserSession

    if not session_key:
        return False
    removed, _ = UserSession.objects.filter(session_key=session_key).delete()
    Session.objects.filter(session_key=session_key).delete()
    return bool(removed)


def describe_device(user_agent):
    """A short human label for a raw user agent string, e.g. "Chrome on
    Windows" or "Safari on iPhone". Best effort only -- anything we cannot
    place comes back as "Unknown device"."""
    ua = (user_agent or "").strip()
    if not ua:
        return "Unknown device"

    lowered = ua.lower()
    if "edg/" in lowered or "edgios" in lowered or "edga" in lowered:
        browser = "Edge"
    elif "opr/" in lowered or "opera" in lowered:
        browser = "Opera"
    elif "chrome" in lowered or "crios" in lowered:
        browser = "Chrome"
    elif "firefox" in lowered or "fxios" in lowered:
        browser = "Firefox"
    elif "safari" in lowered:
        browser = "Safari"
    else:
        browser = ""

    if "iphone" in lowered:
        os_name = "iPhone"
    elif "ipad" in lowered:
        os_name = "iPad"
    elif "android" in lowered:
        os_name = "Android"
    elif "windows" in lowered:
        os_name = "Windows"
    elif "mac os" in lowered or "macintosh" in lowered:
        os_name = "Mac"
    elif "linux" in lowered:
        os_name = "Linux"
    else:
        os_name = ""

    if browser and os_name:
        return f"{browser} on {os_name}"
    if browser:
        return browser
    if os_name:
        return os_name
    return ua[:60]


def is_session_expired(session_obj):
    """Return True if the given Django Session is expired by its expiry_time."""
    if session_obj is None:
        return True
    expiry = getattr(session_obj, "expire_date", None)
    if expiry is None:
        return False
    return expiry < timezone.now()


def is_admin_inactive_too_long(session_data):
    """True if admin session last_activity is older than ADMIN_MAX_AGE_TOO."""
    try:
        tracker = session_data.get("last_activity") if session_data else None
        if not tracker:
            return False
        max_age = getattr(settings, "ADMIN_MAX_AGE_TOO", 1 * 60 * 60)
        return (time.time() - float(tracker)) > max_age
    except Exception:
        return False


def live_sessions_for(user, now=None):
    """Every UserSession row belonging to `user` that is genuinely still usable.

    A row is kept only when ALL of these hold:

    * its ``expires_at`` (mirrors the Django session expiry) is still in the
      future -- this is what stops a row that outlived its session from being
      counted as "active";
    * the matching ``django_session`` row still exists (a wiped session row
      means the cookie is worthless even if UserSession still holds it);
    * for admins, the inactivity tracker inside the session data is not older
      than ``ADMIN_MAX_AGE_TOO``, mirroring what AdminMaxPeriod would do to
      this very session on its next request.
    """
    from AUTHENTICATION.models import UserSession

    now = now or timezone.now()
    rows = list(
        UserSession.objects.filter(user=user, expires_at__isnull=False, expires_at__gt=now)
        .order_by("-logged_in_at")
    )
    if not rows:
        return []

    django_sessions = {
        s.session_key: s
        for s in Session.objects.filter(
            session_key__in=[r.session_key for r in rows]
        )
    }

    live = []
    for row in rows:
        ds = django_sessions.get(row.session_key)
        if ds is None:
            continue
        if getattr(user, "is_admin", False):
            try:
                data = ds.get_decoded()
            except Exception:
                continue
            if is_admin_inactive_too_long(data):
                continue
        live.append(row)
    return live