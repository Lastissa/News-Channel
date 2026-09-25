"""
------------------------------------------------------------
#   IMAGE UPLOAD SECTION 
------------------------------------------------------------
Every function/class that touches image uploading lives in here so the
rest of the project only ever imports from SERVICE_INTERNAL.images and
never talks to the cloudinary SDK directly. Reads from setting

Two upload paths, two different trade offs:
    -   `upload_profile_image`   ->  personal avatar. Always squeezed down
        with the same fixed preset, the user never gets a choice. Every user
        owns exactly ONE avatar asset (`abureport/avatars/user_<id>`), a new
        upload overwrites it in place instead of adding another image.
    -   `upload_news_image`      ->  staff only, called from the Add news
        page. `quality` is whatever the LOW / MEDIUM / HIGH <select> sent
        and drives which Cloudinary preset from `ImageQuality` is used.

Neither function is called until the caller decides to call it, so "no
upload until Publish is clicked" is a rule the view enforces by simply
not calling `upload_news_image` any earlier, not something this file
has to know about.
"""

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from django.conf import settings

from SERVICE_INTERNAL.abstract import error_logger, info_logger

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)

#   WHAT WE ACCEPT FROM A BROWSER FILE INPUT. Anything else is rejected
#   before it ever leaves the server.
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}

MAX_UPLOAD_BYTES = getattr(settings, "IMAGE_UPLOAD_MAX_MB", 8) * 1024 * 1024


class ImageUploadError(Exception):
    """Raised for any bad file or failed Cloudinary call. Views catch this
    and drop `str(exc)` straight into their JSON `detail` key, so the
    message here is always meant to be shown to the person, not just
    logged."""


class ImageQuality:
    """The three choices staff get on the Add news page `<select
    name="image_quality">`. `resolve()` is the only thing views/other
    code should call, it always falls back to MEDIUM for anything it
    does not recognise."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    CHOICES = (
        (LOW, "Low - smallest file, fastest load"),
        (MEDIUM, "Medium - balanced"),
        (HIGH, "High - best detail, largest file"),
    )

    #   `quality` here is Cloudinary's own auto-quality tiers, `width` +
    #   `crop: limit` just stops anyone shipping a 6000px wide photo down
    #   the wire regardless of which quality tier they picked.
    _PRESETS = {
        LOW: {"quality": "auto:eco", "width": 1280, "crop": "limit"},
        MEDIUM: {"quality": "auto:good", "width": 1600, "crop": "limit"},
        HIGH: {"quality": "auto:best", "width": 2000, "crop": "limit"},
    }

    @classmethod
    def resolve(cls, value) -> dict:
        return cls._PRESETS.get((value or "").strip().lower(), cls._PRESETS[cls.MEDIUM])


#   FIXED, NOT USER FACING: every avatar is squeezed the exact same way so
#   personal uploads stay small and fast no matter who is uploading.
_PROFILE_IMAGE_PRESET = {"quality": "auto:eco", "width": 512, "height": 512, "crop": "fill", "gravity": "face"}

_AVATAR_FOLDER = "abureport/avatars"


def _avatar_public_id(user_id) -> str:
    """The one fixed Cloudinary public id a user's avatar always lives at.
    Built from the account id only, never from anything the browser sent, so
    nobody can aim an upload at somebody else's asset."""
    return f"{_AVATAR_FOLDER}/user_{user_id}"


