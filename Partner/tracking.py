"""Small, honest advert tracking helpers.

The public site only writes two things here: a view when an advert becomes the
focused slide (or a landing page is opened), and a click when a tracked advert
link is followed. Bots and link-preview fetchers are ignored, raw IP addresses
are hashed, and repeat views/clicks from the same IP inside 3 seconds are
collapsed so an accidental double tap is counted once.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

from SERVICE_INTERNAL.abstract import get_client_ip, is_bot_request

from .models import AdvertEvent, AdvertReference

#   1x1 transparent GIF. Kept as bytes so the pixel response never touches the
#   filesystem or static storage.
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)

#   One tap should count once, but a second tap a moment later is a real one.
#   The window is short and keyed on the visitor's IP only.
VIEW_DEDUPE_SECONDS = 3
CLICK_DEDUPE_SECONDS = 3


def hash_ip(request) -> str:
    """A stable, non-reversible fingerprint. Never store the raw address."""
    value = (get_client_ip(request) or "").strip()
    if not value:
        return ""
    secret = (getattr(settings, "SECRET_KEY", "") or "").encode("utf-8", "ignore")
    return hashlib.sha256(secret + value.encode("utf-8", "ignore")).hexdigest()


def classify_traffic(request) -> str:
    """On-site, external, or direct.

    ``utm_source=abureport`` is the marker our own links add. Any other UTM
    source is external. With no UTM, a referrer from our own host is internal,
    a different host is external, and no referrer at all is direct.
    """
    utm_source = (request.GET.get("utm_source") or "").strip().lower()
    if utm_source == AdvertEvent.SOURCE_ABUREPORT:
        return AdvertEvent.SOURCE_ABUREPORT
    if utm_source:
        return AdvertEvent.SOURCE_EXTERNAL

    referrer = (request.META.get("HTTP_REFERER") or "").strip()
    if referrer:
        try:
            referrer_host = (urlsplit(referrer).netloc or "").lower()
            own_host = (request.get_host() or "").lower()
        except Exception:
            referrer_host = own_host = ""
        if referrer_host and referrer_host == own_host:
            return AdvertEvent.SOURCE_ABUREPORT
        if referrer_host:
            return AdvertEvent.SOURCE_EXTERNAL
    return AdvertEvent.SOURCE_DIRECT


def append_utm_source(url: str, source: str = AdvertEvent.SOURCE_ABUREPORT) -> str:
    """Add ``utm_source`` to an http(s) link without overriding an existing one."""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return url
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any(key.lower() == "utm_source" for key, _value in query):
        return url
    query.append(("utm_source", source))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _request_session_key(request) -> str:
    try:
        return (request.session.session_key or "")[:40]
    except Exception:
        return ""


def _recent_event_exists(reference, event_type, ip_hash, dedupe_seconds):
    """True when the same IP already recorded this event a moment ago.

    The IP comes from get_client_ip (CF-Connecting-IP first), so visitors
    behind Cloudflare are told apart by their real address. Sessions are not
    used: another visitor on another IP never suppresses this one.
    """
    if dedupe_seconds <= 0 or not ip_hash:
        return False
    return AdvertEvent.objects.filter(
        reference=reference,
        event_type=event_type,
        ip_hash=ip_hash,
        created_at__gte=timezone.now() - timedelta(seconds=dedupe_seconds),
    ).exists()


def record_advert_event(
    reference,
    event_type,
    request,
    *,
    target_url="",
    source=None,
    dedupe_seconds=0,
):
    """Write one event, or return ``None`` when it is a bot/duplicate."""
    if not isinstance(reference, AdvertReference) or not reference.pk:
        return None
    if is_bot_request(request):
        return None

    ip_hash = hash_ip(request)
    session_key = _request_session_key(request)
    if _recent_event_exists(reference, event_type, ip_hash, dedupe_seconds):
        return None

    return AdvertEvent.objects.create(
        reference=reference,
        event_type=event_type,
        source=source or classify_traffic(request),
        target_url=(target_url or "")[:1000],
        path=(request.path or "")[:500],
        referrer=(request.META.get("HTTP_REFERER") or "")[:1000],
        ip_hash=ip_hash,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:255],
        session_key=session_key,
    )


def record_advert_view(reference, request):
    return record_advert_event(
        reference,
        AdvertEvent.EVENT_VIEW,
        request,
        dedupe_seconds=VIEW_DEDUPE_SECONDS,
    )


def record_advert_click(reference, request, target_url=""):
    #   Classify the click by where the reader came from. A click on the home
    #   rail has our own page as its referrer and lands in the Abureport bucket;
    #   a shared tracked link opened from another site lands in External. The
    #   redirect itself still appends utm_source=abureport so the advertiser's
    #   own analytics can attribute the visit to us.
    return record_advert_event(
        reference,
        AdvertEvent.EVENT_CLICK,
        request,
        target_url=target_url,
        dedupe_seconds=CLICK_DEDUPE_SECONDS,
    )


def tracking_pixel_response() -> HttpResponse:
    response = HttpResponse(_TRANSPARENT_GIF, content_type="image/gif")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response
