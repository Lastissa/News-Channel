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
from BLOG.models import Blog, BlogLike, StoryView, get_category_choices
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
TREND_BUCKETS = {
    "day": 1,
    "2day": 2,
    "week": 7,
}
DEFAULT_TREND_BUCKET = "day"

TREND_RANGES = {
    "7d": 7,
    "14d": 14,
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
    ("7d", "Last 7 days"),
    ("14d", "Last 14 days"),
    ("30d", "Last 30 days"),
    ("90d", "Last 90 days"),
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


def trends(bucket, selected_range, series_keys):
    """Line chart data: the selected series bucketed over the selected window.

    `series_keys` is the set of keys the reader left ticked (users / views /
    stories / likes); anything not named is simply left out of the response.
    """
    bucket_days = TREND_BUCKETS.get(bucket, TREND_BUCKETS[DEFAULT_TREND_BUCKET])
    range_days = TREND_RANGES.get(selected_range, TREND_RANGES[DEFAULT_TREND_RANGE])
    now = timezone.localtime()

    if bucket == "week":
        start = _week_start(now - timedelta(days=range_days - 1))
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


def member_overview():
    """The Quick overview card: new users, active readers, stories published."""
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
    }


def member_new_today():
    """The top-bar badge figure: accounts created since local midnight."""
    return _new_users(_local_midnight(timezone.localtime()))


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
