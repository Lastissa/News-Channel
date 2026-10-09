import logging
import random
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.sessions.models import Session
from django.core.exceptions import BadRequest, ValidationError
from django.core.paginator import Paginator
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, Prefetch
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator
from django.views import View

from AUTHENTICATION.models import Auth, UserSession
from BLOG.models import Blog, Comment, get_category_choices
from HOME.models import Bookmark
from SERVICE_INTERNAL.abstract import (
    _optimization,
    _response,
    cache_or_run,
    get_cache,
    info_logger,
    invalidate_cache,
    is_rate_limited,
)
from SERVICE_INTERNAL.config import About, StaffConfig
from SERVICE_INTERNAL.email_batch import _try_send_account_deleted_batch_email
from SERVICE_INTERNAL.email_single import _try_send_newsletter_subscribe_email
from SERVICE_INTERNAL.images import ImageQuality, ImageUploadError, upload_news_image, upload_profile_image
from SERVICE_INTERNAL.indexnow import ping_indexnow
from SERVICE_INTERNAL.permissions import admin_only, staff_only
from SERVICE_INTERNAL.sessions import drop_sessions_for
from SERVICE_INTERNAL.story_validation import first_error_message, validate_story
from STAFF.models import GENDER_CHOICES, AuthorFollow, FollowRelationship, StaffProfile

logger = logging.getLogger(__name__)

PAGE_SIZE = 25  #   THE AMOUNT OF NEWs  TO FIRDT LOAD + THE PAGINATION AS WELL
FEATURED_COUNT = 5  #   FEATUREAD
TEASER_PLACEHOLDER_COUNT = 20  #   HOW MANY "COMING SOON" SLIDES TO SHOW IN THE HERO SIDE CAROUSEL UNTIL REAL DATA EXISTS


NOTFOUND_SUGGESTION_COUNT = 3  #   HOW MANY LATEST STORIES THE 404 PAGES SUGGEST


def latest_stories_for_404(limit=NOTFOUND_SUGGESTION_COUNT):
    """The newest stories, for the "stories you might be interested in" block
    on the 404 pages. It must never make a 404 worse, so any database trouble
    just means an empty list and the block is left out."""
    try:
        return list(
            Blog.objects.exclude(slug__isnull=True)
            .exclude(slug="")
            .select_related("author__staffprofile")
            .order_by("-date_created")[:limit]
        )
    except Exception:
        logger.exception("404 page could not load suggested stories")
        return []


def handler404(request, exception=None):
    """Site wide 404 page, framed by the regular header and footer, with the
    latest stories underneath."""
    return render(request, "HOME/404.html", {"suggested_stories": latest_stories_for_404()}, status=404)

def handler500(request, exception=None):
    html = f"""<html>
                <head>
                    <title>Service Down</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    </head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>SERVICE MODE</h1>
                    <p>System is currently in service.</p>
                    <p>Please try again later.</p>
                    <p>We are very sorry for the inconvenience.</p>
                    <p>This downtime is temporary as we are actively working on fixing some glitches with our database in order to best serve you more. </p>
                    <p>If this screen is visible for more than 30 minutes, please contact +2348113577875 so we can quickly work on it.</p>
                    <p>{About.project_name} team cares.</p>
                </body>
            </html>
            """
    return HttpResponse(html, content_type="text/html", status=500)

class RobotsTxtView(View):
    """Plain robots.txt for crawlers. Every private area (admin, control,
    internal service, auth and profile routes) is disallowed, and the sitemap
    location follows the editable About.domain in SERVICE_INTERNAL.config."""

    def get(self, request):
        domain = About.domain.rstrip("/")
        body = "\n".join(
            [
                "User-agent: *",
                "Disallow: /_admin/",
                "Disallow: /control/",
                "Disallow: /sy/",
                # "Disallow: /auth/",
                "Disallow: /profile/",
                "Disallow: /load-more/",
                "",
                f"Sitemap: {domain}/sitemap.xml",
            ]
        )
        return HttpResponse(body, content_type="text/plain; charset=utf-8")


class SitemapXmlView(View):
    """Hand built sitemap: static pages, every published story and every
    staff portfolio. No contrib.sitemaps dependency, domain comes from the
    editable About.domain so it stays correct after a config change."""

    def get(self, request):
        domain = About.domain.rstrip("/")
        urls = [
            {"loc": f"{domain}/", "lastmod": "", "changefreq": "hourly", "priority": "1.0"},
            {"loc": f"{domain}{reverse('home:privacy_policy')}", "lastmod": "", "changefreq": "yearly", "priority": "0.3"},
            {"loc": f"{domain}{reverse('home:promote')}", "lastmod": "", "changefreq": "monthly", "priority": "0.5"},
            #   /archive/ now also carries every image/file's own real,
            #   same-domain cdn/ URL (see ARCHIVE.views.CloudinaryProxyView),
            #   so the gallery page itself is worth indexing for SEO too.
            {"loc": f"{domain}{reverse('archive:gallery')}", "lastmod": "", "changefreq": "daily", "priority": "0.6"},
        ]

        stories = Blog.objects.exclude(slug__isnull=True).exclude(slug="").only(
            "id", "slug", "date_created", "last_updated"
        ).order_by("-date_created")[:2000]
        for story in stories:
            last_mod = story.last_updated or story.date_created
            if story.date_created and (not last_mod or story.date_created > last_mod):
                last_mod = story.date_created
            urls.append(
                {
                    "loc": f"{domain}{reverse('blog:story_detail', args=[story.slug])}",
                    "lastmod": last_mod.date().isoformat() if last_mod else "",
                    "changefreq": "weekly",
                    "priority": "0.8",
                }
            )

        profiles = (
            StaffProfile.objects.filter(auth__is_active=True)
            .filter(Q(auth__is_staff=True) | Q(auth__is_admin=True) | Q(auth__is_superuser=True))
            .exclude(slug__isnull=True)
            .exclude(slug="")
            .only("id", "slug")
            .order_by("slug")
        )
        for profile in profiles:
            urls.append(
                {
                    "loc": f"{domain}{reverse('staff:portfolio', args=[profile.slug])}",
                    "lastmod": "",
                    "changefreq": "weekly",
                    "priority": "0.6",
                }
            )

        return render(request, "HOME/sitemap.xml", {"urls": urls}, content_type="application/xml")

class FavicoView(View):
    def get(self, request):
        return redirect(to='/static/logo.jpg', preserve_request=True, permanent=True)
    
class BingIndexNowView(View):
    """BING SAY TO INDEX RIGHT AWAY, THIS HELPS"""
    def get(self, request):
        return render(request, '28499029458943a79b9877afdefa8212.txt')
class YandexIndexNow(View):
    """YANDEX SAY MALE I PUT AM FOR INDEXING ON THEIR OWN SIDE"""
    def get(self, request):
        return render(request, "yandex_1093315bd8192b90.html")


def _bookmarked_ids(user):
    if not user.is_authenticated:
        return set()
    #THIS POTENTIALLY CAN CAUSE A N+1 BUT SINCE WE ARE WORKING ON PAGINATED PAGE , I AM SAFE
    return set(Bookmark.objects.filter(user=user).values_list("blog_id", flat=True))


def _page_context(page, user):
    return {
        "page_obj": page,
        "saved_ids": _bookmarked_ids(user),
        "has_more": page.has_next(),
        "next_page": page.next_page_number() if page.has_next() else page.number,
    }


