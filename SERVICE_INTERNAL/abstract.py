"===================================================================="
"""NOT USING ANY INTERFACE, JUST HERE TO AVOID CODE REPETITION"""
"===================================================================="


# import ipaddress  # only used by the disabled IP diagnostic (mask_ip) below
import time

from django.core.cache import cache, caches
from rest_framework.response import Response
from django.http import JsonResponse
from django.db import connection
import logging


logger = logging.getLogger(__name__)

from django.conf import settings
debug_base = getattr(settings, "DEBUG", False)
def get_client_ip(request) -> str:
    """Return the real client IP address.

    The lookup order matters and each step exists for a reason:

    1. ``CF-Connecting-IP`` -- Cloudflare rewrites this header on every
       request to hold the single real client, so it cannot be faked the
       way an ``X-Forwarded-For`` entry can. This is the value to trust on
       the current setup (Cloudflare in front of Render).
    2. The first entry in ``X-Forwarded-For`` -- the oldest hop, which is
       where the client's own address sits. Used when ``CF-Connecting-IP``
       is missing (a plain load balancer that does not inject it).
    3. ``REMOTE_ADDR`` -- the actual TCP peer; last resort, and the only
       value that exists with no proxy in front at all.
    """
    if request is None:
        return "unknown"

    cf_connecting = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_connecting:
        return cf_connecting.strip()

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop

    return request.META.get("REMOTE_ADDR", "unknown")


#   ---------------------------------------------------------------------------
#   TEMPORARY IP DIAGNOSTIC -- COMMENTED OUT (14 Oct 2026).
#
#   What this block did:
#     * mask_ip() blanked the host part of an address (102.89.44.7 ->
#       102.89.x.x) so no raw visitor IP was ever written to the log.
#     * log_forwarded_headers(), when settings.LOG_FORWARDED_HEADERS was on,
#       printed every proxy/IP header each login GET/POST received
#       (CF-Connecting-IP, the X-Forwarded-For chain, X-Real-IP,
#       True-Client-IP, X-Forwarded-Proto/Host and REMOTE_ADDR) so the real
#       client hop could be told apart from Render/Cloudflare infrastructure.
#   The hop is settled now, so this helper, mask_ip, the ``ipaddress`` import,
#   the LOG_FORWARDED_HEADERS setting and the two LoginView call sites are all
#   disabled. Re-enable them together only if the client IP has to be re-checked.
#
# def mask_ip(value: str) -> str:
#     """Hide the host part of an IP address so it is safe to write to logs.
#
#     IPv4 keeps the network prefix and masks the host bits
#     (``102.89.44.7`` -> ``102.89.x.x``); IPv6 keeps the first two hextets
#     (``2001:db8::1`` -> ``2001:db8::x``). Anything that is not an IP, or an
#     empty value, is returned unchanged (empty becomes ``-``)."""
#     value = (value or "").strip()
#     if not value:
#         return "-"
#     try:
#         ip = ipaddress.ip_address(value)
#     except ValueError:
#         return value
#     if ip.version == 4:
#         first, second, *_ = value.split(".")
#         return f"{first}.{second}.x.x"
#     return ":".join(value.split(":")[:2]) + "::x"
#
#
# def log_forwarded_headers(request, label=""):
#     """TEMPORARY DIAGNOSTIC -- no-op unless ``LOG_FORWARDED_HEADERS`` is on.
#
#     Logs every proxy/IP header the app received, masked, so the real client
#     hop can be told apart from Render/Cloudflare infrastructure. The XFF chain
#     is printed in header order, i.e. leftmost = original client, rightmost =
#     the hop nearest us (``client <- proxy1 <- proxy2``)."""
#     if request is None or not getattr(settings, "LOG_FORWARDED_HEADERS", False):
#         return
#
#     def chain(key):
#         raw = request.META.get(key) or ""
#         return " <- ".join(mask_ip(hop) for hop in raw.split(",") if hop.strip()) or "-"
#
#     logger.warning(
#         "FWD-HEADERS[%s] %s %s | remote=%s | xff=[%s] | x-real=%s | "
#         "cf-connecting=%s | true-client=%s | forwarded=[%s] | x-proto=%s | x-host=%s",
#         label,
#         request.method,
#         request.path,
#         mask_ip(request.META.get("REMOTE_ADDR", "")),
#         chain("HTTP_X_FORWARDED_FOR"),
#         mask_ip(request.META.get("HTTP_X_REAL_IP", "")),
#         mask_ip(request.META.get("HTTP_CF_CONNECTING_IP", "")),
#         mask_ip(request.META.get("HTTP_TRUE_CLIENT_IP", "")),
#         chain("HTTP_FORWARDED"),
#         request.META.get("HTTP_X_FORWARDED_PROTO", "-"),
#         request.META.get("HTTP_X_FORWARDED_HOST", "-"),
#     )


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
    #   ---- ADDED: crawlers/clients seen in production logs (Oct 2026) whose
    #   UA does not necessarily contain one of the generic tokens above ----
    #   AI / LLM and answer-engine fetchers
    "chatgpt-user", "cohere-ai", "anthropic-ai", "claude-web", "claudebot", "perplexity",
    "meta-externalagent", "apis-google", "google-extended", "gptbot", "oai-searchbot",
    "openai", "gemini", "googlebot-news", "bingbot", "duckduckbot", "ccbot", "amazonbot",
    "petalbot", "yandexbot", "seznambot", "dotbot", "ahrefsbot", "semrushbot",
    "mj12bot", "blexbot", "bytespider", "imagesiftbot", "tiktokspider", "kagibot",
    "diffbot", "exabot", "turnitinbot", "sogou web spider", "coccocbot", "uptimebot",
    #   search engines and SEO crawlers the generic tokens miss
    "seznam", "megaindex", "qwantify", "screaming frog", "baidu", "sogou",
    "yisou", "yeti/", "google-read-aloud",
    #   RSS / feed fetchers (a feed poll is not a human page read)
    "feedfetcher", "feedly", "feedspot", "inoreader", "newsblur", "feedbin",
    "superfeedr",
    #   social / chat link-preview fetchers not caught above
    "slack-imgproxy", "twitterbot", "telegrambot", "whatsapp", "skypeuripreview",
    #   HTTP clients and scripted libraries a real browser never sends
    "httpx", "aiohttp", "node-fetch", "undici", "got (", "guzzle", "http.rb",
    "ruby/", "php/", "dart/", "deno/", "bun/", "powershell", "winhttp",
    "mechanize", "zend_http_client", "libcurl",
    #   headless browsers, automation and site-audit tools
    "headless", "puppeteer", "webdriver", "chrome-lighthouse", "lighthouse",
    #   uptime and health monitors
    "pingdom", "statuscake", "site24x7", "datadog", "newrelic", "kube-probe",
    "elb-healthchecker", "googlehc", "healthcheck",
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


