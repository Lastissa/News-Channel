from django.db import models
from django.db.models.functions import Lower

from SERVICE_INTERNAL.images import ImageQuality


class ArchiveKind:
    """The two shapes a row in this table can be. IMAGE keeps the original
    behaviour (Cloudinary image transform, required width/height). FILE is
    the generic "any other file" upload added alongside it -- see
    SERVICE_INTERNAL.images.upload_archive_file and
    ARCHIVE.views.ArchiveUploadView."""

    IMAGE = "image"
    FILE = "file"

    CHOICES = (
        (IMAGE, "Image"),
        (FILE, "File"),
    )


class ArchiveImage(models.Model):
    """One item in the public /archive/ gallery -- either a picture or a
    plain file (see `kind`). Any signed in user can add one (see
    ARCHIVE.views.ArchiveUploadView); the gallery itself is readable by
    anyone, signed in or not. Only the uploader can edit or delete their
    own item (see ARCHIVE.views.ArchiveItemEditView / ArchiveItemDeleteView).

    The model kept its original name (and picture-shaped fields) even
    though it now also stores non-image files, to avoid a disruptive
    rename across every place that already imports ArchiveImage (see
    BLOG.views._archive_dimensions_for_url in particular)."""

    kind = models.CharField(max_length=5, choices=ArchiveKind.CHOICES, default=ArchiveKind.IMAGE)
    url = models.URLField()
    alt = models.CharField(max_length=150, help_text="Short description shown under the picture/file.")
    quality = models.CharField(max_length=10, choices=ImageQuality.CHOICES, default=ImageQuality.MEDIUM)
    #   THE ACTUAL PIXEL SIZE OF THE STORED ASSET, as Cloudinary confirmed it
    #   after the upload transform (not just what the uploader typed in the
    #   form). Required at upload time for kind=IMAGE -- see
    #   ARCHIVE.views.ArchiveUploadView -- so every picture in the archive
    #   always has real dimensions to render with (used for the <img width
    #   height> attributes here and wherever this picture is embedded via an
    #   imgl/imgr/imgc token, see BLOG.views._render_inline_image). Left at 0/0
    #   for kind=FILE, where a pixel size makes no sense.
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    #   FILE-ONLY METADATA (kind=FILE). Left blank/0 for kind=IMAGE.
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size = models.PositiveIntegerField(default=0, help_text="Bytes. Only set for kind=FILE.")
    #   CLOUDINARY BOOK KEEPING, needed to delete the remote asset again
    #   (see SERVICE_INTERNAL.images.destroy_archive_asset). Blank for rows
    #   created before this field existed.
    public_id = models.CharField(max_length=255, blank=True, default="")
    resource_type = models.CharField(max_length=10, default="image")
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='archive_images')
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_created']
        constraints = [
            #   NO EXACT IMAGE/FILE TWICE: same url + same alt text is
            #   treated as a duplicate upload, case-insensitively.
            models.UniqueConstraint(Lower('url'), Lower('alt'), name='unique_archive_image_url_alt'),
        ]

    def __str__(self):
        return f"{self.author.email} - {self.alt[:30]}"