def _teaser_items():
    """Data for the hero's side picture carousel (HOME/home.html). Each item is
    {heading, body, image, url}. Real data is the live Partner.AdvertImage rows
    the admin manages in PANEL (active + not expired, newest first). Until at
    least one exists the old placeholder slides are shown so the carousel is
    never empty. The template and hero-teaser.js only read those four keys."""
    from Partner.models import AdvertImage
    live = AdvertImage.objects.filter(expiry_date__gte=timezone.now(), is_active=True).order_by("-date_created")
    if live:
        return [{"heading": row.heading, "body": row.body, "image": row.image_url, "url": row.url or ""} for row in live]

    from django.templatetags.static import static
    curent_dummy_image = [
        static('partner/ad_demo_1.jpg'),
        static('partner/ad_demo_2.jpg'),
        static('partner/ad_demo_3.jpg'),
    ]
    len_current_dummy = len(curent_dummy_image) -1  if bool(curent_dummy_image) else 0
    return [
        {
            "heading": "Have something to promote? Let’s help you get the word out! Whether it’s your business, product, service, or event, we’d love to help you reach more people.",
            "body": "Tap the image above to reach us and let’s work together!",
            "image": curent_dummy_image[random.randint(0, len_current_dummy - 1)],
            "url": "/"
        }
        for _ in range(TEASER_PLACEHOLDER_COUNT)
            ]

def _resolve_page_number(raw_value, *, default=1):
    if raw_value is None or raw_value == "":
        return default
    try:
        page_number = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise BadRequest("Invalid page number.") from exc
    if page_number < 1:
        raise Http404("Page not found.")
    return page_number


def _user_sessions_for_profile(user, request):
    if not user.is_authenticated:
        return []

    current_key = request.session.session_key

    rows = UserSession.objects.filter(user=user).order_by("-logged_in_at")
    return [{
            "session_key": row.session_key,
            "ip": row.ip or "Unknown IP",
            "device": row.user_agent or "Unknown device",
            "logged_in_at": row.logged_in_at,
            "expires_at": row.expires_at,
            "is_current": row.session_key == current_key,
            }
            for row in rows
    ]
    
    

def _ad_center_items():
    """Content of the AD CENTER bar at the top of the home page. Each item is
    {"text": ..., "url": ...} and is rendered as an underlined link. Placeholder
    "coming soon" data for now -- replace the list below (or load it from the
    database) and the template needs no changes. External urls (http...) open
    in a new tab automatically."""
    from Partner.models import AdvertText
    active_advert = AdvertText.objects.filter(expiry_date__gte = timezone.now(), is_active = True)
    if active_advert:
        return [{"text": i.ad_content, "url": i.url  or "#"} for i in active_advert]
    else:
        return [{'text': 'Do You Know You Can Boost Your Bussiness Online Presence By Clicking HERE', 'url': 'https:localhost:8000/missing/'}]


def _home_blog_queryset():
    return (
        Blog.objects.select_related("author")
        .prefetch_related(
            Prefetch(
                "author__staffprofile",
                queryset=StaffProfile.objects.only("auth_id", "full_name"),
            )
        )
        .only(
            "id",
            "image_1",
            "image_info",
            "author_id",
            "category",
            "slug",
            "date_created",
            "heading",
            "content",
        )
        .order_by("-date_created")
    )


class HomeView(View):
    """Landing page: hero carousel of featured stories and paginated story grid."""

    def get(self, request):
        #q = the actual heading to filter
        #category = self explatory
        query = request.GET.get("q", "").strip()
        category = request.GET.get("category", "").strip().upper()
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        is_filtered = bool(query or category)

        if is_filtered:
            base_qs = _home_blog_queryset()
            if query:
                base_qs = base_qs.filter(heading__icontains=query)
            if category:
                base_qs = base_qs.filter(category=category)
            featured = []
            paginator = Paginator(base_qs, PAGE_SIZE)
        else:
            home_posts = cache_or_run("home_page_blogs",fn=lambda: {"posts": list(_home_blog_queryset())},timeout=None)["posts"]
            featured = home_posts[:FEATURED_COUNT]
            featured_ids = {post.id for post in featured}
            grid_posts = [post for post in home_posts if post.id not in featured_ids]
            paginator = Paginator(grid_posts, PAGE_SIZE)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        page = paginator.get_page(page_number)

        #   HEADLINE TICKER: same continuous marquee behaviour as the top-of-page
        #   reading ticker on the story page (BLOG.views.build_ticker_text /
        #   BLOG/static/blog/js/story-ticker.js), but fed with the headings of
        #   whatever stories are actually on this page (hero + grid) instead of
        #   one story's content. Empty on a filtered/search view, same as the
        #   hero row above.
        headline_ticker_text = (
            " * ".join(post.heading for post in list(featured) + list(page.object_list) if post.heading)
            if not is_filtered else ""
        )

        context = {
            "featured_posts": featured,
            "headline_ticker_text": headline_ticker_text,
            "ad_center_items": _ad_center_items(),
            "teaser_items": _teaser_items(),
            "categories": get_category_choices(),
            "query": query,
            "active_category": category,
            "is_filtered": is_filtered,
            "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
            **_page_context(page, request.user),
        }
        return render(request, "HOME/home.html", context)


