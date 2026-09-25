import json

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext

from hypothesis import given, settings as hyp_settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, Comment
from BLOG.views import parse_story_content, StoryDetailView
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

        response = self.client.get(f"/story/{blog.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Views")
        self.assertContains(response, "Word count")
        self.assertContains(response, "Campus gate during screening.")

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

    def test_blog_like_is_unique_per_user(self):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="Daily news update",
            content="A short update.",
        )
        self.client.force_login(self.author)

        first = self.client.post(f"/story/{blog.id}/like/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        second = self.client.post(f"/story/{blog.id}/like/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(json.loads(first.content)["likes"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(json.loads(second.content)["likes"], 1)
        self.assertEqual(json.loads(second.content)["detail"], "You already liked this story.")

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
    request.user = AnonymousUser()
    request.session = SessionStore()
    return request


class Bug1ViewCountUnitExplorationTest(TestCase):
    """
    Unit-level exploration test for Bug 1 (View Count DB Write).

    On UNFIXED code this test is EXPECTED TO FAIL, confirming:
      - cache.get("views:blog:<pk>") returns None  (no Redis counter set)
      - An UPDATE against blog_blog fires on every GET

    Validates: Requirements 1.1, 1.2
    """

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
        DEBUG=True,
    )
    def test_single_get_increments_redis_counter_not_db(self):
        """
        After one anonymous GET to StoryDetailView:
          ASSERT cache.get("views:blog:<pk>") is not None and >= 1
          ASSERT no UPDATE query against blog_blog was issued

        On UNFIXED code:
          • cache.get() returns None  → assertion fails (BUG CONFIRMED)
          • An UPDATE query IS present → assertion fails (BUG CONFIRMED)
        """
        cache.clear()
        author = _make_staff_with_profile()
        blog = _make_blog(author)

        request = _make_anonymous_request(blog.pk)

        # Capture all DB queries during the view call
        with CaptureQueriesContext(connection) as ctx:
            StoryDetailView.as_view()(request, blog_slug=blog.slug)

        # --- Assertion 1: Redis counter was set ---
        redis_key = f"views:blog:{blog.pk}"
        counter_value = cache.get(redis_key)
        self.assertIsNotNone(
            counter_value,
            msg=(
                f"BUG CONFIRMED (counter): cache.get('{redis_key}') returned None. "
                f"No Redis counter was incremented — the view is writing directly to the DB instead."
            ),
        )
        self.assertGreaterEqual(
            counter_value,
            1,
            msg=f"BUG CONFIRMED (counter value): expected >= 1 but got {counter_value}",
        )

        # --- Assertion 2: no SQL UPDATE against blog_blog ---
        # Use startswith to avoid matching SELECT queries that contain
        # "update" as a substring in column names (e.g. "last_updated").
        update_queries = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].upper().lstrip().startswith("UPDATE") and "blog_blog" in q["sql"].lower()
        ]
        self.assertEqual(
            len(update_queries),
            0,
            msg=(
                f"BUG CONFIRMED (db-write): {len(update_queries)} UPDATE query/queries fired "
                f"against blog_blog during a single page-view request. "
                f"Queries: {update_queries}"
            ),
        )


class Bug1ViewCountPBTExplorationTest(HypothesisTestCase):
    """
    Property-based exploration test for Bug 1 (View Count DB Write).

    On UNFIXED code this test is EXPECTED TO FAIL, generating counterexamples
    that prove the bug: every GET fires a SQL UPDATE against blog_blog and
    sets no Redis counter.

    Validates: Requirements 1.1, 2.1
    """

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
    def test_property_get_increments_redis_not_db_for_any_blog_pk(self, _seed):
        """
        Property: for any valid Blog PK, a GET to StoryDetailView
          SHALL increment a Redis counter (cache key "views:blog:<pk>") by 1
          and SHALL NOT fire a SQL UPDATE against blog_blog.

        On UNFIXED code both sub-assertions will fail, proving the bug.

        Validates: Requirements 1.1, 2.1
        """
        cache.clear()
        author = _make_staff_with_profile(email=f"pbt_{_seed}@explore.com")
        blog = _make_blog(author, heading=f"PBT exploration article {_seed}")

        request = _make_anonymous_request(blog.pk)

        with CaptureQueriesContext(connection) as ctx:
            StoryDetailView.as_view()(request, blog_slug=blog.slug)

        redis_key = f"views:blog:{blog.pk}"
        counter_value = cache.get(redis_key)

        # Assertion A — Redis counter present
        self.assertIsNotNone(
            counter_value,
            msg=(
                f"COUNTEREXAMPLE (seed={_seed}, blog_pk={blog.pk}): "
                f"cache.get('{redis_key}') is None — no Redis increment happened."
            ),
        )

        # Assertion B — No DB UPDATE for views
        # Use startswith to avoid matching SELECT queries that contain
        # "update" as a substring in column names (e.g. "last_updated").
        update_queries = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].upper().lstrip().startswith("UPDATE") and "blog_blog" in q["sql"].lower()
        ]
        self.assertEqual(
            len(update_queries),
            0,
            msg=(
                f"COUNTEREXAMPLE (seed={_seed}, blog_pk={blog.pk}): "
                f"SQL UPDATE fired during GET: {update_queries}"
            ),
        )


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
