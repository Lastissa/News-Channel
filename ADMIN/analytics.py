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

from datetime import datetime, time, timedelta

from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, BlogLike, Comment, StoryView, get_category_choices
from HOME.models import CategorySubscription, ReadingHistory
from STAFF.models import AuthorFollow, StaffProfile

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

#   Line chart: bucket size and the window it covers. The two finest buckets
#   are sub-day (12 hours, 1 hour) so a chart can zoom into a single day's
#   shape; the coarser ones step by whole days. "Per month" is a calendar
#   bucket rather than a fixed number of days, so it is handled apart from this
#   map (see MONTH_BUCKET / _trend_frame).
TREND_BUCKETS = {
    "hour": timedelta(hours=1),
    "12hour": timedelta(hours=12),
    "day": timedelta(days=1),
    "2day": timedelta(days=2),
    "week": timedelta(days=7),
}
DEFAULT_TREND_BUCKET = "day"

#   The calendar-month bucket. A month is not a fixed width, so it cannot live
#   in TREND_BUCKETS alongside the day counts; these buckets are built from
#   first-of-month edges instead.
MONTH_BUCKET = "month"

TREND_RANGES = {
    "2d": 2,
    "7d": 7,
    "14d": 14,
    "30d": 30,
    "60d": 60,
    "90d": 90,
    "6m": 182,
    "1y": 365,
}
DEFAULT_TREND_RANGE = "30d"

#   The windows that make sense once the bucket is finer than a day. A day
#   scale window asked for by an hourly bucket would ask for 720 points, which
#   reads as a smear rather than a chart, so the range menu swaps to these
#   when the bucket is 12 hours or 1 hour (see the range swap in analytics.js).
TREND_SUB_RANGES = {
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "48h": timedelta(hours=48),
    "72h": timedelta(hours=72),
}
DEFAULT_TREND_SUB_RANGE = "24h"

#   One colour per series, matched to the checkbox legend in analytics.js.
SERIES_META = [
    {"key": "users", "name": "New users", "color": "#2563eb"},
    {"key": "views", "name": "Total views", "color": "#16a34a"},
    {"key": "stories", "name": "Stories", "color": "#d97706"},
    {"key": "likes", "name": "Likes", "color": "#dc2626"},
]

#   The series each chamber offers. Member lytics is about people, so the
#   story-open series lives on the Story lytics page instead and is not
#   offered (nor drawn by default) here.
MEMBER_TREND_SERIES = [meta for meta in SERIES_META if meta["key"] != "views"]
STORY_TREND_SERIES = [meta for meta in SERIES_META if meta["key"] in {"stories", "views"}]

#   The colours a category series wears. Assigned by position in the category
#   list, so a category keeps the same colour whether it is drawn alone or
#   beside the others.
CATEGORY_SERIES_COLORS = [
    "#2563eb", "#d97706", "#16a34a", "#dc2626",
    "#7c3aed", "#0891b2", "#db2777", "#65a30d",
]

#   Per-story performance chart: the three signals an editor can overlay for a
#   single chosen story. Same shape as SERIES_META so the JS renderer does not
#   need to know which card it is drawing.
STORY_PERFORMANCE_SERIES = [
    {"key": "views", "name": "Views", "color": "#16a34a"},
    {"key": "likes", "name": "Likes", "color": "#dc2626"},
    {"key": "comments", "name": "Comments", "color": "#2563eb"},
]
DEFAULT_STORY_PERFORMANCE_SERIES = ["views", "likes", "comments"]

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
    ("hour", "Per hour"),
    ("12hour", "Per 12 hours"),
    ("day", "Per day"),
    ("2day", "Per 2 days"),
    ("week", "Per week"),
    ("month", "Per month"),
]
TREND_RANGE_CHOICES = [
    ("2d", "Last 2 days"),
    ("7d", "Last 7 days"),
    ("14d", "Last 14 days"),
    ("30d", "Last 30 days"),
    ("60d", "Last 2 months"),
    ("90d", "Last 3 months"),
    ("6m", "Last 6 months"),
    ("1y", "Last 12 months"),
]
TREND_SUB_RANGE_CHOICES = [
    ("6h", "Last 6 hours"),
    ("12h", "Last 12 hours"),
    ("24h", "Last 24 hours"),
    ("48h", "Last 2 days"),
    ("72h", "Last 3 days"),
]


#   The project's week runs Sunday to Saturday (Python: Monday is 0, Sunday is
#   6). STAFF.views uses the same rule for "author of the week", so every part
#   of the site agrees on where a week begins.
WEEK_START_WEEKDAY = 6

#   Overview window. "Last 30 days" is a rolling window rather than a calendar
#   month, so it always means the same span wherever it is read.
OVERVIEW_MONTH_DAYS = 30


def _local_midnight(moment):
    """Midnight, local time, for the day `moment` falls on."""
    return timezone.localtime(moment).replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start(moment):
    """Midnight of the Sunday that begins the week `moment` falls in."""
    local = _local_midnight(moment)
    return local - timedelta(days=(local.weekday() - WEEK_START_WEEKDAY) % 7)


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


def _bucket_label(moment, size):
    """The x-axis label for one bucket edge.

    A bucket shorter than a day needs the hour to be readable, so it reads
    "2pm" or "14:00" rather than repeating the same date all day; a day or
    longer keeps the plain "Oct 18" wording.
    """
    if size >= timedelta(days=1):
        return _fmt_day(moment)
    if size >= timedelta(hours=12):
        #   A 12-hour bucket: name the half of the day it opens on.
        hour = moment.hour
        if hour == 0:
            return "12am"
        if hour == 12:
            return "12pm"
        return f"{hour}am" if hour < 12 else f"{hour - 12}pm"
    return f"{moment:%H:%M}"


def _floor_to_bucket(moment, size):
    """The edge of the bucket `moment` falls in, in local time.

    A day bucket opens at midnight, a 12-hour bucket at midnight or noon, and
    an hourly bucket on the hour. Without this a sub-day chart would start at
    an arbitrary minute and every label would be a slightly different time.
    """
    local = timezone.localtime(moment)
    if size >= timedelta(days=1):
        return _local_midnight(local)
    if size >= timedelta(hours=12):
        return local.replace(hour=0 if local.hour < 12 else 12, minute=0, second=0, microsecond=0)
    return local.replace(minute=0, second=0, microsecond=0)


def _month_start(moment):
    """The first midnight of the month `moment` falls in."""
    local = timezone.localtime(moment)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _fmt_range(start, end):
    if start.month == end.month:
        return f"{start:%b} {start.day}\u2013{end.day}"
    return f"{start:%b} {start.day} \u2013 {end:%b} {end.day}"


def stories_per_week(period):
    """Bar chart data: one bar per Sunday aligned week in the selected window.

    Returns a ready to render dict:
        {type, labels, tooltips, series: [ {name, color, values} ], total}
    """
    weeks = STORY_PERIODS.get(period, STORY_PERIODS[DEFAULT_STORY_PERIOD])
    now = timezone.localtime()
    start = _week_start(now - timedelta(weeks=weeks - 1))

    stamps = _safe_values(Blog.objects.filter(date_created__gte=start), "date_created")
    values = _bucket_counts(stamps, start, timedelta(days=7), weeks)

    labels = []
    tooltips = []
    #   One ISO week-start per bar: the key analytics.js hands back to the week
    #   endpoint when a bar is pressed, so the queryset never has to re-derive
    #   the chart's own frame.
    bucket_starts = []
    for index in range(weeks):
        bucket_start = start + timedelta(weeks=index)
        bucket_end = bucket_start + timedelta(days=6)
        labels.append(_fmt_day(bucket_start))
        bucket_starts.append(bucket_start.date().isoformat())
        count = values[index]
        tooltips.append(
            f"Week of {_fmt_range(bucket_start, bucket_end)} \u2014 "
            f"{count} stor{'y' if count == 1 else 'ies'}"
        )

    return {
        "type": "bar",
        "labels": labels,
        "tooltips": tooltips,
        "bucket_starts": bucket_starts,
        "series": [{"name": "Stories", "color": "#2563eb", "values": values}],
        "total": sum(values),
    }


