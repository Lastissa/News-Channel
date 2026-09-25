"""Public /archive/ gallery: anyone can browse, only a signed in user can
add a picture (see ArchiveUploadModalView / ArchiveUploadView below)."""

import requests
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views import View

from HOME.views import _resolve_page_number
from SERVICE_INTERNAL.abstract import error_logger, is_rate_limited
from SERVICE_INTERNAL.images import ImageQuality, ImageUploadError, upload_archive_image
from SERVICE_INTERNAL.permissions import is_authenticated

from ARCHIVE.models import ArchiveImage

PAGE_SIZE = 5  #   HOW MANY PICTURES LOAD AT ONCE, BOTH FIRST PAINT AND EVERY HTMX PAGE

MIN_DIMENSION = 50
MAX_DIMENSION = 4000

#   {"low": "Low", "medium": "Medium", "high": "High"} -- the human word
#   before the " - ..." blurb in ImageQuality.CHOICES.
QUALITY_LABELS = {value: label.split(" - ")[0] for value, label in ImageQuality.CHOICES}


def _masked_email(email):
    """"jo***@gmail.com" style masking: first 2 characters of the local
    part stay visible, the rest of the local part is blurred, the domain
    is left untouched so the picture can still be traced by a moderator
    without the full address being shown on the page."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    visible = local[:2]
    hidden_len = max(len(local) - 2, 3)
    return f"{visible}{'*' * hidden_len}@{domain}"


def _parse_dimension(raw_value):
    """None for an empty box (no resize requested), the int for a valid
    box, or "invalid" for anything out of range/not a number -- three
    outcomes the caller needs to tell apart, not just None/int."""
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return "invalid"
    if value < MIN_DIMENSION or value > MAX_DIMENSION:
        return "invalid"
    return value


def _serialize_images(images):
    return [
        {
            "id": image.id,
            "url": image.url,
            "width": image.width,
            "height": image.height,
            "alt": image.alt,
            "quality_label": QUALITY_LABELS.get(image.quality, image.quality.title()),
            "uploader_email": _masked_email(image.author.email),
            "date_created": image.date_created,
        }
        for image in images
    ]


def _paginate(page_number):
    qs = ArchiveImage.objects.select_related("author").order_by("-date_created")
    paginator = Paginator(qs, PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    page = paginator.get_page(page_number)
    return {
        "images": _serialize_images(page.object_list),
        "page": page.number,
        "num_pages": paginator.num_pages,
        "has_next": page.has_next(),
        "has_previous": page.has_previous(),
        "next_page": page.next_page_number() if page.has_next() else None,
        "previous_page": page.previous_page_number() if page.has_previous() else None,
        "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
    }


class ArchiveGalleryView(View):
    """GET: the full /archive/ page with the first PAGE_SIZE pictures.
    POST: the paginated picture grid only, for the htmx "see more" swap,
    based on whatever page the (still anonymous-allowed) viewer is on."""

    def get(self, request):
        context = _paginate(page_number=1)
        context["can_upload"] = is_authenticated(request.user)
        return render(request, "ARCHIVE/gallery.html", context)

    def post(self, request):
        page_number = _resolve_page_number(request.POST.get("page"), default=1)
        context = _paginate(page_number=page_number)
        return render(request, "ARCHIVE/partials/gallery_grid.html", context)


class ArchiveUploadModalView(View):
    """Serves the Add image htmx popup. Signed in users only -- the button
    that fires this request is hidden from anonymous visitors already, this
    is the server side half of that same rule."""

    def get(self, request):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to add an image."}, status=401)
        return render(
            request,
            "ARCHIVE/partials/upload_modal.html",
            {"quality_choices": ImageQuality.CHOICES, "default_quality": ImageQuality.MEDIUM},
        )


class ArchiveUploadView(View):
    """Validates the Add image form and creates the ArchiveImage row. The
    file always goes through SERVICE_INTERNAL.images.upload_archive_image
    first -- nothing is written to the database until Cloudinary has
    confirmed the upload."""

    def post(self, request):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to add an image.", "valid": False}, status=401)

        image_file = request.FILES.get("image_file")
        alt = (request.POST.get("alt") or "").strip()
        quality = (request.POST.get("quality") or ImageQuality.MEDIUM).strip().lower()
        width_raw = request.POST.get("width")
        height_raw = request.POST.get("height")

        if not image_file:
            return JsonResponse({"detail": "Please choose a picture to upload.", "valid": False}, status=400)
        if not alt:
            return JsonResponse({"detail": "Please add a short description for the picture.", "valid": False}, status=400)
        if len(alt) > 150:
            return JsonResponse({"detail": "The description is limited to 150 characters.", "valid": False}, status=400)
        if quality not in QUALITY_LABELS:
            return JsonResponse({"detail": "Select a valid image quality.", "valid": False}, status=400)

        #   WIDTH/HEIGHT ARE REQUIRED, not optional: every archive picture
        #   needs a real, known size so it can be embedded elsewhere later
        #   (see BLOG.views._render_inline_image) without layout shift.
        width = _parse_dimension(width_raw)
        if width is None:
            return JsonResponse({"detail": "Please set a width for the picture.", "valid": False}, status=400)
        if width == "invalid":
            return JsonResponse({"detail": f"Width must be a whole number between {MIN_DIMENSION} and {MAX_DIMENSION}.", "valid": False}, status=400)

        height = _parse_dimension(height_raw)
        if height is None:
            return JsonResponse({"detail": "Please set a height for the picture.", "valid": False}, status=400)
        if height == "invalid":
            return JsonResponse({"detail": f"Height must be a whole number between {MIN_DIMENSION} and {MAX_DIMENSION}.", "valid": False}, status=400)

        #   RATE LIMIT BEFORE CLOUDINARY: a blocked request must never touch the upload.
        remaining_time, is_limited = is_rate_limited(request, 30, 5)
        if is_limited:
            unit = "second" if remaining_time == 1 else "seconds"
            return JsonResponse({"detail": f"Too many uploads. Try again in {remaining_time} {unit}.", "valid": False}, status=429)

        try:
            image_url, actual_width, actual_height = upload_archive_image(
                image_file, quality=quality, width=width, height=height
            )
        except ImageUploadError as exc:
            return JsonResponse({"detail": str(exc), "valid": False}, status=400)

        #   NO EXACT IMAGE TWICE: same url + same alt text is a duplicate.
        #   Checked here for a friendly message, and enforced again by the
        #   model's UniqueConstraint below in case of a race.
        if ArchiveImage.objects.filter(url__iexact=image_url, alt__iexact=alt).exists():
            return JsonResponse({"detail": "This exact image already exists in the archive.", "valid": False}, status=400)

        try:
            archive_image = ArchiveImage.objects.create(
                url=image_url,
                alt=alt,
                quality=quality,
                width=actual_width,
                height=actual_height,
                author=request.user,
            )
        except IntegrityError:
            return JsonResponse({"detail": "This exact image already exists in the archive.", "valid": False}, status=400)

        return JsonResponse(
            {
                "detail": "Image added to the archive.",
                "valid": True,
                "id": archive_image.pk,
                "image_url": image_url,
                "width": actual_width,
                "height": actual_height,
            },
            status=201,
        )


class CloudinaryProxyView(View):
    """Serves every Cloudinary-hosted picture in the project from *this*
    domain instead of res.cloudinary.com, so nobody looking at a page (or
    its <img src>) can tell Cloudinary is involved at all.

    `cloud_path` is exactly what Cloudinary itself expects after the cloud
    name, e.g. "image/upload/v1699999999/abureport/archive/x.jpg" -- the
    part of a secure_url that comes after
    "https://res.cloudinary.com/<cloud_name>/". This view rebuilds that
    real Cloudinary URL behind the scenes, fetches it, and streams back
    exactly what Cloudinary returned: same bytes, same content type, just
    served under our own domain.

    Nothing calls this view directly with a hand-built URL -- every link to
    it is produced by the `cloudinary_proxy` template filter (see
    ARCHIVE.templatetags.archive_extras), which only ever rewrites a real
    secure_url this project itself uploaded, so `cloud_path` is always a
    Cloudinary-shaped path under our own cloud name, never anything a
    visitor typed in.
    """

    def get(self, request, cloud_path):
        real_url = f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/{cloud_path}"
        query_string = request.META.get("QUERY_STRING")
        if query_string:
            real_url = f"{real_url}?{query_string}"

        try:
            upstream = requests.get(real_url, timeout=8)
        except requests.RequestException as exc:
            error_logger(msg=f"CLOUDINARY PROXY FETCH FAILED ({cloud_path}): {exc}")
            raise Http404("Image not found.")

        if upstream.status_code == 404:
            raise Http404("Image not found.")
        if upstream.status_code >= 400:
            error_logger(msg=f"CLOUDINARY PROXY UPSTREAM {upstream.status_code} for {real_url} :: {upstream.text[:300]}")
            return HttpResponse(status=502)

        response = HttpResponse(
            upstream.content,
            content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
        )
        #   Cloudinary asset URLs are content-addressed / overwrite-in-place
        #   only for avatars (see SERVICE_INTERNAL.images), so a long,
        #   cacheable lifetime is safe here; fall back to Cloudinary's own
        #   Cache-Control if it sent one.
        response["Cache-Control"] = upstream.headers.get("Cache-Control") or "public, max-age=604800, immutable"
        for header in ("Content-Disposition", "ETag", "Last-Modified"):
            if header in upstream.headers:
                response[header] = upstream.headers[header]
        return response
