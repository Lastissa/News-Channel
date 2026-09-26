import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, logout as auth_logout
from django.contrib.sessions.models import Session
from django.core.exceptions import BadRequest, ValidationError
from django.core.paginator import Paginator
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Q, Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator
from django.views import View

from AUTHENTICATION.models import Auth, UserSession
from BLOG.models import Blog, CATEGORY, Comment
from HOME.models import Bookmark
from SERVICE_INTERNAL.abstract import (
    _optimization,
    _response,
    get_cache,
    info_logger,
    is_rate_limited,
    notify_admins_account_deleted,
)
from SERVICE_INTERNAL.config import About, StaffConfig
from SERVICE_INTERNAL.email_single import _try_send_newsletter_subscribe_email
from SERVICE_INTERNAL.images import ImageQuality, ImageUploadError, upload_news_image, upload_profile_image
from SERVICE_INTERNAL.indexnow import ping_indexnow
from SERVICE_INTERNAL.permissions import admin_only, staff_only
from SERVICE_INTERNAL.sessions import drop_sessions_for
from STAFF.models import GENDER_CHOICES, FollowRelationship, StaffProfile

logger = logging.getLogger(__name__)

PAGE_SIZE = 10  #   THE AMOUNT OF NEWs  TO FIRDT LOAD + THE PAGINATION AS WELL
FEATURED_COUNT = 5  #   FEATUREAD


def handler404(request, exception=None):
    """Site wide 404 page. Kept deliberately minimal but still framed by the
    regular header and footer."""
    return render(request, "HOME/404.html", status=404)

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
                    <p>This downtime is temporary as we are actively working on fixing some glitches with our database in order to best serve you more.</p>
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
                "Disallow: /auth/",
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
    
    

