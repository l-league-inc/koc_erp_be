import json

from django.core.exceptions import ImproperlyConfigured

from .base import *

secret_file = os.path.join(BASE_DIR, "secrets.json")

with open(secret_file) as f:
    secrets = json.loads(f.read())


DJANGO_ENV_NAME = "local"


def get_secret(setting, secrets=secrets):
    try:
        return secrets[setting]
    except KeyError:
        error_msg = "Set the {} environment variable".format(setting)
        raise ImproperlyConfigured(error_msg)


SECRET_KEY = get_secret("SECRET_KEY")

DEBUG = True

# static
STATIC_ROOT = "/vol/web/static"
MEDIA_ROOT = "/vol/web/media"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": get_secret("DB_HOST"),
        "NAME": get_secret("DB_NAME"),
        "USER": get_secret("DB_USER"),
        "PASSWORD": get_secret("DB_PASSWORD"),
    }
}

# cache
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://redis:6379/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,  # 캐시 오류 시 애플리케이션 계속 실행
            "SOCKET_CONNECT_TIMEOUT": 5,  # 연결 타임아웃(초)
            "SOCKET_TIMEOUT": 5,  # 통신 타임아웃(초)
            "CONNECTION_POOL_KWARGS": {"max_connections": 50},  # 최대 연결 수
        },
        "KEY_PREFIX": "django_ninja_api",  # 키 충돌 방지를 위한 접두사
        "TIMEOUT": 300,  # 기본 캐시 만료 시간(초)
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(os.environ.get("REDIS_HOST", "redis"), 6379)],
        },
    },
}

# cors & csrf
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# token expiration
ACCESS_TOKEN_EXPIRATION_TIME = 60 * 60 * 24 * 7
REFRESH_TOKEN_EXPIRATION_TIME = 90 * 60 * 24 * 7

# aws image upload
AWS_UPLOAD_BUCKET = get_secret("AWS_UPLOAD_BUCKET")
AWS_PRIVATE_BUCKET = get_secret("AWS_PRIVATE_BUCKET")
AWS_REGION = get_secret("AWS_REGION")
AWS_ACCESS_KEY_ID = get_secret("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = get_secret("AWS_SECRET_KEY")

# Logger
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "timestamp": {
            "format": "{asctime} {levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "timestamp"},
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": "logs/log.django",
            "formatter": "timestamp",
        },
        "collection": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": "logs/log.collection",
            "formatter": "timestamp",
        },
    },
    "loggers": {
        "console": {
            "handlers": ["console"],
            "level": "ERROR",
        },
        "django": {
            "handlers": ["file"],
            "level": "INFO",
        },
        "collection": {
            "handlers": ["console", "collection"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# Frontend URL
FRONTEND_URL = "http://127.0.0.1:3000"

# AWS SES
FRONTEND_LOGIN_SUCCESS_URL = f"{FRONTEND_URL}/auth/verifyEmail"
FRONTEND_PASSWORD_RESET_SUCCESS_URL = f"{FRONTEND_URL}/auth/verifyEmailpw"

# Redis
REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_DB = 0

# OpenAI
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"

# CloudFront
CLOUDFRONT_URL = "https://d2559sqcuyrr6z.cloudfront.net"
