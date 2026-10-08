import html
import hashlib
import hmac
import logging
import re
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape, linebreaks
from django.views import View

from ADMIN.models import SiteSettings
from AUTHENTICATION.models import Auth
from ARCHIVE.models import ArchiveImage
from SERVICE_INTERNAL.abstract import _optimization, cache_or_run, get_cache, get_client_ip, info_logger, is_bot_request, is_rate_limited, set_cache
from SERVICE_INTERNAL.email_single import _build_email_html, _dispatch_email, _try_send_story_views_alert_email
from STAFF.models import AuthorFollow, StaffProfile
from .models import Blog, BlogLike, Comment

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>'\"]+")

#   INLINE IMAGE TOKEN: "imgl URL alt text" / "imgr URL alt text" (floated,
#   text wraps around it) / "imgc URL alt text" (centered, blocking -- the
#   surrounding text does NOT wrap it, still kept smaller than the
#   top-level/hero image). Must be checked before headings/bold/italic so
#   the URL + alt text are never consumed by those markers (see
#   DOCS/NEWS_CONTENT_CONVENTION.MD).
IMG_TOKEN_RE = re.compile(r"^(imgl|imgr|imgc)\s+(\S+)(?:\s+(.*))?$")

#   Which floated/blocking CSS class each keyword above renders with -- see
#   _render_inline_image below.
IMG_SIDE_CLASSES = {
    "imgl": "story-inline-img-left",
    "imgr": "story-inline-img-right",
    "imgc": "story-inline-img-center",
}

#   INLINE FILE ATTACHMENT TOKEN: "filel URL display text". Same shape as
#   the image token above (keyword, URL, optional trailing text) but
#   renders as a downloadable link in the normal flow of the paragraph
#   instead of a floated picture -- see _render_inline_file below.
FILE_TOKEN_RE = re.compile(r"^filel\s+(\S+)(?:\s+(.*))?$")

STORY_404_CONTENT = (
    "This page does not exist. We may not have enough stories published yet, "
    "or the story you are looking for was deleted by the publisher and is no "
    "longer in existence.".upper()
)


def _linkify_text(value):
    """Turn URL-like tokens into anchor tags while preserving normal text."""
    safe_text = html.escape(value, quote=False)
    safe_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe_text)
    safe_text = re.sub(r"__(.+?)__", r"<em>\1</em>", safe_text)
    safe_text = URL_RE.sub(lambda match: f'<a href="{match.group(0)}" rel="noopener noreferrer" target="_blank">{match.group(0)}</a>', safe_text)
    return safe_text


def _image_filename_from_url(url):
    """Fallback alt text when a writer omits it: the filename from the URL."""
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return name or url


def _archive_dimensions_for_url(url):
    """(width, height) for `url` if it is a picture that was uploaded
    through /archive/ (see ARCHIVE.views.ArchiveUploadView, which now
    requires and stores the real Cloudinary-confirmed size on every
    ArchiveImage row) -- (None, None) for any other URL, e.g. one pasted
    from outside the project."""
    dimensions = ArchiveImage.objects.filter(url=url).values("width", "height").first()
    if not dimensions:
        parsed_path = urlparse(url).path
        if "/cdn/" in parsed_path:
            parsed_path = parsed_path.split("/cdn/", 1)[1]
        elif parsed_path.startswith("/"):
            parsed_path = parsed_path.lstrip("/")
        if parsed_path:
            dimensions = ArchiveImage.objects.filter(url__endswith=parsed_path).values("width", "height").first()
    if not dimensions:
        return None, None
    return dimensions["width"], dimensions["height"]


