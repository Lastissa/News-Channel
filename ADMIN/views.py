"""Admin authority views.

Everything that needs more than plain staff access lives here. Staff level
work stays in HOME.views; this module only holds the extra authority an admin
(or superuser) carries over the rest of the staff.
"""

import json
import math
import logging
import re
from datetime import timedelta
from urllib.parse import quote, urlencode

import cloudinary.utils
import requests
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature
from django.core.validators import URLValidator, validate_email
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import title as title_case
from django.urls import reverse
from django.utils.text import slugify
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from AUTHENTICATION.models import Auth, UserSession
from BLOG.models import Blog, Category, Comment, get_category_choices
from HOME.views import _release_story_image, _resolve_page_number
from SERVICE_INTERNAL.abstract import get_client_ip, info_logger, invalidate_cache, is_rate_limited
from SERVICE_INTERNAL.account_lifecycle import hibernate_account, restore_account
from ADMIN.models import AccountActionLog
from SERVICE_INTERNAL.config import StaffConfig
from SERVICE_INTERNAL.email_batch import _try_send_panel_mass_email, _try_send_staff_created_batch_email
from SERVICE_INTERNAL.hosts import RESERVED_SUBDOMAINS, ads_base_host, advert_host
from Partner.plans import advert_allows, plan_allows, plan_message, time_left
from SERVICE_INTERNAL.email_single import _try_send_staff_direct_email, _try_send_staff_welcome_email
from SERVICE_INTERNAL.images import (
    ADVERT_LANDING_MAX_BYTES,
    ADVERT_STORAGE_MAX_BYTES,
    ImageUploadError,
    destroy_advert_landing_html,
    destroy_archive_asset,
    fetch_advert_landing_html,
    upload_advert_image,
    upload_advert_landing_html,
    upload_advert_storage_file,
)
from SERVICE_INTERNAL.permissions import admin_only, ads_staff_only
from SERVICE_INTERNAL.passwords import first_password_error
from SERVICE_INTERNAL.sessions import (
    describe_device,
    drop_sessions_for,
    drop_single_session,
    is_admin_inactive_too_long,
    is_session_expired,
    live_sessions_for,
)
from Partner.landing import (
    ADVERT_LANDING_TOKENS,
    DEFAULT_ADVERT_LANDING_TEMPLATE,
    ROBOTS_DEFAULT,
    add_advert_landing_author_header,
    advert_landing_slug,
    advert_landing_url,
    render_advert_landing_document,
    strip_advert_landing_author_header,
)
from Partner.models import (
    AdvertEvent,
    AdvertImage,
    AdvertPage,
    AdvertLandingPage,
    AdvertLead,
    AdvertReference,
    AdvertReferenceFile,
    Announcement,
)
from ADMIN.models import SiteSettings
from ADMIN.analytics import (
    AUTHOR_DEFAULT_RANGE,
    AUTHOR_PERFORMANCE_SERIES,
    AUTHOR_RANGE_CHOICES,
    CATEGORY_PERFORMANCE_SERIES,
    DEFAULT_AUTHOR_PERFORMANCE_SERIES,
    DEFAULT_CATEGORY_PERFORMANCE_SERIES,
    DEFAULT_STORY_PERFORMANCE_SERIES,
    DEFAULT_STORY_PERIOD,
    DEFAULT_TREND_BUCKET,
    DEFAULT_TREND_RANGE,
    MEMBER_ACTIVITY_CHOICES,
    MEMBER_CATEGORY_ANY,
    MEMBER_KIND_CHOICES,
    MEMBER_NEWSLETTER_CHOICES,
    MEMBER_STATE_CHOICES,
    MEMBER_TREND_SERIES,
    NO_CATEGORY_KEY,
    NO_CATEGORY_LABEL,
    SERIES_META,
    STORY_KPI_RANGE_CHOICES,
    STORY_KPI_RANGES,
    STORY_PERFORMANCE_SERIES,
    STORY_PERIODS,
    STORY_PERIOD_CHOICES,
    STORY_TREND_SERIES,
    TREND_BUCKET_CHOICES,
    TREND_RANGE_CHOICES,
    TREND_RANGES,
    TREND_SUB_RANGE_CHOICES,
    author_choices,
    author_compare,
    author_detail,
    author_directory_rows,
    author_kpis,
    author_likes,
    author_performance,
    category_comparison,
    category_names,
    category_palette,
    category_performance,
    category_story_counts,
    daily_story_activity,
    member_category_filter_choices,
    member_directory_queryset,
    member_new_today,
    member_overview,
    member_page_details,
    members_growth,
    reading_editorial,
    stories_overview,
    stories_per_day_by_category,
    stories_per_week,
    story_kpis,
    story_performance,
    story_search,
    trends,
    week_stories,
    week_window,
)
from STAFF.models import GENDER_CHOICES, StaffProfile

logger = logging.getLogger(__name__)

STAFF_PAGE_SIZE = 5  #   COPIES THE BOOKMARK / READING HISTORY PANELS


def admin_page_redirect(request):
    """Where a page an admin may not open sends the visitor.

    A signed-in user without admin authority goes to their own profile. An
    anonymous visitor -- which is exactly what an admin becomes the moment the
    inactivity middleware logs them out -- is sent to the login page carrying
    the page they were reaching for, so signing back in lands them on the
    PANEL they meant to open instead of dropping them on the profile.
    """
    if request.user.is_authenticated:
        return redirect("home:profile")
    return redirect(f"{reverse('auth:login')}?{urlencode({'to': request.get_full_path()})}")


def staff_directory_queryset():
    """Every account carrying staff authority, admins and superusers included."""
    return Auth.objects.filter(Q(is_staff=True) | Q(is_admin=True) | Q(is_superuser=True)).order_by("-date_joined")


def staff_directory_rows(account_list):
    """Shape accounts into the row payload that both the server rendered panel
    and the JSON endpoint use. The email is the fallback label whenever a
    StaffProfile row or a full name is missing."""
    profiles = {
        profile.auth_id: profile
        for profile in StaffProfile.objects.filter(auth_id__in=[account.pk for account in account_list])
    }

    rows = []
    for account in account_list:
        profile = profiles.get(account.pk)
        display_name = (profile.full_name.strip() if profile and profile.full_name else "") or "NO USERNAME"

        if account.is_superuser:
            authority = "SAdmin"
        elif account.is_admin:
            authority = "Admin"
        else:
            authority = "Staff"

        detail_bits = [authority]
        if profile is None:
            #   FLAGGED SO AN ADMIN CAN SPOT ACCOUNTS MISSING A STAFF RECORD
            detail_bits.append("No staff profile")
        else:
            detail_bits.append(StaffConfig.role_label(profile.role))
        detail_bits.append(account.email)
        if not account.is_active:
            detail_bits.append("Suspended")

        rows.append(
            {
                "id": account.pk,
                "staff_id": account.pk,
                "heading": display_name,
                "detail": " \u2022 ".join(detail_bits), # The u2022 is for the asterik stuff 
                "email": account.email,
                "authority": authority,
                "has_profile": profile is not None,
                "is_active": account.is_active,
                "profile_img": account.profile_img or "",
                "url": reverse("control:staff_detail", args=[account.pk]),
            }
        )
    return rows


