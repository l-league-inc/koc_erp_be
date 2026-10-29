from .base import *
from urllib.parse import quote

import firebase_admin
from firebase_admin import credentials
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from config.sentry_utils import before_send, before_send_transaction

DJANGO_ENV_NAME = os.getenv("DJANGO_ENV_NAME", "main")

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = False

# allow hosts
ALLOWED_HOSTS = [
    "dev.api.koc-erp.co.kr",
    "api.koc-erp.co.kr",
    ".railway.app",
]

# middleware override
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.BlockScannerPathsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "mobileesp.middleware.MobileDetectionMiddleware",
]

# static
STATIC_URL = "static/"
STATICFILES_BASE_DIR = BASE_DIR / "staticfiles"
STATICFILES_BASE_DIR.mkdir(exist_ok=True, parents=True)
STATICFILES_DIRS = [STATICFILES_BASE_DIR]
STATIC_ROOT = os.path.join(BASE_DIR, "vol/web/static")
MEDIA_ROOT = os.path.join(BASE_DIR, "vol/web/media")

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# DB Options
DB_OPTIONS = {
    "sslmode": "require",  # 모든 환경에서 SSL 강제
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
    "channel_binding": "require",
}

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.getenv("DB_HOST"),
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "PORT": os.getenv("DB_PORT", 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": DB_OPTIONS,
    }
}

# cache
REDIS_HOST = os.getenv("REDIS_HOST", "redis")  # Redis 호스트
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))  # Redis
REDIS_DB = int(os.getenv("REDIS_DB", 1))  # Redis 데이터베이스 인덱스
REDIS_CACHE_DB = int(os.getenv("REDIS_CACHE_DB", 0))  # 캐시용 Redis 데이터베이스 인덱스
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}",
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
            "hosts": [
                f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
            ],
            "symmetric_encryption_keys": [SECRET_KEY],  # 보안 강화
            "capacity": 1500,  # 채널 용량
            "expiry": 60,  # 메시지 만료 시간 (초)
        },
        "OPTIONS": {
            "connection_timeout": 5,  # 연결 타임아웃
            "socket_timeout": 5,  # 소켓 타임아웃
            "max_connections": 50,  # 최대 연결 수
        },
    },
}

# cors & csrf
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
if DJANGO_ENV_NAME in ["main"]:
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"
else:
    SESSION_COOKIE_SAMESITE = "None"
    CSRF_COOKIE_SAMESITE = "None"

# CORS
CORS_ALLOW_CREDENTIALS = True
CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",  # React app URI
    "http://127.0.0.1:3000",  # React app URI
    "http://localhost:5173",  # React app URI
    "http://127.0.0.1:5173",  # React app URI
    "https://koc-erp.co.kr",  # Frontend Domain URI
    "https://www.koc-erp.co.kr",  # Frontend Domain URI
    "https://dev.koc-erp.co.kr",  # Frontend Domain URI
    "https://admin.koc-erp.co.kr",  # Frontend Domain URI
    "https://dev-admin.koc-erp.co.kr",  # Frontend Domain URI
    "https://dev.api.koc-erp.co.kr",  # Backend Domain URI
    "https://api.koc-erp.co.kr",  # Backend Domain URI
    "https://dev.d4ay0e6oi9l0f.amplifyapp.com",  # Amplify URI
    "https://koc-erp-fe.vercel.app",  # Vercel URI
    "https://*.railway.app",
    "http://*.railway.app",
    "https://koc-erp.apps.tossmini.com",  # Toss mini app URI
    "https://koc-erp.private-apps.tossmini.com",  # Toss mini private app URI
    "https://apps-in-toss.toss.im",  # Toss mini 개발자 앱 URI
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://192\.168\.45\.\d{1,3}:5173$",  # 192.168.45.x:5173 패턴
    r"^http://192\.168\.0\.\d{1,3}:5173$",  # 192.168.0.x:5173 패턴
]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",  # React app URI
    "http://127.0.0.1:3000",  # React app URI
    "http://localhost:5173",  # React app URI
    "http://127.0.0.1:5173",  # React app URI
    "https://koc-erp.co.kr",  # Frontend Domain URI
    "https://www.koc-erp.co.kr",  # Frontend Domain URI
    "https://dev.koc-erp.co.kr",  # Frontend Domain URI
    "https://admin.koc-erp.co.kr",  # Frontend Domain URI
    "https://dev-admin.koc-erp.co.kr",  # Frontend Domain URI
    "https://dev.api.koc-erp.co.kr",  # Backend Domain URI
    "https://api.koc-erp.co.kr",  # Backend Domain URI
    "https://dev.d4ay0e6oi9l0f.amplifyapp.com",  # Amplify URI
    "https://koc-erp-fe.vercel.app",  # Vercel URI
    "https://*.railway.app",
    "http://*.railway.app",
    "https://koc-erp.apps.tossmini.com",  # Toss mini app URI
    "https://koc-erp.private-apps.tossmini.com",  # Toss mini private app URI
    "https://apps-in-toss.toss.im",  # Toss mini 개발자 앱 URI
]

