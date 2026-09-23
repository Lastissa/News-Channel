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

from AUTHENTICATION.models import Auth
from SERVICE_INTERNAL.abstract import info_logger, error_logger
from SERVICE_INTERNAL.config import About
from SERVICE_INTERNAL.email_single import _build_email_html
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
    Fired right after a story is published. Recipients are:
      (a) everyone who follows this story's author (STAFF.AuthorFollow), and
      (b) everyone who follows no author at all, so they still get exposed
          to new stories instead of never hearing from the site again.
    Only accounts with `send_newsletter` on are eligible, and the footer's
    unsubscribe link doubles as the opt-out by flipping that same flag off.
    The author themself is always excluded.
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

    if not recipients:
        info_logger(msg=f"BATCH EMAIL: no eligible recipients for new story by {author.email}")
        return

    subject = f"New story from {blog.author_name} on {About.project_name}"
    story_url = f"{About.domain}/story/{blog.pk}/"

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

    _dispatch_batch_email(recipients, subject, build_html_for)
    info_logger(msg=f"BATCH EMAIL: new story alert queued for {len(recipients)} recipients (author={author.email}, blog={blog.pk})")