def staff_directory_page(page_number=1):
    """Shared paginator so the profile panel and the JSON endpoint can never
    drift out of step."""
    paginator = Paginator(staff_directory_queryset(), STAFF_PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    return paginator, paginator.get_page(page_number)


class StaffDirectoryView(View):
    """Paginated JSON feed of every staff account for the admin panel on the
    profile page. Read only by design: no delete action is exposed."""

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required to view This Page."}, status=403)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        paginator, page = staff_directory_page(page_number)

        return JsonResponse(
            {
                "items": staff_directory_rows(list(page.object_list)),
                "page": page.number,
                "num_pages": paginator.num_pages,
                "has_previous": page.has_previous(),
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
                "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "count": paginator.count,
            },
            status=200,
        )


def _unknown_author_stories(limit=50):
    """Stories left behind by deactivated authors, for the PANEL only.

    The public managers hide these stories' anonymized authors, so the PANEL
    uses ``all_objects`` here and links each row to the live public story.
    """
    stories = (
        Blog.all_objects.filter(author__deleted_at__isnull=False)
        .select_related("author")
        .order_by("-date_created")[:limit]
    )
    rows = [
        {
            "id": story.pk,
            "heading": story.heading,
            "category": story.category,
            "detail": f"{story.views} view{'' if story.views == 1 else 's'} `u2022 {story.date_created:%b %d, %Y}",
            "url": reverse("blog:story_detail", args=[story.slug or str(story.pk)]),
            "author_email": story.author.email if story.author else "",
        }
        for story in stories
    ]
    total = Blog.all_objects.filter(author__deleted_at__isnull=False).count()
    return rows, total

def _staff_account_or_404(staff_id, include_deleted=False):
    accounts = Auth.everyone if include_deleted else Auth.objects
    account = accounts.filter(pk=staff_id).first()
    if account is None or not (account.is_staff or account.is_admin or account.is_superuser):
        raise Http404("Staff member not found.")
    return account


def _published_rows(blog_list):
    return [
        {
            "id": blog.id,
            "blog_id": blog.id,
            "heading": blog.heading,
            "detail": f"{blog.views} view{'' if blog.views == 1 else 's'} \u2022 {blog.date_created:%b %d, %Y}",
            "url": reverse("blog:story_detail", args=[blog.slug]),
        }
        for blog in blog_list
    ]


def _published_page(account, page_number=1):
    paginator = Paginator(Blog.all_objects.filter(author=account).order_by("-date_created"), STAFF_PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    return paginator, paginator.get_page(page_number)


class StaffDetailView(View):
    """Full page staff record.

    Privacy: reading history, bookmarks, the profile image URL and the
    newsletter preference are deliberately absent. Those belong to the staff
    member and no admin overrides them from here.

    Authority: every admin reading this page can write the controls on it,
    the superuser no longer outranks an admin here. The page also holds the
    Delete author button (a soft delete an admin can undo for 7 days).
    """

    def get(self, request, staff_id):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        account = _staff_account_or_404(staff_id, include_deleted=True)
        profile = StaffProfile.all_objects.filter(auth=account).first()

        page_number = _resolve_page_number(request.GET.get("published_page"), default=1)
        paginator, page = _published_page(account, page_number)

        speciality = []
        if profile and isinstance(profile.speciality, list):
            speciality = [str(item) for item in profile.speciality if str(item).strip()]

        socials = []
        if profile:
            for label, value in (
                ("Twitter", profile.twitter_handle),
                ("WhatsApp", profile.whatsapp_handle),
                ("Facebook", profile.facebook_handle),
            ):
                if value:
                    socials.append({"label": label, "url": value})

        if account.is_superuser:
            authority = "Superuser"
        elif account.is_admin:
            authority = "Admin"
        else:
            authority = "Staff"

        own_profile = StaffProfile.objects.filter(auth=request.user).first()

        return render(
            request,
            "ADMIN/staff_detail.html",
            {
                "sender_full_name": own_profile.full_name.strip() if own_profile and own_profile.full_name else "",
                "staff_account": account,
                "staff_profile": profile,
                "staff_display_name": (profile.full_name.strip() if profile and profile.full_name else "") or "NO USERNAME",
                "staff_has_profile": profile is not None,
                "staff_authority": authority,
                "staff_role_label": StaffConfig.role_label(profile.role) if profile else "",
                "staff_gender_label": profile.get_gender_display() if profile and profile.gender else "",
                "staff_gender_choices": StaffConfig.gender_choices(),
                "staff_speciality": speciality,
                "staff_speciality_csv": ", ".join(speciality),
                "staff_socials": socials,
                "published_stories": page.object_list,
                "stories_page_obj": page,
                "stories_page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                #   WRITE CONTROLS RENDER FOR EVERY ADMIN, SUPERUSER INCLUDED
                "can_edit_staff": admin_only(request.user),
                "role_choices": StaffConfig.role_choices(),
                "protected_roles": sorted(StaffConfig.PROTECTED_ROLES),
                "gender_endpoint": reverse("control:staff_gender", args=[account.pk]),
                "ads_access_endpoint": reverse("control:staff_ads_access", args=[account.pk]),
                "has_ads_access": bool(account.is_ads_staff),
                **_deletion_context(request.user, account),
            },
        )


#   ACCOUNT HIBERNATION ------------------------------------------------------
#   Deactivated/hibernated accounts are hidden from login and anonymized on
#   public surfaces, but their content stays restorable by an admin. There is no
#   automatic or manual purge path here; true deletion is a separate superuser
#   backdoor endpoint.


def _hibernated_days_ago(account):
    if not getattr(account, "deleted_at", None):
        return 0
    delta = timezone.now() - account.deleted_at
    return max(0, int(delta.total_seconds() // 86400))


def _delete_block_reason(actor, account):
    """Why this account may not be hibernated by this admin, or "" when it may."""
    if account.pk == actor.pk:
        return "You cannot deactivate your own account here."
    if account.is_superuser:
        return "A superuser account cannot be deactivated here."
    if account.is_admin and not actor.is_superuser:
        return "Only a superuser can deactivate an admin account."
    return ""


def _deletion_context(actor, account):
    """What the detail page needs to show hibernation and restore controls."""
    context = {
        "is_deleted": bool(getattr(account, "deleted_at", None)),
        "delete_block_reason": _delete_block_reason(actor, account),
        "stories_count": Blog.all_objects.filter(author=account).count(),
        "comments_count": Comment.all_objects.filter(author=account).count(),
        "days_ago": _hibernated_days_ago(account),
    }
    return context


def account_action_logs(limit=30):
    return list(
        AccountActionLog.objects.select_related("account", "actor").order_by("-created_at", "-pk")[:limit]
    )


def deleted_accounts_notice(user):
    """Admin-visible list of hibernated accounts. No purge/due behavior."""
    if not admin_only(user):
        return []
    rows = []
    for account in Auth.everyone.filter(deleted_at__isnull=False).order_by("-deleted_at"):
        profile = StaffProfile.all_objects.filter(auth=account).first()
        name = (profile.full_name.strip() if profile and profile.full_name else "") or account.email
        rows.append(
            {
                "id": account.pk,
                "name": name,
                "email": account.email,
                "url": reverse("control:staff_detail", args=[account.pk]),
                "stories_count": Blog.all_objects.filter(author=account).count(),
                "comments_count": Comment.all_objects.filter(author=account).count(),
                "days_ago": _hibernated_days_ago(account),
                "deleted_at": account.deleted_at,
            }
        )
    return rows


class StaffDeleteView(View):
    """Hibernate/deactivate a staff account. Restore remains admin-only."""

    def post(self, request, staff_id):
        if not admin_only(request.user):
            return admin_page_redirect(request)
        account = _staff_account_or_404(staff_id)
        reason = _delete_block_reason(request.user, account)
        if reason:
            messages.error(request, reason)
            return redirect("control:staff_detail", account.pk)

        hibernate_account(account, actor=request.user)
        info_logger(msg=f"STAFF HIBERNATED: {account.email} by {request.user.email}")
        messages.success(
            request,
            f"{account.email} has been deactivated. Public content is anonymized and only an admin can restore it.",
        )
        return redirect("control:staff_detail", account.pk)


class StaffRestoreView(View):
    def post(self, request, staff_id):
        if not admin_only(request.user):
            return admin_page_redirect(request)
        account = _staff_account_or_404(staff_id, include_deleted=True)
        if account.deleted_at is None:
            messages.error(request, "That account is not deactivated.")
            return redirect("control:staff_detail", account.pk)
        restore_account(account, actor=request.user)
        messages.success(request, f"{account.email} has been restored.")
        return redirect("control:staff_detail", account.pk)


class StaffPublishedView(View):
    """Paginated JSON feed of one staff member's published news, for the
    detail page. Read only, no delete action is exposed here."""

    def get(self, request, staff_id):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        account = _staff_account_or_404(staff_id)
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        paginator, page = _published_page(account, page_number)

        return JsonResponse(
            {
                "items": _published_rows(list(page.object_list)),
                "page": page.number,
                "num_pages": paginator.num_pages,
                "has_previous": page.has_previous(),
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
                "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "count": paginator.count,
            },
            status=200,
        )


class _SuperuserWriteView(View):
    """Shared guard for the write controls on the staff detail page. Despite
    the historical name, every admin (superuser included) passes: the
    superuser no longer outranks an admin on this page."""

    def _guard(self, request, staff_id):
        if not admin_only(request.user):
            return None, JsonResponse({"detail": "Admin access is required."}, status=403)
        account = _staff_account_or_404(staff_id)
        profile = StaffProfile.objects.filter(auth=account).first()
        if profile is None:
            return None, JsonResponse(
                {"detail": "This account has no staff profile yet, so it cannot be edited here."}, status=409
            )
        return (account, profile), None


class StaffTributeUpdateView(_SuperuserWriteView):
    """Write the tribute the admin keeps about a staff member. This is not the
    staff member's own bio, which stays read only."""

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited: return JsonResponse({'detail':f'Permission Denied, Wait {remaining_seconds} seconds'}, status = 403)
        resolved, error = self._guard(request, staff_id)
        if error:
            return error
        account, profile = resolved

        tribute = (request.POST.get("tribute_bio") or "").strip()
        profile.tribute_bio = tribute
        profile.save(update_fields=["tribute_bio"])
        logger.info("Tribute updated for staff %s by %s", account.email, request.user.email)

        return JsonResponse({"detail": "Tribute saved.", "tribute_bio": tribute}, status=200)


class StaffSpecialityUpdateView(_SuperuserWriteView):
    """Write the speciality tags for a staff member. Mirrors the admin-only
    speciality edit on the profile page (HOME.views), but here a superuser
    sets it for someone else's account instead of their own."""

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited: return JsonResponse({'detail':f'Permission Denied, Wait {remaining_seconds} seconds'}, status = 403)
        resolved, error = self._guard(request, staff_id)
        if error:
            return error
        account, profile = resolved

        raw = request.POST.get("speciality", "")
        speciality = [part.strip() for part in raw.split(",") if part.strip()]
        profile.speciality = speciality
        profile.save(update_fields=["speciality"])
        logger.info("Speciality updated for staff %s by %s", account.email, request.user.email)

        return JsonResponse(
            {
                "detail": "Speciality saved.",
                "speciality": speciality,
                "speciality_csv": ", ".join(speciality),
            },
            status=200,
        )


class StaffRoleUpdateView(_SuperuserWriteView):
    """Set a staff member's role. Choices come from SERVICE_INTERNAL.config so
    editing STAFF_ROLE updates this dropdown everywhere at once. Every accepted
    change stamps last_promotion with today."""

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited: return JsonResponse({'detail':f'Permission Denied, Wait {remaining_seconds} seconds'}, status = 403)
        resolved, error = self._guard(request, staff_id)
        if error:
            return error
        account, profile = resolved

        role = (request.POST.get("role") or "").strip()
        allowed = {value for value, _ in StaffConfig.role_choices()}
        if role not in allowed:
            return JsonResponse({"detail": "That role cannot be assigned from here."}, status=400)

        if role == profile.role:
            return JsonResponse(
                {
                    "detail": "Role unchanged.",
                    "role": profile.role,
                    "role_label": StaffConfig.role_label(profile.role),
                    "last_promotion": profile.last_promotion.strftime("%b %d, %Y") if profile.last_promotion else "",
                },
                status=200,
            )

        profile.role = role
        profile.last_promotion = timezone.localdate()
        profile.save(update_fields=["role", "last_promotion"])
        logger.info("Role for staff %s set to %s by %s", account.email, role, request.user.email)

        return JsonResponse(
            {
                "detail": "Role updated.",
                "role": role,
                "role_label": StaffConfig.role_label(role),
                "last_promotion": profile.last_promotion.strftime("%b %d, %Y"),
            },
            status=200,
        )


class StaffGenderUpdateView(_SuperuserWriteView):
    """Set a staff member's gender. Gender is admin only (the staff member
    cannot change their own from the profile page), so this control lives on
    the admin record page where an admin can actually change it."""

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited: return JsonResponse({'detail':f'Permission Denied, Wait {remaining_seconds} seconds'}, status = 403)
        resolved, error = self._guard(request, staff_id)
        if error:
            return error
        account, profile = resolved

        gender = (request.POST.get("gender") or "").strip()
        if gender not in {value for value, _ in GENDER_CHOICES}:
            return JsonResponse({"detail": "Select a valid gender option."}, status=400)

        if gender == profile.gender:
            return JsonResponse(
                {"detail": "Gender unchanged.", "gender": profile.gender, "gender_label": profile.get_gender_display()},
                status=200,
            )

        profile.gender = gender
        profile.save(update_fields=["gender"])
        logger.info("Gender for staff %s set to %s by %s", account.email, gender, request.user.email)

        return JsonResponse(
            {
                "detail": "Gender updated.",
                "gender": gender,
                "gender_label": profile.get_gender_display(),
            },
            status=200,
        )


class StaffBanToggleView(_SuperuserWriteView):
    """Temporarily suspend or restore a staff account. Suspending drops every
    session the account holds so the ban takes effect immediately. Nothing here
    deletes an account."""

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited: return JsonResponse({'detail':f'Permission Denied, Wait {remaining_seconds} seconds'}, status = 403)
        
        resolved, error = self._guard(request, staff_id)
        if error:
            return error
        account, _profile = resolved

        if account.pk == request.user.pk:
            return JsonResponse({"detail": "You cannot suspend your own account."}, status=400)

        new_state = not account.is_active
        account.is_active = new_state
        account.save(update_fields=["is_active"])

        dropped = 0
        if not new_state:
            dropped = drop_sessions_for(account)
        from SERVICE_INTERNAL.abstract import info_logger
        info_logger(logger, msg = f"Account {account.email} set to {"active" if new_state else "suspended"} by {request.user.email} ({dropped} sessions dropped)")

        return JsonResponse(
            {
                "detail": "Account restored." if new_state else f"Account suspended. {dropped} session(s) ended.",
                "is_active": new_state,
                "status": "active" if new_state else "suspended",
                "sessions_dropped": dropped,
            },
            status=200,
        )


STAFF_MAIL_SUBJECT_MAX = 150
STAFF_MAIL_BODY_MAX = 5000


class StaffMailSendView(View):
    """Send one email to the staff member whose detail page the admin is on.

    "Only while in their profile" is enforced by construction: the recipient
    is looked up from the staff id in THIS URL and nothing else. No address,
    id or recipient list is ever read from the request body, so the endpoint
    cannot be used to mail anyone but the person the page belongs to.

    Like the PANEL mass email, the sending admin needs a StaffProfile
    full_name: it becomes the From display name."""

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 30, 5)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        #   AFTER the admin check on purpose: a non admin must not be able to
        #   tell which staff ids exist from a 404 versus a 403
        account = _staff_account_or_404(staff_id)

        sender_profile = StaffProfile.objects.filter(auth=request.user).first()
        sender_full_name = sender_profile.full_name.strip() if sender_profile and sender_profile.full_name else ""
        if not sender_full_name:
            return JsonResponse(
                {"detail": "Your staff profile has no full name set. An admin cannot send email without one."},
                status=409,
            )

        #   one line: a subject is never allowed to carry line breaks
        subject = " ".join((request.POST.get("subject") or "").split())
        body = (request.POST.get("body") or "").strip()
        if not subject:
            return JsonResponse({"detail": "Enter an email heading."}, status=400)
        if len(subject) > STAFF_MAIL_SUBJECT_MAX:
            return JsonResponse({"detail": f"The email heading is limited to {STAFF_MAIL_SUBJECT_MAX} characters."}, status=400)
        if not body:
            return JsonResponse({"detail": "Enter the email body."}, status=400)
        if len(body) > STAFF_MAIL_BODY_MAX:
            return JsonResponse({"detail": f"The email body is limited to {STAFF_MAIL_BODY_MAX} characters."}, status=400)

        profile = StaffProfile.objects.filter(auth=account).first()
        recipient_name = (profile.full_name.strip() if profile and profile.full_name else "") or "this staff member"

        if not _try_send_staff_direct_email(sender_full_name, account.email, subject, body):
            return JsonResponse({"detail": "The email could not be sent. Try again shortly."}, status=502)

        #   who wrote to whom and the heading, never the message itself
        info_logger(msg=f"STAFF MAIL: {request.user.email} sent '{subject}' to {account.email}")

        return JsonResponse({"detail": f"Email sent to {recipient_name}."}, status=200)


class OwnRoleUpdateView(View):
    """An admin changes their own role from their own profile page. Other
    people's records are the staff detail page's business; this endpoint only
    ever touches request.user and never takes a target id. Every accepted
    change stamps last_promotion with today, exactly like the detail page."""

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        profile = StaffProfile.objects.filter(auth=request.user).first()
        if profile is None:
            return JsonResponse({"detail": "Staff Profile Missing On This Account."}, status=409)

        role = (request.POST.get("role") or "").strip()
        allowed = {value for value, _ in StaffConfig.role_choices()}
        if role not in allowed:
            return JsonResponse({"detail": "That role cannot be assigned."}, status=400)

        if role == profile.role:
            return JsonResponse(
                {
                    "detail": "Role unchanged.",
                    "role": profile.role,
                    "role_label": StaffConfig.role_label(profile.role),
                },
                status=200,
            )

        profile.role = role
        profile.last_promotion = timezone.localdate()
        profile.save(update_fields=["role", "last_promotion"])
        logger.info("Role for staff %s set to %s by themselves", request.user.email, role)

        return JsonResponse(
            {
                "detail": "Role updated.",
                "role": role,
                "role_label": StaffConfig.role_label(role),
                "last_promotion": profile.last_promotion.strftime("%b %d, %Y"),
            },
            status=200,
        )


class StaffCreateView(View):
    """Full page form for adding a staff account. Admin and superuser only Access Only.

    The Auth row and its StaffProfile row are created together: an account
    without a profile is exactly the broken state the staff directory flags.
    Flags are whitelisted here rather than read from POST, and nothing on
    this page can ever grant superuser or delete an account.
    """

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return self._render(request)

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 30, 20)
        if limited:
            return self._fail(request, f"Permission Denied, Wait {remaining_seconds} seconds")
        if not admin_only(request.user):
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"detail": "Admin access is required."}, status=403)
            return admin_page_redirect(request)

        email = (request.POST.get("email") or "").strip()
        password = (request.POST.get("password") or "").strip()
        full_name = (request.POST.get("full_name") or "").strip()
        gender = (request.POST.get("gender") or "").strip()
        role = (request.POST.get("role") or "").strip()
        grant_admin = request.POST.get("is_admin") == "on"
        grant_ads = request.POST.get("is_ads_staff") == "on"

        error = None
        if not email or "@" not in email:
            error = "Enter a valid email address."
        elif Auth.objects.filter(email__iexact=email).exists():
            error = "That email already has an account."
        elif not password or len(password) < 6:
            error = "The password must be at least 6 characters long."
        elif (password_error := first_password_error(password, user=Auth(email=email))):
            error = password_error
        elif not full_name:
            error = "The full name cannot be empty."
        elif len(full_name) > 100:
            error = "The full name is limited to 100 characters."
        elif gender not in {value for value, _ in GENDER_CHOICES}:
            error = "Select a valid gender option."
        elif role not in {value for value, _ in StaffConfig.role_choices()}:
            error = "Select a valid role."

        if error is not None:
            return self._fail(request, error)

        with transaction.atomic():
            account = Auth.objects.create_staff(
                email=email,
                password=password,
                is_admin=grant_admin,
                is_ads_staff=grant_ads,
            )
            StaffProfile.objects.create(auth=account, gender=gender, full_name=full_name, role=role)
            
        _try_send_staff_welcome_email(account, password, full_name)
        role_label = dict(StaffConfig.role_choices()).get(role, role)
        _try_send_staff_created_batch_email(account, full_name, role_label, request.user.email)
        info_logger(msg=f"STAFF CREATED: {account.email} (grant_admin={grant_admin}, ads_staff={grant_ads}) by {request.user.email}")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "detail": "Staff account created.",
                    "redirect_to": reverse("control:staff_detail", args=[account.pk]),
                },
                status=201,
            )
        return redirect("control:staff_detail", account.pk)

    def _render(self, request, error=None, form_data=None):
        return render(
            request,
            "ADMIN/staff_create.html",
            {
                "role_choices": StaffConfig.role_choices(),
                "gender_choices": StaffConfig.gender_choices(),
                "form_error": error,
                "form_data": form_data or {},
            },
        )

    def _fail(self, request, error):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"detail": error}, status=400)
        return self._render(
            request,
            error=error,
            form_data={
                "email": request.POST.get("email", ""),
                "full_name": request.POST.get("full_name", ""),
                "gender": request.POST.get("gender", ""),
                "role": request.POST.get("role", ""),
                "is_admin": request.POST.get("is_admin") == "on",
                "is_ads_staff": request.POST.get("is_ads_staff") == "on",
            },
        )


"""
------------------------------------------------------------
#   PANEL SECTION
------------------------------------------------------------
Everything below powers ADMIN/templates/ADMIN/panel.html, the page the
"PANEL" link on the profile page opens for admins and superusers. Staff
level people never reach here -- every view below is admin_only.
"""

GALLERY_PAGE_SIZE = 12   #   staff gallery strip, bigger than the old 5-row list since it scrolls horizontally
SESSIONS_PAGE_SIZE = 5
SPECIALITY_PAGE_SIZE = 5
MEMBER_PAGE_SIZE = 12   #   ANALYTICS Members table: six columns, so a dozen rows fit before paging


def _mask_email(email):
    """m***a@gmail.com -- never show a full address client side."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return email or ""
    if len(local) <= 2:
        masked = (local[:1] or "?") + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _staff_achievement_text(profile):
    """'On the team since <month year>'. last_promotion when it is set (the
    detail page stamps it on every role change), otherwise the account's own
    date_joined, so this is always generated on the spot and never stored."""
    base_date = profile.last_promotion or (profile.auth.date_joined.date() if profile.auth_id else None)
    if not base_date:
        return "On the team"
    return f"On the team since {base_date:%b %Y}"


class PanelView(View):
    """Main PANEL page. Admin and superuser only -- everything else on this
    page (gallery paging, sessions, settings save, mass email, speciality
    search) is fetched lazily by panel.js against the JSON
    endpoints below, this view only renders the shell plus the first page of
    the staff gallery so the page is never empty on first paint."""

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        own_profile = StaffProfile.objects.filter(auth=request.user).first()
        unknown_rows, unknown_total = _unknown_author_stories()

        gallery_paginator = Paginator(staff_directory_queryset(), GALLERY_PAGE_SIZE)
        gallery_page = gallery_paginator.get_page(1)

        sessions_paginator, sessions_page, sessions_rows, sessions_total_people = _active_sessions_page(1)

        return render(
            request,
            "ADMIN/panel.html",
            {
                "is_superuser": bool(request.user.is_superuser),
                "deleted_accounts": deleted_accounts_notice(request.user),
                "unknown_author_stories": unknown_rows,
                "unknown_author_total": unknown_total,
                "account_action_logs": account_action_logs(),
                "sender_full_name": own_profile.full_name.strip() if own_profile and own_profile.full_name else "",
                "site_settings": SiteSettings.get_solo(),
                "category_rows": _category_rows(),
                "announcement_items": _announcement_items(),
                "image_advert_items": _image_advert_items(),
                "advert_leads": AdvertLead.objects.select_related("user").order_by("-created_at")[:20],
                "advert_lead_total": AdvertLead.objects.count(),
                "landing_tokens": ADVERT_LANDING_TOKENS,
                "landing_robots_choices": AdvertLandingPage.ROBOTS_CHOICES,
                "gallery_items": staff_directory_rows(list(gallery_page.object_list)),
                "gallery_total": gallery_paginator.count,
                "gallery_has_next": gallery_page.has_next(),
                "gallery_next_page": gallery_page.next_page_number() if gallery_page.has_next() else None,
                "sessions_rows": sessions_rows,
                "sessions_total_people": sessions_total_people,
                "sessions_page_obj": sessions_page,
            },
        )


class AnalyticsView(View):
    """ANALYTICS shell. Admin and superuser only, like PANEL.

    This page deliberately carries NO numbers: it renders the controls and an
    empty target per chart, and each chart is filled by its own htmx GET
    (fired on load, and re-fired whenever a control changes). So the shell is
    cheap and every figure arrives from a fragment endpoint below.
    """

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return render(
            request,
            "ADMIN/analytics.html",
            {
                "story_periods": STORY_PERIOD_CHOICES,
                "default_story_period": DEFAULT_STORY_PERIOD,
                "trend_buckets": TREND_BUCKET_CHOICES,
                "default_trend_bucket": DEFAULT_TREND_BUCKET,
                "trend_ranges": TREND_RANGE_CHOICES,
                "trend_sub_ranges": TREND_SUB_RANGE_CHOICES,
                "default_trend_range": DEFAULT_TREND_RANGE,
                "story_performance_series": STORY_PERFORMANCE_SERIES,
                "default_story_performance_series": DEFAULT_STORY_PERFORMANCE_SERIES,
                "member_state_choices": MEMBER_STATE_CHOICES,
                "member_newsletter_choices": MEMBER_NEWSLETTER_CHOICES,
                "member_category_choices": member_category_filter_choices(),
                "member_activity_choices": MEMBER_ACTIVITY_CHOICES,
                "member_kind_choices": MEMBER_KIND_CHOICES,
                "member_page_size": MEMBER_PAGE_SIZE,
                "active_chamber": "member",
            },
        )


class AnalyticsStoriesChartView(View):
    """htmx fragment: the "stories per week" bar chart.

    Read only, admin only, and never linked from anywhere but ANALYTICS. The
    period is validated against STORY_PERIODS inside stories_per_week(), so an
    unknown value simply falls back to the one month default.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        period = (request.GET.get("period") or DEFAULT_STORY_PERIOD).strip()
        return render(
            request,
            "ADMIN/partials/analytics_stories.html",
            {
                "chart": stories_per_week(period),
                "period": period if period in STORY_PERIODS else DEFAULT_STORY_PERIOD,
                "stories": stories_overview(),
            },
        )


