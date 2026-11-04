"""
Django settings for the Weather-Aware Truck Routing API.

Everything environment-specific is read from environment variables (or a local `.env` file),
so the same code runs in development, tests and production. The app is stateless: there is no
database, no user accounts and no sessions. Only a cache is used (for upstream API responses and
throttling counters).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173", "http://127.0.0.1:5173"]),
    REDIS_URL=(str, ""),
    DEMO_MODE=(bool, False),
    OPEN_METEO_API_KEY=(str, ""),
    OSRM_BASE_URL=(str, "https://router.project-osrm.org"),
    TRUCK_SPEED_CAP_MPH=(float, 65.0),
    THROTTLE_PLAN=(str, "20/min"),
    THROTTLE_GEOCODE=(str, "60/min"),
    SECURE_SSL_REDIRECT=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DJANGO_DEBUG")
# A real secret is required in production; the fallback is only usable with DEBUG on.
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-key" if DEBUG else None)
if not SECRET_KEY:
    raise environ.ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off")

ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.staticfiles",  # required by WhiteNoise
    "corsheaders",
    "rest_framework",
    "trips",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The built React app (frontend/dist) is served by Django in production, so the SPA and API share
# one origin. In development Vite serves the frontend and proxies /api to Django.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

TEMPLATES: list = []  # no server-rendered pages; the SPA's index.html is served as a file

DATABASES: dict = {}  # stateless service

if env("REDIS_URL"):
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL"),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "trips",
            "OPTIONS": {"MAX_ENTRIES": 50_000},
        }
    }

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_RATES": {
        "plan": env("THROTTLE_PLAN"),
        "geocode": env("THROTTLE_GEOCODE"),
    },
    "EXCEPTION_HANDLER": "trips.api.exceptions.api_exception_handler",
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# No Django static assets exist (no admin), so STATIC_ROOT stays unset; WhiteNoise serves the SPA.
STATIC_URL = "/static/"
# Vite emits hashed assets under dist/assets; WhiteNoise serves dist/ at the site root.
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_MAX_AGE = 3600
# Vite's content-hashed files (assets/name-HASH.ext) never change: cache them forever.
WHITENOISE_IMMUTABLE_FILE_TEST = r"^.+[.-][0-9a-zA-Z_-]{8,12}\.(js|mjs|css|map)$"

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
USE_I18N = False

# --- Security hardening (effective when DEBUG is off and served behind TLS) ---
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# --- App settings ---
TRIPS = {
    "DEMO_MODE": env("DEMO_MODE"),
    "OPEN_METEO_API_KEY": env("OPEN_METEO_API_KEY"),
    "OSRM_BASE_URL": env("OSRM_BASE_URL"),
    "TRUCK_SPEED_CAP_MPH": env("TRUCK_SPEED_CAP_MPH"),
    "USER_AGENT": "weather-aware-truck-routing/1.0 (+https://github.com/)",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"httpx": {"level": "WARNING"}},
}
