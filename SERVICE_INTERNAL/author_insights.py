"""Per author charts: rank among authors, publishing rhythm, readership by
category and reader response.

These used to feed the public portfolio page. The portfolio no longer shows
them, so they now live here and feed one place only: the author detail panel
in Author lytics (ADMIN.analytics.author_detail). Every figure is all time,
except the rhythm, which covers the last RHYTHM_MONTHS months.
"""
from datetime import date, datetime, time

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, Comment, get_category_choices
from HOME.models import Bookmark

RHYTHM_MONTHS = 6            #   COLUMNS IN THE PUBLISHING RHYTHM CHART
RANK_BARS = 8                #   MOST BARS IN THE AUTHOR RANK MINI CHART
READERSHIP_SLICES = 5        #   NAMED SLICES IN THE DONUT, THE REST FOLD INTO "OTHER"


def author_ranking(author, story_count):
    """Where the author stands among every active author by stories posted.

    Rank is 1 plus the number of authors with strictly more stories, so a
    tie shares the higher position. The bars are anonymous on purpose: the
    chart shows the shape of the field, never other people's numbers."""
    rows = list(
        Blog.objects.filter(author__is_active=True)
        .values("author")
        .annotate(total=Count("id"))
        .order_by("-total", "author")
        .values_list("author", "total")
    )
    total_authors = len(rows)
    if not story_count:
        return {"rank": None, "total_authors": total_authors, "bars": []}

    rank = 1 + sum(1 for _author_id, total in rows if total > story_count)
    bars = [{"count": total, "is_me": author_id == author.pk} for author_id, total in rows]
    if len(bars) > RANK_BARS:
        head = bars[:RANK_BARS]
        if not any(bar["is_me"] for bar in head):
            head = bars[: RANK_BARS - 1] + [next(bar for bar in bars if bar["is_me"])]
        bars = head
    tallest = max((bar["count"] for bar in bars), default=0)
    for bar in bars:
        bar["height"] = max(14, round(bar["count"] * 100 / tallest)) if tallest else 0
    return {"rank": rank, "total_authors": total_authors, "bars": bars}


