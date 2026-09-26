"""Public /archive/ gallery: anyone can browse, only a signed in user can
add a picture or file (see ArchiveUploadModalView / ArchiveUploadView
below), and only the uploader can edit or delete their own item again (see
ArchiveManageModalView / ArchiveItemEditView / ArchiveItemDeleteView)."""

import requests
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from HOME.views import _resolve_page_number
from SERVICE_INTERNAL.abstract import error_logger, is_rate_limited
from SERVICE_INTERNAL.images import (
    ImageQuality,
    ImageUploadError,
    destroy_archive_asset,
    upload_archive_file,
    upload_archive_image,
)
from SERVICE_INTERNAL.permissions import is_authenticated

from ARCHIVE.models import ArchiveImage, ArchiveKind

PAGE_SIZE = 5  #   HOW MANY ITEMS LOAD AT ONCE, BOTH FIRST PAINT AND EVERY HTMX PAGE
MANAGE_PAGE_SIZE = 12  #   items shown at once in the "Edit Added Images" list

MIN_DIMENSION = 50
MAX_DIMENSION = 4000

ALT_MAX_LENGTH = 150

#   {"low": "Low", "medium": "Medium", "high": "High"} -- the human word
#   before the " - ..." blurb in ImageQuality.CHOICES.
QUALITY_LABELS = {value: label.split(" - ")[0] for value, label in ImageQuality.CHOICES}

#   File sizes are always shown human readable ("2.4 MB"), never as a raw
#   byte count -- see _human_file_size below.
_SIZE_UNITS = ("bytes", "KB", "MB", "GB")


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


def _human_file_size(num_bytes):
    """1536 -> "1.5 KB". Used on file cards instead of the quality tag,
    which only ever applied to pictures."""
    size = float(num_bytes or 0)
    for unit in _SIZE_UNITS:
        if size < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} {_SIZE_UNITS[-1]}"


def _file_extension(name):
    name = name or ""
    return name.rsplit(".", 1)[-1].upper() if "." in name else ""