class LoadMoreView(View):
    """Returns the next page of story cards for the "Load more" button."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        category = request.GET.get("category", "").strip().upper()
        page_number = _resolve_page_number(request.GET.get("page"), default=2)

        is_filtered = bool(query or category)
        if is_filtered:
            base_qs = _home_blog_queryset()
            if query:
                base_qs = base_qs.filter(heading__icontains=query)
            if category:
                base_qs = base_qs.filter(category=category)
            grid_qs = base_qs
        else:
            home_posts = cache_or_run(
                "home_page_blogs_v2",
                fn=lambda: {"posts": list(_home_blog_queryset())},
                timeout=None,
            )["posts"]
            featured_ids = {post.id for post in home_posts[:FEATURED_COUNT]}
            grid_qs = [post for post in home_posts if post.id not in featured_ids]

        paginator = Paginator(grid_qs, PAGE_SIZE)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        page = paginator.get_page(page_number)
        return render(
            request,
            "HOME/partials/story_cards.html",
            {**_page_context(page, request.user), "next_page": page.next_page_number() if page.has_next() else None},
        )


class BookmarkView(View):
    """toggles a bookmark for the logged in user. Always
    returns a JSON body with a `detail` key, status code carries the meaning."""

    def post(self, request, blog_id):
        if not request.user.is_authenticated:
            return _response({"detail": "Sign in to save stories."}, status=401)

        try:
            blog = Blog.objects.get(pk=blog_id)
        except Blog.DoesNotExist:
            return _response({"detail": "Story not found."}, status=404)

        existing = Bookmark.objects.filter(user=request.user, blog=blog).first()
        if existing:
            remaining_time, is_limited = is_rate_limited(request, 2, 2, True)
            if is_limited:
                unit = "second" if remaining_time == 1 else "seconds"
                return _response(
                    {"detail": f"Too frequent bookmark removals. Try again in {remaining_time} {unit}."},
                    status=429,
                )
            existing.delete()
            return _response({"detail": "Removed from bookmarks.", "bookmarked": False, "bookmark_count": blog.bookmarked_by.count()}, status=200)

        Bookmark.objects.create(user=request.user, blog=blog)
        return _response({"detail": "Saved to bookmarks.", "bookmarked": True, "bookmark_count": blog.bookmarked_by.count()}, status=201)


class AddNewsView(View):
    """Staff only two pane story editor. GET serves the split loading page,
    POST validates and publishes the story."""

    def dispatch(self, request, *args, **kwargs):
        if not staff_only(request.user):
            messages.info(request, "Sign in to open the editor.")
            url = reverse("auth:login") + "?" + urlencode({"to": "/profile/add-news"})
            return redirect(url)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return render(request, "HOME/add_news.html")

    def post(self, request):
        heading = (request.POST.get("heading") or "").strip()
        image_url = (request.POST.get("image_1") or "").strip()
        image_file = request.FILES.get("image_file")
        image_quality = (request.POST.get("image_quality") or ImageQuality.MEDIUM).strip().lower()
        image_info = (request.POST.get("image_info") or "").strip()
        category = (request.POST.get("category") or "").strip().upper()
        content = (request.POST.get("content") or "").strip()

        if not heading:
            return _response({"detail": "The heading cannot be empty."}, status=400)
        if len(heading) > 100:
            return _response({"detail": "The heading is limited to 100 characters."}, status=400)
        if category not in {value for value, _ in get_category_choices()}:
            return _response({"detail": "Select a valid category."}, status=400)
        if not content:
            return _response({"detail": "The story content cannot be empty."}, status=400)

        #   AUTHOR WRITING RULES (SERVICE_INTERNAL.story_validation). Runs on the
        #   server, BEFORE any image is sent to cloudinary or anything is saved,
        #   so a hand built request cannot skip it. `content` is only inspected,
        #   never changed, so the author's markdown is stored exactly as typed.
        #     errors   -> hard block (400), the author must fix them
        #     warnings -> 409 "needs_confirmation": the author is told why and
        #                 chooses Post anyway (resend with confirm_warnings=1)
        #                 or Go back and edit
        validation = validate_story(heading, content)
        if validation["errors"]:
            return _response(
                {
                    "detail": first_error_message(validation),
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                    "blocked": True,
                },
                status=400,
            )
        confirmed = (request.POST.get("confirm_warnings") or "").strip().lower() in {"1", "true", "yes"}
        if validation["warnings"] and not confirmed:
            return _response(
                {
                    "detail": "Please review these writing notes before this story is posted.",
                    "warnings": validation["warnings"],
                    "needs_confirmation": True,
                },
                status=409,
            )

        #   AN UPLOADED FILE ALWAYS WINS OVER A PASTED URL. Nothing is sent
        #   to cloudinary until this line, i.e. not while the staff member
        #   is still typing/previewing, only once they publish.
        image_public_id = ""
        if image_file:
            try:
                uploaded_image = upload_news_image(image_file, quality=image_quality)
            except ImageUploadError as exc:
                return _response({"detail": str(exc)}, status=400)
            image_url = uploaded_image["secure_url"]
            #   SAVED ONTO THE ROW BELOW SO A FUTURE "EDIT STORY" UPLOAD CAN
            #   PASS THIS BACK INTO upload_news_image(public_id=...) AND
            #   OVERWRITE THIS EXACT ASSET IN PLACE INSTEAD OF LEAVING IT AS
            #   AN ORPHAN WHILE A NEW ONE GETS CREATED FOR THE REPLACEMENT.
            image_public_id = uploaded_image["public_id"]
        elif image_url:
            validator = URLValidator(schemes=["http", "https"])
            try:
                validator(image_url)
            except ValidationError:
                return _response({"detail": "The image link must be a valid http or https URL."}, status=400)

        #   THE SAME AUTHOR CANNOT PUBLISH THE SAME HEADING INTO THE SAME
        #   CATEGORY TWICE (mirrors the database constraint on Blog)
        if Blog.objects.filter(author=request.user, category=category, heading__iexact=heading).exists():
            return _response(
                {"detail": "You already have a story with this exact heading in this category. Edit the heading or choose a different category."},
                status=400,
            )

        try:
            blog_data = dict(
                author=request.user,
                heading=heading,
                image_1=image_url or None,
                image_public_id=image_public_id,
                category=category,
                content=content,
            )
            if image_info:
                blog_data["image_info"] = image_info
            blog = Blog.objects.create(**blog_data)
        except IntegrityError:
            return _response(
                {"detail": "You already have a story with this exact heading in this category. Edit the heading or choose a different category."},
                status=400,
            )

        story_url = f"{About.domain.rstrip('/')}{reverse('blog:story_detail', args=[blog.slug])}"
        #   TELL BING/INDEXNOW RIGHT AWAY THAT THIS ONE STORY EXISTS, instead
        #   of waiting for their crawler to stumble on it later -- see
        #   SERVICE_INTERNAL.indexnow.ping_indexnow. Fire-and-forget: this
        #   can never fail the publish itself.
        ping_indexnow(story_url)
        # invalidate the home_page_blogs so new article can be get
        invalidate_cache("home_page_blogs")
        #TODO: send email of new news alert to all users who have news alert on and they follow the author + users who do not follow anyone, run in a background task and make sure in debug true it should not send anything , just a info_logger print
        return _response(
            {"detail": "Story published.", "story_url": reverse("blog:story_detail", args=[blog.slug]), "id": blog.pk},
            status=201,
        )


class EditNewsView(View):
    """Staff only. Re-opens one of the signed in author's OWN published stories
    in the same two pane editor as AddNewsView, prefilled, and saves it back in
    place. Reached from the "Published stories" list on the profile page.

    WHAT CAN CHANGE: the banner (a pasted image link or an uploaded file, plus
    its one line caption `image_info`), the `category` and the `content`.

    THE HEADING CAN NEVER CHANGE. It is not read from the request at all, and it
    is left out of `update_fields` when saving, so even a hand built POST that
    carries a `heading` cannot touch it (see the long note on `Blog.heading`:
    the public URL slug is built from it once and must keep describing the
    story).

    An edit that changes nothing is not saved, so `last_edited` (and with it
    the "this post was last updated ..." notice readers see on the story page)
    only moves when something really changed.
    """

    def dispatch(self, request, *args, **kwargs):
        if not staff_only(request.user):
            return redirect("home:profile")
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _own_story(request, blog_id):
        return Blog.objects.filter(pk=blog_id, author=request.user).first()

    def get(self, request, blog_id):
        blog = self._own_story(request, blog_id)
        if blog is None:
            messages.error(request, "Story not found. You can only edit stories you published.")
            return redirect("home:profile")

        #   STORIES PUBLISHED UNDER A CATEGORY THAT NO LONGER EXISTS (removed
        #   from PANEL, or never seeded, e.g. SECURITY). Without this the <select> would have no option for
        #   the story's real category and the browser would silently fall back to
        #   another one on save.
        current_categories = {value for value, _ in get_category_choices()}
        return render(
            request,
            "HOME/edit_news.html",
            {
                "blog": blog,
                "legacy_category": blog.category if blog.category not in current_categories else "",
            },
        )

    def post(self, request, blog_id):
        blog = self._own_story(request, blog_id)
        if blog is None:
            return _response({"detail": "Story not found."}, status=404)

        #   NOTE: `heading` is deliberately never read from request.POST.
        image_url = (request.POST.get("image_1") or "").strip()
        image_file = request.FILES.get("image_file")
        image_quality = (request.POST.get("image_quality") or ImageQuality.MEDIUM).strip().lower()
        default_image_info = Blog._meta.get_field("image_info").default
        image_info = (request.POST.get("image_info") or "").strip() or default_image_info
        category = (request.POST.get("category") or "").strip().upper()
        content = (request.POST.get("content") or "").strip()

        allowed_categories = {value for value, _ in get_category_choices()} | {blog.category}
        if category not in allowed_categories:
            return _response({"detail": "Select a valid category."}, status=400)
        if not content:
            return _response({"detail": "The story content cannot be empty."}, status=400)
        if len(image_info) > Blog._meta.get_field("image_info").max_length:
            return _response({"detail": "The image description is limited to 100 characters."}, status=400)

        new_image_url = blog.image_1
        new_public_id = blog.image_public_id

        if not image_file:
            if image_url:
                validator = URLValidator(schemes=["http", "https"])
                try:
                    validator(image_url)
                except ValidationError:
                    return _response({"detail": "The image link must be a valid http or https URL."}, status=400)
                if len(image_url) > Blog._meta.get_field("image_1").max_length:
                    return _response({"detail": "The image link is too long."}, status=400)
                #   THE BOX IS PREFILLED WITH THE CURRENT BANNER LINK, SO THE
                #   SAME VALUE COMING BACK MEANS "LEAVE THE BANNER ALONE"
                #   (this also keeps the Cloudinary public id of an uploaded one).
                if image_url != (blog.image_1 or ""):
                    new_image_url = image_url
                    new_public_id = ""
            else:
                #   BOX CLEARED AND NO FILE PICKED: THE BANNER IS REMOVED
                new_image_url = None
                new_public_id = ""

        #   THE SAME AUTHOR CANNOT HOLD THE SAME HEADING TWICE IN ONE CATEGORY
        #   (mirrors the database constraint), so moving a story into another
        #   category can collide with a sibling story. Checked BEFORE anything is
        #   sent to Cloudinary so a refused edit never leaves a new picture behind.
        if (
            category != blog.category
            and Blog.objects.filter(author=request.user, category=category, heading__iexact=blog.heading)
            .exclude(pk=blog.pk)
            .exists()
        ):
            return _response(
                {"detail": "You already have a story with this exact heading in that category. Choose a different category."},
                status=400,
            )

        story_path = reverse("blog:story_detail", args=[blog.slug])

        def normalised(text):
            return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

        changed = bool(
            image_file
            or (new_image_url or "") != (blog.image_1 or "")
            or new_public_id != blog.image_public_id
            or image_info != blog.image_info
            or category != blog.category
            or normalised(content) != normalised(blog.content)
        )
        if not changed:
            return _response({"detail": "No changes to save.", "changed": False, "story_url": story_path, "id": blog.pk}, status=200)

        #   AN UPLOADED FILE ALWAYS WINS OVER A PASTED URL, same rule as Add.
        #   Passing the story's existing `image_public_id` makes Cloudinary
        #   overwrite that same asset instead of orphaning it (see
        #   SERVICE_INTERNAL.images.upload_news_image). A story whose banner was
        #   a pasted link has no id yet, so it gets a fresh one that is saved.
        if image_file:
            try:
                uploaded_image = upload_news_image(
                    image_file,
                    quality=image_quality,
                    public_id=blog.image_public_id or None,
                )
            except ImageUploadError as exc:
                return _response({"detail": str(exc)}, status=400)
            new_image_url = uploaded_image["secure_url"]
            new_public_id = uploaded_image["public_id"]
        elif blog.image_public_id and not new_public_id:
            #   THE BANNER MOVED FROM AN UPLOADED FILE TO A PASTED LINK (or was
            #   removed). Same as deleting a story today, the old Cloudinary
            #   asset is not destroyed, it is only logged so it can be cleaned
            #   by hand.
            info_logger(msg=f"EDIT STORY {blog.pk}: banner no longer uses Cloudinary asset {blog.image_public_id}")

        blog.image_1 = new_image_url
        blog.image_public_id = new_public_id
        blog.image_info = image_info
        blog.category = category
        blog.content = content
        blog.last_edited = timezone.now()

        #   update_fields, not a bare save(): a full save would write back the
        #   `views` / `likes` this request loaded and wipe any that came in while
        #   the author was editing. "heading" is intentionally absent from the
        #   list. "last_updated" must be listed for its auto_now to fire (it
        #   feeds the sitemap lastmod and the dateModified JSON-LD).
        try:
            blog.save(
                update_fields=[
                    "image_1",
                    "image_public_id",
                    "image_info",
                    "category",
                    "content",
                    "last_edited",
                    "last_updated",
                ]
            )
        except IntegrityError:
            return _response(
                {"detail": "You already have a story with this exact heading in that category. Choose a different category."},
                status=400,
            )

        #   TELL BING/INDEXNOW THE PAGE CHANGED, same fire-and-forget ping Add uses
        ping_indexnow(f"{About.domain.rstrip('/')}{story_path}")

        return _response(
            {"detail": "Story updated.", "changed": True, "story_url": story_path, "id": blog.pk},
            status=200,
        )


class NewsletterSubscribeView(View):
    """Footer newsletter signup. The email becomes a real account with a fixed
    dev only starter password and the newsletter flag switched on. The visitor
    is never logged in: they only opted into the newsletter, and the starter
    password exists so no account is passwordless.