def is_rate_limited(request, timeout_window=60, max_requests=10, reset_timeout = False, scope=""):
    """
    ### Rate limit the user after the max request so if max is 4 , the 4th getd blocked
    RETURN remaining_time, bool = True => bloc am , false ; leave am

    scope: optional label that gives an endpoint its own counter per IP. Without it every
    caller shares one counter per IP (login attempts would eat into password reset ones).
    """
    if request is None:
        return None, False
    
    #   kwy for the cache
    key = get_client_ip(request)
    if scope:
        key = f"{scope}:{key}"
    
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


def set_cache(key, value, timeout = None):
    info_logger(msg=f"CACHE-SET: Set Cache for {key} to a timeout of {timeout}")
    cache.set(key, value, timeout)
    return 0

def get_cache(key):
    value = cache.get(key)
    if not value:
        info_logger(msg=f"CACHE-GET: No Cache Was Found With the key ({key})")
        return False
    return value

def cache_or_run(key, fn, timeout=300):
    """IT TRIES TO GET THE VALUE AND IF ITS NOT FOUND, IT SET THE CACHE, SAME AS GET -> IF NOT GET -> THEN SET"""
    value = get_cache(key)
    if value:
        return value
    value = fn()
    if value is not None:
        set_cache(key, value, timeout)
        info_logger(msg=f"CACHE-SET: {key} set since no key was found in the cache")
    else:
        msg = f"CRITICAL: Cache got a fn of None, almost raising a good 500 error message. LOOK INTO THIS FN {fn}"
        error_logger(msg=msg)
        # raise Exception("BEFORE CACHE CAN SET, THE FN NEED TO RETURN SOMETHING")
    return value

def invalidate_cache(key):
    response  = cache.delete(key)
    if response: info_logger(msg =f"CACHE-DELETE: Succesfully deleted cache with key ({key})")
    else:info_logger(msg= f"CACHE-DELETE: Tried to delete ({key}) but there is no cache with that key")