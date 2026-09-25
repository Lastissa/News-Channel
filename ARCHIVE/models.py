from django.db import models
from django.db.models.functions import Lower

from SERVICE_INTERNAL.images import ImageQuality


class ArchiveImage(models.Model):
    """One picture in the public /archive/ gallery. Any signed in user can
    add one (see ARCHIVE.views.ArchiveUploadView); the gallery itself is
    readable by anyone, signed in or not."""

    url = models.URLField()
    alt = models.CharField(max_length=150, help_text="Short description shown under the picture.")
    quality = models.CharField(max_length=10, choices=ImageQuality.CHOICES, default=ImageQuality.MEDIUM)
    #   THE ACTUAL PIXEL SIZE OF THE STORED ASSET, as Cloudinary confirmed it
    #   after the upload transform (not just what the uploader typed in the
    #   form). Required at upload time -- see ARCHIVE.views.ArchiveUploadView
    #   -- so every picture in the archive always has real dimensions to
    #   render with (used for the <img width height> attributes here and
    #   wherever this picture is embedded via an imgl/imgr token, see
    #   BLOG.views._render_inline_image).
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='archive_images')
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date_created']
        constraints = [
            #   NO EXACT IMAGE TWICE: same url + same alt text is treated as
            #   a duplicate upload, case-insensitively.
            models.UniqueConstraint(Lower('url'), Lower('alt'), name='unique_archive_image_url_alt'),
        ]

    def __str__(self):
        return f"{self.author.email} - {self.alt[:30]}"