"""
    # REMINDER Never reveal this password to outsider as it can be a potential break in
    STARTER_PASSWORD = "newuser"

    def post(self, request):
        remaining_time, is_limited = is_rate_limited(request, 10, 2)
        if is_limited:
            unit = "second" if remaining_time == 1 else "seconds"
            return _response({"detail": f"Too many requests. Try again in {remaining_time} {unit}."}, status=429)

        email = request.POST.get("email", '').strip()

        if not email or "@" not in email:
            return _response({"detail": "Invalid email address."}, status=400)

        user_model = get_user_model()
        existing = user_model.objects.filter(email__iexact=email).first()
        if existing is not None:
            if not existing.send_newsletter:
                existing.send_newsletter = True
                existing.save(update_fields=["send_newsletter"])
                _try_send_newsletter_subscribe_email(email)
                return _response({"detail": "Nesletter now active for this user."}, status=200)
            return _response({"detail": "You've already susbribed before."}, status=400)

        user_model.objects.create_user(email=email, password=self.STARTER_PASSWORD, send_newsletter=True)
        info_logger( msg = f"NEWSLETTER SIGNUP: {email} subscribed, account created")
        _try_send_newsletter_subscribe_email(email)
        return _response({"detail": "Welcome Odogwu."}, status=201)


class PrivacyPolicyView(View):
    def get(self, request):
        """TODO: Create a Quick Navigation for users istead of just header and contents in the privacy_policy.html file"""
        return render(request, "HOME/privacy_policy.html")


class PromoteView(View):
    """Dummy placeholder for the footer's 'promote your business' banner.
    No form/backend logic yet -- just a page to land on until that flow
    is designed."""

    def get(self, request):
        return HttpResponse("still in progress")
        return render(request, "HOME/promote.html")


class ProfileLoginAlert(View):
    """Toggle Login Alert Wether to receive mail or not for login."""

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 3, 5,True)
        if limited:
            return JsonResponse({'detail': f'SPAM: oga calm down for {remaining_seconds} sec!!!'.upper()})
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to update settings.", "enabled": False}, status=401)

        current_state = bool(getattr(request.user, "receive_email_login_alert", True))
        new_state = not current_state
        request.user.receive_email_login_alert = new_state
        request.user.save(update_fields=["receive_email_login_alert"])

        return JsonResponse(
            {
                "detail": "Login alerts enabled." if new_state else "Login alerts disabled.",
                "enabled": new_state,
                "status": "on" if new_state else "off",
            },
            status=200,
        )


class ProfileSendNewsletterToggleView(View):
    """Toggle the news digest delivery (Auth.send_newsletter) without a full
    page refresh. Every account carries the flag, staff or member."""

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to update settings.", "enabled": False}, status=401)

        new_state = not bool(getattr(request.user, "send_newsletter", False))
        request.user.send_newsletter = new_state
        request.user.save(update_fields=["send_newsletter"])

        return JsonResponse(
            {
                "detail": "Thank you. News Update Enabled" if new_state else "News updates disabled.",
                "enabled": new_state,
                "status": "on" if new_state else "off",
            },
            status=200,
        )


class ProfileBlogNotificationToggleView(View):
    """Toggle post-view reminders for staff. This is a staff level setting,
    not an admin power, so it lives with the other profile toggles rather
    than in the ADMIN app."""

    def post(self, request):
        if not staff_only(request.user):
            return JsonResponse({"detail": "Staff access is required.", "enabled": False}, status=403)

        profile = StaffProfile.objects.filter(auth=request.user).first()
        if profile is None:
            return JsonResponse(
                {"detail": "No staff profile on this account yet. Save your staff profile first.", "enabled": False},
                status=409,
            )

        new_state = not profile.get_blog_notification
        profile.get_blog_notification = new_state
        profile.save(update_fields=["get_blog_notification"])

        return JsonResponse(
            {
                "detail": "Story view reminders enabled." if new_state else "Story view reminders disabled.",
                "enabled": new_state,
                "status": "on" if new_state else "off",
            },
            status=200,
        )


class ProfileFollowerNotificationToggleView(View):
    """Toggle the new follower email for an author (StaffProfile.get_follower_notification)."""

    def post(self, request):
        if not staff_only(request.user):
            return JsonResponse({"detail": "Staff access is required.", "enabled": False}, status=403)

        profile = StaffProfile.objects.filter(auth=request.user).first()
        if profile is None:
            return JsonResponse(
                {"detail": "No staff profile on this account yet. Save your staff profile first.", "enabled": False},
                status=409,
            )

        new_state = not profile.get_follower_notification
        profile.get_follower_notification = new_state
        profile.save(update_fields=["get_follower_notification"])

        return JsonResponse(
            {
                "detail": "New follower alerts enabled." if new_state else "New follower alerts disabled.",
                "enabled": new_state,
                "status": "on" if new_state else "off",
            },
            status=200,
        )


class ProfileLogoutAllSessionsView(View):
    """End every session the signed in user holds, the current one included.

    The response is JSON because the fetch caller redirects to the login
    page itself: the session that made this request is gone by the time the
    response arrives.
    """

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in first."}, status=401)

        remaining_time, is_limited = is_rate_limited(request, 30, 2)
        if is_limited:
            return JsonResponse({"detail": f"Too many attempts. Wait {remaining_time} seconds."}, status=429)

        email = request.user.email
        dropped = drop_sessions_for(request.user)
        #   flush() clears whatever the session middleware would otherwise
        #   re-save for this request, so this browser is signed out too.
        auth_logout(request)
        info_logger(msg= f"ACCOUNT LOGOUT ALL: {email} ended {dropped} session(s)")

        return JsonResponse(
            {
                "detail": f"Signed out of {dropped} session(s).",
                "sessions_ended": dropped,
                "redirect_to": reverse("auth:login"),
            },
            status=200,
        )


class ProfileImageUpdateView(View):
    """Save a new profile image from an uploaded file. The file always goes
    through SERVICE_INTERNAL.images.upload_profile_image, which applies a
    fixed, automatic optimization, i.e. the person never picks a quality
    here, that choice only exists for staff on the Add news page. A profile
    image can no longer be set from a pasted link."""

    @staticmethod
    def _too_frequent(request):
        """A 429 JsonResponse when this client is updating too often, else None."""
        remaining_time, is_limited = is_rate_limited(request, 30, 2,False)
        if is_limited: return JsonResponse({'detail': f'too frequent update. Retry in {str(remaining_time) + "seconds" if remaining_time>1 else str(remaining_time)+" second"}'}, status = 429)
        return None

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to update your profile image.", "valid": False}, status=401)

        image_file = request.FILES.get("image_file")
        if not image_file:
            return JsonResponse({"detail": "Please choose an image file to upload.", "valid": False}, status=400)

        #   RATE LIMIT BEFORE CLOUDINARY: the upload overwrites this user's one avatar asset in place, so a
        #   request that is going to be refused must never get as far as touching it.
        too_frequent = self._too_frequent(request)
        if too_frequent: return too_frequent
        try:
            image_url = upload_profile_image(image_file, request.user.pk)
        except ImageUploadError as exc:
            return JsonResponse({"detail": str(exc), "valid": False}, status=400)

        request.user.profile_img = image_url
        request.user.save(update_fields=["profile_img"])
        return JsonResponse({"detail": "Profile image updated.", "valid": True, "image_url": image_url}, status=200)


def _mask_email(email):
    """Partial email for the followers list: keep the first two letters of the
    name and the whole domain, hide the rest (ab***@gmail.com)."""
    local, _, domain = (email or "").lower().partition("@")
    if not domain:
        return "***"
    return f"{local[:2]}***@{domain}" if len(local) > 2 else f"{local[:1]}***@{domain}"


def _author_label(auth, names):
    """Full name when the account has one, else the part of the email before @."""
    return (names.get(auth.pk) or "").strip() or auth.email.partition("@")[0]


def _following_page(user, search_query, page_number):
    """Authors `user` follows, newest follow first (5 per page). Returns the
    paginator page plus display rows for the template."""
    qs = AuthorFollow.objects.filter(follower=user).select_related("author").order_by("-created_at", "-id")
    if search_query:
        qs = qs.filter(Q(author__email__icontains=search_query) | Q(author__staffprofile__full_name__icontains=search_query))
    paginator = Paginator(qs, 5)
    page = paginator.get_page(page_number)
    rows = list(page.object_list)
    profiles = {
        sp.auth_id: sp
        for sp in StaffProfile.objects.filter(auth_id__in=[row.author_id for row in rows]).only("auth_id", "full_name", "slug")
    }
    items = []
    for row in rows:
        sp = profiles.get(row.author_id)
        items.append(
            {
                "author_id": row.author_id,
                "name": _author_label(row.author, {row.author_id: sp.full_name if sp else ""}),
                "portfolio_url": reverse("staff:portfolio", args=[sp.slug]) if sp and sp.slug else "",
                "since": row.created_at,
                "unfollow_url": reverse("home:profile_unfollow", args=[row.author_id]),
            }
        )
    return page, paginator, items


def _followers_page(user, page_number):
    """Accounts following `user` (an author), newest first, emails masked."""
    qs = AuthorFollow.objects.filter(author=user).select_related("follower").order_by("-created_at", "-id")
    paginator = Paginator(qs, 5)
    page = paginator.get_page(page_number)
    items = [{"email": _mask_email(row.follower.email), "since": row.created_at} for row in page.object_list]
    return page, paginator, items


class ProfileBookmarksView(View):
    """Render the bookmarks list partial for the profile page.

    The profile template pages and searches this list with HTMX
    (profile_list_pagination.html + the search box), so the response has to
    be the HTML partial, never JSON.
    """

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to view bookmarks."}, status=401)

        search_query = (request.GET.get("q") or "").strip()[:100]
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        bookmarks_qs = Bookmark.objects.filter(user=request.user).select_related("blog").order_by("-created_at")
        if search_query:
            bookmarks_qs = bookmarks_qs.filter(blog__heading__icontains=search_query)

        paginator = Paginator(bookmarks_qs, 5)
        page = paginator.get_page(page_number)

        return render(
            request,
            "HOME/partials/profile_bookmarks_list.html",
            {
                "recent_bookmarks": page.object_list,
                "bookmark_page_obj": page,
                "bookmark_page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "search_query": search_query,
            },
        )


class ProfileHistoryView(View):
    """Render the reading-history list partial for the profile page.

    The profile template pages and searches this list with HTMX, so the
    response has to be the HTML partial, never JSON.
    """

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to view history."}, status=401)

        search_query = (request.GET.get("q") or "").strip()[:100]
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        history_qs = Blog.objects.filter(non_anonymous_viewer=request.user).order_by("-date_created")
        if search_query:
            history_qs = history_qs.filter(heading__icontains=search_query)

        paginator = Paginator(history_qs, 5)
        page = paginator.get_page(page_number)

        return render(
            request,
            "HOME/partials/profile_history_list.html",
            {
                "reading_history": page.object_list,
                "history_page_obj": page,
                "history_page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "search_query": search_query,
            },
        )


class ProfileFollowingView(View):
    """HTML partial: the authors the signed in account follows (HTMX paging and search)."""

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to view who you follow."}, status=401)
        search_query = (request.GET.get("q") or "").strip()[:100]
        page, paginator, items = _following_page(request.user, search_query, _resolve_page_number(request.GET.get("page"), default=1))
        return render(
            request,
            "HOME/partials/profile_following_list.html",
            {
                "following_items": items,
                "following_page_obj": page,
                "following_page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "search_query": search_query,
                "oob": True,
            },
        )


class ProfileUnfollowView(View):
    """Unfollow only (never toggles), so a stale tab can not follow again by accident."""

    def post(self, request, author_id):
        remaining_time, is_limited = is_rate_limited(request, 10, 10, scope="profile_unfollow")
        if is_limited:
            return JsonResponse({"detail": f"Too frequent requests. Wait {remaining_time} seconds."}, status=429)
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in."}, status=401)
        deleted, _ = AuthorFollow.objects.filter(follower=request.user, author_id=author_id).delete()
        if not deleted:
            return JsonResponse({"detail": "You were not following this author.", "following": False}, status=200)
        return JsonResponse({"detail": "Unfollowed.", "following": False}, status=200)


class ProfileFollowersView(View):
    """HTML partial: who follows this author. Staff level accounts only; emails are masked."""

    def get(self, request):
        if not staff_only(request.user):
            return JsonResponse({"detail": "Only authors have followers."}, status=403)
        page, paginator, items = _followers_page(request.user, _resolve_page_number(request.GET.get("page"), default=1))
        return render(
            request,
            "HOME/partials/profile_followers_list.html",
            {
                "followers_items": items,
                "followers_page_obj": page,
                "followers_page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "oob": True,
            },
        )


class ProfileCommentsView(View):
    """Return a paginated comment-history payload for the profile page."""

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to view comments."}, status=401)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        comments_qs = Comment.objects.filter(author=request.user).select_related("blog").order_by("-id")
        paginator = Paginator(comments_qs, 5)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")

        page = paginator.get_page(page_number)
        items = [
            {
                "id": comment.id,
                "blog_id": comment.blog_id,
                "heading": comment.blog.heading,
                "excerpt": Truncator(comment.content).chars(85),
                "url": reverse("blog:story_detail", args=[comment.blog.slug]),
            }
            for comment in page.object_list
        ]

        return JsonResponse(
            {
                "items": items,
                "page": page.number,
                "num_pages": paginator.num_pages,
                "has_previous": page.has_previous(),
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
                "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "count": paginator.count,
            },
            status=200,
        )


class ProfileStaffUpdateView(View):
    """Staff self-service profile updates with per-field permissions.

    full_name, socials and bio are editable by any staff account. gender and
    speciality are admin/superuser only (their inputs are disabled for plain
    staff so those keys never reach the POST). role is assigned at
    registration and is never accepted from this endpoint.
    """

    def post(self, request):
        remaining_time, is_limited = is_rate_limited(request, 10, 3)
        if is_limited:
            return _response({'detail': f'PERMISSION DENIED, wait {remaining_time} seconds before trying again'}, status=429)
        if not staff_only(request.user):
            return JsonResponse({"detail": "Staff access is required!. Refresh Page"}, status=403)

        profile, _ = StaffProfile.objects.get_or_create(auth=request.user)

        full_name = (request.POST.get("full_name") or "").strip()
        if not full_name:
            return JsonResponse({"detail": "Full name cannot be empty."}, status=400)
        if len(full_name) > 100:
            return JsonResponse({"detail": "Full name is limited to 100 characters."}, status=400)
        profile.full_name = full_name

        profile.bio = (request.POST.get("bio") or "").strip()

        validator = URLValidator(schemes=["http", "https"])
        for field in ("twitter_handle", "facebook_handle", "whatsapp_handle"):
            value = (request.POST.get(field) or "").strip()
            if value:
                try:
                    validator(value)
                except ValidationError:
                    return JsonResponse({"detail": f"The {field.replace('_handle', '')} link must be a valid http or https URL."}, status=400)
            setattr(profile, field, value or None)

        editable_fields = ["full_name", "bio", "twitter_handle", "facebook_handle", "whatsapp_handle"]

        is_admin = admin_only(request.user)
        if "gender" in request.POST:
            if not is_admin:
                return JsonResponse({"detail": "Only admins can change gender."}, status=403)
            gender = request.POST.get("gender", "")
            if gender not in {value for value, _ in GENDER_CHOICES}:
                return JsonResponse({"detail": "Select a valid gender option."}, status=400)
            profile.gender = gender
            editable_fields.append("gender")

        if "speciality" in request.POST:
            if not is_admin:
                return JsonResponse({"detail": "Only admins can change speciality."}, status=403)
            raw = request.POST.get("speciality", "")
            profile.speciality = [part.strip() for part in raw.split(",") if part.strip()]
            editable_fields.append("speciality")

        profile.save(update_fields=editable_fields)

        return JsonResponse(
            {
                "detail": "Staff profile updated.",
                "full_name": profile.full_name,
                "gender": profile.gender,
                "speciality_csv": ", ".join(profile.speciality) if isinstance(profile.speciality, list) else "",
                "bio": profile.bio,
                "twitter_handle": profile.twitter_handle or "",
                "facebook_handle": profile.facebook_handle or "",
                "whatsapp_handle": profile.whatsapp_handle or "",
                "role_display": profile.get_role_display(),
            },
            status=200,
        )


class ProfilePublishedView(View):
    """Render the published-stories list partial for the staff profile.

    The profile template pages and searches this list with HTMX, so the
    response has to be the HTML partial, never JSON.
    """

    def get(self, request):
        if not staff_only(request.user):
            return JsonResponse({"detail": "Staff access is required to view published stories!. Refresh Page"}, status=401)

        search_query = (request.GET.get("q") or "").strip()[:100]
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        published_qs = Blog.objects.filter(author=request.user).order_by("-date_created")
        if search_query:
            published_qs = published_qs.filter(heading__icontains=search_query)

        paginator = Paginator(published_qs, 5)
        page = paginator.get_page(page_number)

        return render(
            request,
            "HOME/partials/profile_published_list.html",
            {
                "published_stories": page.object_list,
                "stories_page_obj": page,
                "stories_page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "search_query": search_query,
                #   the "N total" tag is swapped out of band after a delete refresh, and it must
                #   stay the unfiltered total even while the search box is filtering the list
                "oob": True,
                "published_total": Blog.objects.filter(author=request.user).count(),
            },
        )


class ProfilePublishedDeleteView(View):
    """Delete a story from its author's profile dashboard."""

    def post(self, request, blog_id):
        if not staff_only(request.user):
            return JsonResponse({"detail": "Staff access is required to delete a story!. Refresh Page"}, status=403)

        blog = Blog.objects.filter(pk=blog_id, author=request.user).first()
        if blog is None:
            return JsonResponse({"detail": "Story not found."}, status=404)

        blog.delete()
        return JsonResponse({"detail": "Story deleted.", "id": blog_id}, status=200)