SESSION_COOKIE_DOMAIN = ".koc-erp.co.kr"
CSRF_COOKIE_DOMAIN = ".koc-erp.co.kr"

# URL settings
if DJANGO_ENV_NAME == "main":
    BASE_URL = "https://api.koc-erp.co.kr"
    SERVER_DOMAIN_NAME = "https://api.koc-erp.co.kr"
    KAKAO_LOGIN_DOMAIN = "https://www.koc-erp.co.kr"
    FRONTEND_URL = "https://www.koc-erp.co.kr"
elif DJANGO_ENV_NAME == "dev":
    BASE_URL = "https://dev.api.koc-erp.co.kr"
    SERVER_DOMAIN_NAME = "https://dev.api.koc-erp.co.kr"
    KAKAO_LOGIN_DOMAIN = "http://127.0.0.1:3000"
    FRONTEND_URL = "http://127.0.0.1:3000"


# token expiration
if DJANGO_ENV_NAME == "main":
    ACCESS_TOKEN_EXPIRATION_TIME = 60 * 24 * 3  # 3일로 설정
    REFRESH_TOKEN_EXPIRATION_TIME = 60 * 24 * 30  # 30일로 설정
else:  # dev
    ACCESS_TOKEN_EXPIRATION_TIME = 1  # 테스트 용도로 1분으로 설정
    REFRESH_TOKEN_EXPIRATION_TIME = 60 * 24  # 테스트 용도로 1일로 설정

# aws image upload
AWS_UPLOAD_BUCKET = os.getenv("AWS_UPLOAD_BUCKET")
AWS_PRIVATE_BUCKET = os.getenv("AWS_PRIVATE_BUCKET")
AWS_REGION = os.getenv("AWS_REGION")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
CLOUDFRONT_URL = os.getenv("CLOUDFRONT_URL")

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
        "replicate": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": "logs/log.replicate",
            "formatter": "timestamp",
        },
        "toss": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": "logs/log.toss",
            "formatter": "timestamp",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": True,
        },
        "replicate": {
            "handlers": ["console", "replicate"],
            "level": "DEBUG",
            "propagate": False,
        },
        "toss": {
            "handlers": ["console", "toss"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# AWS SES
FRONTEND_LOGIN_SUCCESS_URL = f"{FRONTEND_URL}/auth/verifyEmail"
FRONTEND_PASSWORD_RESET_SUCCESS_URL = f"{FRONTEND_URL}/auth/verifyEmailpw"

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
OPENAI_MODEL = "gpt-4o-mini"

# kakao api
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_ADMIN_KEY = os.getenv("KAKAO_ADMIN_KEY")
KAKAO_LOGIN_REDIRECT_URI = f"{KAKAO_LOGIN_DOMAIN}/login/kakao/callback"

# alimtalk
ALIMTALK_APIKEY = os.getenv("ALIMTALK_APIKEY")
ALIMTALK_USERID = os.getenv("ALIMTALK_USERID")
ALIMTALK_ADMIN_NUMBER = os.getenv("ALIMTALK_ADMIN_NUMBER")

# Replicate Config
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
REPLICATE_TRAINING_WEBHOOK = f"{BASE_URL}/api/v1/train/replicate-webhook"
REPLICATE_PREDICTION_WEBHOOK_COMPLETED = f"{BASE_URL}/api/v1/generate/replicate-webhook"


# Firebase
PUSH_PRIVATE_KEY = os.getenv("PUSH_PRIVATE_KEY")
PUSH_CLIENT_EMAIL = os.getenv("PUSH_CLIENT_EMAIL") or ""
PUSH_SERVICE_ACCOUNT_KEY = {
    "type": "service_account",
    "project_id": os.getenv("PUSH_PROJECT_ID"),
    "private_key_id": os.getenv("PUSH_PRIVATE_KEY_ID"),
    "private_key": PUSH_PRIVATE_KEY.replace("\\n", "\n") if PUSH_PRIVATE_KEY else None,
    "client_email": PUSH_CLIENT_EMAIL,
    "client_id": os.getenv("PUSH_CLIENT_ID"),
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
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY")
TOSSPAYMENTS_MID = os.getenv("TOSSPAYMENTS_MID")
TOSS_MERT_KEY = os.getenv("TOSS_MERT_KEY")


# Sentry
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[
        DjangoIntegration(),
    ],
    send_default_pii=True,
    release=f"koc_erp_be@{SERVER_VERSION}",
    before_send=before_send,
    before_send_transaction=before_send_transaction,
    traces_sample_rate=0.1,
    profiles_sample_rate=0.1,
    environment=os.getenv("DJANGO_ENV_NAME", "main"),
    auto_session_tracking=True,
)

# Scheduling
SCHEDULING_SECRET_KEY = os.getenv("SCHEDULING_SECRET_KEY")

# YouTube Settings
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")

# MyRealTrip Settings
MYREALTRIP_API_KEY = os.getenv("MYREALTRIP_API_KEY")

# Webhook Settings
AGENT_WEBHOOK_URL = "https://agent.koc-erp.co.kr/webhook"
AGENT_WEBHOOK_API_KEY = os.getenv("AGENT_WEBHOOK_API_KEY")
