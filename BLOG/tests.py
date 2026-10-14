import json
from unittest import mock

from django.apps import apps
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.db.models import F
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from hypothesis import given, settings as hyp_settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase

from ADMIN.models import SiteSettings
from AUTHENTICATION.models import Auth
from BLOG.models import Blog, BlogLike, Comment
from BLOG.views import parse_story_content, StoryDetailView
from SERVICE_INTERNAL.abstract import is_bot_request
from STAFF.models import StaffProfile


class BlogArticleFormattingTests(TestCase):
    def setUp(self):
        self.author = Auth.objects.create_user(email="author@example.com")

    def test_story_content_reformats_links_headers_and_lists(self):
        content = """# Admissions

The official portal is here: https://example.com/path

* First bullet item
* Second bullet item

1. First numbered item
2. Second numbered item

**Important update**

__Please note:__
"""

        html = parse_story_content(content)

        self.assertIn('<h2>Admissions</h2>', html)
        self.assertIn('<a href="https://example.com/path"', html)
        self.assertIn('<ul>', html)
        self.assertIn('<li>First bullet item</li>', html)
        self.assertIn('<ol>', html)
        self.assertIn('<li>First numbered item</li>', html)
        self.assertIn('<strong>Important update</strong>', html)
        self.assertIn('<em>Please note:</em>', html)

    def test_story_content_supports_official_news_markers(self):
        content = """# Admission Process

The official portal is here: https://example.edu/admission

**Late applications will not be accepted.**

__Please note:__ deadlines are strict.

* A valid email address
* A recent passport photo

1. Visit the official portal
2. Complete the form
"""

        html = parse_story_content(content)

        self.assertIn('<h2>Admission Process</h2>', html)
        self.assertIn('<a href="https://example.edu/admission"', html)
        self.assertIn('<strong>Late applications will not be accepted.</strong>', html)
        self.assertIn('<em>Please note:</em>', html)
        self.assertIn('<ul>', html)
        self.assertIn('<ol>', html)

    def test_story_content_renders_an_inline_video_with_play_pause_and_sound_controls(self):
        content = (
            "vidl https://cdn.example.com/clip.mp4 Crowd at the rally\n\n"
            "vidr https://cdn.example.com/clip2.mp4 The damaged bridge\n\n"
            "vidc https://cdn.example.com/clip3.mp4 Flood water rising\n"
        )

        html = parse_story_content(content)

        #   left / right / centre placement reuses the image figure float classes
        self.assertIn("story-inline-fig-left", html)
        self.assertIn("story-inline-fig-right", html)
        self.assertIn("story-inline-fig-center", html)
        #   the video autoplays muted on a loop and carries no native controls
        self.assertIn('<video class="story-inline-video-el"', html)
        self.assertIn("autoplay", html)
        self.assertIn("muted", html)
        self.assertIn("loop", html)
        self.assertNotIn("controls", html)
        #   the two overlaid controls are our own play/pause and sound buttons;
        #   sound starts off, so the sound button promises to unmute
        self.assertIn("data-video-toggle", html)
        self.assertIn("data-video-sound", html)
        self.assertIn('aria-label="Unmute video"', html)
        #   the trailing text becomes the caption
        self.assertIn("<figcaption>Crowd at the rally</figcaption>", html)

    def test_a_video_token_alone_does_not_count_as_body_text(self):
        from SERVICE_INTERNAL.story_validation import validate_story

        result = validate_story("Rally update", "vidc https://cdn.example.com/clip.mp4 Crowd at the rally")

        codes = [item["code"] for item in result["errors"]]
        self.assertIn("no_body_text", codes)

    def test_story_content_renders_markdown_links_and_buttons(self):
        content = (
            "Read the [admission guide](https://example.edu/admission/guide) before you apply.\n\n"
            "btn https://example.edu/apply Start your application\n\n"
            "The portal is https://example.edu/portal\n"
        )

        html = parse_story_content(content)

        #   [words](url): the words carry the link, the address is not shown
        self.assertIn(
            '<a href="https://example.edu/admission/guide" rel="noopener noreferrer" target="_blank">admission guide</a>',
            html,
        )
        #   a btn line becomes one block-level button carrying the trailing text
        self.assertIn('<p class="story-inline-btn-row">', html)
        self.assertIn('<a class="story-inline-btn" href="https://example.edu/apply"', html)
        self.assertIn(">Start your application</a>", html)
        #   a bare URL still linkifies
        self.assertIn('<a href="https://example.edu/portal"', html)

    def test_a_markdown_link_url_is_only_linked_once(self):
        html = parse_story_content("[Guide](https://example.edu/guide)")

        self.assertEqual(html.count("<a "), 1)
        self.assertNotIn("](https://example.edu/guide)", html)

    def test_a_button_without_a_label_falls_back_to_the_url(self):
        html = parse_story_content("btn https://example.edu/apply")

        self.assertIn('<a class="story-inline-btn" href="https://example.edu/apply"', html)
        self.assertIn(">https://example.edu/apply</a>", html)

    def test_ticker_text_strips_markdown_links_and_button_markers(self):
        from BLOG.views import build_ticker_text

        text = build_ticker_text(
            "Read [the guide](https://example.edu/guide) now.\n\n"
            "btn https://example.edu/apply Apply here\n"
        )

        self.assertIn("the guide", text)
        self.assertIn("Apply here", text)
        self.assertNotIn("[", text)
        self.assertNotIn("btn ", text)
        self.assertNotIn("https://example.edu/apply", text)

    def test_a_markdown_link_counts_its_words_but_not_the_address(self):
        from SERVICE_INTERNAL.story_validation import _word_count, split_blocks

        self.assertEqual(_word_count("[Apply here](https://example.edu/very/long/path)"), 2)

        blocks = split_blocks("btn https://example.edu/apply Apply here\n\nA plain paragraph follows.")
        self.assertEqual(blocks[0]["type"], "button")
        self.assertEqual(blocks[1]["type"], "paragraph")

    def test_a_button_alone_does_not_count_as_body_text(self):
        from SERVICE_INTERNAL.story_validation import validate_story

        result = validate_story("Apply now", "btn https://example.edu/apply Apply here")

        codes = [item["code"] for item in result["errors"]]
        self.assertIn("no_body_text", codes)

    def _like(self, blog):
        return self.client.post(f"/story/{blog.id}/like/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")


    @mock.patch("AUTHENTICATION.signals._try_send_login_email")
    def test_blog_like_toggles_and_returns_the_real_total(self, _mail):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="Daily news update",
            content="A short update.",
        )
        self.client.force_login(self.author)

        first = self._like(blog)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(json.loads(first.content)["likes"], 1)
        self.assertTrue(json.loads(first.content)["liked"])

        #   ANOTHER READER LIKES BETWEEN OUR TWO CLICKS
        Blog.objects.filter(pk=blog.pk).update(likes=F("likes") + 4)

        second = self._like(blog)
        payload = json.loads(second.content)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(payload["likes"], 4)  #   THE REAL TOTAL, NOT 1 - 1 = 0
        self.assertFalse(payload["liked"])
        self.assertEqual(payload["detail"], "Like removed.")
        blog.refresh_from_db()
        self.assertEqual(blog.likes, 4)

        third = self._like(blog)
        self.assertEqual(json.loads(third.content)["likes"], 5)
        self.assertTrue(json.loads(third.content)["liked"])

    @mock.patch("AUTHENTICATION.signals._try_send_login_email")
    def test_unlike_never_takes_the_counter_below_zero(self, _mail):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="Daily news update",
            content="A short update.",
        )
        self.client.force_login(self.author)
        session = self.client.session
        session.save()

        response = self._like(blog)

        self.assertEqual(json.loads(response.content)["likes"], 0)
        self.assertFalse(json.loads(response.content)["liked"])

    @mock.patch("AUTHENTICATION.signals._try_send_login_email")
    def test_story_like_state_survives_logout_and_login(self, _mail):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="A like that persists",
            content="A short update.",
        )
        self.client.force_login(self.author)

        first = json.loads(self._like(blog).content)
        self.assertEqual((first["likes"], first["liked"]), (1, True))
        self.assertTrue(BlogLike.objects.filter(user=self.author, blog=blog).exists())

        self.client.logout()
        self.client.force_login(self.author)
        StaffProfile.objects.create(auth=self.author, gender="M", full_name="Like Reader")
        page = self.client.get(reverse("blog:story_detail", kwargs={"blog_slug": blog.slug}))
        self.assertContains(page, 'data-story-like-btn data-liked="true"')

        second = json.loads(self._like(blog).content)

        self.assertEqual((second["likes"], second["liked"]), (0, False))
        self.assertFalse(BlogLike.objects.filter(user=self.author, blog=blog).exists())

    @mock.patch("AUTHENTICATION.signals._try_send_login_email")
    def test_comment_like_toggles_and_returns_the_real_total(self, _mail):
        blog = Blog.objects.create(author=self.author, category="GENERAL", heading="Commented story", content="Body.")
        comment = Comment.objects.create(blog=blog, author=self.author, content="Nice one")
        self.client.force_login(self.author)
        url = f"/story/comment/{comment.id}/like/"
        ajax = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

        first = json.loads(self.client.post(url, **ajax).content)
        self.assertEqual((first["likes"], first["liked"]), (1, True))

        Comment.objects.filter(pk=comment.pk).update(likes=F("likes") + 2)  # other readers

        second = json.loads(self.client.post(url, **ajax).content)
        self.assertEqual((second["likes"], second["liked"]), (2, False))
        self.assertEqual(second["detail"], "Like removed.")

        third = json.loads(self.client.post(url, **ajax).content)
        self.assertEqual((third["likes"], third["liked"]), (3, True))

    def test_anonymous_like_is_rejected(self):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="Daily news update",
            content="A short update.",
        )

        response = self._like(blog)

        self.assertEqual(response.status_code, 401)
        blog.refresh_from_db()
        self.assertEqual(blog.likes, 0)

    def test_only_one_comment_per_story_is_allowed(self):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="A commentable story",
            content="This is a story for comments.",
        )
        self.client.force_login(self.author)

        first = self.client.post(f"/story/{blog.id}/comment/", {"comment": "First comment"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        second = self.client.post(f"/story/{blog.id}/comment/", {"comment": "Second comment"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Comment.objects.filter(blog=blog, author=self.author).count(), 1)


class StoryReportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.author = Auth.objects.create_user(email="report-story-author@example.com")
        self.blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="A reportable story",
            content="The story text.",
        )
        StaffProfile.objects.create(auth=self.author, gender="M", full_name="Report Author")
        SiteSettings.objects.create(pk=1, support_email="support@example.com")
        self.url = reverse("blog:story_report", args=[self.blog.pk])

    def _submit_report(self, content="The image caption does not match the story."):
        return self.client.post(
            self.url,
            {"content": content},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    @mock.patch("BLOG.views._dispatch_email", return_value=True)
    def test_anonymous_report_is_sent_as_anonymous(self, send_report):
        response = self._submit_report()

        self.assertEqual(response.status_code, 200)
        args, kwargs = send_report.call_args
        self.assertEqual(args[0], "support@example.com")
        self.assertIn("Reporter:</strong> Anonymous", args[2])
        self.assertNotIn(self.author.email, args[2])
        self.assertIn(self.blog.heading, args[2])
        self.assertTrue(kwargs["no_async"])

    @mock.patch("BLOG.views._dispatch_email", return_value=True)
    @mock.patch("AUTHENTICATION.signals._try_send_login_email")
    def test_authenticated_report_includes_the_account_email(self, _mail, send_report):
        self.client.force_login(self.author)
        page = self.client.get(
            reverse("blog:story_detail", kwargs={"blog_slug": self.blog.slug})
        )
        self.assertContains(page, "data-story-report-form")
        self.assertContains(page, "Your account email will be included.")

        response = self._submit_report()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"Reporter:</strong> {self.author.email}", send_report.call_args.args[2])

    def test_empty_report_is_rejected_without_sending_email(self):
        response = self._submit_report("   ")

        self.assertEqual(response.status_code, 400)

    @mock.patch("BLOG.views._dispatch_email", return_value=False)
    def test_mail_delivery_failure_is_reported(self, _send_mail):
        response = self._submit_report()

        self.assertEqual(response.status_code, 502)
        self.assertIn("could not send", json.loads(response.content)["detail"])


class ProjectAdminRegistrationTests(TestCase):
    def test_all_project_models_are_registered_in_django_admin(self):
        project_apps = {"ADMIN", "ARCHIVE", "AUTHENTICATION", "BLOG", "HOME", "Partner", "STAFF"}
        unregistered = [
            model._meta.label
            for model in apps.get_models()
            if model._meta.app_label in project_apps and model not in admin.site._registry
        ]

        self.assertEqual(unregistered, [])


class BlogAdminDeleteReleasesImageTests(TestCase):
    """Deleting a story from the hidden Django admin (_admin/) must release its
    uploaded banner from Cloudinary exactly like the profile dashboard does
    (HOME.views.ProfilePublishedDeleteView), so the backdoor cannot orphan it."""

    def setUp(self):
        self.author = Auth.objects.create_user(email="admin-blog-author@example.com")
        self.blog = Blog.objects.create(
            author=self.author,
            heading="Admin deletes me",
            category="GENERAL",
            content="Body.",
            image_1="https://example.com/banner.jpg",
            image_public_id="abureport/news/admin-delete",
        )
        self.model_admin = admin.site._registry[Blog]
        self.request = RequestFactory().get("/_admin/")

    def test_delete_model_releases_the_banner(self):
        with mock.patch("HOME.views.destroy_archive_asset", return_value=True) as destroy_asset:
            self.model_admin.delete_model(self.request, self.blog)
        self.assertFalse(Blog.objects.filter(pk=self.blog.pk).exists())
        destroy_asset.assert_called_once_with("abureport/news/admin-delete", "image")

    def test_delete_queryset_releases_each_banner_once(self):
        Blog.objects.create(
            author=self.author,
            heading="Second admin story",
            category="GENERAL",
            content="Body.",
            image_1="https://example.com/two.jpg",
            image_public_id="abureport/news/admin-delete-two",
        )
        with mock.patch("HOME.views.destroy_archive_asset", return_value=True) as destroy_asset:
            self.model_admin.delete_queryset(self.request, Blog.objects.filter(author=self.author))
        self.assertFalse(Blog.objects.filter(author=self.author).exists())
        self.assertEqual(destroy_asset.call_count, 2)


# ---------------------------------------------------------------------------
# Bug 1 — Exploration test (Task 1)
# ---------------------------------------------------------------------------
# These tests ENCODE THE EXPECTED (FIXED) BEHAVIOUR.
# On UNFIXED code they MUST FAIL — failure proves the bug exists.
# When the fix lands (task 3), these same tests will start passing.
#
# Properties checked:
#   1. cache.get("views:blog:<pk>") is not None and >= 1 after a GET
#      (Redis counter was incremented — expected behaviour after fix)
#   2. No SQL UPDATE statement targeting blog_blog was executed during the GET
#      (DB write on every request — the bug we're removing)
# ---------------------------------------------------------------------------


def _make_staff_with_profile(email="author@explore.com"):
    """Helper: create an Auth (is_staff=True) + matching StaffProfile."""
    author = Auth.objects.create_user(email=email, is_staff=True)
    StaffProfile.objects.create(
        auth=author,
        gender="M",
        full_name="Test Author",
        get_blog_notification=False,
    )
    return author


def _make_blog(author, heading="Exploration test article"):
    return Blog.objects.create(
        author=author,
        category="GENERAL",
        heading=heading,
        content="Content body for the exploration test.",
    )


def _make_anonymous_request(blog_pk):
    from django.contrib.auth.models import AnonymousUser
    from django.contrib.sessions.backends.db import SessionStore

    factory = RequestFactory()
    request = factory.get(f"/story/{blog_pk}/")
    request.META["REMOTE_ADDR"] = "192.0.2.50"
    request.META["HTTP_USER_AGENT"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
    )
    request.user = AnonymousUser()
    request.session = SessionStore()
    return request


class StoryViewDeduplicationTests(TestCase):
    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_same_address_refreshes_are_deduplicated_for_five_seconds(self):
        cache.clear()
        author = _make_staff_with_profile(email="view-dedupe@example.com")
        blog = _make_blog(author, heading="View deduplication story")
        story_url = f"/story/{blog.slug}/"
        browser_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
        )

        first = self.client.get(
            story_url,
            REMOTE_ADDR="192.0.2.10",
            HTTP_USER_AGENT=browser_agent,
        )
        self.assertEqual(first.status_code, 200)
        blog.refresh_from_db()
        self.assertEqual(blog.views, 1)

        accidental_refresh = self.client.get(
            story_url,
            REMOTE_ADDR="192.0.2.10",
            HTTP_USER_AGENT=browser_agent,
        )
        self.assertEqual(accidental_refresh.status_code, 200)
        blog.refresh_from_db()
        self.assertEqual(blog.views, 1)

        different_address = self.client.get(
            story_url,
            REMOTE_ADDR="192.0.2.11",
            HTTP_USER_AGENT=browser_agent,
        )
        self.assertEqual(different_address.status_code, 200)
        blog.refresh_from_db()
        self.assertEqual(blog.views, 2)

        htmx_refresh = self.client.get(
            story_url,
            REMOTE_ADDR="192.0.2.12",
            HTTP_HX_REQUEST="true",
            HTTP_USER_AGENT=browser_agent,
        )
        self.assertEqual(htmx_refresh.status_code, 200)
        blog.refresh_from_db()
        self.assertEqual(blog.views, 2)


class CategoryRecommendationsTests(TestCase):
    def setUp(self):
        self.author = Auth.objects.create_user(email="recommendations@example.com")
        self.current_story = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="Current story",
            content="Current story content.",
        )

    def test_returns_only_three_newest_stories_in_the_current_category(self):
        stories = [
            Blog.objects.create(
                author=self.author,
                category="GENERAL",
                heading=f"Related story {index}",
                content=f"Story {index} first paragraph.\n\nSecond paragraph.",
            )
            for index in range(4)
        ]
        Blog.objects.create(
            author=self.author,
            category="SPORTS",
            heading="Different category story",
            content="This should not be recommended.",
        )

        response = self.client.get(
            reverse("blog:category_recommendations", args=[self.current_story.slug])
        )

        self.assertEqual(response.status_code, 200)
        results = json.loads(response.content)["stories"]
        self.assertEqual(
            [story["slug"] for story in results],
            [story.slug for story in reversed(stories[-3:])],
        )
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["excerpt"], "Story 3 first paragraph.")
        self.assertTrue(all(story["url"].startswith("/story/") for story in results))

    def test_unknown_story_slug_returns_not_found(self):
        response = self.client.get(
            reverse("blog:category_recommendations", args=["missing-story"])
        )
        self.assertEqual(response.status_code, 404)