def _week_start_date(day):
    """The Sunday on or before `day` (a datetime.date)."""
    return day - timedelta(days=(day.weekday() - WEEK_START_WEEKDAY) % 7)


def week_window(value):
    """Turn a `week` querystring value into that week's (start, end).

    `value` names any day of the week as an ISO date; the window is the local
    Sunday and the following Sunday (exclusive), so both halves of this card
    agree on where a week begins. A missing or malformed value, and a week
    that has not started yet, give None -- the endpoint answers 400 rather
    than showing an empty placard that reads like "nothing was published".
    """
    day = parse_date((value or "").strip())
    if day is None:
        return None

    start_date = _week_start_date(day)
    if start_date > _week_start_date(timezone.localdate()):
        return None

    start = timezone.make_aware(datetime.combine(start_date, time.min))
    return start, start + timedelta(days=7)


def week_stories(start, end):
    """The stories behind one bar: everything published in [start, end).

    Oldest first, so the placard reads in the order the week happened, and
    shaped into plain dicts the partial lays out -- the same rule every other
    helper here follows. `updated` is the story's real post-publish edit time
    (`last_edited`, not the auto_now `last_updated`, which is stamped at
    creation too), so it stays blank until a staff member edits the story.
    """
    stories = (
        Blog.objects.filter(date_created__gte=start, date_created__lt=end)
        .select_related("author")
        .order_by("date_created", "pk")
    )
    rows = [
        {
            "heading": story.heading,
            "slug": story.slug,
            "author": story.author_name,
            "posted": timezone.localtime(story.date_created),
            "updated": timezone.localtime(story.last_edited) if story.last_edited else None,
        }
        for story in stories
    ]
    last_day = end - timedelta(days=1)
    return {
        "label": f"Week of {_fmt_range(start, last_day)}, {last_day.year}",
        "count": len(rows),
        "stories": rows,
    }


def _custom_window(start_iso, end_iso):
    """Turn a custom start/end pair into a (start, end_exclusive) window.

    Both dates must be present, well formed and ordered; anything else returns
    None so the caller quietly falls back to the preset range. A future end is
    clamped to today so a hand typed querystring cannot chart days that have
    not happened yet.
    """
    start_day = parse_date((start_iso or "").strip())
    end_day = parse_date((end_iso or "").strip())
    if start_day is None or end_day is None:
        return None

    today = timezone.localdate()
    if end_day > today:
        end_day = today
    if start_day > end_day:
        return None

    start = timezone.make_aware(datetime.combine(start_day, time.min))
    end_exclusive = timezone.make_aware(datetime.combine(end_day + timedelta(days=1), time.min))
    return start, end_exclusive


def _cold_window(cooled_since):
    """The age gate for the cold list, as a whole number of days.

    The admin may hand the Reading card a "cooled since" date: a story is cold
    when it was published on or before that date. The gate is how long ago that
    was, so a *later* date admits more stories and today admits everything
    published today or earlier. A missing, malformed or future date falls back
    to the default, so the list can never be emptied by a bad querystring.
    """
    day = parse_date((cooled_since or "").strip())
    if day is None:
        return READING_COLD_MIN_AGE_DAYS
    days = (timezone.localdate() - day).days
    if days < 0:
        return READING_COLD_MIN_AGE_DAYS
    return days


def _month_starts(start, last):
    """First-of-month edges from `start`'s month through `last`'s month."""
    first = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last = last.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months = []
    cursor = first
    while cursor <= last:
        months.append(cursor)
        #   Jump to the 1st of the next month without a calendar library.
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return months


def _month_counts(stamps, months):
    """Drop each timestamp into its calendar-month bucket."""
    counts = [0] * len(months)
    base = months[0]
    for stamp in stamps:
        local = timezone.localtime(stamp)
        index = (local.year - base.year) * 12 + (local.month - base.month)
        if 0 <= index < len(counts):
            counts[index] += 1
    return counts


