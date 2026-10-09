"""
------------------------------------------------------------
#   SEND BATCH EMAIL SECTION
------------------------------------------------------------
This file never hand-rolls markup -- every email it sends is built by
`_build_email_html` in SERVICE_INTERNAL.email_single, the single source of
truth for HEADING/BODY/FOOTER. This file only fans that markup out to many
recipients at once, through Resend's batch endpoint (max 100 recipients per
API call, so a bigger recipient list is chunked below).
"""

from urllib.parse import quote

import resend
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.utils.html import escape

from AUTHENTICATION.models import Auth
from SERVICE_INTERNAL.abstract import info_logger, error_logger
from SERVICE_INTERNAL.config import About
from SERVICE_INTERNAL.email_single import _EMAIL_EXECUTOR, _build_email_html
from STAFF.models import AuthorFollow

BATCH_CHUNK_SIZE = 100  # Resend's hard limit per batch API call


def _dispatch_batch_email(recipients, subject, build_html_for):
    """
    Never raises: same guarantee as the single email dispatcher, so a
    broken/undecided mail step can never break the request that triggered it.

    recipients      : iterable of email addresses
    subject         : shared subject line for every recipient
    build_html_for  : callable(email) -> html for THAT recipient, so each
                       one still gets their own personalised unsubscribe link
    """
    recipients = [r for r in recipients if r]
    if not recipients:
        info_logger(msg=f"BATCH EMAIL: nothing to send for subject={subject}, no eligible recipients")
        return

    if getattr(settings, 'DEBUG'):from_email = "noreply@resend.dev"
    else:from_email = "noreply@abureport.com.ng"
    from_header = f"{About.project_name} <{from_email}>"

    sent_total = 0
    for i in range(0, len(recipients), BATCH_CHUNK_SIZE):
        chunk = recipients[i:i + BATCH_CHUNK_SIZE]
        params = [
            {
                "from": from_header,
                "to": [email],
                "subject": subject,
                "html": build_html_for(email),
            }
            for email in chunk
        ]
        try:
            resend.Batch.send(params)
            sent_total += len(chunk)
            info_logger(msg=f"BATCH EMAIL: dispatched {len(chunk)} emails in chunk starting at {i}, subject={subject}")
        except Exception as exc:
            error_logger(msg=f"BATCH EMAIL SEND FAILED: chunk starting at {i} subject={subject} error={exc}")

    info_logger(msg=f"BATCH EMAIL: dispatched {sent_total}/{len(recipients)} total, subject={subject}")


def _try_send_new_story_batch_email(blog: object):
    """
    Fired right after a story is published (HOME.views.AddNewsView). Recipients:
      (a) everyone who follows this story's author (STAFF.AuthorFollow), and
      (b) everyone who follows no author at all, so they still get exposed
          to new stories instead of never hearing from the site again.
    Only accounts with `send_newsletter` on are eligible, and the footer's
    unsubscribe link doubles as the opt-out by flipping that same flag off.
    The author themself is always excluded.

    The dispatch is submitted to the shared background email pool
    (_EMAIL_EXECUTOR), so the publish request never waits on Resend. DEBUG
    mode sends nothing at all -- it only prints an info_logger line (which
    prints to the console while DEBUG is on) reporting what would have gone
    out.
    """
    author = blog.author

    following_author_ids = AuthorFollow.objects.filter(author=author).values_list("follower_id", flat=True)
    follows_somebody_ids = AuthorFollow.objects.values_list("follower_id", flat=True)

    recipients = list(
        Auth.objects.filter(
            Q(pk__in=following_author_ids) | ~Q(pk__in=follows_somebody_ids),
            send_newsletter=True,
            is_active=True,
        )
        .exclude(pk=author.pk)
        .values_list("email", flat=True)
        .distinct()
    )

    #   DEBUG = DEV MODE: never touch Resend here, just print what would have
    #   gone out. info_logger prints to the console while DEBUG is on.
    if getattr(settings, "DEBUG"):
        info_logger(
            msg=f"NEW STORY ALERT (DEBUG): new story by {author.email} matched {len(recipients)} eligible recipient(s), "
            "but nothing was sent because DEBUG=True"
        )
        return

    if not recipients:
        info_logger(msg=f"BATCH EMAIL: no eligible recipients for new story by {author.email}")
        return

    subject = f"New story from {blog.author_name} on {About.project_name}"
    story_url = f"{About.domain}/story/{blog.slug}/"

    def build_html_for(email):
        main_content = (
            "<p>Hi,</p>"
            f"<p>{blog.author_name} just published a new story: <strong>{blog.heading}</strong>.</p>"
            f'<p><a href="{story_url}">Read it here</a></p>'
        )
        return _build_email_html(
            title="New Story Published",
            main_content=main_content,
            end_note=f"{About.project_name} Team",
            unsubscribe_query=f"type=author_post&email={quote(email)}",
            preference_note="You can turn off all news update emails from your profile settings at any time.",
        )

    _EMAIL_EXECUTOR.submit(_dispatch_batch_email, recipients, subject, build_html_for)
    info_logger(msg=f"BATCH EMAIL: new story alert queued for {len(recipients)} recipients (author={author.email}, blog={blog.pk})")


