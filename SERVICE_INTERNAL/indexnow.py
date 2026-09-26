"""IndexNow: tells Bing (and every other IndexNow-participating engine --
Yandex, Seznam, Naver...) about one URL the moment it changes, instead of
waiting for their crawlers to notice on their own next visit.

Reuses the key file the project already serves at
"/28499029458943a79b9877afdefa8212.txt" (see
HOME.views.BingIndexNowView / AUTHENTICATION/templates/
28499029458943a79b9877afdefa8212.txt) -- that filename *is* the IndexNow
key, so nothing new needs registering with Bing, this only calls the API
Bing already trusts that key for.

Best effort only: a failed ping never raises and never blocks whatever
just published the page (see BLOG story publish in
HOME.views.AddNewsView.post, the only caller right now). Worst case, the
page just waits for a normal crawl instead of an instant one.
"""

import requests
from django.conf import settings
from concurrent.futures import ThreadPoolExecutor

from SERVICE_INTERNAL.abstract import error_logger, info_logger
from SERVICE_INTERNAL.config import About

#   Same pattern as SERVICE_INTERNAL.email_single._EMAIL_EXECUTOR: a tiny
#   background pool so a slow/unreachable IndexNow endpoint can never add
#   latency to the publish request that triggered the ping.
_INDEXNOW_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="indexnow-ping")

#   THE KEY FILE IS THE KEY: whatever this string is, a file with this
#   exact name + ".txt", containing this exact string, must exist at the
#   domain root -- see AUTHENTICATION/templates/28499029458943a79b9877afdefa8212.txt
#   and its route in NoName/urls.py. Change one, change both.
INDEXNOW_KEY = "28499029458943a79b9877afdefa8212"

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
INDEXNOW_TIMEOUT_SECONDS = 4


def _do_ping(url: str) -> bool:
    if not url:
        return False

    host = About.domain.rstrip("/").split("://")[-1]
    payload = {
        "host": host,
        "key": INDEXNOW_KEY,
        "keyLocation": f"{About.domain.rstrip('/')}/{INDEXNOW_KEY}.txt",
        "urlList": [url],
    }

    try:
        response = requests.post(INDEXNOW_ENDPOINT, json=payload, timeout=INDEXNOW_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        error_logger(msg=f"INDEXNOW PING FAILED (network) for {url}: {exc}")
        return False

    #   200 = accepted, 202 = accepted, key not yet fully validated (still fine).
    if response.status_code in (200, 202):
        info_logger(msg=f"INDEXNOW PING OK ({response.status_code}) for {url}")
        return True

    error_logger(msg=f"INDEXNOW PING REJECTED ({response.status_code}) for {url}: {response.text[:300]}")
    return False


def ping_indexnow(url: str, no_async: bool = False) -> None:
    """Tells IndexNow (Bing et al.) that `url` is new/updated, right now.
    `url` must be the full absolute address of the page (e.g. the story's
    own https://<domain>/news/<slug>/ URL).

    Fires in a background thread by default (see _INDEXNOW_EXECUTOR above)
    so the request that triggered it (a story publish -- see
    HOME.views.AddNewsView.post) returns immediately regardless of how
    IndexNow responds. Pass `no_async=True` (tests, management commands)
    to run and wait for it inline instead.

    Skipped entirely in DEBUG (local/dev runs should never ping a real
    search engine on the developer's behalf)."""
    if getattr(settings, "DEBUG", False):
        info_logger(msg=f"INDEXNOW SKIPPED (DEBUG): {url}")
        return

    if no_async:
        _do_ping(url)
    else:
        _INDEXNOW_EXECUTOR.submit(_do_ping, url)