def _render_inline_image(direction, url, alt_text):
    """Build the inline <img> for an imgl/imgr/imgc token. Always smaller
    than the top-level hero image. imgl/imgr float left/right so
    surrounding text wraps it; imgc is centered and blocking -- it sits on
    its own line and nothing wraps around it, it is just kept smaller than
    the hero image the same way imgl/imgr are.

    Width/height: if `url` is a picture from /archive/, its real, stored
    size (see _archive_dimensions_for_url above) is rendered straight onto
    the <img width height> attributes -- the browser reserves the right
    box before the picture even starts downloading, so there is no layout
    shift and no need to wait for the file to load. Any other URL (one
    pasted from outside the project, where no size is known ahead of time)
    still gets a size: a tiny inline `onload` sets width/height from the
    image's own natural size once it has actually loaded, which is the
    only way to know it without one. Either way the CSS on `.story-inline-img`
    (max-width/max-height) is what actually caps the on-page size -- these
    attributes are about reserving space and giving the browser real
    numbers to shrink from, not about overriding that cap."""
    alt = (alt_text or "").strip() or _image_filename_from_url(url)
    side_class = IMG_SIDE_CLASSES.get(direction, "story-inline-img-left")
    safe_url = html.escape(url, quote=True)
    safe_alt = html.escape(alt, quote=True)

    width, height = _archive_dimensions_for_url(url)
    if width and height:
        size_attrs = f' width="{width}" height="{height}"'
        onload_attr = ""
    else:
        size_attrs = ""
        onload_attr = ' onload="if(!this.getAttribute(\'width\')){this.width=this.naturalWidth;this.height=this.naturalHeight;}"'

    return (
        f'<img class="story-inline-img {side_class}" src="{safe_url}" alt="{safe_alt}"'
        f'{size_attrs} loading="lazy"{onload_attr}>'
    )


def _render_inline_file(url, display_text):
    """Build the inline downloadable link for a "filel URL text" token. This
    sits in the normal flow of the paragraph (unlike imgl/imgr, it is never
    floated -- a file has no picture to wrap text around), but clicking it
    downloads the file instead of navigating the reader away from the
    story. The `download` attribute only actually forces a download for a
    same-origin URL in most browsers, which is exactly what the
    `cloudinary_proxy` template filter is for (see
    ARCHIVE.templatetags.archive_extras) -- any file uploaded through this
    project and served back through /archive/cdn/... downloads correctly;
    an arbitrary external URL still gets a normal link."""
    label = (display_text or "").strip() or _image_filename_from_url(url)
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label, quote=True)
    return (
        f'<a class="story-inline-file" href="{safe_url}" download rel="noopener noreferrer">'
        f'<span class="story-inline-file-icon" aria-hidden="true"><svg xmlns="http://w3.org" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></svg></span>{safe_label}</a>'
    )


def parse_story_content(content):
    """Render story text into a readable article structure with SEO-friendly blocks."""
    if not content:
        return ""

    lines = [line.rstrip() for line in content.strip().splitlines()]
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        img_match = IMG_TOKEN_RE.match(line)
        if img_match:
            direction, url, alt_text = img_match.groups()
            blocks.append(_render_inline_image(direction, url, alt_text))
            i += 1
            continue

        file_match = FILE_TOKEN_RE.match(line)
        if file_match:
            url, display_text = file_match.groups()
            blocks.append(_render_inline_file(url, display_text))
            i += 1
            continue

        heading_match = re.match(r"^(#+)\s*(.*)$", line)
        if heading_match:
            heading_level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if heading_text:
                tag_level = min(heading_level + 1, 4)
                blocks.append(f'<h{tag_level}>{_linkify_text(heading_text)}</h{tag_level}>')
            i += 1
            continue

        if re.match(r"^\*\s+", line):
            items = []
            while i < len(lines):
                current = lines[i].strip()
                if not current or not re.match(r"^\*\s+", current):
                    break
                items.append(current[2:].strip())
                i += 1
            blocks.append('<ul>' + ''.join(f'<li>{_linkify_text(item)}</li>' for item in items if item) + '</ul>')
            continue

        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines):
                current = lines[i].strip()
                if not current or not re.match(r"^\d+\.\s+", current):
                    break
                match = re.match(r"^\d+\.\s+(.*)$", current)
                if match:
                    items.append(match.group(1).strip())
                i += 1
            blocks.append('<ol>' + ''.join(f'<li>{_linkify_text(item)}</li>' for item in items if item) + '</ol>')
            continue

        paragraph_lines = []
        while i < len(lines):
            current = lines[i].strip()
            if not current:
                break
            if re.match(r"^(#+\s+|\*\s+|\d+\.\s+|imgl\s+|imgr\s+|imgc\s+|filel\s+)", current):
                break
            paragraph_lines.append(current)
            i += 1
            if i < len(lines) and not lines[i].strip():
                break

        paragraph = ' '.join(paragraph_lines).strip()
        if paragraph:
            blocks.append(f'<p>{_linkify_text(paragraph)}</p>')

    return '\n'.join(blocks)


