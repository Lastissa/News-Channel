"""Author-facing analytics, scoped to one author and one time range.

Everything shown here is real data from the existing models plus the events
still waiting in the analytics cache. Nothing from the admin's global analytics
is leaked: every queryset is filtered to the selected author before it is
counted, ranked or rendered.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.db.models import Count, Max
from django.urls import reverse
from django.utils import timezone

from BLOG.models import Blog, BlogLike, Comment, StoryView
from HOME.models import Bookmark, ReadingHistory
from SERVICE_INTERNAL.analytics_buffer import pending_story_views
from SERVICE_INTERNAL.permissions import staff_only
from SERVICE_INTERNAL.traffic import (
    SOURCE_GOOGLE_NAME,
    SOURCE_GOOGLE_NAME_ABUREPORT,
    SOURCE_ORDER,
    SOURCE_OTHER,
    source_label,
    tag_internal_url,
)
from STAFF.models import StaffProfile

RANGE_DAYS = {"7": 7, "30": 30, "90": 90}
DEFAULT_RANGE = "30"


def normalize_range(value):
    return value if value in RANGE_DAYS else DEFAULT_RANGE


def _source_key(value):
    """Keep the breakdown totals honest: an unknown or retired key is Other."""
    key = (value or "").strip().lower()
    return key if key in SOURCE_ORDER else SOURCE_OTHER


def author_pool():
    """Active authors with a staff profile, newest story as a tie-breaker."""
    from AUTHENTICATION.models import Auth
    from django.db.models import Q

    authors = (
        Auth.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
            staffprofile__isnull=False,
        )
        .filter(Q(is_staff=True) | Q(is_admin=True) | Q(is_superuser=True))
        .select_related("staffprofile")
        .distinct()
    )
    return list(authors)


def author_name(auth):
    profile = getattr(auth, "staffprofile", None)
    name = (getattr(profile, "full_name", "") or "").strip()
    if name:
        return name
    email = (getattr(auth, "email", "") or "").strip()
    local = email.split("@", 1)[0] if email else ""
    return local or "Author"


def _pending_by_blog(cutoff_timestamp, blog_ids):
    rows = {}
    for row in pending_story_views():
        blog_id = row.get("blog_id")
        if blog_id not in blog_ids:
            continue
        try:
            occurred_at = float(row.get("occurred_at") or 0)
        except (TypeError, ValueError):
            continue
        if occurred_at < cutoff_timestamp:
            continue
        rows.setdefault(blog_id, []).append(row)
    return rows


def _newest_sort_value(newest):
    return newest.timestamp() if newest else 0


def build_author_analytics(target, range_key=DEFAULT_RANGE):
    """Return the full context payload for one author's analytics panel."""
    range_key = normalize_range(range_key)
    days = RANGE_DAYS[range_key]
    cutoff = timezone.now() - timedelta(days=days)
    name = author_name(target)

    pool = author_pool()
    pool_ids = [row.pk for row in pool]
    stories = list(
        Blog.objects.filter(author_id__in=pool_ids)
        .values_list("id", "author_id", "date_created")
    )
    blog_author = {story_id: author_id for story_id, author_id, _created in stories}
    newest_by_author = {}
    for _story_id, author_id, created in stories:
        if created and (_newest_sort_value(created) > _newest_sort_value(newest_by_author.get(author_id))):
            newest_by_author[author_id] = created

    pending = _pending_by_blog(cutoff.timestamp(), set(blog_author))

    story_counts = dict(
        Blog.objects.filter(author_id__in=pool_ids, date_created__gte=cutoff)
        .values("author_id")
        .annotate(total=Count("id"))
        .values_list("author_id", "total")
    )
    view_counts = dict(
        StoryView.objects.filter(blog__author_id__in=pool_ids, created_at__gte=cutoff)
        .values("blog__author_id")
        .annotate(total=Count("id"))
        .values_list("blog__author_id", "total")
    )
    for blog_id, rows in pending.items():
        author_id = blog_author.get(blog_id)
        if author_id is not None:
            view_counts[author_id] = view_counts.get(author_id, 0) + len(rows)

    read_counts = dict(
        ReadingHistory.objects.filter(user_id__in=pool_ids, read_at__gte=cutoff)
        .values("user_id")
        .annotate(total=Count("id"))
        .values_list("user_id", "total")
    )

    stats = {}
    for auth in pool:
        stats[auth.pk] = {
            "stories": story_counts.get(auth.pk, 0),
            "views": view_counts.get(auth.pk, 0),
            "reads": read_counts.get(auth.pk, 0),
            "newest": _newest_sort_value(newest_by_author.get(auth.pk)),
        }

    def ranked(key):
        ordered = sorted(
            pool,
            key=lambda row: (
                -stats[row.pk][key],
                -stats[row.pk]["views"],
                -stats[row.pk]["stories"],
                -stats[row.pk]["newest"],
            ),
        )
        return {row.pk: index for index, row in enumerate(ordered, start=1)}, ordered

    story_rank, _story_order = ranked("stories")
    view_rank, _view_order = ranked("views")
    read_rank, _read_order = ranked("reads")

    overall_rows = sorted(
        pool,
        key=lambda row: (
            math.floor((story_rank[row.pk] + view_rank[row.pk] + read_rank[row.pk]) / 3 + 0.5),
            view_rank[row.pk],
            story_rank[row.pk],
            -stats[row.pk]["newest"],
        ),
    )
    overall_rank = {row.pk: index for index, row in enumerate(overall_rows, start=1)}

    def rank_card(label, positions, metric):
        position = positions.get(target.pk, len(pool) or 1)
        return {
            "label": label,
            "position": position,
            "total": len(pool),
            "metric": metric,
            "value": stats.get(target.pk, {}).get(metric, 0),
        }

    ranks = [
        rank_card("Stories written", story_rank, "stories"),
        rank_card("Views received", view_rank, "views"),
        rank_card("Stories read", read_rank, "reads"),
    ]
    overall_position = overall_rank.get(target.pk, len(pool) or 1)
    mean_position = (
        story_rank.get(target.pk, len(pool))
        + view_rank.get(target.pk, len(pool))
        + read_rank.get(target.pk, len(pool))
    ) / 3
    overall = {
        "position": overall_position,
        "total": len(pool),
        #   Show the same rounded integer used to order the overall card.
        "average": math.floor(mean_position + 0.5),
    }

    #   Source breakdown for the selected author only: database rows plus the
    #   pending cache rows, both limited to the selected time range.
    source_counts = {key: 0 for key in SOURCE_ORDER}
    db_sources = (
        StoryView.objects.filter(blog__author=target, created_at__gte=cutoff)
        .values("source")
        .annotate(total=Count("id"))
        .values_list("source", "total")
    )
    for source, total in db_sources:
        key = _source_key(source)
        source_counts[key] = source_counts.get(key, 0) + total

    target_blog_ids = set(
        Blog.objects.filter(author=target).values_list("id", flat=True)
    )
    for blog_id, rows in pending.items():
        if blog_id in target_blog_ids:
            for row in rows:
                key = _source_key(row.get("source"))
                source_counts[key] = source_counts.get(key, 0) + 1

    source_rows = []
    highest = max(source_counts.values()) or 1
    for key in SOURCE_ORDER:
        count = source_counts.get(key, 0)
        source_rows.append(
            {
                "key": key,
                "label": source_label(key, name),
                "count": count,
                "width": round(count / highest * 100),
            }
        )

    google_rows = [
        row for row in source_rows if row["key"] in (SOURCE_GOOGLE_NAME, SOURCE_GOOGLE_NAME_ABUREPORT)
    ]

    target_stories = list(
        Blog.objects.filter(author=target, date_created__gte=cutoff)
        .order_by("-date_created", "-pk")
        .values("id", "heading", "slug", "date_created", "views", "likes")
    )
    story_ids = [row["id"] for row in target_stories]
    views_by_story = dict(
        StoryView.objects.filter(blog_id__in=story_ids, created_at__gte=cutoff)
        .values("blog_id")
        .annotate(total=Count("id"))
        .values_list("blog_id", "total")
    )
    likes_by_story = dict(
        BlogLike.objects.filter(blog_id__in=story_ids, created_at__gte=cutoff)
        .values("blog_id")
        .annotate(total=Count("id"))
        .values_list("blog_id", "total")
    )
    comments_by_story = dict(
        Comment.objects.filter(blog_id__in=story_ids, date_created__gte=cutoff)
        .values("blog_id")
        .annotate(total=Count("id"))
        .values_list("blog_id", "total")
    )
    story_table = []
    for row in target_stories:
        story_table.append(
            {
                "id": row["id"],
                "heading": row["heading"],
                "slug": row["slug"],
                "url": tag_internal_url(reverse("blog:story_detail", args=[row["slug"]])),
                "date": row["date_created"],
                "views": len(pending.get(row["id"], [])) + views_by_story.get(row["id"], 0),
                "likes": likes_by_story.get(row["id"], 0),
                "comments": comments_by_story.get(row["id"], 0),
            }
        )

    kpis = {
        "stories": stats.get(target.pk, {}).get("stories", 0),
        "views": stats.get(target.pk, {}).get("views", 0),
        "likes": BlogLike.objects.filter(blog__author=target, created_at__gte=cutoff).count(),
        "comments": Comment.objects.filter(blog__author=target, date_created__gte=cutoff).count(),
        "bookmarks": Bookmark.objects.filter(blog__author=target, created_at__gte=cutoff).count(),
        "reads": stats.get(target.pk, {}).get("reads", 0),
    }

    return {
        "range_key": range_key,
        "author": target,
        "author_name": name,
        "kpis": kpis,
        "story_table": story_table,
        "ranks": ranks,
        "overall": overall,
        "source_rows": source_rows,
        "google_rows": google_rows,
        "has_author_profile": StaffProfile.objects.filter(auth=target).exists(),
    }
