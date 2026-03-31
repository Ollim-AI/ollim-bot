FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

COPY docker-entrypoint.sh /usr/local/bin/

RUN useradd --create-home bot \
    && mkdir -p /home/bot/.ollim-bot \
    && chown bot:bot /home/bot/.ollim-bot
USER bot

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "--no-dev", "ollim-bot"]
