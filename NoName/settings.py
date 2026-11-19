import os
from pathlib import Path
from urllib.parse import urlsplit

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

AUTH_USER_MODEL = "AUTHENTICATION.Auth"

BASE_DIR = Path(__file__).resolve().parent.parent

CSRF_FAILURE_VIEW = "AUTHENTICATION.views.csrf_failure"

SECRET_KEY = os.getenv('DJANGO_SECRET')

DEBUG = os.getenv("DEBUG", 'False').upper() in ['TRUE']
# DEBUG = False

if DEBUG:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
else:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

#   HTTPS / SECURITY HEADERS. The site is served through a proxy (Cloudflare
#   in front of Render), so Django has to trust a request with its header containing X-Forwarded-Proto before
#   it can know a request is secure. HSTS is only sent on secure requests and
#   is disabled in DEBUG. CSP is report-only for now: the AdSense tag and the
#   inline splash/theme scripts must keep working while Google reviews them.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_HSTS_SECONDS = 0 if DEBUG else 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

#   CSP REPORTING: report-only violations are posted to /csp-report/, which
#   logs them and emails new ones to this address. Deduplication and an hourly
#   cap keep one noisy page from flooding the inbox.
CSP_REPORT_ENABLED = os.getenv("CSP_REPORT_ENABLED", "False" if DEBUG else "True").upper() == "TRUE"
CSP_REPORT_EMAIL = os.getenv("CSP_REPORT_EMAIL", "lastissa11@gmail.com")
CSP_REPORT_MAX_BYTES = 16 * 1024
CSP_REPORT_DEDUPE_SECONDS = 6 * 60 * 60
CSP_REPORT_MAX_EMAILS_PER_HOUR = 10

def _clean_public_host(value):
    """Return a bare lowercase hostname from an env-style host value."""
    value = (value or "").strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = urlsplit(value).hostname or ""
    else:
        value = value.split("/", 1)[0].split(":", 1)[0]
    return value.strip().rstrip(".").lstrip(".")


def _first_usable_host(hosts):
    for value in hosts:
        host = _clean_public_host(value)
        if host and "*" not in host:
            return host
    return ""


def _derive_ads_host(host):
    """``ads.<host>`` for the first allowed host, including localhost.

    The ads flow is a real subdomain even while developing. If the first
    allowed host is ``www.example.com`` the ``www`` is dropped so the result is
    ``ads.example.com`` rather than ``ads.www.example.com``.
    """
    host = _clean_public_host(host)
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("ads."):
        return host
    return f"ads.{host}"


def _cookie_domain(host):
    """Parent domain for cross-subdomain sessions, or None for local/IP hosts."""
    host = _clean_public_host(host)
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0", "testserver"}:
        return None
    if host.startswith(("www.", "ads.")):
        host = host.split(".", 1)[1]
    return f".{host}" if "." in host else None


ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
]

#   The ads page always gets its own host. ``ADS_HOST`` wins when set;
#   otherwise it is derived from the first usable ALLOWED_HOSTS entry, including
#   localhost (ads.localhost) so development matches production routing.
ADS_HOST = _clean_public_host(os.getenv("ADS_HOST", ""))
if not ADS_HOST or "*" in ADS_HOST:
    ADS_HOST = _derive_ads_host(_first_usable_host(ALLOWED_HOSTS))

if ADS_HOST:
    if ADS_HOST not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(ADS_HOST)
    #   A manager may give one advert its own subdomain (newads.<base>). The
    #   wildcard lets that host reach Django; the middleware only serves a host
    #   when an AdvertReference actually owns it.
    ads_base = ADS_HOST[4:] if ADS_HOST.startswith("ads.") else ""
    if ads_base and f".{ads_base}" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(f".{ads_base}")

CSRF_TRUSTED_ORIGINS = []
for host in ALLOWED_HOSTS:
    if not host or host == "*" or host.startswith("*."):
        continue
    if host.startswith("."):
        CSRF_TRUSTED_ORIGINS.append(f"https://*{host}")
        if DEBUG:
            CSRF_TRUSTED_ORIGINS.append(f"http://*{host}")
    else:
        CSRF_TRUSTED_ORIGINS.append(f"https://{host}")
        if DEBUG:
            CSRF_TRUSTED_ORIGINS.append(f"http://{host}")
CSRF_TRUSTED_ORIGINS = sorted(set(CSRF_TRUSTED_ORIGINS))

#   Session and CSRF cookies are shared by the root domain and every subdomain
#   (news, ads and any advert subdomain), so a login on one host holds on all
#   of them. The shared domain is the ads base, the same domain the wildcard
#   ALLOWED_HOSTS entry covers. Locally the cookies stay host-only because
#   browsers may reject a Domain for localhost or a raw IP; set COOKIE_DOMAIN
#   (for example ".localhost") to try sharing there. An explicit value wins in
#   every mode.
_explicit_cookie_domain = (os.getenv("COOKIE_DOMAIN", "") or "").strip().lower()
if _explicit_cookie_domain:
    SESSION_COOKIE_DOMAIN = _explicit_cookie_domain
elif DEBUG:
    SESSION_COOKIE_DOMAIN = None
else:
    SESSION_COOKIE_DOMAIN = _cookie_domain(
        ADS_HOST[4:] if ADS_HOST.startswith("ads.") else _first_usable_host(ALLOWED_HOSTS)
    )