class ProfileView(View):
    """Shared profile dashboard for any authenticated user."""

    def get(self, request):
        if not request.user.is_authenticated:
            messages.info(request, "sign in to open your profile.")
            return redirect("auth:login")

        profile = StaffProfile.objects.filter(auth=request.user).first()
        bookmark_qs = Bookmark.objects.filter(user=request.user).select_related("blog").order_by("-created_at")
        bookmark_page_number = _resolve_page_number(request.GET.get("page"), default=1)
        bookmark_paginator = Paginator(bookmark_qs, 5)
        if bookmark_page_number > bookmark_paginator.num_pages and bookmark_paginator.num_pages:
            raise Http404("Page not found.")
        bookmark_page = bookmark_paginator.get_page(bookmark_page_number)

        recent_bookmarks = bookmark_page.object_list
        reading_history_qs = Blog.objects.filter(non_anonymous_viewer=request.user).order_by("-date_created")
        history_page_number = _resolve_page_number(request.GET.get("history_page"), default=1)
        history_paginator = Paginator(reading_history_qs, 5)
        if history_page_number > history_paginator.num_pages and history_paginator.num_pages:
            raise Http404("Page not found.")
        history_page = history_paginator.get_page(history_page_number)

        comments_qs = Comment.objects.filter(author=request.user).select_related("blog").order_by("-id")
        comments_page_number = _resolve_page_number(request.GET.get("comments_page"), default=1)
        comments_paginator = Paginator(comments_qs, 5)
        if comments_page_number > comments_paginator.num_pages and comments_paginator.num_pages:
            raise Http404("Page not found.")
        comments_page = comments_paginator.get_page(comments_page_number)

        published_qs = Blog.objects.filter(author=request.user).order_by("-date_created")
        stories_page_number = _resolve_page_number(request.GET.get("stories_page"), default=1)
        stories_paginator = Paginator(published_qs, 5)
        if stories_page_number > stories_paginator.num_pages and stories_paginator.num_pages:
            raise Http404("Page not found.")
        stories_page = stories_paginator.get_page(stories_page_number)

        following_page, following_paginator, following_items = _following_page(
            request.user, "", _resolve_page_number(request.GET.get("following_page"), default=1)
        )
        followers_page = followers_paginator = None
        followers_items = []
        if staff_only(request.user):
            followers_page, followers_paginator, followers_items = _followers_page(
                request.user, _resolve_page_number(request.GET.get("followers_page"), default=1)
            )

        #   ADMIN AUTHORITY PANEL: the staff directory, mass email, active
        #   sessions, site socials, speciality search and analytics all moved
        #   to ADMIN.views.PanelView / templates/ADMIN/panel.html, reachable
        #   from the "PANEL" link above instead of living on this page.
        # if profile:
        #     agg = FollowRelationship.objects.filter(Q(followee_id=profile.id) | Q(follower_id=profile.id))
        #     agg = agg.aggregate(followers=Count("id", filter=Q(followee_id=profile.id)),following=Count("id", filter=Q(follower_id=profile.id)),) if profile else {"followers": 0, "following": 0}
        #     follower_count = agg['followers']
        #     following_count = agg['following']
        # else:
        #     follower_count = 0
        #     following_count = 0
        #   Own-role select: only admins and superusers get the choices in
        #   context, so non-admin pages pay nothing for it.
        is_admin = admin_only(request.user)

        context = {
            "profile": profile,
            "user": request.user,
            "recent_bookmarks": recent_bookmarks,
            "bookmark_page_obj": bookmark_page,
            "bookmark_page_range": list(bookmark_paginator.get_elided_page_range(bookmark_page.number, on_each_side=1, on_ends=1)),
            "reading_history": history_page.object_list,
            "history_page_obj": history_page,
            "history_page_range": list(history_paginator.get_elided_page_range(history_page.number, on_each_side=1, on_ends=1)),
            "recent_comments": comments_page.object_list,
            "comments_page_obj": comments_page,
            "comments_page_range": list(comments_paginator.get_elided_page_range(comments_page.number, on_each_side=1, on_ends=1)),
            "published_stories": stories_page.object_list,
            "stories_page_obj": stories_page,
            "stories_page_range": list(stories_paginator.get_elided_page_range(stories_page.number, on_each_side=1, on_ends=1)),

            "following_items": following_items,
            "following_page_obj": following_page,
            "following_page_range": list(following_paginator.get_elided_page_range(following_page.number, on_each_side=1, on_ends=1)),
            "followers_items": followers_items,
            "followers_page_obj": followers_page,
            "followers_page_range": list(followers_paginator.get_elided_page_range(followers_page.number, on_each_side=1, on_ends=1)) if followers_paginator else [],

            "is_staff_user": staff_only(request.user),
            "is_admin_user": is_admin,
            "show_staff_dashboard": staff_only(request.user),
            "user_sessions": _user_sessions_for_profile(request.user, request),
            "gender_choices": GENDER_CHOICES,
            "role_choices": StaffConfig.role_choices() if is_admin else [],
            "protected_roles": sorted(StaffConfig.PROTECTED_ROLES) if is_admin else [],
            'staff_profile': get_cache('session-count') or 0,
            "speciality_csv": ", ".join(profile.speciality) if profile and isinstance(profile.speciality, list) else "",
        }
        return render(request, "HOME/profile.html", context)


