FROM python:3.12.12-slim-bookworm AS wheels
RUN apt-get update && apt-get install -y --no-install-recommends gcc pkg-config default-libmysqlclient-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements-prototype.txt requirements-nas.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-nas.txt

FROM python:3.12.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Seoul APPROVAL_PRODUCTION=1 DJANGO_DEBUG=0 APPROVAL_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends libmariadb3 mariadb-client && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home approval
COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl && rm -rf /wheels
WORKDIR /app
COPY manage.py ./
COPY approval_site ./approval_site
COPY workflow ./workflow
COPY purchasing ./purchasing
COPY deploy/nas ./deploy/nas
RUN APPROVAL_PRODUCTION=1 DJANGO_DEBUG=0 DJANGO_SECRET_KEY=build-only-unused-key-0000000000000000000000000000000000000000 DB_ENGINE=mariadb DB_NAME=build DB_USER=build DB_PASSWORD=unused DJANGO_ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput && rm -rf var && chmod -R a+rX /app && mkdir -p /data /backups && chown approval:approval /data /backups
USER approval
EXPOSE 8000
CMD ["gunicorn", "approval_site.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "2", "--timeout", "120", "--max-requests", "1000", "--max-requests-jitter", "100", "--access-logfile", "-", "--error-logfile", "-"]