CSRF_COOKIE_DOMAIN = SESSION_COOKIE_DOMAIN

#   TEMPORARY IP DIAGNOSTIC -- COMMENTED OUT (14 Oct 2026).
#   When True this flag switched on SERVICE_INTERNAL.abstract.log_forwarded_headers,
#   which made the login views log the masked proxy/IP header chain
#   (CF-Connecting-IP, the X-Forwarded-For hops, X-Real-IP, True-Client-IP,
#   REMOTE_ADDR, X-Forwarded-Proto/Host) so the real client hop could be told
#   apart from Render/Cloudflare infrastructure. The investigation is finished,
#   so the flag, the helper, mask_ip and the two LoginView call sites are all
#   disabled. Re-enable them together only if the client IP has to be re-checked.
# LOG_FORWARDED_HEADERS = os.getenv("LOG_FORWARDED_HEADERS", "False").upper() in {"TRUE", "1", "YES"}

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    '_',
    'AUTHENTICATION',
    'BLOG',
    'HOME',
    'STAFF',
    'ADMIN',
    'ARCHIVE',
    'Partner'
    
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    '_.middleware.SecurityHeadersMiddleware',
    '_.middleware.AdsSubdomainMiddleware',
    '_.middleware.MaintenanceModeMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'AUTHENTICATION.middleware.AuthEndpointThrottleMiddleware',
    'AUTHENTICATION.middleware.QueryCountMiddleware',
    'AUTHENTICATION.middleware.AdminMaxPeriod',
    'AUTHENTICATION.middleware.ActiveSessionTracker',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'NoName.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'SERVICE_INTERNAL.config.custom_context_processors',
            ],
        },
    },
]

WSGI_APPLICATION = 'NoName.wsgi.application'

if os.getenv('use_external'):
    DATABASES = {
        "default": dj_database_url.config(
            default=os.environ.get("db_url"),
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
    DATABASES["default"]["OPTIONS"] = {
        "sslmode": "require",
    }
    
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        #   THE PROJECT'S PASSWORD FLOOR IS 6 CHARACTERS (the forms say so and
        #   SERVICE_INTERNAL.passwords runs these validators on every incoming
        #   password), so the length validator is pinned to 6 rather than
        #   Django's default 8. Common/numeric/similarity checks still apply.
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 6},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Africa/Lagos'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60 # 7 days for regular user
ADMIN_MAX_AGE_TOO = 24 * 60 * 60 # 1 day max for admins for security reason

STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

SY_SECRET = os.getenv('sy_secret')

MAINTENANCE_MODE = os.getenv('MAINTENANCE_MODE', "FALSE")

REDIS_URL=os.getenv('redis_url')
if REDIS_URL and os.getenv('use_redis'):
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "IGNORE_EXCEPTIONS": True,
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
            },
        }
    }
else:
    print("i no use redis")
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    


CLOUDINARY_CLOUD_NAME = os.getenv('cloud_name')
CLOUDINARY_API_KEY = os.getenv('cloudinary_api_key')
CLOUDINARY_API_SECRET = os.getenv('cloudinary_api_secret')

#IMAGE UPLOADS (avatars + news images, see SERVICE_INTERNAL/images.py)
IMAGE_UPLOAD_MAX_MB = int(os.getenv('image_upload_max_mb', 5))
#   Advert landing pages are full HTML documents stored as Cloudinary raw
#   assets. They are code, so keep the ceiling small. ADVERT_LANDING_MAX_BYTES
#   wins when set; otherwise the friendlier MB value is used.
ADVERT_LANDING_MAX_MB = int(os.getenv('advert_landing_max_mb', 5))
ADVERT_LANDING_MAX_BYTES = int(ADVERT_LANDING_MAX_MB * 1024 * 1024)
#   NON-IMAGE FILE uploads to the /archive/ gallery (see
#   SERVICE_INTERNAL.images.upload_archive_file). Two ceilings:
#   videos (mp4/mov) get ARCHIVE_VIDEO_UPLOAD_MAX_MB (default 5 -- kept
#   small so a single clip can never burn a big slice of hosting bandwidth),
#   and every other file kind is kept much smaller with
#   ARCHIVE_FILE_UPLOAD_MAX_MB (default 3).
ARCHIVE_VIDEO_UPLOAD_MAX_MB = int(os.getenv('archive_video_upload_max_mb', 5))
ARCHIVE_FILE_UPLOAD_MAX_MB = int(os.getenv('archive_file_upload_max_mb', 3))

RESEND_API_KEY = os.getenv('resend_api_key')

#   ARCHIVE UPLOAD ALERTS: when the superuser turns the toggle on
#   (ADMIN.models.SiteSettings.archive_upload_alerts), every new item added to
#   the /archive/ gallery emails this address who uploaded it and what kind of
#   file it was/
ARCHIVE_UPLOAD_ALERT_EMAIL = os.getenv('archive_upload_alert_email', 'lastissa11@gmail.com')

#   STORY VIEW ALERTS: staff with StaffProfile.get_blog_notification on get
#   an email every N views their own story crosses
STORY_VIEWS_ALERT_INTERVAL = int(os.getenv('story_views_alert_interval', 10))