"""Analytics aggregation for the ADMIN panel.

Every number ANALYTICS draws is built here, so the fragment views in
ADMIN.views stay thin and the bucketing rules live in one place.

Design notes
------------
*   All timestamps are pulled from the database in the requested window and
    bucketed in Python. That keeps "per 2 days" (which no database date
    function gives us) and the Monday aligned week rule working identically
    on SQLite (dev) and Postgres (prod), instead of relying on TruncWeek /
    extract(), which differ between backends. The windows are small (a year
    at most) so the row counts stay modest.
*   Every helper returns plain dicts ready for `json_script`, never a
    QuerySet, so a template can ship them straight to the chart renderer.
"""

from datetime import timedelta

from django.db import DatabaseError, transaction
from django.utils import timezone

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, BlogLike, StoryView

#   -------------------------------------------------------------------------
#   PERIODS THE UI CAN ASK FOR
#   -------------------------------------------------------------------------
#   Bar chart: how far back stories-per-week runs. Default is one month; the
#   dropdown offers the longer windows.
STORY_PERIODS = {
    "1m": 4,
    "3m": 13,
    "6m": 26,
    "1y": 52,
}
DEFAULT_STORY_PERIOD = "1m"

#   Line chart: bucket size (day / 2 days / week) and the window it covers.
TREND_BUCKETS = {
    "day": 1,
    "2day": 2,
    "week": 7,
}
DEFAULT_TREND_BUCKET = "day"

TREND_RANGES = {
    "30d": 30,
    "90d": 90,
    "6m": 182,
    "1y": 365,
}
DEFAULT_TREND_RANGE = "30d"

#   One colour per series, matched to the checkbox legend in analytics.js.
SERIES_META = [
    {"key": "users", "name": "New users", "color": "#2563eb"},
    {"key": "views", "name": "Total views", "color": "#16a34a"},
    {"key": "stories", "name": "Stories", "color": "#d97706"},
    {"key": "likes", "name": "Likes", "color": "#dc2626"},
]

#   Dropdown options, in the order the shell renders them. Kept beside the
#   period dictionaries above so a value can never appear in a menu that the
#   aggregation helper does not understand.
STORY_PERIOD_CHOICES = [
    ("1m", "Last month"),
    ("3m", "Last 3 months"),
    ("6m", "Last 6 months"),
    ("1y", "Last 12 months"),
]
TREND_BUCKET_CHOICES = [
    ("day", "Per day"),
    ("2day", "Per 2 days"),
    ("week", "Per week"),
]
TREND_RANGE_CHOICES = [
    ("30d", "Last 30 days"),
    ("90d", "Last 90 days"),
    ("6m", "Last 6 months"),
    ("1y", "Last 12 months"),
]


def _local_midnight(moment):
    """Midnight, local time, for the day `moment` falls on."""
    return timezone.localtime(moment).replace(hour=0, minute=0, second=0, microsecond=0)


def _monday_midnight(moment):
    """Midnight of the Monday of the week `moment` falls in."""
    local = _local_midnight(moment)
    return local - timedelta(days=local.weekday())


def _safe_values(queryset, field):
    """Return a plain list of datetimes, or [] if the table is not migrated yet.

    StoryView in particular will not exist until the migration that adds it is
    applied, and ANALYTICS must render an empty chart rather than 500 while
    that is still pending. The atomic() savepoint means the failed read rolls
    back on its own and never poisons a surrounding transaction.
    """
    try:
        with transaction.atomic():
            return list(queryset.values_list(field, flat=True))
    except DatabaseError:
        return []


def _bucket_counts(stamps, start, size, count):
    """Drop each timestamp into its bucket. `start` is the first bucket edge."""
    counts = [0] * count
    for stamp in stamps:
        offset = timezone.localtime(stamp) - start
        index = int(offset // size)
        if 0 <= index < count:
            counts[index] += 1
    return counts


def _fmt_day(moment):
    return f"{moment:%b} {moment.day}"


def _fmt_range(start, end):
    if start.month == end.month:
        return f"{start:%b} {start.day}\u2013{end.day}"
    return f"{start:%b} {start.day} \u2013 {end:%b} {end.day}"


def stories_per_week(period):
    """Bar chart data: one bar per Monday aligned week in the selected window.

    Returns a ready to render dict:
        {type, labels, tooltips, series: [ {name, color, values} ], total}
    """
    weeks = STORY_PERIODS.get(period, STORY_PERIODS[DEFAULT_STORY_PERIOD])
    now = timezone.localtime()
    start = _monday_midnight(now - timedelta(weeks=weeks - 1))

    stamps = _safe_values(Blog.objects.filter(date_created__gte=start), "date_created")
    values = _bucket_counts(stamps, start, timedelta(days=7), weeks)

    labels = []
    tooltips = []
    for index in range(weeks):
        bucket_start = start + timedelta(weeks=index)
        bucket_end = bucket_start + timedelta(days=6)
        labels.append(_fmt_day(bucket_start))
        count = values[index]
        tooltips.append(
            f"Week of {_fmt_range(bucket_start, bucket_end)} \u2014 "
            f"{count} stor{'y' if count == 1 else 'ies'}"
        )

    return {
        "type": "bar",
        "labels": labels,
        "tooltips": tooltips,
        "series": [{"name": "Stories", "color": "#2563eb", "values": values}],
        "total": sum(values),
    }


def trends(bucket, selected_range, series_keys):
    """Line chart data: the selected series bucketed over the selected window.

    `series_keys` is the set of keys the reader left ticked (users / views /
    stories / likes); anything not named is simply left out of the response.
    """
    bucket_days = TREND_BUCKETS.get(bucket, TREND_BUCKETS[DEFAULT_TREND_BUCKET])
    range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
    now = timezone.localtime()

    if bucket == "week":
        start = _monday_midnight(now - timedelta(days=range_days - 1))
    else:
        start = _local_midnight(now - timedelta(days=range_days - 1))

    size = timedelta(days=bucket_days)
    #   +1 so the partial final bucket (today) is always included.
    count = max(int((now - start) // size) + 1, 1)

    sources = {
        "users": lambda: _safe_values(Auth.objects.filter(date_joined__gte=start), "date_joined"),
        "views": lambda: _safe_values(StoryView.objects.filter(created_at__gte=start), "created_at"),
        "stories": lambda: _safe_values(Blog.objects.filter(date_created__gte=start), "date_created"),
        "likes": lambda: _safe_values(BlogLike.objects.filter(created_at__gte=start), "created_at"),
    }

    series = []
    for meta in SERIES_META:
        if meta["key"] not in series_keys:
            continue
        stamps = sources[meta["key"]]()
        series.append(
            {
                "key": meta["key"],
                "name": meta["name"],
                "color": meta["color"],
                "values": _bucket_counts(stamps, start, size, count),
            }
        )

    labels = [_fmt_day(start + timedelta(days=bucket_days * index)) for index in range(count)]

    return {
        "type": "line",
        "labels": labels,
        "series": series,
        "bucket": bucket,
        "range": selected_range,
    }