def _serialize_images(images):
    return [
        {
            "id": image.id,
            "kind": image.kind,
            "url": image.url,
            "width": image.width,
            "height": image.height,
            "alt": image.alt,
            "quality_label": QUALITY_LABELS.get(image.quality, image.quality.title()),
            "original_filename": image.original_filename,
            "file_extension": _file_extension(image.original_filename),
            "file_size_label": _human_file_size(image.file_size),
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


def _paginate_own(user, page_number):
    """Same shape as _paginate above, but scoped to *this* user's own
    uploads only, and with its own (smaller) page size -- backs the "Edit
    Added Images" htmx list (see ArchiveManageModalView)."""
    qs = ArchiveImage.objects.filter(author=user).order_by("-date_created")
    paginator = Paginator(qs, MANAGE_PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    page = paginator.get_page(page_number)
    return {
        "items": _serialize_images(page.object_list),
        "page": page.number,
        "num_pages": paginator.num_pages,
        "has_next": page.has_next(),
        "has_previous": page.has_previous(),
        "next_page": page.next_page_number() if page.has_next() else None,
        "previous_page": page.previous_page_number() if page.has_previous() else None,
    }


class ArchiveGalleryView(View):
    """GET: the full /archive/ page with the first PAGE_SIZE items.
    POST: the paginated grid only, for the htmx "see more" swap, based on
    whatever page the (still anonymous-allowed) viewer is on."""

    def get(self, request):
        context = _paginate(page_number=1)
        context["can_upload"] = is_authenticated(request.user)
        return render(request, "ARCHIVE/gallery.html", context)

    def post(self, request):
        page_number = _resolve_page_number(request.POST.get("page"), default=1)
        context = _paginate(page_number=page_number)
        return render(request, "ARCHIVE/partials/gallery_grid.html", context)


class ArchiveUploadModalView(View):
    """Serves the Add image/file htmx popup. Signed in users only -- the
    button that fires this request is hidden from anonymous visitors
    already, this is the server side half of that same rule."""

    def get(self, request):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to add an image or file."}, status=401)
        return render(
            request,
            "ARCHIVE/partials/upload_modal.html",
            {"quality_choices": ImageQuality.CHOICES, "default_quality": ImageQuality.MEDIUM},
        )


class ArchiveUploadView(View):
    """Validates the Add image/file form and creates the ArchiveImage row.
    Which branch runs is decided purely by the *uploaded file's* content
    type, not by anything the visitor picked in a dropdown: a JPEG/PNG
    always goes through the existing Cloudinary image transform pipeline
    (SERVICE_INTERNAL.images.upload_archive_image, width/height/quality
    required), anything else goes through the plain file pipeline
    (SERVICE_INTERNAL.images.upload_archive_file, no transform, no
    width/height/quality). Nothing is written to the database until
    Cloudinary has confirmed the upload."""

    def post(self, request):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to add an image or file.", "valid": False}, status=401)

        upload_file = request.FILES.get("upload_file")
        alt = (request.POST.get("alt") or "").strip()

        if not upload_file:
            return JsonResponse({"detail": "Please choose a picture or file to upload.", "valid": False}, status=400)
        if not alt:
            return JsonResponse({"detail": "Please add a short description.", "valid": False}, status=400)
        if len(alt) > ALT_MAX_LENGTH:
            return JsonResponse({"detail": f"The description is limited to {ALT_MAX_LENGTH} characters.", "valid": False}, status=400)

        content_type = (getattr(upload_file, "content_type", "") or "").lower()
        is_image = content_type in {"image/jpeg", "image/png"}

        #   RATE LIMIT BEFORE CLOUDINARY: a blocked request must never touch the upload.
        remaining_time, is_limited = is_rate_limited(request, 30, 5)
        if is_limited:
            unit = "second" if remaining_time == 1 else "seconds"
            return JsonResponse({"detail": f"Too many uploads. Try again in {remaining_time} {unit}.", "valid": False}, status=429)

        if is_image:
            quality = (request.POST.get("quality") or ImageQuality.MEDIUM).strip().lower()
            if quality not in QUALITY_LABELS:
                return JsonResponse({"detail": "Select a valid image quality.", "valid": False}, status=400)

            #   WIDTH/HEIGHT ARE REQUIRED, not optional: every archive picture
            #   needs a real, known size so it can be embedded elsewhere later
            #   (see BLOG.views._render_inline_image) without layout shift.
            width = _parse_dimension(request.POST.get("width"))
            if width is None:
                return JsonResponse({"detail": "Please set a width for the picture.", "valid": False}, status=400)
            if width == "invalid":
                return JsonResponse({"detail": f"Width must be a whole number between {MIN_DIMENSION} and {MAX_DIMENSION}.", "valid": False}, status=400)

            height = _parse_dimension(request.POST.get("height"))
            if height is None:
                return JsonResponse({"detail": "Please set a height for the picture.", "valid": False}, status=400)
            if height == "invalid":
                return JsonResponse({"detail": f"Height must be a whole number between {MIN_DIMENSION} and {MAX_DIMENSION}.", "valid": False}, status=400)

            try:
                uploaded = upload_archive_image(upload_file, quality=quality, width=width, height=height)
            except ImageUploadError as exc:
                return JsonResponse({"detail": str(exc), "valid": False}, status=400)

            row_kwargs = {
                "kind": ArchiveKind.IMAGE,
                "quality": quality,
                "width": uploaded["width"],
                "height": uploaded["height"],
            }
        else:
            try:
                uploaded = upload_archive_file(upload_file)
            except ImageUploadError as exc:
                return JsonResponse({"detail": str(exc), "valid": False}, status=400)

            row_kwargs = {
                "kind": ArchiveKind.FILE,
                "original_filename": uploaded["original_filename"],
                "file_size": uploaded["bytes"],
            }

        image_url = uploaded["secure_url"]

        #   NO EXACT ITEM TWICE: same url + same alt text is a duplicate.
        #   Checked here for a friendly message, and enforced again by the
        #   model's UniqueConstraint below in case of a race.
        if ArchiveImage.objects.filter(url__iexact=image_url, alt__iexact=alt).exists():
            return JsonResponse({"detail": "This exact item already exists in the archive.", "valid": False}, status=400)

        try:
            archive_item = ArchiveImage.objects.create(
                url=image_url,
                alt=alt,
                author=request.user,
                public_id=uploaded.get("public_id", ""),
                resource_type=uploaded.get("resource_type", "image"),
                **row_kwargs,
            )
        except IntegrityError:
            return JsonResponse({"detail": "This exact item already exists in the archive.", "valid": False}, status=400)

        return JsonResponse(
            {
                "detail": "Image added to the archive." if is_image else "File added to the archive.",
                "valid": True,
                "id": archive_item.pk,
                "kind": archive_item.kind,
                "image_url": image_url,
                "width": archive_item.width,
                "height": archive_item.height,
            },
            status=201,
        )


class ArchiveManageModalView(View):
    """Serves the "Edit Added Images" htmx popup: every item *this* signed
    in user has uploaded, each with an inline "edit description" form and
    a delete button (see ArchiveItemEditView / ArchiveItemDeleteView).
    Reuses the same [data-archive-overlay] slot the Add Image/File modal
    uses -- there is no separate manage page."""

    def get(self, request):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to manage your uploads."}, status=401)
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        context = _paginate_own(request.user, page_number)
        return render(request, "ARCHIVE/partials/manage_modal.html", context)


class ArchiveManageListView(View):
    """POST: same list ArchiveManageModalView renders, for the "load more"
    button inside the manage popup -- mirrors ArchiveGalleryView.post."""

    def post(self, request):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to manage your uploads."}, status=401)
        page_number = _resolve_page_number(request.POST.get("page"), default=1)
        context = _paginate_own(request.user, page_number)
        return render(request, "ARCHIVE/partials/manage_rows_page.html", context)


class ArchiveItemEditView(View):
    """Updates the description of one of *this* user's own archive items.
    Always re-renders the manage list (page 1 of it), whether the edit
    succeeded or not, so the popup never needs a second request shape for
    the error case -- errors just show up as a banner above the same
    list. On success, `HX-Trigger` tells archive.js to also refresh the
    public gallery grid behind the popup."""

    def post(self, request, pk):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to manage your uploads."}, status=401)

        item = get_object_or_404(ArchiveImage, pk=pk, author=request.user)
        alt = (request.POST.get("alt") or "").strip()

        error = None
        if not alt:
            error = "Description can't be empty."
        elif len(alt) > ALT_MAX_LENGTH:
            error = f"The description is limited to {ALT_MAX_LENGTH} characters."
        elif ArchiveImage.objects.filter(url__iexact=item.url, alt__iexact=alt).exclude(pk=item.pk).exists():
            error = "Another item already uses this exact description."

        if not error:
            item.alt = alt
            try:
                item.save(update_fields=["alt"])
            except IntegrityError:
                error = "Another item already uses this exact description."

        context = _paginate_own(request.user, page_number=1)
        context["error"] = error
        if not error:
            context["notice"] = "Description updated."
        response = render(request, "ARCHIVE/partials/manage_list.html", context)
        if not error:
            response["HX-Trigger"] = "archive:refresh"
        return response


class ArchiveItemDeleteView(View):
    """Deletes one of *this* user's own archive items -- the database row
    and, best effort, the underlying Cloudinary asset (see
    SERVICE_INTERNAL.images.destroy_archive_asset). Re-renders the manage
    list the same way ArchiveItemEditView does above."""

    def post(self, request, pk):
        if not is_authenticated(request.user):
            return JsonResponse({"detail": "Please sign in to manage your uploads."}, status=401)

        item = get_object_or_404(ArchiveImage, pk=pk, author=request.user)
        destroy_archive_asset(item.public_id, item.resource_type)
        item.delete()
        "TODO: also delete it in the cloudinary table itslelf, not just here."
        context = _paginate_own(request.user, page_number=1)
        context["notice"] = "Item deleted."
        response = render(request, "ARCHIVE/partials/manage_list.html", context)
        response["HX-Trigger"] = "archive:refresh"
        return response


class CloudinaryProxyView(View):
    """Serves every Cloudinary-hosted asset in the project -- pictures and
    plain files alike, any Cloudinary `resource_type` (image/raw/video) --
    from *this* domain instead of res.cloudinary.com, so nobody looking at
    a page (or its <img src>/download link) can tell Cloudinary is
    involved at all, and every asset URL on the site shares this project's
    own domain for SEO/link-authority purposes.

    `cloud_path` is exactly what Cloudinary itself expects after the cloud
    name, e.g. "image/upload/v1699999999/abureport/archive/x.jpg" or
    "raw/upload/v1699999999/abureport/archive/report.pdf" -- the part of a
    secure_url that comes after "https://res.cloudinary.com/<cloud_name>/".
    This view rebuilds that real Cloudinary URL behind the scenes, fetches
    it, and streams back exactly what Cloudinary returned: same bytes,
    same content type, just served under our own domain.

    An optional `?filename=` query parameter forces the browser to
    download the response under that exact name (used for archive FILE
    items, whose Cloudinary public id rarely matches the original
    filename a human uploaded -- see ARCHIVE/templates/ARCHIVE/partials/
    gallery_grid.html and manage_list.html). It is stripped out before the
    upstream request is made, so Cloudinary itself never sees it.

    Nothing calls this view directly with a hand-built URL -- every link to
    it is produced by the `cloudinary_proxy` template filter (see
    ARCHIVE.templatetags.archive_extras), which only ever rewrites a real
    secure_url this project itself uploaded, so `cloud_path` is always a
    Cloudinary-shaped path under our own cloud name, never anything a
    visitor typed in.
    """

    def get(self, request, cloud_path):
        query_params = request.GET.copy()
        requested_filename = (query_params.pop("filename", [""])[0] or "").strip()

        real_url = f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/{cloud_path}"
        query_string = query_params.urlencode()
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
        if requested_filename:
            safe_filename = requested_filename.replace('"', "").replace("\r", "").replace("\n", "")
            response["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
        return response
