FROM python:3.11

ENV PYTHONUNBUFFERED 1
ENV POETRY_VERSION=1.8.2

RUN echo "koc erp backend railway django container. 2026.10.29 13:30 release"

WORKDIR /home/koc_erp_be/

ARG DJANGO_ENV_NAME
ENV DJANGO_ENV_NAME=${DJANGO_ENV_NAME}

# Copy source code to container
COPY . .

RUN pip install --upgrade pip

RUN pip install "poetry==$POETRY_VERSION"

RUN poetry config virtualenvs.create false

RUN poetry install --no-interaction --no-ansi

RUN poetry add whitenoise

EXPOSE 8000

WORKDIR /home/koc_erp_be/app/

CMD ["bash", "-c", "python manage.py collectstatic --noinput --settings=config.settings.railway && python manage.py migrate --settings=config.settings.railway && gunicorn config.asgi:application -k uvicorn.workers.UvicornWorker --workers 4 --env DJANGO_SETTINGS_MODULE=config.settings.railway --bind 0.0.0.0:8000 --timeout 60"]
