FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV POETRY_VERSION=1.8.2
ENV POETRY_NO_INTERACTION=1
ENV POETRY_VIRTUALENVS_CREATE=false

# 필요한 시스템 패키지만 설치
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        postgresql-client \
        curl \
        build-essential \
        libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Poetry 설치
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app

# 의존성 파일만 먼저 복사하여 캐시 활용
COPY pyproject.toml poetry.lock ./

# 의존성 설치 (코드 변경과 독립적으로 캐시됨)
RUN poetry install --only=main --no-root

# 소스코드 복사
COPY ./app /app
COPY ./docs /app/docs

# 사용자 생성
RUN adduser \
    --disabled-password \
    --no-create-home \
    --gecos '' \
    django-user

USER django-user
EXPOSE 8000
