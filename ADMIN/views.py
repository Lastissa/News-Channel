"""Admin authority views.

Everything that needs more than plain staff access lives here. Staff level
work stays in HOME.views; this module only holds the extra authority an admin
(or superuser) carries over the rest of the staff.
"""

import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import title as title_case
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views import View

from AUTHENTICATION.models import Auth, UserSession
from BLOG.models import Blog, Category
from HOME.views import _resolve_page_number
from SERVICE_INTERNAL.abstract import info_logger, is_rate_limited
from SERVICE_INTERNAL.config import StaffConfig
from SERVICE_INTERNAL.email_batch import _try_send_panel_mass_email, _try_send_staff_created_batch_email
from SERVICE_INTERNAL.email_single import _try_send_staff_direct_email, _try_send_staff_welcome_email
from SERVICE_INTERNAL.images import ImageUploadError, destroy_archive_asset, upload_advert_image
from SERVICE_INTERNAL.permissions import admin_only
from SERVICE_INTERNAL.passwords import first_password_error
from SERVICE_INTERNAL.sessions import (
    describe_device,
    drop_sessions_for,
    drop_single_session,
    is_admin_inactive_too_long,
    is_session_expired,
    live_sessions_for,
)
from Partner.models import AdvertImage, Announcement
from ADMIN.models import SiteSettings
from ADMIN.analytics import (
    DEFAULT_STORY_PERFORMANCE_SERIES,
    DEFAULT_STORY_PERIOD,
    DEFAULT_TREND_BUCKET,
    DEFAULT_TREND_RANGE,
    MEMBER_ACTIVITY_CHOICES,
    MEMBER_CATEGORY_ANY,
    MEMBER_KIND_CHOICES,
    MEMBER_NEWSLETTER_CHOICES,
    MEMBER_STATE_CHOICES,
    SERIES_META,
    STORY_KPI_RANGE_CHOICES,
    STORY_KPI_RANGES,
    STORY_PERFORMANCE_SERIES,
    STORY_PERIODS,
    STORY_PERIOD_CHOICES,
    TREND_BUCKET_CHOICES,
    TREND_RANGE_CHOICES,
    TREND_RANGES,
    member_category_filter_choices,
    member_directory_queryset,
    member_new_today,
    member_overview,
    member_page_details,
    members_growth,
    reading_editorial,
    stories_overview,
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


def _staff_account_or_404(staff_id):
    account = Auth.objects.filter(pk=staff_id).first()
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
    paginator = Paginator(Blog.objects.filter(author=account).order_by("-date_created"), STAFF_PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    return paginator, paginator.get_page(page_number)


class StaffDetailView(View):
    """Full page staff record.

    Privacy: reading history, bookmarks, the profile image URL and the
    newsletter preference are deliberately absent. Those belong to the staff
    member and no admin overrides them from here.

    Authority: every admin reading this page can write the controls on it,
    the superuser no longer outranks an admin here. Nothing on this page
    deletes an account.
    """

    def get(self, request, staff_id):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        account = _staff_account_or_404(staff_id)
        profile = StaffProfile.objects.filter(auth=account).first()

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
            },
        )


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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 30, 3)
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
            account = Auth.objects.create_staff(email=email, password=password, is_admin=grant_admin)
            StaffProfile.objects.create(auth=account, gender=gender, full_name=full_name, role=role)
            
        _try_send_staff_welcome_email(account, password, full_name)
        role_label = dict(StaffConfig.role_choices()).get(role, role)
        _try_send_staff_created_batch_email(account, full_name, role_label, request.user.email)
        info_logger(msg=f"STAFF CREATED: {account.email} (grant_admin={grant_admin}) by {request.user.email}")

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

        gallery_paginator = Paginator(staff_directory_queryset(), GALLERY_PAGE_SIZE)
        gallery_page = gallery_paginator.get_page(1)

        sessions_paginator, sessions_page, sessions_rows, sessions_total_people = _active_sessions_page(1)

        return render(
            request,
            "ADMIN/panel.html",
            {
                "is_superuser": bool(request.user.is_superuser),
                "sender_full_name": own_profile.full_name.strip() if own_profile and own_profile.full_name else "",
                "site_settings": SiteSettings.get_solo(),
                "category_rows": _category_rows(),
                "announcement_items": _announcement_items(),
                "image_advert_items": _image_advert_items(),
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
                "default_trend_range": DEFAULT_TREND_RANGE,
                "series_meta": SERIES_META,
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

    The four checkboxes in the shell decide which series are drawn. On the
    very first (load) request the browser sends no `submitted` marker, so all
    four series are shown by default; once the form has fired, the ticked set
    is honoured exactly -- including the case where every box is cleared,
    which draws an empty chart rather than silently re-adding them all.
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
            series_keys = {meta["key"] for meta in SERIES_META}

        return render(
            request,
            "ADMIN/partials/analytics_trends.html",
            {"chart": trends(bucket, selected_range, series_keys, start_iso, end_iso)},
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


class StaffLyticsView(View):
    """Placeholder for the staff chamber of analytics (not built yet)."""

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return render(
            request,
            "ADMIN/analytics_placeholder.html",
            {"heading": "Staff lytics", "message": "Staff analytics is not built yet. It will cover story production and authors.", "active_chamber": "staff"},
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


class AuthorLyticsView(View):
    """Placeholder for the author chamber of analytics (not built yet)."""

    def get(self, request):
        if not admin_only(request.user):
            return admin_page_redirect(request)

        return render(
            request,
            "ADMIN/analytics_placeholder.html",
            {"heading": "Author lytics", "message": "Author analytics is not built yet. It will cover authors and their production.", "active_chamber": "author"},
        )


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
                "default_trend_range": DEFAULT_TREND_RANGE,
                #   Only the two series that belong to stories: how much is
                #   published and how often stories are opened. The Trends
                #   endpoint draws exactly what the legend has ticked.
                "series_meta": [meta for meta in SERIES_META if meta["key"] in {"stories", "views"}],
                "story_kpi_ranges": STORY_KPI_RANGE_CHOICES,
                "story_performance_series": STORY_PERFORMANCE_SERIES,
                "default_story_performance_series": DEFAULT_STORY_PERFORMANCE_SERIES,
                "active_chamber": "story",
            },
        )


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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        settings_row.save()

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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
        remaining_seconds, limited = is_rate_limited(request, 10, 3)
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
    remaining_seconds, limited = is_rate_limited(request, 10, 6)
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


def _image_advert_item(row):
    expiry = timezone.localtime(row.expiry_date)
    if not row.is_active:
        status = "paused"
    elif row.expiry_date < timezone.now():
        status = "expired"
    else:
        status = "live"
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
    }


def _image_advert_items():
    rows = AdvertImage.objects.select_related("author").order_by("-date_created")[:IMAGE_ADVERT_LIST_LIMIT]
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

    url = (post.get("url") or "").strip()
    if not url:
        return None, "Add the link this advert should open."
    if not url.lower().startswith(("http://", "https://")):
        return None, "The link must start with http:// or https://"
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError:
        return None, "Enter a valid link."

    expiry = parse_datetime((post.get("expiry_date") or "").strip())
    if expiry is None:
        return None, "Pick when this advert should stop showing."
    if timezone.is_naive(expiry):
        expiry = timezone.make_aware(expiry, timezone.get_current_timezone())

    is_active = (post.get("is_active") or "").lower() in ("1", "true", "on", "yes")
    return {"heading": heading, "body": body, "url": url or None, "expiry_date": expiry, "is_active": is_active}, None


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
