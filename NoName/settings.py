import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
import os

load_dotenv()

AUTH_USER_MODEL = "AUTHENTICATION.Auth"

BASE_DIR = Path(__file__).resolve().parent.parent

CSRF_FAILURE_VIEW = "AUTHENTICATION.views.csrf_failure"
CSRF_TRUSTED_ORIGINS = ['https://esta-sensate-unquickly.ngrok-free.dev',]

SECRET_KEY = os.getenv('DJANGO_SECRET')

DEBUG = os.getenv("DEBUG", 'False').upper() in ['TRUE']
# DEBUG = False

ALLOWED_HOSTS = (os.getenv("ALLOWED_HOSTS") or "localhost,127.0.0.1").split(',')

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
    'ADMIN'
    
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
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
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
SESSION_COOKIE_AGE = 7 * 60 * 60

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


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
IMAGE_UPLOAD_MAX_MB = int(os.getenv('image_upload_max_mb', 4))

RESEND_API_KEY = os.getenv('resend_api_key')