def _month_start(today, back):
    """First day of the month `back` months before the month of `today`."""
    index = today.year * 12 + (today.month - 1) - back
    return date(index // 12, index % 12 + 1, 1)


def publishing_rhythm(author):
    """Stories published per month for the last RHYTHM_MONTHS months, empty
    months included so the chart keeps a steady width."""
    today = timezone.localdate()
    starts = [_month_start(today, back) for back in range(RHYTHM_MONTHS - 1, -1, -1)]
    window_start = timezone.make_aware(datetime.combine(starts[0], time.min))
    rows = (
        Blog.objects.filter(author=author, date_created__gte=window_start)
        .annotate(month=TruncMonth("date_created"))
        .values("month")
        .annotate(total=Count("id"))
    )
    per_month = {timezone.localtime(row["month"]).date().replace(day=1): row["total"] for row in rows}

    columns = [
        {
            "label": start.strftime("%b"),
            "year": start.year if (index == 0 or start.month == 1) else "",
            "total": per_month.get(start, 0),
            "is_current": index == len(starts) - 1,
        }
        for index, start in enumerate(starts)
    ]
    peak = max((column["total"] for column in columns), default=0)
    for column in columns:
        column["height"] = max(8, round(column["total"] * 100 / peak)) if column["total"] else 0
    window_total = sum(column["total"] for column in columns)
    return {"columns": columns, "window_total": window_total, "peak": peak, "months": RHYTHM_MONTHS}


def coverage_and_readership(author, story_count, total_views):
    """One grouped query feeds both charts: stories per category (ranked
    bars) and views per category (donut)."""
    rows = (
        Blog.objects.filter(author=author)
        .values("category")
        .annotate(total=Count("id"), views=Sum("views"))
        .order_by("-total", "-views", "category")
    )
    labels = dict(get_category_choices())
    parsed = [
        {
            "label": labels.get(row["category"], row["category"]).title(),
            "total": row["total"],
            "views": row["views"] or 0,
        }
        for row in rows
    ]

    leader = parsed[0]["total"] if parsed else 0
    coverage = [
        {
            "position": index,
            "label": row["label"],
            "total": row["total"],
            "share": round(row["total"] * 100 / story_count),
            "width": max(4, round(row["total"] * 100 / leader)),
        }
        for index, row in enumerate(parsed, start=1)
    ]

    #   DONUT: the biggest categories by views get a slice each, the tail
    #   folds into one neutral "Other" slice so the ring stays readable.
    by_views = sorted((row for row in parsed if row["views"]), key=lambda row: (-row["views"], row["label"]))
    head, tail = by_views[:READERSHIP_SLICES], by_views[READERSHIP_SLICES:]
    slices = [{"label": row["label"], "views": row["views"], "is_other": False} for row in head]
    if tail:
        slices.append(
            {"label": f"Other ({len(tail)})", "views": sum(row["views"] for row in tail), "is_other": True}
        )
    gap = 0.6 if len(slices) > 1 else 0.0
    running = 0.0
    for index, item in enumerate(slices, start=1):
        share = item["views"] * 100 / total_views if total_views else 0.0
        item["pct_label"] = "under 1%" if 0 < share < 0.5 else f"{round(share)}%"
        item["dash"] = round(max(share - gap, 0.05), 3)
        item["gap"] = round(100 - item["dash"], 3)
        item["offset"] = round(25 - running, 3)         #   25 STARTS THE RING AT 12 O'CLOCK
        item["tone"] = "other" if item["is_other"] else f"c{index}"
        running += share
    return coverage, slices


def reader_response(author, total_views, total_likes):
    """How readers act on the work: views, distinct signed in readers, likes,
    comments and bookmarks. Every bar is measured against total views."""
    comments = Comment.objects.filter(blog__author=author).count()
    saves = Bookmark.objects.filter(blog__author=author).count()
    readers = Auth.objects.filter(non_anonymous_viewer__author=author).distinct().count()

    rows = [
        ("Story views", total_views, "Every open of a published story"),
        ("Signed in readers", readers, "Different accounts that read a story"),
        ("Likes", total_likes, "Reactions left on stories"),
        ("Comments", comments, "Feedback written under stories"),
        ("Saved stories", saves, "Times a story was bookmarked"),
    ]
    funnel = []
    for index, (label, value, note) in enumerate(rows):
        if index == 0:
            width, ratio = (100 if value else 0), ""
        elif total_views and value:
            width = min(100, max(2, round(value * 100 / total_views)))
            ratio = f"{round(value * 100 / total_views, 1):g}% of views"
        else:
            width, ratio = 0, ""
        funnel.append({"label": label, "value": value, "note": note, "width": width, "ratio": ratio})
    return funnel


def author_insights(author, story_count, total_views, total_likes):
    """Everything the author detail panel draws, in one dict. A writer with no
    stories gets empty charts, never an error."""
    if not story_count:
        return {
            "has_stories": False,
            "ranking": author_ranking(author, 0),
            "rhythm": publishing_rhythm(author),
            "coverage": [],
            "readership": [],
            "response": reader_response(author, 0, 0),
            "top_story": None,
        }
    coverage, readership = coverage_and_readership(author, story_count, total_views)
    top_story = (
        Blog.objects.filter(author=author)
        .only("slug", "heading", "views")
        .order_by("-views", "-date_created", "-pk")
        .first()
    )
    return {
        "has_stories": True,
        "ranking": author_ranking(author, story_count),
        "rhythm": publishing_rhythm(author),
        "coverage": coverage,
        "readership": readership,
        "response": reader_response(author, total_views, total_likes),
        "top_story": top_story,
    }
