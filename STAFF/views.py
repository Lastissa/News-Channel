"""Public author portfolio and reader-facing author follow."""

import json
import logging
from datetime import date, datetime, time

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from AUTHENTICATION.models import Auth
from BLOG.models import CATEGORY, Blog, Comment
from HOME.models import Bookmark
from SERVICE_INTERNAL.abstract import _optimization, is_rate_limited
from SERVICE_INTERNAL.config import StaffConfig
from SERVICE_INTERNAL.permissions import is_authenticated
from STAFF.models import AuthorFollow, StaffProfile

logger = logging.getLogger(__name__)

PORTFOLIO_STORY_LIMIT = 6
RHYTHM_MONTHS = 6            #   COLUMNS IN THE PUBLISHING RHYTHM CHART
RANK_BARS = 8                #   MOST BARS IN THE AUTHOR RANK MINI CHART
READERSHIP_SLICES = 5        #   NAMED SLICES IN THE DONUT, THE REST FOLD INTO "OTHER"

#   (key, label, StaffProfile field, aria label). The key doubles as the icon
#   name and as the fab-* class that carries the hover colour.
SOCIAL_LINKS = (
    ("whatsapp", "WhatsApp", "whatsapp_handle", "Chat with {name} on WhatsApp"),
    ("twitter", "X (Twitter)", "twitter_handle", "Follow {name} on X"),
    ("facebook", "Facebook", "facebook_handle", "Visit {name} on Facebook"),
)


def _portfolio_author_or_404(author_id):
    """Only an active staff level account has a portfolio; a member id or a
    suspended account 404s exactly like a missing page."""
    author = (
        Auth.objects.filter(pk=author_id, is_active=True)
        .filter(Q(is_staff=True) | Q(is_admin=True) | Q(is_superuser=True))
        .first()
    )
    if author is None:
        raise Http404("This author does not have a portfolio.")
    return author


def _portfolio_profile_or_404(author_slug):
    """Slug based lookup for the public portfolio URL. Only an active staff
    level account with a profile slug has a portfolio; anything else 404s
    exactly like a missing page."""
    profile = (
        StaffProfile.objects.filter(slug=author_slug, auth__is_active=True)
        .filter(Q(auth__is_staff=True) | Q(auth__is_admin=True) | Q(auth__is_superuser=True))
        .select_related("auth")
        .first()
    )
    if profile is None:
        raise Http404("This author does not have a portfolio.")
    return profile


def _display_name(profile, author):
    """The portfolio username: the staff full name when set, otherwise the
    email local part, mirroring blog.author_name."""
    if profile and profile.full_name.strip():
        return profile.full_name.strip()
    return author.email.split("@")[0].title()


def _portfolio_stats(author):
    """Accumulated numbers over the author's stories, one aggregate query."""
    stats = Blog.objects.filter(author=author).aggregate(
        total_views=Sum("views"),
        total_likes=Sum("likes"),
        story_count=Count("id"),
        latest_story=Max("date_created"),
    )
    total_views = stats["total_views"] or 0
    total_likes = stats["total_likes"] or 0
    story_count = stats["story_count"] or 0
    return {
        "total_views": total_views,
        "total_likes": total_likes,
        "story_count": story_count,
        "latest_story": stats["latest_story"],
        "average_views": round(total_views / story_count) if story_count else 0,
        "average_likes": round(total_likes / story_count) if story_count else 0,
    }


def _portfolio_socials(profile, display_name):
    """Every filled social of the author, in the order the icons are drawn.
    An empty handle is skipped so no dead icon is ever rendered, and only
    http(s) links are accepted so a stray value can never become a
    javascript: link."""
    socials = []
    if not profile:
        return socials
    for key, label, field, aria in SOCIAL_LINKS:
        url = (getattr(profile, field, "") or "").strip()
        if url.lower().startswith(("http://", "https://")):
            socials.append({"key": key, "label": label, "url": url, "aria": aria.format(name=display_name)})
    return socials


def _author_ranking(author, story_count):
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


def _publishing_rhythm(author):
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
    return {"columns": columns, "window_total": window_total, "peak": peak}


def _coverage_and_readership(author, story_count, total_views):
    """One grouped query feeds both charts: stories per category (ranked
    bars) and views per category (donut)."""
    rows = (
        Blog.objects.filter(author=author)
        .values("category")
        .annotate(total=Count("id"), views=Sum("views"))
        .order_by("-total", "-views", "category")
    )
    labels = dict(CATEGORY)
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
        item["pct"] = round(share)
        item["pct_label"] = "under 1%" if 0 < share < 0.5 else f"{round(share)}%"
        item["dash"] = round(max(share - gap, 0.05), 3)
        item["gap"] = round(100 - item["dash"], 3)
        item["offset"] = round(25 - running, 3)         #   25 STARTS THE RING AT 12 O'CLOCK
        item["tone"] = "other" if item["is_other"] else f"c{index}"
        running += share
    return coverage, slices


def _reader_response(author, total_views, total_likes):
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


