from django.test import TestCase
from django.core.cache import cache

from AUTHENTICATION.models import Auth
from BLOG.models import Blog
from HOME.models import Bookmark


class HomePaginationTests(TestCase):
    def setUp(self):
        self.author = Auth.objects.create_user(email="author@example.com")

    def test_home_view_exposes_next_page_metadata(self):
        for i in range(26):
            Blog.objects.create(
                author=self.author,
                category="GENERAL",
                heading=f"Headline {i}",
                content="A short update.",
            )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("next_page" in ctx for ctx in response.context))
        next_page = next(ctx["next_page"] for ctx in response.context if "next_page" in ctx)
        self.assertEqual(next_page, 2)
        self.assertTrue(next(ctx["has_more"] for ctx in response.context if "has_more" in ctx))

    def test_home_view_returns_404_for_missing_page(self):
        for i in range(5):
            Blog.objects.create(
                author=self.author,
                category="GENERAL",
                heading=f"Missing page {i}",
                content="A short update.",
            )

        response = self.client.get("/?page=99")

        self.assertEqual(response.status_code, 404)

    def test_load_more_view_exposes_next_page_metadata(self):
        for i in range(26):
            Blog.objects.create(
                author=self.author,
                category="GENERAL",
                heading=f"More headlines {i}",
                content="A short update.",
            )

        response = self.client.get("/load-more/?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("next_page" in ctx for ctx in response.context))
        next_page = next(ctx["next_page"] for ctx in response.context if "next_page" in ctx)
        self.assertEqual(next_page, 3)
        self.assertTrue(next(ctx["has_more"] for ctx in response.context if "has_more" in ctx))

    def test_load_more_view_returns_404_for_missing_page(self):
        for i in range(5):
            Blog.objects.create(
                author=self.author,
                category="GENERAL",
                heading=f"No page here {i}",
                content="A short update.",
            )

        response = self.client.get("/load-more/?page=99")

        self.assertEqual(response.status_code, 404)


class ProfileAccessTests(TestCase):
    def test_profile_requires_login(self):
        response = self.client.get("/profile/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login/", response.url)

    def test_staff_user_sees_profile_dashboard(self):
        staff_user = Auth.objects.create_staff(email="staff@example.com")
        self.client.force_login(staff_user)

        response = self.client.get("/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Profile")
        self.assertContains(response, "Staff access")

    def test_profile_page_renders_newsletter_toggle_button(self):
        staff_user = Auth.objects.create_staff(email="staff@example.com")
        self.client.force_login(staff_user)

        response = self.client.get("/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-newsletter-toggle")
        self.assertContains(response, "data-enable-url")
        self.assertNotContains(response, "hx-post=")

    def test_staff_profile_renders_delete_control_for_own_story(self):
        staff_user = Auth.objects.create_staff(email="profile-story-owner@example.com")
        blog = Blog.objects.create(
            author=staff_user,
            category="GENERAL",
            heading="Profile story",
            content="A short update.",
        )
        self.client.force_login(staff_user)

        response = self.client.get("/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"/profile/stories/{blog.id}/delete/")
        self.assertContains(response, "data-published-story-delete-form")

    def test_profile_newsletter_toggle_returns_json_response(self):
        user = Auth.objects.create_user(email="newsletter@example.com")
        user.receive_email_login_alert = True
        user.save(update_fields=["receive_email_login_alert"])
        self.client.force_login(user)

        response = self.client.post("/profile/settings/newsletter/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"].split(";")[0], "application/json")
        payload = response.json()
        self.assertIn("detail", payload)
        self.assertIn("enabled", payload)
        self.assertIn("status", payload)

    def test_profile_bookmarks_endpoint_returns_paginated_json(self):
        user = Auth.objects.create_user(email="bookmark@example.com")
        self.client.force_login(user)

        for i in range(12):
            blog = Blog.objects.create(
                author=user,
                category="GENERAL",
                heading=f"Bookmark story {i}",
                content="A short update.",
            )
            user.bookmarks.create(blog=blog)

        response = self.client.get("/profile/bookmarks/?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Content-Type"].split(";")[0], "application/json")
        payload = response.json()
        self.assertEqual(payload["page"], 2)
        self.assertGreaterEqual(payload["num_pages"], 2)
        self.assertEqual(len(payload["items"]), 5)
        self.assertIn("page_range", payload)
        self.assertIn("has_next", payload)

    def test_bookmark_removal_is_limited_to_two_requests_per_ten_seconds(self):
        cache.clear()
        self.addCleanup(cache.clear)
        user = Auth.objects.create_user(email="limited-bookmarks@example.com")
        blog = Blog.objects.create(
            author=user,
            category="GENERAL",
            heading="Bookmark rate limit story",
            content="A short update.",
        )
        self.client.force_login(user)

        for _ in range(2):
            user.bookmarks.create(blog=blog)
            response = self.client.post(f"/bookmark/{blog.id}/")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["bookmarked"])

        user.bookmarks.create(blog=blog)
        response = self.client.post(f"/bookmark/{blog.id}/")

        self.assertEqual(response.status_code, 429)
        self.assertTrue(Bookmark.objects.filter(user=user, blog=blog).exists())

    def test_staff_can_delete_own_published_story(self):
        staff_user = Auth.objects.create_staff(email="story-owner@example.com")
        blog = Blog.objects.create(
            author=staff_user,
            category="GENERAL",
            heading="A story to delete",
            content="A short update.",
        )
        self.client.force_login(staff_user)

        response = self.client.post(f"/profile/stories/{blog.id}/delete/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "Story deleted.")
        self.assertFalse(Blog.objects.filter(pk=blog.pk).exists())

    def test_staff_cannot_delete_another_authors_story(self):
        owner = Auth.objects.create_staff(email="owner@example.com")
        other_staff = Auth.objects.create_staff(email="other-staff@example.com")
        blog = Blog.objects.create(
            author=owner,
            category="GENERAL",
            heading="Protected story",
            content="A short update.",
        )
        self.client.force_login(other_staff)

        response = self.client.post(f"/profile/stories/{blog.id}/delete/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Blog.objects.filter(pk=blog.pk).exists())
