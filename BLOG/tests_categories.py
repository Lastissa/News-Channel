"""Category model + its no-TTL cache (BLOG.models, BLOG.signals).

Every class here runs on its OWN isolated cache. TestCase rolls the database
back after each test but nothing rolls a cache back, so a category cached by
one test would otherwise leak into every test that runs after it.

TestCase never really commits, so the on_commit refresh only fires inside
`self.captureOnCommitCallbacks(execute=True)`, which is what stands in for
"the request finished and the transaction committed".
"""
import itertools
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from AUTHENTICATION.models import Auth
from BLOG import models as blog_models
from BLOG.models import CATEGORY_CACHE_KEY, Blog, Category, get_category_choices, refresh_category_cache
from SERVICE_INTERNAL.config import custom_context_processors
from STAFF.models import StaffProfile

ISOLATED_CACHE = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "blog-category-tests",
    }
}

ORIGINAL_CATEGORIES = [
    "UNIVERSITY", "POLYTECHNIC", "ORGANIZATION", "JAMB", "WAEC",
    "NECO", "POSTUTME", "SCHOLARSHIP", "TECHNOLOGY", "GENERAL",
]
ORIGINAL_CHOICES = [(name, name) for name in ORIGINAL_CATEGORIES]

_MISS = object()
_counter = itertools.count(1)


