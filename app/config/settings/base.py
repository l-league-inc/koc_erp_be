import os
from pathlib import Path

SERVER_VERSION = "0.0.1"

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def resolve_wiki_docs_dir() -> Path:
    env_dir = os.getenv("WIKI_DOCS_DIR")
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(BASE_DIR / "docs")
    candidates.append(BASE_DIR.parent / "docs")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return BASE_DIR / "docs"


WIKI_DOCS_DIR = resolve_wiki_docs_dir()

# 같은 프로세스의 /mcp. false면 마운트하지 않는다.
MCP_ENABLED = os.getenv("MCP_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
MCP_MAX_PAGE_SIZE = 20
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", "https://api.koc-erp.co.kr/mcp")
MCP_OAUTH_ISSUER = os.getenv("MCP_OAUTH_ISSUER", "").strip()
MCP_OAUTH_CLIENT_ID = os.getenv("MCP_OAUTH_CLIENT_ID", "koc-erp-chatgpt")
MCP_OAUTH_CLIENT_SECRET = os.getenv("MCP_OAUTH_CLIENT_SECRET", "").strip()
MCP_OAUTH_EXTRA_REDIRECT_URIS = os.getenv("MCP_OAUTH_EXTRA_REDIRECT_URIS", "")
OPENAI_APPS_CHALLENGE_TOKEN = os.getenv(
    "OPENAI_APPS_CHALLENGE_TOKEN",
    "b6iX0RdyLRruUa6Bivr8T96asm7XmB__s_4Z8du2abQ",
)

# 로그 디렉토리 경로 설정
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 로그 디렉토리가 없으면 생성
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 기본 설정
TESTING = False

ALLOWED_HOSTS = ["*"]

ASGI_APPLICATION = "config.asgi.application"

CHANNEL_APPS = [
    "channels",
    "daphne",
]

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "corsheaders",
]

if os.getenv("DJANGO_SETTINGS_MODULE") == "config.settings.local":
    THIRD_PARTY_APPS += []

LOCAL_APPS = [
    "core",
    "common",
    "user",
    "verification",
    "notification",
    "notice",
    "wiki",
    "mcp_server",
]

INSTALLED_APPS = CHANNEL_APPS + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "config.middleware.OAuthPopupMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.BlockScannerPathsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "mobileesp.middleware.MobileDetectionMiddleware",
]

MIDDLEWARE += ["django.middleware.gzip.GZipMiddleware"]


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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = "ko-kr"

TIME_ZONE = "Asia/Seoul"

USE_I18N = True

USE_L10N = True

USE_TZ = False

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = "/static/static/"
MEDIA_URL = "/static/media/"

# User model
AUTH_USER_MODEL = "user.User"

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SERVICE_NAME = "KOC ERP"

MAX_UPLOAD_SIZE = 52428800
DATA_UPLOAD_MAX_MEMORY_SIZE = None
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800
DATA_UPLOAD_MAX_NUMBER_FIELDS = None

# cookie 관련 설정
SESSION_SAVE_EVERY_REQUEST = False  # JWT 기반 인증 — 매 요청마다 세션 저장 불필요
SESSION_COOKIE_AGE = 60 * 60 * 24
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# ninja settings
NINJA_PAGINATION_CLASS = "api.pagination.CustomPageNumberPagination"
PAGINATION_PER_PAGE = 10

# AWS SES
SENDER = "cs@koc-erp.co.kr"
BASE_URL = "https://api.koc-erp.co.kr"
API_V1_STR = "/api/v1"
EMAIL_TOKEN_EXPIRE_HOURS = 12
ALGORITHM = "HS256"

SYS_PROMPT = """
당신은 KOC ERP 업무를 돕는 보조입니다. 사용자가 요청한 범위 안에서 절차를 정리하고, 확인된 정보만 안내합니다.
"""

# Plan
FREE_PLAN_LIMIT = {
    "ai_chat_count": 30,
}

# verification limit time
EMAIL_VERIFICATION_LIMIT_TIME = 60 * 10  # 10분
PHONE_VERIFICATION_LIMIT_TIME = 60 * 3  # 3분

# Replicate Config
REPLICATE_MODEL = "l-league-inc/koc-erp-ai"
REPLICATE_FINE_TUNING_MODEL = "ostris/flux-dev-lora-trainer:e440909d3512c31646ee2e0c7d6f6f4923224863a6a10c494606e79fb5844497"
REPLICATE_PROMPT = """
[Trigger Words]
TOK, face_transform, face_swap, portrait_swap, korean_face, asian_face

[Base Prompt]
A photo of TOK Stunning professional portrait photograph, face_transform, ultra-realistic facial features, face_swap, 8k uhd, detailed skin texture, natural lighting, studio quality, photorealistic rendering, seamless face blending, high-end fashion photography, perfect facial symmetry, portrait_swap, clear facial features, professional retouching, magazine quality, flawless skin, spotless complexion, high-end designer dress, luxury fashion, modern elegant style, haute couture, minimalist chic, contemporary fashion, vogue style, smile face

[Negative Prompt]
deformed, bad anatomy, bad eyes, crossed eyes, disfigured, poorly drawn face, mutation, extra limb, ugly, poorly drawn hands, missing limb, floating limbs, disconnected limbs, malformed hands, blur, out of focus, long neck, distorted, body out of frame, bad anatomy, watermark, signature, out of frame, ugly, extra legs, bad eyes, deformed iris, deformed pupils, moles, spots, blemishes, freckles, beauty marks, skin imperfections, acne, pimples, birthmarks, facial marks, dark spots, outdated fashion, tacky, gaudy, cheap looking, excessive frills, old-fashioned dress, costume-like dress
"""