def _try_send_panel_mass_email(sender_full_name, subject, body_html, recipients, sent_by_email):
    """PANEL "send mass email" action.

    Unlike the other batch senders in this file the display name on the
    `from` header is the sending admin's own StaffProfile.full_name (never
    the project name), so the receiver always knows a real person sent it.
    Recipient email addresses are resolved server side by the caller and
    never round-trip through the client -- this function only ever receives
    the final address list.
    """
    if getattr(settings, 'DEBUG'):
        from_email = "noreply@resend.dev"
    else:
        from_email = "noreply@abureport.com.ng"
    from_header = f"{sender_full_name} <{from_email}>"

    recipients = [r for r in recipients if r]
    if not recipients:
        info_logger(msg=f"PANEL MASS EMAIL: nothing to send for subject={subject}, no eligible recipients")
        return 0

    def build_html_for(email):
        return _build_email_html(
            title=subject,
            main_content=body_html,
            end_note=f"{sender_full_name} \u2014 {About.project_name}",
            unsubscribe_query="",
            preference_note="",
        )

    sent_total = 0
    for i in range(0, len(recipients), BATCH_CHUNK_SIZE):
        chunk = recipients[i:i + BATCH_CHUNK_SIZE]
        params = [
            {
                "from": from_header,
                "to": [email],
                "subject": subject,
                "html": build_html_for(email),
            }
            for email in chunk
        ]
        try:
            resend.Batch.send(params)
            sent_total += len(chunk)
        except Exception as exc:
            error_logger(msg=f"PANEL MASS EMAIL SEND FAILED: chunk starting at {i} subject={subject} error={exc}")

    info_logger(msg=f"PANEL MASS EMAIL: dispatched {sent_total}/{len(recipients)} total, subject={subject}, sent_by={sent_by_email}")
    return sent_total


def _active_admin_emails(exclude_pk=None):
    """Email of every admin / superuser account with is_active=True."""
    admins = Auth.objects.filter(Q(is_admin=True) | Q(is_superuser=True), is_active=True)
    if exclude_pk:
        admins = admins.exclude(pk=exclude_pk)
    return list(admins.values_list("email", flat=True).distinct())


def _format_mail_datetime(moment):
    """'02 Oct 2026, 03:15 PM WAT' in the project timezone."""
    return timezone.localtime(moment).strftime("%d %b %Y, %I:%M %p %Z")


def _try_send_account_deleted_batch_email(deleted_email, deleted_account_type, deleted_full_name="", deleted_at=None):
    """
    Fired after a user deletes their own account (HOME.views.ProfileDeleteAccountView).
    One batch mail to every active admin / superuser carrying the account
    type, the deleted account email, the staff full name (only passed for
    Staff / Admin / S-Admin accounts) and the date and time of deletion.

    The caller must capture `deleted_full_name` BEFORE deleting, because the
    StaffProfile row is gone the moment the account is. The dispatch runs on
    the shared email pool so the delete request never waits on Resend.
    """
    deleted_at = deleted_at or timezone.now()
    recipients = _active_admin_emails()
    if not recipients:
        info_logger(msg=f"BATCH EMAIL: no active admins to notify about deleted account {deleted_email}")
        return

    subject = f"{deleted_account_type} account deleted on {About.project_name}"
    detail_rows = f"<li>Account type: <strong>{escape(deleted_account_type)}</strong></li>"
    detail_rows += f"<li>Email: <strong>{escape(deleted_email)}</strong></li>"
    if deleted_full_name:
        detail_rows += f"<li>Full name: <strong>{escape(deleted_full_name)}</strong></li>"
    detail_rows += f"<li>Deleted on: <strong>{escape(_format_mail_datetime(deleted_at))}</strong></li>"

    main_content = (
        "<p>Hi,</p>"
        "<p>An account was just deleted by its owner from their profile page.</p>"
        f"<ul>{detail_rows}</ul>"
    )

    def build_html_for(email):
        return _build_email_html(
            title="Account Deleted",
            main_content=main_content,
            end_note=f"{About.project_name} Team",
            unsubscribe_query="",
            preference_note="You receive this because you are an admin on this site.",
        )

    _EMAIL_EXECUTOR.submit(_dispatch_batch_email, recipients, subject, build_html_for)
    info_logger(msg=f"BATCH EMAIL: account deleted alert queued for {len(recipients)} admins (deleted={deleted_email})")


def _try_send_staff_created_batch_email(new_account, full_name, role_label, created_by_email):
    """
    Fired right after an admin adds a staff account (ADMIN.views.StaffCreateView).
    One batch mail to every admin / superuser with is_active=True, the new
    account itself excluded since it already gets the welcome credentials mail.
    """
    recipients = _active_admin_emails(exclude_pk=new_account.pk)
    if not recipients:
        info_logger(msg=f"BATCH EMAIL: no active admins to notify about new staff {new_account.email}")
        return

    account_type = "Admin" if new_account.is_admin else "Staff"
    subject = f"New {account_type.lower()} account added on {About.project_name}"
    detail_rows = (
        f"<li>Account type: <strong>{account_type}</strong></li>"
        f"<li>Full name: <strong>{escape(full_name)}</strong></li>"
        f"<li>Email: <strong>{escape(new_account.email)}</strong></li>"
        f"<li>Role: <strong>{escape(role_label)}</strong></li>"
        f"<li>Added by: <strong>{escape(created_by_email)}</strong></li>"
        f"<li>Added on: <strong>{escape(_format_mail_datetime(timezone.now()))}</strong></li>"
    )
    main_content = (
        "<p>Hi,</p>"
        "<p>A new team account was just created from the add staff page.</p>"
        f"<ul>{detail_rows}</ul>"
    )

    def build_html_for(email):
        return _build_email_html(
            title="New Staff Account",
            main_content=main_content,
            end_note=f"{About.project_name} Team",
            unsubscribe_query="",
            preference_note="You receive this because you are an admin on this site.",
        )

    _EMAIL_EXECUTOR.submit(_dispatch_batch_email, recipients, subject, build_html_for)
    info_logger(msg=f"BATCH EMAIL: new staff alert queued for {len(recipients)} admins (new={new_account.email})")
