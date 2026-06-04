# Builder stage
FROM python:3.12-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/qatrackplus

ENV VIRTUAL_ENV=/opt/venv
RUN uv venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY pyproject.toml README.md ./
# Install dependencies using uv pip
RUN uv pip install ".[docker,postgres]" django-extensions

# Runtime stage
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y \
    postgresql-client \
    cifs-utils \
    chromium \
    libpq5 \
    curl \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /usr/src/qatrackplus
# Cache bust 2
COPY . .

# Ensure necessary directories exist
RUN mkdir -p logs qatrack/media qatrack/static

# Automatically inject local_settings if provided
RUN cp deploy/docker/local_settings.py qatrack/local_settings.py 2>/dev/null || true

# Make entrypoint executable and move it out of the volume mount
RUN cp deploy/docker/django/entrypoint.sh /entrypoint.sh && \
    dos2unix /entrypoint.sh && \
    chmod +x /entrypoint.sh


EXPOSE 8000
CMD ["/entrypoint.sh"]
# Cache bust 1
