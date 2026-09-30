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
from SERVICE_INTERNAL import email_single
from SERVICE_INTERNAL.config import About
from STAFF.models import StaffProfile

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
            ("ADMIN.views.is_rate_limited", {"return_value": (0, False)}),
        ]:
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

        patcher = mock.patch("resend.Emails.send")
        self.send = patcher.start()
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
