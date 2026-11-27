"""Write-through cache for analytics events.

Page requests never write analytics rows directly. They append a small dict to
one of two cache lists; ``/health`` calls :func:`flush_pending_events`, which
writes the queued rows in one batch and clears the lists. Analytics screens
always read the database *and* the pending cache list, so a number is never
missing just because the flush has not happened yet.

The project's default cache is used. Redis gives one shared queue across all
workers; the LocMem fallback is per process, which is fine for local work but
needs Redis for exact counts on more than one server.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from SERVICE_INTERNAL.abstract import error_logger, info_logger
from SERVICE_INTERNAL.traffic import SOURCE_ABUREPORT

STORY_VIEW_KEY = "analytics:pending:story_views:v1"
ADVERT_EVENT_KEY = "analytics:pending:advert_events:v1"
APPEND_LOCK_KEY = "analytics:append:lock"
FLUSH_LOCK_KEY = "analytics:flush:lock"

_APPEND_LOCK_SECONDS = 10
_FLUSH_LOCK_SECONDS = 60
_MAX_PENDING = 5000


def _append(key, event):
    """Append under a short cache lock so concurrent requests do not lose rows."""
    for _attempt in range(50):
        if cache.add(APPEND_LOCK_KEY, "1", timeout=_APPEND_LOCK_SECONDS):
            break
        time.sleep(0.01)
    else:
        #   Never block a page request on analytics. The event is dropped with
        #   a log line rather than making the reader wait indefinitely.
        error_logger(msg=f"ANALYTICS BUFFER: append lock busy, dropped event for {key}")
        return False

    try:
        rows = cache.get(key) or []
        if not isinstance(rows, list):
            rows = []
        rows.append(event)
        if len(rows) > _MAX_PENDING:
            rows = rows[-_MAX_PENDING:]
        cache.set(key, rows, timeout=None)
        return True
    except Exception as exc:
        error_logger(msg=f"ANALYTICS BUFFER: could not queue event for {key}: {exc}")
        return False
    finally:
        cache.delete(APPEND_LOCK_KEY)


def buffer_story_view(blog_id, user_id, source, occurred_at=None):
    """Queue one story view. ``occurred_at`` keeps the original read time."""
    return _append(
        STORY_VIEW_KEY,
        {
            "id": uuid.uuid4().hex,
            "blog_id": blog_id,
            "user_id": user_id,
            "source": source or "direct",
            "occurred_at": (occurred_at or timezone.now()).timestamp(),
        },
    )


def buffer_advert_event(
    reference_id,
    event_type,
    source,
    *,
    target_url="",
    path="",
    referrer="",
    ip_hash="",
    user_agent="",
    session_key="",
    occurred_at=None,
):
    """Queue one advert event for a reference that actually exists."""
    if not reference_id:
        return False
    return _append(
        ADVERT_EVENT_KEY,
        {
            "id": uuid.uuid4().hex,
            "reference_id": reference_id,
            "event_type": event_type,
            "source": (source or "direct")[:16],
            "target_url": (target_url or "")[:1000],
            "path": (path or "")[:500],
            "referrer": (referrer or "")[:1000],
            "ip_hash": (ip_hash or "")[:64],
            "user_agent": (user_agent or "")[:255],
            "session_key": (session_key or "")[:40],
            "occurred_at": (occurred_at or timezone.now()).timestamp(),
        },
    )


def pending_story_views():
    rows = cache.get(STORY_VIEW_KEY) or []
    return rows if isinstance(rows, list) else []


def pending_advert_events():
    rows = cache.get(ADVERT_EVENT_KEY) or []
    return rows if isinstance(rows, list) else []


def _as_datetime(timestamp):
    try:
        return datetime.fromtimestamp(float(timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return timezone.now()


def pending_advert_event_rows(reference_ids=None):
    """Pending advert events shaped for ``build_advert_analytics``.

    Passing ``None`` returns every queued row. A list of ids scopes the rows to
    one advertiser's references, which is what the dashboards need. The original
    timestamp is restored so a chart drawn before the flush matches the chart
    drawn after it.
    """
    allowed = None if reference_ids is None else {str(value) for value in reference_ids}
    rows = []
    for row in pending_advert_events():
        if not isinstance(row, dict):
            continue
        reference_id = str(row.get("reference_id") or "")
        if allowed is not None and reference_id not in allowed:
            continue
        rows.append(
            {
                "reference_id": reference_id,
                "event_type": row.get("event_type") or "view",
                "source": (row.get("source") or "direct")[:16],
                "created_at": _as_datetime(row.get("occurred_at")),
            }
        )
    return rows


def pending_advert_event_counts(reference_ids=None):
    """Pending counts by reference id, shaped like the dashboard annotations.

    This lets reference cards show the same numbers as the chart before
    ``/health`` has written the queued rows to the database.
    """
    counts = {}
    for row in pending_advert_event_rows(reference_ids):
        reference_id = str(row.get("reference_id") or "")
        bucket = counts.setdefault(
            reference_id,
            {"view": 0, "click": 0, "abureport_click": 0, "other_click": 0},
        )
        event_type = row.get("event_type")
        if event_type == "view":
            bucket["view"] += 1
        elif event_type == "click":
            bucket["click"] += 1
            if row.get("source") == SOURCE_ABUREPORT:
                bucket["abureport_click"] += 1
            else:
                bucket["other_click"] += 1
    return counts


def _drop_resolved(key, resolved_ids):
    """Remove only the rows that were written (or deliberately discarded)."""
    rows = cache.get(key) or []
    if not isinstance(rows, list) or not resolved_ids:
        return
    remaining = [
        row
        for row in rows
        if not isinstance(row, dict) or row.get("id") not in resolved_ids
    ]
    if remaining:
        cache.set(key, remaining, timeout=None)
    else:
        cache.delete(key)


def flush_pending_events():
    """Write queued rows to the database, keeping them on failure for retry.

    Returns a small dict for logging. ``/health`` deliberately ignores the
    counts in its response; the numbers are only for the server log.
    """
    result = {"story_views": 0, "advert_events": 0, "flushed": False}
    if not cache.add(FLUSH_LOCK_KEY, "1", timeout=_FLUSH_LOCK_SECONDS):
        return result

    from BLOG.models import StoryView
    from Partner.models import AdvertEvent, AdvertReference

    try:
        story_rows = pending_story_views()
        advert_rows = pending_advert_events()
        if not story_rows and not advert_rows:
            result["flushed"] = True
            return result

        reference_ids = {
            str(row.get("reference_id") or "")
            for row in advert_rows
            if isinstance(row, dict)
        }
        live_references = {
            str(pk)
            for pk in AdvertReference.objects.filter(pk__in=reference_ids).values_list(
                "pk", flat=True
            )
        }
        written_story_ids = set()
        resolved_advert_ids = set()

        for row in story_rows:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            try:
                #   One row is all or nothing. A failed timestamp update must
                #   not leave a database row behind while the cache row is
                #   kept for the next retry.
                with transaction.atomic():
                    story_view = StoryView.objects.create(
                        blog_id=row.get("blog_id"),
                        user_id=row.get("user_id") or None,
                        source=(row.get("source") or "direct")[:32],
                    )
                    #   created_at is auto_now_add, so the original visit time
                    #   is put back with a targeted update after the insert.
                    StoryView.objects.filter(pk=story_view.pk).update(
                        created_at=_as_datetime(row.get("occurred_at"))
                    )
                result["story_views"] += 1
                if row_id is not None:
                    written_story_ids.add(row_id)
            except Exception as exc:
                error_logger(msg=f"ANALYTICS FLUSH: story view kept in cache: {exc}")

        for row in advert_rows:
            if not isinstance(row, dict):
                continue
            row_id = row.get("id")
            reference_id = str(row.get("reference_id") or "")
            #   A story advert with no reference is counted while it is in
            #   cache only; there is no generic event table to write it to.
            if reference_id not in live_references:
                if row_id is not None:
                    resolved_advert_ids.add(row_id)
                continue
            try:
                with transaction.atomic():
                    event = AdvertEvent.objects.create(
                        reference_id=reference_id,
                        event_type=row.get("event_type") or AdvertEvent.EVENT_VIEW,
                        source=(row.get("source") or "direct")[:16],
                        target_url=row.get("target_url", ""),
                        path=row.get("path", ""),
                        referrer=row.get("referrer", ""),
                        ip_hash=row.get("ip_hash", ""),
                        user_agent=row.get("user_agent", ""),
                        session_key=row.get("session_key", ""),
                    )
                    AdvertEvent.objects.filter(pk=event.pk).update(
                        created_at=_as_datetime(row.get("occurred_at"))
                    )
                result["advert_events"] += 1
                if row_id is not None:
                    resolved_advert_ids.add(row_id)
            except Exception as exc:
                error_logger(msg=f"ANALYTICS FLUSH: advert event kept in cache: {exc}")

        #   Only the rows that made it to the database (or have no destination
        #   table) leave the cache. A failed row stays for the next probe, and
        #   is never written twice.
        _drop_resolved(STORY_VIEW_KEY, written_story_ids)
        _drop_resolved(ADVERT_EVENT_KEY, resolved_advert_ids)
        result["flushed"] = not pending_story_views() and not pending_advert_events()
        if result["flushed"]:
            info_logger(
                msg=(
                    "ANALYTICS FLUSH: "
                    f"story_views={result['story_views']} advert_events={result['advert_events']}"
                )
            )
        else:
            error_logger(msg="ANALYTICS FLUSH: some events kept in cache for retry")
        return result
    except Exception as exc:
        error_logger(msg=f"ANALYTICS FLUSH FAILED (events kept in cache): {exc}")
        return result
    finally:
        cache.delete(FLUSH_LOCK_KEY)
