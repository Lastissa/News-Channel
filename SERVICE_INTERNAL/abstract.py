"===================================================================="
"""NOT USING ANY INTERFACE, JUST HERE TO AVOID CODE REPETITION"""
"===================================================================="


import time

from django.core.cache import cache, caches
from rest_framework.response import Response
from django.http import JsonResponse
from django.db import connection
import logging

logger = logging.getLogger(__name__)

from django.conf import settings
debug_base = getattr(settings, "DEBUG", False)
def get_client_ip(request)-> str:
    """Return the client IP using X-Forwarded-For when available."""
    if request is None:
        return "unknown"


    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or request.META.get("REMOTE_ADDR", "unknown")

    return request.META.get("REMOTE_ADDR", "unknown")


#   USER-AGENT SUBSTRINGS (already lowercased) THAT MARK A REQUEST AS A BOT:
#   search engine/SEO crawlers, link-preview/unfurl bots (Slack, Discord,
#   WhatsApp, Telegram, social share cards), and the common scripted-request
#   libraries a real browser never sends. Not exhaustive -- a bot can always
#   fake its User-Agent -- but it catches every well behaved crawler plus
#   anything using a scraping/HTTP-client default UA. Extend this set rather
#   than replacing it with a stricter/looser check.
BOT_USER_AGENT_MARKERS = (
    "bot", "crawl", "spider", "slurp", "mediapartners", "facebookexternalhit",
    "whatsapp", "telegrambot", "discordbot", "slackbot", "skypeuripreview",
    "curl/", "wget/", "python-requests", "python-urllib", "scrapy", "axios/",
    "headlesschrome", "phantomjs", "ahrefsbot", "semrushbot", "mj12bot",
    "dotbot", "petalbot", "bingpreview", "yandex", "duckduckbot", "applebot",
    "linkedinbot", "pinterest", "embedly", "quora link preview", "outbrain",
    "vkshare", "w3c_validator", "google-inspectiontool", "postmanruntime",
    "go-http-client", "java/", "libwww-perl", "okhttp",
)


def is_bot_request(request) -> bool:
    """Best-effort bot/crawler detection off the User-Agent header alone.
    Used to gate a "+1" style counter (see BLOG.views.StoryDetailView.get,
    the `views` counter on Blog) so a search crawler or a link-preview
    fetch never gets counted as a real reader. A missing/empty User-Agent
    is treated as a bot too -- a real browser always sends one, so its
    absence is itself the strongest signal here. This is NOT a security
    control (a bot can always lie in its User-Agent); it is only meant to
    keep the counter honest against well behaved crawlers and the default
    UAs of common HTTP libraries."""
    if request is None:
        return True

    user_agent = (request.META.get("HTTP_USER_AGENT") or "").strip().lower()
    if not user_agent:
        return True

    return any(marker in user_agent for marker in BOT_USER_AGENT_MARKERS)


def is_rate_limited(request, timeout_window=60, max_requests=10, reset_timeout = False):
    """
    ### Rate limit the user after the max request so if max is 4 , the 4th getd blocked
    RETURN remaining_time, bool = True => bloc am , false ; leave am
    """
    if request is None:
        return None, False
    
    #   kwy for the cache
    key = get_client_ip(request)
    
    #   Value of the cache
    value = cache.get(key) or []
    
    current_request_lenght = len(value)
    
    #   add new time so i can access the value lenght
    value.append(time.time())
    
    
    if reset_timeout:
        cache.set(key, value, timeout=timeout_window)
        remaining_time = timeout_window
    else:
        old_time = value[0] if value else time.time()
        
        time_diff = timeout_window - int(time.time() - old_time)
        cache.set(key, value, timeout= max(time_diff, 1))
        remaining_time = timeout_window - max((int(time.time() - value[0]), 1))
    
    is_limited = current_request_lenght >= max_requests
    if is_limited:
        #   ONLY LOG THE INFORMATION IF THE LIMITING ACTUALLY HAPPENS
        info_logger(msg=f"RATE-LIMITED: ip ({key}) v_len = {current_request_lenght} max_req= {max_requests},supposed expirty is {remaining_time} sec")
    return remaining_time, is_limited


def _response(dict: dict, status=200, debug= debug_base, log = False, logger=logger, logger_type="info", msg = "NOT PASSED") -> JsonResponse | Response:
    """
    ----------------------------------------------------------------------
    ##   RESPONSE + LOGGING
    Dict: required
    
    Logging will not work unles log is set to true

    ----------------------------------------------------------------------
    ### Use this function to return response but also collect logs optionally
    """
    #WORKING ON LOGS FIRST
    if log:
        if logger_type == "info":info_logger(logger=logger, debug=debug, msg=msg )
        elif logger_type == "warning":warning_logger(logger=logger, debug=debug, msg=msg)
        elif logger_type == "error":error_logger(logger=logger, debug=debug, msg=msg)
        else:pass

    # RETURNING RESPONSE
    return JsonResponse(dict, status=status)
    

def info_logger(logger = logger, debug = debug_base, msg = "NOT PASSED"):
    "Info / Debug Logger"
    if debug: print(msg)
    else: return logger.info(msg=msg)
    
def warning_logger(logger = logger, debug = debug_base, msg = "NOT PASSED"):
    "Warning / Debug Logger"
    if debug: print(msg)
    else: return logger.warning(msg=msg)

def error_logger(logger = logger, debug = debug_base, msg = "NOT PASSED"):
    "Error / Debug Logger"
    if debug: print(msg)
    else: return logger.error(msg=msg)



def _optimization(debug = debug_base):
    """Analyze database queries"""
    return 0
    if debug:
        for i, q in enumerate(connection.queries):
            print(f'\nQuery {i + 1}: {q["sql"]}\n')
        print("DB queries:", len(connection.queries))
    else:
        print('debug mode is off')


def notify_admins_account_deleted(deleted_email, deleted_account_type="Staff"):
    """
    ----------------------------------------------------------------------
    ##   DUMMY ADMIN ALERT: ACCOUNT DELETED
    deleted_email: required, the email of the account that was deleted
    deleted_account_type: "Staff" | "Admin" | "Member"

    NO EXTERNAL MAIL PLATFORM IS WIRED YET, so every admin notification is
    just printed to the terminal as a fake email. When a real mail platform
    arrives, only the print block below needs to swap for a real send.
    """
    return 0
    


def set_cache(key, value, timeout = None):
    info_logger(msg=f"CACHE-SET: Set Cache for {key} to a timeout of {timeout}")
    cache.set(key, value, timeout)
    return 0

def get_cache(key):
    value = cache.get(key)
    if not value:
        return False
    return value

def cache_or_run(key, fn, timeout=300):
    # value = get_cache(key)
    # if value:
    #     return value
    value = fn()
    # if value is not None:
    #     set_cache(key, value, timeout)
    #     info_logger(msg=f"CACHE-SET: {key} set since no key was found")
    # else:
        # raise Exception("BEFORE CACHE CAN SET, THE FN NEED TO RETURN SOMETHING")
    return value