"""Admin authority views.

Everything that needs more than plain staff access lives here. Staff level
work stays in HOME.views; this module only holds the extra authority an admin
(or superuser) carries over the rest of the staff.
"""

import logging

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from AUTHENTICATION.models import Auth
from BLOG.models import Blog
from HOME.views import _resolve_page_number
from SERVICE_INTERNAL.abstract import info_logger, is_rate_limited
from SERVICE_INTERNAL.config import StaffConfig
from SERVICE_INTERNAL.email_single import _base_email
from SERVICE_INTERNAL.permissions import admin_only
from SERVICE_INTERNAL.sessions import drop_sessions_for
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
            "url": reverse("blog:story_detail", args=[blog.id]),
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
            "TODO:WRITE UP THE HTML_MESSAGE WELCOMING CREATED STAFF AND ATTACHING THEIT DEFAULT PASSWORD UNFORMING THEM AN ACCOUNT HAVE BEEN CREATED FOR THEM"
            _base_email(request.user.email, account.email)
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
