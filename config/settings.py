import os
import logging
from pathlib import Path

from dotenv import load_dotenv
import dj_database_url

# Load .env early so os.environ/getenv picks up values from a local .env file in development
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Deployment mode
IS_PRODUCTION = os.environ.get("IS_PRODUCTION", "False") == "True"

# Security / debugging
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-default-development-key")
DEBUG = not IS_PRODUCTION

# Cognito / OAuth settings
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")
COGNITO_CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET")
COGNITO_DOMAIN = os.getenv("COGNITO_DOMAIN")
COGNITO_REDIRECT_URI = os.getenv("COGNITO_REDIRECT_URI", "https://3.235.196.246.nip.io/auth/callback/")
COGNITO_LOGOUT_REDIRECT_URI = os.getenv("COGNITO_LOGOUT_REDIRECT_URI", "https://3.235.196.246.nip.io/")
COGNITO_REGION = os.getenv("COGNITO_REGION")
# OAuth2 scopes - default to 'openid email'. Use 'openid email profile' if profile scope is enabled in Cognito app client
COGNITO_SCOPE = os.getenv("COGNITO_SCOPE", "openid email")

# Hosts and CSRF trusted origins
# Build ALLOWED_HOSTS depending on environment. Ensure nip.io host is allowed in dev.
if IS_PRODUCTION:
    allowed_hosts_list = []
    eb_hostname = os.environ.get("EB_HOSTNAME")
    if eb_hostname:
        allowed_hosts_list.append(eb_hostname)
    # still include nip.io in case you're testing with it in production slot
    if "3.235.196.246.nip.io" not in allowed_hosts_list:
        allowed_hosts_list.append("3.235.196.246.nip.io")
    ALLOWED_HOSTS = allowed_hosts_list
else:
    ALLOWED_HOSTS = ["3.235.196.246.nip.io", "3.235.196.246", "localhost", "127.0.0.1"]

# CSRF_TRUSTED_ORIGINS: Django 4+ requires full origin (including scheme).
# You may set DJANGO_CSRF_TRUSTED_ORIGINS environment variable as a comma-separated list of origins,
# e.g. "https://example.com,https://sub.example.com"
csrf_env = os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
if csrf_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_env.split(",") if o.strip()]
else:
    # sensible defaults for development / testing
    CSRF_TRUSTED_ORIGINS = ["https://3.235.196.246.nip.io"]
    # In production you may add the real origin via env var or EB_HOSTNAME:
    if IS_PRODUCTION and os.environ.get("EB_HOSTNAME"):
        CSRF_TRUSTED_ORIGINS = [f"https://{os.environ.get('EB_HOSTNAME')}"]

# If sitting behind a proxy or ALB that terminates TLS, set this so Django knows requests are HTTPS.
# Only set if your reverse proxy populates X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker.apps.TrackerConfig",  # Use TrackerConfig to ensure signals are loaded
    "storages",
    "core",  # provides health endpoint and small utilities
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tracker.middleware.CognitoTokenMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Security headers - Content Security Policy is handled via meta tag in templates
# Note: If you want to use CSP middleware instead, install django-csp and configure it here
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

# --- DATABASE SETTINGS ---
# Use sqlite fallback when no RDBMS is configured to prevent Django crashes
# This allows Django admin/auth to work while app data is stored in DynamoDB
db_url = os.getenv("DATABASE_URL", "").strip()
if IS_PRODUCTION and db_url:
    # Production: try DATABASE_URL first
    try:
        DATABASES = {
            'default': dj_database_url.config(conn_max_age=600)
        }
        # Validate the config actually has a database
        if not DATABASES.get('default', {}).get('NAME'):
            raise ValueError("DATABASE_URL did not provide a database name")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning("Failed to configure database from DATABASE_URL: %s. Falling back to sqlite.", e)
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
elif not IS_PRODUCTION:
    # Development: If DATABASE_NAME env var is supplied, use Postgres settings
    db_name = os.getenv("DATABASE_NAME", "").strip()
    if db_name:
        db_host = os.getenv("DATABASE_HOST") or "localhost"
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": db_name,
                "USER": os.getenv("DATABASE_USER", ""),
                "PASSWORD": os.getenv("DATABASE_PASSWORD", ""),
                "HOST": db_host,
                "PORT": os.getenv("DATABASE_PORT", "5432"),
            }
        }
    else:
        # Fallback to sqlite when DATABASE_NAME is not set
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
else:
    # Production but no DATABASE_URL: use sqlite fallback
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# -------- AWS CONFIGURATION --------
# AWS Region (used by all AWS services)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# -------- AWS S3 CONFIGURATION --------
# S3 bucket for storing planting images
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME") or os.environ.get("S3_BUCKET", "terratrack-media")
AWS_S3_REGION_NAME = os.getenv("AWS_S3_REGION_NAME", AWS_REGION)
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com" if AWS_STORAGE_BUCKET_NAME else ""

# -------- AWS DYNAMODB CONFIGURATION --------
# DynamoDB tables for users and plantings
DYNAMODB_USERS_TABLE_NAME = os.getenv("DYNAMODB_USERS_TABLE_NAME") or os.getenv("DYNAMO_USERS_TABLE", "users")
DYNAMODB_PLANTINGS_TABLE_NAME = os.getenv("DYNAMODB_PLANTINGS_TABLE_NAME") or os.getenv("DYNAMO_PLANTINGS_TABLE", "plantings")
DYNAMO_USERS_PK = os.getenv("DYNAMO_USERS_PK", "username")

# -------- AWS SNS CONFIGURATION --------
# SNS topic for harvest notifications
SNS_TOPIC_ARN = os.getenv(
    "SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:518029233624:harvest-notifications"
)

# -------- AWS COGNITO CONFIGURATION --------
# Cognito User Pool ID (for JWKS verification)
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "us-east-1_HGEM2vRNI")

# --- STATIC FILES (CSS, JavaScript, Images) ---
if IS_PRODUCTION and AWS_STORAGE_BUCKET_NAME:
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
    STATIC_LOCATION = "static"
    MEDIA_LOCATION = "media"

    STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{STATIC_LOCATION}/"
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/{MEDIA_LOCATION}/"

    STATICFILES_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    # Provide a media storage class reference (used by DEFAULT_FILE_STORAGE setting)
    from storages.backends.s3boto3 import S3Boto3Storage

    class MediaStorage(S3Boto3Storage):
        location = MEDIA_LOCATION
        file_overwrite = False

    DEFAULT_FILE_STORAGE = "config.settings.MediaStorage"
else:
    STATIC_URL = "/static/"
    STATIC_ROOT = BASE_DIR / "staticfiles"
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- SESSION CONFIGURATION ---
# Use signed cookies for sessions to avoid database access during OAuth callbacks
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
LOGIN_URL = "/auth/login/"

# Force HTTPS for redirects when behind a proxy
# If your app is behind a reverse proxy (nginx, ALB) that terminates TLS,
# ensure X-Forwarded-Proto header is set and SECURE_PROXY_SSL_HEADER is configured above
# For direct access, you may need to configure your web server to redirect HTTP to HTTPS
USE_TLS = os.getenv("USE_TLS", "False").lower() == "true"
if USE_TLS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Optional: logging minimal config to surface errors during startup/runtime
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"}
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}

# Any additional third-party or project specific settings can go below.