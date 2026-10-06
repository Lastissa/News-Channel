from unittest import mock

from django.test import TestCase
from django.urls import reverse

from AUTHENTICATION.models import Auth
from BLOG.models import Blog
from STAFF.models import StaffProfile


class PortfolioFeedTests(TestCase):
    def setUp(self):
        self.author = Auth.objects.create_user(
            email="portfolio-feed@example.com",
            is_staff=True,
        )
        with mock.patch("AUTHENTICATION.signals._try_send_login_email"):
            self.profile = StaffProfile.objects.create(
                auth=self.author,
                full_name="Portfolio Author",
                gender="O",
            )

        self.stories = [
            Blog.objects.create(
                author=self.author,
                heading=f"Portfolio story {index}",
                category="NEWS",
                content=f"Story content {index}",
            )
            for index in range(7)
        ]

    def test_portfolio_starts_with_feed_and_no_dashboard_sections(self):
        response = self.client.get(reverse("staff:portfolio", args=[self.profile.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Posts by Portfolio Author")
        self.assertContains(response, "portfolio-feed-skeleton")
        self.assertContains(response, "data-next-page=\"2\"")
        self.assertNotContains(response, "Recent story reach")
        self.assertEqual(len(response.context["stories"]), 6)

    def test_feed_endpoint_returns_next_slice_and_pagination_headers(self):
        final_story = self.stories[0]
        final_story.content = "imgc https://example.com/photo.jpg A scenic view\n\nMore story text."
        final_story.save(update_fields=["content"])
        response = self.client.get(
            reverse("staff:portfolio_stories", args=[self.profile.slug]),
            {"page": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portfolio story 0")
        self.assertContains(response, "A scenic view")
        self.assertNotContains(response, "imgc https://example.com/photo.jpg")
        self.assertEqual(response.headers["X-Portfolio-Has-Next"], "false")
        self.assertNotIn("X-Portfolio-Next-Page", response.headers)

    def test_feed_endpoint_rejects_invalid_page(self):
        response = self.client.get(
            reverse("staff:portfolio_stories", args=[self.profile.slug]),
            {"page": "invalid"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"detail": "Invalid story page."})
