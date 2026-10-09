# One image for the API, the collectors and the scheduler; the command picks the role.
FROM python:3.13-slim AS base

RUN pip install --no-cache-dir uv==0.11.32

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# Supercronic runs the collectors on a schedule inside the stack, so the
# schedule moves with the compose file instead of living in a host crontab.
ARG TARGETARCH
ARG SUPERCRONIC_VERSION=v0.2.33
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) sha1=71b0d58cc53f6bd72cf2f293e09e294b79c666d8 ;; \
      arm64) sha1=e0f0c06ebc5627e43b25475711e694450489ab00 ;; \
      *) echo "unsupported arch ${TARGETARCH}"; exit 1 ;; \
    esac; \
    python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH:-amd64}', '/usr/local/bin/supercronic')"; \
    echo "${sha1}  /usr/local/bin/supercronic" | sha1sum -c -; \
    chmod +x /usr/local/bin/supercronic

RUN useradd --system --uid 1000 app
USER app

EXPOSE 8000
CMD ["dr", "serve"]
