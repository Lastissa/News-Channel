"""
------------------------------------------------------------
#   SEND SINGLE EMAIL ONLY SECTION
------------------------------------------------------------
Layout rule: `_build_email_html` is the ONLY place that builds HEAD, BODY or
FOOTER markup. No other function in this file (or elsewhere) should hand-roll
part of the template -- every "prefilled" sender below just supplies content
to that one method.
"""

from urllib.parse import quote
import resend

from SERVICE_INTERNAL.abstract import info_logger, error_logger
from SERVICE_INTERNAL.config import About

from django.conf import settings

resend.api_key = getattr(settings, 'RESEND_API_KEY', 'abcdef')

def _build_email_html(title, main_content, end_note="", header_extra="", unsubscribe_query="", preference_note=""):
    """
    THE single source of truth for every outgoing email's markup: HEADING,
    BODY and FOOTER all come from this one method, so no email in the
    project ever drifts from this layout.

    title              : formal-letter style heading for the body, e.g. "Login Alert"
    main_content       : the actual message. Small HTML (<p>, <br>, <a>) is fine.
    end_note           : closing line of the body, e.g. "Stay safe, AbuReport Team"
    header_extra       : optional line under the project name in the heading
                         (defaults to the project catchphrase)
    unsubscribe_query  : query string appended to the unsubscribe link so the
                         receiving view knows what to switch off, e.g.
                         "type=login_alert&email=jane%40mail.com"
    preference_note    : optional extra footer line (e.g. a link to manage
                         preferences generally, not just unsubscribe)

    Mobile vs desktop: the layout is a single fluid table capped at 600px, so
    desktop clients get the boxed card while the @media block below drops the
    side padding and shrinks type once the viewport goes under 600px -- same
    html, no separate render path.
    """
    unsubscribe_url = f"{About.domain}/unsubscribe/?{unsubscribe_query}" if unsubscribe_query else f"{About.domain}/unsubscribe/"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{About.project_name}</title>
    <style>
        body {{ margin:0; padding:0; background-color:#f4f4f5; font-family: Arial, Helvetica, sans-serif; color:#222222; }}
        .email-wrapper {{ width:100%; background-color:#f4f4f5; padding:24px 0; }}
        .email-container {{ max-width:600px; margin:0 auto; background-color:#ffffff; border-radius:8px; overflow:hidden; }}
        .email-heading {{ background-color:#111827; padding:24px 32px; text-align:center; }}
        .email-heading h1 {{ margin:0; color:#ffffff; font-size:20px; letter-spacing:0.5px; }}
        .email-heading p {{ margin:4px 0 0; color:#9ca3af; font-size:12px; }}
        .email-body {{ padding:32px; }}
        .email-title {{ margin:0 0 16px; font-size:18px; color:#111827; }}
        .email-main {{ font-size:15px; line-height:1.6; color:#374151; }}
        .email-end-note {{ margin-top:24px; font-size:14px; color:#374151; }}
        .email-footer {{ padding:20px 32px; background-color:#f9fafb; text-align:center; font-size:12px; color:#6b7280; }}
        .email-footer p {{ margin:4px 0; }}
        .email-footer a {{ color:#6b7280; text-decoration:underline; }}
        @media only screen and (max-width:600px) {{
            .email-container {{ width:100% !important; border-radius:0 !important; }}
            .email-heading, .email-body, .email-footer {{ padding-left:20px !important; padding-right:20px !important; }}
            .email-title {{ font-size:16px !important; }}
            .email-main {{ font-size:14px !important; }}
        }}
    </style>
</head>
<body>
    <div class="email-wrapper">
        <table role="presentation" class="email-container" width="100%" cellpadding="0" cellspacing="0">
            <tr><td class="email-heading">
                <h1>{About.project_name}</h1>
                <p>{header_extra or About.project_cachphrase}</p>
            </td></tr>
            <tr><td class="email-body">
                <h2 class="email-title">{title}</h2>
                <div class="email-main">{main_content}</div>
                {f'<p class="email-end-note">{end_note}</p>' if end_note else ''}
            </td></tr>
            <tr><td class="email-footer">
                <p>No longer want this kind of email? <a href="{unsubscribe_url}">Unsubscribe</a></p>
                {f'<p>{preference_note}</p>' if preference_note else ''}
                <p>Questions? Reach us at <a href="mailto:support@abureport.com.ng">support@abureport.com.ng</a></p>
            </td></tr>
        </table>
    </div>
</body>
</html>"""


def _dispatch_email(receiver, subject, html_message):
    """
    Never raises: any failure here is caught and logged, so an undecided or
    broken mail step can never break the request that triggered it.
    """
    try:
        if getattr(settings, 'DEBUG'):from_email = "noreply@resend.dev" 
        else:from_email = "noreply@abureport.com.ng" 
        params = {
            "from": f"{About.project_name} <{from_email}>",
            "to": [receiver],
            "subject": subject,
            "html": html_message,
        }
        resend.Emails.send(params)
        info_logger(msg=f"EMAIL: dispatched to {receiver} subject={subject}")
    except Exception as exc:
        error_logger(msg=f"EMAIL SEND FAILED: to={receiver} subject={subject} error={exc}")

"""
------------------------------------------------------------
#   PREFILLED SENDERS -- each just supplies content to _build_email_html
#   and hands the result to _dispatch_email. No template markup here.
------------------------------------------------------------
"""


def _try_send_login_email(user: object):
    """
    Receives the user queryset and looks for the login alert preference.
    If enabled, prepares and "sends" the login success email; else logs why
    nothing was sent.
    """
    if not getattr(user, "receive_email_login_alert", False):
        info_logger(msg=f"LOGIN ALERT: {user.email} logged in but no login alert was sent as they have it disabled")
        return

    subject = f"New login to your {About.project_name} account"
    main_content = (
        "<p>Hi,</p>"
        f"<p>We noticed a new login to your {About.project_name} account ({user.email}). "
        "If this was you, no action is needed.</p>"
        "<p>If you don't recognise this activity, reset your password as soon as possible.</p>"
        
    )
    html_message = _build_email_html(
        title="Login Alert",
        main_content=main_content,
        end_note=f"You receive this mail becAUSE you have 'receive alert' toggeled on in your profile. Stay safe,<br>{About.project_name} Team",
        unsubscribe_query=f"type=login_alert&email={quote(user.email)}",
    )
    _dispatch_email(user.email, subject, html_message)


def _try_send_password_reset_email(user: object, reset_link: str):
    """
    Receives the user and the freshly generated reset link and prepares the
    password-reset-request email.
    """
    subject = f"Reset your {About.project_name} password"
    main_content = (
        "<p>Hi,</p>"
        f"<p>We received a request to reset the password on your account ({user.email}).</p>"
        f'<p><a href="{reset_link}">Click here to reset your password</a></p>'
        "<p>If you didn't request this, you can safely ignore this email -- your password won't change.</p>"
    )
    html_message = _build_email_html(
        title="Password Reset Requested",
        main_content=main_content,
        end_note=f"{About.project_name} Team",
        unsubscribe_query=f"type=password_reset&email={quote(user.email)}",
    )
    _dispatch_email(user.email, subject, html_message)
    info_logger(msg=f"EMAIL: password reset requested for {user.email}")
    info_logger(msg=f"RESET LINK for {user.email}: {reset_link}")


def _try_send_password_reset_success_email(user: object):
    """
    Confirms a password was just changed through the reset flow. Sent right
    after the new password is saved, so the account owner has a record even
    if they didn't make the change themselves.
    """
    subject = f"Your {About.project_name} password was changed"
    main_content = (
        "<p>Hi,</p>"
        f"<p>This confirms the password on your account ({user.email}) was just changed.</p>"
        "<p>If you made this change, no action is needed. If you didn't, contact us immediately.</p>"
    )
    html_message = _build_email_html(
        title="Password Changed",
        main_content=main_content,
        end_note=f"{About.project_name} Team",
        unsubscribe_query=f"type=password_reset&email={quote(user.email)}",
    )
    _dispatch_email(user.email, subject, html_message)
    info_logger(msg=f"EMAIL: password reset success notice sent to {user.email}")


def _try_send_story_views_alert_email(user: object, blog: object):
    """
    Notifies a staff author that one of their stories just crossed another
    STORY_VIEWS_ALERT_INTERVAL views. The caller (BLOG.views.StoryDetailView)
    is responsible for checking the StaffProfile 'get_blog_notification'
    preference and the interval before calling this -- this function only
    builds and sends.
    """
    subject = f"Your story just crossed {blog.views} views"
    main_content = (
        "<p>Hi,</p>"
        f"<p>Your story <strong>{blog.heading}</strong> on {About.project_name} just reached "
        f"<strong>{blog.views}</strong> views.</p>"
        f'<p><a href="{About.domain}/story/{blog.pk}/">View the story</a></p>'
    )
    html_message = _build_email_html(
        title="Story Views Alert",
        main_content=main_content,
        end_note=f"Keep up the great work,<br>{About.project_name} Team",
        unsubscribe_query=f"type=story_views_alert&email={quote(user.email)}",
        preference_note="You can turn these alerts off from your profile settings at any time.",
    )
    _dispatch_email(user.email, subject, html_message)
    info_logger(msg=f"EMAIL: story views alert sent to {user.email} for blog={blog.pk} views={blog.views}")


def _try_send_newsletter_subscribe_email(email: str):
    """
    Confirms a newsletter subscription for an anonymous visitor who used the
    footer signup on the base page. `email` is a plain string here since no
    user object is guaranteed to exist yet at the call site.
    """
    subject = f"You're subscribed to {About.project_name}"
    main_content = (
        "<p>Hi,</p>"
        f"<p>You're now subscribed to news updates from {About.project_name}.</p>"
        "<p>We'll only email you when there's something worth reading.</p>"
    )
    html_message = _build_email_html(
        title="Subscription Confirmed",
        main_content=main_content,
        end_note=f"Welcome aboard,<br>{About.project_name} Team",
        unsubscribe_query=f"type=newsletter&email={quote(email)}",
    )
    _dispatch_email(email, subject, html_message)
    info_logger(msg=f"EMAIL: newsletter subscribe confirmation sent to {email}")

def _try_send_staff_welcome_email(user: object, password: str, full_name: str = ""):
    """
    Sent once, right after an admin creates a staff account (ADMIN.views.StaffCreateView),
    carrying the login email + the plaintext password the admin just set so the
    new hire can sign in. `password` is only ever known at this one moment --
    it is hashed immediately on save and never stored or logged in the clear
    again after this call.
    """
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    subject = f"Your {About.project_name} staff account is ready"
    main_content = (
        f"<p>{greeting}</p>"
        f"<p>An account has been created for you on {About.project_name}. Here are your login details:</p>"
        f"<p>Email: <strong>{user.email}</strong><br>Password: <strong>{password}</strong></p>"
        f'<p><a href="{About.domain}/login/">Log in here</a> and change your password once you\'re in.</p>'
    )
    html_message = _build_email_html(
        title="Welcome to the Team",
        main_content=main_content,
        end_note=f"Welcome aboard,<br>{About.project_name} Team",
        unsubscribe_query=f"type=staff_welcome&email={quote(user.email)}",
    )
    _dispatch_email(user.email, subject, html_message)
    info_logger(msg=f"EMAIL: staff welcome credentials sent to {user.email}")