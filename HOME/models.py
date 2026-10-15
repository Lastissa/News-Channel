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


class CategorySubscription(models.Model):
    """One news category an account has opted into for new-story email alerts.

    The category is stored as its NAME, not a foreign key, on purpose: the live
    list belongs to BLOG.models.Category, which contractually must only be read
    through get_category_choices(). Storing the name means a row simply goes
    stale when the category is later removed or renamed, and the profile
    control filters it out at render time -- so a reader can never stay
    "subscribed" to a category that no longer exists.

    Rows are the OPT-IN set. An account with NO rows has no preference yet and
    is treated as subscribed to EVERY current category, so the email default
    stays "everyone hears about everything" until the reader touches the
    control. Clearing the last row collapses back to that same no-preference
    state (see HOME.views._category_subscription_state), so an empty set can
    never silently mean "wants nothing" -- the master News alerts switch owns
    turning category mail off completely.
    """

    user = models.ForeignKey(
        "AUTHENTICATION.Auth",
        on_delete=models.CASCADE,
        related_name="category_subscriptions",
    )
    category = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "category"],
                name="unique_user_category_subscription",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} gets {self.category} alerts"
