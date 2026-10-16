import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

load_dotenv()

AUTH_USER_MODEL = "AUTHENTICATION.Auth"

BASE_DIR = Path(__file__).resolve().parent.parent

CSRF_FAILURE_VIEW = "AUTHENTICATION.views.csrf_failure"
CSRF_TRUSTED_ORIGINS = [f"https://{i}" for i in (os.getenv("ALLOWED_HOSTS") or "localhost,127.0.0.1").split(',')]

SECRET_KEY = os.getenv('DJANGO_SECRET')

DEBUG = os.getenv("DEBUG", 'False').upper() in ['TRUE']
# DEBUG = False

if not DEBUG:
    SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

ALLOWED_HOSTS = (os.getenv("ALLOWED_HOSTS") or "localhost,127.0.0.1").split(',')

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
SESSION_COOKIE_AGE = 7 * 60 * 60 # 7 days for reuGlar user
ADMIN_MAX_AGE_TOO = 24 * 60 * 60 # 1 day max for admins for security reason
MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

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
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    
    
CSRF_TRUSTED_ORIGINS

CLOUDINARY_CLOUD_NAME = os.getenv('cloud_name')
CLOUDINARY_API_KEY = os.getenv('cloudinary_api_key')
CLOUDINARY_API_SECRET = os.getenv('cloudinary_api_secret')

#IMAGE UPLOADS (avatars + news images, see SERVICE_INTERNAL/images.py)
IMAGE_UPLOAD_MAX_MB = int(os.getenv('image_upload_max_mb', 5))
#   NON-IMAGE FILE uploads to the /archive/ gallery (see
#   SERVICE_INTERNAL.images.upload_archive_file). Two ceilings, never one:
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
#   file it was (see ARCHIVE.views.ArchiveUploadView and
#   SERVICE_INTERNAL.email_single._try_send_archive_upload_alert_email).
ARCHIVE_UPLOAD_ALERT_EMAIL = os.getenv('archive_upload_alert_email', 'lastissa11@gmail.com')

#   STORY VIEW ALERTS: staff with StaffProfile.get_blog_notification on get
#   an email every N views their own story crosses (see BLOG.views.StoryDetailView
#   and SERVICE_INTERNAL.email_single._try_send_story_views_alert_email).
STORY_VIEWS_ALERT_INTERVAL = int(os.getenv('story_views_alert_interval', 5))