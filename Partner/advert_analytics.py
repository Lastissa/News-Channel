"""Shared chart data for advert views and clicks.

Dates are derived from AdvertEvent.created_at -- there is deliberately no
duplicate date column. The project runs in Africa/Lagos, so a "day" here is a
local calendar day, not a UTC one. Both the advertiser dashboard and the staff
Ads desk use this helper, which keeps their numbers and labels identical.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone

from Partner.models import AdvertEvent

RANGE_CHOICES = (
    {"key": "7", "label": "7 days"},
    {"key": "30", "label": "30 days"},
    {"key": "90", "label": "90 days"},
    {"key": "all", "label": "All time"},
)
RANGE_DAYS = {row["key"]: int(row["key"]) for row in RANGE_CHOICES if row["key"] != "all"}
DEFAULT_RANGE = "30"

_PIE_COLORS = ("#e8b84a", "#6b7c93")


def normalize_range(value):
    key = str(value or "").strip().lower()
    if key in RANGE_DAYS or key == "all":
        return key
    return DEFAULT_RANGE


def _window(range_key, now=None):
    """Return (start_datetime_or_None, local_end_date)."""
    tz = timezone.get_current_timezone()
    local_now = timezone.localtime(now or timezone.now(), tz)
    if range_key == "all":
        return None, local_now.date()
    start_date = local_now.date() - timedelta(days=RANGE_DAYS[range_key] - 1)
    return timezone.make_aware(datetime.combine(start_date, time.min), tz), local_now.date()


def build_advert_analytics(events, range_key=DEFAULT_RANGE, now=None, element_prefix="advert"):
    """Turn an AdvertEvent queryset into two ready-to-draw chart payloads.

    ``events`` must already be scoped to the advertiser/staff being served.
    Direct traffic is folded into "Other sources" so the click pie has exactly
    the two slices requested: From Abureport and everything else.
    """
    range_key = normalize_range(range_key)
    start_dt, end_date = _window(range_key, now)
    tz = timezone.get_current_timezone()

    rows = list(events.values_list("created_at", "event_type", "source"))
    if start_dt is not None:
        rows = [row for row in rows if row[0] is None or row[0] >= start_dt]

    views_by_day = {}
    abureport_clicks = other_clicks = 0
    for created_at, event_type, source in rows:
        day = timezone.localtime(created_at, tz).date()
        if event_type == AdvertEvent.EVENT_VIEW:
            views_by_day[day] = views_by_day.get(day, 0) + 1
        elif event_type == AdvertEvent.EVENT_CLICK:
            if source == AdvertEvent.SOURCE_ABUREPORT:
                abureport_clicks += 1
            else:
                other_clicks += 1

    if start_dt is not None:
        first_day = start_dt.date()
    elif views_by_day:
        first_day = min(views_by_day)
    else:
        first_day = end_date

    dates = []
    current = first_day
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)

    view_values = [views_by_day.get(day, 0) for day in dates]
    click_values = [abureport_clicks, other_clicks]

    return {
        "range": range_key,
        "range_label": next(
            row["label"] for row in RANGE_CHOICES if row["key"] == range_key
        ),
        "totals": {
            "views": sum(view_values),
            "clicks": abureport_clicks + other_clicks,
            "abureport_clicks": abureport_clicks,
            "other_clicks": other_clicks,
            "click_rate": (
                round((abureport_clicks + other_clicks) / sum(view_values) * 100, 1)
                if view_values and sum(view_values)
                else 0
            ),
        },
        "view_chart": {
            "element_id": f"{element_prefix}-views",
            "data_id": f"{element_prefix}-views-data",
            "kind": "line",
            "name": "Views",
            "labels": [day.strftime("%d %b") for day in dates],
            "values": view_values,
            "has_data": any(view_values),
        },
        "click_chart": {
            "element_id": f"{element_prefix}-clicks",
            "data_id": f"{element_prefix}-clicks-data",
            "kind": "pie",
            "labels": ["From Abureport", "Other sources"],
            "values": click_values,
            "colors": list(_PIE_COLORS),
            "has_data": any(click_values),
        },
    }