TICKER_MARKER_RE = re.compile(r"^(#{1,6}\s*|\*\s+|\d+\.\s+)")


def _clean_content_block(block):
    """Plain-text rendering of one content block (one paragraph/heading/list
    chunk, i.e. the text between blank lines): strips this project's
    markdown-style markers (#, *, __, **) and replaces an inline
    imgl/imgr/imgc token with its alt text and a filel token with its link
    text, so nothing but readable prose survives. Shared by build_ticker_text
    (the whole story, for the reading marquee) and the og/meta excerpt built
    in StoryDetailView.get (just the story's first block) -- neither should
    ever leak a raw imgl/imgr/imgc/filel token, or a leftover #/*/**/__
    marker, into what a reader (or a search engine's snippet/the page's own
    <head> tags) sees."""
    lines = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        img_match = IMG_TOKEN_RE.match(line)
        if img_match:
            _, img_url, img_alt = img_match.groups()
            line = (img_alt or "").strip() or _image_filename_from_url(img_url)
        else:
            file_match = FILE_TOKEN_RE.match(line)
            if file_match:
                file_url, file_text = file_match.groups()
                line = (file_text or "").strip() or _image_filename_from_url(file_url)
            else:
                line = TICKER_MARKER_RE.sub("", line)
                line = line.replace("**", "").replace("__", "")
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def build_ticker_text(content):
    """Plain-text feed for the reading marquee at the top of the story page.
    Cleans every paragraph/block with _clean_content_block above and joins
    them with ' * ' so the whole story can be read in one continuous pass
    while it scrolls."""
    if not content:
        return ""

    blocks = [block for block in re.split(r"\n\s*\n", content.strip()) if block.strip()]
    cleaned_blocks = [text for block in blocks if (text := _clean_content_block(block))]

    return " ** ".join(cleaned_blocks)

class StoryHome(View):
    """Redirect to the latest story. This is not meant to exist as a page
    itself, but it is useful for SEO purposes to have a /blog/ URL that
    points to the latest story instead of a bare numeric ID."""
    def get(self, request):
        latest_story = Blog.objects.order_by("-date_created").first()
        if latest_story:
            return redirect("blog:story_detail", blog_slug=latest_story.slug)
        return render(request, "blog/story_404.html", {"blog_id": "latest", "decoy_content": STORY_404_CONTENT, "suggested_stories": _suggested_stories()}, status=404)
def _suggested_stories():
    """Latest stories for the "you might be interested in" block of the story 404 page."""
    from HOME.views import latest_stories_for_404  #   LOCAL IMPORT: HOME.views already imports BLOG.models

    return latest_stories_for_404()


