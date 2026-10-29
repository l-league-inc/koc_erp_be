from .local import *

# 테스트 환경 플래그
TESTING = True

# Redis 설정 변경
REDIS_TEST_DB = 1  # 테스트용 Redis 데이터베이스 인덱스

REDIS_HOST = "redis"
REDIS_PORT = 6379
REDIS_DB = REDIS_TEST_DB

# 테스트용 캐시: Redis 대신 로컬 메모리 캐시 사용
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-test-cache",
        "TIMEOUT": 300,
    }
}

# 테스트용 채널 레이어: Redis 대신 인메모리 레이어 사용
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
