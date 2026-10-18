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

from django.db import DatabaseError, transaction
from django.db.models import Count, Max
from django.utils import timezone
from django.utils.dateparse import parse_date

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, BlogLike, Comment, StoryView, get_category_choices
from HOME.models import CategorySubscription, ReadingHistory
from STAFF.models import AuthorFollow

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
#   "Per month" is a calendar bucket rather than a fixed number of days, so it
#   is handled apart from this map (see MONTH_BUCKET / _trend_frame).
TREND_BUCKETS = {
    "day": 1,
    "2day": 2,
    "week": 7,
}
DEFAULT_TREND_BUCKET = "day"

#   The calendar-month bucket. A month is not a fixed width, so it cannot live
#   in TREND_BUCKETS alongside the day counts; these buckets are built from
#   first-of-month edges instead.
MONTH_BUCKET = "month"

TREND_RANGES = {
    "7d": 7,
    "14d": 14,
    "30d": 30,
    "60d": 60,
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
    ("day", "Per day"),
    ("2day", "Per 2 days"),
    ("week", "Per week"),
    ("month", "Per month"),
]
TREND_RANGE_CHOICES = [
    ("7d", "Last 7 days"),
    ("14d", "Last 14 days"),
    ("30d", "Last 30 days"),
    ("60d", "Last 2 months"),
    ("90d", "Last 3 months"),
    ("6m", "Last 6 months"),
    ("1y", "Last 12 months"),
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


def _trend_frame(bucket, selected_range, start_iso=None, end_iso=None):
    """Resolve the chart window and its bucket edges.

    A valid custom start/end pair overrides the preset range. Returns a plain
    dict the trend / growth helpers share: the window, the bucket labels, the
    number of buckets, and the edge list (fixed timedelta or month starts).
    """
    now = timezone.localtime()
    custom = _custom_window(start_iso, end_iso)
    month = bucket == MONTH_BUCKET

    if custom is not None:
        start, end_exclusive = custom
        #   Last instant the window can contain, so the +1 bucket rule below
        #   never appends an empty trailing bucket.
        span_end = end_exclusive - timedelta(microseconds=1)
    else:
        range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
        if bucket == "week":
            start = _week_start(now - timedelta(days=range_days - 1))
        else:
            start = _local_midnight(now - timedelta(days=range_days - 1))
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

    size = timedelta(days=TREND_BUCKETS.get(bucket, TREND_BUCKETS[DEFAULT_TREND_BUCKET]))
    #   +1 so the partial final bucket (today) is always included.
    count = max(int((span_end - start) // size) + 1, 1)
    return {
        "start": start,
        "end_exclusive": end_exclusive,
        "months": None,
        "size": size,
        "count": count,
        "labels": [_fmt_day(start + size * index) for index in range(count)],
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
#   A story is only "cold" once it has had a fair week to be discovered.
READING_COLD_MIN_AGE_DAYS = 7


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
        liked = likes.get(story.pk, 0)
        stories.append(
            {
                "heading": story.heading,
                "slug": story.slug,
                "category": story.category,
                "views": views,
                "likes": liked,
                #   Likes per hundred views, so a low-traffic story that lands
                #   well is not hidden behind a high-traffic one.
                "engagement": round(liked * 100 / views) if views else 0,
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


def _cold_stories(now):
    """The never-viewed backlog: stories older than the cold window with 0 views.

    Uses the stored Blog.views counter (written in the same branch as StoryView)
    so this stays one indexed query rather than an appetite for the whole view
    history.
    """
    cutoff = now - timedelta(days=READING_COLD_MIN_AGE_DAYS)
    cold = Blog.objects.filter(views=0, date_created__lt=cutoff).order_by("-date_created")
    total = cold.count()
    items = [
        {
            "heading": story.heading,
            "slug": story.slug,
            "category": story.category,
            "posted": timezone.localtime(story.date_created),
        }
        for story in cold[:READING_COLD_LIMIT]
    ]
    return {
        "older_than": READING_COLD_MIN_AGE_DAYS,
        "total": total,
        "remaining": max(total - len(items), 0),
        "items": items,
    }


def reading_editorial(selected_range):
    """The "Reading & editorial" card: what members read over the range.

    Returns the top-read stories, per-category published-vs-read, and the
    never-viewed backlog. All three are measured to the same window, so the
    card reads as one story.
    """
    range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
    now = timezone.localtime()
    start = _local_midnight(now - timedelta(days=range_days - 1))

    return {
        "range": selected_range,
        "range_label": _range_label(selected_range),
        "top_stories": _top_read_stories(start),
        "top_categories": _category_read_vs_published(start),
        "cold_stories": _cold_stories(now),
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

    frame = _trend_frame(bucket, selected_range, start_iso, end_iso)

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
