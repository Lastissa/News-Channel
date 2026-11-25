"""PANEL "News categories" card (ADMIN.views.PanelCategory*View).

Runs on an isolated cache (see BLOG/tests_categories.py for why) and with the
per IP rate limiter switched off, since it allows only 3 requests per 10
seconds and these tests post far more than that.
"""
from unittest import mock

import io
import json
import re
import zipfile
import threading
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.core import signing
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.http import HttpResponse
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ADMIN.analytics import (
    NO_CATEGORY_KEY,
    _week_start,
    daily_story_activity,
    member_new_today,
    member_overview,
)
from ADMIN.models import SiteSettings
from ADMIN.views import (
    ADVERT_STORAGE_LINK_SALT,
    _advert_storage_display_name,
    _advert_storage_share_urls,
)
from AUTHENTICATION.models import Auth
from BLOG.models import Blog, BlogLike, Category, Comment, StoryView, get_category_choices
from HOME.models import CategorySubscription, ReadingHistory
from Partner.models import (
    AdvertEvent,
    AdvertImage,
    AdvertLandingPage,
    AdvertLead,
    AdvertPage,
    AdvertReference,
    AdvertReferenceFile,
)
from SERVICE_INTERNAL import email_single
from SERVICE_INTERNAL.config import About
from STAFF.models import AuthorFollow, StaffProfile

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
        self.assertContains(response, f">{ORIGINAL_COUNT}<")

    def test_panel_page_is_not_shown_to_plain_staff(self):
        self.client.force_login(self.writer)
        response = self.client.get(reverse("control:panel"))
        self.assertRedirects(response, reverse("home:profile"), fetch_redirect_response=False)


class _MainThreadSendMock(mock.Mock):
    """A resend mock that ignores work drained from the background mail pool.

    Other tests queue welcome/batch emails on a module-level executor. Those
    jobs can finish while a StaffMailTests assertion is running; counting them
    would make an unrelated background send look like this class's direct mail.
    """

    def __call__(self, *args, **kwargs):
        if threading.current_thread() is not threading.main_thread():
            return None
        return super().__call__(*args, **kwargs)


@override_settings(CACHES=ISOLATED_CACHE)
class StaffMailTests(TestCase):
    """The "Send mail" box on each staff detail page (ADMIN.views.StaffMailSendView).

    resend.Emails.send is replaced by a mock in every test: nothing here can
    reach the real mail service."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        for target, kwargs in [
            ("AUTHENTICATION.signals._try_send_login_email", {}),
            #   Welcome emails from earlier tests run on this shared pool. Keeping
            #   the pool mocked stops them from landing in this class's direct
            #   resend.Emails.send mock and inflating its call count.
            ("SERVICE_INTERNAL.email_single._EMAIL_EXECUTOR", {}),
            #   Batch mail keeps its own imported reference to the same pool.
            ("SERVICE_INTERNAL.email_batch._EMAIL_EXECUTOR", {}),
            ("ADMIN.views.is_rate_limited", {"return_value": (0, False)}),
        ]:
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.send = _MainThreadSendMock()
        patcher = mock.patch("resend.Emails.send", new=self.send)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.admin = self.make("admin@example.com", Auth.objects.create_admin, "Ada Admin")
        self.superuser = self.make("root@example.com", Auth.objects.create_superuser, "Root Owner")
        self.writer = self.make("writer@example.com", Auth.objects.create_staff, "Wale Writer")
        self.other_writer = self.make("other@example.com", Auth.objects.create_staff, "Other Writer")
        self.member = Auth.objects.create_user(email="member@example.com")
        self.url = reverse("control:staff_mail", args=[self.writer.pk])

    @staticmethod
    def make(email, factory, full_name):
        user = factory(email=email)
        if full_name:
            StaffProfile.objects.create(auth=user, gender="M", full_name=full_name, get_blog_notification=False)
        return user

    def mail(self, subject="Hello there", body="A short message.", url=None, **extra):
        return self.client.post(url or self.url, {"subject": subject, "body": body, **extra})

    def params(self):
        self.assertEqual(self.send.call_count, 1)
        return self.send.call_args[0][0]

    #   ------------------------------------------------------------ who can send, and to whom
    def test_admin_and_superuser_send_to_the_staff_member_whose_page_it_is(self):
        for sender, sender_name in [(self.admin, "Ada Admin"), (self.superuser, "Root Owner")]:
            with self.subTest(sender=sender.email):
                self.send.reset_mock()
                self.client.force_login(sender)
                response = self.mail("Meeting moved", "See you at ten.")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["detail"], "Email sent to Wale Writer.")
                params = self.params()
                self.assertEqual(params["to"], [self.writer.email])
                self.assertTrue(params["from"].startswith(f"{sender_name} <"), params["from"])
                self.assertEqual(params["subject"], "Meeting moved")
                self.assertIn("See you at ten.", params["html"])

    def test_the_recipient_only_ever_comes_from_the_url(self):
        self.client.force_login(self.admin)
        response = self.mail(
            to=self.other_writer.email, email=self.other_writer.email, recipient=self.other_writer.email,
            staff_id=self.other_writer.pk, extra_account_ids=str(self.other_writer.pk),
            include_member="on", include_staff="on", include_admin="on",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.params()["to"], [self.writer.email])   #   exactly one call, exactly one address

    def test_anonymous_writers_and_members_cannot_send(self):
        for user in [None, self.writer, self.other_writer, self.member]:
            with self.subTest(user=getattr(user, "email", "anonymous")):
                self.client.logout()
                if user:
                    self.client.force_login(user)
                self.assertEqual(self.mail().status_code, 403)
        self.send.assert_not_called()

    def test_unknown_and_non_staff_accounts_are_a_404(self):
        self.client.force_login(self.admin)
        for staff_id in [999999, self.member.pk]:
            with self.subTest(staff_id=staff_id):
                self.assertEqual(self.mail(url=reverse("control:staff_mail", args=[staff_id])).status_code, 404)
        self.send.assert_not_called()

    def test_a_non_admin_cannot_tell_which_staff_ids_exist(self):
        self.client.force_login(self.writer)
        real = self.mail()
        missing = self.mail(url=reverse("control:staff_mail", args=[999999]))
        self.assertEqual((real.status_code, missing.status_code), (403, 403))

    def test_send_is_refused_when_rate_limited(self):
        self.client.force_login(self.admin)
        with mock.patch("ADMIN.views.is_rate_limited", return_value=(9, True)):
            response = self.mail()
        self.assertEqual(response.status_code, 403)
        self.assertIn("Wait 9 seconds", response.json()["detail"])
        self.send.assert_not_called()

    def test_get_is_not_allowed(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_a_staff_member_with_no_profile_can_still_be_mailed(self):
        bare = Auth.objects.create_staff(email="bare@example.com")
        self.client.force_login(self.admin)
        response = self.mail(url=reverse("control:staff_mail", args=[bare.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "Email sent to this staff member.")
        self.assertEqual(self.params()["to"], [bare.email])

    #   ------------------------------------------------------------ the sending admin
    def test_an_admin_with_no_full_name_cannot_send(self):
        no_name = self.make("noname@example.com", Auth.objects.create_admin, "")
        blank = self.make("blank@example.com", Auth.objects.create_admin, "   ")
        for admin in [no_name, blank]:
            with self.subTest(admin=admin.email):
                self.client.force_login(admin)
                response = self.mail()
                self.assertEqual(response.status_code, 409)
                self.assertIn("no full name", response.json()["detail"])
        self.send.assert_not_called()

    def test_a_display_name_cannot_break_the_from_header(self):
        StaffProfile.objects.filter(auth=self.admin).update(full_name='Ada <evil@x.com> "Admin"')
        self.client.force_login(self.admin)
        self.assertEqual(self.mail().status_code, 200)
        sender = self.params()["from"]
        self.assertEqual(sender.count("<"), 1)          #   only the real address bracket
        self.assertTrue(sender.startswith("Ada evil@x.com Admin <"), sender)

    #   ------------------------------------------------------------ what was typed
    def test_typed_html_never_reaches_the_email_as_markup(self):
        self.client.force_login(self.admin)
        self.mail("<script>alert(1)</script>", "<b>bold</b> & <img src=x onerror=alert(1)>")
        html = self.params()["html"]
        for live_markup in ["<script", "<b>bold", "<img"]:
            self.assertNotIn(live_markup, html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt; &amp; &lt;img", html)

    def test_line_breaks_become_paragraphs(self):
        self.client.force_login(self.admin)
        self.mail(body="Line one\n\nLine two\nstill two")
        html = self.params()["html"]
        self.assertIn("<p>Line one</p>", html)
        self.assertIn("Line two<br>still two", html)

    def test_the_subject_is_flattened_to_one_line(self):
        self.client.force_login(self.admin)
        self.mail(subject="Hello\r\nBcc: someone@else.com\n  again")
        self.assertEqual(self.params()["subject"], "Hello Bcc: someone@else.com again")

    def test_empty_and_oversized_fields_are_refused_with_a_reason(self):
        self.client.force_login(self.admin)
        cases = [
            ({"subject": "", "body": "x"}, "Enter an email heading."),
            ({"subject": "   ", "body": "x"}, "Enter an email heading."),
            ({"subject": "x" * 151, "body": "x"}, "limited to 150"),
            ({"subject": "x", "body": ""}, "Enter the email body."),
            ({"subject": "x", "body": " \n "}, "Enter the email body."),
            ({"subject": "x", "body": "x" * 5001}, "limited to 5000"),
        ]
        for fields, expected in cases:
            with self.subTest(fields={k: v[:12] for k, v in fields.items()}):
                response = self.client.post(self.url, fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, response.json()["detail"])
        self.send.assert_not_called()

    def test_the_limits_themselves_are_accepted(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.mail("x" * 150, "y" * 5000).status_code, 200)

    #   ------------------------------------------------------------ failure
    def test_a_failed_send_is_reported_not_swallowed(self):
        self.client.force_login(self.admin)
        self.send.side_effect = Exception("mail service down")
        response = self.mail()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "The email could not be sent. Try again shortly.")

    #   ------------------------------------------------------------ the page
    def test_the_staff_page_shows_the_box_to_admins_and_points_it_at_that_staff_member(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("control:staff_detail", args=[self.writer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-mail-block")
        self.assertContains(response, f'data-mail-endpoint="/control/staff/{self.writer.pk}/mail/"')
        self.assertNotContains(response, "before you can send email")

    def test_the_box_is_locked_and_explained_when_the_admin_has_no_full_name(self):
        no_name = self.make("noname@example.com", Auth.objects.create_admin, "")
        self.client.force_login(no_name)
        response = self.client.get(reverse("control:staff_detail", args=[self.writer.pk]))
        self.assertContains(response, "before you can send email")
        html = response.content.decode()
        send_button = html[html.index("data-mail-send"):][:120]
        self.assertIn("disabled", send_button)

    def test_plain_staff_never_see_the_staff_page_or_the_box(self):
        self.client.force_login(self.writer)
        response = self.client.get(reverse("control:staff_detail", args=[self.other_writer.pk]))
        self.assertRedirects(response, reverse("home:profile"), fetch_redirect_response=False)


class DispatcherStillBehavesForExistingSendersTests(TestCase):
    """_dispatch_email gained an optional sender name and a return value. Every
    other email in the project (login alert, password reset, welcome, ...) uses
    it the old way, fire and forget, and must not change."""

    def test_the_background_path_still_uses_the_project_name_and_returns_nothing(self):
        with mock.patch("resend.Emails.send") as send, mock.patch.object(email_single, "_EMAIL_EXECUTOR") as executor:
            result = email_single._dispatch_email("someone@example.com", "Subject", "<p>hi</p>")
            self.assertIsNone(result)
            executor.submit.assert_called_once()
            send.assert_not_called()                      #   queued, not sent inline
            executor.submit.call_args[0][0]()             #   run what was queued
        params = send.call_args[0][0]
        self.assertTrue(params["from"].startswith(f"{About.project_name} <"), params["from"])
        self.assertEqual(params["to"], ["someone@example.com"])

    def test_the_inline_path_reports_success_and_failure(self):
        with mock.patch("resend.Emails.send") as send:
            self.assertTrue(email_single._dispatch_email("a@example.com", "S", "<p>x</p>", no_async=True))
            send.side_effect = Exception("down")
            self.assertFalse(email_single._dispatch_email("a@example.com", "S", "<p>x</p>", no_async=True))


def _chart_data(test, response, element_id):
    """Pull the JSON payload back out of a chart fragment's json_script tag."""
    match = re.search(
        r'<script id="%s" type="application/json">(.*?)</script>' % element_id,
        response.content.decode(),
        re.S,
    )
    if not match:
        test.fail(f"no {element_id} payload in the fragment")
    return json.loads(match.group(1))


