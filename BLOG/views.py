import html
import hashlib
import hmac
import logging
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, linebreaks
from django.utils.text import slugify
from django.views import View

from ADMIN.models import SiteSettings
from AUTHENTICATION.models import Auth
from ARCHIVE.models import ArchiveImage
from SERVICE_INTERNAL.abstract import _optimization, cache_or_run, error_logger, get_cache, get_client_ip, info_logger, is_bot_request, is_rate_limited, set_cache
from SERVICE_INTERNAL.email_single import (
    _build_email_html,
    _dispatch_email,
    _try_send_comment_like_email,
    _try_send_new_comment_email,
    _try_send_story_like_email,
    _try_send_story_views_alert_email,
)
from STAFF.models import AuthorFollow, StaffProfile
from .models import Blog, BlogLike, Comment, StoryView

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>'\"]+")

#   OUTBOUND REFERRAL TAGGING
#   An author only ever has to paste a plain link. Before that link is drawn
#   as an anchor it is stamped with our referral parameters so every site we
#   send a reader to can see the traffic came from us: utm_source is our
#   domain (the "primary tag" -- abureport.com.ng), utm_medium is "referral"
#   and utm_campaign names the story that sent the click. This is done at
#   RENDER time (never on save), so it is always current, needs no data
#   migration, and every already-published story gets it too -- the stored
#   content is never rewritten.
#
#   Only links that leave the site are tagged. Our own domain, mailto:/tel:
#   and #anchors are left exactly as written. A link the author already
#   tagged by hand (it carries a utm_source) is respected and left alone, so
#   a deliberately chosen campaign is never overwritten.
REFERRAL_SOURCE = "abureport.com.ng"
REFERRAL_MEDIUM = "referral"


def _is_internal_host(host):
    """True when `host` is our own site (abureport.com.ng or any subdomain,
    plus localhost while developing), so a link that stays on the site is
    never handed our own referral parameters."""
    host = (host or "").split(":", 1)[0].lower()
    if not host:
        return True
    if host in ("localhost", "127.0.0.1"):
        return True
    bare = REFERRAL_SOURCE.lower()
    return host == bare or host.endswith(f".{bare}")