DELETE_PLACARD_STEPS = 4  #   THREE "ARE YOU SURE" CONFIRMS + THE FINAL STEP


class ProfileDeletePlacardView(View):
    """Serve the delete-account placard fragments for the htmx overlay.

    The placard is fetched lazily: nothing about it ships with the profile
    page until the Delete account button is pressed. Step 1 to 3 are the
    "are you sure" confirms, step 4 lists everything the deletion destroys
    and carries the type-your-email-to-finalize form.
    """

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in first."}, status=401)
        #   THE ONE ACCOUNT THAT CAN NEVER DELETE ITSELF FROM THE UI
        if request.user.is_superuser:
            return JsonResponse({"detail": "The superuser account cannot be deleted from here."}, status=403)

        try:
            step = _resolve_page_number(request.GET.get("step"), default=1)
        except BadRequest:
            step = 1
        if step < 1 or step > DELETE_PLACARD_STEPS:
            step = 1

        context = {
            "step": step,
            "total_steps": DELETE_PLACARD_STEPS,
            "steps_remaining": DELETE_PLACARD_STEPS - step,
            "placard_endpoint": reverse("home:profile_delete_placard"),
            "delete_endpoint": reverse("home:profile_delete_account"),
            "account_email": request.user.email,
        }

        #   THE CONSEQUENCES LIST IS ONLY COMPUTED FOR THE FINAL STEP
        if step == DELETE_PLACARD_STEPS:
            profile = StaffProfile.objects.filter(auth=request.user).first()
            context.update(
                {
                    "stories_count": Blog.objects.filter(author=request.user).count(),
                    "comments_count": Comment.objects.filter(author=request.user).count(),
                    "bookmarks_count": Bookmark.objects.filter(user=request.user).count(),
                    "has_staff_profile": profile is not None,
                    "is_staff_user": staff_only(request.user),
                }
            )

        return render(request, "HOME/partials/delete_account_placard.html", context)