class AnalyticsTrendsChartView(View):
    """htmx fragment: the multi-series trend line chart.

    The checkboxes in the shell decide which series are drawn. On the very
    first (load) request the browser sends no `submitted` marker, so the
    Member lytics set is shown by default -- the story-open series belongs to
    the Story lytics page, which always sends the boxes it has ticked. Once
    the form has fired, the ticked set is honoured exactly -- including the
    case where every box is cleared, which draws an empty chart rather than
    silently re-adding them all.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        bucket = (request.GET.get("bucket") or DEFAULT_TREND_BUCKET).strip()
        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()
        if "submitted" in request.GET:
            series_keys = set(request.GET.getlist("series"))
        else:
            series_keys = {meta["key"] for meta in MEMBER_TREND_SERIES}

        return render(
            request,
            "ADMIN/partials/analytics_trends.html",
            {"chart": trends(bucket, selected_range, series_keys, start_iso, end_iso)},
        )


class AnalyticsStoryCategoryDailyView(View):
    """htmx fragment: stories published per bucket, one line per category.

    Read only and admin only, like every other figure endpoint. The category
    names are checked against the live category list, so a hand typed
    querystring can only ever name a category that exists.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        bucket = (request.GET.get("bucket") or DEFAULT_TREND_BUCKET).strip()
        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()

        palette = category_palette(category_names())
        ticked = [name for name in request.GET.getlist("category") if name in palette]

        return render(
            request,
            "ADMIN/partials/analytics_story_category_daily.html",
            {
                "chart": stories_per_day_by_category(
                    bucket, selected_range, ticked, palette, start_iso, end_iso
                )
            },
        )


class AnalyticsCategoryCompareView(View):
    """htmx fragment: two categories side by side over one window.

    Read only and admin only. The two names are snapped to real categories
    and must differ, so the chart always compares two subjects rather than a
    category with itself.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        names = category_names()
        palette = category_palette(names)
        defaults = _default_chart_categories(limit=2)

        first = (request.GET.get("a") or "").strip()
        second = (request.GET.get("b") or "").strip()
        if first not in palette:
            #   The busiest subject, so the first paint compares two subjects
            #   that have actually published.
            first = defaults[0] if defaults else (names[0] if names else "")
        if second not in palette or second == first:
            second = next((name for name in defaults if name != first), "")
            if not second:
                second = next((name for name in names if name != first), "")

        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()

        if not first or not second:
            return render(
                request,
                "ADMIN/partials/analytics_category_compare.html",
                {"chart": None},
            )

        return render(
            request,
            "ADMIN/partials/analytics_category_compare.html",
            {
                "chart": category_comparison(
                    first, second, selected_range, palette, start_iso, end_iso
                )
            },
        )


class AnalyticsCategoryPerformanceView(View):
    """htmx fragment: one category's views / likes / comments over time.

    The category twin of Story performance. The chosen name is snapped to the
    live category list, so a hand typed querystring can only chart a subject
    that exists. No category chosen falls back to the busiest one, which keeps
    the first paint useful instead of showing an empty prompt.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        names = category_names()
        palette = category_palette(names)
        defaults = _default_chart_categories(limit=1)

        category_name = (request.GET.get("category") or "").strip()
        if category_name not in palette:
            category_name = defaults[0] if defaults else (names[0] if names else "")

        bucket = (request.GET.get("bucket") or DEFAULT_TREND_BUCKET).strip()
        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()

        if "submitted" in request.GET:
            series_keys = set(request.GET.getlist("series"))
        else:
            series_keys = set(DEFAULT_CATEGORY_PERFORMANCE_SERIES)

        return render(
            request,
            "ADMIN/partials/analytics_category_performance.html",
            {
                "chart": category_performance(
                    category_name,
                    bucket,
                    selected_range,
                    series_keys,
                    start_iso,
                    end_iso,
                )
            },
        )


class AnalyticsMembersGrowthView(View):
    """htmx fragment: the "Members over time" running-total line chart.

    Read only and admin only. Takes the same bucket / range / custom-date
    controls as Trends, but always draws the one cumulative series.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        bucket = (request.GET.get("bucket") or DEFAULT_TREND_BUCKET).strip()
        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()

        return render(
            request,
            "ADMIN/partials/analytics_members_growth.html",
            {"chart": members_growth(bucket, selected_range, start_iso, end_iso)},
        )


class AnalyticsStoryPerformanceView(View):
    """htmx fragment: one story's views / likes / comments over time.

    Read only and admin only. A missing or unknown story id draws the "pick a
    story" note; otherwise the chosen signals are bucketed exactly like Trends.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        raw_id = (request.GET.get("story") or "").strip()
        blog_id = int(raw_id) if raw_id.isdigit() else None
        bucket = (request.GET.get("bucket") or DEFAULT_TREND_BUCKET).strip()
        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()
        if "submitted" in request.GET:
            series_keys = set(request.GET.getlist("series"))
        else:
            series_keys = set(DEFAULT_STORY_PERFORMANCE_SERIES)

        return render(
            request,
            "ADMIN/partials/analytics_story_performance.html",
            {"chart": story_performance(blog_id, bucket, selected_range, series_keys, start_iso, end_iso)},
        )


class AnalyticsStorySearchView(View):
    """htmx fragment: story matches for the Story performance picker.

    Read only and admin only. Returns a short list of buttons; pressing one
    submits the picker form and loads that story's chart.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        query = (request.GET.get("story_q") or "").strip()[:100]
        return render(
            request,
            "ADMIN/partials/analytics_story_search.html",
            {"results": story_search(query)},
        )


class AnalyticsWeekStoriesView(View):
    """Fetch fragment: the stories behind one bar of the Stories-per-week chart.

    Read only and admin only, like every other analytics view. The bar passes
    an ISO date naming the week it stands for (any day of it); an unknown,
    missing or not-yet-started week answers 400, so the placard can only ever
    describe a real week. analytics.js requests it on demand, so the chart
    fragment itself still ships counts and nothing else.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        window = week_window(request.GET.get("week"))
        if window is None:
            return JsonResponse({"detail": "A past week is required."}, status=400)

        start, end = window
        return render(request, "ADMIN/partials/analytics_week_stories.html", week_stories(start, end))


def _member_choice(request, name, choices, default="all"):
    """Read one Members filter, snapping anything unknown back to its default.

    The dropdowns are the only legitimate source of these values, so a hand
    typed querystring must never reach the ORM as a surprise value.
    """
    allowed = {value for value, _ in choices}
    value = (request.GET.get(name) or default).strip()
    return value if value in allowed else default


class AnalyticsMembersView(View):
    """htmx fragment: the ANALYTICS "Members" table.

    Admin only and read only. Filters are validated against the fixed choice
    lists in ADMIN.analytics (and the live category names), so an unknown value
    can only ever fall back to its default -- exactly like the chart fragments.
    The shell ships a loading placeholder and this fills it on load and whenever
    a control changes.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        state = _member_choice(request, "state", MEMBER_STATE_CHOICES)
        newsletter = _member_choice(request, "newsletter", MEMBER_NEWSLETTER_CHOICES)
        activity = _member_choice(request, "activity", MEMBER_ACTIVITY_CHOICES)
        kind = _member_choice(request, "kind", MEMBER_KIND_CHOICES)

        category_choices = member_category_filter_choices()
        category = _member_choice(request, "category", category_choices, default=MEMBER_CATEGORY_ANY)
        search = (request.GET.get("q") or "").strip()[:100]

        queryset = member_directory_queryset(
            state=state, newsletter=newsletter, category=category, activity=activity, kind=kind, search=search
        )

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        paginator = Paginator(queryset, MEMBER_PAGE_SIZE)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        page = paginator.get_page(page_number)

        return render(
            request,
            "ADMIN/partials/analytics_members.html",
            {
                "rows": member_directory_rows(page.object_list),
                "page": page,
                #   The standard project pager (base.css .story-pagination),
                #   windowed exactly like the profile lists. The page buttons
                #   carry only ?page=N and reach the active filters through the
                #   hx-include on the shell's filter form, so nothing has to be
                #   echoed back here and an unknown value is re-validated above.
                "page_range": list(paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
                "total": paginator.count,
                "subscribed_total": queryset.filter(send_newsletter=True).count(),
            },
        )


class AnalyticsOverviewView(View):
    """htmx fragment: the ANALYTICS "Quick overview" card.

    Read only and admin only, like every other figure endpoint. The whole card
    is one GET carrying no controls, so the shell stays number-free and the
    figures always arrive from a fragment.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        return render(request, "ADMIN/partials/analytics_overview.html", {"stats": member_overview()})


class AnalyticsNewTodayView(View):
    """htmx fragment: the "N new users today" badge in the ANALYTICS top bar.

    Its own GET, separate from the overview card, so the badge can refresh on
    its own without redrawing everything else.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        return render(request, "ADMIN/partials/analytics_new_today.html", {"count": member_new_today()})


class AnalyticsReadingView(View):
    """htmx fragment: the ANALYTICS "Reading & editorial" card.

    Read only and admin only, like every other figure endpoint. The single
    Range dropdown reuses the Trends ranges; an unknown value falls back to the
    30 day default here, so a hand typed querystring can never widen the window
    past a choice the menu offers. The optional "cooled since" date only moves
    the age gate on the barely-read list.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        if selected_range not in TREND_RANGES:
            selected_range = DEFAULT_TREND_RANGE

        cooled_since = (request.GET.get("cooled") or "").strip()

        return render(
            request,
            "ADMIN/partials/analytics_reading.html",
            reading_editorial(selected_range, cooled_since),
        )


class AnalyticsDailyStoryActivityView(View):
    """htmx fragment: stories opened on one day, with that day's signals.

    Read only and admin only. The optional `day` querystring is parsed and
    clamped inside daily_story_activity(), so a malformed or future date
    quietly falls back to today instead of widening the roster.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        day_iso = (request.GET.get("day") or "").strip()
        return render(
            request,
            "ADMIN/partials/analytics_daily_story_activity.html",
            {"activity": daily_story_activity(day_iso)},
        )


class AnalyticsStoryKpisView(View):
    """htmx fragment: the Story lytics KPI strip.

    Read only and admin only, like every other figure endpoint. The range is
    validated against the preset list and an unknown value falls back, exactly
    like the Reading card, so a hand typed querystring cannot widen the window.
    A custom start/end pair overrides the preset inside story_kpis().
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range = (request.GET.get("range") or DEFAULT_TREND_RANGE).strip()
        if selected_range not in STORY_KPI_RANGES:
            selected_range = DEFAULT_TREND_RANGE
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()

        context = story_kpis(selected_range, start_iso, end_iso)
        context["kpi_ranges"] = STORY_KPI_RANGE_CHOICES
        return render(request, "ADMIN/partials/analytics_story_kpis.html", context)


class AnalyticsUncategorizedStoriesView(View):
    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)
        valid = set([c[0] for c in get_category_choices()])
        stories = (
            Blog.objects.exclude(category__in=valid)
            .order_by("-date_created", "-pk")
            .values("id", "heading", "category", "date_created", "slug")
        )
        paginator = Paginator(stories, 25)
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        page = paginator.get_page(page_number)
        total_stories = Blog.objects.count()
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        return render(
            request,
            "ADMIN/partials/analytics_uncategorized.html",
            {
                "stories": page.object_list,
                "count": paginator.count,
                "total_stories": total_stories,
                "uncategorized_percent": (
                    round(paginator.count * 100 / total_stories) if total_stories else 0
                ),
                "page": page,
                "page_range": list(
                    paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
                ),
            },
        )


class PartnerLyticsView(View):
    """Placeholder for the partner chamber of analytics (not built yet)."""

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return render(
            request,
            "ADMIN/analytics_placeholder.html",
            {"heading": "Partner lytics", "message": "Partner analytics is not built yet. It will cover adverts and announcements.", "active_chamber": "partner"},
        )


def _author_window_args(request):
    """The (range, since) pair behind an Author lytics request.

    `range` is snapped to the fixed choice list, and `since` is passed through
    as the raw date string -- ADMIN.analytics parses it and silently ignores
    anything unusable, so a hand typed date can never widen the window.
    """
    selected_range = _member_choice(
        request, "range", AUTHOR_RANGE_CHOICES, default=AUTHOR_DEFAULT_RANGE
    )
    since = (request.GET.get("since") or "").strip()
    return selected_range, since


class AuthorLyticsView(View):
    """The Author lytics chamber: who writes, how much, and who liked it.

    The people-facing chamber, replacing the old Staff placeholder (the two had
    the same job). A leaderboard of authors with their production, reads, likes
    and comments, the named readers behind every like, and a per-author detail
    that opens from any row. Like the other chambers the shell holds no numbers
    -- each figure arrives from its own htmx fragment.
    """

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return render(
            request,
            "ADMIN/author_lytics.html",
            {
                "author_ranges": AUTHOR_RANGE_CHOICES,
                "default_author_range": AUTHOR_DEFAULT_RANGE,
                "author_choices": author_choices(),
                "active_chamber": "author",
            },
        )


class AnalyticsAuthorKpisView(View):
    """htmx fragment: the Author lytics KPI strip.

    Read only and admin only, like every other figure endpoint. The range is
    validated against the fixed choice list, so a hand typed querystring can
    only ever fall back to the default; a valid custom "since" date overrides it.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range, since = _author_window_args(request)
        return render(
            request,
            "ADMIN/partials/analytics_author_kpis.html",
            author_kpis(selected_range, since),
        )


class AnalyticsAuthorsView(View):
    """htmx fragment: the Author lytics leaderboard table.

    Admin only and read only. The range is validated against the fixed choice
    list in ADMIN.analytics, so a hand typed querystring can only ever fall back
    to the default. The "focus" query, when set, asks the fragment to open that
    author's detail once the table has painted.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range, since = _author_window_args(request)
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        table = author_directory_rows(selected_range, since, page_number)
        if page_number > table["page"].paginator.num_pages and table["page"].paginator.num_pages:
            raise Http404("Page not found.")
        return render(
            request,
            "ADMIN/partials/analytics_authors.html",
            {**table, "focus": (request.GET.get("focus") or "").strip(), "since": since},
        )


