"""Admin authority views.

Everything that needs more than plain staff access lives here. Staff level
work stays in HOME.views; this module only holds the extra authority an admin
(or superuser) carries over the rest of the staff.
"""

import logging

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import title as title_case
from django.urls import reverse
from django.utils import timezone
from django.views import View

from AUTHENTICATION.models import Auth, UserSession
from BLOG.models import Blog, Category
from HOME.views import _resolve_page_number
from SERVICE_INTERNAL.abstract import info_logger, is_rate_limited
from SERVICE_INTERNAL.config import StaffConfig
from SERVICE_INTERNAL.email_batch import _try_send_panel_mass_email
from SERVICE_INTERNAL.email_single import _try_send_staff_welcome_email
from SERVICE_INTERNAL.permissions import admin_only
from SERVICE_INTERNAL.sessions import drop_sessions_for
from ADMIN.models import SiteSettings
from STAFF.models import GENDER_CHOICES, StaffProfile

logger = logging.getLogger(__name__)

STAFF_PAGE_SIZE = 5  #   COPIES THE BOOKMARK / READING HISTORY PANELS


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
            return redirect("home:profile")

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

        return render(
            request,
            "ADMIN/staff_detail.html",
            {
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
            return redirect("home:profile")

        return self._render(request)

    def post(self, request):
        remaining_seconds, limited = is_rate_limited(request, 30, 3)
        if limited:
            return self._fail(request, f"Permission Denied, Wait {remaining_seconds} seconds")
        if not admin_only(request.user):
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"detail": "Admin access is required."}, status=403)
            return redirect("home:profile")

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
        info_logger(msg=f"STAFF CREATED: {account.email} (grant_admin={grant_admin}) by {request.user.email} with password set as : {password}")

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
            return redirect("home:profile")

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
                "gallery_items": staff_directory_rows(list(gallery_page.object_list)),
                "gallery_has_next": gallery_page.has_next(),
                "gallery_next_page": gallery_page.next_page_number() if gallery_page.has_next() else None,
                "sessions_rows": sessions_rows,
                "sessions_total_people": sessions_total_people,
                "sessions_page_obj": sessions_page,
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


def _active_sessions_page(page_number):
    """One row per account that currently holds at least one live session,
    not one row per session -- the logout button on that row drops every
    session the account has, matching how drop_sessions_for already works."""
    account_ids = list(
        UserSession.objects.order_by().values_list("user_id", flat=True).distinct()
    )
    accounts = list(Auth.objects.filter(pk__in=account_ids).order_by("-date_joined"))

    paginator = Paginator(accounts, SESSIONS_PAGE_SIZE)
    if page_number > paginator.num_pages and paginator.num_pages:
        raise Http404("Page not found.")
    page = paginator.get_page(page_number)

    session_counts = {}
    latest_logins = {}
    for account in page.object_list:
        account_sessions = UserSession.objects.filter(user=account).order_by("-logged_in_at")
        session_counts[account.pk] = account_sessions.count()
        latest_session = account_sessions.first()
        latest_logins[account.pk] = latest_session.logged_in_at if latest_session else None

    rows = [
        {
            "id": account.pk,
            "email_masked": _mask_email(account.email),
            "session_count": session_counts.get(account.pk, 0),
            #   MOST RECENT LOGIN AMONG THIS ACCOUNT'S ACTIVE SESSIONS, SHOWN ON
            #   THE PANEL SO AN ADMIN CAN SEE WHEN SOMEONE ACTUALLY SIGNED IN.
            "logged_in_at": (
                timezone.localtime(latest_logins[account.pk]).strftime("%b %d, %Y \u00b7 %I:%M %p")
                if latest_logins.get(account.pk) else ""
            ),
        }
        for account in page.object_list
    ]
    return paginator, page, rows, len(accounts)


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