class PortfolioView(View):
    """The staff portfolio page a staff member can submit for jobs."""

    def get(self, request, author_slug):
        profile = _portfolio_profile_or_404(author_slug)
        author = profile.auth

        display_name = _display_name(profile, author)
        bio = (profile.bio or "").strip() if profile else ""
        tribute = (profile.tribute_bio or "").strip() if profile else ""
        role_label = StaffConfig.role_label(profile.role) if profile else "Staff"
        sex_label = profile.get_gender_display() if profile and profile.gender else ""

        stats = _portfolio_stats(author)
        story_count = stats["story_count"]

        follower_count = AuthorFollow.objects.filter(author=author).count()
        following_count = AuthorFollow.objects.filter(follower=author).count()
        is_following = bool(
            is_authenticated(request.user)
            and AuthorFollow.objects.filter(follower=request.user, author=author).exists()
        )

        socials = _portfolio_socials(profile, display_name)
        speciality = []
        if profile and isinstance(profile.speciality, list):
            speciality = [str(item).strip() for item in profile.speciality if str(item).strip()]

        description_source = bio or f"{display_name}, {role_label} at {self._project_name()}."

        stories = list(
            Blog.objects.filter(author=author)
            .only("id", "slug", "heading", "category", "views", "likes", "date_created")
            .order_by("-date_created")[:PORTFOLIO_STORY_LIMIT]
        )
        highest_recent_views = max((story.views for story in stories), default=0)
        for story in stories:
            story.reach_share = round(story.views * 100 / highest_recent_views) if highest_recent_views else 0

        top_story = None
        coverage, readership = [], []
        rhythm = {"columns": [], "window_total": 0, "peak": 0}
        reader_response = []
        if story_count:
            top_story = Blog.objects.filter(author=author).only("id", "slug", "heading", "views").order_by("-views", "-date_created").first()
            coverage, readership = _coverage_and_readership(author, story_count, stats["total_views"])
            rhythm = _publishing_rhythm(author)
            reader_response = _reader_response(author, stats["total_views"], stats["total_likes"])

        context = {
            "author": author,
            "staff_profile": profile,
            'staff_image': author.profile_img or None,
            "display_name": display_name,
            "sex_label": sex_label,
            "bio": bio,
            "role_label": role_label,
            "socials": socials,
            "speciality": speciality,
            "tribute": tribute,
            "stats": stats,
            "ranking": _author_ranking(author, story_count),
            "top_story": top_story,
            "top_category": coverage[0]["label"] if coverage else "",
            "stories": stories,
            "coverage": coverage,
            "readership": readership,
            "rhythm": rhythm,
            "rhythm_months": RHYTHM_MONTHS,
            "reader_response": reader_response,
            "follower_count": follower_count,
            "following_count": following_count,
            "is_following": is_following,
            "follow_endpoint": reverse("staff:author_follow", args=[author.pk]),
            "meta_description": description_source[:300],
            "page_og_image": author.profile_img or None,
            "person_schema_json": self._person_schema(
                request, author, display_name, bio or description_source, role_label, socials, speciality
            ),
        }
        return render(request, "staff/portfolio.html", context)

    @staticmethod
    def _project_name():
        from SERVICE_INTERNAL.config import About

        return About.project_name

    @staticmethod
    def _person_schema(request, author, display_name, description, role_label, socials, speciality):
        """JSON-LD Person so search engines capture the username, the email
        and every reach out link on the page."""
        from SERVICE_INTERNAL.config import About

        schema = {
            "@context": "https://schema.org",
            "@type": "Person",
            "name": display_name,
            "email": f"mailto:{author.email}",
            "description": description[:300],
            "jobTitle": role_label,
            "worksFor": {"@type": "Organization", "name": PortfolioView._project_name()},
            #   REAL DOMAIN, NOT request.build_absolute_uri(): that reflects whatever
            #   host/IP/tunnel served the request, which hurts SEO ranking signals.
            "url": f"{About.domain}{request.path}",
        }
        if author.profile_img:
            schema["image"] = author.profile_img
        if author.date_joined:
            schema["hireDate"] = author.date_joined.date().isoformat()
        if speciality:
            schema["knowsAbout"] = speciality
        same_as = [social["url"] for social in socials]
        if same_as:
            schema["sameAs"] = same_as
        #   Encode < so a bio can never close the script tag early.
        return json.dumps(schema, ensure_ascii=False).replace("<", "\\u003c")


class AuthorFollowToggleView(View):
    """Follow or unfollow an author. Following means personally receiving
    the newsletter whenever this author makes a post (the sending itself is
    wired when the author newsletter ships; the note on every follow button
    already promises exactly this)."""

    def post(self, request, author_id):
        remaining_time, is_limited = is_rate_limited(request, 10, 3)
        if is_limited:
            return JsonResponse({"detail": f"Too frequent requests. Wait {remaining_time} seconds."}, status=429)

        if not is_authenticated(request.user):
            return JsonResponse({"detail": "You have to log in to follow this author."}, status=401)

        author = _portfolio_author_or_404(author_id)
        if author.pk == request.user.pk:
            return JsonResponse({"detail": "You cannot follow your own account."}, status=400)

        existing = AuthorFollow.objects.filter(follower=request.user, author=author).first()
        if existing:
            existing.delete()
            following = False
            detail = f"Unfollowed {self._display_name_for(author)}."
        else:
            AuthorFollow.objects.create(follower=request.user, author=author)
            following = True
            detail = f"Following {self._display_name_for(author)}."

        follower_count = AuthorFollow.objects.filter(author=author).count()
        logger.info("AUTHOR FOLLOW: %s %s %s", request.user.email, "followed" if following else "unfollowed", author.email)
        return JsonResponse(
            {"detail": detail, "following": following, "follower_count": follower_count},
            status=200,
        )

    @staticmethod
    def _display_name_for(author):
        profile = StaffProfile.objects.filter(auth=author).only("full_name").first()
        if profile and profile.full_name.strip():
            return profile.full_name.strip()
        return author.email.split("@")[0].title()
