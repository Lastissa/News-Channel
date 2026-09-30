"""PANEL "News categories" card (ADMIN.views.PanelCategory*View).

Runs on an isolated cache (see BLOG/tests_categories.py for why) and with the
per IP rate limiter switched off, since it allows only 3 requests per 10
seconds and these tests post far more than that.
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, Category, get_category_choices

ISOLATED_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "panel-category-tests",
    }
}

ORIGINAL_COUNT = 10


@override_settings(CACHES=ISOLATED_CACHE)
class PanelCategoryTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        for target, value in [
            ("AUTHENTICATION.signals._try_send_login_email", None),
            ("ADMIN.views.is_rate_limited", (0, False)),
        ]:
            patcher = mock.patch(target, return_value=value) if value is not None else mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.admin = Auth.objects.create_admin(email="admin@example.com")
        self.superuser = Auth.objects.create_superuser(email="root@example.com")
        self.writer = Auth.objects.create_staff(email="writer@example.com")   #   plain staff: NOT admin
        self.member = Auth.objects.create_user(email="member@example.com")

        self.create_url = reverse("control:panel_category_create")

    def delete_url(self, category_id):
        return reverse("control:panel_category_delete", args=[category_id])

    def add(self, name):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.create_url, {"name": name})

    def story(self, category, heading):
        return Blog.objects.create(
            author=self.writer, heading=heading, category=category, content="Body.", image_1="https://example.com/a.jpg"
        )

    #   ------------------------------------------------------------ create
    def test_admin_and_superuser_can_add_a_category(self):
        for user, name in [(self.admin, "sports"), (self.superuser, "study abroad")]:
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.add(name)
                self.assertEqual(response.status_code, 201)
                stored = name.upper()
                self.assertTrue(Category.objects.filter(name=stored).exists())
                self.assertEqual(response.json()["category"]["name"], stored)
                self.assertEqual(response.json()["category"]["label"], name.title())
                self.assertEqual(response.json()["category"]["story_count"], 0)
                #   reached the cache that feeds the menu and the story form
                self.assertIn((stored, stored), get_category_choices())

    def test_re_adding_a_retired_category_reports_the_stories_still_under_it(self):
        self.client.force_login(self.admin)
        self.story("SECURITY", "Old one")      #   SECURITY was never in the table: a retired category
        self.story("SECURITY", "Older one")
        response = self.add("security")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["category"]["story_count"], 2)
        self.assertIn("2 existing stories show under it again", response.json()["detail"])

    def test_anonymous_writers_and_members_cannot_add(self):
        for user in [None, self.writer, self.member]:
            with self.subTest(user=getattr(user, "email", "anonymous")):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                response = self.add("hackers")
                self.assertEqual(response.status_code, 403)
                self.assertFalse(Category.objects.filter(name="HACKERS").exists())

    def test_add_is_refused_when_rate_limited(self):
        self.client.force_login(self.admin)
        with mock.patch("ADMIN.views.is_rate_limited", return_value=(7, True)):
            response = self.add("sports")
        self.assertEqual(response.status_code, 403)
        self.assertIn("Wait 7 seconds", response.json()["detail"])
        self.assertFalse(Category.objects.filter(name="SPORTS").exists())

    def test_bad_names_are_refused_with_a_reason(self):
        self.client.force_login(self.admin)
        cases = {
            "": "Enter a category name.",
            "   ": "Enter a category name.",
            "sport&news": "letters, numbers",
            "a" * 21: "at most 20 characters",
            "jamb": "already exists",        #   same as JAMB, whatever the case
            "  Jamb  ": "already exists",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                response = self.add(name)
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, response.json()["detail"])
        self.assertEqual(Category.objects.count(), ORIGINAL_COUNT)

    def test_two_admins_adding_the_same_name_at_once_gets_a_clean_400(self):
        self.client.force_login(self.admin)
        #   skip the validation pre check so the database constraint is what catches it
        with mock.patch.object(Category, "full_clean"):
            response = self.add("neco")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "That category already exists.")
        self.assertEqual(Category.objects.count(), ORIGINAL_COUNT)

    #   ------------------------------------------------------------ delete
    def test_admin_can_remove_a_category_and_its_stories_stay_published(self):
        self.client.force_login(self.admin)
        self.story("NECO", "First neco story")
        self.story("NECO", "Second neco story")
        get_category_choices()   #   prime the cache with NECO still in it
        neco = Category.objects.get(name="NECO")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.delete_url(neco.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["story_count"], 2)
        self.assertIn("2 existing stories stay published", response.json()["detail"])
        self.assertFalse(Category.objects.filter(name="NECO").exists())
        self.assertEqual(Blog.objects.filter(category="NECO").count(), 2)   #   untouched
        self.assertNotIn(("NECO", "NECO"), get_category_choices())          #   gone from menu + story form

    def test_superuser_can_remove_a_category_with_no_stories(self):
        self.client.force_login(self.superuser)
        waec = Category.objects.get(name="WAEC")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.delete_url(waec.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "Waec removed.")

    def test_anonymous_writers_and_members_cannot_remove(self):
        neco = Category.objects.get(name="NECO")
        for user in [None, self.writer, self.member]:
            with self.subTest(user=getattr(user, "email", "anonymous")):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                self.assertEqual(self.client.post(self.delete_url(neco.id)).status_code, 403)
                self.assertTrue(Category.objects.filter(pk=neco.pk).exists())

    def test_remove_is_refused_when_rate_limited(self):
        self.client.force_login(self.admin)
        neco = Category.objects.get(name="NECO")
        with mock.patch("ADMIN.views.is_rate_limited", return_value=(4, True)):
            response = self.client.post(self.delete_url(neco.id))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Category.objects.filter(pk=neco.pk).exists())

    def test_removing_an_unknown_category_is_a_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.delete_url(999999)).status_code, 404)

    def test_the_last_category_cannot_be_removed(self):
        self.client.force_login(self.admin)
        Category.objects.exclude(name="GENERAL").delete()
        last = Category.objects.get()
        response = self.client.post(self.delete_url(last.id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("At least one category", response.json()["detail"])
        self.assertTrue(Category.objects.filter(pk=last.pk).exists())

    #   ------------------------------------------------------------ the card itself
    def test_panel_page_lists_categories_with_story_counts(self):
        self.client.force_login(self.admin)
        self.story("GENERAL", "One")
        self.story("GENERAL", "Two")
        self.story("JAMB", "Three")

        response = self.client.get(reverse("control:panel"))

        self.assertEqual(response.status_code, 200)
        rows = {row["name"]: row for row in response.context["category_rows"]}
        self.assertEqual(len(rows), ORIGINAL_COUNT)
        self.assertEqual(rows["GENERAL"]["story_count"], 2)
        self.assertEqual(rows["JAMB"]["story_count"], 1)
        self.assertEqual(rows["WAEC"]["story_count"], 0)
        self.assertContains(response, "News categories")
        self.assertContains(response, "2 stories")
        self.assertContains(response, "1 story")
        self.assertContains(response, f"{ORIGINAL_COUNT} active")

    def test_panel_page_is_not_shown_to_plain_staff(self):
        self.client.force_login(self.writer)
        response = self.client.get(reverse("control:panel"))
        self.assertRedirects(response, reverse("home:profile"), fetch_redirect_response=False)