def _trend_frame(bucket, selected_range, start_iso=None, end_iso=None, not_before=None):
    """Resolve the chart window and its bucket edges.

    A valid custom start/end pair overrides the preset range. Returns a plain
    dict the trend / growth helpers share: the window, the bucket labels, the
    number of buckets, and the edge list (fixed timedelta or month starts).

    `not_before` is a floor on the window's start: a story's chart opens on
    the day the story was published, so the left of the chart is never an
    empty stretch of days the story could not have been read in. The range
    still bounds how far back the chart looks.
    """
    now = timezone.localtime()
    custom = _custom_window(start_iso, end_iso)
    month = bucket == MONTH_BUCKET
    size = TREND_BUCKETS.get(bucket, TREND_BUCKETS[DEFAULT_TREND_BUCKET])
    sub_day = size < timedelta(days=1)

    if custom is not None:
        start, end_exclusive = custom
        #   Last instant the window can contain, so the +1 bucket rule below
        #   never appends an empty trailing bucket.
        span_end = end_exclusive - timedelta(microseconds=1)
    elif sub_day:
        #   A day scale window would ask an hourly bucket for 720 points, so a
        #   sub-day bucket reads its window from the hour scale list instead.
        #   A day scale key can only reach here with the script off (the menu
        #   swaps scales otherwise), and the longest sub-day window is the
        #   honest reading of it -- never a month of hourly points.
        window = TREND_SUB_RANGES.get(selected_range, TREND_SUB_RANGES["72h"])
        start = _floor_to_bucket(now - window, size)
        end_exclusive = None
        span_end = now
    else:
        range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
        if bucket == "week":
            start = _week_start(now - timedelta(days=range_days - 1))
        else:
            start = _local_midnight(now - timedelta(days=range_days - 1))
        end_exclusive = None
        span_end = now

    if not_before is not None:
        floor = _month_start(not_before) if month else _floor_to_bucket(not_before, size)
        if floor > start:
            start = floor
            if end_exclusive is not None and end_exclusive <= start:
                #   The floor has eaten the whole custom window.
                end_exclusive = None
                span_end = now

    if month:
        months = _month_starts(start, span_end)
        return {
            "start": start,
            "end_exclusive": end_exclusive,
            "months": months,
            "size": None,
            "count": len(months),
            "labels": [f"{moment:%b %Y}" for moment in months],
        }

    #   +1 so the partial final bucket (today) is always included.
    count = max(int((span_end - start) // size) + 1, 1)
    return {
        "start": start,
        "end_exclusive": end_exclusive,
        "months": None,
        "size": size,
        "count": count,
        "labels": [_bucket_label(start + size * index, size) for index in range(count)],
    }


def _frame_counts(frame, stamps):
    """Bucket a list of timestamps inside an already resolved frame."""
    if frame["months"] is not None:
        return _month_counts(stamps, frame["months"])
    return _bucket_counts(stamps, frame["start"], frame["size"], frame["count"])


def _windowed_values(queryset, field, frame):
    """Timestamps of `queryset` inside the frame's [start, end) window."""
    queryset = queryset.filter(**{f"{field}__gte": frame["start"]})
    if frame["end_exclusive"] is not None:
        queryset = queryset.filter(**{f"{field}__lt": frame["end_exclusive"]})
    return _safe_values(queryset, field)


def trends(bucket, selected_range, series_keys, start_iso=None, end_iso=None):
    """Line chart data: the selected series bucketed over the selected window.

    `series_keys` is the set of keys the reader left ticked (users / views /
    stories / likes); anything not named is simply left out of the response.
    A custom start/end pair overrides the preset range when both are valid.
    """
    frame = _trend_frame(bucket, selected_range, start_iso, end_iso)

    sources = {
        "users": lambda: _windowed_values(Auth.objects.all(), "date_joined", frame),
        "views": lambda: _windowed_values(StoryView.objects.all(), "created_at", frame),
        "stories": lambda: _windowed_values(Blog.objects.all(), "date_created", frame),
        "likes": lambda: _windowed_values(BlogLike.objects.all(), "created_at", frame),
    }

    series = []
    for meta in SERIES_META:
        if meta["key"] not in series_keys:
            continue
        series.append(
            {
                "key": meta["key"],
                "name": meta["name"],
                "color": meta["color"],
                "values": _frame_counts(frame, sources[meta["key"]]()),
            }
        )

    return {
        "type": "line",
        "labels": frame["labels"],
        "series": series,
        "bucket": bucket,
        "range": selected_range,
    }


def members_growth(bucket, selected_range, start_iso=None, end_iso=None):
    """Line chart data: the running total of member accounts over the window.

    Each bucket carries every member that existed by the end of it -- members
    that joined before the window are the baseline, so the line keeps rising
    instead of resetting to zero. With no members at all the line is simply
    flat at zero.
    """
    frame = _trend_frame(bucket, selected_range, start_iso, end_iso)
    members = Auth.objects.filter(is_staff=False, is_admin=False, is_superuser=False)

    baseline = members.filter(date_joined__lt=frame["start"]).count()
    counts = _frame_counts(frame, _windowed_values(members, "date_joined", frame))

    running = []
    total = baseline
    for added in counts:
        total += added
        running.append(total)

    return {
        "type": "line",
        "labels": frame["labels"],
        "series": [
            {"key": "members", "name": "Total members", "color": "#7c3aed", "values": running}
        ],
        "total": total,
        "baseline": baseline,
        "bucket": bucket,
        "range": selected_range,
    }


#   -------------------------------------------------------------------------
#   MEMBER OVERVIEW -- the "Quick overview" card and its top-bar badge
#   -------------------------------------------------------------------------
#   Three member figures, each counted over the same windows: today, the
#   current week (Sunday to now) and the last 30 days.
#
#   "Change since last week" is the current (unfinished) week measured against
#   the whole of the previous week, which is what the owner asked for. Weeks
#   start on Sunday, so both sides of the comparison are Sunday anchored.

def _count_since(queryset, field, start, end=None):
    """Count the rows in `queryset` whose `field` falls in [start, end)."""
    rows = queryset.filter(**{f"{field}__gte": start})
    if end is not None:
        rows = rows.filter(**{f"{field}__lt": end})
    return rows.count()


def _new_users(start, end=None):
    """Accounts created in the window."""
    return _count_since(Auth.objects.all(), "date_joined", start, end)


def _active_readers(start, end=None):
    """Distinct accounts that opened a story in the window.

    Counted from ReadingHistory (one row per reader/story pair, user always
    set) rather than StoryView, so this matches the Members table's own "read a
    story" activity filter instead of also counting anonymous opens.
    """
    rows = ReadingHistory.objects.filter(read_at__gte=start)
    if end is not None:
        rows = rows.filter(read_at__lt=end)
    return rows.values("user_id").distinct().count()


def _stories_published(start, end=None):
    """Stories whose publish timestamp falls in the window."""
    return _count_since(Blog.objects.all(), "date_created", start, end)


def _members_total():
    """Every current member account, the running audience size.

    Members only -- the same complement of staff that the Members table lists,
    so "Current members" and the directory can never disagree.
    """
    return Auth.objects.filter(is_staff=False, is_admin=False, is_superuser=False).count()


def member_overview():
    """The Quick overview card: new users, active readers, current members."""
    now = timezone.localtime()
    today = _local_midnight(now)
    week = _week_start(now)
    last_week = week - timedelta(days=7)
    month = today - timedelta(days=OVERVIEW_MONTH_DAYS - 1)

    users_week = _new_users(week)
    last_week_users = _new_users(last_week, week)
    delta = users_week - last_week_users

    return {
        "users": {
            "today": _new_users(today),
            "week": users_week,
            "last_week": last_week_users,
            "month": _new_users(month),
            #   Signed so the direction is readable without relying on colour
            #   alone: +8 / -3 / 0.
            "delta_display": f"+{delta}" if delta > 0 else (f"-{abs(delta)}" if delta < 0 else "0"),
            "delta_tone": "is-up" if delta > 0 else ("is-down" if delta < 0 else "is-flat"),
        },
        "readers": {
            "today": _active_readers(today),
            "week": _active_readers(week),
            "month": _active_readers(month),
        },
        "stories": {
            "today": _stories_published(today),
            "week": _stories_published(week),
            "month": _stories_published(month),
        },
        "members_total": _members_total(),
    }


def member_new_today():
    """The top-bar badge figure: accounts created since local midnight."""
    return _new_users(_local_midnight(timezone.localtime()))


def stories_overview():
    """Stories published today / this week / the last 30 days.

    Split out of member_overview so the Story lytics "Stories published" tile
    can carry just this figure without running the member queries beside it.
    """
    now = timezone.localtime()
    today = _local_midnight(now)
    week = _week_start(now)
    month = today - timedelta(days=OVERVIEW_MONTH_DAYS - 1)
    return {
        "today": _stories_published(today),
        "week": _stories_published(week),
        "month": _stories_published(month),
    }


#   -------------------------------------------------------------------------
#   READING & EDITORIAL -- the "Reading & editorial" card on ANALYTICS
#   -------------------------------------------------------------------------
#   Every figure is measured over the SAME range control as Trends, so a 7 day
#   reading and a yearly reading never disagree. "Views" always means StoryView
#   events INSIDE the window, never the cumulative Blog.views -- otherwise every
#   range would report the same all-time leaderboard and the range control would
#   be a lie.

READING_TOP_STORIES = 10        #   rows in the top-read table
READING_TOP_CATEGORIES = 8      #   categories in the published-vs-read list
READING_COLD_LIMIT = 10         #   cold-story entries shown before the "and N more" line
#   Cold means "barely read at all", not "never read": a story with a handful of
#   views is still unpublished in practice. The threshold is a cap, inclusive.
READING_COLD_MAX_VIEWS = 5      #   views at or below this reads as cold
#   A story is only "cold" once it has had a fair couple of days to be
#   discovered, so a story published this morning is never counted.
READING_COLD_MIN_AGE_DAYS = 2   #   default age gate; the admin can override it


def _safe_rows(rows):
    """Materialise an aggregation queryset, or [] if its table is missing.

    StoryView will not exist until its migration is applied, and ANALYTICS must
    draw an empty panel rather than 500 while that is still pending. The
    atomic() savepoint keeps a failed read from poisoning the surrounding
    transaction, exactly like _safe_values above.
    """
    try:
        with transaction.atomic():
            return list(rows)
    except DatabaseError:
        return []


def _range_label(selected_range):
    """The human label behind a range key, e.g. "90d" -> "Last 3 months"."""
    return dict(TREND_RANGE_CHOICES).get(selected_range, "")


def _top_read_stories(start):
    """The most-read stories in the window, ranked by StoryView events."""
    view_rows = _safe_rows(
        StoryView.objects.filter(created_at__gte=start)
        .values("blog_id")
        .annotate(views=Count("id"))
        .order_by("-views")[:READING_TOP_STORIES]
    )
    if not view_rows:
        return []

    ids = [row["blog_id"] for row in view_rows]
    blogs = Blog.objects.in_bulk(ids)
    like_rows = _safe_rows(
        BlogLike.objects.filter(created_at__gte=start, blog_id__in=ids)
        .values("blog_id")
        .annotate(likes=Count("id"))
    )
    likes = {row["blog_id"]: row["likes"] for row in like_rows}

    stories = []
    for row in view_rows:
        story = blogs.get(row["blog_id"])
        if story is None:      #   deleted between the two reads
            continue
        views = row["views"]
        stories.append(
            {
                "heading": story.heading,
                "slug": story.slug,
                "category": story.category,
                "views": views,
                "likes": likes.get(story.pk, 0),
            }
        )
    return stories


def _category_read_vs_published(start):
    """Per-category stories published vs read in the window.

    The gap is the point: a category that is published heavily but barely read
    shows up as a wide bar next to a tall "published" count.
    """
    published = {
        row["category"]: row["n"]
        for row in Blog.objects.filter(date_created__gte=start)
        .values("category")
        .annotate(n=Count("id"))
    }
    views = {
        row["blog__category"]: row["n"]
        for row in _safe_rows(
            StoryView.objects.filter(created_at__gte=start)
            .values("blog__category")
            .annotate(n=Count("id"))
        )
    }

    rows = [
        {
            "category": name,
            "published": published.get(name, 0),
            "views": views.get(name, 0),
            "avg_views": round(views.get(name, 0) / published[name]) if published.get(name) else 0,
        }
        for name in set(published) | set(views)
    ]
    rows.sort(key=lambda item: (item["views"], item["published"]), reverse=True)
    rows = rows[:READING_TOP_CATEGORIES]

    top = max((row["views"] for row in rows), default=0)
    for row in rows:
        row["bar_percent"] = round(row["views"] * 100 / top) if top else 0
    return rows


def _cold_stories(now, min_age_days=None):
    """The barely-read backlog: stories at or below 5 views, published before today.

    "Cold" used to mean exactly zero views, which hid the far larger pile of
    stories that drew one or two reads and were never really published. The cap
    is inclusive (5 views or fewer) and the age gate keeps a story published
    this morning out of the list, because it has not had a chance yet.

    `min_age_days` is the age gate; the Reading card passes the admin's own
    "cooled since" date, and any value falls back to the default when it is
    missing or nonsensical.

    Uses the stored Blog.views counter (written in the same branch as StoryView)
    so this stays one indexed query rather than an appetite for the whole view
    history.
    """
    age_days = READING_COLD_MIN_AGE_DAYS
    if min_age_days is not None:
        try:
            age_days = max(int(min_age_days), 0)
        except (TypeError, ValueError):
            age_days = READING_COLD_MIN_AGE_DAYS

    cutoff = now - timedelta(days=age_days)
    cold = (
        Blog.objects.filter(views__lte=READING_COLD_MAX_VIEWS, date_created__lt=cutoff)
        .order_by("-date_created")
    )
    total = cold.count()
    items = [
        {
            "heading": story.heading,
            "slug": story.slug,
            "category": story.category,
            "views": story.views,
            "posted": timezone.localtime(story.date_created),
        }
        for story in cold[:READING_COLD_LIMIT]
    ]
    return {
        "older_than": age_days,
        "max_views": READING_COLD_MAX_VIEWS,
        "total": total,
        "remaining": max(total - len(items), 0),
        "items": items,
    }


def reading_editorial(selected_range, cooled_since=None):
    """The "Reading & editorial" card: what members read over the range.

    Returns the top-read stories, per-category published-vs-read, and the
    barely-read backlog. The first two are measured to the same window, so the
    card reads as one story; the backlog has its own age gate, which the admin
    can move with the "cooled since" date.
    """
    range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
    now = timezone.localtime()
    start = _local_midnight(now - timedelta(days=range_days - 1))
    age_days = _cold_window(cooled_since)

    #   The gate rounds to whole days, so the date box can show back exactly what
    #   that became: "cooled since <date>" is unambiguous when a typed date sits
    #   mid-day.
    today = timezone.localdate(now)
    cooled_day = today - timedelta(days=age_days)

    return {
        "range": selected_range,
        "range_label": _range_label(selected_range),
        "top_stories": _top_read_stories(start),
        "top_categories": _category_read_vs_published(start),
        "cold_stories": _cold_stories(now, age_days),
        "cooled_since_value": cooled_day.isoformat(),
        "cooled_since_label": cooled_day,
        "cooled_since_default": (
            today - timedelta(days=READING_COLD_MIN_AGE_DAYS)
        ).isoformat(),
    }


#   -------------------------------------------------------------------------
#   STORIES PER DAY, BY CATEGORY -- the publishing rate of each subject
#   -------------------------------------------------------------------------
#   One line per category, each counting the stories published in that
#   category inside the bucket. The window is the same one every other chart
#   uses: a preset, or a custom start and end date when the admin wants
#   exactly two days, or exactly one week.


def category_palette(names):
    """{name: colour} for the given category names, in the order given.

    The colour follows the category's position in the list, so a category
    keeps the same colour whether it is drawn alone or beside the others.
    """
    return {
        name: CATEGORY_SERIES_COLORS[index % len(CATEGORY_SERIES_COLORS)]
        for index, name in enumerate(names)
    }


def category_names():
    """Every category the charts can talk about, in one stable order.

    The menu (the Category table) comes first, because that is the order the
    admin knows the categories by. A category that a story still carries but
    the menu has dropped follows it, alphabetically, so nothing a reader has
    published is ever left out of the count.
    """
    names = [name for name, _ in get_category_choices()]
    known = set(names)
    extra = sorted(
        {
            name
            for name in Blog.objects.values_list("category", flat=True).distinct()
            if name and name not in known
        }
    )
    return names + extra


def category_story_counts():
    """{category: stories published}, busiest first.

    Only used to decide which categories a chart starts out drawing: a card
    that opens on subjects nobody has published in reads as an empty chart,
    which is not the same thing as saying nothing has been published.
    """
    rows = _safe_rows(
        Blog.objects.values("category").annotate(n=Count("id")).order_by("-n")
    )
    return {row["category"]: row["n"] for row in rows if row["category"]}


def stories_per_day_by_category(
    bucket, selected_range, categories, palette, start_iso=None, end_iso=None
):
    """Line chart data: stories published per bucket, one line per category.

    `categories` is the set the admin left ticked and `palette` is the colour
    map for every category, so a category keeps its colour whatever else is
    drawn beside it. The buckets are the ones the trend charts use, so a day
    bucket really is one story-published-per-day reading.
    """
    frame = _trend_frame(bucket, selected_range, start_iso, end_iso)
    wanted = set(categories)
    chosen = [name for name in palette if name in wanted]

    rows = _safe_rows(
        Blog.objects.filter(date_created__gte=frame["start"], category__in=chosen)
        .values("date_created", "category")
    )
    stamps = {}
    for row in rows:
        stamps.setdefault(row["category"], []).append(row["date_created"])

    series = []
    for name in chosen:
        if frame["months"] is not None:
            values = _month_counts(stamps.get(name, []), frame["months"])
        else:
            values = _frame_counts(frame, stamps.get(name, []))
        series.append(
            {"key": name, "name": name, "color": palette[name], "values": values}
        )

    return {
        "type": "line",
        "labels": frame["labels"],
        "series": series,
        "bucket": bucket,
        "range": selected_range,
        "total": sum(sum(item["values"]) for item in series),
    }


#   -------------------------------------------------------------------------
#   CATEGORY COMPARISON -- two subjects, head to head
#   -------------------------------------------------------------------------
#   The numbers a comparison is made of: how many stories each category
#   published, how many likes and how many comments those stories drew.

COMPARISON_METRICS = [
    ("Stories", "stories"),
    ("Likes", "likes"),
    ("Comments", "comments"),
]


def category_comparison(
    name_a, name_b, selected_range, palette, start_iso=None, end_iso=None
):
    """Two categories side by side over one window.

    Stories, likes and comments for each category, counted inside the same
    window -- a preset range or a custom start and end date -- so the
    difference between the two is a difference over one period and never a
    difference between two different periods.
    """
    custom = _custom_window(start_iso, end_iso)
    if custom is not None:
        start, end_exclusive = custom
        range_label = "Custom range"
    else:
        range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
        start = _local_midnight(timezone.localtime() - timedelta(days=range_days - 1))
        end_exclusive = None
        range_label = _range_label(selected_range)

    def totals(category):
        published = Blog.objects.filter(category=category, date_created__gte=start)
        liked = BlogLike.objects.filter(blog__category=category, created_at__gte=start)
        commented = Comment.objects.filter(blog__category=category, date_created__gte=start)
        if end_exclusive is not None:
            published = published.filter(date_created__lt=end_exclusive)
            liked = liked.filter(created_at__lt=end_exclusive)
            commented = commented.filter(date_created__lt=end_exclusive)
        return {
            "stories": published.count(),
            "likes": liked.count(),
            "comments": commented.count(),
        }

    totals_a = totals(name_a)
    totals_b = totals(name_b)

    differences = []
    for label, key in COMPARISON_METRICS:
        first = totals_a[key]
        second = totals_b[key]
        gap = first - second
        differences.append(
            {
                "metric": label,
                "a": first,
                "b": second,
                "difference": gap,
                #   Signed, so the direction is readable without relying on
                #   colour alone.
                "display": f"+{gap}" if gap > 0 else (f"-{abs(gap)}" if gap < 0 else "0"),
                "leader": name_a if gap > 0 else (name_b if gap < 0 else ""),
                "tie": gap == 0,
            }
        )

    return {
        "type": "bar",
        "labels": [label for label, _ in COMPARISON_METRICS],
        "series": [
            {
                "key": name_a,
                "name": name_a,
                "color": palette.get(name_a, CATEGORY_SERIES_COLORS[0]),
                "values": [totals_a[key] for _, key in COMPARISON_METRICS],
            },
            {
                "key": name_b,
                "name": name_b,
                "color": palette.get(name_b, CATEGORY_SERIES_COLORS[1]),
                "values": [totals_b[key] for _, key in COMPARISON_METRICS],
            },
        ],
        "differences": differences,
        "range_label": range_label,
        "categories": [name_a, name_b],
    }


#   -------------------------------------------------------------------------
#   STORY KPI STRIP -- the totals above the Story lytics cards
#   -------------------------------------------------------------------------
#   Published and reads are counted over one window (a preset range or a custom
#   start/end pair), and each carries a delta against the window immediately
#   before it. The delta is only produced when that earlier window had data, so
#   a fresh install never shows a fall invented out of nothing.

STORY_KPI_RANGE_CHOICES = [
    ("7d", "7 days"),
    ("30d", "30 days"),
    ("90d", "90 days"),
]
STORY_KPI_RANGES = tuple(value for value, _ in STORY_KPI_RANGE_CHOICES)


def _safe_count(queryset):
    """Count a queryset, or 0 while its table is still unmigrated.

    StoryView is the only table this guards, matching _safe_values and
    _safe_rows: ANALYTICS must show a zero, not a 500, before its migration.
    """
    try:
        with transaction.atomic():
            return queryset.count()
    except DatabaseError:
        return 0


def _story_reads(start, end=None):
    """Story-open events in [start, end), the same source the charts count."""
    queryset = StoryView.objects.filter(created_at__gte=start)
    if end is not None:
        queryset = queryset.filter(created_at__lt=end)
    return _safe_count(queryset)


def _delta_chip(current, previous):
    """A signed delta against the previous window, or None when it was empty."""
    if not previous:
        return None
    diff = current - previous
    tone = "is-up" if diff > 0 else ("is-down" if diff < 0 else "is-flat")
    display = f"+{diff}" if diff > 0 else (f"-{abs(diff)}" if diff < 0 else "0")
    return {
        "display": display,
        "tone": tone,
        "label": f"Change against the previous period: {display}",
    }


def story_kpis(selected_range, start_iso=None, end_iso=None):
    """The Story lytics KPI strip: published, reads, reads per story, cold.

    Published and reads share the chosen window, so the ratio between them is
    honest. "Cold" is the current never-viewed backlog: a running figure, not a
    windowed one, so it is never set against a previous period.
    """
    now = timezone.localtime()
    custom = _custom_window(start_iso, end_iso)
    if custom is not None:
        start, end_exclusive = custom
        span = end_exclusive - start
    else:
        range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
        start = _local_midnight(now - timedelta(days=range_days - 1))
        end_exclusive = None
        span = now - start

    published = _stories_published(start, end_exclusive)
    reads = _story_reads(start, end_exclusive)

    previous_start = start - span
    previous_published = _stories_published(previous_start, start)
    previous_reads = _story_reads(previous_start, start)

    last_day = (end_exclusive - timedelta(days=1)) if end_exclusive is not None else now
    cold = _cold_stories(now)
    return {
        "range": selected_range,
        "range_label": "Custom range" if custom is not None else _range_label(selected_range),
        "display_range": _fmt_range(start, last_day),
        "start_value": (start_iso or "").strip(),
        "end_value": (end_iso or "").strip(),
        "published": published,
        "reads": reads,
        "reads_per_story": round(reads / published) if published else 0,
        "cold_total": cold["total"],
        "cold_max_views": cold["max_views"],
        "cold_older_than": cold["older_than"],
        "published_delta": _delta_chip(published, previous_published),
        "reads_delta": _delta_chip(reads, previous_reads),
    }


#   -------------------------------------------------------------------------
#   STORY PERFORMANCE -- one story's views / likes / comments over a window
#   -------------------------------------------------------------------------
#   The reader picks a single story and overlays the three signals on one line
#   chart, reusing the same bucket and range controls as Trends. Everything is
#   counted from the event tables, so a range means the same thing here as it
#   does everywhere else on the page.

STORY_SEARCH_LIMIT = 15        #   matches offered by the picker
STORY_SEARCH_MIN_CHARS = 2     #   shorter queries just show the latest stories


def story_search(query):
    """Stories matching an admin's picker query, newest first.

    A blank or one character query falls back to the latest stories, so the
    picker shows something useful the moment it opens instead of an empty box.
    """
    stories = Blog.objects.all()
    text = (query or "").strip()
    if len(text) >= STORY_SEARCH_MIN_CHARS:
        stories = stories.filter(heading__icontains=text)

    rows = stories.order_by("-date_created")[:STORY_SEARCH_LIMIT]
    return [
        {
            "id": story.pk,
            "heading": story.heading,
            "author": story.author_name,
            "category": story.category,
            "posted": timezone.localtime(story.date_created),
        }
        for story in rows
    ]


def story_performance(blog_id, bucket, selected_range, series_keys, start_iso=None, end_iso=None):
    """Line chart data for a single story: views, likes and comments over time.

    Returns an empty series (with a null story) when the id names nothing, so
    the fragment can draw a "pick a story" note rather than an empty chart.
    """
    story = Blog.objects.filter(pk=blog_id).first() if blog_id else None
    if story is None:
        return {
            "type": "line",
            "labels": [],
            "series": [],
            "story": None,
            "bucket": bucket,
            "range": selected_range,
        }

    #   The chart opens on the day the story was published. A window that
    #   started earlier would leave the whole left of the chart empty and
    #   squeeze the story's own life into one side of it; the range still
    #   bounds how far back the chart looks.
    published = timezone.localtime(story.date_created)
    publish_day = _local_midnight(published)
    frame = _trend_frame(bucket, selected_range, start_iso, end_iso, not_before=publish_day)

    def count_events(model, field):
        queryset = model.objects.filter(blog_id=story.pk)
        queryset = queryset.filter(**{f"{field}__gte": frame["start"]})
        if frame["end_exclusive"] is not None:
            queryset = queryset.filter(**{f"{field}__lt": frame["end_exclusive"]})
        return _frame_counts(frame, _safe_values(queryset, field))

    sources = {
        "views": lambda: count_events(StoryView, "created_at"),
        "likes": lambda: count_events(BlogLike, "created_at"),
        "comments": lambda: count_events(Comment, "date_created"),
    }

    series = []
    for meta in STORY_PERFORMANCE_SERIES:
        if meta["key"] not in series_keys:
            continue
        series.append({**meta, "values": sources[meta["key"]]()})

    return {
        "type": "line",
        "labels": frame["labels"],
        "series": series,
        "story": {
            "id": story.pk,
            "heading": story.heading,
            "slug": story.slug,
            "author": story.author_name,
            "category": story.category,
            "published": publish_day,
            "published_label": _month_day(publish_day),
        },
        "bucket": bucket,
        "range": selected_range,
    }


#   -------------------------------------------------------------------------
#   MEMBER DIRECTORY -- the "Members" table on ANALYTICS
#   -------------------------------------------------------------------------
#   Members only: the exact complement of ADMIN.views.staff_directory_queryset
#   and the same group the PANEL "Users" card and the mass-email "Member"
#   toggle reach. Read only -- nothing in this module can change an account.

MEMBER_STATE_CHOICES = [
    ("all", "Any status"),
    ("active", "Active"),
    ("suspended", "Suspended"),
]
MEMBER_NEWSLETTER_CHOICES = [
    ("all", "Any news-alert setting"),
    ("on", "News alerts on"),
    ("off", "News alerts off"),
]
MEMBER_ACTIVITY_CHOICES = [
    ("all", "Any reading activity"),
    ("recent", "Read a story in the last day"),
    ("never", "Never read a story"),
]
MEMBER_KIND_CHOICES = [
    ("all", "All member accounts"),
    ("signup", "Newsletter sign-ups (never signed in)"),
    ("regular", "Has signed in before"),
]

#   A story read within this window counts as "recent" activity.
MEMBER_ACTIVITY_WINDOW = timedelta(days=1)

#   The category dropdown's two non-category values. Real category names come
#   from get_category_choices() (short codes such as NEWS), so neither clashes.
MEMBER_CATEGORY_ANY = "any"   #   no category filter at all
MEMBER_CATEGORY_ALL = "all"   #   the documented "no rows == every category" default


def member_category_filter_choices():
    """Category dropdown options: any / the no-preference default / each one."""
    return [
        (MEMBER_CATEGORY_ANY, "Any category"),
        (MEMBER_CATEGORY_ALL, "All categories (no preference)"),
    ] + list(get_category_choices())


def member_directory_queryset(
    state="all", newsletter="all", category=MEMBER_CATEGORY_ANY, activity="all", kind="all", search=""
):
    """Regular member accounts narrowed by the ANALYTICS Members filters.

    Every narrowing is a pk__in / exclude subquery rather than a JOIN, so the
    queryset keeps one row per account: the paginator's count stays honest and
    the per-page aggregates in member_page_details can never be multiplied by a
    join. Unknown filter values simply fall back to "all" -- the same
    forgiving-at-the-edge rule the chart fragments follow.
    """
    members = Auth.objects.filter(is_staff=False, is_admin=False, is_superuser=False)

    if state == "active":
        members = members.filter(is_active=True)
    elif state == "suspended":
        members = members.filter(is_active=False)

    if newsletter == "on":
        members = members.filter(send_newsletter=True)
    elif newsletter == "off":
        members = members.filter(send_newsletter=False)

    #   A newsletter-only account is recognised by an empty last_login: the
    #   footer signup creates a real account but never signs it in. A normal
    #   member has signed in at least once, so this is the "newsletter user"
    #   filter, deliberately separate from the news-alert flag above.
    if kind == "signup":
        members = members.filter(last_login__isnull=True)
    elif kind == "regular":
        members = members.filter(last_login__isnull=False)

    current_names = [name for name, _ in get_category_choices()]
    preference_ids = CategorySubscription.objects.filter(category__in=current_names).values_list("user_id", flat=True)
    if category == MEMBER_CATEGORY_ALL:
        members = members.exclude(pk__in=preference_ids)
    elif category in current_names:
        members = members.filter(
            pk__in=CategorySubscription.objects.filter(category=category).values_list("user_id", flat=True)
        )

    if activity == "recent":
        cutoff = timezone.now() - MEMBER_ACTIVITY_WINDOW
        members = members.filter(
            pk__in=ReadingHistory.objects.filter(read_at__gte=cutoff).values_list("user_id", flat=True)
        )
    elif activity == "never":
        members = members.exclude(pk__in=ReadingHistory.objects.values_list("user_id", flat=True))

    search = (search or "").strip()
    if search:
        members = members.filter(email__icontains=search)

    return members.order_by("-date_joined")


def member_page_details(account_list):
    """Per-account aggregates for one page of members, keyed by account id.

    Four small, fixed queries for the whole page instead of N per row. Accounts
    with no data still get an entry, so the row builder never has to guess.
    """
    accounts = list(account_list)
    ids = [account.pk for account in accounts]
    details = {
        account.pk: {"categories": [], "last_read": None, "stories_read": 0, "following": 0}
        for account in accounts
    }
    if not ids:
        return details

    current_names = {name for name, _ in get_category_choices()}
    for user_id, name in CategorySubscription.objects.filter(user_id__in=ids).values_list("user_id", "category"):
        if name in current_names:   #   a row for a category since removed never counts
            details[user_id]["categories"].append(name)
    for info in details.values():
        info["categories"].sort()

    for row in (
        ReadingHistory.objects.filter(user_id__in=ids)
        .values("user_id")
        .annotate(last=Max("read_at"))
        .order_by()
    ):
        details[row["user_id"]]["last_read"] = row["last"]

    for row in (
        ReadingHistory.objects.filter(user_id__in=ids)
        .values("user_id")
        .annotate(n=Count("id"))
        .order_by()
    ):
        details[row["user_id"]]["stories_read"] = row["n"]

    for row in (
        AuthorFollow.objects.filter(follower_id__in=ids)
        .values("follower_id")
        .annotate(n=Count("id"))
        .order_by()
    ):
        details[row["follower_id"]]["following"] = row["n"]

    return details


#   -------------------------------------------------------------------------
#   AUTHOR LYTICS -- who writes, how much, and who liked it
#   -------------------------------------------------------------------------
#   The people-facing chamber. A story is owned by Blog.author, which is an
#   Auth row (limit_choices_to is_staff), so an "author" here is any staff
#   account that has published at least once -- deliberately not the StaffProfile
#   table, so a story written by an admin without a profile still appears.
#
#   Every figure is counted from the event tables (StoryView / BlogLike /
#   Comment) inside the chosen window, so an author's reads on this page mean the
#   same thing as a read anywhere else in lytics. Blog.views / Blog.likes are the
#   fast all-time counters the story page reads, and are used only where the
#   figure is explicitly all-time.

AUTHOR_RANGE_CHOICES = [
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("90d", "Last 3 months"),
    ("1y", "Last 12 months"),
]
AUTHOR_DEFAULT_RANGE = "30d"
AUTHOR_RANGES = dict(TREND_RANGES)

#   Every list on the page is paged rather than cut off, so a busy instance
#   stays a page you can read instead of a column you have to scroll.
AUTHOR_LIST_PAGE_SIZE = 12
AUTHOR_LIKES_PAGE_SIZE = 12
AUTHOR_DETAIL_LIKES_PAGE_SIZE = 8
AUTHOR_STORY_PAGE_SIZE = 8

#   How far back a custom "since" date may reach, so a hand-typed date cannot
#   ask the database for ten years of events in one page render.
AUTHOR_SINCE_MAX_DAYS = 365 * 3


def _parse_since(raw):
    """A YYYY-MM-DD "since" date as the day it starts, or None if unusable.

    Accepts only the plain date field the form posts; anything else (a blank, a
    stray string, a date beyond the cap or in the future) is treated as "no
    custom window", so a hand-typed querystring can never widen the window
    without bound or reach into next week.
    """
    if not raw:
        return None
    parsed = parse_date(str(raw).strip())
    if parsed is None:
        return None

    start = timezone.make_aware(
        datetime.combine(parsed, time.min), timezone.get_current_timezone()
    )
    now = timezone.localtime()
    if start > now:
        return None
    if (now - start).days > AUTHOR_SINCE_MAX_DAYS:
        return None
    return start


def _month_day(moment):
    """e.g. "Oct 18, 2026" -- strftime without the platform-specific %-d."""
    return f"{moment:%b} {moment.day}, {moment.year}"


def _relative_label(moment, nominal_days=None):
    """How far back something reaches, in words: "2 days ago", "3 months ago".

    Deliberately coarse: an admin reading the strip wants "since when", not a
    to-the-second duration, so the biggest sensible unit wins. `nominal_days`
    lets a preset window say "30 days ago" rather than the "29 days ago" its
    own elapsed days would give, so the words match the preset's label.
    """
    days = nominal_days if nominal_days is not None else max((timezone.localtime() - moment).days, 0)
    days = max(days, 0)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 60:
        return f"{days} days ago"
    months = round(days / 30)
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = round(days / 365)
    return f"{years} year{'s' if years != 1 else ''} ago"


def _author_window(selected_range, since=None):
    """The [start, now] window behind a range key, with a human label.

    A usable custom `since` date wins over the preset, so the free "since"
    field can narrow or widen the window past any of the four presets. The
    second label says how far back the window reaches in words -- "3 days ago"
    for a custom date, or the preset's own span ("30 days ago") -- which is what
    keeps the two labels reading as one thought rather than two.
    """
    now = timezone.localtime()
    start = _parse_since(since)
    if start is None:
        range_days = AUTHOR_RANGES.get(selected_range, AUTHOR_RANGES[AUTHOR_DEFAULT_RANGE])
        start = _local_midnight(now - timedelta(days=range_days - 1))
        label = _range_label(selected_range)
        return start, now, label, _relative_label(start, nominal_days=range_days)

    return start, now, f"Since {_month_day(start)}", _relative_label(start)


def _author_event_counts(model, field, start, end=None):
    """Views / likes / comments per author, in one grouped query per table.

    Grouped by `blog__author_id` in the database rather than stitched together
    in Python: one query per signal covers every author on the page, instead of
    a query per (signal × story). Guarded with _safe_rows the same way the rest
    of the module is, so an unmigrated StoryView yields zeroes, not a 500.
    """
    queryset = model.objects.filter(**{f"{field}__gte": start, "blog__author_id__isnull": False})
    if end is not None:
        queryset = queryset.filter(**{f"{field}__lt": end})
    rows = _safe_rows(
        queryset.values("blog__author_id").annotate(n=Count("id")).order_by()
    )
    return {row["blog__author_id"]: row["n"] for row in rows}


def _story_event_counts(model, field, start, blog_ids):
    """Views / likes / comments per story, across one author's own stories.

    The same shape as _author_event_counts, grouped by story instead of author,
    used by the per-author detail so each story can carry its own windowed
    figures without a query per story.
    """
    if not blog_ids:
        return {}
    queryset = model.objects.filter(**{f"{field}__gte": start, "blog_id__in": blog_ids})
    rows = _safe_rows(queryset.values("blog_id").annotate(n=Count("id")).order_by())
    return {row["blog_id"]: row["n"] for row in rows}


def _mask_email(email):
    """m***a@gmail.com -- never show a full address client side."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return email or ""
    if len(local) <= 2:
        masked = (local[:1] or "?") + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _author_names(models):
    """{auth_id: display name} for a set of author accounts, in one query.

    The staff full name wins when there is one; otherwise the masked email is
    the name, so a raw address never reaches the page.
    """
    ids = {model.pk for model in models if model is not None}
    if not ids:
        return {}
    full_names = {
        profile.auth_id: profile.full_name
        for profile in StaffProfile.objects.filter(auth_id__in=ids)
        if profile.full_name
    }
    return {
        model.pk: full_names.get(model.pk) or _mask_email(model.email) or "Unknown"
        for model in models
        if model is not None
    }


def _author_profiles(auth_ids):
    """{auth_id: StaffProfile} for a set of accounts, in one query."""
    if not auth_ids:
        return {}
    return {
        profile.auth_id: profile
        for profile in StaffProfile.objects.filter(auth_id__in=auth_ids)
    }


def author_directory_rows(selected_range, since=None, page_number=1):
    """One page of authors that published or were read in the window.

    Sorted by reads, so the leaderboard leads with whoever is actually being
    read. An author with no reads in the window still appears if they published
    in it, so a brand new author is never invisible. The rows are ranked in full
    and then paged, because "top of the table" only means anything once every
    author has been ranked -- but only one page is ever rendered.
    """
    start, now, range_label, relative_label = _author_window(selected_range, since)

    published = {
        row["author_id"]: row["n"]
        for row in _safe_rows(
            Blog.objects.filter(date_created__gte=start)
            .values("author_id")
            .annotate(n=Count("id"))
        )
    }

    viewed = _author_event_counts(StoryView, "created_at", start)
    liked = _author_event_counts(BlogLike, "created_at", start)
    commented = _author_event_counts(Comment, "date_created", start)

    per_author_readers = {}
    reader_rows = (
        StoryView.objects.filter(created_at__gte=start, user__isnull=False)
        .values_list("blog__author_id", "user_id")
        .distinct()
    )
    for author_id, user_id in _safe_rows(reader_rows):
        per_author_readers.setdefault(author_id, set()).add(user_id)

    author_ids = set(published) | set(viewed) | set(liked) | set(commented)
    authors = Auth.objects.in_bulk(list(author_ids))
    names = _author_names(list(authors.values()))
    profiles = _author_profiles(author_ids)

    followers = {
        row["author_id"]: row["n"]
        for row in _safe_rows(
            AuthorFollow.objects.filter(author_id__in=author_ids)
            .values("author_id")
            .annotate(n=Count("id"))
        )
    }

    rows = []
    for author_id in author_ids:
        author = authors.get(author_id)
        if author is None:      #   account deleted between the reads
            continue
        views = viewed.get(author_id, 0)
        like_count = liked.get(author_id, 0)
        profile = profiles.get(author_id)
        rows.append(
            {
                "id": author_id,
                "name": names.get(author_id, author.email or "Unknown"),
                "email_masked": _mask_email(author.email),
                "profile_img": author.profile_img or "",
                "initial": (author.email or "?")[:1].upper(),
                "is_active": author.is_active,
                "role": profile.get_role_display() if profile else "",
                "stories": published.get(author_id, 0),
                "views": views,
                "likes": like_count,
                "comments": commented.get(author_id, 0),
                "readers": len(per_author_readers.get(author_id, ())),
                "followers": followers.get(author_id, 0),
                #   Likes per hundred reads, so a low-traffic author who lands
                #   well is not hidden behind a high-traffic one.
                "engagement": round(like_count * 100 / views) if views else 0,
            }
        )

    rows.sort(key=lambda row: (row["views"], row["stories"], row["likes"]), reverse=True)

    total_views = sum(row["views"] for row in rows)
    top = max((row["views"] for row in rows), default=0)
    for position, row in enumerate(rows, start=1):
        row["rank"] = position
        row["bar_percent"] = round(row["views"] * 100 / top) if top else 0
        row["share_percent"] = round(row["views"] * 100 / total_views) if total_views else 0

    paginator = Paginator(rows, AUTHOR_LIST_PAGE_SIZE)
    page = paginator.get_page(page_number)

    return {
        "rows": page.object_list,
        "page": page,
        "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
        "total_authors": paginator.count,
        "range_label": range_label,
        "relative_label": relative_label,
        "start": start,
        "range": selected_range,
    }


def author_kpis(selected_range, since=None):
    """The Author lytics KPI strip.

    Authors, stories published, reads and non-anonymous likes, all measured to
    the same window so the ratios between them stay honest.
    """
    start, now, range_label, relative_label = _author_window(selected_range, since)
    published = _safe_rows(
        Blog.objects.filter(date_created__gte=start).values("author_id").annotate(n=Count("id"))
    )
    author_count = len({row["author_id"] for row in published}) or Auth.objects.filter(
        blogs__isnull=False
    ).distinct().count()

    stories = sum(row["n"] for row in published)
    reads = _story_reads(start)
    liked = _safe_count(
        BlogLike.objects.filter(created_at__gte=start, user__isnull=False)
    )
    commented = _safe_count(Comment.objects.filter(date_created__gte=start))

    span = now - start
    previous_start = start - span
    previous_stories = _stories_published(previous_start, start)
    previous_reads = _story_reads(previous_start, start)
    previous_liked = _safe_count(
        BlogLike.objects.filter(created_at__gte=previous_start, created_at__lt=start, user__isnull=False)
    )

    return {
        "range": selected_range,
        "range_label": range_label,
        "relative_label": relative_label,
        "since_value": start.strftime("%Y-%m-%d"),
        "authors": author_count,
        "stories": stories,
        "reads": reads,
        "reads_per_story": round(reads / stories) if stories else 0,
        "likes": liked,
        "comments": commented,
        "stories_delta": _delta_chip(stories, previous_stories),
        "reads_delta": _delta_chip(reads, previous_reads),
        "likes_delta": _delta_chip(liked, previous_liked),
    }


def author_likes(selected_range, page_number=1, since=None):
    """Non-anonymous likes, newest first, with the reader's name.

    A like can only ever come from a signed-in account (BlogLike.user is a
    required FK and the like endpoint rejects anonymous readers), so every row
    here is a named person -- that is the point of the list. Paged rather than
    truncated so an admin can actually read who liked what.
    """
    start, now, range_label, relative_label = _author_window(selected_range, since)
    queryset = (
        BlogLike.objects.filter(created_at__gte=start)
        .select_related("user", "blog", "blog__author")
        .order_by("-created_at")
    )
    paginator = Paginator(queryset, AUTHOR_LIKES_PAGE_SIZE)
    page = paginator.get_page(page_number)
    likes = list(page.object_list)

    #   One name query for the readers who liked, one for the authors who were
    #   liked -- never a query per row.
    author_names = _author_names([like.blog.author for like in likes])
    reader_names = _author_names([like.user for like in likes])

    items = []
    for like in likes:
        author = like.blog.author
        items.append(
            {
                "reader_name": reader_names.get(like.user_id) or _mask_email(like.user.email) or "Unknown",
                "reader_email": _mask_email(like.user.email),
                "reader_img": like.user.profile_img or "",
                "reader_initial": (like.user.email or "?")[:1].upper(),
                "story_heading": like.blog.heading,
                "story_slug": like.blog.slug,
                "author_name": author_names.get(author.pk) or _mask_email(author.email) or "Unknown",
                "author_id": author.pk,
                "liked_at": timezone.localtime(like.created_at),
            }
        )

    return {
        "range_label": range_label,
        "relative_label": relative_label,
        "page": page,
        "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
        "total": paginator.count,
        "items": items,
        "range": selected_range,
        "since": since,
    }


def author_detail(author_id, selected_range, since=None, story_page=1, like_page=1):
    """One author's production over the window, plus their named likers.

    Every number matches the leaderboard row for the same author and range, so
    opening a row never contradicts the table it came from. Both long lists --
    the author's stories and the named likers -- are paged, so the panel stays
    something you read rather than something you scroll.
    """
    start, now, range_label, relative_label = _author_window(selected_range, since)
    author = Auth.objects.filter(pk=author_id).first()
    if author is None:
        return None

    profile = StaffProfile.objects.filter(auth_id=author_id).first()
    stories = Blog.objects.filter(author_id=author_id).order_by("-date_created")
    published = stories.filter(date_created__gte=start).count()
    story_ids = list(stories.values_list("pk", flat=True))

    #   One grouped query per signal, windowed on the author's own stories.
    viewed = _story_event_counts(StoryView, "created_at", start, story_ids)
    liked = _story_event_counts(BlogLike, "created_at", start, story_ids)
    commented = _story_event_counts(Comment, "date_created", start, story_ids)

    reads = sum(viewed.values())
    likes = sum(liked.values())
    comments = sum(commented.values())
    readers = (
        StoryView.objects.filter(created_at__gte=start, user__isnull=False, blog_id__in=story_ids)
        .values("user_id")
        .distinct()
        .count()
    )
    followers = AuthorFollow.objects.filter(author_id=author_id).count()

    #   The named likers across this author's stories, paged and named with one
    #   extra query rather than one per like.
    likes_queryset = (
        BlogLike.objects.filter(created_at__gte=start, blog_id__in=story_ids)
        .select_related("user", "blog")
        .order_by("-created_at")
    )
    likes_paginator = Paginator(likes_queryset, AUTHOR_DETAIL_LIKES_PAGE_SIZE)
    likes_page = likes_paginator.get_page(like_page)
    recent_likes = list(likes_page.object_list)
    reader_names = _author_names([like.user for like in recent_likes])
    like_rows = [
        {
            "reader_name": reader_names.get(like.user_id) or _mask_email(like.user.email) or "Unknown",
            "reader_email": _mask_email(like.user.email),
            "reader_img": like.user.profile_img or "",
            "reader_initial": (like.user.email or "?")[:1].upper(),
            "story_heading": like.blog.heading,
            "story_slug": like.blog.slug,
            "liked_at": timezone.localtime(like.created_at),
            "liked_ago": _relative_label(timezone.localtime(like.created_at)),
        }
        for like in recent_likes
    ]

    #   The author's own stories, each carrying its windowed figures, paged so a
    #   prolific author does not push the panel into a scroll.
    stories_paginator = Paginator(stories, AUTHOR_STORY_PAGE_SIZE)
    stories_page = stories_paginator.get_page(story_page)
    story_rows = []
    for story in stories_page.object_list:
        story_views = viewed.get(story.pk, 0)
        story_likes = liked.get(story.pk, 0)
        story_rows.append(
            {
                "heading": story.heading,
                "slug": story.slug,
                "category": story.category,
                "posted": timezone.localtime(story.date_created),
                "posted_ago": _relative_label(timezone.localtime(story.date_created)),
                "views": story_views,
                "likes": story_likes,
                "comments": commented.get(story.pk, 0),
                "totals_views": story.views,
                "totals_likes": story.likes,
                "engagement": round(story_likes * 100 / story_views) if story_views else 0,
            }
        )

    return {
        "id": author_id,
        "name": _author_names([author]).get(author_id) or _mask_email(author.email) or "Unknown",
        "email_masked": _mask_email(author.email),
        "profile_img": author.profile_img or "",
        "initial": (author.email or "?")[:1].upper(),
        "is_active": author.is_active,
        "role": profile.get_role_display() if profile else "",
        "joined": timezone.localtime(author.date_joined),
        "joined_ago": _relative_label(timezone.localtime(author.date_joined)),
        "range": selected_range,
        "range_label": range_label,
        "relative_label": relative_label,
        "since": since,
        "published": published,
        "stories_total": stories.count(),
        "reads": reads,
        "likes": likes,
        "likes_total": stories.aggregate(total=Sum("likes"))["total"] or 0,
        "comments": comments,
        "readers": readers,
        "followers": followers,
        "likers": like_rows,
        "likers_page": likes_page,
        "likers_page_range": list(
            likes_paginator.get_elided_page_range(likes_page.number, on_each_side=1, on_ends=1)
        ),
        "likes_in_range": likes_paginator.count,
        "stories": story_rows,
        "stories_page": stories_page,
        "stories_page_range": list(
            stories_paginator.get_elided_page_range(stories_page.number, on_each_side=1, on_ends=1)
        ),
    }