class ProfileDeleteAccountView(View):
    """Delete the signed in account entirely, staff or member.

    The placard asked "are you sure" three times and made the user type
    their email to finalize; this endpoint re-checks that email against the
    signed in account before anything is deleted. Deletion cascades through
    every table the account touches (stories, comments, bookmarks, staff
    profile, follow relationships, reset keys), every session is dropped,
    all active admins get a batch email alert, and the visitor lands on
    the home page with a django message.
    """

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in first."}, status=401)
        if request.user.is_superuser:
            return JsonResponse({"detail": "The superuser account cannot be deleted from here."}, status=403)

        remaining_time, is_limited = is_rate_limited(request, 30, 3)
        if is_limited:
            return render(
                request,
                "HOME/partials/delete_account_placard.html",
                self._final_context(request, error=f"Too frequent requests. Try again in {remaining_time} seconds."),
                status=429,
            )

        typed_email = (request.POST.get("email") or "").strip()
        if not typed_email:
            return render(
                request,
                "HOME/partials/delete_account_placard.html",
                self._final_context(request, error="Enter your email address to finalize."),
                status=400,
            )
        if typed_email.upper() != request.user.email.upper():
            return render(
                request,
                "HOME/partials/delete_account_placard.html",
                self._final_context(request, error="That email does not match this account."),
                status=400,
            )

        account = request.user
        deleted_email = account.email
        if account.is_admin:
            deleted_account_type = "Admin"
        elif staff_only(account):
            deleted_account_type = "Staff"
        else:
            deleted_account_type = "Member"

        #   THE STAFF PROFILE DIES WITH THE ACCOUNT, SO THE FULL NAME HAS TO BE READ FIRST
        deleted_full_name = ""
        if staff_only(account):
            deleted_profile = StaffProfile.objects.filter(auth=account).only("full_name").first()
            deleted_full_name = deleted_profile.full_name.strip() if deleted_profile else ""
        deleted_at = timezone.now()

        dropped = drop_sessions_for(account)
        with transaction.atomic():
            account.delete()

        #   EVERY ACTIVE ADMIN GETS THE BATCH MAIL (ACCOUNT TYPE, EMAIL, STAFF FULL NAME, DATETIME)
        _try_send_account_deleted_batch_email(deleted_email, deleted_account_type, deleted_full_name, deleted_at)
        info_logger(
            msg=f"ACCOUNT DELETED: {deleted_email} ({deleted_account_type}) deleted their own account, {dropped} session(s) ended"
        )

        #   logout AFTER the deletion: it flushes the request session, then
        #   the message is stored on the fresh session the redirect reads.
        auth_logout(request)
        messages.success(request, "Account successfully deleted")
        home_url = reverse("home:home")

        #   htmx callers get HX-Redirect so the browser does a full navigation
        #   (the toast with the django message renders on the home page); a
        #   non htmx post falls back to the classic redirect.
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse(status=204)
            response["HX-Redirect"] = home_url
            return response
        return redirect(home_url)

    def _final_context(self, request, error=None):
        profile = StaffProfile.objects.filter(auth=request.user).first()
        context = {
            "step": DELETE_PLACARD_STEPS,
            "total_steps": DELETE_PLACARD_STEPS,
            "placard_endpoint": reverse("home:profile_delete_placard"),
            "delete_endpoint": reverse("home:profile_delete_account"),
            "account_email": request.user.email,
            "stories_count": Blog.objects.filter(author=request.user).count(),
            "comments_count": Comment.objects.filter(author=request.user).count(),
            "bookmarks_count": Bookmark.objects.filter(user=request.user).count(),
            "has_staff_profile": profile is not None,
            "is_staff_user": staff_only(request.user),
            "error": error,
        }
        return context