class StoryDetailRecommendationsMarkupTests(TestCase):
    def test_story_page_renders_the_recommendation_panel_and_script(self):
        author = Auth.objects.create_user(email="story-page@example.com", is_staff=True)
        StaffProfile.objects.create(
            auth=author,
            gender="M",
            full_name="Story Page Author",
            get_blog_notification=False,
        )
        story = Blog.objects.create(
            author=author,
            category="GENERAL",
            heading="Story page recommendation test",
            content="First paragraph.\n\nSecond paragraph.",
        )
        second = Blog.objects.create(
            author=author,
            category="GENERAL",
            heading="Another story from the same author",
            content="Author rail story content.",
            views=30,
        )
        most_viewed = Blog.objects.create(
            author=author,
            category="GENERAL",
            heading="Most viewed author story",
            content="Popular author story content.",
            views=90,
        )
        third = Blog.objects.create(
            author=author,
            category="GENERAL",
            heading="Third author story",
            content="Third author story content.",
            views=20,
        )

        response = self.client.get(reverse("blog:story_detail", args=[story.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-story-body")
        self.assertContains(response, "data-read-also")
        self.assertContains(response, "Read similar stories")
        self.assertContains(response, 'class="read-also-skeleton"')
        self.assertContains(response, "Most recent from Story Page Author")
        self.assertContains(response, "Another story from the same author")
        self.assertContains(response, "Most viewed author story")
        self.assertContains(response, 'class="trending-list author-latest-list"')
        # Resolve through static() so the assertion follows the hashed manifest
        # name that {% static %} prints (the template also appends a ?v= tag).
        from django.templatetags.static import static

        self.assertContains(response, static("blog/js/category-recommendations.js"))
        self.assertContains(response, 'class="story-like-icon"')
        self.assertContains(response, 'aria-label="Like this story"')
        self.assertContains(response, "Like this story")
        content = response.content.decode()
        self.assertLess(content.index('data-story-body'), content.index("First paragraph.</p>"))
        self.assertLess(content.index("First paragraph.</p>"), content.index("<p>Second paragraph.</p>"))
        self.assertLess(content.index("<p>Second paragraph.</p>"), content.index("comments-title"))
        self.assertLess(content.index("comments-title"), content.index('data-read-also'))
        self.assertLess(content.index('data-read-also'), content.index("Most recent from Story Page Author"))
        # The rail is newest first now, so the last-created story leads.
        self.assertLess(content.index("Third author story"), content.index("Most viewed author story"))
        self.assertLess(content.index("Most viewed author story"), content.index("Another story from the same author"))
        self.assertNotIn(story.heading, content[content.index("author-latest-list"):])
        self.assertIn("story-rail-read-also", content)
        self.assertIn("story-rail-author", content)


class StoryHeroImageFallbackTests(TestCase):
    def test_story_without_a_lead_image_uses_the_placeholder(self):
        from django.templatetags.static import static

        author = Auth.objects.create_user(email="hero-fallback@example.com", is_staff=True)
        StaffProfile.objects.create(
            auth=author,
            gender="M",
            full_name="Hero Fallback Author",
            get_blog_notification=False,
        )
        story = Blog.objects.create(
            author=author,
            category="GENERAL",
            heading="Story with no lead image",
            content="Body copy for the hero fallback test.",
        )

        response = self.client.get(reverse("blog:story_detail", args=[story.slug]))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('src="None"', content)
        self.assertIn(
            f'<img src="{static("404.jpg")}" alt="{story.heading}" loading="eager">',
            content,
        )


class Bug1ViewCountUnitExplorationTest(TestCase):
    """View counter updates once, while a same-IP refresh is deduplicated."""

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_same_address_get_increments_database_once(self):
        cache.clear()
        author = _make_staff_with_profile()
        blog = _make_blog(author)
        request = _make_anonymous_request(blog.pk)

        with CaptureQueriesContext(connection) as ctx:
            StoryDetailView.as_view()(request, blog_slug=blog.slug)
            StoryDetailView.as_view()(request, blog_slug=blog.slug)

        update_queries = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].upper().lstrip().startswith("UPDATE") and "blog_blog" in q["sql"].lower()
        ]
        blog.refresh_from_db()
        self.assertEqual(blog.views, 1)
        self.assertEqual(len(update_queries), 1)


class Bug1ViewCountPBTExplorationTest(HypothesisTestCase):
    """View counts remain idempotent for any generated story identifier."""

    # ------------------------------------------------------------------
    # Property 1 (property-based) — holds for arbitrary blog PKs
    # ------------------------------------------------------------------
    @hyp_settings(
        max_examples=5,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(st.integers(min_value=1, max_value=9999))
    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_property_get_increments_once_for_any_blog_pk(self, _seed):
        cache.clear()
        author = _make_staff_with_profile(email=f"pbt_{_seed}@explore.com")
        blog = _make_blog(author, heading=f"PBT exploration article {_seed}")

        request = _make_anonymous_request(blog.pk)

        with CaptureQueriesContext(connection) as ctx:
            StoryDetailView.as_view()(request, blog_slug=blog.slug)

        StoryDetailView.as_view()(request, blog_slug=blog.slug)
        update_queries = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].upper().lstrip().startswith("UPDATE") and "blog_blog" in q["sql"].lower()
        ]
        blog.refresh_from_db()
        self.assertEqual(blog.views, 1)
        self.assertEqual(len(update_queries), 1)