class AnalyticsAuthorDetailView(View):
    """htmx fragment: one author's production and their named likers.

    Read only and admin only. `author` is the account id; an unknown id renders
    the "no such author" notice rather than a 500, so a stale link degrades. The
    stories and likers lists each carry their own page number so they page
    independently inside the one panel.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range, since = _author_window_args(request)
        author_id = request.GET.get("author")
        try:
            author_id = int(author_id)
        except (TypeError, ValueError):
            author_id = None

        story_page = _resolve_page_number(request.GET.get("stories_page"), default=1)
        like_page = _resolve_page_number(request.GET.get("likes_page"), default=1)
        detail = (
            author_detail(author_id, selected_range, since, story_page, like_page)
            if author_id
            else None
        )
        #   Ship the first performance chart with the detail rather than asking
        #   htmx to fetch it after a fetch-inserted fragment: the chart is then
        #   painted by the same render pass as the rest of the panel, and only
        #   later control changes need another request.
        performance_chart = (
            author_performance(
                author_id,
                DEFAULT_TREND_BUCKET,
                selected_range,
                set(DEFAULT_AUTHOR_PERFORMANCE_SERIES),
            )
            if detail
            else None
        )
        return render(
            request,
            "ADMIN/partials/analytics_author_detail.html",
            {
                "detail": detail,
                "range": selected_range,
                "since": since,
                "performance_chart": performance_chart,
                "trend_buckets": TREND_BUCKET_CHOICES,
                "default_trend_bucket": DEFAULT_TREND_BUCKET,
                "trend_ranges": TREND_RANGE_CHOICES,
                "trend_sub_ranges": TREND_SUB_RANGE_CHOICES,
                "default_trend_range": selected_range,
                "author_performance_series": AUTHOR_PERFORMANCE_SERIES,
                "default_author_performance_series": DEFAULT_AUTHOR_PERFORMANCE_SERIES,
            },
        )


class AnalyticsAuthorPerformanceView(View):
    """htmx fragment: one author's views / likes / comments over time.

    Read only and admin only. The events are counted across every story the
    author wrote, so the chart reflects the whole portfolio while the stories
    table below still breaks the same window down per story.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        raw_id = (request.GET.get("author") or "").strip()
        author_id = int(raw_id) if raw_id.isdigit() else None
        bucket = (request.GET.get("bucket") or DEFAULT_TREND_BUCKET).strip()
        selected_range = (request.GET.get("range") or AUTHOR_DEFAULT_RANGE).strip()
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()
        if "submitted" in request.GET:
            series_keys = set(request.GET.getlist("series"))
        else:
            series_keys = set(DEFAULT_AUTHOR_PERFORMANCE_SERIES)

        return render(
            request,
            "ADMIN/partials/analytics_author_performance.html",
            {
                "chart": author_performance(
                    author_id,
                    bucket,
                    selected_range,
                    series_keys,
                    start_iso,
                    end_iso,
                )
            },
        )