class AnalyticsPageTests(TestCase):
    """ANALYTICS shell + its two htmx chart fragments (ADMIN.views.Analytics*).

    The shell must carry the controls and NO numbers; every figure arrives from
    a separate GET fragment. These tests pin that split down.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="analytics-admin@example.com")
        self.writer = Auth.objects.create_staff(email="analytics-writer@example.com")
        self.member = Auth.objects.create_user(email="analytics-member@example.com")

        self.page_url = reverse("control:analytics")
        self.stories_url = reverse("control:analytics_stories")
        self.trends_url = reverse("control:analytics_trends")

    def make_story(self, heading):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        #   date_created is auto_now_add, so pin it into the window by hand.
        Blog.objects.filter(pk=story.pk).update(date_created=timezone.now())
        return story

    #   ------------------------------------------------------------ access
    def test_only_admins_and_superusers_can_open_the_page(self):
        self.assertEqual(self.client.get(self.page_url).status_code, 302)   # anonymous
        for user in [self.writer, self.member]:
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.page_url).status_code, 302)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.page_url).status_code, 200)

    def test_both_fragments_are_admin_only(self):
        for url in [self.stories_url, self.trends_url]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.force_login(self.writer)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.logout()

    #   ------------------------------------------------------------ shell
    def test_shell_carries_the_controls_but_no_chart_data(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.page_url).content.decode()
        self.assertIn("analytics-growth-body", body)
        self.assertIn("analytics/members-growth/", body)
        #   Trends was removed from Member lytics: it duplicated the story
        #   chamber's event chart and told an admin nothing about people.
        self.assertNotIn("analytics-trends-body", body)
        self.assertNotIn("analytics/trends/", body)
        #   prove the figures come over htmx: no baked-in payload in the shell
        self.assertNotIn("analytics-trends-data", body)
        self.assertNotIn("analytics-members-growth-data", body)
        #   stories and reading have moved to Story lytics
        self.assertNotIn("analytics-stories-body", body)
        self.assertNotIn("analytics-reading-body", body)

    def test_shell_carries_the_how_it_works_guide(self):
        #   The info button and one guide step per section, in DOM order.
        self.client.force_login(self.admin)
        body = self.client.get(self.page_url).content.decode()
        self.assertIn("data-guide-open", body)
        self.assertIn("data-guide-body", body)
        for title in ["Quick overview", "Members over time", "Members"]:
            with self.subTest(title=title):
                self.assertIn('data-guide-title="%s"' % title, body)

    #   ------------------------------------------------------------ which series
    def test_member_lytics_no_longer_offers_the_story_open_series(self):
        #   Story views live on the Story lytics page now, so Member lytics
        #   does not offer them at all.
        self.client.force_login(self.admin)
        body = self.client.get(self.page_url).content.decode()
        self.assertNotIn('name="series" value="views"', body)

    def test_story_lytics_still_offers_the_story_open_series(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn('name="series" value="views"', body)

    #   ------------------------------------------------------------ buckets
    def test_the_finest_buckets_are_offered_on_every_lytics_page(self):
        self.client.force_login(self.admin)
        for url in [self.page_url, reverse("control:story_lytics")]:
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                self.assertIn('value="hour"', body)
                self.assertIn('value="12hour"', body)

    def test_an_hourly_bucket_is_drawn(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.trends_url, {"bucket": "hour", "range": "24h"}),
            "analytics-trends-data",
        )
        self.assertEqual(chart["bucket"], "hour")
        #   A day of hours, not a month of them.
        self.assertLessEqual(len(chart["labels"]), 26)
        self.assertTrue(all(":" in label for label in chart["labels"]))

    def test_a_twelve_hour_bucket_is_drawn(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.trends_url, {"bucket": "12hour", "range": "72h"}),
            "analytics-trends-data",
        )
        self.assertEqual(chart["bucket"], "12hour")
        self.assertLessEqual(len(chart["labels"]), 8)
        self.assertTrue(all("am" in label or "pm" in label for label in chart["labels"]))

    #   ------------------------------------------------------------ stories bar
    def test_stories_fragment_returns_a_week_bar_chart(self):
        self.client.force_login(self.admin)
        self.make_story("Analytics story one")
        self.make_story("Analytics story two")

        chart = _chart_data(self, self.client.get(self.stories_url, {"period": "1m"}), "analytics-stories-data")
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(len(chart["labels"]), 4)                       # one month => four weeks
        self.assertEqual(sum(chart["series"][0]["values"]), 2)

    def test_a_longer_period_returns_more_week_bars(self):
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.stories_url, {"period": "1y"}), "analytics-stories-data")
        self.assertEqual(len(chart["labels"]), 52)

    def test_an_unknown_period_falls_back_to_one_month(self):
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.stories_url, {"period": "banana"}), "analytics-stories-data")
        self.assertEqual(len(chart["labels"]), 4)

    #   ------------------------------------------------------------ trends line
    def test_first_load_shows_every_member_series(self):
        #   Member lytics is about people, so the story-open series is not
        #   drawn here: it lives on the Story lytics page instead.
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.trends_url), "analytics-trends-data")
        self.assertEqual(chart["type"], "line")
        self.assertEqual([s["key"] for s in chart["series"]], ["users", "stories", "likes"])

    def test_the_story_open_series_is_still_available_when_asked_for(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.trends_url, {"submitted": "1", "series": ["views"]}),
            "analytics-trends-data",
        )
        self.assertEqual([s["key"] for s in chart["series"]], ["views"])

    def test_only_the_ticked_boxes_are_plotted(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            self.trends_url,
            {"submitted": "1", "bucket": "week", "range": "90d", "series": ["likes", "users"]},
        )
        chart = _chart_data(self, response, "analytics-trends-data")
        #   order follows the fixed legend order, not the query order
        self.assertEqual([s["key"] for s in chart["series"]], ["users", "likes"])
        self.assertEqual(chart["bucket"], "week")
        self.assertEqual(chart["range"], "90d")

    def test_clearing_every_box_draws_an_empty_chart(self):
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.trends_url, {"submitted": "1"}), "analytics-trends-data")
        self.assertEqual(chart["series"], [])

    def test_the_new_users_series_counts_the_accounts_in_the_window(self):
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.trends_url, {"submitted": "1", "series": ["users"]}), "analytics-trends-data")
        self.assertEqual(chart["series"][0]["key"], "users")
        #   setUp made three accounts, all indexed "now" and so inside the window
        self.assertGreaterEqual(sum(chart["series"][0]["values"]), 3)

    def test_the_likes_series_reads_blog_likes_not_the_cached_counter(self):
        self.client.force_login(self.admin)
        story = self.make_story("A liked story")
        BlogLike.objects.create(blog=story, user=self.member)
        response = self.client.get(self.trends_url, {"submitted": "1", "bucket": "day", "range": "30d", "series": ["likes"]})
        chart = _chart_data(self, response, "analytics-trends-data")
        self.assertEqual(sum(chart["series"][0]["values"]), 1)

    def test_a_custom_range_overrides_the_range_preset(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        start = (today - timedelta(days=3)).isoformat()
        end = today.isoformat()
        chart = _chart_data(
            self,
            self.client.get(
                self.trends_url,
                {"submitted": "1", "series": ["users"], "bucket": "day", "range": "30d", "start": start, "end": end},
            ),
            "analytics-trends-data",
        )
        #   three days back through today inclusive => four daily buckets
        self.assertEqual(len(chart["labels"]), 4)

    def test_an_invalid_custom_range_falls_back_to_the_preset(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        chart = _chart_data(
            self,
            self.client.get(
                self.trends_url,
                {
                    "submitted": "1", "series": ["users"], "bucket": "day", "range": "7d",
                    "start": today.isoformat(), "end": (today - timedelta(days=3)).isoformat(),
                },
            ),
            "analytics-trends-data",
        )
        self.assertEqual(len(chart["labels"]), 7)

    def test_the_month_bucket_builds_calendar_month_labels(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.trends_url, {"submitted": "1", "series": ["users"], "bucket": "month", "range": "1y"}),
            "analytics-trends-data",
        )
        self.assertGreaterEqual(len(chart["labels"]), 12)
        for label in chart["labels"]:
            self.assertRegex(label, r"^[A-Z][a-z]{2} \d{4}$")

    #   ------------------------------------------------------------ week stories endpoint
    def test_week_stories_requires_admin(self):
        url = reverse("control:member_week_stories")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_week_stories_rejects_bad_missing_or_future_week(self):
        url = reverse("control:member_week_stories")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 400)  # missing
        self.assertEqual(self.client.get(url, {"week": "not-a-date"}).status_code, 400)  # bad
        # future week should be rejected
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=14)).isoformat()
        self.assertEqual(self.client.get(url, {"week": future}).status_code, 400)

    def test_week_stories_returns_fragment_with_story_and_author_button(self):
        url = reverse("control:member_week_stories")
        self.client.force_login(self.admin)
        from django.utils import timezone
        from datetime import timedelta
        from ADMIN.analytics import _week_start
        # create story this week
        story = self.make_story("Week story one")
        # get this week's Sunday
        week_start = _week_start(timezone.localtime(story.date_created))
        resp = self.client.get(url, {"week": week_start.date().isoformat()})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Week story one", body)
        # the author name is a link into the Author lytics chamber
        self.assertIn(reverse("control:author_lytics"), body)
        self.assertIn("analytics-week-author", body)

    def test_week_stories_wednesday_and_sunday_return_same_fragment(self):
        url = reverse("control:member_week_stories")
        self.client.force_login(self.admin)
        from django.utils import timezone
        from ADMIN.analytics import _week_start
        from datetime import timedelta
        story = self.make_story("Week identity")
        ws = _week_start(timezone.localtime(story.date_created))
        wed = ws + timedelta(days=3)
        r_sun = self.client.get(url, {"week": ws.date().isoformat()})
        r_wed = self.client.get(url, {"week": wed.date().isoformat()})
        self.assertEqual(r_sun.content, r_wed.content)

    def test_stories_per_week_bucket_starts_matches_labels(self):
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.stories_url, {"period": "1m"}), "analytics-stories-data")
        self.assertEqual(chart["type"], "bar")
        self.assertIn("bucket_starts", chart)
        self.assertEqual(len(chart["bucket_starts"]), len(chart["labels"]))


class StoryViewHistoryTests(TransactionTestCase):
    """Every counted story open leaves a timestamped StoryView row: the source
    the ANALYTICS "total views" series reads.

    The migration that creates the table is the owner's to run, so until it is
    applied this class builds the table in the (throwaway) test database itself
    and drops it again. Once the migration exists the table is already there and
    neither hook does anything. TransactionTestCase, not TestCase: SQLite refuses
    to create a foreign-key table from inside the class-wide atomic a TestCase
    opens, and this DDL has to run outside one.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._added_table = StoryView._meta.db_table not in connections["default"].introspection.table_names()
        if cls._added_table:
            with connections["default"].schema_editor() as editor:
                editor.create_model(StoryView)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_added_table", False):
            with connections["default"].schema_editor() as editor:
                editor.delete_model(StoryView)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.author = Auth.objects.create_staff(email="view-history@example.com")
        StaffProfile.objects.create(
            auth=self.author, gender="M", full_name="View History Author", get_blog_notification=False
        )

    def test_a_counted_open_writes_a_history_row(self):
        story = Blog.objects.create(
            author=self.author, heading="View history story", category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        response = self.client.get(
            f"/story/{story.slug}/",
            REMOTE_ADDR="192.0.2.30",
            HTTP_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
        )
        story.refresh_from_db()
        #   the counter and the timestamped row are written in the same branch,
        #   so they must always agree
        self.assertEqual(response.status_code, 200)
        self.assertEqual(story.views, 1)
        self.assertEqual(StoryView.objects.filter(blog=story).count(), 1)

    def test_a_deduplicated_refresh_does_not_add_a_second_row(self):
        story = Blog.objects.create(
            author=self.author, heading="Deduplicated view story", category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        kwargs = {
            "REMOTE_ADDR": "192.0.2.31",
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
        }
        self.client.get(f"/story/{story.slug}/", **kwargs)
        self.client.get(f"/story/{story.slug}/", **kwargs)
        self.assertEqual(StoryView.objects.filter(blog=story).count(), 1)

    def test_deleting_a_viewers_account_keeps_the_view_history(self):
        """A served view is never taken back. Deleting the reader's account
        nulls the user FK (SET_NULL) but leaves the StoryView row in place, so
        the ANALYTICS "total views" count can never shrink."""
        viewer = Auth.objects.create_user(email="viewer-to-delete@example.com", password="pw123456")
        story = Blog.objects.create(
            author=self.author, heading="View history survives the reader", category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        StoryView.objects.create(blog=story, user=viewer)

        viewer.delete()

        rows = StoryView.objects.filter(blog=story)
        self.assertEqual(rows.count(), 1)
        self.assertIsNone(rows.first().user)


class AdminPageRedirectTests(TestCase):
    """A control page an admin cannot open must send an anonymous visitor
    through the login screen carrying the page they wanted. That way the
    inactivity logout followed by a fresh sign-in returns them to the PANEL
    instead of dropping them on the profile."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.member = Auth.objects.create_user(email="redirect-member@example.com")

    def test_anonymous_visitors_are_sent_to_login_with_the_target(self):
        for name in ["control:panel", "control:analytics"]:
            with self.subTest(name=name):
                target = reverse(name)
                response = self.client.get(target)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    response.url,
                    f"{reverse('auth:login')}?{urlencode({'to': target})}",
                )

    def test_signed_in_non_admins_still_go_to_the_profile(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("control:panel"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("home:profile"))


@override_settings(CACHES=ISOLATED_CACHE)
class AnalyticsMembersTests(TestCase):
    """The ANALYTICS "Members" table fragment (ADMIN.views.AnalyticsMembersView).

    Members only, read only, and every filter is pinned: account status, the
    news-alert flag, the category preference, reading activity and the
    "newsletter sign-up" account type (recognised by an empty last_login).
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(cache.clear)

        #   A real category has to exist for the category filter to have any
        #   values; clear the cache afterwards so the first read rebuilds it.
        Category.objects.get_or_create(name="NEWS")
        cache.clear()

        #   Distinct staff/admin addresses, so "not listed" is provable: their
        #   masked forms must never appear in a members-only table.
        self.admin = Auth.objects.create_admin(email="zulu-admin@example.com")
        self.writer = Auth.objects.create_staff(email="zulu-writer@example.com")

        #   alpha signed up through the footer newsletter form: never signed in,
        #   no category rows (so "all categories"), and no reading history.
        self.alpha = Auth.objects.create_user(email="alpha@example.com", send_newsletter=True)

        #   bravo is a normal member: has signed in, switched news alerts off,
        #   narrowed to NEWS, and read a story a moment ago.
        self.bravo = Auth.objects.create_user(email="bravo@example.com", send_newsletter=False)
        Auth.objects.filter(pk=self.bravo.pk).update(last_login=timezone.now())
        CategorySubscription.objects.create(user=self.bravo, category="NEWS")
        self.story = Blog.objects.create(
            author=self.writer, heading="Members read story", category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        ReadingHistory.objects.create(user=self.bravo, blog=self.story)

        #   charlie was suspended: news alerts still on, but has read nothing.
        self.charlie = Auth.objects.create_user(
            email="charlie@example.com", send_newsletter=True, is_active=False
        )
        Auth.objects.filter(pk=self.charlie.pk).update(last_login=timezone.now())

        self.url = reverse("control:analytics_members")

    def rows(self, **params):
        self.client.force_login(self.admin)
        return self.client.get(self.url, params).content.decode()

    #   ------------------------------------------------------------ access
    def test_only_admins_can_read_the_fragment(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)   # anonymous
        for user in [self.writer, self.alpha]:
            with self.subTest(user=user.email):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)

    #   ------------------------------------------------------------ membership
    def test_only_regular_members_are_listed_never_staff_or_admins(self):
        html = self.rows()
        self.assertIn("A***A@EXAMPLE.COM", html)     # alpha
        self.assertIn("B***O@EXAMPLE.COM", html)     # bravo
        self.assertIn("C***E@EXAMPLE.COM", html)     # charlie
        self.assertNotIn("Z***R@EXAMPLE.COM", html)  # writer
        self.assertNotIn("Z***N@EXAMPLE.COM", html)  # admin

    def test_the_newsletter_signup_filter_finds_never_signed_in_accounts(self):
        html = self.rows(kind="signup")
        self.assertIn("A***A@EXAMPLE.COM", html)          # never signed in
        self.assertNotIn("B***O@EXAMPLE.COM", html)       # has signed in
        self.assertNotIn("C***E@EXAMPLE.COM", html)

    def test_the_regular_filter_excludes_never_signed_in_accounts(self):
        html = self.rows(kind="regular")
        self.assertNotIn("A***A@EXAMPLE.COM", html)
        self.assertIn("B***O@EXAMPLE.COM", html)
        self.assertIn("C***E@EXAMPLE.COM", html)

    #   ------------------------------------------------------------ filters
    def test_the_news_alert_filter_separates_on_from_off(self):
        on = self.rows(newsletter="on")
        self.assertIn("A***A@EXAMPLE.COM", on)
        self.assertIn("C***E@EXAMPLE.COM", on)
        self.assertNotIn("B***O@EXAMPLE.COM", on)

        off = self.rows(newsletter="off")
        self.assertIn("B***O@EXAMPLE.COM", off)
        self.assertNotIn("A***A@EXAMPLE.COM", off)

    def test_the_status_filter_finds_suspended_accounts(self):
        html = self.rows(state="suspended")
        self.assertIn("C***E@EXAMPLE.COM", html)
        self.assertNotIn("A***A@EXAMPLE.COM", html)

    def test_the_activity_filter_uses_recent_reads_and_never_reads(self):
        recent = self.rows(activity="recent")
        self.assertIn("B***O@EXAMPLE.COM", recent)
        self.assertNotIn("A***A@EXAMPLE.COM", recent)

        never = self.rows(activity="never")
        self.assertIn("A***A@EXAMPLE.COM", never)
        self.assertIn("C***E@EXAMPLE.COM", never)
        self.assertNotIn("B***O@EXAMPLE.COM", never)

    def test_a_member_with_no_category_rows_reads_as_all_categories(self):
        html = self.rows(category="all")
        self.assertIn("A***A@EXAMPLE.COM", html)          # no preference
        self.assertIn("C***E@EXAMPLE.COM", html)
        self.assertNotIn("B***O@EXAMPLE.COM", html)       # narrowed to NEWS

    def test_the_category_filter_matches_the_subscribed_category(self):
        html = self.rows(category="NEWS")
        self.assertIn("B***O@EXAMPLE.COM", html)
        self.assertNotIn("A***A@EXAMPLE.COM", html)
        self.assertNotIn("C***E@EXAMPLE.COM", html)

    #   ------------------------------------------------------------ rendering
    def test_the_category_cell_shows_either_chips_or_the_default(self):
        html = self.rows()
        self.assertIn("analytics-chip--muted", html)   # the "All categories" chip
        self.assertIn(">NEWS<", html)                  # bravo's chip

    def test_a_never_signed_in_account_reads_as_a_newsletter_signup(self):
        html = self.rows(kind="signup")
        self.assertIn("newsletter sign-up", html)

    def test_an_unknown_filter_value_falls_back_to_the_default(self):
        html = self.rows(state="bogus", kind="bogus", category="bogus")
        self.assertIn("A***A@EXAMPLE.COM", html)
        self.assertNotIn("bogus", html)

    @mock.patch("ADMIN.views.MEMBER_PAGE_SIZE", 1)
    def test_the_pager_carries_the_active_filters_forward(self):
        html = self.rows(state="active")
        #   The standard project pager: each page button asks only for ?page=N
        #   and the shell's filter form is pulled in through hx-include, so the
        #   active filters travel with the request without being echoed in a URL.
        self.assertIn("analytics-members-pagination", html)
        self.assertIn('hx-include="#analytics-members-filters"', html)
        self.assertIn("page=2", html)

    def test_a_single_page_has_no_pager(self):
        self.assertNotIn("analytics-members-pagination", self.rows())


class AnalyticsOverviewTests(TestCase):
    """The ANALYTICS "Quick overview" card and the "new users today" badge.

    Both are member-facing figures read from columns the database already has
    (Auth.date_joined, ReadingHistory.read_at, Blog.date_created), fetched by
    their own htmx GET and admin only. Windows: today, the current week (Sunday
    to now) and the last 30 days; the change since last week is the current
    week measured against the whole of the previous one.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="overview-admin@example.com")
        self.writer = Auth.objects.create_staff(email="overview-writer@example.com")
        #   Push the two fixtures far outside every window so the numbers a
        #   test reads are only ever the accounts that test created.
        Auth.objects.filter(pk__in=[self.admin.pk, self.writer.pk]).update(
            date_joined=timezone.now() - timedelta(days=400)
        )

        self.overview_url = reverse("control:member_overview")
        self.badge_url = reverse("control:member_new_today")

    def account_joined(self, email, when):
        account = Auth.objects.create_user(email=email)
        Auth.objects.filter(pk=account.pk).update(date_joined=when)
        return account

    def make_story(self, heading):
        return Blog.objects.create(
            author=self.writer, heading=heading, category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )

    #   ------------------------------------------------------------ access
    def test_both_endpoints_are_admin_only(self):
        for url in [self.overview_url, self.badge_url]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.force_login(self.writer)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.logout()

    def test_an_admin_can_read_both(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.overview_url).status_code, 200)
        self.assertEqual(self.client.get(self.badge_url).status_code, 200)

    #   ------------------------------------------------------------ shell
    def test_the_shell_ships_both_targets_but_no_numbers(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:analytics")).content.decode()
        self.assertIn("analytics-overview-body", body)
        self.assertIn("analytics-new-today", body)
        self.assertIn("analytics/overview/", body)
        self.assertIn("analytics/new-today/", body)
        self.assertNotIn("analytics-overview-data", body)

    #   ------------------------------------------------------------ new users
    def test_the_badge_counts_only_accounts_created_today(self):
        self.account_joined("today@example.com", timezone.now())
        self.account_joined("lastweek@example.com", timezone.now() - timedelta(days=8))
        self.assertEqual(member_new_today(), 1)

        self.client.force_login(self.admin)
        body = self.client.get(self.badge_url).content.decode()
        self.assertIn("1", body)
        self.assertIn("new user today", body)

    def test_the_month_window_is_a_rolling_thirty_days(self):
        self.account_joined("ten@example.com", timezone.now() - timedelta(days=10))
        self.account_joined("forty@example.com", timezone.now() - timedelta(days=40))
        stats = member_overview()
        self.assertEqual(stats["users"]["today"], 0)
        self.assertEqual(stats["users"]["month"], 1)

    def test_this_week_is_measured_against_all_of_last_week(self):
        #   One account this week, none last week -> +1.
        self.account_joined("thisweek@example.com", timezone.now())
        stats = member_overview()
        self.assertEqual(stats["users"]["delta_display"], "+1")
        self.assertEqual(stats["users"]["delta_tone"], "is-up")

    def test_a_quiet_week_reports_a_negative_change(self):
        #   No account this week; one on the previous week's Sunday.
        last_sunday = _week_start(timezone.localtime()) - timedelta(days=7)
        self.account_joined("lastweek@example.com", last_sunday + timedelta(hours=12))
        stats = member_overview()
        self.assertEqual(stats["users"]["delta_display"], "-1")
        self.assertEqual(stats["users"]["delta_tone"], "is-down")

    def test_an_empty_week_reads_as_zero_not_a_dash(self):
        stats = member_overview()
        self.assertEqual(stats["users"]["delta_display"], "0")
        self.assertEqual(stats["users"]["delta_tone"], "is-flat")

    #   ------------------------------------------------------------ readers + stories
    def test_active_readers_counts_distinct_readers(self):
        reader = self.account_joined("reader@example.com", timezone.now() - timedelta(days=5))
        for index in range(2):
            ReadingHistory.objects.create(user=reader, blog=self.make_story(f"Read story {index}"))
        stats = member_overview()
        self.assertEqual(stats["readers"]["today"], 1)
        self.assertEqual(stats["readers"]["month"], 1)

    def test_stories_published_counts_todays_stories(self):
        self.make_story("Fresh overview story")
        stats = member_overview()
        self.assertEqual(stats["stories"]["today"], 1)

    #   ------------------------------------------------------------ rendering
    def test_the_overview_fragment_renders_the_metrics(self):
        self.account_joined("today@example.com", timezone.now())
        self.client.force_login(self.admin)
        body = self.client.get(self.overview_url).content.decode()
        self.assertIn("analytics-overview", body)
        self.assertIn("vs last week", body)
        self.assertIn("Current members total", body)
        self.assertIn("Active readers", body)
        #   stories published moved to Story lytics
        self.assertNotIn("Stories published", body)


class AnalyticsReadingTests(TestCase):
    """The ANALYTICS "Reading & editorial" card.

    All three blocks are windowed to one range (the Trends ranges) and read
    only from existing tables: StoryView events for "views", Blog.category for
    the published-vs-read split, and the stored Blog.views counter for the cold
    backlog.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="reading-admin@example.com")
        self.writer = Auth.objects.create_staff(email="reading-writer@example.com")
        self.member = Auth.objects.create_user(email="reading-member@example.com")

        self.url = reverse("control:analytics_reading")

    def make_story(self, heading, category="NEWS", age_days=0, views=0):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category=category,
            content="Body.", image_1="https://example.com/a.jpg",
        )
        #   date_created and views are pinned by hand: auto_now_add would file
        #   every fixture under "now".
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days), views=views
        )
        return story

    def add_view(self, story, age_days=0):
        view = StoryView.objects.create(blog=story)
        StoryView.objects.filter(pk=view.pk).update(created_at=timezone.now() - timedelta(days=age_days))
        return view

    #   ------------------------------------------------------------ access
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    #   ------------------------------------------------------------ shell
    def test_the_shell_ships_the_reading_target_but_no_numbers(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("analytics-reading-body", body)
        self.assertIn("analytics/reading/", body)
        self.assertNotIn("analytics-reading-data", body)

    #   ------------------------------------------------------------ top stories
    def test_top_stories_rank_by_views_inside_the_window(self):
        busy = self.make_story("Reading busiest")
        quiet = self.make_story("Reading quiet")
        stale = self.make_story("Reading stale")
        for _ in range(3):
            self.add_view(busy)
        self.add_view(quiet)
        for _ in range(9):
            self.add_view(stale, age_days=200)   # outside even a year-long range? no: outside 30d

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "30d"}).content.decode()
        self.assertIn("Reading busiest", body)
        self.assertIn("Reading quiet", body)
        self.assertNotIn("Reading stale", body)
        self.assertLess(body.index("Reading busiest"), body.index("Reading quiet"))

    def test_a_longer_range_pulls_in_older_views(self):
        story = self.make_story("Reading older win")
        self.add_view(story, age_days=60)
        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "90d"}).content.decode()
        self.assertIn("Reading older win", body)

    #   ------------------------------------------------------------ cold backlog
    def test_cold_stories_caps_views_and_gates_by_age(self):
        #   Five views or fewer is cold; six is not. The gate is two days, so a
        #   story published this morning is never cold however few views it has.
        self.make_story("Cold story", age_days=10)
        self.make_story("Almost cold", age_days=10, views=5)
        self.make_story("Warm story", age_days=10, views=6)
        self.make_story("Fresh story", age_days=1)

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "30d"}).content.decode()
        self.assertIn("Cold story", body)
        self.assertIn("Almost cold", body)
        self.assertNotIn("Warm story", body)
        self.assertNotIn("Fresh story", body)

    def test_a_cooled_since_date_moves_the_age_gate(self):
        #   One day old is inside the default two-day gate, so it is NOT cold by
        #   default. Moving "cooled since" forward to today means "published on
        #   or before today", which the story now is, so it joins the list.
        self.make_story("One day story", age_days=1)

        self.client.force_login(self.admin)
        default = self.client.get(self.url, {"range": "30d"}).content.decode()
        self.assertNotIn("One day story", default)

        cooled = timezone.localdate().isoformat()
        wide = self.client.get(self.url, {"range": "30d", "cooled": cooled}).content.decode()
        self.assertIn("One day story", wide)
        self.assertIn('value="%s"' % cooled, wide)

    def test_a_bad_cooled_date_falls_back_to_the_default_gate(self):
        self.make_story("Default gate story", age_days=3)

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "30d", "cooled": "banana"}).content.decode()
        self.assertIn("Default gate story", body)

    #   ------------------------------------------------------------ range guard
    def test_an_unknown_range_falls_back_to_the_default(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "banana"}).content.decode()
        self.assertIn("Last 30 days", body)

    #   ------------------------------------------------------------ categories
    def test_categories_compare_published_and_read(self):
        news = self.make_story("Category news", category="NEWS")
        self.make_story("Category sport", category="SPORT")
        self.add_view(news)

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "30d"}).content.decode()
        self.assertIn("NEWS", body)
        self.assertIn("SPORT", body)
        self.assertIn("Published vs read", body)

    #   ------------------------------------------------------------ like rate
    def test_the_top_read_table_no_longer_carries_a_like_rate(self):
        story = self.make_story("Rate story")
        self.add_view(story)
        self.add_view(story)
        BlogLike.objects.create(blog=story, user=self.member)

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "30d"}).content.decode()
        self.assertIn("Rate story", body)
        self.assertNotIn("Like rate", body)


