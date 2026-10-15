from datetime import timedelta
import hashlib
import ipaddress

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.conf import settings
from django.utils import timezone

from SERVICE_INTERNAL.abstract import get_client_ip, info_logger
from SERVICE_INTERNAL.email_single import _try_send_login_email

from .models import KnownDevice, UserSession


def device_fingerprint(ip, user_agent):
    """Stable SHA-256 of the login network + browser so the same device maps
    to the same KnownDevice row across logins."""
    raw = f"{(ip or '').strip().lower()}|{(user_agent or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _valid_ip_or_none(value):
    """UserSession.ip is a GenericIPAddressField, so the 'unknown' fallback
    from get_client_ip cannot be stored there -- blank it instead."""
    try:
        ipaddress.ip_address(value)
    except (ValueError, TypeError):
        return None
    return value


@receiver(user_logged_in)
def track_login(sender, request, user, **kwargs):
    if not request.session.session_key:
        return

    ip = get_client_ip(request)
    user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:255]
    fingerprint = device_fingerprint(ip, user_agent)

    #   A login is suspicious only when the account has signed in from
    #   something before AND this device is new. The very first device on a
    #   fresh account is never flagged -- there is nothing familiar to compare
    #   against yet.
    had_known_device = KnownDevice.objects.filter(user=user).exists()
    device, device_created = KnownDevice.objects.get_or_create(
        user=user,
        fingerprint=fingerprint,
        defaults={"ip": ip or "", "user_agent": user_agent},
    )
    if not device_created:
        KnownDevice.objects.filter(pk=device.pk).update(last_seen=timezone.now())
    is_suspicious = bool(device_created and had_known_device)

    _try_send_login_email(user)
    UserSession.objects.update_or_create(
        session_key=request.session.session_key,
        # THE DEFAULT EXIST AS PER I AM USING A UPDATE OR CREATE AND IT NEED VARIBALE WHILE THE ABOVE IS THE REAL LOOKUP
        defaults={
            "user": user,
            "ip": _valid_ip_or_none(ip),
            "user_agent": user_agent,
            "is_suspicious": is_suspicious,
            'expires_at': timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE),
        },
    )


@receiver(user_logged_out)
def track_logout(sender, request, user, **kwargs):
    if not request.session.session_key:
        return
    email = getattr(user, "email", None) or "Anonymous"
    info_logger(msg=f"ACCOUNT LOGOUT: {email} logged out successfully")
    UserSession.objects.filter(session_key=request.session.session_key).delete()