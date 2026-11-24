FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# The release build passes the version; a local build stays "dev".
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# The key directory: a new named volume mounted here takes this owner and mode.
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh && useradd --system --uid 10001 megooitadmin \
    && install -d -o megooitadmin -g megooitadmin -m 0700 /var/lib/megooitadmin/ssh
USER megooitadmin
EXPOSE 8000
# The entrypoint migrates and sets the API role's password first; if either fails, Uvicorn never starts.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