class AnalyticsDailyStoryActivityTests(TestCase):
    """The Daily story activity card: stories opened on one day, with that
    day's own views, likes and comments."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="daily-admin@example.com")
        self.writer = Auth.objects.create_staff(email="daily-writer@example.com")
        self.member = Auth.objects.create_user(email="daily-member@example.com")
        self.other_member = Auth.objects.create_user(email="daily-member-2@example.com")
        self.today = timezone.localdate()
        self.url = reverse("control:analytics_daily_story_activity")

    def make_story(self, heading, category="NEWS"):
        return Blog.objects.create(
            author=self.writer, heading=heading, category=category,
            content="Body.", image_1="https://example.com/a.jpg",
        )

    def stamp(self, day, hour=12):
        return timezone.make_aware(datetime.combine(day, time(hour=hour)))

    def add_view(self, story, day):
        view = StoryView.objects.create(blog=story)
        StoryView.objects.filter(pk=view.pk).update(created_at=self.stamp(day))

    def add_like(self, story, day, user=None):
        like = BlogLike.objects.create(blog=story, user=user or self.member)
        BlogLike.objects.filter(pk=like.pk).update(created_at=self.stamp(day))

    def add_comment(self, story, day):
        comment = Comment.objects.create(
            blog=story, author=self.member, content="Good read."
        )
        Comment.objects.filter(pk=comment.pk).update(date_created=self.stamp(day))

    #   ------------------------------------------------------------ access
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_the_story_lytics_shell_links_the_card(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("analytics-daily-activity-body", body)
        self.assertIn("analytics/story/daily-activity/", body)

    #   ------------------------------------------------------------ the roster
    def test_only_stories_viewed_that_day_are_listed(self):
        busy = self.make_story("Daily busy")
        quiet = self.make_story("Daily quiet")
        yesterday_story = self.make_story("Daily yesterday")
        never_viewed = self.make_story("Daily never viewed")
        reacted_not_viewed = self.make_story("Daily reacted not viewed")

        for _ in range(3):
            self.add_view(busy, self.today)
        self.add_view(quiet, self.today)
        self.add_view(yesterday_story, self.today - timedelta(days=1))
        self.add_like(reacted_not_viewed, self.today)
        self.add_comment(reacted_not_viewed, self.today)

        self.client.force_login(self.admin)
        activity = daily_story_activity(self.today.isoformat())
        self.assertEqual(
            [story["heading"] for story in activity["stories"]],
            ["Daily busy", "Daily quiet"],
        )
        self.assertEqual(activity["story_count"], 2)
        self.assertEqual(activity["views"], 4)

        body = self.client.get(self.url).content.decode()
        self.assertIn("Daily busy", body)
        self.assertIn("Daily quiet", body)
        self.assertNotIn(yesterday_story.heading, body)
        self.assertNotIn(never_viewed.heading, body)
        self.assertNotIn(reacted_not_viewed.heading, body)

    def test_likes_and_comments_are_counted_for_that_day_only(self):
        story = self.make_story("Daily signals")
        self.add_view(story, self.today)
        self.add_view(story, self.today - timedelta(days=1))

        self.add_like(story, self.today, self.member)
        self.add_like(story, self.today - timedelta(days=1), self.other_member)
        self.add_comment(story, self.today)
        self.add_comment(story, self.today - timedelta(days=1))

        activity = daily_story_activity(self.today.isoformat())
        row = activity["stories"][0]
        self.assertEqual(row["views"], 1)
        self.assertEqual(row["likes"], 1)
        self.assertEqual(row["comments"], 1)
        self.assertEqual(activity["views"], 1)
        self.assertEqual(activity["likes"], 1)
        self.assertEqual(activity["comments"], 1)

    def test_each_row_shows_the_publish_date_before_the_category(self):
        posted = self.stamp(self.today - timedelta(days=5))
        story = self.make_story("Daily dated story", category="NEWS")
        Blog.objects.filter(pk=story.pk).update(date_created=posted)
        self.add_view(story, self.today)

        self.client.force_login(self.admin)
        body = self.client.get(self.url).content.decode()
        label = "%s %d, %d" % (posted.strftime("%b"), posted.day, posted.year)
        self.assertIn(label + " &middot; NEWS", body)

    def test_the_date_box_loads_another_day(self):
        yesterday = self.today - timedelta(days=1)
        story = self.make_story("Daily yesterday story")
        self.add_view(story, yesterday)
        self.add_like(story, yesterday)
        self.add_comment(story, yesterday)

        self.client.force_login(self.admin)
        default = self.client.get(self.url).content.decode()
        self.assertNotIn("Daily yesterday story", default)

        body = self.client.get(self.url, {"day": yesterday.isoformat()}).content.decode()
        self.assertIn("Daily yesterday story", body)
        self.assertIn('value="%s"' % yesterday.isoformat(), body)
        self.assertIn("1 view", body)
        self.assertIn("1 like", body)
        self.assertIn("1 comment", body)

    def test_a_future_or_malformed_day_falls_before_today(self):
        future = self.today + timedelta(days=3)
        self.assertEqual(daily_story_activity(future.isoformat())["day"], self.today)
        self.assertTrue(daily_story_activity("banana")["is_today"])


class AnalyticsCategoryDailyTests(TestCase):
    """The "Stories per day, by category" chart
    (control:analytics_story_category_daily).

    One line per category, each counting the stories published in that
    category inside the bucket. The window is a preset or a custom start and
    end date, so the admin can ask for exactly two days or exactly a week.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="catdaily-admin@example.com")
        self.writer = Auth.objects.create_staff(email="catdaily-writer@example.com")

        self.url = reverse("control:analytics_story_category_daily")

    def make_story(self, heading, category="NEWS", age_days=0):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category=category,
            content="Body.", image_1="https://example.com/a.jpg",
        )
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )
        return story

    #   ------------------------------------------------------------ access
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    #   ------------------------------------------------------------ shell
    def test_the_shell_ships_the_card_but_no_numbers(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("analytics-category-daily-body", body)
        self.assertIn("analytics/story-category-daily/", body)
        self.assertNotIn("analytics-story-category-daily-data", body)

    #   ------------------------------------------------------------ the chart
    def test_each_ticked_category_gets_its_own_line(self):
        self.make_story("Daily news one", category="NEWS")
        self.make_story("Daily news two", category="NEWS")
        self.make_story("Daily sport one", category="SPORT")

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"bucket": "day", "range": "30d", "category": ["NEWS", "SPORT"]},
            ),
            "analytics-story-category-daily-data",
        )
        self.assertEqual(chart["type"], "line")
        self.assertEqual([s["key"] for s in chart["series"]], ["NEWS", "SPORT"])
        totals = {s["key"]: sum(s["values"]) for s in chart["series"]}
        self.assertEqual(totals, {"NEWS": 2, "SPORT": 1})
        self.assertEqual(chart["total"], 3)

    def test_an_unticked_category_is_not_drawn(self):
        self.make_story("Only news", category="NEWS")
        self.make_story("Unticked sport", category="SPORT")

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"bucket": "day", "range": "30d", "category": ["NEWS"]}),
            "analytics-story-category-daily-data",
        )
        self.assertEqual([s["key"] for s in chart["series"]], ["NEWS"])

    def test_an_unknown_category_name_is_ignored(self):
        self.make_story("Real news", category="NEWS")

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"bucket": "day", "range": "30d", "category": ["BANANA"]},
            ),
            "analytics-story-category-daily-data",
        )
        self.assertEqual(chart["series"], [])
        self.assertEqual(chart["total"], 0)

    def test_blank_category_uses_the_no_category_series(self):
        self.make_story("Retired category story", category="RETIRED")
        self.make_story("Blank category story", category="")

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"bucket": "day", "range": "30d", "category": [NO_CATEGORY_KEY]},
            ),
            "analytics-story-category-daily-data",
        )

        self.assertEqual(len(chart["series"]), 1)
        self.assertEqual(chart["series"][0]["key"], NO_CATEGORY_KEY)
        self.assertEqual(chart["series"][0]["name"], "No category")
        self.assertEqual(sum(chart["series"][0]["values"]), 1)

    def test_a_custom_period_narrows_the_window_to_exactly_two_days(self):
        self.make_story("Inside the two days", category="NEWS", age_days=1)
        self.make_story("Outside the two days", category="NEWS", age_days=5)

        start = (timezone.localdate() - timedelta(days=1)).isoformat()
        end = timezone.localdate().isoformat()
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {
                    "bucket": "day",
                    "category": ["NEWS"],
                    "start": start,
                    "end": end,
                },
            ),
            "analytics-story-category-daily-data",
        )
        totals = {s["key"]: sum(s["values"]) for s in chart["series"]}
        self.assertEqual(totals, {"NEWS": 1})

    def test_a_custom_period_can_cover_exactly_a_week(self):
        self.make_story("Inside the week", category="NEWS", age_days=6)
        self.make_story("Outside the week", category="NEWS", age_days=9)

        start = (timezone.localdate() - timedelta(days=6)).isoformat()
        end = timezone.localdate().isoformat()
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {
                    "bucket": "day",
                    "category": ["NEWS"],
                    "start": start,
                    "end": end,
                },
            ),
            "analytics-story-category-daily-data",
        )
        totals = {s["key"]: sum(s["values"]) for s in chart["series"]}
        self.assertEqual(totals, {"NEWS": 1})

    def test_the_stories_are_bucketed_by_day(self):
        self.make_story("Two days ago", category="NEWS", age_days=2)
        self.make_story("Also two days ago", category="NEWS", age_days=2)
        self.make_story("Yesterday", category="NEWS", age_days=1)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"bucket": "day", "range": "7d", "category": ["NEWS"]},
            ),
            "analytics-story-category-daily-data",
        )
        values = chart["series"][0]["values"]
        self.assertEqual(sum(values), 3)
        #   The last three buckets are two days ago, yesterday and today: the
        #   two stories share one bucket, yesterday carries one, today none.
        self.assertEqual(values[-3:], [2, 1, 0])

    def test_an_hourly_bucket_finer_than_a_day(self):
        self.make_story("Just now", category="NEWS")

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"bucket": "hour", "range": "24h", "category": ["NEWS"]},
            ),
            "analytics-story-category-daily-data",
        )
        values = chart["series"][0]["values"]
        self.assertEqual(sum(values), 1)
        #   An hourly window is a handful of points, not a month of them.
        self.assertLessEqual(len(values), 26)