def tag_outbound_url(url, campaign=""):
    """Return `url` with our referral parameters appended, or `url` unchanged
    when it should not be tagged (not http/https, our own domain, already
    carries a utm_source). Existing query parameters and the #fragment are
    preserved; a fragment keeps its place at the very end."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.scheme not in ("http", "https") or _is_internal_host(parsed.netloc):
        return url

    query = parse_qs(parsed.query, keep_blank_values=True)
    if "utm_source" in query:
        return url

    query["utm_source"] = [REFERRAL_SOURCE]
    query["utm_medium"] = [REFERRAL_MEDIUM]
    if campaign:
        query["utm_campaign"] = [campaign]
    new_query = urlencode(query, doseq=True)

    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


#   MARKDOWN-STYLE LINK: "[label](https://url)". Lets the author show a short
#   word while the anchor still points at a long address, so a raw link never
#   has to stretch across the page. It is matched in the SAME pass as the
#   bare-URL form below (see _LINK_OR_URL_RE) so the URL inside the brackets
#   is never linkified a second time.
MARKDOWN_LINK_RE = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s)]+)\)")
#   One alternation, tried left to right: a markdown link wins over the bare
#   URL it contains because the whole "[words](url)" is consumed in one match.
#   Group 1 = the label, group 2 = its URL; group 3 is a bare URL on its own.
_LINK_OR_URL_RE = re.compile(
    r"\[([^\[\]]+)\]\((https?://[^\s)]+)\)|(https?://[^\s<>'\"]+)"
)

#   INLINE IMAGE TOKEN: "imgl URL alt text" / "imgr URL alt text" (floated,
#   text wraps around it) / "imgc URL alt text" (centered, blocking -- the
#   surrounding text does NOT wrap it, still kept smaller than the
#   top-level/hero image). Must be checked before headings/bold/italic so
#   the URL + alt text are never consumed by those markers (see
#   DOCS/NEWS_CONTENT_CONVENTION.MD).
IMG_TOKEN_RE = re.compile(r"^(imgl|imgr|imgc)\s+(\S+)(?:\s+(.*))?$")

#   Which floated/blocking CSS class each keyword above puts on the <figure>
#   that wraps the picture and its caption -- see _render_inline_image below.
IMG_FIG_CLASSES = {
    "imgl": "story-inline-fig-left",
    "imgr": "story-inline-fig-right",
    "imgc": "story-inline-fig-center",
}

#   INLINE VIDEO TOKEN: "vidl URL caption" / "vidr URL caption" (floated,
#   text wraps around it) / "vidc URL caption" (centered, blocking -- the
#   surrounding text does NOT wrap it). Same shape as the image token above
#   but renders a self-playing <video> whose only control is a play/pause
#   button (see _render_inline_video below). Must be checked with the image
#   token, before headings/bold/italic, so the URL + caption are never
#   consumed by those markers (see DOCS/NEWS_CONTENT_CONVENTION.MD).
VID_TOKEN_RE = re.compile(r"^(vidl|vidr|vidc)\s+(\S+)(?:\s+(.*))?$")

#   Which floated/blocking CSS class each video keyword puts on the <figure>
#   wrapper. The float/centre behaviour is shared with the image figures --
#   see _render_inline_video below.
VID_FIG_CLASSES = {
    "vidl": "story-inline-fig-left",
    "vidr": "story-inline-fig-right",
    "vidc": "story-inline-fig-center",
}

#   EXTERNAL VIDEO PROVIDERS. A vidl/vidr/vidc line normally points at a
#   direct video FILE (an /archive/ upload, or any .mp4/.webm/.ogg/.mov/.m4v
#   address), which a plain <video> plays. A YouTube or Vimeo address is a
#   PAGE, not a file: "https://www.youtube.com/watch?v=..." is an HTML
#   document, so a <video> can never load it -- the browser fires `error` and
#   the old 404 fallback clip played in its place. Those addresses are
#   recognised here and rendered as an <iframe> embed with the provider's own
#   player instead. Anything unrecognised keeps the plain <video> path.
YOUTUBE_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?[^\s#]*?v=|embed/|shorts/|live/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)
VIMEO_ID_RE = re.compile(r"vimeo\.com/(?:video/)?(\d+)")


def _video_embed_url(url):
    """The <iframe> src for a recognised provider page (YouTube or Vimeo), or
    None when `url` is not one -- e.g. a direct video file, which the caller
    plays in a plain <video>.

    The embed autoplays muted and loops, matching the direct-file <video>
    (browsers only allow autoplay while muted). The provider draws its own
    controls for an embed, so the custom play/pause and sound overlay is not
    used here (see _render_inline_video)."""
    value = url or ""
    youtube = YOUTUBE_ID_RE.search(value)
    if youtube:
        video_id = youtube.group(1)
        params = [
            "rel=0",
            "playsinline=1",
            "modestbranding=1",
            "autoplay=1",
            "mute=1",
            "loop=1",                      #   loop=1 needs playlist=<id> too
            f"playlist={video_id}",
        ]
        start = re.search(r"[?&](?:t|start)=(\d+)", value)
        if start:
            params.append(f"start={start.group(1)}")
        return f"https://www.youtube.com/embed/{video_id}?" + "&".join(params)
    vimeo = VIMEO_ID_RE.search(value)
    if vimeo:
        return (
            f"https://player.vimeo.com/video/{vimeo.group(1)}"
            "?autoplay=1&muted=1&loop=1&playsinline=1&dnt=1"
        )
    return None

#   INLINE FILE ATTACHMENT TOKEN: "filel URL display text". Same shape as
#   the image token above (keyword, URL, optional trailing text) but
#   renders as a downloadable link in the normal flow of the paragraph
#   instead of a floated picture -- see _render_inline_file below.
FILE_TOKEN_RE = re.compile(r"^filel\s+(\S+)(?:\s+(.*))?$")

#   BUTTON BLOCK TOKEN: "btn URL label text". A whole line that starts with
#   `btn` becomes one button-style link. The URL is the destination and the
#   trailing text is the label printed on the button -- the block-level
#   companion to the inline "[words](url)" link above. See
#   DOCS/NEWS_CONTENT_CONVENTION.MD.
BTN_TOKEN_RE = re.compile(r"^btn\s+(\S+)(?:\s+(.*))?$")

STORY_404_CONTENT = (
    "This page does not exist. We may not have enough stories published yet, "
    "or the story you are looking for was deleted by the publisher and is no "
    "longer in existence.".upper()
)


def _linkify_text(value, campaign=""):
    """Turn markdown links ([words](url)) and bare URLs into anchor tags
    while preserving normal text. A markdown link lets the writer show a
    short word instead of a long raw URL; the bare-URL form stays for links
    simply pasted into the text. Both are matched in one pass so a URL that
    already sits inside "[words](...)" is never linkified a second time.

    Every link that leaves the site is stamped with our referral parameters
    (see tag_outbound_url); `campaign` is the story slug that sent the
    click. A link back to our own site, or one already tagged by hand, is
    left as written."""
    safe_text = html.escape(value, quote=False)
    safe_text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe_text)
    safe_text = re.sub(r"__(.+?)__", r"<em>\1</em>", safe_text)

    def _anchor(match):
        label, url = match.group(1), match.group(2)
        if url is None:                       #   bare-URL branch (group 3)
            url = label = match.group(3)
        #   `safe_text` is already HTML-escaped, so a "&" in the author's URL
        #   is sitting here as "&amp;". Undo that before parsing so the
        #   tagging step sees the real query string, then escape the result
        #   for the attribute. Without this a second "&" would come back out
        #   as "&amp%3B" and break the link.
        tagged = html.escape(tag_outbound_url(html.unescape(url), campaign), quote=True)
        return f'<a href="{tagged}" rel="noopener noreferrer" target="_blank">{label}</a>'

    return _LINK_OR_URL_RE.sub(_anchor, safe_text)


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
    """Build the inline <figure> for an imgl/imgr/imgc token. Always smaller
    than the top-level hero image. imgl/imgr float left/right so
    surrounding text wraps it; imgc is centered and blocking -- it sits on
    its own line and nothing wraps around it, it is just kept smaller than
    the hero image the same way imgl/imgr are.

    Caption: when the author typed alt text after the URL, it is shown
    beneath the picture in a <figcaption>, the same way the headline image
    description shows under the banner. When no alt text was typed the file
    name is still used for the `alt` attribute (accessibility), but it is
    never printed as a caption.

    Width/height: if `url` is a picture from /archive/, its real, stored
    size (see _archive_dimensions_for_url above) is rendered straight onto
    the <img width height> attributes -- the browser reserves the right
    box before the picture even starts downloading, so there is no layout
    shift and no need to wait for the file to load. Any other URL (one
    pasted from outside the project, where no size is known ahead of time)
    still gets a size: a tiny inline `onload` sets width/height from the
    image's own natural size once it has actually loaded, which is the
    only way to know it without one. Either way the CSS on `.story-inline-fig`
    (max-width) and `.story-inline-img` (max-height) is what actually caps
    the on-page size -- these attributes are about reserving space and
    giving the browser real numbers to shrink from, not about overriding
    that cap."""
    caption = (alt_text or "").strip()
    alt = caption or _image_filename_from_url(url)
    fig_class = IMG_FIG_CLASSES.get(direction, "story-inline-fig-left")
    safe_url = html.escape(url, quote=True)
    safe_alt = html.escape(alt, quote=True)

    width, height = _archive_dimensions_for_url(url)
    if width and height:
        size_attrs = f' width="{width}" height="{height}"'
        onload_attr = ""
    else:
        size_attrs = ""
        onload_attr = ' onload="if(!this.getAttribute(\'width\')){this.width=this.naturalWidth;this.height=this.naturalHeight;}"'

    caption_html = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
    return (
        f'<figure class="story-inline-fig {fig_class}">'
        f'<img class="story-inline-img" src="{safe_url}" alt="{safe_alt}"'
        f'{size_attrs} loading="lazy"{onload_attr}>'
        f"{caption_html}</figure>"
    )


def _render_inline_file(url, display_text, campaign=""):
    """Build the inline downloadable link for a "filel URL text" token. This
    sits in the normal flow of the paragraph (unlike imgl/imgr, it is never
    floated -- a file has no picture to wrap text around), but clicking it
    downloads the file instead of navigating the reader away from the
    story. The `download` attribute only actually forces a download for a
    same-origin URL in most browsers, which is exactly what the
    `cloudinary_proxy` template filter is for (see
    ARCHIVE.templatetags.archive_extras) -- any file uploaded through this
    project and served back through /archive/cdn/... downloads correctly;
    an arbitrary external URL still gets a normal link, and (like every
    other outbound link) is stamped with our referral parameters."""
    label = (display_text or "").strip() or _image_filename_from_url(url)
    safe_url = html.escape(tag_outbound_url(url, campaign), quote=True)
    safe_label = html.escape(label, quote=True)
    return (
        f'<a class="story-inline-file" href="{safe_url}" download rel="noopener noreferrer">'
        f'<span class="story-inline-file-icon" aria-hidden="true"><svg xmlns="http://w3.org" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" x2="12" y1="15" y2="3" /></svg></span>{safe_label}</a>'
    )


def _render_inline_button(url, label_text, campaign=""):
    """Build the block-level button for a "btn URL label" token.

    Unlike `filel`, this is not a download: it is a normal link the reader
    taps, styled to stand out as a call to action. The URL is the
    destination and the trailing text is the label printed on the button.
    When no label was typed the URL itself is printed so the button is never
    blank. It sits on its own line (a <p> wrapper), so it never floats and
    surrounding text never wraps around it. As with every other outbound
    link it carries our referral parameters."""
    label = (label_text or "").strip() or url
    safe_url = html.escape(tag_outbound_url(url, campaign), quote=True)
    safe_label = html.escape(label, quote=False)
    return (
        f'<p class="story-inline-btn-row">'
        f'<a class="story-inline-btn" href="{safe_url}" rel="noopener noreferrer" target="_blank">{safe_label}</a>'
        f'</p>'
    )


def _render_inline_video(direction, url, caption_text):
    """Build the inline <figure> for a vidl/vidr/vidc token.

    Placement is identical to the image token: vidl/vidr float left/right so
    surrounding text wraps around the video, vidc is centered and blocking.
    The <video> autoplays muted on a loop -- browsers only allow a video to
    autoplay while it is muted -- and carries NO native control bar. Two
    controls are drawn on top of the video: the play/pause button
    (`data-video-toggle`) and a sound button (`data-video-sound`). Sound is
    off by default, and the reader can only hear a video while it is on
    screen (HOME/static/home/js/interactions.js enforces the in-view rule).
    Both buttons are wired in that same script.

    Caption: the trailing text is shown beneath the video in a <figcaption>,
    exactly like the image token. With no trailing text no caption is drawn
    (the accessible name falls back to a plain "Story video" label).

    A YouTube or Vimeo address (see _video_embed_url) is a page, not a file,
    so it is rendered in an <iframe> with the provider's own player instead:
    the figure carries `is-embed` and no overlay buttons are drawn. Every
    other URL keeps the self-playing <video> below."""
    caption = (caption_text or "").strip()
    fig_class = VID_FIG_CLASSES.get(direction, "story-inline-fig-left")
    safe_aria = html.escape(caption or "Story video", quote=True)
    caption_html = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""

    embed_url = _video_embed_url(url)
    if embed_url:
        safe_embed = html.escape(embed_url, quote=True)
        return (
            f'<figure class="story-inline-fig story-inline-video is-embed {fig_class}">'
            f'<div class="story-inline-video-frame">'
            f'<iframe class="story-inline-video-embed" src="{safe_embed}" '
            f'title="{safe_aria}" loading="lazy" '
            f'allow="autoplay; encrypted-media; picture-in-picture; fullscreen" '
            f'allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>'
            f'</div>'
            f"{caption_html}</figure>"
        )

    safe_url = html.escape(url, quote=True)
    return (
        f'<figure class="story-inline-fig story-inline-video {fig_class}">'
        f'<div class="story-inline-video-frame">'
        f'<video class="story-inline-video-el" src="{safe_url}" muted loop playsinline '
        f'autoplay preload="metadata" aria-label="{safe_aria}" '
        f'onerror="this.onerror=null;this.src=\'/static/404_video.mp4\';"></video>'
        f'<button type="button" class="story-inline-video-toggle" data-video-toggle '
        f'aria-label="Pause video">'
        f'<svg class="story-inline-video-icon story-inline-video-icon-pause" width="16" height="16" '
        f'viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        f'<rect x="6" y="5" width="4" height="14" rx="1"></rect>'
        f'<rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>'
        f'<svg class="story-inline-video-icon story-inline-video-icon-play" width="16" height="16" '
        f'viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        f'<path d="M8 5v14l11-7z"></path></svg>'
        f'</button>'
        f'<button type="button" class="story-inline-video-toggle story-inline-video-sound" '
        f'data-video-sound aria-label="Unmute video">'
        f'<svg class="story-inline-video-icon story-inline-video-icon-sound-on" width="16" height="16" '
        f'viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        f'<path d="M11 5L6 9H3v6h3l5 4V5z"></path>'
        f'<path d="M15.5 8.5a5 5 0 0 1 0 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        f'<path d="M18.5 5.5a9 9 0 0 1 0 13" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path></svg>'
        f'<svg class="story-inline-video-icon story-inline-video-icon-sound-off" width="16" height="16" '
        f'viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
        f'<path d="M11 5L6 9H3v6h3l5 4V5z"></path>'
        f'<line x1="16" y1="9" x2="22" y2="15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></line>'
        f'<line x1="22" y1="9" x2="16" y2="15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></line></svg>'
        f'</button></div>'
        f"{caption_html}</figure>"
    )


def parse_story_content(content, campaign=""):
    """Render story text into a readable article structure with SEO-friendly blocks.

    `campaign` is the story slug; every outbound link the parser draws is
    stamped with our referral parameters naming that story (see
    tag_outbound_url). It defaults to "" so the news editor's JavaScript
    preview -- and every test -- can call the parser without a story."""
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
            blocks.append(_render_inline_file(url, display_text, campaign))
            i += 1
            continue

        vid_match = VID_TOKEN_RE.match(line)
        if vid_match:
            direction, url, caption_text = vid_match.groups()
            blocks.append(_render_inline_video(direction, url, caption_text))
            i += 1
            continue

        btn_match = BTN_TOKEN_RE.match(line)
        if btn_match:
            url, label_text = btn_match.groups()
            blocks.append(_render_inline_button(url, label_text, campaign))
            i += 1
            continue

        heading_match = re.match(r"^(#+)\s*(.*)$", line)
        if heading_match:
            heading_level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            if heading_text:
                tag_level = min(heading_level + 1, 4)
                blocks.append(f'<h{tag_level}>{_linkify_text(heading_text, campaign)}</h{tag_level}>')
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
            blocks.append('<ul>' + ''.join(f'<li>{_linkify_text(item, campaign)}</li>' for item in items if item) + '</ul>')
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
            blocks.append('<ol>' + ''.join(f'<li>{_linkify_text(item, campaign)}</li>' for item in items if item) + '</ol>')
            continue

        paragraph_lines = []
        while i < len(lines):
            current = lines[i].strip()
            if not current:
                break
            if re.match(r"^(#+\s+|\*\s+|\d+\.\s+|imgl\s+|imgr\s+|imgc\s+|vidl\s+|vidr\s+|vidc\s+|filel\s+|btn\s+)", current):
                break
            paragraph_lines.append(current)
            i += 1
            if i < len(lines) and not lines[i].strip():
                break

        paragraph = ' '.join(paragraph_lines).strip()
        if paragraph:
            blocks.append(f'<p>{_linkify_text(paragraph, campaign)}</p>')

    return '\n'.join(blocks)


#   STORY TABLE OF CONTENTS
#   parse_story_content above returns the whole story body as one HTML
#   string. A long story is far easier to skim when every heading is a jump
#   target, so enhance_story_body runs over that HTML and (a) gives each
#   heading a stable, unique `id` and (b) inserts a "TABLE OF CONTENT"
#   section right after the first paragraph. Only #-style headings exist
#   (DOCS/NEWS_CONTENT_CONVENTION.MD) and parse_story_content maps them to
#   h2/h3/h4, so the heading pattern below never has to think about h1/h5.
#   This runs on the parsed HTML in the VIEW only, so parse_story_content's
#   exact output -- which the news editor's JavaScript preview mirrors word
#   for word -- is never touched.
#
#   THE AUTHOR DECIDES. Blog.toc_mode (a dropdown on the add/edit editor) is
#   what turns this on and picks how much of the list is open on arrival:
#   Off returns the parser's output untouched (byte-for-byte, so nothing is
#   imposed on a reader who never asked for a list); the three on-levels are
#   "title only", "top sections" and "fully open". See Blog.TOC_* in
#   BLOG.models. The list itself is a nested tree of the #/##/### headings,
#   so a "top sections" reader sees just the # rows with a chevron beside
#   each one that has children.
_STORY_HEADING_RE = re.compile(r"<h([2-4])>(.*?)</h\1>", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TOC_CHEVRON = (
    '<svg class="story-toc-chevron" viewBox="0 0 16 16" width="18" height="18" '
    'aria-hidden="true" focusable="false"><path d="M4 6.5 8 10.5 12 6.5" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)


def _toc_slug(text, seen):
    """A unique, URL-safe id for one heading. slugify drops the markdown
    noise (a heading can hold a link or bold text), and a repeated heading --
    or two different headings that slugify the same way -- gets a -2/-3
    suffix so no id collides and every anchor lands on the right section. A
    heading of only punctuation or emoji falls back to "part". Every id is
    prefixed with "section-": that keeps a heading whose text happens to
    slugify to one of the page's own ids (e.g. "story-heading",
    "main-content", "comments-title") from hijacking that element and
    sending the jump link to the wrong place."""
    base = slugify(text) or "part"
    candidate = f"section-{base}"
    suffix = 2
    while candidate in seen:
        candidate = f"section-{base}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _toc_tree(headings):
    """Turn the flat [(level, slug, text), ...] list into a nested tree so the
    table of contents can show the #/##/### hierarchy. A heading nests under
    the nearest previous heading of a lower level; a jump straight from # to
    ### (a skipped level) simply nests the ### under that #. Each node is
    {"level", "slug", "text", "children"}."""
    roots = []
    stack = []
    for level, slug, text in headings:
        node = {"level": level, "slug": slug, "text": text, "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        (stack[-1]["children"] if stack else roots).append(node)
        stack.append(node)
    return roots


def _render_toc_nodes(nodes, branches_open):
    """One <li> per node. A node with children gets a chevron dropdown button
    that reveals its nested <ol>; the "fully open" level starts every branch
    open, the other on-levels start them closed. A leaf is just its link."""
    items = []
    for node in nodes:
        link = (
            f'<a class="story-toc-link" href="#{node["slug"]}">'
            f'{escape(node["text"])}</a>'
        )
        if node["children"]:
            expanded = "true" if branches_open else "false"
            hidden = "" if branches_open else " hidden"
            items.append(
                f'<li class="story-toc-item story-toc-item--has-children" data-level="{node["level"]}">'
                '<div class="story-toc-row">'
                f"{link}"
                '<button type="button" class="story-toc-branch" '
                f'aria-expanded="{expanded}" aria-label="Toggle subsections">'
                f"{_TOC_CHEVRON}</button>"
                "</div>"
                f'<ol class="story-toc-children"{hidden}>'
                f'{_render_toc_nodes(node["children"], branches_open)}</ol>'
                "</li>"
            )
        else:
            items.append(
                f'<li class="story-toc-item" data-level="{node["level"]}">'
                f'<div class="story-toc-row">{link}</div>'
                "</li>"
            )
    return "".join(items)


def _story_toc_html(headings, toc_mode):
    """The <nav> block itself. The outer <details> starts open for levels 2
    and 3 and closed for level 1 ("title only"), and the branch buttons start
    open only for level 3. That is the whole difference between the three
    collapse levels: the same tree, three different starting states. The
    "TABLE OF CONTENT" label is always visible in the summary row, so even a
    level-1 reader sees the section exists."""
    branches_open = toc_mode == Blog.TOC_FULL
    shell_open = " open" if toc_mode in (Blog.TOC_TOP_LEVEL, Blog.TOC_FULL) else ""
    rows = _render_toc_nodes(_toc_tree(headings), branches_open)
    return (
        '<nav class="story-toc" aria-label="Table of contents" '
        f'data-story-toc data-toc-mode="{toc_mode}">'
        f'<details class="story-toc-shell"{shell_open}>'
        '<summary class="story-toc-head">'
        '<span class="story-toc-title">TABLE OF CONTENT</span>'
        f"{_TOC_CHEVRON}"
        "</summary>"
        f'<ol class="story-toc-list">{rows}</ol>'
        "</details></nav>"
    )


def enhance_story_body(html_body, toc_mode=0):
    """When the author chose a table of contents for a story (Blog.toc_mode
    other than "Off"), give every heading in the parsed body a stable `id`
    and splice the "TABLE OF CONTENT" section in right after the first
    paragraph. With the mode off -- the default, and every story written
    before this existed -- the parsed body is returned untouched. Called only
    by StoryDetailView, never by parse_story_content, so the parser stays
    byte-for-byte identical for the editor preview and its tests."""
    if not html_body or not toc_mode:
        return html_body

    headings = []
    seen_slugs = set()

    def _tag_heading(match):
        level = int(match.group(1))
        inner = match.group(2)
        #   The plain, tag-free heading text is what the link shows and what
        #   the id is built from -- a heading holding <a>/<strong> must not
        #   leak its markup into either.
        plain = html.unescape(_HTML_TAG_RE.sub("", inner)).strip()
        slug = _toc_slug(plain, seen_slugs)
        headings.append((level, slug, plain))
        return f'<h{level} id="{slug}">{inner}</h{level}>'

    with_ids = _STORY_HEADING_RE.sub(_tag_heading, html_body)

    #   No headings means there is nothing to list; the body (with no ids
    #   added) is returned as the parser made it.
    if not headings:
        return with_ids

    #   Blocks are newline-joined (see parse_story_content), so walk them and
    #   drop the TOC just after the first real paragraph -- one that starts
    #   with a bare "<p>". The button row ("<p class=...>") deliberately does
    #   not match: it is not prose, so the TOC should not be pushed below it.
    #   A body that opens with a picture, video, list or heading and has no
    #   paragraph at all still gets the TOC, at the very top.
    blocks = with_ids.split("\n")
    insert_at = 0
    for index, block in enumerate(blocks):
        if block.startswith("<p>"):
            insert_at = index + 1
            break
    blocks.insert(insert_at, _story_toc_html(headings, toc_mode))
    return "\n".join(blocks)


TICKER_MARKER_RE = re.compile(r"^(#{1,6}\s*|\*\s+|\d+\.\s+)")


def _clean_content_block(block):
    """Plain-text rendering of one content block (one paragraph/heading/list
    chunk, i.e. the text between blank lines): strips this project's
    markdown-style markers (#, *, __, **) and replaces an inline
    imgl/imgr/imgc token with its alt text, a vidl/vidr/vidc token with its
    caption, a filel token with its link text and a btn token with its button
    label, so nothing but readable prose survives. A markdown link
    ([words](url)) keeps its words and drops the address. Shared by
    build_ticker_text (the whole story, for the reading marquee) and the
    og/meta excerpt built in StoryDetailView.get (just the story's first
    block) -- neither should ever leak a raw
    imgl/imgr/imgc/vidl/vidr/vidc/filel/btn token, a [words](url) address, or
    a leftover #/*/**/__ marker, into what a reader (or a search engine's
    snippet/the page's own <head> tags) sees."""
    lines = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        btn_match = BTN_TOKEN_RE.match(line)
        if btn_match:
            btn_url, btn_label = btn_match.groups()
            line = (btn_label or "").strip() or btn_url
        else:
            img_match = IMG_TOKEN_RE.match(line)
            if img_match:
                _, img_url, img_alt = img_match.groups()
                line = (img_alt or "").strip() or _image_filename_from_url(img_url)
            else:
                vid_match = VID_TOKEN_RE.match(line)
                if vid_match:
                    _, vid_url, vid_caption = vid_match.groups()
                    line = (vid_caption or "").strip() or _image_filename_from_url(vid_url)
                else:
                    file_match = FILE_TOKEN_RE.match(line)
                    if file_match:
                        file_url, file_text = file_match.groups()
                        line = (file_text or "").strip() or _image_filename_from_url(file_url)
                    else:
                        line = TICKER_MARKER_RE.sub("", line)
                        line = MARKDOWN_LINK_RE.sub(r"\1", line)
                        line = line.replace("**", "").replace("__", "")
        if line:
            lines.append(line)
    return " ".join(lines).strip()


def _build_meta_description(content, max_len=160):
    """A non-empty description for the story page's meta/OG/Twitter tags and
    its JSON-LD `description` (see StoryDetailView.get).

    The opening paragraph is preferred, but a one-line opener ("The match
    ended 2-0.") makes a poor snippet, so the following plain-text blocks are
    appended until there is enough to read. Blocks that clean down to nothing
    (a lone imgl/btn token, a bare heading marker) are skipped, so the tag is
    never empty when the story has any prose at all. Trimmed on a word
    boundary so it never ends mid-word."""
    if not content:
        return ""
    blocks = [block for block in re.split(r"\n\s*\n", content.strip()) if block.strip()]
    parts, length = [], 0
    for block in blocks:
        text = _clean_content_block(block)
        if not text:
            continue
        parts.append(text)
        length += len(text) + 1
        if length >= max_len:
            break
    description = " ".join(parts).strip()
    if len(description) > max_len:
        description = description[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return description


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
        #   THE BLOG RAISE ERRROR IF THERE IS NO BLOG
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

        #   `blog` can arrive from a 100s Redis cache, so a row pickled just
        #   before this field shipped would not carry `toc_mode`. getattr keeps
        #   that first request from 500-ing; the cache self-heals in 100s.
        blog_content = enhance_story_body(parse_story_content(blog.content, blog.slug), getattr(blog, "toc_mode", 0))
        ticker_text = build_ticker_text(blog.content)

        comments = blog.comments.select_related("author__staffprofile").order_by("id")
        
        
        try:
            author_profile = blog.author.staffprofile or ""
        except StaffProfile.DoesNotExist as e:
            info_logger(msg=f"MISSING STAFFPROFILE: story for {blog.author.email} was found with no staff profile")
            author_profile = StaffProfile()
            #   The page renders normally, but with a real 404 status so search
            #   engines never index a story whose author has no profile.
            return render(request, 'blog/staffprofile_404.html', {'blog': blog}, status=404)
            
        author_tags = []
        if author_profile and isinstance(author_profile.speciality, list):
            author_tags = [str(tag).strip() for tag in author_profile.speciality if str(tag).strip()]

        #   The author's latest stories for the sidebar rail, newest first, the
        #   story being read excluded and the list capped at three.
        author_latest_stories = (
            Blog.objects.filter(author=blog.author)
            .exclude(pk=blog.pk)
            .order_by("-date_created", "-pk")[:3]
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
            remote_addr = get_client_ip(request).strip() or "unknown"
            address_hash = hmac.new(
                settings.SECRET_KEY.encode("utf-8"),
                remote_addr.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            view_dedupe_key = f"story-view:{blog.pk}:{address_hash}"
            if cache.add(view_dedupe_key, "1", timeout=10):
                Blog.objects.filter(pk=blog.pk).update(views=F("views") + 1)
                blog.refresh_from_db(fields=["views"])

                #   TIMESTAMPED HISTORY behind Blog.views, so ANALYTICS can
                #   chart views per period instead of just the running total.
                #   Written in the SAME dedupe branch as the counter bump, so
                #   the two can never disagree. The inner atomic() is a
                #   savepoint: if the write fails -- the table is not migrated
                #   yet, say -- only the savepoint rolls back, the story page
                #   still renders and the request is never 500'd.
                try:
                    with transaction.atomic():
                        StoryView.objects.create(
                            blog=blog,
                            user=request.user if request.user.is_authenticated else None,
                        )
                except Exception as exc:
                    error_logger(msg=f"STORY VIEW LOG FAILED: blog={blog.pk} error={exc}")

                alert_interval = getattr(settings, "STORY_VIEWS_ALERT_INTERVAL", 10)
                if author_profile.get_blog_notification and blog.views > 0 and blog.views % alert_interval == 0:
                    _try_send_story_views_alert_email(blog.author, blog)

        if request.user.is_authenticated:
            # THROUGH LET ME ACCESS THE BG MODEL THAT DJANGO CREATE FOR M2M
            already = Blog.non_anonymous_viewer.through.objects.filter(
                blog=blog, auth=request.user
            ).exists()
            if not already:
                Blog.non_anonymous_viewer.through.objects.create(blog=blog, auth=request.user)

            #   TIMESTAMPED READ: the M2M above predates this and carries no
            #   time, so it can only ever be ordered by the story's publish
            #   date. The "Continue reading" popup needs the true "last read"
            #   order, so every open bumps one row here too. Imported locally
            #   to keep BLOG from importing HOME at module load.
            from HOME.models import ReadingHistory

            ReadingHistory.objects.update_or_create(
                user=request.user, blog=blog, defaults={"read_at": timezone.now()}
            )

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
        #   DESCRIPTION for the <head> meta/OG/Twitter tags and the story's
        #   JSON-LD node. Built from the opening paragraph and, when that is
        #   too thin to read (or cleans down to nothing, e.g. a lone image
        #   token), the blocks that follow -- so the tag is never an empty
        #   string or a one-word snippet. _clean_content_block also drops any
        #   imgl/imgr/imgc/filel token down to just its alt/link text, so one
        #   never leaks into the <head> (see StoryDetailView.get context).
        og_descr = _build_meta_description(blog.content) or (blog.heading or "")

        #   STRUCTURED DATA: the story's NewsArticle, with its `author` built as
        #   a full Person node from the shared schema builder. The Person's @id
        #   is keyed on the author's portfolio slug, so this byline and the
        #   author's portfolio page resolve to ONE entity (E-E-A-T) instead of
        #   two unrelated nodes, and `worksFor` attaches it to the publisher.
        #   The image is the same same-origin cdn URL the page renders, resolved
        #   against the canonical domain (never the request host).
        from ARCHIVE.templatetags.archive_extras import cloudinary_proxy
        from SERVICE_INTERNAL.config import About, StaffConfig
        from SERVICE_INTERNAL.schema import dumps, news_article_node, person_node
        from STAFF.views import _portfolio_socials

        author_schema = person_node(
            name=blog.author_name,
            slug=author_profile.slug or "",
            url=f"{About.domain}{author_portfolio_url}" if author_portfolio_url else "",
            image=blog.author.profile_img or "",
            description=(author_profile.bio or "").strip()[:300],
            job_title=StaffConfig.role_label(author_profile.role) if author_profile.role else "",
            same_as=[social["url"] for social in _portfolio_socials(author_profile, blog.author_name)],
            knows_about=author_tags,
        )
        article_image = ""
        if blog.image_1:
            proxied = cloudinary_proxy(blog.image_1)
            article_image = f"{About.domain}{proxied}" if str(proxied).startswith("/") else str(proxied)
        article_schema_json = dumps(
            {
                "@context": "https://schema.org",
                **news_article_node(
                    headline=blog.heading,
                    url=f"{About.domain}{request.path}",
                    description=og_descr,
                    author=author_schema,
                    image=article_image,
                    date_published=blog.date_created.isoformat() if blog.date_created else "",
                    date_modified=(
                        (blog.last_updated or blog.date_created).isoformat() if blog.date_created else ""
                    ),
                    section=blog.get_category_display(),
                    word_count=blog.word_count,
                ),
            }
        )

        context = {
            "blog": blog,
            'excerp': og_descr,
            "article_schema_json": article_schema_json,
            "blog_content_html": blog_content,
            "ticker_text": ticker_text,
            "comments": comments,
            "author_profile": author_profile,
            "author_tags": author_tags,
            "author_latest_stories": author_latest_stories,
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

        #   CONTINUE READING ON A STORY PAGE: signed in readers only, so the
        #   bookmarked reader gets the "keep on reading" sheet here too. The
        #   story they are on is excluded -- it was just written to their
        #   ReadingHistory above, and offering it back would be odd. Imported
        #   locally to keep BLOG from importing HOME at module load.
        if request.user.is_authenticated:
            from HOME.views import (
                CONTINUE_COOLDOWN_STORY_MS,
                _continue_popup_context,
            )

            context.update(
                _continue_popup_context(
                    request.user,
                    exclude_ids=[blog.id],
                    scope="story",
                    cooldown_ms=CONTINUE_COOLDOWN_STORY_MS,
                )
            )
            context["continue_popup_enabled"] = True

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


def _actor_label(user):
    """How a liker/commenter is named in an alert email: their staff full name
    when they have one, otherwise a masked email so a reader's address is
    never handed out in full."""
    profile = StaffProfile.objects.filter(auth=user).only("full_name").first()
    if profile and profile.full_name and profile.full_name.strip():
        return profile.full_name.strip()
    local, _, domain = (user.email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "A reader"


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

        new_like = False
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
                liked, detail, new_like = True, "Thank You", True

            if had_legacy_like:
                request.session["liked_blogs"] = [
                    liked_id for liked_id in legacy_likes if liked_id != blog.id
                ]
                request.session.modified = True

        likes = Blog.objects.values_list("likes", flat=True).get(pk=blog.pk)

        #   Tell the author, unless the like is their own or they switched
        #   like alerts off. The fresh count is stitched on so the email is
        #   never one behind.
        if new_like and blog.author_id != user.id and getattr(blog.author, "receive_like_alert", False):
            blog.likes = likes
            _try_send_story_like_email(blog.author, blog, _actor_label(user))

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
        remaining_time, limited = is_rate_limited(
            request,
            timeout_window=5,
            max_requests=3,
            scope="comment",
        )
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

        #   Tell the story's author, unless the comment is their own or they
        #   switched comment alerts off (StaffProfile.get_comment_notification).
        if blog.author_id and comment.author_id != blog.author_id:
            author_profile = (
                StaffProfile.objects.filter(auth=blog.author)
                .only("get_comment_notification")
                .first()
            )
            if author_profile is not None and author_profile.get_comment_notification:
                _try_send_new_comment_email(blog.author, blog, comment, _actor_label(user))

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
    """Toggle a comment like. On a new like the comment's author is emailed
    (unless it is their own comment or they switched like alerts off)."""

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

        #   Tell the comment's author, unless it is their own comment or they
        #   switched like alerts off (Auth.receive_like_alert).
        if liked and comment.author_id != user.id and getattr(comment.author, "receive_like_alert", False):
            comment.likes = likes
            _try_send_comment_like_email(comment.author, comment.blog, comment, _actor_label(user))

        return JsonResponse({"detail": detail, "likes": likes, "liked": liked}, status=200)