from django.contrib import messages
from django.forms.models import model_to_dict
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

import hashlib
import json
import logging, hmac

logger = logging.getLogger(__name__)





class CreateSYAcc(View):    
    def get(self, request, email = None, password = None, sy_secret_incoming = None):
        key= f'admin-create:{email}'.upper()
        limit=cache.get(key)    #   Increase exponentially 1,2,4,8,etc
        superuser_logger(msg=f"Current rate limited status of email '{email}' is {limit}")
        if limit:
            if limit >=60: new_lim = 60
            else:new_lim= limit*2
            cache.set(key, new_lim, timeout=new_lim)
            return JsonResponse({'message': f'try again in the next {new_lim} seconds, try before time end increase ban time'}, status=400)
        cache.set(key, 1, timeout=1)        #Made this indpendedt so below code after theif not can use it
        _ = getattr(settings, "SY_SECRET", None)
        if not _: return JsonResponse({'message': 'Tampered Project'})
        data = {
            'email': email,
            'password':password,
        }
        superuser_logger(msg=f"ATTEMPT BACKDOOR BREACH: {request.META['REMOTE_ADDR']} and x-forwared is ({request.META.get('HTTP_X_FORWARDED_FOR', None)}) attempted a breach on the system with data as ({data})")
        if not hmac.compare_digest(sy_secret_incoming, _):
            superuser_logger("BREACH OUTCOME: breach failed as sy secret not match")
            return JsonResponse({'message': 'ERROR; missing params, your action have been Noted, avoid spam as you will be restricted'})
        try:
            superuser_logger("BREACH OUTCOME: breach successful!")
            with transaction.atomic():
                istance = get_user_model().objects.create_superuser(**data)
                istance.full_clean()
                istance.save()
                superuser_logger("Account Creation success, attacker inside the project")
                return JsonResponse(model_to_dict(istance, exclude=['password', 'id']))
        except Exception as e:
            superuser_logger("Account Creation failed")
            return JsonResponse({'detail': str(e)})
            
    
    
def superuser_logger(msg, debug = getattr(settings, 'DEBUG', False)):
    """LOGGER BUT FOR BACKDOOR ONLY SO ITS MOBILE AND EASILY MOVABLE ACROSS PROJECTS"""
    logger.error(msg=msg)
    if debug:print(msg)
    else:logger.info(msg=msg)
    send_alert(msg)
    
    
def send_alert(msg):
    #Only for this SUPERUSER USAGE TO NOTIFY OF POTENTIAL BREACH
    """Email every active superuser that the backdoor guard just recorded an
    event. Called from superuser_logger() on every invocation, so a breach is
    reported to the people who can act on it even if nobody is watching the
    server console. Runs on the shared background email pool, so the request
    that tripped the guard never waits on the mail provider."""
    recipients = list(
        get_user_model().objects.filter(is_superuser=True, is_active=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return

    from django.utils.html import escape
    from SERVICE_INTERNAL.config import About
    from SERVICE_INTERNAL.email_single import _build_email_html, _dispatch_email

    subject = f"Security alert: potential breach on {About.project_name}"
    main_content = (
        "<p>The backdoor guard recorded the following event:</p>"
        f"<p><code>{escape(msg)}</code></p>"
        "<p>If you did not trigger this, treat it as a potential breach and review "
        "the server logs immediately.</p>"
    )
    html_message = _build_email_html(
        title="Potential breach detected",
        main_content=main_content,
        end_note=f"{About.project_name} security",
        unsubscribe_query="",
    )
    for email in recipients:
        _dispatch_email(email, subject, html_message)


def _iter_csp_reports(payload):
    """Yield one report body from either CSP payload shape.

    Browsers send the legacy ``application/csp-report`` object
    (``{"csp-report": {...}}``) or the Reporting API array
    (``[{"type": "csp-violation", "body": {...}}]``).
    """
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        yield payload["csp-report"]
        return
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("type") not in (None, "csp-violation"):
                continue
            body = item.get("body", item)
            if isinstance(body, dict):
                yield body
        return
    if isinstance(payload, dict):
        yield payload


def _csp_report_value(report, *names):
    for name in names:
        value = report.get(name)
        if value is not None:
            return str(value)[:1000]
    return ""


def _normalize_csp_report(report):
    return {
        "document_uri": _csp_report_value(report, "document-uri", "documentURL"),
        "violated_directive": _csp_report_value(
            report, "violated-directive", "effectiveDirective", "effective-directive"
        ),
        "blocked_uri": _csp_report_value(report, "blocked-uri", "blockedURL"),
        "source_file": _csp_report_value(report, "source-file", "sourceFile"),
        "line_number": _csp_report_value(report, "line-number", "lineNumber"),
        "column_number": _csp_report_value(report, "column-number", "columnNumber"),
        "script_sample": _csp_report_value(report, "script-sample", "sample"),
        "disposition": _csp_report_value(report, "disposition"),
        "status_code": _csp_report_value(report, "status-code", "statusCode"),
    }


@method_decorator(csrf_exempt, name="dispatch")
class CSPReportView(View):
    """Receives browser CSP reports and emails new violations.

    The endpoint is deliberately public and CSRF-exempt: browsers post these
    reports without a cookie or a form token. Reports are deduplicated for a
    few hours and capped per hour so one broken page cannot flood the inbox.
    """

    http_method_names = ["post"]

    def post(self, request):
        max_bytes = int(getattr(settings, "CSP_REPORT_MAX_BYTES", 16 * 1024))
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            content_length = 0
        if content_length > max_bytes:
            return HttpResponse(status=413)

        body = request.body
        if len(body) > max_bytes:
            return HttpResponse(status=413)

        try:
            payload = json.loads(body.decode("utf-8", errors="replace"))
        except (TypeError, ValueError):
            logger.warning("CSP report rejected: invalid JSON")
            return HttpResponse(status=400)

        reports = [
            _normalize_csp_report(report)
            for report in _iter_csp_reports(payload)
            if isinstance(report, dict)
        ]
        if not reports:
            return HttpResponse(status=204)

        dedupe_seconds = int(getattr(settings, "CSP_REPORT_DEDUPE_SECONDS", 6 * 60 * 60))
        max_emails = int(getattr(settings, "CSP_REPORT_MAX_EMAILS_PER_HOUR", 20))
        hour_key = f"csp-report-emails:{timezone.now():%Y%m%d%H}"
        email_count = int(cache.get(hour_key, 0) or 0)

        from SERVICE_INTERNAL.email_single import _try_send_csp_report_email

        for report in reports:
            digest = hashlib.sha256(
                json.dumps(report, sort_keys=True).encode("utf-8")
            ).hexdigest()
            logger.warning(
                "CSP violation: %s blocked by %s on %s",
                report["blocked_uri"] or "(unknown)",
                report["violated_directive"] or "(unknown)",
                report["document_uri"] or "(unknown)",
            )
            if not cache.add(f"csp-report-seen:{digest}", 1, timeout=dedupe_seconds):
                continue
            if email_count >= max_emails:
                logger.warning("CSP report email skipped: hourly limit reached")
                continue
            email_count += 1
            cache.set(hour_key, email_count, timeout=60 * 60)
            _try_send_csp_report_email(report)

        return HttpResponse(status=204)