@override_settings(CACHES=ISOLATED_CACHE)
class CategoryCacheTestCase(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def add_category(self, name):
        with self.captureOnCommitCallbacks(execute=True):
            return Category.objects.create(name=name)


class CategoryModelTests(CategoryCacheTestCase):
    def test_original_ten_categories_are_seeded_in_their_old_order(self):
        self.assertEqual(list(Category.objects.values_list("name", flat=True)), ORIGINAL_CATEGORIES)

    def test_name_is_saved_in_capitals_with_single_spaces(self):
        category = Category.objects.create(name="  study    abroad ")
        self.assertEqual(category.name, "STUDY ABROAD")

    def test_same_name_in_any_case_is_refused_by_validation(self):
        with self.assertRaisesMessage(ValidationError, "That category already exists."):
            Category(name="jamb").full_clean()

    def test_same_name_in_any_case_is_refused_by_the_database_too(self):
        #   bulk_create skips save(), so this reaches the constraint with the lowercase name intact
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.bulk_create([Category(name="jamb")])

    def test_bad_names_are_rejected(self):
        for bad in ["", "SPORT&NEWS", "-SPORTS", "SPORTS-", "TWO  SPACES", "A" * 21, "NEWS/ONE", "<B>"]:
            with self.subTest(name=bad), self.assertRaises(ValidationError):
                Category(name=bad).full_clean()

    def test_good_names_pass_validation(self):
        for good in ["SPORTS", "study abroad", "COVID-19", "2027 JAMB", "A" * 20]:
            with self.subTest(name=good):
                Category(name=good).full_clean()


class CategoryCacheTests(CategoryCacheTestCase):
    def test_first_read_uses_one_query_then_nothing(self):
        with self.assertNumQueries(1):
            first = get_category_choices()
        with self.assertNumQueries(0):
            second = get_category_choices()
        self.assertEqual(first, ORIGINAL_CHOICES)
        self.assertEqual(second, ORIGINAL_CHOICES)

    def test_cached_entry_never_expires(self):
        refresh_category_cache()
        ten_years = 10 * 365 * 24 * 3600
        with mock.patch("time.time", return_value=__import__("time").time() + ten_years):
            self.assertEqual(cache.get(CATEGORY_CACHE_KEY, _MISS), ORIGINAL_CHOICES)

    def test_adding_a_category_replaces_the_cached_list(self):
        get_category_choices()   #   prime the cache with the old list
        self.add_category("sports")
        with self.assertNumQueries(0):   #   already rebuilt, this read is a pure cache hit
            self.assertEqual(get_category_choices(), ORIGINAL_CHOICES + [("SPORTS", "SPORTS")])

    def test_removing_a_category_replaces_the_cached_list(self):
        get_category_choices()
        with self.captureOnCommitCallbacks(execute=True):
            Category.objects.get(name="NECO").delete()
        with self.assertNumQueries(0):
            self.assertEqual(get_category_choices(), [c for c in ORIGINAL_CHOICES if c[0] != "NECO"])

    def test_editing_a_category_replaces_the_cached_list(self):
        get_category_choices()
        category = Category.objects.get(name="GENERAL")
        category.name = "everything else"
        with self.captureOnCommitCallbacks(execute=True):
            category.save()
        with self.assertNumQueries(0):
            self.assertIn(("EVERYTHING ELSE", "EVERYTHING ELSE"), get_category_choices())
        self.assertNotIn(("GENERAL", "GENERAL"), get_category_choices())

    def test_queryset_delete_also_refreshes(self):
        get_category_choices()
        with self.captureOnCommitCallbacks(execute=True):
            Category.objects.filter(name__in=["WAEC", "NECO"]).delete()
        self.assertEqual(
            get_category_choices(),
            [c for c in ORIGINAL_CHOICES if c[0] not in {"WAEC", "NECO"}],
        )

    def test_a_rolled_back_change_never_reaches_the_cache(self):
        get_category_choices()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                Category.objects.create(name="ghost")
                raise RuntimeError("rolled back")
        self.assertEqual(callbacks, [])
        self.assertEqual(get_category_choices(), ORIGINAL_CHOICES)

    def test_an_empty_table_is_cached_as_empty_not_treated_as_a_miss(self):
        with self.captureOnCommitCallbacks(execute=True):
            Category.objects.all().delete()
        with self.assertNumQueries(0):
            self.assertEqual(get_category_choices(), [])
        self.assertEqual(cache.get(CATEGORY_CACHE_KEY, _MISS), [])

    def test_a_database_failure_returns_nothing_and_caches_nothing(self):
        with mock.patch.object(blog_models, "_load_category_choices", side_effect=OperationalError("no such table")):
            self.assertEqual(get_category_choices(), [])
        self.assertIs(cache.get(CATEGORY_CACHE_KEY, _MISS), _MISS)   #   the failure was NOT remembered
        self.assertEqual(get_category_choices(), ORIGINAL_CHOICES)   #   and the next call recovers

    def test_a_foreign_value_under_the_key_is_healed(self):
        for junk in ["garbage", {"a": 1}, [("ONE",)], [("A", "B", "C")], ["JAMB"], None]:
            with self.subTest(junk=junk):
                cache.set(CATEGORY_CACHE_KEY, junk, timeout=None)
                self.assertEqual(get_category_choices(), ORIGINAL_CHOICES)
                self.assertEqual(cache.get(CATEGORY_CACHE_KEY, _MISS), ORIGINAL_CHOICES)


class BlogUsesTheLiveCategoriesTests(CategoryCacheTestCase):
    def test_field_choices_follow_the_table(self):
        field = Blog._meta.get_field("category")
        self.assertEqual(list(field.choices), ORIGINAL_CHOICES)
        self.add_category("sports")
        self.assertIn(("SPORTS", "SPORTS"), list(field.choices))

    def test_field_validation_accepts_a_new_category_and_refuses_an_unknown_one(self):
        field = Blog._meta.get_field("category")
        with self.assertRaises(ValidationError):
            field.validate("SPORTS", None)
        self.add_category("sports")
        field.validate("SPORTS", None)

    def test_display_is_the_stored_value_and_never_reads_the_cache(self):
        with mock.patch.object(blog_models, "get_category_choices", side_effect=AssertionError("cache read")):
            self.assertEqual(Blog(category="JAMB").get_category_display(), "JAMB")
            #   a retired category (not in the table) shows exactly as before
            self.assertEqual(Blog(category="SECURITY").get_category_display(), "SECURITY")

    def test_navbar_context_comes_from_the_cache_and_follows_changes(self):
        request = RequestFactory().get("/")
        self.assertEqual(custom_context_processors(request)["nav_categories"], ORIGINAL_CHOICES)
        self.add_category("sports")
        self.assertEqual(custom_context_processors(request)["nav_categories"], ORIGINAL_CHOICES + [("SPORTS", "SPORTS")])


@mock.patch("HOME.views.ping_indexnow")
class StoryFormFollowsCategoriesTests(CategoryCacheTestCase):
    """The story form validates against the live list (HOME.views.AddNewsView)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch("AUTHENTICATION.signals._try_send_login_email")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.author = Auth.objects.create_user(email="writer@example.com", is_staff=True)
        StaffProfile.objects.create(auth=self.author, gender="M", full_name="Test Writer", get_blog_notification=False)
        self.client.force_login(self.author)

    def publish(self, category):
        return self.client.post(
            reverse("home:add_news"),
            {"heading": f"Heading {next(_counter)}", "category": category, "content": "Body text of the story."},
        )

    def test_a_category_added_in_panel_can_be_published_into(self, _ping):
        self.assertEqual(self.publish("SPORTS").status_code, 400)
        self.add_category("sports")
        response = self.publish("SPORTS")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Blog.objects.get(pk=response.json()["id"]).category, "SPORTS")

    def test_a_removed_category_can_no_longer_be_published_into(self, _ping):
        self.assertEqual(self.publish("NECO").status_code, 201)
        with self.captureOnCommitCallbacks(execute=True):
            Category.objects.get(name="NECO").delete()
        response = self.publish("NECO")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Select a valid category.")
        #   the story published before the removal is untouched
        self.assertEqual(Blog.objects.filter(category="NECO").count(), 1)

    def test_home_menu_lists_a_new_category_only_after_it_is_added(self, _ping):
        self.assertNotContains(self.client.get(reverse("home:home")), "?category=SPORTS")
        self.add_category("sports")
        self.assertContains(self.client.get(reverse("home:home")), "?category=SPORTS")