class HomeView(View):
    """Landing page: hero carousel of featured stories and paginated story grid."""

    def get(self, request):
        #q = the actual heading to filter
        #category = self explatory
        query = request.GET.get("q", "").strip()
        category = request.GET.get("category", "").strip().upper()
        page_number = _resolve_page_number(request.GET.get("page"), default=1)

        base_qs = Blog.objects.select_related("author__staffprofile").order_by("-date_created")

        if query:
            base_qs = base_qs.filter(heading__icontains=query)
        if category:
            base_qs = base_qs.filter(category=category)

        is_filtered = bool(query or category)

        featured = [] if is_filtered else list(base_qs[:FEATURED_COUNT])
        featured_ids = [post.id for post in featured]

        grid_qs = base_qs.exclude(id__in=featured_ids)
        paginator = Paginator(grid_qs, PAGE_SIZE)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        page = paginator.get_page(page_number)

        context = {
            "featured_posts": featured,
            "categories": CATEGORY,
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

        base_qs = Blog.objects.select_related("author").order_by("-date_created")
        if query:
            base_qs = base_qs.filter(heading__icontains=query)
        if category:
            base_qs = base_qs.filter(category=category)

        is_filtered = bool(query or category)
        featured_ids = [] if is_filtered else list(base_qs[:FEATURED_COUNT].values_list("id", flat=True))
        grid_qs = base_qs.exclude(id__in=featured_ids)

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
            return redirect("home:profile")
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
        if category not in {value for value, _ in CATEGORY}:
            return _response({"detail": "Select a valid category."}, status=400)
        if not content:
            return _response({"detail": "The story content cannot be empty."}, status=400)

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

        return _response(
            {"detail": "Story published.", "story_url": reverse("blog:story_detail", args=[blog.slug]), "id": blog.pk},
            status=201,
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
        return render(request, "HOME/promote.html")


class ProfileNewsletterToggleView(View):
    """Toggle newsletter delivery without a full page refresh."""

    def post(self, request):
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
                "detail": "News updates enabled." if new_state else "News updates disabled.",
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
    """Validate and save a new profile image, either a pasted URL (unchanged
    flow) or an uploaded file. An uploaded file always goes through
    SERVICE_INTERNAL.images.upload_profile_image, which applies a fixed,
    automatic optimization, i.e. the person never picks a quality here,
    that choice only exists for staff on the Add news page."""

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
        if image_file:
            #   RATE LIMIT BEFORE CLOUDINARY: the upload overwrites this user's one avatar asset in place, so a
            #   request that is going to be refused must never get as far as touching it.
            too_frequent = self._too_frequent(request)
            if too_frequent: return too_frequent
            try:
                image_url = upload_profile_image(image_file, request.user.pk)
            except ImageUploadError as exc:
                return JsonResponse({"detail": str(exc), "valid": False}, status=400)
        else:
            image_url = (request.POST.get("image_url") or "").strip()
            if not image_url:
                return JsonResponse({"detail": "Please add a valid image URL.", "valid": False}, status=400)

            validator = URLValidator(schemes=["http", "https"])
            try:
                validator(image_url)
            except ValidationError:
                return JsonResponse({"detail": "The URL must be a valid http or https link.", "valid": False}, status=400)

            #   RATE LIMIT THE ENDPOINT JUST BEFORE DATABASE UPLOAD
            too_frequent = self._too_frequent(request)
            if too_frequent: return too_frequent

        request.user.profile_img = image_url
        request.user.save(update_fields=["profile_img"])
        return JsonResponse({"detail": "Profile image updated.", "valid": True, "image_url": image_url}, status=200)


class ProfileBookmarksView(View):
    """Return a paginated bookmark payload for the profile page."""

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to view bookmarks."}, status=401)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        bookmarks_qs = Bookmark.objects.filter(user=request.user).select_related("blog").order_by("-created_at")
        paginator = Paginator(bookmarks_qs, 5)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")

        page = paginator.get_page(page_number)
        items = [
            {
                "id": bookmark.id,
                "blog_id": bookmark.blog_id,
                "heading": bookmark.blog.heading,
                "created_at": bookmark.created_at.isoformat(),
                "url": reverse("blog:story_detail", args=[bookmark.blog.slug]),
            }
            for bookmark in page.object_list
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


class ProfileHistoryView(View):
    """Return a paginated reading-history payload for the profile page."""

    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Please sign in to view history."}, status=401)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        history_qs = Blog.objects.filter(non_anonymous_viewer=request.user).order_by("-date_created")
        paginator = Paginator(history_qs, 5)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")

        page = paginator.get_page(page_number)
        items = [
            {
                "id": blog.id,
                "blog_id": blog.id,
                "heading": blog.heading,
                "date_created": blog.date_created.isoformat(),
                "url": reverse("blog:story_detail", args=[blog.slug]),
            }
            for blog in page.object_list
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
    """Return a paginated published-stories payload for the staff profile."""

    def get(self, request):
        if not staff_only(request.user):
            return JsonResponse({"detail": "Staff access is required to view published stories!. Refresh Page"}, status=401)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        published_qs = Blog.objects.filter(author=request.user).order_by("-date_created")
        paginator = Paginator(published_qs, 5)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")

        page = paginator.get_page(page_number)
        items = [
            {
                "id": blog.id,
                "blog_id": blog.id,
                "heading": blog.heading,
                "views": blog.views,
                "date_created": blog.date_created.isoformat(),
                "url": reverse("blog:story_detail", args=[blog.slug]),
            }
            for blog in page.object_list
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
            messages.info(request, "Please sign in to open your profile.")
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

        #   ADMIN AUTHORITY PANEL: the staff directory only loads for admins
        #   and superusers, deferred import keeps ADMIN.views free to import
        #   from HOME.views without a circular reference.
        staff_directory = []
        staff_directory_page_obj = None
        staff_directory_page_range = []
        if admin_only(request.user):
            from ADMIN.views import staff_directory_page, staff_directory_rows

            staff_page_number = _resolve_page_number(request.GET.get("staff_page"), default=1)
            staff_paginator, staff_page = staff_directory_page(staff_page_number)
            staff_directory = staff_directory_rows(list(staff_page.object_list))
            staff_directory_page_obj = staff_page
            staff_directory_page_range = list(
                staff_paginator.get_elided_page_range(staff_page.number, on_each_side=1, on_ends=1)
            )
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

            "is_staff_user": staff_only(request.user),
            "is_admin_user": is_admin,
            "show_staff_dashboard": staff_only(request.user),
            "user_sessions": _user_sessions_for_profile(request.user, request),
            "gender_choices": GENDER_CHOICES,
            "role_choices": StaffConfig.role_choices() if is_admin else [],
            "protected_roles": sorted(StaffConfig.PROTECTED_ROLES) if is_admin else [],
            'staff_profile': get_cache('session-count') or 0,
            "staff_directory": staff_directory,
            "staff_directory_page_obj": staff_directory_page_obj,
            "staff_directory_page_range": staff_directory_page_range,
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
    all admins get the dummy terminal email alert, and the visitor lands on
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

        dropped = drop_sessions_for(account)
        with transaction.atomic():
            account.delete()

        #   EVERY ADMIN GETS THE DUMMY TERMINAL ALERT
        notify_admins_account_deleted(deleted_email, deleted_account_type)
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

class UnsubscribeView(View):
    "TODO: Handle unsuscribe logic for when user want to stop receving email click"
    def get(self, request):
        return render(request, 'HOME/unsubscribe.html')