class AnalyticsAuthorCompareView(View):
    """htmx fragment: two authors side by side over one window.

    Read only and admin only. Both ids are optional: a missing pick, an
    unknown account or the same author twice renders a hint instead of a
    board, so a half-filled form never 500s. The fragment owns its window
    controls -- a complete start/end pair overrides the preset range.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range, since = _author_window_args(request)
        start_iso = (request.GET.get("start") or "").strip()
        end_iso = (request.GET.get("end") or "").strip()

        def author_id(name):
            raw = (request.GET.get(name) or "").strip()
            return int(raw) if raw.isdigit() else None
        
        remaining_seconds, limited = is_rate_limited(request, timeout_window=10, max_requests=10, reset_timeout = False, scope=f"{get_client_ip(request)}{3}")
        if limited: return JsonResponse({"detail": f"Rate limit exceeded. Please wait {remaining_seconds} seconds and try again."}, status=429)
        

        return render(
            request,
            "ADMIN/partials/analytics_author_compare.html",
            author_compare(
                author_id("a"),
                author_id("b"),
                selected_range,
                since,
                start_iso,
                end_iso,
            ),
        )


class AnalyticsAuthorLikesView(View):
    """htmx fragment: the named, non-anonymous likes list, newest first.

    Read only and admin only. Every like belongs to a signed-in reader, so the
    list always carries a name; it pages rather than truncating so an admin can
    read the whole run for the range.
    """

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        selected_range, since = _author_window_args(request)
        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        context = author_likes(selected_range, page_number, since)
        if page_number > context["page"].paginator.num_pages and context["page"].paginator.num_pages:
            raise Http404("Page not found.")
        return render(request, "ADMIN/partials/analytics_author_likes.html", context)


class StoryLyticsView(View):
    """The Story lytics chamber: stories produced, how they read and perform.

    Hosts the pieces that belong to stories rather than members -- the
    Stories-per-week bar chart and its published figure, the Reading &
    editorial card, and the per-story performance chart. Each figure still
    arrives from its own htmx fragment, so the shell stays cheap.
    """

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return render(
            request,
            "ADMIN/story_lytics.html",
            {
                "story_periods": STORY_PERIOD_CHOICES,
                "default_story_period": DEFAULT_STORY_PERIOD,
                "trend_buckets": TREND_BUCKET_CHOICES,
                "default_trend_bucket": DEFAULT_TREND_BUCKET,
                "trend_ranges": TREND_RANGE_CHOICES,
                "trend_sub_ranges": TREND_SUB_RANGE_CHOICES,
                "default_trend_range": DEFAULT_TREND_RANGE,
                #   Only the two series that belong to stories: how much is
                #   published and how often stories are opened. The Trends
                #   endpoint draws exactly what the legend has ticked.
                "series_meta": STORY_TREND_SERIES,
                "story_kpi_ranges": STORY_KPI_RANGE_CHOICES,
                "story_performance_series": STORY_PERFORMANCE_SERIES,
                "default_story_performance_series": DEFAULT_STORY_PERFORMANCE_SERIES,
                "category_performance_series": CATEGORY_PERFORMANCE_SERIES,
                "default_category_performance_series": DEFAULT_CATEGORY_PERFORMANCE_SERIES,
                #   The per-category charts work from the live category list.
                "categories": [
                    {
                        "name": name,
                        "label": NO_CATEGORY_LABEL if name == NO_CATEGORY_KEY else name,
                        "color": color,
                    }
                    for name, color in category_palette(category_names()).items()
                ],
                #   The per-category card opens on the subjects that have
                #   actually published, not on the first few in the menu: a
                #   card that starts on silent subjects reads as an empty
                #   chart, which is not what "nothing published" means.
                "default_categories": _default_chart_categories(),
                "active_chamber": "story",
            },
        )


def _default_chart_categories(limit=4):
    """The categories the per-category charts open on.

    The subjects that have actually published, busiest first. When nothing
    has been published at all the first few in the menu are used instead, so
    the card is never an empty box: an empty chart and a project with no
    stories are not the same thing.
    """
    counts = category_story_counts()
    known = category_names()
    ranked = sorted(
        (name for name in counts if name in known),
        key=lambda name: (-counts[name], name),
    )
    chosen = ranked[:limit]
    return chosen or known[:limit]


class PanelStaffGalleryView(View):
    """JSON feed powering the horizontal auto-scroll staff strip. Bigger page
    size than the old admin_only staff_directory list since this is meant to
    be paged in continuously as the strip is dragged, not clicked through."""

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required to view This Page."}, status=403)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        paginator = Paginator(staff_directory_queryset(), GALLERY_PAGE_SIZE)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        page = paginator.get_page(page_number)

        return JsonResponse(
            {
                "items": staff_directory_rows(list(page.object_list)),
                "page": page.number,
                "num_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
            },
            status=200,
        )


def _since_label(when, now):
    """'Today' / 'Yesterday' / 'N days ago' / a dated fallback, in local time.

    Both endpoints are localised first so a stored UTC instant never reads as a
    day off around midnight, and the fallback switches to an absolute date once
    "N days ago" stops being useful to scan.
    """
    if when is None:
        return ""
    days = (timezone.localtime(now).date() - timezone.localtime(when).date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    return timezone.localtime(when).strftime("%b %d, %Y")


def member_directory_rows(account_list):
    """Shape a page of member accounts into the row payload the ANALYTICS
    Members table renders. The address is only ever exposed masked, and the
    per-account reading/category aggregates come from one fixed set of
    page-wide queries (member_page_details), never one query per row."""
    accounts = list(account_list)
    details = member_page_details(accounts)
    now = timezone.now()

    rows = []
    for account in accounts:
        info = details.get(account.pk, {})
        last_read = info.get("last_read")
        last_login = account.last_login
        local = (account.email or "").partition("@")[0]
        rows.append(
            {
                "id": account.pk,
                "email_masked": _mask_email(account.email),
                "initial": (local[:1] or "?").upper(),
                "profile_img": account.profile_img or "",
                "joined_at": timezone.localtime(account.date_joined).strftime("%b %d, %Y"),
                "is_active": account.is_active,
                "send_newsletter": account.send_newsletter,
                "categories": info.get("categories", []),
                "last_read_label": _since_label(last_read, now) if last_read else "",
                "read_recently": bool(last_read and last_read >= now - timedelta(days=1)),
                "last_login_label": _since_label(last_login, now) if last_login else "Never",
                "is_newsletter_signup": last_login is None,
                "stories_read": info.get("stories_read", 0),
                "following": info.get("following", 0),
            }
        )
    return rows


def _session_detail_rows(account, now):
    """Per-session detail for one account, one dict per genuinely live session.

    "Genuinely live" means the row is not past its expiry, its Django session
    row still exists, and -- for admins -- the inactivity tracker is not past
    ADMIN_MAX_AGE_TOO. The same check drives the count, so the list, the
    number beside the account and any "all expired" hiding always agree."""
    detail = []
    for session in live_sessions_for(account, now):
        detail.append(
            {
                "session_key": session.session_key,
                "device": describe_device(session.user_agent),
                "ip": session.ip or "Unknown IP",
                "logged_in_at": timezone.localtime(session.logged_in_at).strftime("%b %d, %Y · %I:%M %p"),
                "last_seen": timezone.localtime(session.last_seen).strftime("%b %d, %Y · %I:%M %p"),
                "expires_at": (
                    timezone.localtime(session.expires_at).strftime("%b %d, %Y · %I:%M %p")
                    if session.expires_at else ""
                ),
                "is_suspicious": session.is_suspicious,
            }
        )
    return detail


def _active_sessions_page(page_number):
    """One row per account that currently holds at least one live session,
    not one row per session -- the logout button on that row drops every
    session the account has, matching how drop_sessions_for already works.

    "Live" is judged on UserSession.expires_at (which mirrors the Django
    session expiry) so rows left behind by an expired -- but never deleted --
    session never inflate the count or the list. Admin accounts are also put
    through the ADMIN_MAX_AGE_TOO inactivity check, because AdminMaxPeriod
    signs them out at that limit but the row survives when they never come
    back. Accounts whose sessions have all gone are dropped entirely."""
    now = timezone.now()
    live = UserSession.objects.filter(expires_at__isnull=False, expires_at__gt=now)

    account_ids = list(live.order_by().values_list("user_id", flat=True).distinct())

    #   An admin row can be past ADMIN_MAX_AGE_TOO while still being inside
    #   its cookie lifetime; the middleware would sign it out on the next
    #   request, so it is not a live session for counting purposes either.
    timed_out_admin_ids = {
        admin.pk
        for admin in Auth.objects.filter(pk__in=account_ids, is_admin=True)
        if not live_sessions_for(admin, now)
    }
    if timed_out_admin_ids:
        account_ids = [i for i in account_ids if i not in timed_out_admin_ids]

    accounts = list(Auth.objects.filter(pk__in=account_ids).order_by("-date_joined"))

    paginator = Paginator(accounts, SESSIONS_PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    page = paginator.get_page(page_number)

    session_counts = {}
    latest_logins = {}
    details = {}
    for account in page.object_list:
        account_sessions = live_sessions_for(account, now)
        session_counts[account.pk] = len(account_sessions)
        latest_logins[account.pk] = account_sessions[0].logged_in_at if account_sessions else None
        details[account.pk] = _session_detail_rows(account, now)

    rows = [
        {
            "id": account.pk,
            "is_staff": bool(account.is_staff),
            "email_masked": _mask_email(account.email),
            "session_count": session_counts.get(account.pk, 0),
            #   MOST RECENT LOGIN AMONG THIS ACCOUNT'S ACTIVE SESSIONS, SHOWN ON
            #   THE PANEL SO AN ADMIN CAN SEE WHEN SOMEONE ACTUALLY SIGNED IN.
            "logged_in_at": (
                timezone.localtime(latest_logins[account.pk]).strftime("%b %d, %Y · %I:%M %p")
                if latest_logins.get(account.pk) else ""
            ),
            "suspicious_count": sum(1 for item in details.get(account.pk, []) if item["is_suspicious"]),
            "sessions": details.get(account.pk, []),
        }
        for account in page.object_list
        if session_counts.get(account.pk, 0) > 0
    ]
    #   Total is the whole filtered candidate set, not just this page, so the
    #   header count stays right once the list runs to more than one page.
    return paginator, page, rows, paginator.count


class PanelSessionsView(View):
    """Paginated (5) JSON feed of who currently holds a live session."""

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required to view This Page."}, status=403)

        page_number = _resolve_page_number(request.GET.get("page"), default=1)
        paginator, page, rows, total_people = _active_sessions_page(page_number)

        return JsonResponse(
            {
                "items": rows,
                "page": page.number,
                "num_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
                "has_previous": page.has_previous(),
                "previous_page": page.previous_page_number() if page.has_previous() else None,
                "total_people": total_people,
            },
            status=200,
        )


class PanelSessionLogoutView(View):
    """Drops every session a given account holds, logging them out
    instantly. Reuses the exact same helper the suspend-account control uses."""

    def post(self, request, account_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        account = Auth.objects.filter(pk=account_id).first()
        if account is None:
            return JsonResponse({"detail": "Account not found."}, status=404)

        dropped = drop_sessions_for(account)
        info_logger(msg=f"PANEL: {dropped} session(s) for {account.email} ended by {request.user.email}")

        return JsonResponse({"detail": f"{dropped} session(s) ended.", "sessions_dropped": dropped}, status=200)


class PanelSingleSessionLogoutView(View):
    """Ends exactly one session of an account (its session key is in the body).

    The account id and the session key both have to agree before anything is
    dropped, so a stale panel page cannot end a session that has since been
    reissued to someone else."""

    def post(self, request, account_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        session_key = (request.POST.get("session_key") or "").strip()
        if not session_key:
            return JsonResponse({"detail": "Missing session."}, status=400)

        belongs = UserSession.objects.filter(user_id=account_id, session_key=session_key).exists()
        if not belongs:
            return JsonResponse({"detail": "Session not found."}, status=404)

        drop_single_session(session_key)
        info_logger(
            msg=f"PANEL: one session for account {account_id} ended by {request.user.email}"
        )
        return JsonResponse({"detail": "Session ended."}, status=200)


class PanelSiteSettingsUpdateView(View):
    """Saves the socials / contact addresses row PANEL edits instead of a
    code deploy. Every field is optional -- clearing one falls back to the
    About defaults everywhere it is used (see custom_context_processors)."""

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        settings_row = SiteSettings.get_solo()
        settings_row.twitter_handle = (request.POST.get("twitter_handle") or "").strip()
        settings_row.facebook_handle = (request.POST.get("facebook_handle") or "").strip()
        settings_row.promotion_email = (request.POST.get("promotion_email") or "").strip()
        settings_row.tech_expert_email = (request.POST.get("tech_expert_email") or "").strip()
        settings_row.support_email = (request.POST.get("support_email") or "").strip()
        settings_row.whatsapp_channel = (request.POST.get("whatsapp_channel") or "").strip()
        settings_row.customer_support_mobile = (request.POST.get("customer_support_mobile") or "").strip()
        settings_row.ads_whatsapp_support = (request.POST.get("ads_whatsapp_support") or "").strip()
        settings_row.save()

        #   The context processor keeps this row in the cache with no TTL, so
        #   saving without clearing it would leave the old contact details on
        #   the site until the process restarted.
        invalidate_cache("site_settings_socials")

        info_logger(msg=f"PANEL: site settings updated by {request.user.email}")

        return JsonResponse({"detail": "Site settings saved."}, status=200)


def _category_rows():
    """Every news category in menu order with the number of stories that
    currently carry it. Read straight from the table (not the cache) because
    PANEL needs the row ids and must always show what is really stored."""
    story_counts = dict(Blog.objects.order_by().values_list("category").annotate(total=Count("id")))
    return [
        {"id": category.id, "name": category.name, "label": title_case(category.name), "story_count": story_counts.get(category.name, 0)}
        for category in Category.objects.all()
    ]


class PanelCategoryCreateView(View):
    """Adds a news category. It reaches the navbar menu, the story form and
    every category check straight away: Category.save() rebuilds the no-TTL
    category cache (BLOG/signals.py), so nothing here touches the cache."""

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        name = " ".join((request.POST.get("name") or "").split()).upper()
        if not name:
            return JsonResponse({"detail": "Enter a category name."}, status=400)

        category = Category(name=name)
        try:
            #   full_clean: length, allowed characters and the case insensitive duplicate check
            category.full_clean()
            #   atomic: a constraint failure rolls back only this save, it never
            #   leaves a surrounding transaction (ATOMIC_REQUESTS) broken
            with transaction.atomic():
                category.save()
        except ValidationError as error:
            return JsonResponse({"detail": error.messages[0]}, status=400)
        except IntegrityError:
            #   two admins adding the same name at the same instant, the database constraint wins
            return JsonResponse({"detail": "That category already exists."}, status=400)

        info_logger(msg=f"PANEL: category {category.name} added by {request.user.email}")

        #   NOT always 0: re-adding a retired category (e.g. SECURITY) brings back
        #   the stories that were still carrying it
        story_count = Blog.objects.filter(category=category.name).count()
        detail = f"{title_case(category.name)} added."
        if story_count:
            detail += f" {story_count} existing {'story shows' if story_count == 1 else 'stories show'} under it again."

        return JsonResponse(
            {
                "detail": detail,
                "category": {"id": category.id, "name": category.name, "label": title_case(category.name), "story_count": story_count},
            },
            status=201,
        )


class PanelCategoryDeleteView(View):
    """Removes a news category from the menu and the story form. Stories that
    already carry it are NOT touched: they stay published and editable (see
    HOME.views.EditNewsView `legacy_category`). The last remaining category
    cannot be removed, otherwise nobody could publish a story any more."""

    def post(self, request, category_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        category = Category.objects.filter(pk=category_id).first()
        if category is None:
            return JsonResponse({"detail": "Category not found."}, status=404)
        if Category.objects.count() <= 1:
            return JsonResponse({"detail": "At least one category has to stay so stories can still be published."}, status=400)

        name = category.name
        story_count = Blog.objects.filter(category=name).count()
        category.delete()

        info_logger(msg=f"PANEL: category {name} removed by {request.user.email} ({story_count} stories still carry it)")

        detail = f"{title_case(name)} removed."
        if story_count:
            detail += f" {story_count} existing {'story stays' if story_count == 1 else 'stories stay'} published under it."
        return JsonResponse({"detail": detail, "story_count": story_count}, status=200)



class PanelUnknownAuthorDeleteView(View):
    """Permanently delete a story left behind by a deactivated author.

    Restricted to admin/superuser and to stories whose author is anonymized;
    a live author's story must be handled through their own profile tools.
    The uploaded banner is released with the same helper the profile delete
    uses, so no Cloudinary asset is orphaned.
    """

    def post(self, request, blog_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied

        story = (
            Blog.all_objects.select_related("author")
            .filter(pk=blog_id, author__deleted_at__isnull=False)
            .first()
        )
        if story is None:
            return JsonResponse({"detail": "Story not found."}, status=404)

        heading = story.heading
        image_public_id = story.image_public_id
        story.delete()
        _release_story_image(image_public_id)

        remaining = Blog.all_objects.filter(author__deleted_at__isnull=False).count()
        info_logger(
            msg=f"PANEL: unknown-author story {blog_id} ({heading}) deleted by {request.user.email}"
        )
        return JsonResponse(
            {"detail": "Story deleted.", "remaining": remaining}, status=200
        )

class PanelStaffSearchView(View):
    """The "+" search in the mass-email composer. Matches StaffProfile
    full_name, case-insensitive. Only ever used to add an individual on top
    of the Member/Staff/Admin toggles -- it never returns raw emails, only
    enough to render a confirmation row (name + avatar)."""

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required to view This Page."}, status=403)

        query = (request.GET.get("q") or "").strip()
        if not query:
            return JsonResponse({"items": []}, status=200)

        profiles = (
            StaffProfile.objects.select_related("auth")
            .filter(full_name__icontains=query, auth__is_active=True)
            .order_by("full_name")[:8]
        )

        items = [
            {
                "account_id": profile.auth_id,
                "full_name": profile.full_name,
                "profile_img": profile.auth.profile_img or "",
                "authority": (
                    "SAdmin" if profile.auth.is_superuser else "Admin" if profile.auth.is_admin else "Staff"
                ),
            }
            for profile in profiles
        ]
        return JsonResponse({"items": items}, status=200)


def _mass_email_recipients(include_member, include_staff, include_admin, extra_account_ids):
    """Resolves the toggle state + explicit "+" adds into a final, deduped
    email address list. Never sent to the client -- this stays server side
    end to end."""
    query = Q(pk__in=[])
    if include_member:
        query |= Q(is_staff=False, is_admin=False, is_superuser=False)
    if include_staff:
        query |= Q(is_staff=True, is_admin=False, is_superuser=False)
    if include_admin:
        query |= Q(is_admin=True) | Q(is_superuser=True)
    if extra_account_ids:
        query |= Q(pk__in=extra_account_ids)

    return list(Auth.objects.filter(query, is_active=True).values_list("email", flat=True).distinct())


class PanelMassEmailView(View):
    """Send mass email action. The sending admin must have a StaffProfile
    full_name -- the From header's display name comes from it and an admin
    account with no full name is treated as broken here, exactly like
    StaffCreateView already requires a full name for every new account."""

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 30, 5)
        if limited:
            return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        sender_profile = StaffProfile.objects.filter(auth=request.user).first()
        sender_full_name = sender_profile.full_name.strip() if sender_profile and sender_profile.full_name else ""
        if not sender_full_name:
            return JsonResponse(
                {"detail": "Your staff profile has no full name set. An admin cannot send mass email without one."},
                status=409,
            )

        subject = (request.POST.get("subject") or "").strip()
        body = (request.POST.get("body") or "").strip()
        if not subject:
            return JsonResponse({"detail": "Enter an email heading."}, status=400)
        if not body:
            return JsonResponse({"detail": "Enter the email body."}, status=400)

        include_member = request.POST.get("include_member") == "on"
        include_staff = request.POST.get("include_staff") == "on"
        include_admin = request.POST.get("include_admin") == "on"
        extra_raw = request.POST.get("extra_account_ids") or ""
        try:
            extra_account_ids = [int(v) for v in extra_raw.split(",") if v.strip().isdigit()]
        except ValueError:
            extra_account_ids = []

        recipients = _mass_email_recipients(include_member, include_staff, include_admin, extra_account_ids)
        if not recipients:
            return JsonResponse({"detail": "No recipients selected."}, status=400)

        body_html = "<p>" + body.replace("\r\n", "\n").replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        sent_total = _try_send_panel_mass_email(sender_full_name, subject, body_html, recipients, request.user.email)

        info_logger(
            msg=f"PANEL MASS EMAIL: {request.user.email} sent '{subject}' to {sent_total} recipients "
            f"(member={include_member}, staff={include_staff}, admin={include_admin}, extra={len(extra_account_ids)})"
        )

        return JsonResponse({"detail": f"Email queued for {sent_total} recipient(s)."}, status=200)


class PanelSpecialityView(View):
    """Paginated (5) staff search by speciality tag. StaffProfile.speciality
    is a JSONField list, so the match happens in Python rather than a
    backend-specific JSON lookup -- fine at staff-directory scale."""

    def get(self, request):
        if not admin_only(request.user):
            return JsonResponse({"detail": "Admin access is required to view This Page."}, status=403)

        query = (request.GET.get("q") or "").strip().lower()
        page_number = _resolve_page_number(request.GET.get("page"), default=1)

        profiles = StaffProfile.objects.select_related("auth").filter(auth__is_active=True).order_by("full_name")
        if query:
            matched = [
                profile
                for profile in profiles
                if isinstance(profile.speciality, list)
                and any(query in str(item).lower() for item in profile.speciality)
            ]
        else:
            matched = list(profiles)

        paginator = Paginator(matched, SPECIALITY_PAGE_SIZE)
        if page_number > paginator.num_pages and paginator.num_pages:
            raise Http404("Page not found.")
        page = paginator.get_page(page_number)

        items = [
            {
                "id": profile.auth_id,
                "full_name": profile.full_name or "NO USERNAME",
                "profile_img": profile.auth.profile_img or "",
                "speciality": profile.speciality if isinstance(profile.speciality, list) else [],
                "achievement": _staff_achievement_text(profile),
                "url": reverse("control:staff_detail", args=[profile.auth_id]),
            }
            for profile in page.object_list
        ]

        return JsonResponse(
            {
                "items": items,
                "page": page.number,
                "num_pages": paginator.num_pages,
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
                "has_previous": page.has_previous(),
                "previous_page": page.previous_page_number() if page.has_previous() else None,
                "count": paginator.count,
            },
            status=200,
        )


"""
------------------------------------------------------------
#   ANNOUNCEMENTS
------------------------------------------------------------
The scrolling bar at the top of the home page (HOME.views._announcement_items)
shows every Partner.Announcement row that is active and not expired. These
three endpoints let an admin add, edit and delete those rows from PANEL.
"""

ANNOUNCEMENT_LIST_LIMIT = 100   #   newest rows shown in PANEL


def _announcement_item(row):
    expiry = timezone.localtime(row.expiry_date)
    if not row.is_active:
        status = "paused"
    elif row.expiry_date < timezone.now():
        status = "expired"
    else:
        status = "live"
    return {
        "id": row.id,
        "content": row.content,
        "url": row.url or "",
        "expiry_input": expiry.strftime("%Y-%m-%dT%H:%M"),
        "expiry_label": expiry.strftime("%d %b %Y, %H:%M"),
        "is_active": row.is_active,
        "status": status,
        "added_by": _mask_email(row.author.email) if row.author_id else "",
    }


def _announcement_items():
    rows = Announcement.objects.select_related("author").order_by("-date_created")[:ANNOUNCEMENT_LIST_LIMIT]
    return [_announcement_item(row) for row in rows]


def _clean_announcement(post):
    """Validate the posted fields. Returns (values, error)."""
    content = " ".join((post.get("content") or "").split())
    if not content:
        return None, "Enter the text to scroll."
    if len(content) > 400:
        return None, "The text can be at most 400 characters."

    url = (post.get("url") or "").strip()
    if url:
        if not url.lower().startswith(("http://", "https://")):
            return None, "The link must start with http:// or https://"
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            return None, "Enter a valid link, or leave it empty."

    expiry = parse_datetime((post.get("expiry_date") or "").strip())
    if expiry is None:
        return None, "Pick when this text should stop showing."
    if timezone.is_naive(expiry):
        expiry = timezone.make_aware(expiry, timezone.get_current_timezone())

    is_active = (post.get("is_active") or "").lower() in ("1", "true", "on", "yes")
    return {"content": content, "url": url or None, "expiry_date": expiry, "is_active": is_active}, None


def _panel_write_guard(request):
    """Rate limit + admin check shared by the panel write endpoints. Returns an error response or None."""
    remaining_seconds, limited = is_rate_limited(request, 10, 30)
    if limited:
        return JsonResponse({"detail": f"Permission Denied, Wait {remaining_seconds} seconds"}, status=403)
    if not admin_only(request.user):
        return JsonResponse({"detail": "Admin access is required."}, status=403)
    return None


class PanelAnnouncementCreateView(View):
    def post(self, request):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        values, error = _clean_announcement(request.POST)
        if error:
            return JsonResponse({"detail": error}, status=400)
        if values["expiry_date"] <= timezone.now():
            return JsonResponse({"detail": "The end time has to be in the future."}, status=400)

        row = Announcement.objects.create(author=request.user, **values)
        info_logger(msg=f"PANEL: announcement {row.id} added by {request.user.email}")
        return JsonResponse({"detail": "Text added to the scrolling bar.", "item": _announcement_item(row)}, status=201)


class PanelAnnouncementUpdateView(View):
    def post(self, request, item_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        row = Announcement.objects.select_related("author").filter(pk=item_id).first()
        if row is None:
            return JsonResponse({"detail": "That text no longer exists."}, status=404)
        values, error = _clean_announcement(request.POST)
        if error:
            return JsonResponse({"detail": error}, status=400)

        for field, value in values.items():
            setattr(row, field, value)
        row.save()
        info_logger(msg=f"PANEL: announcement {row.id} edited by {request.user.email}")
        return JsonResponse({"detail": "Text updated.", "item": _announcement_item(row)}, status=200)


class PanelAnnouncementDeleteView(View):
    def post(self, request, item_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        row = Announcement.objects.filter(pk=item_id).first()
        if row is None:
            return JsonResponse({"detail": "That text no longer exists."}, status=404)
        row.delete()
        info_logger(msg=f"PANEL: announcement {item_id} deleted by {request.user.email}")
        return JsonResponse({"detail": "Text deleted."}, status=200)


"""
------------------------------------------------------------
#   IMAGE ADVERTS
------------------------------------------------------------
The picture carousel beside the hero on the home page
(HOME.views._teaser_items) shows every Partner.AdvertImage row that is
active and not expired. Mobile shows the picture only, desktop also shows
heading + body under it. These three endpoints let an admin add, edit
(optionally replacing the picture in place) and delete those rows from PANEL.
"""

IMAGE_ADVERT_LIST_LIMIT = 100   #   newest rows shown in PANEL


def _image_advert_landing_status(row):
    landing = getattr(row, "landing_page", None)
    if landing is None or not landing.html_public_id:
        return "none"
    if not landing.author_is_trusted:
        return "blocked"
    if not landing.is_published:
        return "draft"
    return "live"


def _image_advert_item(row):
    expiry = timezone.localtime(row.expiry_date)
    if not row.is_active:
        status = "paused"
    elif row.expiry_date < timezone.now():
        status = "expired"
    else:
        status = "live"
    landing = getattr(row, "landing_page", None)
    landing_status = _image_advert_landing_status(row)
    landing_path = advert_landing_url(row) if landing else ""
    return {
        "id": row.id,
        "heading": row.heading,
        "body": row.body,
        "image": row.image_url,
        "url": row.url or "",
        "expiry_input": expiry.strftime("%Y-%m-%dT%H:%M"),
        "expiry_label": expiry.strftime("%d %b %Y, %H:%M"),
        "is_active": row.is_active,
        "status": status,
        "added_by": _mask_email(row.author.email) if row.author_id else "",
        "landing_status": landing_status,
        "landing_url": landing_path if landing_status == "live" else "",
        "landing_path": landing_path,
        "landing_slug": advert_landing_slug(row) if landing else "",
        "landing_author": (landing.author_label if landing else ""),
        "landing_updated": (
            timezone.localtime(landing.date_updated).strftime("%d %b %Y, %H:%M")
            if landing
            else ""
        ),
    }


def _image_advert_items():
    rows = (
        AdvertImage.objects.select_related("author", "landing_page__author")
        .order_by("-date_created")[:IMAGE_ADVERT_LIST_LIMIT]
    )
    return [_image_advert_item(row) for row in rows]


def _clean_image_advert(post):
    """Validate the posted text fields (the picture is checked separately).
    Returns (values, error)."""
    heading = " ".join((post.get("heading") or "").split())
    body = " ".join((post.get("body") or "").split())
    if len(heading) > 90:
        return None, "The heading can be at most 90 characters."
    if len(body) > 200:
        return None, "The text can be at most 200 characters."

    #   There is no link here on purpose. The link an advert opens is set in
    #   the Ads desk (the reference's public URL) and copied onto the advert.
    expiry = parse_datetime((post.get("expiry_date") or "").strip())
    if expiry is None:
        return None, "Pick when this advert should stop showing."
    if timezone.is_naive(expiry):
        expiry = timezone.make_aware(expiry, timezone.get_current_timezone())

    is_active = (post.get("is_active") or "").lower() in ("1", "true", "on", "yes")
    return {"heading": heading, "body": body, "expiry_date": expiry, "is_active": is_active}, None


class PanelImageAdvertCreateView(View):
    def post(self, request):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        values, error = _clean_image_advert(request.POST)
        if error:
            return JsonResponse({"detail": error}, status=400)
        if values["expiry_date"] <= timezone.now():
            return JsonResponse({"detail": "The end time has to be in the future."}, status=400)

        image_file = request.FILES.get("image")
        if image_file is None:
            return JsonResponse({"detail": "Choose the advert picture."}, status=400)
        try:
            uploaded = upload_advert_image(image_file)
        except ImageUploadError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)

        try:
            row = AdvertImage.objects.create(
                author=request.user,
                image_url=uploaded["secure_url"],
                image_public_id=uploaded["public_id"],
                **values,
            )
        except Exception:
            #   THE PICTURE IS ALREADY UP, DON'T LEAVE IT ORPHANED
            destroy_archive_asset(uploaded["public_id"])
            raise
        info_logger(msg=f"PANEL: image advert {row.id} added by {request.user.email}")
        return JsonResponse({"detail": "Advert added to the home page.", "item": _image_advert_item(row)}, status=201)


class PanelImageAdvertUpdateView(View):
    def post(self, request, item_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        row = AdvertImage.objects.select_related("author").filter(pk=item_id).first()
        if row is None:
            return JsonResponse({"detail": "That advert no longer exists."}, status=404)
        values, error = _clean_image_advert(request.POST)
        if error:
            return JsonResponse({"detail": error}, status=400)

        #   A NEW PICTURE IS OPTIONAL ON EDIT. WHEN SENT, IT OVERWRITES THE
        #   EXISTING CLOUDINARY ASSET IN PLACE (SAME public_id).
        image_file = request.FILES.get("image")
        if image_file is not None:
            try:
                uploaded = upload_advert_image(image_file, public_id=row.image_public_id or None)
            except ImageUploadError as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
            row.image_url = uploaded["secure_url"]
            row.image_public_id = uploaded["public_id"]

        for field, value in values.items():
            setattr(row, field, value)
        row.save()
        info_logger(msg=f"PANEL: image advert {row.id} edited by {request.user.email}")
        return JsonResponse({"detail": "Advert updated.", "item": _image_advert_item(row)}, status=200)


class PanelImageAdvertDeleteView(View):
    def post(self, request, item_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        row = AdvertImage.objects.filter(pk=item_id).first()
        if row is None:
            return JsonResponse({"detail": "That advert no longer exists."}, status=404)
        public_id = row.image_public_id
        row.delete()
        if public_id:
            destroy_archive_asset(public_id)
        info_logger(msg=f"PANEL: image advert {item_id} deleted by {request.user.email}")
        return JsonResponse({"detail": "Advert deleted."}, status=200)


"""
------------------------------------------------------------
#   IMAGE ADVERT LANDING PAGE
------------------------------------------------------------
The landing page is a complete HTML document stored in Cloudinary (raw,
authenticated). PANEL edits it in a full-width modal: GET loads the current
file (without its internal author header), POST saves/overwrites it, POST
preview renders the unsaved text through the same token replacer the public
view uses, and POST delete removes the row + Cloudinary object.