class AnalyticsCategoryCompareTests(TestCase):
    """The "Category, head to head" chart (control:analytics_category_compare).

    Two subjects, four numbers each -- stories published, likes, comments and
    story opens -- all counted inside the same window, with the gap between the
    two stated in figures.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="compare-admin@example.com")
        self.writer = Auth.objects.create_staff(email="compare-writer@example.com")
        self.member = Auth.objects.create_user(email="compare-member@example.com")

        self.url = reverse("control:analytics_category_compare")

    def make_story(self, heading, category="NEWS", age_days=0):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category=category,
            content="Body.", image_1="https://example.com/a.jpg",
        )
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )
        return story

    def add_view(self, story, age_days=0):
        view = StoryView.objects.create(blog=story)
        StoryView.objects.filter(pk=view.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        return view

    #   ------------------------------------------------------------ access
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    #   ------------------------------------------------------------ shell
    def test_the_shell_ships_the_card_but_no_numbers(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("analytics-category-compare-body", body)
        self.assertIn("analytics/category-compare/", body)
        self.assertNotIn("analytics-category-compare-data", body)

    #   ------------------------------------------------------------ the chart
    def test_the_two_subjects_are_counted_side_by_side(self):
        news = self.make_story("Compare news one", category="NEWS")
        self.make_story("Compare news two", category="NEWS")
        sport = self.make_story("Compare sport one", category="SPORT")
        BlogLike.objects.create(blog=news, user=self.member)
        Comment.objects.create(blog=sport, author=self.member, content="Nice one.")
        self.add_view(news)
        self.add_view(news)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"a": "NEWS", "b": "SPORT", "range": "30d"}),
            "analytics-category-compare-data",
        )
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(
            chart["labels"], ["Stories", "Likes", "Comments", "Views"]
        )
        self.assertEqual([s["key"] for s in chart["series"]], ["NEWS", "SPORT"])
        self.assertEqual(chart["series"][0]["values"], [2, 1, 0, 2])
        self.assertEqual(chart["series"][1]["values"], [1, 0, 1, 0])

    def test_no_category_bucket_is_comparable(self):
        blank = self.make_story("Blank category", category="")
        self.make_story("Category comparison news", category="NEWS")
        self.add_view(blank)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"a": NO_CATEGORY_KEY, "b": "NEWS", "range": "30d"},
            ),
            "analytics-category-compare-data",
        )

        self.assertEqual(chart["categories"], ["No category", "NEWS"])
        self.assertEqual(chart["series"][0]["name"], "No category")
        self.assertEqual(chart["series"][0]["values"], [1, 0, 0, 1])

    def test_the_difference_between_the_two_is_stated_in_figures(self):
        news = self.make_story("Gap news one", category="NEWS")
        self.make_story("Gap news two", category="NEWS")
        self.make_story("Gap sport one", category="SPORT")
        self.add_view(news)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"a": "NEWS", "b": "SPORT", "range": "30d"}),
            "analytics-category-compare-data",
        )
        rows = {row["metric"]: row for row in chart["differences"]}
        self.assertEqual(rows["Stories"]["difference"], 1)
        self.assertEqual(rows["Stories"]["display"], "+1")
        self.assertEqual(rows["Stories"]["leader"], "NEWS")
        self.assertEqual(rows["Likes"]["difference"], 0)
        self.assertEqual(rows["Likes"]["display"], "0")
        self.assertTrue(rows["Likes"]["tie"])
        #   The views are counted in their own right, not left out of the
        #   comparison because they live on the Story lytics page.
        self.assertEqual(rows["Views"]["difference"], 1)
        self.assertEqual(rows["Views"]["display"], "+1")
        self.assertEqual(rows["Views"]["leader"], "NEWS")

    def test_the_note_line_states_the_difference(self):
        self.make_story("Note news one", category="NEWS")
        self.make_story("Note news two", category="NEWS")
        self.make_story("Note sport", category="SPORT")

        self.client.force_login(self.admin)
        body = self.client.get(
            self.url, {"a": "NEWS", "b": "SPORT", "range": "30d"}
        ).content.decode()
        self.assertIn("Stories +1", body)
        self.assertIn("Views ", body)

    def test_the_two_subjects_must_differ(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"a": "NEWS", "b": "NEWS", "range": "30d"}),
            "analytics-category-compare-data",
        )
        self.assertEqual(len(chart["series"]), 2)
        self.assertNotEqual(chart["series"][0]["key"], chart["series"][1]["key"])

    def test_an_unknown_subject_snaps_to_a_real_category(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"a": "BANANA", "b": "ALSO BANANA", "range": "30d"}),
            "analytics-category-compare-data",
        )
        self.assertNotIn("BANANA", [s["key"] for s in chart["series"]])

    def test_the_window_applies_to_every_metric(self):
        old = self.make_story("Old news", category="NEWS", age_days=200)
        self.make_story("Old sport", category="SPORT", age_days=200)
        like = BlogLike.objects.create(blog=old, user=self.member)
        #   The like is as old as the story it belongs to.
        BlogLike.objects.filter(pk=like.pk).update(
            created_at=timezone.now() - timedelta(days=200)
        )
        self.add_view(old, age_days=200)

        self.client.force_login(self.admin)
        wide = _chart_data(
            self,
            self.client.get(self.url, {"a": "NEWS", "b": "SPORT", "range": "1y"}),
            "analytics-category-compare-data",
        )
        narrow = _chart_data(
            self,
            self.client.get(self.url, {"a": "NEWS", "b": "SPORT", "range": "30d"}),
            "analytics-category-compare-data",
        )
        self.assertEqual(wide["series"][0]["values"], [1, 1, 0, 1])
        #   The like and the view are 200 days old, so a 30 day window leaves
        #   them out.
        self.assertEqual(narrow["series"][0]["values"], [0, 0, 0, 0])


class AnalyticsUncategorizedStoriesTests(TestCase):
    def setUp(self):
        super().setUp()
        self.admin = Auth.objects.create_admin(email="uncategorized-admin@example.com")
        self.writer = Auth.objects.create_staff(email="uncategorized-writer@example.com")
        self.url = reverse("control:analytics_uncategorized_stories")

    def make_story(self, heading, category):
        return Blog.objects.create(
            author=self.writer,
            heading=heading,
            category=category,
            content="Body.",
            image_1="https://example.com/a.jpg",
        )

    def test_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_lists_blank_and_retired_categories_with_a_real_total(self):
        self.make_story("Retired story", "RETIRED")
        self.make_story("Blank story", "")
        self.client.force_login(self.admin)

        response = self.client.get(self.url)
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(">2</strong> uncategorized stories", body)
        self.assertIn("100% of 2 stories", body)
        self.assertIn("Retired story", body)
        self.assertIn("Blank story", body)

    def test_list_is_paginated_without_reporting_a_truncated_count(self):
        for index in range(26):
            self.make_story(f"Uncategorized story {index:02}", "RETIRED")
        self.client.force_login(self.admin)

        first_page = self.client.get(self.url).content.decode()
        second_page = self.client.get(self.url, {"page": 2}).content.decode()

        self.assertIn(">26</strong> uncategorized stories", first_page)
        self.assertIn("Uncategorized story 25", first_page)
        self.assertIn("Uncategorized story 00", second_page)


class AnalyticsStoryKpisTests(TestCase):
    """The Story lytics KPI strip (control:analytics_story_kpis).

    Four real totals over one window: published, reads, reads per story and the
    current cold backlog. The two windowed figures can only carry a delta when
    the period before them had data, so an empty history shows no chip at all
    rather than a fall invented out of nothing.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="story-kpis-admin@example.com")
        self.writer = Auth.objects.create_staff(email="story-kpis-writer@example.com")
        self.member = Auth.objects.create_user(email="story-kpis-member@example.com")

        self.url = reverse("control:analytics_story_kpis")

    def make_story(self, heading, category="NEWS", age_days=0, views=0):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category=category,
            content="Body.", image_1="https://example.com/a.jpg",
        )
        #   Pinned by hand: auto_now_add would file every fixture under "now".
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days), views=views
        )
        return story

    def add_view(self, story, age_days=0):
        view = StoryView.objects.create(blog=story)
        StoryView.objects.filter(pk=view.pk).update(created_at=timezone.now() - timedelta(days=age_days))
        return view

    #   ------------------------------------------------------------ access
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    #   ------------------------------------------------------------ shell
    def test_the_shell_ships_the_target_but_never_the_figures(self):
        self.client.force_login(self.admin)
        shell = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("analytics-kpis-body", shell)
        self.assertNotIn("analytics-kpi-value", shell)
        self.assertNotIn("analytics-kpis-range", shell)

    def test_the_strip_ships_the_four_real_tiles(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "7d"}).content.decode()
        for label in ["Published", "Reads", "Reads per story", "Cold stories"]:
            with self.subTest(label=label):
                self.assertIn(label, body)
        #   the segmented control is squared markup, and copy stays free of em
        #   dashes project wide
        self.assertIn("analytics-segmented", body)
        self.assertNotIn("\u2014", body)

    #   ------------------------------------------------------------ deltas
    def test_a_delta_only_appears_when_the_previous_window_had_data(self):
        #   One story and one read a fortnight ago (the previous 7 day window),
        #   two stories inside the current one: published up, reads down.
        earlier = self.make_story("KPI earlier story", age_days=10)
        self.add_view(earlier, age_days=10)
        self.make_story("KPI current one", age_days=0)
        self.make_story("KPI current two", age_days=1)

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "7d"}).content.decode()
        self.assertIn('class="analytics-delta is-up"', body)
        self.assertIn('class="analytics-delta is-down"', body)
        self.assertIn("against the previous period", body)

        #   A window whose earlier half is empty carries no chip at all.
        wide = self.client.get(self.url, {"range": "90d"}).content.decode()
        self.assertNotIn("analytics-delta", wide)
        self.assertIn("No earlier period to compare.", wide)

    #   ------------------------------------------------------------ windows
    def test_an_unknown_range_falls_back_to_the_default(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "banana"}).content.decode()
        self.assertIn("Last 30 days", body)

    def test_a_custom_pair_overrides_the_preset_and_activates_no_segment(self):
        today = timezone.localdate()
        start = (today - timedelta(days=3)).isoformat()
        end = today.isoformat()

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"range": "7d", "start": start, "end": end}).content.decode()
        self.assertIn("Custom range", body)
        self.assertNotIn("is-active", body)
        #   the typed dates come back, so the boxes keep what was entered
        self.assertIn('value="%s"' % start, body)
        self.assertIn('value="%s"' % end, body)

    def test_published_and_reads_are_windowed_not_all_time(self):
        #   The stale story sits outside seven days but inside ninety, so the
        #   published tile has to move with the range instead of holding an
        #   all-time figure.
        self.make_story("KPI stale story", age_days=40)
        recent = self.make_story("KPI fresh story", age_days=0)
        self.add_view(recent)

        self.client.force_login(self.admin)
        seven = self.client.get(self.url, {"range": "7d"}).content.decode()
        wide = self.client.get(self.url, {"range": "90d"}).content.decode()

        #   published / reads / reads-per-story / cold all read one in the short
        #   window, then published becomes two while reads stays at one
        self.assertEqual(seven.count('analytics-kpi-value">1<'), 4)
        self.assertIn('analytics-kpi-value">2<', wide)
        self.assertNotIn('analytics-kpi-value">2<', seven)


class AnalyticsMembersGrowthTests(TestCase):
    """The "Members over time" running-total line chart (control:member_growth).

    Cumulative, not per-period: each bucket carries every member that existed by
    its end, with members from before the window as the baseline, so the line
    never resets, and an empty project is a flat line at zero.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="growth-admin@example.com")
        self.writer = Auth.objects.create_staff(email="growth-writer@example.com")
        #   Staff are not members; still push them far back so they can never
        #   leak into a fixture window.
        Auth.objects.filter(pk__in=[self.admin.pk, self.writer.pk]).update(
            date_joined=timezone.now() - timedelta(days=800)
        )
        self.url = reverse("control:member_growth")

    def member_joined(self, email, when):
        account = Auth.objects.create_user(email=email)
        Auth.objects.filter(pk=account.pk).update(date_joined=when)
        return account

    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_the_line_is_a_running_total_not_a_per_bucket_count(self):
        self.member_joined("old@example.com", timezone.now() - timedelta(days=10))
        self.member_joined("a@example.com", timezone.now())
        self.member_joined("b@example.com", timezone.now())

        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.url, {"bucket": "day", "range": "30d"}), "analytics-members-growth-data")
        values = chart["series"][0]["values"]
        self.assertEqual(values, sorted(values))            # never steps down
        self.assertEqual(values[-1], chart["total"])
        self.assertEqual(chart["total"], 3)

    def test_members_before_the_window_are_carried_as_the_baseline(self):
        self.member_joined("ancient@example.com", timezone.now() - timedelta(days=200))
        self.member_joined("fresh@example.com", timezone.now())

        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.url, {"bucket": "day", "range": "30d"}), "analytics-members-growth-data")
        self.assertEqual(chart["baseline"], 1)
        self.assertEqual(chart["series"][0]["values"][0], 1)
        self.assertEqual(chart["total"], 2)

    def test_an_empty_project_reads_as_a_flat_zero_line(self):
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.url), "analytics-members-growth-data")
        self.assertEqual(chart["total"], 0)
        self.assertEqual(set(chart["series"][0]["values"]), {0})

    def test_the_month_bucket_labels_are_calendar_months(self):
        self.member_joined("m@example.com", timezone.now())
        self.client.force_login(self.admin)
        chart = _chart_data(self, self.client.get(self.url, {"bucket": "month", "range": "1y"}), "analytics-members-growth-data")
        self.assertGreaterEqual(len(chart["labels"]), 12)
        for label in chart["labels"]:
            self.assertRegex(label, r"^[A-Z][a-z]{2} \d{4}$")

    def test_a_custom_range_overrides_the_range_preset(self):
        self.member_joined("old@example.com", timezone.now() - timedelta(days=200))
        self.client.force_login(self.admin)
        today = timezone.localdate()
        start = (today - timedelta(days=5)).isoformat()
        chart = _chart_data(
            self,
            self.client.get(self.url, {"range": "30d", "start": start, "end": today.isoformat()}),
            "analytics-members-growth-data",
        )
        #   six daily buckets: five days back through today inclusive
        self.assertEqual(len(chart["labels"]), 6)
        self.assertEqual(chart["series"][0]["values"][0], 1)   # the baseline member


class AnalyticsStoryPerformanceTests(TestCase):
    """The Story performance card: one story's views, likes and comments over
    time, plus the search endpoint behind its picker."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="perf-admin@example.com")
        self.writer = Auth.objects.create_staff(email="perf-writer@example.com")
        self.member = Auth.objects.create_user(email="perf-member@example.com")

        self.url = reverse("control:analytics_story_performance")
        self.search_url = reverse("control:analytics_story_search")
        self.story = self.make_story("Performance story")

    def make_story(self, heading, age_days=0):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )
        return story

    def add_view(self, story, age_days=0):
        view = StoryView.objects.create(blog=story)
        StoryView.objects.filter(pk=view.pk).update(created_at=timezone.now() - timedelta(days=age_days))

    #   ------------------------------------------------------------ access
    def test_both_endpoints_are_admin_only(self):
        for url in [self.url, self.search_url]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.force_login(self.writer)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.logout()

    #   ------------------------------------------------------------ chart
    def test_no_story_selected_draws_a_prompt_not_a_chart(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.url).content.decode()
        self.assertIn("Pick a story", body)
        self.assertNotIn("analytics-story-performance-data", body)

    def test_the_chart_counts_views_likes_and_comments(self):
        self.add_view(self.story)
        self.add_view(self.story)
        BlogLike.objects.create(blog=self.story, user=self.member)
        Comment.objects.create(blog=self.story, author=self.member, content="Good read.")

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"story": self.story.pk, "bucket": "day", "range": "30d"}),
            "analytics-story-performance-data",
        )
        totals = {s["key"]: sum(s["values"]) for s in chart["series"]}
        self.assertEqual(totals, {"views": 2, "likes": 1, "comments": 1})

    def test_only_the_chosen_series_are_drawn(self):
        self.add_view(self.story)
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"submitted": "1", "story": self.story.pk, "series": ["views"]}),
            "analytics-story-performance-data",
        )
        self.assertEqual([s["key"] for s in chart["series"]], ["views"])

    def test_an_unknown_story_id_draws_the_prompt(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"story": "999999"}).content.decode()
        self.assertIn("Pick a story", body)

    #   ------------------------------------------------------------ the window
    def test_the_chart_opens_on_the_day_the_story_was_published(self):
        #   A story published three days ago must not be drawn against a
        #   thirty day window: the chart starts on its own publish day, so the
        #   story's life fills the chart instead of hiding on one side of it.
        story = self.make_story("Published three days ago", age_days=3)
        self.add_view(story)
        story.refresh_from_db()   #   date_created was pinned in the database

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"story": story.pk, "bucket": "day", "range": "30d"}),
            "analytics-story-performance-data",
        )
        published = timezone.localtime(story.date_created)
        self.assertEqual(chart["labels"][0], "%s %d" % (published.strftime("%b"), published.day))
        #   The publish day and the three days since it.
        self.assertEqual(len(chart["labels"]), 4)

    def test_the_range_still_bounds_an_old_story(self):
        story = self.make_story("Published long ago", age_days=200)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(self.url, {"story": story.pk, "bucket": "day", "range": "30d"}),
            "analytics-story-performance-data",
        )
        #   Thirty days of buckets, even though the story is much older.
        self.assertEqual(len(chart["labels"]), 30)

    def test_the_publish_day_is_named_above_the_chart(self):
        story = self.make_story("Published today", age_days=0)
        story.refresh_from_db()

        self.client.force_login(self.admin)
        body = self.client.get(self.url, {"story": story.pk, "bucket": "day", "range": "30d"}).content.decode()
        published = timezone.localtime(story.date_created)
        self.assertIn("%s %d" % (published.strftime("%b"), published.day), body)

    #   ------------------------------------------------------------ picker search
    def test_search_matches_by_heading(self):
        self.make_story("A different topic")
        self.client.force_login(self.admin)
        body = self.client.get(self.search_url, {"story_q": "Performance"}).content.decode()
        self.assertIn("Performance story", body)
        self.assertNotIn("A different topic", body)

    def test_search_with_no_query_shows_the_latest_stories(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.search_url).content.decode()
        self.assertIn("Performance story", body)


