from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, StoryView
from HOME.author_analytics import build_author_analytics
from HOME.models import ReadingHistory
from Partner.models import AdvertEvent, AdvertImage, AdvertReference
from SERVICE_INTERNAL.analytics_buffer import (
    buffer_advert_event,
    buffer_story_view,
    flush_pending_events,
    pending_advert_event_counts,
    pending_advert_events,
    pending_story_views,
)
from SERVICE_INTERNAL.traffic import (
    SOURCE_FACEBOOK,
    SOURCE_GOOGLE,
    SOURCE_GOOGLE_NAME,
    SOURCE_GOOGLE_NAME_ABUREPORT,
    SOURCE_WHATSAPP,
    classify_request_source,
    tag_internal_url,
)
from STAFF.models import StaffProfile


class QuietAnalyticsTests(TestCase):
    """force_login sends a real login email through a signal; tests stub it."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        patcher = mock.patch("AUTHENTICATION.signals._try_send_login_email")
        patcher.start()
        self.addCleanup(patcher.stop)


def make_author(email, full_name, **flags):
    user = Auth.objects.create_user(email=email, **flags)
    StaffProfile.objects.create(
        auth=user,
        gender="M",
        full_name=full_name,
        get_blog_notification=False,
    )
    return user


def make_story(author, heading):
    return Blog.objects.create(
        author=author,
        heading=heading,
        category="GENERAL",
        content="A short test report with enough detail for the parser.",
        image_1="https://example.com/test.jpg",
        image_info="Test caption.",
    )


class TrafficSourceTests(TestCase):
    def test_google_query_with_full_name_and_abureport_gets_its_own_key(self):
        request = RequestFactory().get(
            "/", HTTP_REFERER="https://www.google.com/search?q=Ada%20Bello%20abureport"
        )

        self.assertEqual(
            classify_request_source(request, "  Ada   Bello "),
            SOURCE_GOOGLE_NAME_ABUREPORT,
        )

    def test_google_query_with_full_name_only_gets_the_name_key(self):
        request = RequestFactory().get(
            "/", HTTP_REFERER="https://www.google.com/search?q=Ada+Bello"
        )

        self.assertEqual(classify_request_source(request, "Ada Bello"), SOURCE_GOOGLE_NAME)

    def test_google_without_a_query_stays_plain_google(self):
        request = RequestFactory().get("/", HTTP_REFERER="https://news.google.com/")

        self.assertEqual(classify_request_source(request, "Ada Bello"), SOURCE_GOOGLE)

    def test_referrer_wins_over_utm_source(self):
        request = RequestFactory().get(
            "/",
            {"utm_source": "google"},
            HTTP_HOST="abureport.com.ng",
            HTTP_REFERER="https://www.facebook.com/story.php",
        )

        self.assertEqual(classify_request_source(request), SOURCE_FACEBOOK)

    def test_utm_is_only_a_fallback(self):
        factory = RequestFactory()
        self.assertEqual(
            classify_request_source(factory.get("/", {"utm_source": "abureport"})),
            "abureport",
        )
        self.assertEqual(
            classify_request_source(factory.get("/", {"utm_source": "whatsapp"})),
            SOURCE_WHATSAPP,
        )
        self.assertEqual(classify_request_source(factory.get("/")), "direct")

    def test_unknown_referrer_falls_back_to_utm(self):
        request = RequestFactory().get(
            "/",
            {"utm_source": "whatsapp"},
            HTTP_REFERER="https://news.example.net/story",
        )

        self.assertEqual(classify_request_source(request), SOURCE_WHATSAPP)

    def test_whatsapp_short_link_referrer_is_whatsapp(self):
        request = RequestFactory().get("/", HTTP_REFERER="https://wa.me/2348012345678")

        self.assertEqual(classify_request_source(request), SOURCE_WHATSAPP)

    def test_tagging_generated_links_preserves_other_query_parts(self):
        self.assertEqual(
            tag_internal_url("/story/one/?utm_medium=email#top"),
            "/story/one/?utm_medium=email&utm_source=abureport#top",
        )
        self.assertEqual(
            tag_internal_url("https://abureport.com.ng/story/two/"),
            "https://abureport.com.ng/story/two/?utm_source=abureport",
        )
        tagged = "https://example.com/story/?utm_source=partner"
        self.assertEqual(tag_internal_url(tagged), tagged)


class AnalyticsBufferTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.author = make_author("buffer@example.com", "Buffer Author", is_staff=True)
        self.story = make_story(self.author, "Buffered story")

    def test_health_flushes_story_views_without_changing_its_response(self):
        moment = timezone.now() - timedelta(days=2)
        buffer_story_view(
            self.story.pk,
            self.author.pk,
            SOURCE_GOOGLE_NAME_ABUREPORT,
            occurred_at=moment,
        )
        self.assertEqual(len(pending_story_views()), 1)
        self.assertEqual(StoryView.objects.count(), 0)

        response = self.client.get("/health", HTTP_CF_CONNECTING_IP="102.89.3.3")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"message": "success", "ip": "102.89.3.3"}
        )
        row = StoryView.objects.get()
        self.assertEqual(row.source, SOURCE_GOOGLE_NAME_ABUREPORT)
        self.assertEqual(row.user_id, self.author.pk)
        self.assertLess(abs((row.created_at - moment).total_seconds()), 2)
        self.assertEqual(pending_story_views(), [])

    def test_health_keeps_its_response_with_a_non_form_post_body(self):
        response = self.client.post(
            "/health", data="not-a-form-body", content_type="text/plain"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {"message", "ip"})
        self.assertEqual(payload["message"], "success")

    def test_pending_advert_counts_include_cache_only_events(self):
        buffer_advert_event(11, "view", "google")
        buffer_advert_event(11, "click", "abureport")
        buffer_advert_event(12, "click", "facebook")

        counts = pending_advert_event_counts([11, 12])

        self.assertEqual(counts["11"]["view"], 1)
        self.assertEqual(counts["11"]["click"], 1)
        self.assertEqual(counts["11"]["abureport_click"], 1)
        self.assertEqual(counts["12"]["other_click"], 1)

    def test_a_failed_write_keeps_the_event_for_the_next_probe(self):
        buffer_story_view(self.story.pk, None, SOURCE_FACEBOOK)

        with mock.patch(
            "BLOG.models.StoryView.objects.create",
            side_effect=RuntimeError("database busy"),
        ):
            result = flush_pending_events()

        self.assertEqual(result["story_views"], 0)
        self.assertFalse(result["flushed"])
        self.assertEqual(len(pending_story_views()), 1)
        self.assertEqual(StoryView.objects.count(), 0)

        response = self.client.get("/health")

        self.assertEqual(response.json()["message"], "success")
        self.assertEqual(StoryView.objects.get().source, SOURCE_FACEBOOK)
        self.assertEqual(pending_story_views(), [])

    def test_a_failed_timestamp_update_rolls_back_the_created_row(self):
        buffer_story_view(self.story.pk, None, SOURCE_FACEBOOK)

        with mock.patch(
            "SERVICE_INTERNAL.analytics_buffer._as_datetime",
            side_effect=RuntimeError("bad timestamp"),
        ):
            result = flush_pending_events()

        self.assertEqual(result["story_views"], 0)
        self.assertFalse(result["flushed"])
        self.assertEqual(len(pending_story_views()), 1)
        self.assertEqual(StoryView.objects.count(), 0)

    def test_reference_advert_events_flush_and_unreferenced_rows_are_dropped(self):
        admin = make_author("buffer-ads@example.com", "Ads Author", is_admin=True)
        advert = AdvertImage.objects.create(
            author=admin,
            expiry_date=timezone.now(),
            heading="Buffered advert",
            image_url="https://example.com/banner.jpg",
            url="https://example.com",
        )
        reference = AdvertReference.objects.create(
            user=self.author,
            plan="pro",
            business_name="Buffered Shop",
            advert=advert,
        )
        buffer_advert_event(reference.pk, AdvertEvent.EVENT_VIEW, "google")
        buffer_advert_event(99999, AdvertEvent.EVENT_VIEW, SOURCE_FACEBOOK)

        result = flush_pending_events()

        self.assertEqual(result["advert_events"], 1)
        self.assertTrue(result["flushed"])
        self.assertEqual(AdvertEvent.objects.get().reference_id, reference.pk)
        self.assertEqual(pending_advert_events(), [])


class AuthorAnalyticsTests(QuietAnalyticsTests):
    def setUp(self):
        super().setUp()
        self.author = make_author("ada@example.com", "Ada Bello", is_staff=True)
        self.other = make_author("bola@example.com", "Bola Okafor", is_staff=True)
        self.story = make_story(self.author, "Ada story")
        self.other_story = make_story(self.other, "Bola story")

        google_view = StoryView.objects.create(
            blog=self.story, source=SOURCE_GOOGLE_NAME_ABUREPORT
        )
        StoryView.objects.filter(pk=google_view.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        old_view = StoryView.objects.create(blog=self.story, source="other")
        StoryView.objects.filter(pk=old_view.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )
        StoryView.objects.create(blog=self.other_story, source=SOURCE_GOOGLE)
        buffer_story_view(self.story.pk, None, SOURCE_FACEBOOK)

    def test_views_sources_and_story_urls_are_scoped_to_the_selected_author(self):
        context = build_author_analytics(self.author, "30")

        self.assertEqual(context["author_name"], "Ada Bello")
        self.assertEqual(context["kpis"]["views"], 2)
        self.assertEqual(context["story_table"][0]["views"], 2)
        self.assertIn("utm_source=abureport", context["story_table"][0]["url"])

        sources = {row["key"]: row["count"] for row in context["source_rows"]}
        self.assertEqual(sources[SOURCE_GOOGLE_NAME_ABUREPORT], 1)
        self.assertEqual(sources[SOURCE_FACEBOOK], 1)
        self.assertEqual(sources[SOURCE_GOOGLE], 0)
        self.assertEqual(sources["other"], 0)

        google_rows = {row["key"]: row["count"] for row in context["google_rows"]}
        self.assertEqual(google_rows[SOURCE_GOOGLE_NAME], 0)
        self.assertEqual(google_rows[SOURCE_GOOGLE_NAME_ABUREPORT], 1)

        ranks = {row["label"]: row for row in context["ranks"]}
        self.assertEqual(ranks["Views received"]["position"], 1)
        self.assertEqual(ranks["Views received"]["total"], 2)

    def test_range_change_filters_database_and_pending_rows_together(self):
        narrow = build_author_analytics(self.author, "7")
        wide = build_author_analytics(self.author, "90")

        self.assertEqual(narrow["kpis"]["views"], 2)
        self.assertEqual(wide["kpis"]["views"], 3)

        StoryView.objects.filter(blog=self.story).update(
            created_at=timezone.now() - timedelta(days=20)
        )
        self.assertEqual(build_author_analytics(self.author, "7")["kpis"]["views"], 1)
        self.assertEqual(build_author_analytics(self.author, "90")["kpis"]["views"], 3)

    def test_reads_rank_uses_this_author_as_a_reader(self):
        ReadingHistory.objects.create(user=self.other, blog=self.story)

        context = build_author_analytics(self.other, "30")
        ranks = {row["label"]: row for row in context["ranks"]}

        self.assertEqual(ranks["Stories read"]["value"], 1)
        self.assertEqual(ranks["Stories read"]["position"], 1)


class ProfileAnalyticsViewTests(QuietAnalyticsTests):
    def setUp(self):
        super().setUp()
        self.author = make_author("view-ada@example.com", "View Ada", is_staff=True)
        self.other = make_author("view-bola@example.com", "View Bola", is_staff=True)
        self.url = reverse("home:profile_analytics")

    def test_htmx_returns_only_the_panel_and_full_get_returns_a_page(self):
        make_story(self.author, "Panel story")
        self.client.force_login(self.author)

        panel = self.client.get(self.url, HTTP_HX_REQUEST="true")
        full = self.client.get(self.url)

        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "Author analytics")
        self.assertContains(panel, 'data-profile-analytics')
        self.assertNotContains(panel, "<html")
        self.assertEqual(full.status_code, 200)
        self.assertContains(full, "Author analytics")
        self.assertContains(full, "<html")

    def test_admin_picker_is_kept_in_the_session_and_ignored_for_authors(self):
        admin = make_author(
            "view-admin@example.com", "View Admin", is_staff=True, is_admin=True
        )
        self.client.force_login(admin)

        picked = self.client.get(
            self.url,
            {"author": self.other.pk},
            HTTP_HX_REQUEST="true",
        )
        remembered = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertContains(picked, "Viewing View Bola")
        self.assertContains(remembered, "Viewing View Bola")
        self.assertContains(remembered, 'name="author"')

        self.client.logout()
        self.client.force_login(self.author)
        ignored = self.client.get(
            self.url,
            {"author": self.other.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(ignored, "Viewing View Ada")
        self.assertNotContains(ignored, 'name="author"')


class AdvertAnalyticsPendingTests(QuietAnalyticsTests):
    def setUp(self):
        super().setUp()
        self.owner = Auth.objects.create_user(email="pending-ads@example.com")
        self.admin = make_author(
            "pending-admin@example.com", "Pending Admin", is_superuser=True
        )
        advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now(),
            heading="Pending advert",
            image_url="https://example.com/pending.jpg",
            url="https://example.com",
        )
        self.reference = AdvertReference.objects.create(
            user=self.owner,
            plan="pro",
            business_name="Pending Shop",
            advert=advert,
        )
        buffer_advert_event(
            self.reference.pk, AdvertEvent.EVENT_VIEW, "google", occurred_at=timezone.now()
        )
        buffer_advert_event(
            self.reference.pk,
            AdvertEvent.EVENT_CLICK,
            "abureport",
            occurred_at=timezone.now(),
        )

    def test_advertiser_dashboard_counts_events_still_waiting_in_cache(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("home:advertise_dashboard_analytics"))

        self.assertEqual(response.status_code, 200)
        totals = response.context["analytics"]["totals"]
        self.assertEqual(totals["views"], 1)
        self.assertEqual(totals["clicks"], 1)
        self.assertEqual(totals["abureport_clicks"], 1)
        self.assertEqual(AdvertEvent.objects.count(), 0)

    def test_ads_desk_modal_counts_events_still_waiting_in_cache(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("control:advert_analytics_modal", args=[self.reference.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["analytics"]["totals"]["views"], 1)
        self.assertEqual(response.context["analytics"]["totals"]["clicks"], 1)


class EditorAssetTests(QuietAnalyticsTests):
    def _static_source(self, relative_path):
        path = Path(settings.BASE_DIR) / relative_path
        return path.read_text(encoding="utf-8")

    def test_add_page_has_clear_button_and_keeps_only_one_file_loader(self):
        self.client.force_login(
            make_author("editor-add@example.com", "Add Author", is_staff=True)
        )

        html = self.client.get(reverse("home:add_news")).content.decode()

        self.assertEqual(html.count("data-clear-writeup-btn"), 1)
        self.assertEqual(html.count("data-load-news-btn"), 1)
        self.assertEqual(html.count("data-load-news-input"), 1)
        self.assertIn(static("blog/css/story-detail.css"), html)
        self.assertIn(
            static("home/js/editor-clear-writeup.js") + "?v=20261127-01", html
        )

    def test_edit_page_has_revert_button(self):
        author = make_author("editor-edit@example.com", "Edit Author", is_staff=True)
        story = make_story(author, "Editable story")
        self.client.force_login(author)

        html = self.client.get(reverse("home:edit_news", args=[story.pk])).content.decode()

        self.assertIn("data-clear-writeup-btn", html)
        self.assertIn("Revert all changes to the published story", html)
        self.assertIn(static("blog/css/story-detail.css"), html)
        self.assertIn(
            static("home/js/editor-clear-writeup.js") + "?v=20261127-01", html
        )

    def test_editor_scripts_declare_the_two_step_confirmation_and_honest_preview(self):
        confirmation = self._static_source(
            "HOME/static/home/js/editor-clear-writeup.js"
        )
        add_script = self._static_source("HOME/static/home/js/add-news-editor.js")
        edit_script = self._static_source("HOME/static/home/js/edit-news-editor.js")

        self.assertIn("CALM DOWN AND READ IT PROPERLY", confirmation)
        self.assertIn("COUNTDOWN_MS = 1500", confirmation)
        self.assertIn("clearWriteup", add_script)
        self.assertIn("DEFAULT_CATEGORY", add_script)
        self.assertIn("Word count", add_script)
        self.assertIn("PUBLISHED_VALUES", edit_script)
        self.assertIn("revertToPublished", edit_script)
        self.assertIn("Word count", edit_script)
        for script in (add_script, edit_script):
            self.assertIn("editor-preview-frame", script)
            self.assertIn("story-hero-figure", script)
            self.assertIn("author-card", script)