The public view in Partner.views re-reads this row on every request and refuses
to run the file unless its last writer is still an active admin/superuser.
"""


def _active_admin_required(request):
    if not admin_only(request.user) or not getattr(request.user, "is_active", False):
        return JsonResponse({"detail": "Admin access is required."}, status=403)
    return None


def _clean_advert_landing(post):
    """Validate the editor fields. Returns (values, error)."""
    html_text = strip_advert_landing_author_header((post.get("html") or "").strip())
    if not html_text:
        return None, "Paste the landing page HTML first."
    if len(html_text.encode("utf-8")) > ADVERT_LANDING_MAX_BYTES:
        return None, (
            f"Landing page HTML is too large. Max allowed size is "
            f"{ADVERT_LANDING_MAX_BYTES // (1024 * 1024)}MB."
        )

    meta_title = " ".join((post.get("meta_title") or "").split())
    if len(meta_title) > 120:
        return None, "The metadata title can be at most 120 characters."

    meta_description = " ".join((post.get("meta_description") or "").split())
    if len(meta_description) > 320:
        return None, "The metadata description can be at most 320 characters."

    og_image = (post.get("og_image") or "").strip()
    if og_image:
        try:
            URLValidator(schemes=["http", "https"])(og_image)
        except ValidationError:
            return None, "Enter a valid OG image URL, or leave it empty to use the advert picture."

    robots = (post.get("robots") or ROBOTS_DEFAULT).strip() or ROBOTS_DEFAULT
    valid_robots = {value for value, _label in AdvertLandingPage.ROBOTS_CHOICES}
    if robots not in valid_robots:
        return None, "Choose a valid robots setting."

    return {
        "html": html_text,
        "meta_title": meta_title,
        "meta_description": meta_description,
        "og_image": og_image,
        "robots": robots,
        "is_published": (post.get("is_published") or "").lower() in ("1", "true", "on", "yes"),
    }, None


def _landing_response_payload(row):
    landing = getattr(row, "landing_page", None)
    return {
        "item": _image_advert_item(row),
        "html": "",
        "template": "",
        "fetch_error": "",
        "landing": {
            "meta_title": landing.meta_title if landing else "",
            "meta_description": landing.meta_description if landing else "",
            "og_image": landing.og_image if landing else "",
            "robots": landing.robots if landing else ROBOTS_DEFAULT,
            "is_published": bool(landing.is_published) if landing else False,
        },
        "tokens": [
            {"name": name, "description": description}
            for name, description in ADVERT_LANDING_TOKENS
        ],
        "robots_choices": [
            {"value": value, "label": label}
            for value, label in AdvertLandingPage.ROBOTS_CHOICES
        ],
    }


class PanelImageAdvertLandingView(View):
    def get(self, request, item_id):
        denied = _active_admin_required(request)
        if denied:
            return denied
        row = (
            AdvertImage.objects.select_related("author", "landing_page__author")
            .filter(pk=item_id)
            .first()
        )
        if row is None:
            return JsonResponse({"detail": "That advert no longer exists."}, status=404)

        payload = _landing_response_payload(row)
        landing = getattr(row, "landing_page", None)
        if landing is None or not landing.html_public_id:
            payload["template"] = DEFAULT_ADVERT_LANDING_TEMPLATE
            return JsonResponse(payload, status=200)

        try:
            payload["html"] = strip_advert_landing_author_header(
                fetch_advert_landing_html(landing.html_public_id)
            )
        except ImageUploadError as exc:
            payload["fetch_error"] = str(exc)

        return JsonResponse(payload, status=200)

    def post(self, request, item_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        if not getattr(request.user, "is_active", False):
            return JsonResponse({"detail": "Admin access is required."}, status=403)

        row = (
            AdvertImage.objects.select_related("author", "landing_page__author")
            .filter(pk=item_id)
            .first()
        )
        if row is None:
            return JsonResponse({"detail": "That advert no longer exists."}, status=404)

        values, error = _clean_advert_landing(request.POST)
        if error:
            return JsonResponse({"detail": error}, status=400)
        #   The plan on the advert's reference decides if it may have a landing page.
        if not advert_allows(row, "landing_page"):
            reference = row.reference
            return JsonResponse({"detail": plan_message(reference.plan, "landing_page")}, status=400)

        landing = getattr(row, "landing_page", None)
        previous_public_id = landing.html_public_id if landing else ""

        try:
            uploaded = upload_advert_landing_html(
                add_advert_landing_author_header(values["html"], row, request.user),
                row.pk,
            )
        except ImageUploadError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)

        try:
            if landing is None:
                landing = AdvertLandingPage(advert=row)
            landing.meta_title = values["meta_title"]
            landing.meta_description = values["meta_description"]
            landing.og_image = values["og_image"]
            landing.robots = values["robots"]
            landing.is_published = values["is_published"]
            landing.html_public_id = uploaded["public_id"]
            landing.html_bytes = uploaded["bytes"]
            landing.author = request.user
            landing.save()
        except Exception:
            if not previous_public_id:
                destroy_advert_landing_html(uploaded["public_id"])
            raise

        row = (
            AdvertImage.objects.select_related("author", "landing_page__author")
            .get(pk=row.pk)
        )
        if values["is_published"]:
            detail = "Landing page saved and published."
        else:
            detail = "Landing page saved as a draft. Advert clicks use the advertiser link until it is published."
        info_logger(msg=f"PANEL: landing page for image advert {item_id} saved by {request.user.email}")
        return JsonResponse({"detail": detail, "item": _image_advert_item(row)}, status=200)


class PanelImageAdvertLandingPreviewView(View):
    def post(self, request, item_id):
        denied = _active_admin_required(request)
        if denied:
            return denied
        remaining_seconds, limited = is_rate_limited(request, 10, 30, scope="advert-landing-preview")
        if limited:
            return JsonResponse(
                {"detail": f"Too many previews. Wait {remaining_seconds} seconds."},
                status=429,
            )
        row = AdvertImage.objects.select_related("author").filter(pk=item_id).first()
        if row is None:
            return JsonResponse({"detail": "That advert no longer exists."}, status=404)

        values, error = _clean_advert_landing(request.POST)
        if error:
            return JsonResponse({"detail": error}, status=400)

        rendered = render_advert_landing_document(
            advert=row,
            request=request,
            html_text=values["html"],
            meta_title=values["meta_title"],
            meta_description=values["meta_description"],
            og_image=values["og_image"],
            robots=values["robots"],
        )
        return JsonResponse({"detail": "Preview ready.", "html": rendered}, status=200)


class PanelImageAdvertLandingDeleteView(View):
    def post(self, request, item_id):
        denied = _panel_write_guard(request)
        if denied:
            return denied
        if not getattr(request.user, "is_active", False):
            return JsonResponse({"detail": "Admin access is required."}, status=403)
        row = AdvertImage.objects.filter(pk=item_id).first()
        if row is None:
            return JsonResponse({"detail": "That advert no longer exists."}, status=404)
        landing = getattr(row, "landing_page", None)
        if landing is None:
            return JsonResponse({"detail": "This advert has no landing page."}, status=404)
        landing.delete()
        row = (
            AdvertImage.objects.select_related("author", "landing_page__author")
            .get(pk=row.pk)
        )
        info_logger(msg=f"PANEL: landing page for image advert {item_id} deleted by {request.user.email}")
        return JsonResponse(
            {"detail": "Landing page deleted. Advert clicks now use the advertiser link.", "item": _image_advert_item(row)},
            status=200,
        )


"""
------------------------------------------------------------
#   ADVERT REFERENCES / ADS DESK
------------------------------------------------------------
One permanent reference is issued per advert, not per account. The ads desk
(admin, superuser or Auth.is_ads_staff) uses this page to issue, pause, renew
and re-point references. Nothing here exposes the staff directory, site
settings or the rest of PANEL, so limited ads staff can do their job without
receiving full admin authority.
"""

ADVERT_REFERENCE_LIST_LIMIT = 100
ADVERT_REFERENCE_RENEW_DAYS = 7
ADVERT_RESERVED_SUBDOMAINS = RESERVED_SUBDOMAINS


def _reference_form_data(post=None, defaults=False):
    """Values for the issue form.

    ``defaults`` is only used for a fresh GET: it fills the current week so
    staff can issue a reference without typing dates. A submitted empty date
    stays empty, which is how staff clear an end date on an existing row.
    """
    post = post or {}
    now = timezone.localtime()
    default_start = now.strftime("%Y-%m-%dT%H:%M") if defaults else ""
    default_end = (
        (now + timedelta(days=ADVERT_REFERENCE_RENEW_DAYS)).strftime("%Y-%m-%dT%H:%M")
        if defaults
        else ""
    )
    return {
        "email": (post.get("email") or "").strip(),
        "plan": (post.get("plan") or AdvertLead.PLAN_REGULAR).strip(),
        "business_name": (post.get("business_name") or "").strip(),
        "starts_at": (post.get("starts_at", default_start) or "").strip(),
        "expires_at": (post.get("expires_at", default_end) or "").strip(),
        "public_url": (post.get("public_url") or "").strip(),
        "subdomain": (post.get("subdomain") or "").strip().lower(),
        "advert_id": (post.get("advert_id") or "").strip(),
        "notes": (post.get("notes") or "").strip(),
    }


def _parse_form_datetime(value):
    value = (value or "").strip()
    if not value:
        return None, None
    parsed = parse_datetime(value)
    if parsed is None:
        return None, "Enter a valid date and time."
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed, None


def _validate_reference_fields(form, existing=None):
    """Shared validation for issuing and editing a reference.

    The owner is chosen once, at issuance, and is intentionally not editable
    here: analytics are filtered by that owner, so changing it would hand one
    advertiser's traffic to another account.
    """
    plan = form["plan"]
    if plan not in {value for value, _label in AdvertLead.PLAN_CHOICES}:
        return None, "Choose a valid plan."

    business_name = " ".join(form["business_name"].split())
    if not business_name:
        return None, "Enter the business name."
    if len(business_name) > 120:
        return None, "Business name must be 120 characters or fewer."

    starts_at, error = _parse_form_datetime(form["starts_at"])
    if error:
        return None, error
    expires_at, error = _parse_form_datetime(form["expires_at"])
    if error:
        return None, error
    if starts_at and expires_at and expires_at <= starts_at:
        return None, "The end date must be after the start date."

    public_url = form["public_url"]
    if public_url:
        try:
            URLValidator(schemes=["http", "https"])(public_url)
        except ValidationError:
            return None, "Enter a valid http(s) public URL."

    subdomain = form["subdomain"]
    if subdomain:
        if subdomain in ADVERT_RESERVED_SUBDOMAINS:
            return None, "That subdomain is reserved for the site. Choose another."
        if "." in subdomain:
            return None, "Enter only the subdomain label, for example newads."
        #   A standard host name label (RFC 1123): letters, digits and hyphens,
        #   1 to 63 characters, no hyphen at either end.
        if "_" in subdomain:
            return None, "Underscores are not valid in a web address. Use a hyphen, like my-shop."
        if len(subdomain) > 63:
            return None, "A subdomain can have at most 63 characters."
        if subdomain.startswith("-") or subdomain.endswith("-"):
            return None, "A subdomain cannot start or end with a hyphen."
        if not re.fullmatch(r"[a-z0-9-]+", subdomain):
            return None, "Use only lowercase letters, numbers and hyphens, like my-shop."
        if not ads_base_host():
            return None, "Set ALLOWED_HOSTS or ADS_HOST before assigning a subdomain."
        if not advert_host(subdomain):
            return None, (
                "Use one lowercase label of 1-63 letters, numbers or hyphens, "
                "without a leading or trailing hyphen."
            )
        conflict = AdvertReference.objects.filter(subdomain__iexact=subdomain)
        if existing is not None:
            conflict = conflict.exclude(pk=existing.pk)
        if conflict.exists():
            return None, "Another advert already uses that subdomain."
        if not plan_allows(plan, "subdomain"):
            return None, plan_message(plan, "subdomain")

    advert = None
    if form["advert_id"]:
        try:
            advert_id = int(form["advert_id"])
        except (TypeError, ValueError):
            return None, "Choose a valid advert."
        advert = AdvertImage.objects.filter(pk=advert_id).first()
        if advert is None:
            return None, "That advert no longer exists."
        conflict = AdvertReference.objects.filter(advert=advert)
        if existing is not None:
            conflict = conflict.exclude(pk=existing.pk)
        if conflict.exists():
            return None, "That advert already has a reference. Each advert has exactly one."

    #   Pro and Advance are subdomain plans. Staff can only leave it empty when
    #   the advert opens an external link instead (Public page URL, or the link
    #   saved on the advert image).
    if plan_allows(plan, "subdomain") and not subdomain:
        external = public_url or bool(advert and (advert.url or "").strip())
        if not external:
            return None, (
                "Pro and Advance plans need a subdomain. Add one, or set a Public "
                "page URL (or an advert link) to open an external link instead."
            )

    notes = form["notes"]
    if len(notes) > 1000:
        return None, "Notes must be 1,000 characters or fewer."

    return {
        "plan": plan,
        "business_name": business_name,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "public_url": public_url or "",
        "subdomain": subdomain or None,
        "advert": advert,
        "notes": notes,
    }, None


def _clean_reference_form(post):
    form = _reference_form_data(post)
    email = form["email"]
    if not email or "@" not in email:
        return form, None, "Enter the advertiser's account email."
    try:
        validate_email(email)
    except ValidationError:
        return form, None, "Enter a valid email address."
    account = Auth.objects.filter(email__iexact=email).first()
    if account is None:
        return form, None, "No account uses that email. Ask the advertiser to sign up first."
    values, error = _validate_reference_fields(form)
    if error:
        return form, None, error
    return form, {"account": account, **values}, None


def _clean_reference_update_form(post, reference):
    form = _reference_form_data(post)
    form["email"] = reference.user.email
    values, error = _validate_reference_fields(form, existing=reference)
    if error:
        return form, None, error
    return form, values, None


def _reference_edit_values(reference):
    starts_at = (
        timezone.localtime(reference.starts_at).strftime("%Y-%m-%dT%H:%M")
        if reference.starts_at
        else ""
    )
    expires_at = (
        timezone.localtime(reference.expires_at).strftime("%Y-%m-%dT%H:%M")
        if reference.expires_at
        else ""
    )
    return {
        "plan": reference.plan,
        "business_name": reference.business_name,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "public_url": reference.public_url,
        "subdomain": reference.subdomain or "",
        "advert_id": str(reference.advert_id) if reference.advert_id else "",
        "notes": reference.notes,
    }


def _reference_status(reference):
    now = timezone.now()
    if reference.status == AdvertReference.STATUS_PAUSED:
        return "paused", "Paused"
    if reference.status == AdvertReference.STATUS_EXPIRED or reference.is_expired:
        return "expired", "Expired"
    if reference.starts_at and reference.starts_at > now:
        return "scheduled", "Scheduled"
    return "live", "Live"


def _advert_choices(current_advert_id=None):
    """Options for the advert picker. An advert already tied to another
    reference is shown but disabled, so the one-reference-per-advert rule is
    visible before the server rejects it."""
    taken = {
        row.advert_id: row.reference
        for row in AdvertReference.objects.exclude(advert__isnull=True).select_related("advert")
    }
    choices = []
    for advert in AdvertImage.objects.order_by("-date_created")[:200]:
        taken_by = taken.get(advert.pk, "")
        choices.append(
            {
                "id": advert.pk,
                "label": advert.heading or f"Advert #{advert.pk}",
                "taken_by": taken_by,
                "allowed": not taken_by or advert.pk == current_advert_id,
                "has_url": bool((advert.url or "").strip()),
            }
        )
    return choices


def _advert_reference_row(reference, advert_choices, storage_counts=None):
    status_key, status_label = _reference_status(reference)
    advert = reference.advert
    landing = getattr(advert, "landing_page", None)
    has_landing = bool(landing and landing.is_deliverable)
    return {
        "id": reference.pk,
        "reference": reference.reference,
        "email": reference.user.email,
        "email_used": reference.email_used,
        "plan": reference.plan,
        "plan_label": reference.plan_name,
        "business_name": reference.business_name,
        "status": status_key,
        "status_label": status_label,
        "is_live": reference.is_live,
        "is_expired": reference.is_expired,
        "starts_at": reference.starts_at,
        "expires_at": reference.expires_at,
        "public_url": reference.public_url,
        "public_target": reference.public_target,
        "subdomain": reference.subdomain or "",
        "public_host": reference.public_host,
        "public_page_url": reference.public_page_url,
        "public_link": reference.public_link,
        "advert_id": advert.pk if advert else None,
        "advert_label": (advert.heading or f"Advert #{advert.pk}") if advert else "",
        "notes": reference.notes,
        "storage_count": (storage_counts or {}).get(reference.pk, 0),
        "view_total": getattr(reference, "view_total", 0),
        "click_total": getattr(reference, "click_total", 0),
        "ctr": round(getattr(reference, "click_total", 0) / getattr(reference, "view_total", 0) * 100, 1)
        if getattr(reference, "view_total", 0)
        else 0,
        "created_at": reference.created_at,
        "issued_by": reference.issued_by.email if reference.issued_by else "",
        "edit": _reference_edit_values(reference),
        "allows_pages": plan_allows(reference.plan, "extra_pages") and bool(advert),
        "allows_landing": plan_allows(reference.plan, "landing_page"),
        "allows_subdomain": plan_allows(reference.plan, "subdomain"),
        "needs_landing_warning": plan_allows(reference.plan, "landing_page") and not has_landing,
        "allows_analytics": plan_allows(reference.plan, "analytics"),
        **time_left(reference),
        "advert_choices": [
            {**choice, "allowed": choice["allowed"] or choice["id"] == reference.advert_id}
            for choice in advert_choices
        ],
    }


def _reference_queryset():
    return AdvertReference.objects.select_related(
        "user", "issued_by", "advert__landing_page", "advert__landing_page__author"
    ).annotate(
        view_total=Count("events", filter=Q(events__event_type=AdvertEvent.EVENT_VIEW)),
        click_total=Count("events", filter=Q(events__event_type=AdvertEvent.EVENT_CLICK)),
    )


def _storage_counts_for(reference_ids=None):
    """File counts by reference, without adding another join to the already
    annotated view/click queryset."""
    rows = AdvertReferenceFile.objects.all()
    if reference_ids is not None:
        rows = rows.filter(reference_id__in=reference_ids)
    return dict(rows.values_list("reference_id").annotate(total=Count("id")))


def _advert_reference_rows():
    advert_choices = _advert_choices()
    rows = list(_reference_queryset().order_by("-created_at")[:ADVERT_REFERENCE_LIST_LIMIT])
    counts = _storage_counts_for([row.pk for row in rows])
    return [_advert_reference_row(row, advert_choices, counts) for row in rows]


def _one_reference_row(reference_id):
    row = _reference_queryset().filter(pk=reference_id).first()
    return _advert_reference_row(row, _advert_choices(), _storage_counts_for([reference_id])) if row else None


def _copy_link_to_advert(reference, old_advert=None):
    """The link an advert opens comes only from the Ads desk: the reference's
    public URL is copied onto the advert, and cleared from an advert that was
    unlinked."""
    if old_advert is not None and old_advert.pk != reference.advert_id and old_advert.url:
        old_advert.url = None
        old_advert.save(update_fields=["url"])
    if reference.advert_id:
        advert = reference.advert
        advert.url = reference.public_url or None
        advert.save(update_fields=["url"])


def _card_reply(request, reference_id, text, ok=True):
    """The answer to a button on one reference card.

    From the page (htmx) the answer is the fresh card plus a small message, so
    nothing reloads. Without JavaScript it is the old redirect with a message.
    """
    if request.headers.get("HX-Request") != "true":
        (messages.success if ok else messages.error)(request, text)
        return redirect("control:advert_references")
    row = _one_reference_row(reference_id)
    if row is None:
        response = HttpResponse("")
    else:
        response = render(
            request,
            "ADMIN/partials/advert_reference_card.html",
            {
                "ref": row,
                "plan_choices": AdvertLead.PLAN_CHOICES,
                "ads_base_host": ads_base_host(),
            },
        )
    response["HX-Trigger"] = json.dumps({"adsToast": {"text": text, "ok": ok}})
    return response


def _days_from_post(request):
    try:
        days = int(request.POST.get("days") or ADVERT_REFERENCE_RENEW_DAYS)
    except (TypeError, ValueError):
        days = ADVERT_REFERENCE_RENEW_DAYS
    return max(1, min(days, 365))


def _ads_control_context(form_data=None, form_error=""):
    rows = _advert_reference_rows()
    return {
        "reference_rows": rows,
        "reference_total": AdvertReference.objects.count(),
        "live_reference_total": sum(1 for row in rows if row["is_live"]),
        "view_total": sum(row["view_total"] for row in rows),
        "click_total": sum(row["click_total"] for row in rows),
        "advert_choices": _advert_choices(),
        "plan_choices": AdvertLead.PLAN_CHOICES,
        "ads_base_host": ads_base_host(),
        "advert_leads": AdvertLead.objects.select_related("user").order_by("-created_at")[:12],
        "advert_lead_total": AdvertLead.objects.count(),
        "form_data": form_data or _reference_form_data(defaults=True),
        "form_error": form_error,
    }


"""
------------------------------------------------------------
#   ADVERT REFERENCE STORAGE
------------------------------------------------------------
Each Ads desk reference gets its own private file shelf. It is NOT the public
/archive/ library: no story tokens, no public gallery, no advertiser access.
Only ads staff can open it, upload, delete or hand out a one-hour signed link.
The linked advert picture/HTML is listed as read-only system context.
"""

ADVERT_STORAGE_LINK_SALT = "advert-storage-share"
ADVERT_STORAGE_LINK_AGE = 3600  #   one hour, as requested
_ADVERT_ACTIVE_EXTENSIONS = {"html", "htm", "svg", "js", "mjs", "php", "py", "sh", "bat", "cmd", "exe"}


def _ads_desk_denied(request):
    if ads_staff_only(request.user):
        return None
    if request.headers.get("HX-Request") == "true":
        return JsonResponse({"detail": "Ads access is required."}, status=403)
    return admin_page_redirect(request)


def _ads_file_size_label(num_bytes):
    if not num_bytes:
        return ""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def _advert_storage_kind(filename, content_type):
    name_ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    mime = (content_type or "").lower()
    if mime.startswith("image/") or name_ext in {"png", "jpg", "jpeg", "gif", "webp", "avif", "bmp", "svg"}:
        return "image"
    if mime.startswith("video/") or name_ext in {"mp4", "mov", "webm"}:
        return "video"
    return "file"


def _advert_storage_force_download(filename):
    """Active content is stored, but never rendered on our own domain."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext in _ADVERT_ACTIVE_EXTENSIONS


