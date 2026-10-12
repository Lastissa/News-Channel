from django.contrib import messages
from django.forms.models import model_to_dict
from django.http import JsonResponse
from django.views import View
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.conf import settings
from django.db import transaction

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