def _validate_image_file(file) -> None:
    """Raises ImageUploadError if `file` is not an acceptable image
    upload. Kept deliberately simple, content type + size only. Cloudinary
    itself is the real gatekeeper for anything more exotic like a
    corrupted/malformed image."""
    if file is None:
        raise ImageUploadError("No image file was received.")

    size = getattr(file, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ImageUploadError(f"Image is too large. Max allowed size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.")

    content_type = (getattr(file, "content_type", "") or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ImageUploadError("Unsupported image type. Please upload a JPEG, PNG file.")


def _run_upload(file, folder: str, preset: dict, tag: str, public_id: str | None = None) -> dict:
    """Shared Cloudinary call used by both upload functions below. Returns
    the raw Cloudinary result dict (secure_url, width, height, ...) -- not
    just the URL -- so a caller that needs the *actual* stored size (e.g.
    upload_archive_image below) doesn't have to guess it from whatever the
    uploader typed into the form. Any Cloudinary side failure is logged and
    re-raised as ImageUploadError, so callers never need to know the SDK
    exists or catch cloudinary's own exception type.

    Without `public_id` every call stores a brand new asset in `folder` (news
    images). With `public_id` the asset lives at that exact id and is
    overwritten in place (avatars), `folder` is then ignored because the id
    already carries the full path. `invalidate` clears the CDN copy so the
    replaced picture shows up straight away."""
    if public_id:
        placement = {"public_id": public_id, "unique_filename": False, "overwrite": True, "invalidate": True}
    else:
        placement = {"folder": folder, "unique_filename": True, "overwrite": False}

    try:
        result = cloudinary.uploader.upload(
            file,
            resource_type="image",
            fetch_format="auto",
            transformation=[preset],
            tags=[tag],
            **placement,
        )
    except CloudinaryError as exc:
        error_logger(msg=f"CLOUDINARY UPLOAD FAILED ({tag}): {exc}")
        raise ImageUploadError("Could not upload the image right now. Please try again.") from exc

    secure_url = result.get("secure_url") or result.get("url")
    if not secure_url:
        error_logger(msg=f"CLOUDINARY UPLOAD ({tag}) RETURNED NO URL: {result}")
        raise ImageUploadError("Cloudinary did not return an image URL.")

    info_logger(msg=f"CLOUDINARY UPLOAD OK ({tag}): {secure_url}")
    return result


def upload_profile_image(file, user_id) -> str:
    """Personal / avatar image upload. Always the same optimized preset,
    on purpose there is no quality choice here, unlike the staff news
    upload below. The picture replaces the user's previous uploaded avatar
    (same public id, overwritten), so re-uploading never piles up images."""
    _validate_image_file(file)
    result = _run_upload(
        file,
        folder=_AVATAR_FOLDER,
        preset=_PROFILE_IMAGE_PRESET,
        tag="avatar",
        public_id=_avatar_public_id(user_id),
    )
    return result.get("secure_url") or result.get("url")


def upload_news_image(file, quality=ImageQuality.MEDIUM) -> str:
    """Staff-only news/story image upload. `quality` is whatever the Add
    news page `<select name="image_quality">` sent (low/medium/high)."""
    _validate_image_file(file)
    preset = ImageQuality.resolve(quality)
    result = _run_upload(file, folder="abureport/news", preset=preset, tag="news")
    return result.get("secure_url") or result.get("url")


def upload_archive_image(file, quality=ImageQuality.MEDIUM, width=None, height=None) -> tuple[str, int, int]:
    """Public /archive/ gallery upload, open to any signed in user (see
    ARCHIVE.views.ArchiveUploadView). `quality` picks the same auto-quality
    tier as the news upload above, but the width/height are whatever the
    uploader typed into the Add image form, so a copy of the preset dict is
    taken here instead of mutating the shared ImageQuality preset.

    If either box was filled in, the tier's own fixed width (e.g. 1600 for
    MEDIUM) is dropped first -- otherwise a height-only request would keep
    that leftover width in the transform and Cloudinary would constrain to
    a `1600 x height` box instead of scaling by height alone. `limit` never
    upscales, it only ever caps a dimension down.

    Returns `(secure_url, actual_width, actual_height)`. The width/height
    are read back from Cloudinary's own upload result, not from the
    `width`/`height` arguments -- those are only a requested *ceiling*
    (`crop: limit`), the real stored size can end up smaller (e.g. a photo
    narrower than the requested width is never upscaled). Callers (see
    ARCHIVE.views.ArchiveUploadView) persist these actual numbers so every
    picture in the archive can be rendered with correct <img width height>
    attributes wherever it is later embedded, instead of that information
    being lost after upload."""
    _validate_image_file(file)
    preset = dict(ImageQuality.resolve(quality))
    if width or height:
        preset.pop("width", None)
        preset.pop("height", None)
        if width:
            preset["width"] = width
        if height:
            preset["height"] = height
        preset["crop"] = "limit"
    result = _run_upload(file, folder="abureport/archive", preset=preset, tag="archive")
    secure_url = result.get("secure_url") or result.get("url")
    actual_width = result.get("width") or width or 0
    actual_height = result.get("height") or height or 0
    return secure_url, actual_width, actual_height
