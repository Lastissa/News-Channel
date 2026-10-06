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
                views=index * 10,
            )
            for index in range(7)
        ]

    def test_portfolio_starts_with_feed_and_no_dashboard_sections(self):
        response = self.client.get(reverse("staff:portfolio", args=[self.profile.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Posts by Portfolio Author")
        self.assertContains(response, "portfolio-feed-skeleton")
        self.assertContains(response, "data-next-page=\"2\"")
        self.assertContains(response, "portfolio-feed.js?v=20261006-3")
        self.assertNotContains(response, "Recent story reach")
        self.assertEqual(len(response.context["stories"]), 6)
        self.assertEqual(
            [story.heading for story in response.context["top_viewed_stories"]],
            ["Portfolio story 6", "Portfolio story 5", "Portfolio story 4"],
        )
        content = response.content.decode()
        rail_start = content.index('class="portfolio-popular-rail"')
        feed_start = content.index('id="portfolio-feed"')
        self.assertGreater(rail_start, feed_start)
        self.assertLess(
            content.index("Portfolio story 6", rail_start),
            content.index("Portfolio story 5", rail_start),
        )
        self.assertLess(
            content.index("Portfolio story 5", rail_start),
            content.index("Portfolio story 4", rail_start),
        )

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


class EditorialTeamPageTests(TestCase):
    def setUp(self):
        self.author = Auth.objects.create_user(
            email="editorial-author@example.com",
            is_staff=True,
            profile_img="https://example.com/editor.jpg",
        )
        self.profile = StaffProfile.objects.create(
            auth=self.author,
            full_name="Editorial Author",
            gender="O",
            role="JOURNALIST",
            bio="Reports on the stories that matter.",
            speciality=["Education"],
        )
        self.author_stories = [
            Blog.objects.create(
                author=self.author,
                heading=f"Editorial story {index}",
                category="NEWS",
                content=f"Story content {index}",
                views=index * 10,
            )
            for index in range(2)
        ]
        self.author_stories[-1].image_1 = "https://example.com/story-preview.jpg"
        self.author_stories[-1].save(update_fields=["image_1"])
        self.staff_without_profile = Auth.objects.create_user(
            email="new-editor@example.com",
            is_staff=True,
        )
        self.inactive_author = Auth.objects.create_user(
            email="inactive-editor@example.com",
            is_staff=True,
            is_active=False,
        )
        self.reader = Auth.objects.create_user(email="reader@example.com")

    def test_editorial_page_shows_all_active_staff_and_real_story_data(self):
        Blog.objects.create(
            author=self.reader,
            heading="Community report",
            category="NEWS",
            content="A report published by a non-staff author.",
        )
        response = self.client.get(reverse("editorial_team"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Meet our")
        self.assertContains(response, "editorial team.")
        self.assertContains(response, "Editorial Author")
        self.assertContains(response, "New-Editor")
        self.assertContains(response, "Editorial story 1")
        self.assertContains(response, 'class="editorial-latest"')
        self.assertContains(response, "story-preview.jpg")
        self.assertContains(response, 'class="editorial-output"')
        self.assertContains(response, 'class="editorial-grid"')
        self.assertEqual(response.content.decode().count('data-count-up="2"'), 1)
        self.assertContains(response, 'data-count-up="3"')
        self.assertContains(response, 'data-journalist-search')
        self.assertContains(response, 'data-search-clear')
        self.assertContains(response, 'data-search-status')
        self.assertContains(response, 'data-search-empty')
        self.assertContains(response, 'class="editorial-stat-icon"')
        self.assertContains(response, 'class="editorial-spotlight-scene"')
        self.assertContains(response, 'class="editorial-spotlight-profile"')
        self.assertContains(response, "editorial_team.css?v=20261006-2")
        self.assertContains(response, "editorial-motion.js?v=20261006-2")
        self.assertContains(response, "editorial-motion.js")
        self.assertNotContains(response, "editorial-role-group")
        self.assertNotContains(response, "editorial-role-chip")
        self.assertNotContains(response, "Journalist")
        self.assertContains(response, 'href="/editorial/"')
        self.assertNotContains(response, "inactive-editor")
        self.assertNotContains(response, "reader@example")
        self.assertEqual(response.context["team_size"], 2)
        self.assertEqual(response.context["total_stories"], 3)
        self.assertEqual(response.context["highlight"]["display_name"], "Editorial Author")
        self.assertEqual(
            response.context["highlight"]["latest_story"].heading,
            "Editorial story 1",
        )

        members = response.context["members"]
        self.assertEqual(len(members), 2)
        self.assertEqual(
            [member["display_name"] for member in members],
            sorted(member["display_name"] for member in members),
        )
        member_by_name = {member["display_name"]: member for member in members}
        self.assertEqual(member_by_name["Editorial Author"]["story_count"], 2)
        self.assertEqual(member_by_name["Editorial Author"]["total_views"], 10)
        self.assertEqual(member_by_name["New-Editor"]["story_count"], 0)
        self.assertIsNone(member_by_name["New-Editor"]["latest_story"])

    def test_editorial_links_are_available_in_navigation_and_footer(self):
        response = self.client.get(reverse("editorial_team"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, 'href="/editorial/"')
