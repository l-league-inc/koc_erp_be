from .base import *
import json
from urllib.parse import quote

from django.core.exceptions import ImproperlyConfigured
import firebase_admin
from firebase_admin import credentials


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
ASSISTANT_ID = get_secret("ASSISTANT_ID")
OPENAI_MODEL = "gpt-4o-mini"

# kakao api
KAKAO_REST_API_KEY = get_secret("KAKAO_REST_API_KEY")
KAKAO_ADMIN_KEY = get_secret("KAKAO_ADMIN_KEY")
KAKAO_LOGIN_DOMAIN = "http://127.0.0.1:8000"
# KAKAO_LOGIN_REDIRECT_URI = f"{KAKAO_LOGIN_DOMAIN}/login/kakao/callback"
KAKAO_LOGIN_REDIRECT_URI = f"{KAKAO_LOGIN_DOMAIN}/api/v1/kakao/callback"

# CloudFront
CLOUDFRONT_URL = "https://d2559sqcuyrr6z.cloudfront.net"

# alimtalk
ALIMTALK_APIKEY = get_secret("ALIMTALK_APIKEY")
ALIMTALK_USERID = get_secret("ALIMTALK_USERID")
ALIMTALK_ADMIN_NUMBER = get_secret("ALIMTALK_ADMIN_NUMBER")

# Replicate Config
REPLICATE_API_TOKEN = get_secret("REPLICATE_API_TOKEN")
REPLICATE_TRAINING_WEBHOOK = None
REPLICATE_PREDICTION_WEBHOOK_COMPLETED = None


# Firebase
PUSH_PRIVATE_KEY = get_secret("PUSH_PRIVATE_KEY")
PUSH_CLIENT_EMAIL = get_secret("PUSH_CLIENT_EMAIL")
PUSH_SERVICE_ACCOUNT_KEY = {
    "type": "service_account",
    "project_id": get_secret("PUSH_PROJECT_ID"),
    "private_key_id": get_secret("PUSH_PRIVATE_KEY_ID"),
    "private_key": PUSH_PRIVATE_KEY.replace("\\n", "\n") if PUSH_PRIVATE_KEY else None,
    "client_email": PUSH_CLIENT_EMAIL,
    "client_id": get_secret("PUSH_CLIENT_ID"),
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/"
    + quote(PUSH_CLIENT_EMAIL, safe=""),
    "universe_domain": "googleapis.com",
}
cred = credentials.Certificate(PUSH_SERVICE_ACCOUNT_KEY)
FCM_APP = firebase_admin.initialize_app(cred)


# Toss
TOSS_SECRET_KEY = get_secret("TOSS_SECRET_KEY")
TOSSPAYMENTS_MID = get_secret("TOSSPAYMENTS_MID")
TOSS_MERT_KEY = get_secret("TOSS_MERT_KEY")

# YouTube Settings
YOUTUBE_API_KEY = get_secret("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = get_secret("YOUTUBE_CHANNEL_ID")

# MyRealTrip Settings
MYREALTRIP_API_KEY = get_secret("MYREALTRIP_API_KEY")

# Webhook Settings
AGENT_WEBHOOK_URL = "https://agent.koc-erp.co.kr/webhook"
AGENT_WEBHOOK_API_KEY = get_secret("AGENT_WEBHOOK_API_KEY")

# 우체국 종적조회 (공공데이터포털). Decoding 키 권장. Encoding 키도 서버가 unquote한다.
EPOST_TRACKING_SERVICE_KEY = secrets.get("EPOST_TRACKING_SERVICE_KEY") or os.getenv(
    "EPOST_TRACKING_SERVICE_KEY", ""
)