class StoryDetailView(View):
    def get(self, request, blog_slug):
        blog = cache_or_run(f"blog-{blog_slug}", lambda: Blog.objects.filter(slug=blog_slug).select_related("author__staffprofile").first(), timeout=100)
        if blog is None:
            return render(
                request,"blog/story_404.html",{"blog_id": blog_slug, "decoy_content": STORY_404_CONTENT, "suggested_stories": _suggested_stories()},status=404,)
            
        #   A STORY STAFF HAVE EDITED SINCE PUBLISHING TELLS THE READER SO, EVERY
        #   TIME IT IS OPENED. `last_edited` is only ever set by
        #   HOME.views.EditNewsView, so null means "never edited" and nothing is
        #   shown. The "story-edited" tag is what interactions.js keys off to
        #   show this one as a notice at the TOP of the page instead of the
        #   usual bottom toast.
        if blog.last_edited:
            messages.info(
                request,
                f"Last updated {blog.edited_gap_label} after its initial publication.",
                extra_tags="story-edited",
            )

        #   THE STORY ROW ABOVE COMES FROM A 100s CACHE, SO ITS `likes` CAN BE
        #   STALE. Other readers may have liked/unliked meanwhile, so the
        #   counter is always re-read from the database before rendering.
        blog.refresh_from_db(fields=["likes", "views"])
        is_liked = (
            request.user.is_authenticated
            and BlogLike.objects.filter(blog=blog, user=request.user).exists()
        )

        blog_content = parse_story_content(blog.content)
        ticker_text = build_ticker_text(blog.content)

        comments = blog.comments.select_related("author__staffprofile").order_by("id")
        
        
        try:
            author_profile = blog.author.staffprofile or ""
        except StaffProfile.DoesNotExist as e:
            info_logger(msg=f"MISSING STAFFPROFILE: story for {blog.author.email} was found with no staff profile")
            author_profile = StaffProfile()
            return render(request, 'blog/staffprofile_404.html', {'blog': blog})
            
        author_tags = []
        if author_profile and isinstance(author_profile.speciality, list):
            author_tags = [str(tag).strip() for tag in author_profile.speciality if str(tag).strip()]

        author_most_viewed_stories = (
            Blog.objects.filter(author=blog.author)
            .exclude(pk=blog.pk)
            .order_by("-views", "-date_created", "-pk")[:3]
        )


        #   Only a confirmed non-bot, non-HTMX page visit moves the counter.
        #   A short per-story/per-IP cache key makes accidental reloads
        #   idempotent without storing the address in the cache key.
        if is_bot_request(request):
            info_logger(
                msg=(
                    f"BOT VIEW (no +1) on '{blog.slug}': ip={get_client_ip(request)} "
                    f"ua={request.META.get('HTTP_USER_AGENT', '')[:200]!r}"
                )
            )
        elif request.headers.get("HX-Request", "").lower() != "true":
            remote_addr = request.META.get("REMOTE_ADDR", "").strip() or "unknown"
            address_hash = hmac.new(
                settings.SECRET_KEY.encode("utf-8"),
                remote_addr.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            view_dedupe_key = f"story-view:{blog.pk}:{address_hash}"
            if cache.add(view_dedupe_key, "1", timeout=5):
                Blog.objects.filter(pk=blog.pk).update(views=F("views") + 1)
                blog.refresh_from_db(fields=["views"])

                alert_interval = getattr(settings, "STORY_VIEWS_ALERT_INTERVAL", 5)
                if author_profile.get_blog_notification and blog.views > 0 and blog.views % alert_interval == 0:
                    _try_send_story_views_alert_email(blog.author, blog)

        if request.user.is_authenticated:
            # THROUGH LET ME ACCESS THE BG MODEL THAT DJANGO CREATE FOR M2M
            already = Blog.non_anonymous_viewer.through.objects.filter(
                blog=blog, auth=request.user
            ).exists()
            if not already:
                Blog.non_anonymous_viewer.through.objects.create(blog=blog, auth=request.user)

        is_bookmarked = request.user.is_authenticated and blog.bookmarked_by.filter(user=request.user).exists()

        #   AUTHOR PORTFOLIO + FOLLOW: only staff level accounts own a
        #   portfolio, so the follow button and the profile links only appear
        #   when the author actually has a page to point at.
        author_has_portfolio = blog.author.is_active and (
            blog.author.is_staff or blog.author.is_admin or blog.author.is_superuser
        )
        author_portfolio_url = (
            reverse("staff:portfolio", args=[author_profile.slug])
            if author_has_portfolio and author_profile and author_profile.slug
            else ""
        )
        is_following_author = bool(
            author_has_portfolio
            and request.user.is_authenticated
            and AuthorFollow.objects.filter(follower=request.user, author=blog.author).exists()
        )
        author_follower_count = (
            AuthorFollow.objects.filter(author=blog.author).count() if author_has_portfolio else 0
        )
        #   FOR OG DESCRIPTION TO BE CLEAN AND CLEAR carrying the first paragrah 
        #   -- _clean_content_block also drops any imgl/imgr/imgc/filel token
        #   down to just its alt/link text, so one never leaks into the
        #   <head> meta/JSON-LD tags this feeds (see StoryDetailView.get context).
        og_descr_block = re.split(r'\n\s*\n', blog.content.strip(), maxsplit=1)[0]
        og_descr = _clean_content_block(og_descr_block)
        if len(og_descr) > 400: og_descr = og_descr[:400]
        context = {
            "blog": blog,
            'excerp': og_descr,
            "blog_content_html": blog_content,
            "ticker_text": ticker_text,
            "comments": comments,
            "author_profile": author_profile,
            "author_tags": author_tags,
            "author_most_viewed_stories": author_most_viewed_stories,
            "is_bookmarked": is_bookmarked,
            "is_liked": is_liked,
            "liked_comment_ids": request.session.get("liked_comments", []) if request.user.is_authenticated else [],
            "bookmark_count": blog.bookmarked_by.count(),
            "author_portfolio_url": author_portfolio_url,
            "follow_endpoint": (
                reverse("staff:author_follow", args=[blog.author_id]) if author_has_portfolio else ""
            ),
            "is_following_author": is_following_author,
            "author_follower_count": author_follower_count,
            "social_links": [
                ("Twitter", author_profile.twitter_handle if author_profile else "#"),
                ("Facebook", author_profile.facebook_handle if author_profile else "#"),
                ("WhatsApp", author_profile.whatsapp_handle if author_profile else "#"),
            ],
        }
        return render(request, "blog/story_detail.html", context)


class CategoryRecommendationsView(View):
    """Return the three newest stories in the current story's category."""

    def get(self, request, blog_slug):
        blog = get_object_or_404(Blog, slug=blog_slug)
        stories = (
            Blog.objects.filter(category=blog.category)
            .exclude(pk=blog.pk)
            .order_by("-date_created", "-pk")[:3]
        )
        recommendations = []
        for story in stories:
            first_block = re.split(r"\n\s*\n", story.content.strip(), maxsplit=1)[0]
            excerpt = " ".join(_clean_content_block(first_block).split())
            recommendations.append(
                {
                    "slug": story.slug,
                    "url": reverse("blog:story_detail", args=[story.slug]),
                    "heading": story.heading,
                    "image": story.image_1 or "",
                    "category": story.get_category_display(),
                    "date_created": story.date_created.isoformat(),
                    "excerpt": excerpt[:180],
                }
            )
        return JsonResponse({"stories": recommendations})


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _authenticated_user(request):
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return user

    user_id = request.session.get("_auth_user_id")
    if user_id:
        session_user = Auth.objects.filter(pk=user_id, is_active=True).first()
        if session_user:
            request.user = session_user
            return session_user
    return None


class BookmarkNotFoundView(View):
    """Bookmark endpoint for the decoy 404 story page. It must never succeed:
    there is no story to attach a Bookmark row to, so every attempt gets the
    same error and the page's optimistic UI reverts itself."""

    def post(self, request):
        return JsonResponse({"detail": "Cannot bookmark, report to developer."}, status=400)


class BlogLikeView(View):
    """Toggle a persistent user/story like and keep the displayed total current."""

    def post(self, request, blog_id):
        user = _authenticated_user(request)
        if not user:
            if _is_ajax(request):
                return JsonResponse({"detail": "Please sign in to like this story."}, status=401)
            return redirect("auth:login")

        with transaction.atomic():
            blog = get_object_or_404(Blog.objects.select_for_update(), pk=blog_id)
            existing_like = BlogLike.objects.filter(blog=blog, user=user).first()
            legacy_likes = request.session.get("liked_blogs", [])
            had_legacy_like = blog.id in legacy_likes

            if existing_like:
                existing_like.delete()
                Blog.objects.filter(pk=blog.pk, likes__gt=0).update(likes=F("likes") - 1)
                liked, detail = False, "Like removed."
            elif had_legacy_like:
                # Preserve the toggle behavior for sessions created before likes
                # were persisted; those existing counts already include this like.
                Blog.objects.filter(pk=blog.pk, likes__gt=0).update(likes=F("likes") - 1)
                liked, detail = False, "Like removed."
            else:
                BlogLike.objects.create(blog=blog, user=user)
                Blog.objects.filter(pk=blog.pk).update(likes=F("likes") + 1)
                liked, detail = True, "Thank You"

            if had_legacy_like:
                request.session["liked_blogs"] = [
                    liked_id for liked_id in legacy_likes if liked_id != blog.id
                ]
                request.session.modified = True

        likes = Blog.objects.values_list("likes", flat=True).get(pk=blog.pk)
        return JsonResponse({"detail": detail, "likes": likes, "liked": liked}, status=200)


class StoryReportView(View):
    """Email a reader's story report to the configured support address."""

    max_content_length = 5000

    def post(self, request, blog_id):
        blog = get_object_or_404(Blog, pk=blog_id)
        content = (request.POST.get("content") or "").strip()
        if not content:
            return self._failure(request, blog, "Please enter a report before sending.", 400)
        if len(content) > self.max_content_length:
            return self._failure(request, blog, "Reports must be 5,000 characters or fewer.", 400)

        remaining_time, limited = is_rate_limited(
            request,
            timeout_window=3600,
            max_requests=5,
            scope="story-report",
        )
        if limited:
            return self._failure(
                request,
                blog,
                f"Too many reports were sent. Please try again in {remaining_time} seconds.",
                429,
            )

        recipient = SiteSettings.get_solo().support_email.strip()
        if not recipient:
            logger.error("Could not send story report for blog %s: support email is not configured.", blog.pk)
            return self._failure(
                request,
                blog,
                "We could not send this report because the support email is not configured.",
                503,
            )

        user = _authenticated_user(request)
        reporter = user.email if user else "Anonymous"
        story_url = request.build_absolute_uri(
            reverse("blog:story_detail", kwargs={"blog_slug": blog.slug})
        )
        safe_heading = " ".join(blog.heading.splitlines())
        subject = f"Story report: {safe_heading}"
        body = (
            f"<p><strong>Reporter:</strong> {escape(reporter)}</p>"
            f"<p><strong>Story:</strong> {escape(blog.heading)}</p>"
            f'<p><strong>Story URL:</strong> <a href="{escape(story_url)}">{escape(story_url)}</a></p>'
            f"<h3>Report</h3>{linebreaks(escape(content), autoescape=False)}"
        )
        email_html = _build_email_html(
            title="Story report received",
            main_content=body,
            end_note="This report was sent by a reader using the story report form.",
        )
        sent = _dispatch_email(
            recipient,
            subject,
            email_html,
            no_async=True,
        )
        if not sent:
            logger.error("Email backend did not send story report for blog %s.", blog.pk)
            return self._failure(
                request,
                blog,
                "We could not send your report right now. Please try again later.",
                502,
            )

        detail = "Your report has been sent. Thank you for helping us improve this story."
        if _is_ajax(request):
            return JsonResponse({"detail": detail}, status=200)
        messages.success(request, detail)
        return redirect("blog:story_detail", blog_slug=blog.slug)

    def _failure(self, request, blog, detail, status):
        if _is_ajax(request):
            return JsonResponse({"detail": detail}, status=status)
        messages.error(request, detail)
        return redirect("blog:story_detail", blog_slug=blog.slug)


class CommentCreateView(View):
    def post(self, request, blog_id):
        remaining_time, limited = is_rate_limited(request, 5, 3, )
        if limited:
            return JsonResponse({'detail': f'too many request, wait {remaining_time} seconds and retry'}, status = 429)
        blog = get_object_or_404(Blog, pk=blog_id)
        user = _authenticated_user(request)
        if not user:
            if _is_ajax(request):
                return JsonResponse({"detail": "Please sign in to comment."}, status=401)
            return redirect("auth:login")

        content = (request.POST.get("comment", "") or "").strip()
        if not content or len(content) < 2:
            return JsonResponse({"detail": "Comment cannot be empty."}, status=400)

        if Comment.objects.filter(blog=blog, author=user).exists():
            return JsonResponse({"detail": "You can only post one comment per story."}, status=400)

        comment = Comment.objects.create(blog=blog, author=user, content=content)
        if _is_ajax(request):
            return JsonResponse({"detail": "Comment posted.", "comment_id": comment.id, "comment_count": blog.comments.count(), "content": comment.content}, status=201)
        return redirect("blog:story_detail", blog_slug=blog.slug)


class CommentDeleteView(View):
    def post(self, request, comment_id):
        comment = get_object_or_404(Comment, pk=comment_id)
        user = _authenticated_user(request)
        if not user:
            if _is_ajax(request):
                return JsonResponse({"detail": "Please sign in."}, status=401)
            return redirect("auth:login")

        if comment.author_id != user.id and not user.is_staff:
            return JsonResponse({"detail": "You can only delete your own comment."}, status=403)

        blog_id = comment.blog_id
        blog_slug = comment.blog.slug
        comment.delete()
        if _is_ajax(request):
            return JsonResponse({"detail": "Comment deleted.", "comment_count": Comment.objects.filter(blog_id=blog_id).count()}, status=200)
        return redirect("blog:story_detail", blog_slug=blog_slug)


class CommentLikeView(View):
    """TODO: send a notification to the poster of that comment that their comment have been like by the likee with time and which story and adiitional relevant details"""
    def post(self, request, comment_id):
        comment = get_object_or_404(Comment, pk=comment_id)
        user = _authenticated_user(request)
        if not user:
            if _is_ajax(request):
                return JsonResponse({"detail": "Please sign in to like this comment."}, status=401)
            return redirect("auth:login")

        liked_comments = request.session.get("liked_comments", [])
        if comment.id in liked_comments:
            #   UNLIKE. `likes__gt=0` keeps the PositiveIntegerField from going below 0.
            Comment.objects.filter(pk=comment.pk, likes__gt=0).update(likes=F("likes") - 1)
            liked_comments = [liked_id for liked_id in liked_comments if liked_id != comment.id]
            liked, detail = False, "Like removed."
        else:
            Comment.objects.filter(pk=comment.pk).update(likes=F("likes") + 1)
            liked_comments = list(dict.fromkeys([*liked_comments, comment.id]))
            liked, detail = True, "Comment liked."
        request.session["liked_comments"] = liked_comments
        request.session.modified = True

        #   READ THE REAL TOTAL BACK: other readers may have liked meanwhile.
        likes = Comment.objects.values_list("likes", flat=True).get(pk=comment.pk)
        return JsonResponse({"detail": detail, "likes": likes, "liked": liked}, status=200)