from django.conf import settings
from django.db import models


class Bookmark(models.Model):
    """A saved story for a signed in user. One row per user/story pair."""

    user = models.ForeignKey("AUTHENTICATION.Auth",on_delete=models.CASCADE,related_name="bookmarks",)
    blog = models.ForeignKey("BLOG.Blog",on_delete=models.CASCADE,related_name="bookmarked_by",)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "blog"], name="unique_user_blog_bookmark"),
        ]

    def __str__(self):
        return f"{self.user.email} saved {self.blog.heading}"