# ---------------------------------------------------------------------------
# Bug 1 — Preservation tests (Task 2)
# ---------------------------------------------------------------------------
# These tests ENCODE THE BASELINE BEHAVIOUR that must never regress.
# They MUST PASS on UNFIXED code (they capture what we preserve).
# When the fix lands (task 3) they must continue to pass.
#
# Properties checked:
#   2a. For any valid Blog PK and any user state (anonymous / authenticated),
#       StoryDetailView.get() returns HTTP 200 and the response context contains
#       all mandatory keys with non-None values:
#         blog, blog_content_html, ticker_text, comments, author_profile
#   2b. For an authenticated request, Blog.non_anonymous_viewer contains the
#       requesting user after the view runs.
#
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------


class Bug1PreservationContextTest(TestCase):
    """
    Unit preservation test — verifies StoryDetailView returns HTTP 200 with
    every mandatory context key present and non-None for a single concrete
    blog / user combination.

    MUST PASS on unfixed code.

    Validates: Requirements 3.1, 3.2
    """

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_anonymous_request_returns_200_with_mandatory_context(self):
        """
        An anonymous GET to StoryDetailView MUST return HTTP 200 and include
        all required context keys with non-None values.
        """
        author = _make_staff_with_profile(email="preserve_anon@example.com")
        blog = _make_blog(author, heading="Preservation anon test article")

        response = self.client.get(f"/story/{blog.slug}/")

        self.assertEqual(response.status_code, 200)

        mandatory_keys = ["blog", "blog_content_html", "ticker_text", "comments", "author_profile"]
        for key in mandatory_keys:
            self.assertIn(
                key,
                response.context,
                msg=f"Mandatory context key '{key}' is missing from StoryDetailView response.",
            )
            self.assertIsNotNone(
                response.context[key],
                msg=f"Mandatory context key '{key}' is None — must be non-None.",
            )

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_authenticated_request_returns_200_with_mandatory_context(self):
        """
        An authenticated GET to StoryDetailView MUST also return HTTP 200 with
        all required context keys present and non-None.
        """
        author = _make_staff_with_profile(email="preserve_auth@example.com")
        blog = _make_blog(author, heading="Preservation auth test article")

        self.client.force_login(author)
        response = self.client.get(f"/story/{blog.slug}/")

        self.assertEqual(response.status_code, 200)

        mandatory_keys = ["blog", "blog_content_html", "ticker_text", "comments", "author_profile"]
        for key in mandatory_keys:
            self.assertIn(
                key,
                response.context,
                msg=f"Mandatory context key '{key}' is missing for authenticated user.",
            )
            self.assertIsNotNone(
                response.context[key],
                msg=f"Mandatory context key '{key}' is None for authenticated user.",
            )

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_authenticated_viewer_tracked_in_non_anonymous_viewer(self):
        """
        After an authenticated GET, the requesting user MUST appear in
        Blog.non_anonymous_viewer (authenticated viewer tracking must not be broken).
        """
        author = _make_staff_with_profile(email="preserve_viewer@example.com")
        blog = _make_blog(author, heading="Preservation viewer tracking article")

        self.client.force_login(author)
        self.client.get(f"/story/{blog.slug}/")

        is_tracked = Blog.non_anonymous_viewer.through.objects.filter(
            blog=blog, auth=author
        ).exists()
        self.assertTrue(
            is_tracked,
            msg=(
                "REGRESSION: after an authenticated GET to StoryDetailView, "
                "the user was NOT added to Blog.non_anonymous_viewer. "
                "This tracking must be preserved by the fix."
            ),
        )


