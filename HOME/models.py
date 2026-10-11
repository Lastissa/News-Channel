from django.conf import settings
from django.db import models
from django.utils import timezone


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


class ReadingHistory(models.Model):
    """One row per signed-in reader/story pair.

    `read_at` is bumped every time the story is opened, so the "Continue
    reading" popup can show the most recently read stories in order. The older
    `Blog.non_anonymous_viewer` link has no timestamp at all, so it can only
    ever be sorted by the story's publish date.
    """

    user = models.ForeignKey("AUTHENTICATION.Auth", on_delete=models.CASCADE, related_name="reading_history")
    blog = models.ForeignKey("BLOG.Blog", on_delete=models.CASCADE, related_name="read_by")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-read_at"]
        verbose_name_plural = "reading history"
        constraints = [
            models.UniqueConstraint(fields=["user", "blog"], name="unique_user_blog_read"),
        ]

    def __str__(self):
        return f"{self.user.email} read {self.blog.heading}"