def _advert_storage_share_urls(row):
    token = signing.TimestampSigner(salt=ADVERT_STORAGE_LINK_SALT).sign(str(row.pk))
    base = reverse("control:advert_storage_share", kwargs={"file_id": row.pk, "token": token})
    return base, f"{base}?download=1"


def _advert_storage_file_rows(reference):
    rows = []
    for item in reference.storage_files.select_related("uploaded_by").order_by("-date_uploaded"):
        preview_url, download_url = _advert_storage_share_urls(item)
        rows.append(
            {
                "id": item.pk,
                "name": item.original_filename,
                "note": item.note,
                "kind": _advert_storage_kind(item.original_filename, item.content_type),
                "secure_url": item.secure_url,
                "size": _ads_file_size_label(item.file_size),
                "uploaded_by": item.uploaded_by.email if item.uploaded_by_id else "",
                "date": timezone.localtime(item.date_uploaded).strftime("%d %b %Y, %H:%M"),
                "preview_url": preview_url,
                "download_url": download_url,
                "force_download": _advert_storage_force_download(item.original_filename),
                "system": False,
            }
        )
    return rows


def _advert_storage_system_rows(reference):
    """Read-only context already owned by the linked advert. These rows are
    never edited or deleted from the storage shelf -- that stays in PANEL and
    the landing-page editor."""
    advert = reference.advert
    if advert is None:
        return []
    rows = []
    if advert.image_url:
        rows.append(
            {
                "name": (advert.heading or "Advert banner") + " (banner)",
                "note": "Linked advert banner",
                "kind": "image",
                "secure_url": advert.image_url,
                "size": "",
                "uploaded_by": "",
                "date": timezone.localtime(advert.date_created).strftime("%d %b %Y, %H:%M"),
                "system": True,
            }
        )
    landing = getattr(advert, "landing_page", None)
    if landing and landing.html_public_id:
        rows.append(
            {
                "name": "Landing page HTML",
                "note": f"{landing.html_bytes or 0} bytes · managed in PANEL",
                "kind": "file",
                "secure_url": "",
                "size": _ads_file_size_label(landing.html_bytes),
                "uploaded_by": landing.author_label,
                "date": timezone.localtime(landing.date_updated).strftime("%d %b %Y, %H:%M"),
                "system": True,
            }
        )
    for page in advert.pages.all():
        if page.html_public_id:
            rows.append(
                {
                    "name": f"/{page.path}/ HTML",
                    "note": "Extra advert page · managed in PANEL",
                    "kind": "file",
                    "secure_url": "",
                    "size": _ads_file_size_label(page.html_bytes),
                    "uploaded_by": "",
                    "date": timezone.localtime(page.date_updated).strftime("%d %b %Y, %H:%M"),
                    "system": True,
                }
            )
    return rows


def _advert_storage_context(reference, error="", notice=""):
    return {
        "ref": {
            "id": reference.pk,
            "reference": reference.reference,
            "business_name": reference.business_name,
        },
        "storage_files": _advert_storage_file_rows(reference),
        "system_files": _advert_storage_system_rows(reference),
        "storage_max_mb": ADVERT_STORAGE_MAX_BYTES // (1024 * 1024),
        "storage_error": error,
        "storage_notice": notice,
    }


def _advert_storage_response(request, reference, error="", notice="", status=200):
    response = render(
        request,
        "ADMIN/partials/advert_reference_storage.html",
        _advert_storage_context(reference, error, notice),
        status=status,
    )
    if notice or error:
        response["HX-Trigger"] = json.dumps({"adsToast": {"text": notice or error, "ok": not bool(error)}})
    return response


class AdvertReferenceStorageModalView(View):
    """htmx GET: the storage drawer for one reference."""

    def get(self, request, reference_id):
        denied = _ads_desk_denied(request)
        if denied:
            return denied
        reference = get_object_or_404(AdvertReference, pk=reference_id)
        return _advert_storage_response(request, reference)


class AdvertReferenceStorageUploadView(View):
    def post(self, request, reference_id):
        denied = _ads_desk_denied(request)
        if denied:
            return denied
        remaining_seconds, limited = is_rate_limited(request, 20, 60, scope="advert-storage")
        if limited:
            return _advert_storage_response(
                request,
                get_object_or_404(AdvertReference, pk=reference_id),
                error=f"Please wait {remaining_seconds} seconds before uploading again.",
                status=429,
            )
        reference = get_object_or_404(AdvertReference, pk=reference_id)
        upload = request.FILES.get("storage_file")
        if upload is None:
            return _advert_storage_response(request, reference, error="Choose a file first.", status=400)
        size = getattr(upload, "size", 0) or 0
        if size > ADVERT_STORAGE_MAX_BYTES:
            return _advert_storage_response(
                request, reference, error=f"Files are limited to {ADVERT_STORAGE_MAX_BYTES // (1024 * 1024)}MB.", status=400
            )
        note = " ".join((request.POST.get("note") or "").split())[:240]
        try:
            uploaded = upload_advert_storage_file(upload)
        except ImageUploadError as exc:
            return _advert_storage_response(request, reference, error=str(exc), status=400)
        try:
            AdvertReferenceFile.objects.create(
                reference=reference,
                uploaded_by=request.user,
                original_filename=(getattr(upload, "name", "") or "file")[:255],
                note=note,
                content_type=(getattr(upload, "content_type", "") or "")[:100],
                resource_type=uploaded["resource_type"],
                public_id=uploaded["public_id"],
                secure_url=uploaded["secure_url"],
                file_size=uploaded["bytes"],
            )
        except Exception:
            destroy_archive_asset(uploaded["public_id"], uploaded["resource_type"])
            raise
        info_logger(msg=f"ADS STORAGE: file added to reference {reference.reference} by {request.user.email}")
        return _advert_storage_response(request, reference, notice="File added to this reference.")


class AdvertReferenceStorageDeleteView(View):
    def post(self, request, reference_id, file_id):
        denied = _ads_desk_denied(request)
        if denied:
            return denied
        reference = get_object_or_404(AdvertReference, pk=reference_id)
        item = get_object_or_404(AdvertReferenceFile, pk=file_id, reference=reference)
        public_id, resource_type = item.public_id, item.resource_type
        item.delete()
        if public_id:
            destroy_archive_asset(public_id, resource_type or "image")
        info_logger(msg=f"ADS STORAGE: file {file_id} removed from reference {reference.reference} by {request.user.email}")
        return _advert_storage_response(request, reference, notice="File deleted.")


def _stream_advert_storage_asset(request, item, force_download):
    """Relay one small (<=5MB) Ads storage file from Cloudinary with a signed
    link. Range is forwarded so video preview can seek."""
    filename = item.original_filename or item.public_id.rsplit("/", 1)[-1] or "download"
    delivery_url, _ = cloudinary.utils.cloudinary_url(
        item.public_id, resource_type=item.resource_type or "image", secure=True
    )
    upstream_headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        upstream_headers["Range"] = range_header
    try:
        upstream = requests.get(delivery_url, headers=upstream_headers, stream=True, timeout=(8, 60))
    except requests.RequestException as exc:
        info_logger(msg=f"ADS STORAGE FETCH FAILED ({item.public_id}): {exc}")
        raise Http404("File not found.")
    if upstream.status_code == 404:
        upstream.close()
        raise Http404("File not found.")
    if upstream.status_code >= 400:
        upstream.close()
        return HttpResponse(status=502)

    def chunks():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    #   Active files must never be rendered as page/script on our domain, so
    #   even a preview link hands them out as an opaque attachment.
    content_type = (
        "application/octet-stream"
        if force_download
        else (item.content_type or upstream.headers.get("Content-Type") or "application/octet-stream")
    )
    response = StreamingHttpResponse(
        chunks(),
        status=206 if upstream.status_code == 206 else 200,
        content_type=content_type,
    )
    for header in ("Content-Length", "Content-Range", "ETag", "Last-Modified"):
        if header in upstream.headers:
            response[header] = upstream.headers[header]
    response["Accept-Ranges"] = upstream.headers.get("Accept-Ranges", "bytes")
    response["Cache-Control"] = "private, no-store"
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    disposition = "attachment" if force_download else "inline"
    response["Content-Disposition"] = f"{disposition}; filename=\"{safe_name}\"; filename*=UTF-8''{quote(filename)}"
    return response