class AnalyticsCategoryPerformanceTests(TestCase):
    """The Category performance card: one category's views, likes and comments
    over time, with the same bucket / range controls as Story performance."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="cat-perf-admin@example.com")
        self.writer = Auth.objects.create_staff(email="cat-perf-writer@example.com")
        self.member = Auth.objects.create_user(email="cat-perf-member@example.com")

        Category.objects.get_or_create(name="NEWS")
        Category.objects.get_or_create(name="SPORT")

        self.url = reverse("control:analytics_category_performance")
        self.news_story = self.make_story("News story", "NEWS")
        self.sport_story = self.make_story("Sport story", "SPORT")

    def make_story(self, heading, category, age_days=0):
        story = Blog.objects.create(
            author=self.writer, heading=heading, category=category,
            content="Body.", image_1="https://example.com/a.jpg",
        )
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )
        return story

    def add_view(self, story, age_days=0):
        view = StoryView.objects.create(blog=story)
        StoryView.objects.filter(pk=view.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )

    def add_like(self, story, age_days=0):
        like = BlogLike.objects.create(blog=story, user=self.member)
        BlogLike.objects.filter(pk=like.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )

    def add_comment(self, story, age_days=0):
        comment = Comment.objects.create(blog=story, author=self.member, content="Good read.")
        Comment.objects.filter(pk=comment.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )

    #   ------------------------------------------------------------ access
    def test_the_endpoint_is_admin_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    #   ------------------------------------------------------------ chart
    def test_the_chart_counts_only_the_chosen_category(self):
        self.add_view(self.news_story)
        self.add_view(self.news_story)
        self.add_like(self.news_story)
        self.add_comment(self.news_story)

        #   The other subject's events must not leak into this chart.
        self.add_view(self.sport_story)
        self.add_like(self.sport_story)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"category": "NEWS", "bucket": "day", "range": "30d"},
            ),
            "analytics-category-performance-data",
        )
        totals = {series["key"]: sum(series["values"]) for series in chart["series"]}
        self.assertEqual(
            [series["key"] for series in chart["series"]],
            ["stories", "views", "likes", "comments"],
        )
        self.assertEqual(
            totals, {"stories": 1, "views": 2, "likes": 1, "comments": 1}
        )
        self.assertEqual(chart["category"]["label"], "NEWS")

    def test_only_the_chosen_series_are_drawn(self):
        self.add_view(self.news_story)
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"submitted": "1", "category": "NEWS", "series": ["views"]},
            ),
            "analytics-category-performance-data",
        )
        self.assertEqual([series["key"] for series in chart["series"]], ["views"])

    def test_the_chart_reports_the_stories_published_in_the_window(self):
        self.make_story("Old news", "NEWS", age_days=50)
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"category": "NEWS", "bucket": "day", "range": "30d"},
            ),
            "analytics-category-performance-data",
        )
        #   The news story from setUp is inside thirty days; the old one is not.
        self.assertEqual(chart["category"]["stories"], 1)

    def test_the_stories_series_counts_published_stories_per_bucket(self):
        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.url,
                {"category": "NEWS", "bucket": "day", "range": "30d"},
            ),
            "analytics-category-performance-data",
        )
        stories = next(
            series for series in chart["series"] if series["key"] == "stories"
        )
        self.assertEqual(len(stories["values"]), len(chart["labels"]))
        self.assertEqual(sum(stories["values"]), 1)

    def test_the_story_lytics_shell_links_the_card(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("Category performance", body)
        self.assertIn(self.url, body)


class AnalyticsChamberPlaceholderTests(TestCase):
    """The partner analytics page is a placeholder for now, the panel sidebar
    links to every chamber, and the Author chamber is a real shell (it replaced
    the old Staff placeholder, which duplicated it)."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = Auth.objects.create_admin(email="chamber-admin@example.com")
        self.writer = Auth.objects.create_staff(email="chamber-writer@example.com")

    def test_the_partner_placeholder_is_admin_only(self):
        name = "control:partner_lytics"
        self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.client.logout()

    def test_the_panel_links_to_every_chamber(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:panel")).content.decode()
        self.assertIn("Member lytics", body)
        self.assertIn("Author lytics", body)
        self.assertIn("Story lytics", body)
        self.assertIn("Partner lytics", body)
        #   Staff lytics is gone: it duplicated Author lytics.
        self.assertNotIn("Staff lytics", body)

    def test_the_staff_chamber_is_gone(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse("control:staff_lytics")

    def test_the_chamber_rail_drops_staff_and_keeps_author(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("Author", body)
        self.assertNotIn(">Staff<", body)
        self.assertNotIn(reverse("control:author_lytics").replace("/author/", "/staff/"), body)

    def test_the_story_chamber_is_a_real_shell_not_a_placeholder(self):
        self.assertEqual(self.client.get(reverse("control:story_lytics")).status_code, 302)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(reverse("control:story_lytics")).status_code, 302)
        self.client.logout()
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("Story lytics", body)
        self.assertIn("analytics-stories-body", body)
        self.assertIn("analytics-reading-body", body)
        self.assertIn("analytics-story-perf-body", body)
        self.assertNotIn("analytics-placeholder", body)

    def test_the_story_shell_carries_the_how_it_works_guide(self):
        self.client.force_login(self.admin)
        body = self.client.get(reverse("control:story_lytics")).content.decode()
        self.assertIn("data-guide-open", body)
        self.assertIn("data-guide-body", body)
        for title in ["Stories per week", "Reading &amp; editorial", "Story performance"]:
            with self.subTest(title=title):
                self.assertIn('data-guide-title="%s"' % title, body)


class AuthorLyticsTests(TestCase):
    """The Author lytics chamber (control:author_lytics and its fragments).

    It replaced the old Staff placeholder. Everything is windowed to one range
    and counted from the event tables, so an author's reads here mean the same
    as a read anywhere else in lytics. The named-likes list is the point of the
    chamber: a like always belongs to a signed-in reader, so it always carries a
    name.
    """

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

        self.admin = Auth.objects.create_admin(email="author-admin@example.com")
        self.writer = Auth.objects.create_staff(email="author-writer@example.com")
        self.other_writer = Auth.objects.create_staff(email="author-second@example.com")
        self.member = Auth.objects.create_user(email="author-member@example.com")
        self.other_member = Auth.objects.create_user(email="author-member-two@example.com")

        StaffProfile.objects.create(auth=self.writer, gender="O", full_name="Ada Writer")

        self.shell_url = reverse("control:author_lytics")
        self.table_url = reverse("control:analytics_authors")
        self.kpis_url = reverse("control:analytics_author_kpis")
        self.likes_url = reverse("control:analytics_author_likes")
        self.detail_url = reverse("control:analytics_author_detail")
        self.compare_url = reverse("control:analytics_author_compare")
        self.performance_url = reverse("control:analytics_author_performance")

    def make_story(self, heading, author=None, age_days=0):
        story = Blog.objects.create(
            author=author or self.writer, heading=heading, category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg",
        )
        Blog.objects.filter(pk=story.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )
        return story

    def add_view(self, story, age_days=0, user=None):
        view = StoryView.objects.create(blog=story, user=user)
        StoryView.objects.filter(pk=view.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        return view

    def add_like(self, story, user, age_days=0):
        like = BlogLike.objects.create(blog=story, user=user)
        BlogLike.objects.filter(pk=like.pk).update(
            created_at=timezone.now() - timedelta(days=age_days)
        )
        return like

    def add_comment(self, story, age_days=0):
        comment = Comment.objects.create(blog=story, author=self.member, content="Nice.")
        Comment.objects.filter(pk=comment.pk).update(
            date_created=timezone.now() - timedelta(days=age_days)
        )
        return comment

    #   ------------------------------------------------------------ access
    def test_every_endpoint_is_admin_only(self):
        for url in [
            self.shell_url,
            self.table_url,
            self.kpis_url,
            self.likes_url,
            self.detail_url,
            self.compare_url,
            self.performance_url,
        ]:
            with self.subTest(url=url):
                self.client.force_login(self.writer)
                self.assertEqual(self.client.get(url).status_code, 302 if url == self.shell_url else 403)
                self.client.logout()
                self.client.force_login(self.admin)
                self.assertEqual(self.client.get(url).status_code, 200)
                self.client.logout()

    #   ------------------------------------------------------------ shell
    def test_the_shell_is_a_real_shell_not_a_placeholder(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.shell_url).content.decode()
        self.assertIn("<h1 class=\"analytics-title\">Authors</h1>", body)
        self.assertIn("analytics-author-kpis-body", body)
        self.assertIn("analytics-authors-body", body)
        self.assertIn("analytics-author-detail-body", body)
        self.assertIn("analytics-author-compare-body", body)
        self.assertIn("analytics-author-likes-body", body)
        #   The comparison owns its window controls, so custom dating is
        #   reachable without changing the leaderboard beside it.
        self.assertIn("analytics-compare-window-row", body)
        self.assertIn('name="start"', body)
        self.assertIn('name="end"', body)
        #   The layout is a master and a detail side by side, not a stack.
        self.assertIn("analytics-author-split", body)
        self.assertNotIn("analytics-placeholder", body)

    def test_the_shell_carries_the_chamber_rail_with_author_current(self):
        self.client.force_login(self.admin)
        body = self.client.get(self.shell_url).content.decode()
        self.assertIn(reverse("control:analytics"), body)
        self.assertIn(reverse("control:story_lytics"), body)
        self.assertIn('aria-current="page"', body)

    #   ------------------------------------------------------------ leaderboard
    def test_the_leaderboard_ranks_authors_by_windowed_reads(self):
        busy = self.make_story("Busy story")
        quiet = self.make_story("Quiet story", author=self.other_writer)
        for _ in range(3):
            self.add_view(busy)
        self.add_view(quiet)

        self.client.force_login(self.admin)
        body = self.client.get(self.table_url, {"range": "30d"}).content.decode()
        #   The staff full name wins for the writer who has a profile; the other
        #   writer is only known by their masked (uppercased) email.
        self.assertIn("Ada Writer", body)
        self.assertIn("A***D@EXAMPLE.COM", body)
        # busy writer is ranked above the quiet one
        self.assertLess(body.index("Ada Writer"), body.index("A***D@EXAMPLE.COM"))

    def test_stale_reads_fall_out_of_a_shorter_range(self):
        #   Published and read forty days ago, so the author is invisible in a
        #   seven-day window on both counts.
        story = self.make_story("Old reader", age_days=40)
        self.add_view(story, age_days=40)

        self.client.force_login(self.admin)
        body = self.client.get(self.table_url, {"range": "7d"}).content.decode()
        self.assertNotIn("Ada Writer", body)

    def test_an_unknown_range_falls_back_to_the_default(self):
        self.make_story("Fallback story")
        self.client.force_login(self.admin)
        response = self.client.get(self.table_url, {"range": "nonsense"})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        #   The list labels the window in words ("7 days ago" for the default),
        #   and the author who published in it is listed.
        self.assertIn("7 days ago", body)
        self.assertIn("Ada Writer", body)

    #   ------------------------------------------------------------ KPIs
    def test_the_kpi_strip_counts_reads_and_named_likes(self):
        story = self.make_story("KPI story")
        self.add_view(story, user=self.member)
        self.add_view(story)
        self.add_like(story, self.member)

        self.client.force_login(self.admin)
        body = self.client.get(self.kpis_url, {"range": "30d"}).content.decode()
        self.assertIn("Last 30 days", body)
        self.assertIn("published", body)
        self.assertIn("by name", body)
        # two reads, one like
        self.assertRegex(body, r"analytics-author-figure-value\">2<")
        self.assertRegex(body, r"analytics-author-figure-value\">1<")

    #   ------------------------------------------------------------ custom window
    def test_a_custom_since_narrows_the_window(self):
        recent = self.make_story("Recent story", age_days=1)
        older = self.make_story("Older story", age_days=10)
        self.add_view(recent, age_days=1)
        self.add_view(older, age_days=10)

        self.client.force_login(self.admin)
        since = (timezone.localdate() - timedelta(days=2)).isoformat()
        kpis = self.client.get(self.kpis_url, {"range": "30d", "since": since}).content.decode()
        self.assertIn("Since", kpis)

        #   Only the recent story's read survives the narrower window, so the one
        #   author shows a single read rather than two.
        body = self.client.get(self.table_url, {"range": "30d", "since": since}).content.decode()
        self.assertIn("1 read", body)
        self.assertNotIn("2 reads", body)

    def test_a_since_date_in_the_future_is_ignored(self):
        self.make_story("Present story")
        self.client.force_login(self.admin)
        tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
        body = self.client.get(self.table_url, {"range": "30d", "since": tomorrow}).content.decode()
        #   Falls back to the preset, so the label is the preset's, not a "Since".
        self.assertNotIn("Since", body)
        self.assertIn("30 days ago", body)

    def test_a_junk_since_date_is_ignored(self):
        self.make_story("Present story")
        self.client.force_login(self.admin)
        body = self.client.get(self.table_url, {"range": "30d", "since": "not-a-date"}).content.decode()
        self.assertNotIn("Since", body)

    def test_the_window_labels_read_as_words(self):
        self.make_story("Some story")
        self.client.force_login(self.admin)
        body = self.client.get(self.kpis_url, {"range": "7d"}).content.decode()
        self.assertIn("Last 7 days", body)
        self.assertIn("7 days ago", body)

    #   ------------------------------------------------------------ pagination
    def test_the_author_list_pages(self):
        #   One distinct author per story, so the list is long enough to page.
        for index in range(15):
            author = Auth.objects.create_staff(email=f"paged-author-{index}@example.com")
            self.make_story(f"Paged story {index}", author=author)

        self.client.force_login(self.admin)
        first = self.client.get(self.table_url, {"range": "30d", "page": 1}).content.decode()
        second = self.client.get(self.table_url, {"range": "30d", "page": 2}).content.decode()

        self.assertEqual(first.count('<li class="analytics-author-item'), 12)
        self.assertEqual(second.count('<li class="analytics-author-item'), 3)
        self.assertNotEqual(first, second)

    def test_a_page_number_past_the_end_is_a_404(self):
        self.make_story("Only story")
        self.client.force_login(self.admin)
        response = self.client.get(self.table_url, {"range": "30d", "page": 99})
        self.assertEqual(response.status_code, 404)

    def test_the_likers_list_pages_inside_the_detail(self):
        story = self.make_story("Popular story")
        for index in range(10):
            reader = Auth.objects.create_user(email=f"liker-{index}@example.com")
            self.add_like(story, reader)

        self.client.force_login(self.admin)
        first = self.client.get(
            self.detail_url, {"author": self.writer.pk, "range": "30d", "likes_page": 1}
        ).content.decode()
        second = self.client.get(
            self.detail_url, {"author": self.writer.pk, "range": "30d", "likes_page": 2}
        ).content.decode()

        #   Eight likers a page, ten in total.
        self.assertEqual(first.count('<li class="analytics-author-liker">'), 8)
        self.assertEqual(second.count('<li class="analytics-author-liker">'), 2)

    #   ------------------------------------------------------------ named likes
    def test_the_likes_list_names_every_liker(self):
        story = self.make_story("Liked story")
        self.add_like(story, self.member)
        self.add_like(story, self.other_member)

        self.client.force_login(self.admin)
        body = self.client.get(self.likes_url, {"range": "30d"}).content.decode()
        self.assertIn("A***R@EXAMPLE.COM", body)
        self.assertIn("A***O@EXAMPLE.COM", body)
        self.assertIn("Liked story", body)

    def test_the_likes_list_is_windowed_and_pages(self):
        story = self.make_story("Windowed likes")
        self.add_like(story, self.member)
        self.add_like(story, self.other_member, age_days=40)

        self.client.force_login(self.admin)
        body = self.client.get(self.likes_url, {"range": "7d"}).content.decode()
        self.assertIn("A***R@EXAMPLE.COM", body)
        self.assertNotIn("A***O@EXAMPLE.COM", body)

    def test_the_likes_list_never_shows_a_full_address(self):
        story = self.make_story("Masked likes")
        self.add_like(story, self.member)

        self.client.force_login(self.admin)
        body = self.client.get(self.likes_url, {"range": "30d"}).content.decode()
        self.assertIn("A***R@EXAMPLE.COM", body)
        self.assertNotIn("AUTHOR-MEMBER@EXAMPLE.COM", body)

    #   ------------------------------------------------------------ detail
    def test_the_detail_matches_the_leaderboard_for_the_same_author(self):
        story = self.make_story("Detail story")
        for _ in range(4):
            self.add_view(story)
        self.add_like(story, self.member)

        self.client.force_login(self.admin)
        body = self.client.get(
            self.detail_url, {"author": self.writer.pk, "range": "30d"}
        ).content.decode()
        self.assertIn("Ada Writer", body)
        self.assertIn("Detail story", body)
        self.assertIn("A***R@EXAMPLE.COM", body)

    def test_author_story_totals_distinguish_the_window_from_all_time(self):
        self.make_story("Recent count story")
        self.make_story("Older count story", age_days=40)

        self.client.force_login(self.admin)
        leaderboard = self.client.get(self.table_url, {"range": "30d"}).content.decode()
        detail = self.client.get(
            self.detail_url, {"author": self.writer.pk, "range": "30d"}
        ).content.decode()

        self.assertIn("1 published in range", leaderboard)
        self.assertIn("2 all time", leaderboard)
        self.assertIn("published in range", detail)
        self.assertIn("2 all time", detail)
        self.assertIn("All stories", detail)

    def test_the_detail_for_an_unknown_author_degrades_quietly(self):
        self.client.force_login(self.admin)
        body = self.client.get(
            self.detail_url, {"author": 999999, "range": "30d"}
        ).content.decode()
        self.assertIn("data-author-detail-hint", body)

    def test_the_detail_rejects_a_non_numeric_author(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.detail_url, {"author": "abc", "range": "30d"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("data-author-detail-hint", response.content.decode())

    #   ------------------------------------------------------------ performance chart
    def test_the_detail_includes_the_performance_chart(self):
        self.make_story("Charted story")

        self.client.force_login(self.admin)
        body = self.client.get(
            self.detail_url, {"author": self.writer.pk, "range": "30d"}
        ).content.decode()

        self.assertIn("Performance over time", body)
        self.assertIn("analytics-author-performance-body", body)
        self.assertIn("analytics-author-performance-data", body)
        self.assertIn(self.performance_url, body)

    def test_the_author_performance_chart_counts_the_whole_portfolio(self):
        first = self.make_story("First story")
        second = self.make_story("Second story")
        other = self.make_story("Someone else's story", author=self.other_writer)

        self.add_view(first)
        self.add_view(second)
        self.add_like(first, self.member)
        self.add_comment(second)

        #   The other author's events must not leak into this author's chart.
        self.add_view(other)
        self.add_like(other, self.member)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.performance_url,
                {"author": self.writer.pk, "bucket": "day", "range": "30d"},
            ),
            "analytics-author-performance-data",
        )
        totals = {series["key"]: sum(series["values"]) for series in chart["series"]}
        self.assertEqual(totals, {"stories": 2, "views": 2, "likes": 1, "comments": 1})
        self.assertEqual(chart["author"]["id"], self.writer.pk)
        self.assertEqual(chart["author"]["stories"], 2)

    def test_the_author_performance_chart_includes_published_stories(self):
        self.make_story("Fresh story")
        self.make_story("Stale story", age_days=40)

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.performance_url,
                {
                    "submitted": "1",
                    "author": self.writer.pk,
                    "bucket": "day",
                    "range": "30d",
                    "series": ["stories"],
                },
            ),
            "analytics-author-performance-data",
        )

        self.assertEqual([series["key"] for series in chart["series"]], ["stories"])
        self.assertEqual(sum(chart["series"][0]["values"]), 1)

    def test_the_author_performance_chart_honours_the_series_toggles(self):
        self.add_view(self.make_story("Series story"))

        self.client.force_login(self.admin)
        chart = _chart_data(
            self,
            self.client.get(
                self.performance_url,
                {
                    "submitted": "1",
                    "author": self.writer.pk,
                    "series": ["likes", "comments"],
                },
            ),
            "analytics-author-performance-data",
        )
        self.assertEqual([series["key"] for series in chart["series"]], ["likes", "comments"])

    def test_the_author_performance_chart_degrades_for_an_unknown_author(self):
        self.client.force_login(self.admin)
        body = self.client.get(
            self.performance_url, {"author": 999999, "range": "30d"}
        ).content.decode()
        self.assertIn("No stories yet", body)
        self.assertNotIn("analytics-author-performance-data", body)

    #   ------------------------------------------------------------ comparison
    def test_the_compare_board_scores_two_authors_side_by_side(self):
        first = self.make_story("First compare story")
        second = self.make_story("Second compare story")
        rival = self.make_story("Rival story", author=self.other_writer)

        for _ in range(3):
            self.add_view(first)
        self.add_view(second)
        self.add_like(first, self.member)
        self.add_like(first, self.other_member)
        self.add_comment(second)

        self.add_view(rival)
        self.add_like(rival, self.member)

        self.client.force_login(self.admin)
        body = self.client.get(
            self.compare_url,
            {"a": self.writer.pk, "b": self.other_writer.pk, "range": "30d"},
        ).content.decode()

        self.assertIn("analytics-compare-board", body)
        self.assertIn("Ada Writer", body)
        self.assertIn("A***D@EXAMPLE.COM", body)
        self.assertIn("metrics won", body)
        #   Both the windowed output row and the reader-response rows are drawn.
        for label in ("Stories published", "Stories all time", "Reads", "Likes", "Comments", "Likes per 100 reads"):
            with self.subTest(label=label):
                self.assertIn(label, body)
        #   Ada published twice and read four times; the rival published and
        #   was read once, so Ada's values lead those rows.
        self.assertIn("analytics-compare-row is-a-win", body)

    def test_the_compare_board_needs_two_different_authors(self):
        self.client.force_login(self.admin)

        missing = self.client.get(
            self.compare_url, {"a": self.writer.pk, "range": "30d"}
        ).content.decode()
        self.assertIn("Pick two authors to see them side by side.", missing)

        same = self.client.get(
            self.compare_url,
            {"a": self.writer.pk, "b": self.writer.pk, "range": "30d"},
        ).content.decode()
        self.assertIn("Pick two different authors to compare.", same)

        unknown = self.client.get(
            self.compare_url,
            {"a": self.writer.pk, "b": 999999, "range": "30d"},
        ).content.decode()
        self.assertIn("One of those authors no longer exists.", unknown)

    def test_the_compare_board_uses_the_same_window_as_the_detail(self):
        story = self.make_story("Windowed compare story")
        self.add_view(story)

        self.client.force_login(self.admin)
        body = self.client.get(
            self.compare_url,
            {"a": self.writer.pk, "b": self.other_writer.pk, "range": "30d"},
        ).content.decode()

        self.assertIn("Windowed figures cover Last 30 days", body)
        self.assertIn("30 days ago", body)

    def test_the_compare_board_accepts_a_custom_start_and_end(self):
        story = self.make_story("Archived compare story", age_days=30)
        self.add_view(story, age_days=10)  # inside the custom window
        self.add_view(story, age_days=1)  # after the custom end, so excluded

        self.client.force_login(self.admin)
        start = (timezone.localdate() - timedelta(days=15)).isoformat()
        end = (timezone.localdate() - timedelta(days=5)).isoformat()
        body = self.client.get(
            self.compare_url,
            {
                "a": self.writer.pk,
                "b": self.other_writer.pk,
                "range": "7d",
                "start": start,
                "end": end,
            },
        ).content.decode()

        self.assertIn("analytics-compare-board", body)
        self.assertIn("11-day window", body)
        rows = re.findall(r'<li class="analytics-compare-row[^"]*">(.*?)</li>', body, re.S)
        reads_row = next(row for row in rows if 'analytics-compare-label">Reads<' in row)
        self.assertIn('analytics-compare-value is-a">1<', reads_row)

    def test_an_incomplete_custom_compare_window_falls_back_to_the_preset(self):
        self.make_story("Present compare story")

        self.client.force_login(self.admin)
        start = (timezone.localdate() - timedelta(days=2)).isoformat()
        body = self.client.get(
            self.compare_url,
            {
                "a": self.writer.pk,
                "b": self.other_writer.pk,
                "range": "30d",
                "start": start,
            },
        ).content.decode()

        self.assertIn("Windowed figures cover Last 30 days", body)
        self.assertIn("30 days ago", body)
        self.assertNotIn("day window", body)


class AuthorLyticsInsightsTests(TestCase):
    """The rank, rhythm, readership and reader response charts that used to sit
    on the public portfolio now live in the author detail panel."""

    def setUp(self):
        self.admin = Auth.objects.create_admin(email="insight-admin@example.com")
        self.writer = Auth.objects.create_staff(email="insight-writer@example.com")
        StaffProfile.objects.create(auth=self.writer, gender="O", full_name="Ines Writer")

    def _detail(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse("control:analytics_author_detail"), {"author": self.writer.pk})

    def test_panel_draws_every_chart_for_an_author_with_stories(self):
        Blog.objects.create(
            author=self.writer, heading="Insight story", category="NEWS",
            content="Body.", image_1="https://example.com/a.jpg", views=12, likes=3,
        )

        body = self._detail().content.decode()

        for heading in ("Author rank", "Publishing rhythm", "Readership by category", "Reader response"):
            with self.subTest(heading=heading):
                self.assertIn(heading, body)
        self.assertIn("Insight story", body)

    def test_panel_tells_the_admin_when_there_is_nothing_to_chart(self):
        body = self._detail().content.decode()

        self.assertIn("nothing to chart", body)
        self.assertNotIn("Publishing rhythm", body)


@override_settings(CACHES=ISOLATED_CACHE)
class PanelSiteSettingsUpdateTests(TestCase):
    """The ads WhatsApp number is edited from PANEL, and saving it must clear
    the cached settings row the context processor otherwise keeps forever."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        patcher = mock.patch("ADMIN.views.is_rate_limited", return_value=(0, False))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = Auth.objects.create_admin(email="settings-admin@example.com")

    def test_ads_whatsapp_support_is_saved_and_settings_cache_is_cleared(self):
        cache.set("site_settings_socials", {"twitter_handle": "old"}, None)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("control:panel_settings"),
            {"ads_whatsapp_support": "+234 800 123 4567"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            SiteSettings.get_solo().ads_whatsapp_support,
            "+234 800 123 4567",
        )
        self.assertIsNone(cache.get("site_settings_socials"))


@override_settings(CACHES=ISOLATED_CACHE)
class PanelAdvertLeadTests(TestCase):
    """The public partner form saves an AdvertLead, and PANEL must show it to
    the ads team instead of leaving it only in the Django admin."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        patcher = mock.patch("AUTHENTICATION.signals._try_send_login_email")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = Auth.objects.create_admin(email="leads-admin@example.com")

    def test_panel_lists_the_latest_advert_enquiries(self):
        AdvertLead.objects.create(
            plan="pro",
            business_name="Grace Stores",
            contact_email="grace@example.com",
            whatsapp_number="+2348011112222",
            business_details="We sell fabrics in Kano.",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("control:panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Advert enquiries")
        self.assertContains(response, "Grace Stores")
        self.assertContains(response, "grace@example.com")
        self.assertContains(response, "We sell fabrics in Kano.")


@override_settings(CACHES=ISOLATED_CACHE)
class AdvertReferenceDeskTests(TestCase):
    """The ads desk is a limited staff surface, not full PANEL access."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        patcher = mock.patch("ADMIN.views.is_rate_limited", return_value=(0, False))
        patcher.start()
        self.addCleanup(patcher.stop)
        #   Account creation fires login/welcome emails on the global executor.
        #   Keep this desk's many fixtures from queueing jobs that land in a
        #   later test's mocked resend.Emails.send.
        for target in (
            "SERVICE_INTERNAL.email_single._EMAIL_EXECUTOR",
            "SERVICE_INTERNAL.email_batch._EMAIL_EXECUTOR",
        ):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.admin = Auth.objects.create_admin(email="ads-desk-admin@example.com")
        self.ads_staff = Auth.objects.create_user(
            email="ads-desk-staff@example.com", is_ads_staff=True
        )
        self.member = Auth.objects.create_user(email="ads-desk-reader@example.com")
        self.owner = Auth.objects.create_user(email="grace.owner@example.com")
        self.other_owner = Auth.objects.create_user(email="other.owner@example.com")
        self.advert = self._advert("Desk advert")
        self.second_advert = self._advert("Second desk advert")

    def _advert(self, heading):
        return AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading=heading,
            image_url="https://cdn.example.com/ads/desk.jpg",
            url="https://example.com/desk",
        )

    def _reference(self, advert=None, owner=None, **kwargs):
        values = {
            "user": owner or self.owner,
            "plan": AdvertLead.PLAN_REGULAR,
            "business_name": "Desk Business",
        }
        values.update(kwargs)
        return AdvertReference.objects.create(advert=advert or self.advert, **values)

    def _storage_file(self, reference, public_id="abureport/advert-storage/brief", name="brief.pdf"):
        return AdvertReferenceFile.objects.create(
            reference=reference,
            uploaded_by=self.ads_staff,
            original_filename=name,
            note="Final brief",
            content_type="application/pdf",
            resource_type="raw",
            public_id=public_id,
            secure_url="https://res.cloudinary.com/demo/raw/upload/v1/" + public_id,
            file_size=12,
        )

    def _issue_payload(self, **overrides):
        values = {
            "email": self.owner.email,
            "plan": AdvertLead.PLAN_PRO,
            "business_name": "Grace Stores",
            "starts_at": "",
            "expires_at": "",
            "public_url": "",
            "advert_id": str(self.advert.pk),
            "notes": "Paid by transfer.",
        }
        values.update(overrides)
        return values

    def test_create_staff_can_grant_ads_desk_access_without_admin_rights(self):
        self.client.force_login(self.admin)
        with mock.patch("ADMIN.views._try_send_staff_welcome_email"), mock.patch(
            "ADMIN.views._try_send_staff_created_batch_email"
        ):
            response = self.client.post(
                reverse("control:staff_create"),
                {
                    "email": "new-ads-staff@example.com",
                    "password": "Str0ngPass1!",
                    "full_name": "New Ads Staff",
                    "gender": "F",
                    "role": "JOURNALIST",
                    "is_ads_staff": "on",
                },
            )

        self.assertEqual(response.status_code, 302)
        account = Auth.objects.get(email__iexact="new-ads-staff@example.com")
        self.assertTrue(account.is_ads_staff)
        self.assertFalse(account.is_admin)
        self.assertTrue(StaffProfile.objects.filter(auth=account).exists())

    def test_staff_detail_toggle_is_admin_only_and_toggles_the_flag(self):
        target = Auth.objects.create_staff(email="toggle-target@example.com")
        StaffProfile.objects.create(
            auth=target, gender="M", full_name="Toggle Target", role="JOURNALIST"
        )
        endpoint = reverse("control:staff_ads_access", args=[target.pk])

        self.client.force_login(self.ads_staff)
        denied = self.client.post(endpoint)
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.admin)
        granted = self.client.post(endpoint)
        self.assertEqual(granted.status_code, 200)
        self.assertTrue(granted.json()["is_ads_staff"])
        target.refresh_from_db()
        self.assertTrue(target.is_ads_staff)

        removed = self.client.post(endpoint)
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(removed.json()["is_ads_staff"])
        target.refresh_from_db()
        self.assertFalse(target.is_ads_staff)

    def test_ads_staff_can_open_the_desk_but_not_panel(self):
        self.client.force_login(self.ads_staff)

        desk = self.client.get(reverse("control:advert_references"))
        self.assertEqual(desk.status_code, 200)
        self.assertContains(desk, "Advert references")

        panel = self.client.get(reverse("control:panel"))
        self.assertRedirects(
            panel, reverse("home:profile"), fetch_redirect_response=False
        )

        self.client.force_login(self.member)
        blocked = self.client.get(reverse("control:advert_references"))
        self.assertRedirects(
            blocked, reverse("home:profile"), fetch_redirect_response=False
        )

    def test_ads_staff_can_issue_a_reference_tied_to_the_account_email(self):
        self.client.force_login(self.ads_staff)

        response = self.client.post(
            reverse("control:advert_references"), self._issue_payload()
        )

        self.assertEqual(response.status_code, 302)
        reference = AdvertReference.objects.get()
        self.assertEqual(reference.user, self.owner)
        self.assertEqual(reference.email_used, self.owner.email)
        self.assertEqual(reference.issued_by, self.ads_staff)
        self.assertEqual(reference.advert, self.advert)
        self.assertEqual(len(reference.reference), 16)
        self.assertTrue(reference.reference.startswith("GRACE"))
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_advertiser)

    def test_subdomain_is_saved_and_cannot_be_reused_by_another_advert(self):
        self.client.force_login(self.ads_staff)
        url = reverse("control:advert_references")

        first = self.client.post(url, self._issue_payload(subdomain="NewAds"))
        self.assertEqual(first.status_code, 302)
        self.assertEqual(AdvertReference.objects.get().subdomain, "newads")

        duplicate = self.client.post(
            url,
            self._issue_payload(
                email=self.other_owner.email,
                advert_id=str(self.second_advert.pk),
                subdomain="newads",
            ),
        )
        self.assertContains(
            duplicate, "Another advert already uses that subdomain.", status_code=400
        )
        self.assertEqual(AdvertReference.objects.count(), 1)

    def test_reserved_or_dotted_subdomains_are_refused(self):
        self.client.force_login(self.ads_staff)
        url = reverse("control:advert_references")

        for bad in ("ads", "www", "a.b"):
            response = self.client.post(url, self._issue_payload(subdomain=bad))
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(AdvertReference.objects.count(), 0)

    def test_a_subdomain_must_be_a_valid_web_address_label(self):
        self.client.force_login(self.ads_staff)
        url = reverse("control:advert_references")
        for bad in ("my_shop", "-shop", "shop-", "Shop Name", "a" * 64, "shop.site"):
            response = self.client.post(url, self._issue_payload(plan=AdvertLead.PLAN_PRO, subdomain=bad))
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(AdvertReference.objects.count(), 0)
        good = self.client.post(url, self._issue_payload(plan=AdvertLead.PLAN_PRO, subdomain="my-shop"))
        self.assertEqual(good.status_code, 302)

    def test_regular_plan_cannot_take_a_subdomain(self):
        self.client.force_login(self.ads_staff)
        response = self.client.post(
            reverse("control:advert_references"),
            self._issue_payload(plan=AdvertLead.PLAN_REGULAR, subdomain="newads"),
        )
        self.assertContains(response, "does not include a custom subdomain", status_code=400)
        self.assertEqual(AdvertReference.objects.count(), 0)

    def test_paid_plans_need_a_subdomain_unless_an_external_link_is_set(self):
        self.client.force_login(self.ads_staff)
        url = reverse("control:advert_references")
        self.advert.url = ""
        self.advert.save(update_fields=["url"])

        blocked = self.client.post(
            url, self._issue_payload(plan=AdvertLead.PLAN_PRO)
        )
        self.assertContains(blocked, "need a subdomain", status_code=400)
        self.assertEqual(AdvertReference.objects.count(), 0)

        #   A Public page URL is the other allowed way to open a paid advert.
        external = self.client.post(
            url,
            self._issue_payload(
                plan=AdvertLead.PLAN_ADVANCE,
                public_url="https://shop.example.com/campaign",
            ),
        )
        self.assertEqual(external.status_code, 302)
        self.assertEqual(AdvertReference.objects.get().subdomain, None)

    def test_ads_desk_warns_when_a_paid_advert_has_no_custom_landing_page(self):
        self.client.force_login(self.ads_staff)
        row = self._reference(plan=AdvertLead.PLAN_PRO, subdomain="newads")

        response = self.client.get(reverse("control:advert_references"))
        self.assertContains(response, "This plan is on Pro and no landing page was detected.")
        self.assertContains(response, "advertisement is being built")

        AdvertLandingPage.objects.create(
            advert=self.advert,
            author=self.admin,
            html_public_id="abureport/advert-landing/desk.html",
            is_published=True,
        )
        response = self.client.get(reverse("control:advert_references"))
        self.assertNotContains(response, "no landing page was detected")
        self.assertTrue(row.is_live)

    def test_button_press_from_the_page_returns_the_card_without_a_reload(self):
        reference = self._reference(expires_at=timezone.now() + timedelta(days=10))
        self.client.force_login(self.ads_staff)
        response = self.client.post(
            reverse("control:advert_reference_renew", args=[reference.pk]),
            {"days": "7"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="ref-{reference.pk}"')
        self.assertIn("adsToast", response["HX-Trigger"])
        reference.refresh_from_db()
        self.assertGreater(reference.expires_at, timezone.now() + timedelta(days=16))

    def test_remove_seven_days_never_moves_the_end_into_the_past(self):
        reference = self._reference(expires_at=timezone.now() + timedelta(days=20))
        self.client.force_login(self.ads_staff)
        url = reverse("control:advert_reference_shorten", args=[reference.pk])

        self.client.post(url, {"days": "7"}, HTTP_HX_REQUEST="true")
        reference.refresh_from_db()
        self.assertLess(reference.expires_at, timezone.now() + timedelta(days=14))

        #   13 days left: removing 7 is fine, 6 days left after that, so the next one is refused.
        self.client.post(url, {"days": "7"}, HTTP_HX_REQUEST="true")
        before = AdvertReference.objects.get(pk=reference.pk).expires_at
        refused = self.client.post(url, {"days": "7"}, HTTP_HX_REQUEST="true")
        self.assertIn("past", refused["HX-Trigger"])
        self.assertEqual(AdvertReference.objects.get(pk=reference.pk).expires_at, before)

    def test_the_link_comes_from_the_reference_and_not_from_the_panel(self):
        self.client.force_login(self.ads_staff)
        self.client.post(
            reverse("control:advert_references"),
            self._issue_payload(plan=AdvertLead.PLAN_PRO, public_url="https://shop.example.org/offer", advert_id=str(self.advert.pk)),
        )
        self.advert.refresh_from_db()
        self.assertEqual(self.advert.url, "https://shop.example.org/offer")

        from django.http import QueryDict
        from ADMIN.views import _clean_image_advert

        post = QueryDict("heading=Hello&body=Text&expiry_date=2030-01-01T10:00&url=https://elsewhere.example.com")
        values, error = _clean_image_advert(post)
        self.assertIsNone(error)
        self.assertNotIn("url", values)

    def test_extra_pages_screen_is_for_admins_and_the_advance_plan_only(self):
        advance = self._reference(plan=AdvertLead.PLAN_ADVANCE)
        pro = self._reference(advert=self.second_advert, owner=self.other_owner, plan=AdvertLead.PLAN_PRO)

        self.client.force_login(self.ads_staff)
        self.assertEqual(self.client.get(reverse("control:advert_pages", args=[advance.pk])).status_code, 302)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("control:advert_pages", args=[pro.pk])).status_code, 302)
        self.assertEqual(self.client.get(reverse("control:advert_pages", args=[advance.pk])).status_code, 200)

        upload = {"public_id": "abureport/advert-landing/advert_x_p_about.html", "bytes": 40, "secure_url": ""}
        with mock.patch("ADMIN.views.upload_advert_landing_html", return_value=upload):
            bad = self.client.post(reverse("control:advert_pages", args=[advance.pk]), {"path": "About Us!", "html": "<p>x</p>"})
            good = self.client.post(
                reverse("control:advert_pages", args=[advance.pk]),
                {"path": "about", "html": "<!doctype html><p>About</p>", "is_published": "1"},
            )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(good.status_code, 302)
        self.assertEqual(AdvertPage.objects.get(advert=self.advert).path, "about")

    def test_unknown_email_and_a_second_reference_for_the_same_advert_are_refused(self):
        self.client.force_login(self.admin)

        unknown = self.client.post(
            reverse("control:advert_references"),
            self._issue_payload(
                email="nobody@example.com", business_name="Nobody", advert_id=""
            ),
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertContains(
            unknown, "No account uses that email", status_code=400
        )
        self.assertEqual(AdvertReference.objects.count(), 0)

        first = self._reference()
        duplicate = self.client.post(
            reverse("control:advert_references"), self._issue_payload()
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertContains(
            duplicate, "That advert already has a reference", status_code=400
        )
        self.assertEqual(AdvertReference.objects.count(), 1)
        self.assertEqual(AdvertReference.objects.get(), first)

    def test_pause_resume_and_renew_keep_the_same_reference(self):
        reference = self._reference(
            expires_at=timezone.now() + timedelta(days=2)
        )
        self.client.force_login(self.ads_staff)

        paused = self.client.post(
            reverse("control:advert_reference_status", args=[reference.pk]),
            {"action": "pause"},
        )
        self.assertEqual(paused.status_code, 302)
        reference.refresh_from_db()
        self.assertEqual(reference.status, AdvertReference.STATUS_PAUSED)
        self.assertFalse(reference.is_live)

        resumed = self.client.post(
            reverse("control:advert_reference_status", args=[reference.pk]),
            {"action": "resume"},
        )
        self.assertEqual(resumed.status_code, 302)
        reference.refresh_from_db()
        self.assertEqual(reference.status, AdvertReference.STATUS_ACTIVE)
        self.assertTrue(reference.is_live)

        old_expiry = reference.expires_at
        old_reference = reference.reference
        renewed = self.client.post(
            reverse("control:advert_reference_renew", args=[reference.pk]),
            {"days": "7"},
        )
        self.assertEqual(renewed.status_code, 302)
        reference.refresh_from_db()
        self.assertEqual(reference.reference, old_reference)
        self.assertGreater(reference.expires_at, old_expiry + timedelta(days=6))
        self.assertEqual(reference.status, AdvertReference.STATUS_ACTIVE)

    def test_renewing_a_paused_reference_does_not_resume_it(self):
        reference = self._reference(
            advert=self.second_advert,
            status=AdvertReference.STATUS_PAUSED,
            expires_at=timezone.now() + timedelta(days=1),
        )
        old_expiry = reference.expires_at
        self.client.force_login(self.ads_staff)

        response = self.client.post(
            reverse("control:advert_reference_renew", args=[reference.pk]),
            {"days": "7"},
        )

        self.assertEqual(response.status_code, 302)
        reference.refresh_from_db()
        self.assertEqual(reference.status, AdvertReference.STATUS_PAUSED)
        self.assertGreater(reference.expires_at, old_expiry + timedelta(days=6))

    def test_update_can_replace_the_advert_and_never_changes_the_owner(self):
        reference = self._reference()
        self.client.force_login(self.ads_staff)
        starts_at = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        expires_at = (timezone.localtime() + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M")

        response = self.client.post(
            reverse("control:advert_reference_update", args=[reference.pk]),
            {
                "email": self.other_owner.email,
                "plan": AdvertLead.PLAN_ADVANCE,
                "business_name": "Updated Business",
                "starts_at": starts_at,
                "expires_at": expires_at,
                "public_url": "https://advance.example.com/landing",
                "advert_id": str(self.second_advert.pk),
                "notes": "Replaced after review.",
            },
        )

        self.assertEqual(response.status_code, 302)
        reference.refresh_from_db()
        self.assertEqual(reference.user, self.owner)
        self.assertEqual(reference.advert, self.second_advert)
        self.assertEqual(reference.plan, AdvertLead.PLAN_ADVANCE)
        self.assertEqual(reference.business_name, "Updated Business")
        self.assertEqual(reference.public_url, "https://advance.example.com/landing")
        self.assertEqual(reference.notes, "Replaced after review.")

    def test_ads_staff_can_upload_preview_and_delete_reference_storage(self):
        reference = self._reference()
        self.client.force_login(self.ads_staff)
        upload = SimpleUploadedFile("brief.pdf", b"%PDF-1.4 demo", content_type="application/pdf")
        uploaded = {
            "secure_url": "https://res.cloudinary.com/demo/raw/upload/v1/abureport/advert-storage/brief.pdf",
            "public_id": "abureport/advert-storage/brief",
            "resource_type": "raw",
            "bytes": 12,
        }
        with mock.patch("ADMIN.views.upload_advert_storage_file", return_value=uploaded):
            response = self.client.post(
                reverse("control:advert_storage_upload", args=[reference.pk]),
                {"storage_file": upload, "note": "Final brief"},
            )

        self.assertEqual(response.status_code, 200)
        row = AdvertReferenceFile.objects.get()
        self.assertEqual(row.reference, reference)
        self.assertEqual(row.uploaded_by, self.ads_staff)
        self.assertEqual(row.note, "Final brief")
        self.assertEqual(row.public_id, "abureport/advert-storage/brief")

        modal = self.client.get(reverse("control:advert_storage_modal", args=[reference.pk]))
        self.assertContains(modal, "brief.pdf")
        self.assertContains(modal, "Final brief")
        match = re.search(r'href="(/control/ads/storage/[^"]+)"', modal.content.decode())
        self.assertIsNotNone(match)
        share_url = match.group(1)

        self.client.logout()
        with mock.patch("ADMIN.views._stream_advert_storage_asset", return_value=HttpResponse("ok")) as stream:
            shared = self.client.get(share_url)
        self.assertEqual(shared.status_code, 200)
        self.assertTrue(stream.called)
        start = share_url.index("/share/") + len("/share/")
        end = share_url.index("/", start)
        token = share_url[start:end]
        bad_token = token[:-1] + ("y" if token[-1] == "x" else "x")
        bad_url = share_url[:start] + bad_token + share_url[end:]
        self.assertEqual(self.client.get(bad_url).status_code, 403)

        self.client.force_login(self.ads_staff)
        with mock.patch("ADMIN.views.destroy_archive_asset", return_value=True) as destroy:
            response = self.client.post(
                reverse("control:advert_storage_delete", args=[reference.pk, row.pk])
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(AdvertReferenceFile.objects.exists())
        destroy.assert_called_once_with("abureport/advert-storage/brief", "raw")

    def test_reference_storage_serves_named_static_asset_with_real_mime(self):
        reference = self._reference()
        item = AdvertReferenceFile.objects.create(
            reference=reference,
            uploaded_by=self.ads_staff,
            original_filename="2:1xVxKz:GQLIw-Gud1oBMuaSew",
            note="Landing script",
            content_type="application/octet-stream",
            resource_type="raw",
            public_id="abureport/advert-storage/landing_ab12cd",
            secure_url="https://res.cloudinary.com/demo/raw/upload/v1/abureport/advert-storage/landing_ab12cd.js",
            file_size=12,
        )
        self.client.force_login(self.ads_staff)
        modal = self.client.get(reverse("control:advert_storage_modal", args=[reference.pk]))
        self.assertContains(modal, "landing_ab12cd.js")
        self.assertContains(modal, ">JS<")
        share_url = re.search(r'href="(/control/ads/storage/[^"]+)"', modal.content.decode()).group(1)
        self.assertTrue(share_url.endswith("/landing_ab12cd.js/"))

        upstream = mock.Mock(status_code=200, headers={"Content-Length": "12"})
        upstream.iter_content.return_value = [b"alert(1);"]
        self.client.logout()
        with mock.patch("ADMIN.views.requests.get", return_value=upstream):
            response = self.client.get(share_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertIn("landing_ab12cd.js", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_reference_storage_share_links_do_not_expire(self):
        reference = self._reference()
        item = self._storage_file(
            reference,
            public_id="abureport/advert-storage/styles_css123",
            name="styles.css",
        )
        old_time = timezone.now().timestamp() - (48 * 60 * 60)
        with mock.patch("django.core.signing.time.time", return_value=old_time):
            old_token = signing.TimestampSigner(salt=ADVERT_STORAGE_LINK_SALT).sign(str(item.pk))
        share_url = reverse(
            "control:advert_storage_share",
            kwargs={"file_id": item.pk, "token": old_token},
        )

        upstream = mock.Mock(status_code=200, headers={"Content-Length": "12"})
        upstream.iter_content.return_value = [b"body { color: red; }"]
        with mock.patch("ADMIN.views.requests.get", return_value=upstream):
            response = self.client.get(share_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/css")

    def test_reference_storage_keeps_html_as_an_opaque_download(self):
        reference = self._reference()
        item = AdvertReferenceFile.objects.create(
            reference=reference,
            uploaded_by=self.ads_staff,
            original_filename="page.html",
            content_type="text/html",
            resource_type="raw",
            public_id="abureport/advert-storage/page_html123",
            secure_url="https://res.cloudinary.com/demo/raw/upload/v1/abureport/advert-storage/page_html123.html",
            file_size=12,
        )
        share_url, _ = _advert_storage_share_urls(item, _advert_storage_display_name(item))

        upstream = mock.Mock(status_code=200, headers={"Content-Length": "12"})
        upstream.iter_content.return_value = [b"<p>hi</p>"]
        with mock.patch("ADMIN.views.requests.get", return_value=upstream):
            response = self.client.get(share_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertIn("page.html", response["Content-Disposition"])

    def test_cached_storage_file_advertises_its_cache_duration(self):
        reference = self._reference()
        item = self._storage_file(reference, name="styles.css")
        item.cache_seconds = 3600
        item.save(update_fields=["cache_seconds"])
        share_url, _ = _advert_storage_share_urls(
            item, _advert_storage_display_name(item)
        )

        upstream = mock.Mock(status_code=200, headers={"Content-Length": "12"})
        upstream.iter_content.return_value = [b"body{}"]
        with mock.patch("ADMIN.views.requests.get", return_value=upstream):
            response = self.client.get(share_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, max-age=3600, must-revalidate")

    def test_ads_staff_can_set_a_cache_duration_for_a_storage_file(self):
        reference = self._reference()
        item = self._storage_file(reference, name="styles.css")
        self.client.force_login(self.ads_staff)

        response = self.client.post(
            reverse("control:advert_storage_cache", args=[reference.pk, item.pk]),
            {"cache_seconds": "86400"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 day is now the cache duration")
        item.refresh_from_db()
        self.assertEqual(item.cache_seconds, 86400)
        modal = self.client.get(reverse("control:advert_storage_modal", args=[reference.pk]))
        self.assertContains(modal, "No cache (default)")
        self.assertContains(modal, "Clear cache")

    def test_ads_staff_can_clear_a_storage_file_cache(self):
        reference = self._reference()
        item = self._storage_file(reference, name="styles.css")
        item.cache_seconds = 604800
        item.save(update_fields=["cache_seconds"])
        self.client.force_login(self.ads_staff)

        with mock.patch(
            "ADMIN.views.clear_advert_storage_cache", return_value=True
        ) as clear:
            response = self.client.post(
                reverse("control:advert_storage_cache_clear", args=[reference.pk, item.pk])
            )

        self.assertEqual(response.status_code, 200)
        clear.assert_called_once_with(item.public_id, item.resource_type)
        self.assertContains(response, "Cloudinary cache cleared")

        with mock.patch(
            "ADMIN.views.clear_advert_storage_cache", return_value=True
        ) as clear:
            item.cache_seconds = 0
            item.save(update_fields=["cache_seconds"])
            no_cache = self.client.post(
                reverse("control:advert_storage_cache_clear", args=[reference.pk, item.pk])
            )
        self.assertEqual(no_cache.status_code, 200)
        clear.assert_not_called()
        self.assertContains(no_cache, "already uses No cache")

    def test_reader_cannot_change_a_storage_file_cache(self):
        reference = self._reference()
        item = self._storage_file(reference, name="styles.css")
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("control:advert_storage_cache", args=[reference.pk, item.pk]),
            {"cache_seconds": "86400"},
        )

        self.assertEqual(response.status_code, 302)

    def test_ads_staff_can_export_whole_reference_as_one_zip(self):
        reference = self._reference()
        self._storage_file(reference, name="brief.pdf")
        AdvertLandingPage.objects.create(
            advert=self.advert,
            author=self.admin,
            html_public_id="abureport/advert-landing/advert_1",
            html_bytes=11,
            is_published=True,
        )
        AdvertPage.objects.create(
            advert=self.advert,
            path="about",
            author=self.admin,
            html_public_id="abureport/advert-pages/advert_1_about",
            html_bytes=11,
        )
        self.client.force_login(self.ads_staff)

        def fake_get(url, **kwargs):
            response = mock.Mock(status_code=200)
            response.iter_content.return_value = (
                [b"BANNER"] if "desk.jpg" in url else [b"PDF"]
            )
            return response

        def fake_html(public_id):
            return "<html>landing</html>" if "landing" in public_id else "<html>about</html>"

        with mock.patch("ADMIN.views.requests.get", side_effect=fake_get), mock.patch(
            "ADMIN.views.fetch_advert_landing_html", side_effect=fake_html
        ):
            response = self.client.get(
                reverse("control:advert_storage_export", args=[reference.pk])
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            self.assertIn("uploaded/brief.pdf", names)
            self.assertIn("advert/banner.jpg", names)
            self.assertIn("pages/index.html", names)
            self.assertIn("pages/about.html", names)
            self.assertIn("README.txt", names)
            self.assertNotIn("EXPORT_ERRORS.txt", names)
            self.assertEqual(archive.read("uploaded/brief.pdf"), b"PDF")
            self.assertIn(b"Desk Business", archive.read("README.txt"))

    def test_export_reports_a_failed_cloudinary_file_without_aborting(self):
        reference = self._reference()
        self._storage_file(reference, name="broken.pdf")
        self.client.force_login(self.ads_staff)

        failed = mock.Mock(status_code=404)
        with mock.patch("ADMIN.views.requests.get", return_value=failed):
            response = self.client.get(
                reverse("control:advert_storage_export", args=[reference.pk])
            )

        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("README.txt", archive.namelist())
            self.assertIn("EXPORT_ERRORS.txt", archive.namelist())
            self.assertIn(b"no longer exists", archive.read("EXPORT_ERRORS.txt"))
            self.assertNotIn("uploaded/broken.pdf", archive.namelist())

    def test_reader_cannot_export_reference_storage(self):
        reference = self._reference()
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("control:advert_storage_export", args=[reference.pk])
        )

        self.assertEqual(response.status_code, 302)

    def test_ads_staff_can_edit_a_text_storage_file_in_place(self):
        reference = self._reference()
        item = self._storage_file(reference, public_id="abureport/advert-storage/styles", name="styles.css")
        self.client.force_login(self.ads_staff)

        upstream = mock.Mock(status_code=200)
        upstream.iter_content.return_value = [b"body { color: red; }"]
        with mock.patch("ADMIN.views.requests.get", return_value=upstream):
            editor = self.client.get(
                reverse("control:advert_storage_edit", args=[reference.pk, item.pk])
            )
        self.assertEqual(editor.status_code, 200)
        self.assertContains(editor, "body { color: red; }")
        self.assertContains(editor, "Save changes")

        with mock.patch(
            "ADMIN.views.replace_advert_storage_file",
            return_value={"bytes": 20},
        ) as replace:
            response = self.client.post(
                reverse("control:advert_storage_edit", args=[reference.pk, item.pk]),
                {"content": "body { color: blue; }", "note": "Updated stylesheet"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pages using its share URL keep the same address.")
        args = replace.call_args.args
        self.assertEqual(args[0], "body { color: blue; }")
        self.assertEqual(args[1], item.public_id)
        self.assertEqual(args[3], "css")
        item.refresh_from_db()
        self.assertEqual(item.note, "Updated stylesheet")
        self.assertEqual(item.file_size, 20)
        self.assertEqual(item.content_type, "text/css")

    def test_binary_storage_file_cannot_be_text_edited(self):
        reference = self._reference()
        item = self._storage_file(reference, public_id="abureport/advert-storage/pic", name="pic.png")
        self.client.force_login(self.ads_staff)

        response = self.client.get(
            reverse("control:advert_storage_edit", args=[reference.pk, item.pk])
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "cannot be edited", status_code=400)

    def test_reader_cannot_edit_reference_storage(self):
        reference = self._reference()
        item = self._storage_file(reference, public_id="abureport/advert-storage/styles", name="styles.css")
        self.client.force_login(self.member)

        response = self.client.get(
            reverse("control:advert_storage_edit", args=[reference.pk, item.pk])
        )

        self.assertEqual(response.status_code, 302)

    def test_reader_cannot_open_or_upload_reference_storage(self):
        reference = self._reference()
        self.client.force_login(self.member)

        modal = self.client.get(reverse("control:advert_storage_modal", args=[reference.pk]))
        upload = self.client.post(reverse("control:advert_storage_upload", args=[reference.pk]), {})

        self.assertEqual(modal.status_code, 302)
        self.assertEqual(upload.status_code, 302)
        self.assertFalse(AdvertReferenceFile.objects.exists())

    def test_oversized_reference_storage_upload_is_rejected(self):
        reference = self._reference()
        self.client.force_login(self.ads_staff)
        big = SimpleUploadedFile(
            "big.zip", b"x" * (5 * 1024 * 1024 + 1), content_type="application/zip"
        )

        with mock.patch("ADMIN.views.upload_advert_storage_file") as upload:
            response = self.client.post(
                reverse("control:advert_storage_upload", args=[reference.pk]),
                {"storage_file": big},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("limited to 5MB", response.content.decode())
        upload.assert_not_called()

    def test_reference_delete_removes_storage_and_only_checkbox_removes_advert_assets(self):
        reference = self._reference()
        self._storage_file(reference)
        AdvertLandingPage.objects.create(
            advert=self.advert,
            html_public_id="abureport/advert-landing/advert_1.html",
            html_bytes=12,
            is_published=True,
            author=self.admin,
        )
        self.client.force_login(self.ads_staff)

        with (
            mock.patch("SERVICE_INTERNAL.images.destroy_archive_asset", return_value=True) as signal_destroy,
            mock.patch("ADMIN.views.destroy_archive_asset", return_value=True) as view_destroy,
            mock.patch("ADMIN.views.destroy_advert_landing_html", return_value=True) as html_destroy,
        ):
            response = self.client.post(reverse("control:advert_reference_delete", args=[reference.pk]), {})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AdvertReference.objects.filter(pk=reference.pk).exists())
        self.assertFalse(AdvertReferenceFile.objects.exists())
        signal_destroy.assert_called_once_with("abureport/advert-storage/brief", "raw")
        view_destroy.assert_not_called()
        html_destroy.assert_not_called()
        self.assertTrue(AdvertImage.objects.filter(pk=self.advert.pk).exists())

        second_advert = self._advert("Second with assets")
        AdvertImage.objects.filter(pk=second_advert.pk).update(
            image_public_id="abureport/adverts/second",
            image_url="https://res.cloudinary.com/demo/image/upload/v1/abureport/adverts/second.jpg",
        )
        second_advert.refresh_from_db()
        second = self._reference(advert=second_advert)
        AdvertLandingPage.objects.create(
            advert=second_advert,
            html_public_id="abureport/advert-landing/advert_2.html",
            html_bytes=14,
            is_published=True,
            author=self.admin,
        )
        AdvertPage.objects.create(
            advert=second_advert,
            path="about",
            html_public_id="abureport/advert-pages/advert_2_about.html",
            html_bytes=20,
            author=self.admin,
            is_published=True,
        )
        with (
            mock.patch("SERVICE_INTERNAL.images.destroy_archive_asset", return_value=True),
            mock.patch("ADMIN.views.destroy_archive_asset", return_value=True) as view_destroy,
            mock.patch("SERVICE_INTERNAL.images.destroy_advert_landing_html", return_value=True) as landing_destroy,
            mock.patch("ADMIN.views.destroy_advert_landing_html", return_value=True) as page_destroy,
        ):
            response = self.client.post(
                reverse("control:advert_reference_delete", args=[second.pk]),
                {"delete_advert_assets": "1"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AdvertReference.objects.filter(pk=second.pk).exists())
        self.assertFalse(AdvertImage.objects.filter(pk=second_advert.pk).exists())
        view_destroy.assert_called_once_with("abureport/adverts/second")
        landing_destroy.assert_called_once_with("abureport/advert-landing/advert_2.html")
        page_destroy.assert_called_once_with("abureport/advert-pages/advert_2_about.html")

    def test_desk_lists_recent_advert_leads(self):
        AdvertLead.objects.create(
            plan=AdvertLead.PLAN_PRO,
            business_name="Lead Shop",
            contact_email="lead@example.com",
            whatsapp_number="+2348011112222",
            business_details="We sell shoes.",
        )
        self.client.force_login(self.ads_staff)

        response = self.client.get(reverse("control:advert_references"))

        self.assertContains(response, "Lead Shop")
        self.assertContains(response, "lead@example.com")


    def test_analytics_modal_works_for_regular_references_and_folds_direct_clicks(self):
        reference = self._reference(plan=AdvertLead.PLAN_REGULAR)
        AdvertEvent.objects.create(
            reference=reference, event_type=AdvertEvent.EVENT_VIEW
        )
        for source in (
            AdvertEvent.SOURCE_ABUREPORT,
            AdvertEvent.SOURCE_DIRECT,
            AdvertEvent.SOURCE_EXTERNAL,
        ):
            AdvertEvent.objects.create(
                reference=reference,
                event_type=AdvertEvent.EVENT_CLICK,
                source=source,
            )
        self.client.force_login(self.ads_staff)

        response = self.client.get(
            reverse("control:advert_analytics_modal", args=[reference.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["analytics"]["click_chart"]["values"], [1, 2]
        )
        self.assertEqual(
            response.context["analytics"]["totals"]["views"], 1
        )
        self.assertContains(response, "Where clicks come from")
        self.assertContains(response, f"ads-{reference.pk}-views")
        self.assertNotContains(response, "Analytics come with Pro")

    def test_analytics_modal_range_filters_older_events(self):
        reference = self._reference()
        now = timezone.now()
        AdvertEvent.objects.create(reference=reference, event_type=AdvertEvent.EVENT_VIEW)
        old = AdvertEvent.objects.create(
            reference=reference, event_type=AdvertEvent.EVENT_VIEW
        )
        AdvertEvent.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=20))
        self.client.force_login(self.ads_staff)

        endpoint = reverse("control:advert_analytics_modal", args=[reference.pk])
        week = self.client.get(endpoint, {"range": "7"})
        lifetime = self.client.get(endpoint, {"range": "all"})

        self.assertEqual(week.context["analytics"]["totals"]["views"], 1)
        self.assertEqual(lifetime.context["analytics"]["totals"]["views"], 2)

    def test_non_ads_staff_cannot_open_the_analytics_modal(self):
        reference = self._reference(plan=AdvertLead.PLAN_PRO)
        self.client.force_login(self.member)
        response = self.client.get(
            reverse("control:advert_analytics_modal", args=[reference.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    def test_reference_card_exposes_an_analytics_action(self):
        reference = self._reference()
        self.client.force_login(self.ads_staff)
        response = self.client.get(reverse("control:advert_references"))
        self.assertContains(response, "data-open-analytics")
        self.assertContains(
            response,
            reverse("control:advert_analytics_modal", args=[reference.pk]),
        )


class DeleteAuthorTests(TestCase):
    """Admin deactivation/hibernation and restore. No 7-day purge window."""

    def setUp(self):
        from BLOG.models import Blog, Comment

        self.admin = Auth.objects.create_user(email="del-admin@example.com", is_staff=True, is_admin=True)
        self.superuser = Auth.objects.create_user(email="del-super@example.com", is_staff=True, is_admin=True, is_superuser=True)
        self.author = Auth.objects.create_user(email="del-author@example.com", is_staff=True)
        StaffProfile.objects.create(auth=self.author, gender="M", full_name="Ada Author", role="JOURNALIST")
        self.story = Blog.objects.create(
            heading="Ada's Story", content="Body text", author=self.author, category="x", image_1=""
        )
        self.comment = Comment.objects.create(blog=self.story, author=self.author, content="Nice")
        self.client.force_login(self.admin)

    def _delete(self, account=None):
        account = account or self.author
        return self.client.post(reverse("control:staff_delete", args=[account.pk]))

    def test_delete_hibernates_account_keeps_content_and_profile(self):
        from BLOG.models import Blog, Comment

        with mock.patch("SERVICE_INTERNAL.account_lifecycle.drop_sessions_for", return_value=0), mock.patch(
            "SERVICE_INTERNAL.account_lifecycle._try_send_account_deactivation_code_email", create=True
        ), mock.patch("SERVICE_INTERNAL.email_single._dispatch_email", create=True):
            response = self._delete()

        self.assertEqual(response.status_code, 302)
        author = Auth.everyone.get(pk=self.author.pk)
        self.assertIsNotNone(author.deleted_at)
        self.assertFalse(author.is_active)
        # Stories/comments remain in storage and public querysets (anonymized in rendering).
        self.assertEqual(Blog.objects.filter(pk=self.story.pk).count(), 1)
        self.assertEqual(Comment.objects.filter(pk=self.comment.pk).count(), 1)
        self.assertEqual(StaffProfile.objects.filter(auth_id=self.author.pk).count(), 1)

    def test_a_signed_in_author_is_signed_out_when_hibernated(self):
        author_client = self.client_class()
        author_client.force_login(self.author)
        self.assertEqual(author_client.get(reverse("home:profile")).status_code, 200)
        with mock.patch("SERVICE_INTERNAL.account_lifecycle.drop_sessions_for", return_value=0):
            self._delete()
        self.assertNotEqual(author_client.get(reverse("home:profile")).status_code, 200)

    def test_restore_reactivates_account(self):
        from BLOG.models import Blog

        with mock.patch("SERVICE_INTERNAL.account_lifecycle.drop_sessions_for", return_value=0):
            self._delete()
        self.client.post(reverse("control:staff_restore", args=[self.author.pk]))
        author = Auth.everyone.get(pk=self.author.pk)
        self.assertIsNone(author.deleted_at)
        self.assertTrue(author.is_active)
        self.assertEqual(Blog.objects.filter(pk=self.story.pk).count(), 1)

    def test_you_cannot_delete_yourself_a_superuser_or_an_admin_as_non_superuser(self):
        self._delete(self.admin)
        self._delete(self.superuser)
        self.assertIsNone(Auth.everyone.get(pk=self.admin.pk).deleted_at)
        self.assertIsNone(Auth.everyone.get(pk=self.superuser.pk).deleted_at)

        other_admin = Auth.objects.create_user(email="del-admin2@example.com", is_staff=True, is_admin=True)
        self._delete(other_admin)
        self.assertIsNone(Auth.everyone.get(pk=other_admin.pk).deleted_at)
        self.client.force_login(self.superuser)
        with mock.patch("SERVICE_INTERNAL.account_lifecycle.drop_sessions_for", return_value=0):
            self._delete(other_admin)
        self.assertIsNotNone(Auth.everyone.get(pk=other_admin.pk).deleted_at)

    def test_ads_staff_without_admin_cannot_delete(self):
        ads = Auth.objects.create_user(email="del-ads@example.com", is_staff=True, is_ads_staff=True)
        self.client.force_login(ads)
        self._delete()
        self.assertIsNone(Auth.everyone.get(pk=self.author.pk).deleted_at)

    def test_admins_get_hibernated_accounts_notice_without_purge(self):
        with mock.patch("SERVICE_INTERNAL.account_lifecycle.drop_sessions_for", return_value=0):
            self._delete()
        Auth.everyone.filter(pk=self.author.pk).update(deleted_at=timezone.now() - timedelta(days=9))
        page = self.client.get(reverse("home:profile"))
        self.assertContains(page, "Ada Author")
        self.assertContains(page, "Deactivated")
        self.assertNotContains(page, "due for deletion")
        self.assertNotContains(page, "Delete permanently")
        self.assertNotContains(page, "staff_purge")

        plain = self.client_class()
        member = Auth.objects.create_user(email="del-member@example.com")
        plain.force_login(member)
        self.assertNotContains(plain.get(reverse("home:profile")), "Deactivated accounts")


class UnknownAuthorPanelTests(TestCase):
    """The PANEL groups stories left behind by deactivated authors."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = Auth.objects.create_user(
            email="unknown-admin@example.com", is_staff=True, is_admin=True
        )
        self.live_author = Auth.objects.create_user(
            email="live-author@example.com", is_staff=True
        )
        self.gone_author = Auth.objects.create_user(
            email="gone-author@example.com", is_staff=True
        )
        self.orphan_story = Blog.objects.create(
            heading="Orphan story", content="Body", author=self.gone_author,
            category="GENERAL", image_1="",
        )
        Blog.objects.create(
            heading="Live story", content="Body", author=self.live_author,
            category="GENERAL", image_1="",
        )
        self.client.force_login(self.admin)

    def test_panel_lists_anonymized_author_stories_with_red_count(self):
        Auth.everyone.filter(pk=self.gone_author.pk).update(deleted_at=timezone.now())

        response = self.client.get(reverse("control:panel"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unknown_author_total"], 1)
        self.assertEqual(
            [row["id"] for row in response.context["unknown_author_stories"]],
            [self.orphan_story.pk],
        )
        self.assertContains(response, "Unknown Author")
        self.assertContains(response, "Orphan story")
        self.assertContains(response, "unknown-author-badge")
        self.assertContains(response, self.gone_author.email)

    def test_no_unknown_section_when_no_author_is_anonymized(self):
        response = self.client.get(reverse("control:panel"))

        self.assertEqual(response.context["unknown_author_total"], 0)
        self.assertNotContains(response, "unknown-author-badge")
    @mock.patch("ADMIN.views._release_story_image")
    def test_admin_can_delete_an_anonymized_author_story(self, release):
        Auth.everyone.filter(pk=self.gone_author.pk).update(deleted_at=timezone.now())
        self.orphan_story.image_public_id = "stories/orphan-banner"
        self.orphan_story.save(update_fields=["image_public_id"])

        response = self.client.post(
            reverse("control:panel_unknown_author_delete", args=[self.orphan_story.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["detail"], "Story deleted.")
        self.assertEqual(response.json()["remaining"], 0)
        self.assertFalse(Blog.all_objects.filter(pk=self.orphan_story.pk).exists())
        release.assert_called_once_with("stories/orphan-banner")

    def test_non_admin_cannot_delete_an_anonymized_author_story(self):
        Auth.everyone.filter(pk=self.gone_author.pk).update(deleted_at=timezone.now())
        self.client.force_login(self.live_author)

        response = self.client.post(
            reverse("control:panel_unknown_author_delete", args=[self.orphan_story.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Admin access is required.")
        self.assertTrue(Blog.all_objects.filter(pk=self.orphan_story.pk).exists())

    @mock.patch("ADMIN.views._release_story_image")
    def test_cannot_delete_a_live_authors_story(self, release):
        live_story = Blog.all_objects.get(heading="Live story")

        response = self.client.post(
            reverse("control:panel_unknown_author_delete", args=[live_story.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Story not found.")
        self.assertTrue(Blog.all_objects.filter(pk=live_story.pk).exists())
        release.assert_not_called()