class Bug1PreservationContextPBTTest(HypothesisTestCase):
    """
    Property-based preservation test for Bug 1.

    For arbitrary blog PKs and user states:
      - Response is HTTP 200
      - All mandatory context keys are present and non-None
      - Authenticated viewers are added to Blog.non_anonymous_viewer

    These tests MUST PASS on UNFIXED code, confirming the baseline behaviour
    that the fix in task 3 must not break.

    Validates: Requirements 3.1, 3.2
    """

    # ------------------------------------------------------------------
    # Property 2a — context keys present for any blog PK (anonymous)
    # ------------------------------------------------------------------
    @hyp_settings(
        max_examples=5,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(st.integers(min_value=1, max_value=9999))
    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_property_anonymous_get_returns_200_with_context(self, seed):
        """
        Property 2a (anonymous): for any Blog PK, anonymous GET returns HTTP 200
        and all mandatory context keys are present with non-None values.

        MUST PASS on unfixed code.

        Validates: Requirements 3.1
        """
        author = _make_staff_with_profile(email=f"pbt_preserve_anon_{seed}@example.com")
        blog = _make_blog(author, heading=f"PBT preservation anon article {seed}")

        request = _make_anonymous_request(blog.pk)
        response = StoryDetailView.as_view()(request, blog_slug=blog.slug)

        self.assertEqual(
            response.status_code,
            200,
            msg=f"REGRESSION (seed={seed}, pk={blog.pk}): StoryDetailView returned {response.status_code}, expected 200.",
        )

        # For direct view calls the context lives on response.context_data when
        # using TemplateResponse; use the test client path for context inspection.
        # Re-run via test client to inspect context keys.
        self.client.logout()
        tc_response = self.client.get(f"/story/{blog.slug}/")
        self.assertEqual(tc_response.status_code, 200)

        mandatory_keys = ["blog", "blog_content_html", "ticker_text", "comments", "author_profile"]
        for key in mandatory_keys:
            self.assertIn(
                key,
                tc_response.context,
                msg=f"REGRESSION (seed={seed}): context key '{key}' missing from anonymous response.",
            )
            self.assertIsNotNone(
                tc_response.context[key],
                msg=f"REGRESSION (seed={seed}): context key '{key}' is None for anonymous user.",
            )

    # ------------------------------------------------------------------
    # Property 2b — authenticated viewer tracking preserved for any PK
    # ------------------------------------------------------------------
    @hyp_settings(
        max_examples=5,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
        deadline=None,
    )
    @given(st.integers(min_value=1, max_value=9999))
    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_property_authenticated_viewer_is_tracked(self, seed):
        """
        Property 2b (authenticated): for any Blog PK, after an authenticated
        GET, the requesting user MUST appear in Blog.non_anonymous_viewer.

        MUST PASS on unfixed code.

        Validates: Requirements 3.2
        """
        author = _make_staff_with_profile(email=f"pbt_preserve_auth_{seed}@example.com")
        blog = _make_blog(author, heading=f"PBT preservation auth article {seed}")

        self.client.force_login(author)
        response = self.client.get(f"/story/{blog.slug}/")

        self.assertEqual(
            response.status_code,
            200,
            msg=f"REGRESSION (seed={seed}, pk={blog.pk}): expected 200, got {response.status_code}.",
        )

        is_tracked = Blog.non_anonymous_viewer.through.objects.filter(
            blog=blog, auth=author
        ).exists()
        self.assertTrue(
            is_tracked,
            msg=(
                f"REGRESSION (seed={seed}, pk={blog.pk}): "
                f"authenticated user was NOT added to Blog.non_anonymous_viewer. "
                f"This tracking must survive the Bug 1 fix."
            ),
        )


class BotDetectionTests(TestCase):
    """`is_bot_request` is the only gate keeping crawler/scripted traffic out
    of the story view counter (see BLOG.views.StoryDetailView). These tests
    pin the marker list so a future edit cannot silently let a crawler back
    in, and -- just as important -- cannot start treating a real browser as
    a bot (which would freeze the counter)."""

    @staticmethod
    def _request(user_agent):
        request = RequestFactory().get("/")
        request.META["HTTP_USER_AGENT"] = user_agent
        return request

    def test_crawlers_and_scripted_clients_are_detected(self):
        crawlers = [
            # SemrushBot was already covered; kept to guard the regression.
            "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
            "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
            "Mozilla/5.0 (compatible; Yeti/1.1; +http://naver.me/spd)",
            "Feedly/1.0 (+http://www.feedly.com/fetcher.html)",
            "python-httpx/0.27.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.0.0 Safari/537.36",
            "Pingdom.com_bot_version_1.4",
            "Mozilla/5.0 (compatible; Google-Read-Aloud; +https://support.google.com/webmasters/answer/1061943)",
        ]
        for ua in crawlers:
            with self.subTest(user_agent=ua):
                self.assertTrue(is_bot_request(self._request(ua)), ua)

    def test_missing_user_agent_is_a_bot(self):
        self.assertTrue(is_bot_request(self._request("")))

    def test_real_browser_is_not_a_bot(self):
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.assertFalse(is_bot_request(self._request(ua)))