REPLICATE_PREDICTION_INPUT = {
    "prompt": REPLICATE_PROMPT,
    "num_outputs": 4,
    "output_format": "jpg",
}

# AI Photo
AI_PHOTO_TRAINING_MIN_COUNT = 10
AI_PHOTO_TRAINING_MAX_COUNT = 15
AI_PHOTO_TYPES_PHOTO_COUNT = {"A": 4}

# Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1336929022294360145/4qQZNyRmifxKp7Gb2bpxrbxUi-wZ1FqQ9xCb5fB1mNYZcqXiX9YPEc2mB9_KMZrgj3is"

# S3 RAG Bucket
RAG_BUCKET_NAME = "koc-erp-rag"

# Cache TTL (seconds)
CACHE_TTL = 60 * 5  # 5분 — 기본값
CACHE_TTL_AUTH = 60  # 1분 — JWT 인증 유저 캐시
CACHE_TTL_STATIC = 60 * 60 * 24  # 24시간 — 카테고리, FAQ 등 정적 데이터
CACHE_TTL_SHORT = 60 * 15  # 15분 — 광고 배너, 상품 목록

# TOSS
# 토스 로그인 설정
TOSS_DECRYPT_KEY = os.getenv("TOSS_DECRYPT_KEY", "")  # Base64로 인코딩된 AES 키
TOSS_AAD = os.getenv("TOSS_AAD", "TOSS")  # Additional Authenticated Data
TOSS_CALLBACK_BASIC_AUTH = os.getenv(
    "TOSS_CALLBACK_BASIC_AUTH", "BUDGET"
)  # 콜백 Basic Auth 키

# 토스 mTLS 인증서 설정
# Railway에서는 /koc_erp_be/app/certs 볼륨 사용
# 로컬에서는 BASE_DIR/certs 사용
TOSS_CERT_DIR = os.getenv("TOSS_CERT_DIR", os.path.join(BASE_DIR, "certs"))
TOSS_CERT_PATH = os.path.join(
    TOSS_CERT_DIR, "koc-erp_public.crt"
)  # 클라이언트 인증서 경로 (공개키)
TOSS_KEY_PATH = os.path.join(
    TOSS_CERT_DIR, "koc-erp_private.key"
)  # 클라이언트 키 경로 (비밀키)

# Apple Sign In 설정 (REST API & Flutter SDK 공통)
APPLE_APP_ID = os.getenv(
    "APPLE_APP_ID", "kr.co.kocerp.app"
)  # Apple App ID (Bundle ID) - V2에서 사용
APPLE_CLIENT_ID = os.getenv(
    "APPLE_CLIENT_ID", "kr.co.kocerp.web"
)  # Service ID - V1 REST API에서 사용
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")  # Apple Developer Team ID
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")  # Key ID from Apple Developer Console
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY", "")  # .p8 파일의 내용 (Private Key)
APPLE_REDIRECT_URI = os.getenv("APPLE_REDIRECT_URI", "")  # OAuth Redirect URI

# YouTube 설정
YOUTUBE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

# Myrealtrip
MYREALTRIP_API_KEY = os.getenv("MYREALTRIP_API_KEY", "")

# NicePay
NICEPAYMENTS_API_BASE_URL = os.getenv(
    "NICEPAYMENTS_API_BASE_URL", "https://api.nicepay.co.kr"
)
NICEPAYMENTS_API_KEY = os.getenv("NICEPAYMENTS_API_KEY", "")
NICEPAYMENTS_SECRET_KEY = os.getenv("NICEPAYMENTS_SECRET_KEY", "")
NICEPAYMENTS_WEBHOOK_SECRET = os.getenv("NICEPAYMENTS_WEBHOOK_SECRET", "")
NICEPAYMENTS_WEBHOOK_SKIP_VERIFY = os.getenv(
    "NICEPAYMENTS_WEBHOOK_SKIP_VERIFY", ""
).lower() in ("1", "true", "yes")

# 우체국 국내우편 종적조회 (공공데이터포털)
EPOST_TRACKING_SERVICE_KEY = os.getenv("EPOST_TRACKING_SERVICE_KEY", "")
EPOST_TRACKING_API_URL = os.getenv(
    "EPOST_TRACKING_API_URL",
    "http://openapi.epost.go.kr/trace/retrieveLongitudinalService"
    "/retrieveLongitudinalService/getLongitudinalDomesticList",
)