class AdvertReferenceShareView(View):
    """Public one-hour signed link for one Ads storage file. No login needed:
    possession of the token IS the permission. Active file types are forced
    to download even when the link was opened as a preview."""

    def get(self, request, file_id, token):
        try:
            signed_id = signing.TimestampSigner(salt=ADVERT_STORAGE_LINK_SALT).unsign(
                token, max_age=ADVERT_STORAGE_LINK_AGE
            )
        except BadSignature:
            return HttpResponse("This share link has expired or is invalid.", status=403)
        if signed_id != str(file_id):
            return HttpResponse("This share link has expired or is invalid.", status=403)
        item = get_object_or_404(AdvertReferenceFile, pk=file_id)
        force = request.GET.get("download") in {"1", "true", "yes"} or _advert_storage_force_download(
            item.original_filename
        )
        return _stream_advert_storage_asset(request, item, force)


class AdvertReferenceDeleteView(View):
    """Delete one reference from the Ads desk. Storage files always go; the
    linked advert picture/HTML only go when the confirm box is ticked."""

    def get(self, request, reference_id):
        denied = _ads_desk_denied(request)
        if denied:
            return denied
        reference = get_object_or_404(AdvertReference, pk=reference_id)
        return render(
            request,
            "ADMIN/partials/advert_reference_delete.html",
            {
                "ref": {
                    "id": reference.pk,
                    "reference": reference.reference,
                    "business_name": reference.business_name,
                    "storage_count": reference.storage_files.count(),
                    "has_advert": bool(reference.advert_id),
                }
            },
        )

    def post(self, request, reference_id):
        denied = _ads_desk_denied(request)
        if denied:
            return denied
        remaining_seconds, limited = is_rate_limited(request, 10, 60, scope="advert-reference-delete")
        if limited:
            return JsonResponse({"detail": f"Please wait {remaining_seconds} seconds before deleting again."}, status=429)
        reference = get_object_or_404(AdvertReference, pk=reference_id)
        reference_code = reference.reference
        advert = reference.advert
        delete_assets = (
            (request.POST.get("delete_advert_assets") or "").lower() in {"1", "true", "on", "yes"}
            and advert is not None
        )
        html_public_ids = []
        if delete_assets:
            #   The landing page row's post_delete signal already removes its
            #   Cloudinary HTML when advert.delete() cascades below. Extra
            #   pages have no such signal, so their assets are collected here.
            html_public_ids = list(
                AdvertPage.objects.filter(advert=advert)
                .exclude(html_public_id="")
                .values_list("html_public_id", flat=True)
            )
        advert_image_public_id = advert.image_public_id if delete_assets else ""
        reference.delete()  #   pre_delete signal removes storage files/assets
        if delete_assets:
            #   Ticking the box destroys the campaign itself, not just the
            #   assignment. Deleting the AdvertImage row cascades its landing
            #   and extra-page rows; the Cloudinary objects go below.
            advert.delete()
        if advert_image_public_id:
            destroy_archive_asset(advert_image_public_id)
        for public_id in html_public_ids:
            destroy_advert_landing_html(public_id)
        info_logger(
            msg=(
                f"ADS DESK: reference {reference_code} deleted by {request.user.email}; "
                f"advert assets removed={delete_assets}"
            )
        )
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("")
            response["HX-Redirect"] = reverse("control:advert_references")
            return response
        messages.success(request, f"Reference {reference_code} was deleted.")
        return redirect("control:advert_references")


class AdvertReferencesView(View):
    """The ads desk: issue references and see their lifecycle at a glance."""

    def get(self, request):
        if not ads_staff_only(request.user):
            return admin_page_redirect(request)
        return render(request, "ADMIN/advert_references.html", _ads_control_context())

    def post(self, request):
        if not ads_staff_only(request.user):
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"detail": "Ads access is required."}, status=403)
            return admin_page_redirect(request)

        remaining_seconds, limited = is_rate_limited(
            request, 60, 10, scope="advert-reference-issue"
        )
        if limited:
            return render(
                request,
                "ADMIN/advert_references.html",
                _ads_control_context(
                    form_data=_reference_form_data(request.POST),
                    form_error=f"Wait {remaining_seconds} seconds before issuing another reference.",
                ),
                status=429,
            )

        form, values, error = _clean_reference_form(request.POST)
        if error:
            return render(
                request,
                "ADMIN/advert_references.html",
                _ads_control_context(form_data=form, form_error=error),
                status=400,
            )

        reference = AdvertReference.objects.create(
            user=values["account"],
            plan=values["plan"],
            business_name=values["business_name"],
            starts_at=values["starts_at"],
            expires_at=values["expires_at"],
            public_url=values["public_url"],
            subdomain=values["subdomain"],
            advert=values["advert"],
            notes=values["notes"],
            issued_by=request.user,
        )
        _copy_link_to_advert(reference)
        if not values["account"].is_advertiser:
            values["account"].is_advertiser = True
            values["account"].save(update_fields=["is_advertiser"])
        info_logger(
            msg=(
                f"ADS DESK: reference {reference.reference} issued to "
                f"{values['account'].email} by {request.user.email}"
            )
        )
        messages.success(
            request,
            f"Reference {reference.reference} issued to {values['account'].email}.",
        )
        return redirect("control:advert_references")


class AdvertReferenceStatusView(View):
    """Pause, resume or end one reference. This is the commercial switch: a
    paused reference stops the home rail and tracked clicks immediately."""

    ACTIONS = {
        "pause": AdvertReference.STATUS_PAUSED,
        "resume": AdvertReference.STATUS_ACTIVE,
        "activate": AdvertReference.STATUS_ACTIVE,
        "expire": AdvertReference.STATUS_EXPIRED,
    }

    def post(self, request, reference_id):
        if not ads_staff_only(request.user):
            return admin_page_redirect(request)
        row = AdvertReference.objects.filter(pk=reference_id).first()
        if row is None:
            return _card_reply(request, reference_id, "That advert reference no longer exists.", ok=False)

        action = (request.POST.get("action") or "").strip().lower()
        status = self.ACTIONS.get(action)
        if status is None:
            return _card_reply(request, reference_id, "Unknown reference action.", ok=False)

        row.status = status
        row.save(update_fields=["status", "updated_at"])
        info_logger(msg=f"ADS DESK: reference {row.reference} set to {status} by {request.user.email}")
        return _card_reply(request, reference_id, f"{row.reference} is now {row.get_status_display().lower()}.")


class AdvertReferenceRenewView(View):
    """Add days to the paid period. Expired rows restart from now; live rows
    extend from their current end date."""

    def post(self, request, reference_id):
        if not ads_staff_only(request.user):
            return admin_page_redirect(request)
        row = AdvertReference.objects.filter(pk=reference_id).first()
        if row is None:
            return _card_reply(request, reference_id, "That advert reference no longer exists.", ok=False)

        days = _days_from_post(request)
        now = timezone.now()
        base = row.expires_at if row.expires_at and row.expires_at > now else now
        row.expires_at = base + timedelta(days=days)
        #   Renewing pays for more time; it must not silently lift a pause.
        update_fields = ["expires_at", "updated_at"]
        if row.status != AdvertReference.STATUS_PAUSED:
            row.status = AdvertReference.STATUS_ACTIVE
            update_fields.append("status")
        row.save(update_fields=update_fields)
        info_logger(msg=f"ADS DESK: reference {row.reference} renewed {days} day(s) by {request.user.email}")
        return _card_reply(request, reference_id, f"{row.reference} renewed for {days} day(s).")


class AdvertReferenceShortenView(View):
    """Take days off the current end date (for a mistaken renewal). It never
    moves the end into the past: use End reference for that."""

    def post(self, request, reference_id):
        if not ads_staff_only(request.user):
            return admin_page_redirect(request)
        row = AdvertReference.objects.filter(pk=reference_id).first()
        if row is None:
            return _card_reply(request, reference_id, "That advert reference no longer exists.", ok=False)
        if not row.expires_at:
            return _card_reply(request, reference_id, "This reference has no end date to shorten.", ok=False)

        days = _days_from_post(request)
        new_end = row.expires_at - timedelta(days=days)
        if new_end <= timezone.now():
            return _card_reply(
                request, reference_id,
                "That would put the end date in the past. Use End reference instead.", ok=False,
            )
        if row.starts_at and new_end <= row.starts_at:
            return _card_reply(request, reference_id, "That would end the reference before it starts.", ok=False)

        row.expires_at = new_end
        row.save(update_fields=["expires_at", "updated_at"])
        info_logger(msg=f"ADS DESK: reference {row.reference} shortened {days} day(s) by {request.user.email}")
        return _card_reply(request, reference_id, f"Removed {days} day(s) from {row.reference}.")


class AdvertReferenceUpdateView(View):
    """Edit the advert a reference points at, its plan, dates, URL or notes."""

    def post(self, request, reference_id):
        if not ads_staff_only(request.user):
            return admin_page_redirect(request)
        row = (
            AdvertReference.objects.select_related("user", "advert")
            .filter(pk=reference_id)
            .first()
        )
        if row is None:
            messages.error(request, "That advert reference no longer exists.")
            return redirect("control:advert_references")

        form, values, error = _clean_reference_update_form(request.POST, row)
        if error:
            context = _ads_control_context()
            for reference_row in context["reference_rows"]:
                if reference_row["id"] == row.pk:
                    reference_row["edit"] = form
                    break
            context.update({"edit_error": error, "edit_error_id": row.pk})
            return render(request, "ADMIN/advert_references.html", context, status=400)

        old_advert = row.advert
        for field in (
            "plan",
            "business_name",
            "starts_at",
            "expires_at",
            "public_url",
            "subdomain",
            "advert",
            "notes",
        ):
            setattr(row, field, values[field])
        row.save()
        _copy_link_to_advert(row, old_advert)
        info_logger(
            msg=f"ADS DESK: reference {row.reference} updated by {request.user.email}"
        )
        messages.success(request, f"{row.reference} updated.")
        return redirect("control:advert_references")


class StaffAdsAccessToggleView(_SuperuserWriteView):
    """Give one staff account the limited ads-desk flag, or take it away.

    This is deliberately separate from ``is_admin``: ads staff can issue and
    renew references but cannot open the staff directory, site settings or the
    rest of PANEL.
    """

    def post(self, request, staff_id):
        remaining_seconds, limited = is_rate_limited(request, 10, 20)
        if limited:
            return JsonResponse(
                {"detail": f"Permission Denied, Wait {remaining_seconds} seconds"},
                status=403,
            )
        resolved, error = self._guard(request, staff_id)
        if error:
            return error
        account, _profile = resolved

        new_state = not account.is_ads_staff
        account.is_ads_staff = new_state
        account.save(update_fields=["is_ads_staff"])
        info_logger(
            msg=(
                f"ADS ACCESS: {account.email} set to "
                f"{'ads staff' if new_state else 'no ads access'} by {request.user.email}"
            )
        )
        return JsonResponse(
            {
                "detail": "Ads desk access granted." if new_state else "Ads desk access removed.",
                "is_ads_staff": new_state,
            },
            status=200,
        )


#   EXTRA PAGES (ADVANCE PLAN) --------------------------------------------
#   Pages are HTML code, so only active admins can write them (the same rule
#   as the landing page). Ads staff manage the rest of the desk but not this.
PAGE_PATH_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")


def _page_public_url(request, reference, page):
    path = page.path
    if reference.public_host:
        return f"{request.scheme}://{reference.public_host}/{path}/"
    return reverse("partner:advert_page", kwargs={"slug": slugify(page.advert.heading or "") or "advert", "pk": page.advert_id, "path": path})


def _pages_context(request, reference, form=None, error=""):
    pages = list(AdvertPage.objects.filter(advert=reference.advert))
    return {
        "reference": reference,
        "pages": [
            {"page": page, "url": _page_public_url(request, reference, page), "live": page.is_deliverable}
            for page in pages
        ],
        "form": form or {"path": "", "html": "", "is_published": True},
        "error": error,
    }


def _pages_reference(request, reference_id):
    """The reference whose pages are edited, or a redirect to say why not."""
    if not admin_only(request.user) or not request.user.is_active:
        return None, admin_page_redirect(request)
    reference = AdvertReference.objects.select_related("advert__landing_page").filter(pk=reference_id).first()
    if reference is None or reference.advert is None:
        messages.error(request, "Link an advert to this reference before adding pages.")
        return None, redirect("control:advert_references")
    if not plan_allows(reference.plan, "extra_pages"):
        messages.error(request, plan_message(reference.plan, "extra_pages"))
        return None, redirect("control:advert_references")
    return reference, None


class AdvertPagesView(View):
    """List, add, edit and remove the extra pages of one Advance advert."""

    def get(self, request, reference_id):
        reference, denied = _pages_reference(request, reference_id)
        if denied:
            return denied
        form = None
        edit_path = (request.GET.get("edit") or "").strip()
        page = AdvertPage.objects.filter(advert=reference.advert, path=edit_path).first() if edit_path else None
        if page:
            try:
                html = strip_advert_landing_author_header(fetch_advert_landing_html(page.html_public_id))
            except ImageUploadError:
                html = ""
            form = {"path": page.path, "html": html, "is_published": page.is_published}
        return render(request, "ADMIN/advert_pages.html", _pages_context(request, reference, form))

    def post(self, request, reference_id):
        reference, denied = _pages_reference(request, reference_id)
        if denied:
            return denied
        path = (request.POST.get("path") or "").strip().strip("/").lower()
        html = strip_advert_landing_author_header((request.POST.get("html") or "").strip())
        form = {"path": path, "html": html, "is_published": request.POST.get("is_published") == "1"}

        error = ""
        if not path or len(path) > 80 or not PAGE_PATH_RE.match(path):
            error = "Use lowercase letters, numbers and hyphens, like about or about/team."
        elif not html:
            error = "Paste the page HTML first."
        elif len(html.encode("utf-8")) > ADVERT_LANDING_MAX_BYTES:
            error = f"The page is too large. The limit is {ADVERT_LANDING_MAX_BYTES // (1024 * 1024)}MB."
        if error:
            return render(request, "ADMIN/advert_pages.html", _pages_context(request, reference, form, error), status=400)

        try:
            uploaded = upload_advert_landing_html(
                add_advert_landing_author_header(html, reference.advert, request.user),
                reference.advert.pk,
                page_path=path,
            )
        except ImageUploadError as exc:
            return render(request, "ADMIN/advert_pages.html", _pages_context(request, reference, form, str(exc)), status=400)

        AdvertPage.objects.update_or_create(
            advert=reference.advert,
            path=path,
            defaults={
                "html_public_id": uploaded["public_id"],
                "html_bytes": uploaded["bytes"],
                "is_published": form["is_published"],
                "author": request.user,
            },
        )
        info_logger(msg=f"ADS DESK: page /{path}/ of reference {reference.reference} saved by {request.user.email}")
        messages.success(request, f"Page /{path}/ saved.")
        return redirect("control:advert_pages", reference_id=reference.pk)


class AdvertPageDeleteView(View):
    def post(self, request, reference_id):
        reference, denied = _pages_reference(request, reference_id)
        if denied:
            return denied
        page = AdvertPage.objects.filter(advert=reference.advert, path=(request.POST.get("path") or "")).first()
        if page is None:
            messages.error(request, "That page no longer exists.")
        else:
            destroy_advert_landing_html(page.html_public_id)
            page.delete()
            info_logger(msg=f"ADS DESK: page /{page.path}/ of reference {reference.reference} removed by {request.user.email}")
            messages.success(request, f"Page /{page.path}/ removed.")
        return redirect("control:advert_pages", reference_id=reference.pk)