#   EVERY `type` THE FOOTER UNSUBSCRIBE LINK OF AN EMAIL CAN CARRY (see the
#   unsubscribe_query values in SERVICE_INTERNAL/email_single.py and
#   email_batch.py). Anything not listed here is refused, so the query string
#   can never be used to switch off a setting that was not meant to be reachable.
UNSUBSCRIBE_KINDS = {
    "author_post": {
        "label": "new story alert emails",
        "detail": "the emails telling you when a new story is published",
    },
    "login_alert": {
        "label": "login alert emails",
        "detail": "the emails telling you when your account is signed in to",
    },
    "story_views_alert": {
        "label": "story views alert emails",
        "detail": "the emails telling you when one of your stories reaches a new views milestone",
    },
    "new_follower_alert": {
        "label": "new follower alert emails",
        "detail": "the emails telling you when someone starts following you",
    },
}


def _switch_off_email_setting(kind, email):
    """Turn the matching email preference OFF for the account with this email.
    It only ever switches things off, never on, and says nothing about whether
    the account exists (the caller shows the same result either way)."""
    user_model = get_user_model()
    if kind == "author_post":
        user_model.objects.filter(email__iexact=email).update(send_newsletter=False)
    elif kind == "login_alert":
        user_model.objects.filter(email__iexact=email).update(receive_email_login_alert=False)
    elif kind == "story_views_alert":
        StaffProfile.objects.filter(auth__email__iexact=email).update(get_blog_notification=False)
    elif kind == "new_follower_alert":
        StaffProfile.objects.filter(auth__email__iexact=email).update(get_follower_notification=False)



class UnsubscribeView(View):
    """Landing page for the Unsubscribe link in the footer of our emails
    (/unsubscribe/?type=...&email=...).

    GET only shows what is about to be switched off and asks for a click, so
    an email scanner or link previewer that opens the link can not unsubscribe
    anybody. The POST from that button does the switch (CSRF protected, rate
    limited per IP). A link with no or unknown details gets a plain
    explanation and a way to manage emails from the profile instead."""

    EMAIL_MAX_LENGTH = 254

    def _clean(self, source):
        kind = (source.get("type") or "").strip()
        email = (source.get("email") or "").strip()
        valid = kind in UNSUBSCRIBE_KINDS and "@" in email and len(email) <= self.EMAIL_MAX_LENGTH
        return kind, email, valid

    def _page(self, request, state, kind="", email="", status=200):
        spec = UNSUBSCRIBE_KINDS.get(kind, {})
        context = {
            "state": state,
            "kind": kind,
            "email": email,
            "masked_email": _mask_email(email) if email else "",
            "label": spec.get("label", ""),
            "detail": spec.get("detail", ""),
        }
        return render(request, "HOME/unsubscribe.html", context, status=status)

    def get(self, request):
        kind, email, valid = self._clean(request.GET)
        if not valid:
            return self._page(request, "invalid")
        return self._page(request, "confirm", kind, email)

    def post(self, request):
        remaining_time, is_limited = is_rate_limited(request, 60, 10, scope="unsubscribe")
        if is_limited:
            return self._page(request, "limited", status=429)

        kind, email, valid = self._clean(request.POST)
        if not valid:
            return self._page(request, "invalid", status=400)

        _switch_off_email_setting(kind, email)
        info_logger(msg=f"UNSUBSCRIBE: {kind} emails switched off for {_mask_email(email)}")
        return self._page(request, "done", kind, email)

MOST_VIEWED_COUNT = 3

class MostViewedView(View):
    """JSON for the home page's "Most viewed" rail (see
    HOME/static/home/js/most-viewed.js)."""

    def get(self, request):
        posts = cache_or_run("most-viewed-popular-stories", lambda: Blog.objects.select_related("author__staffprofile").order_by("-views", "-date_created")[:MOST_VIEWED_COUNT], timeout=30)
        
        results = [
            {
                "heading": post.heading,
                "url": reverse("blog:story_detail", args=[post.slug]),
                "image": post.image_1 or "",
                "views": post.views,
                "category": post.get_category_display(),
            }
            for post in posts
        ]
        return JsonResponse({"results": results}, status=200)