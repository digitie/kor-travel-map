FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp \
    TEMP=/tmp \
    TMP=/tmp

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY packages/kor-travel-map-dagster ./packages/kor-travel-map-dagster

# `[providers]` extra는 git+https pin이라 builder에 git이 필요하다 (#370).
# private provider repo(python-datagokr-api)는 BuildKit secret `github_token`으로
# fetch한다 — GIT_CONFIG_* 환경변수는 이 RUN 수명에서만 존재하므로 토큰이
# 레이어/최종 이미지에 남지 않는다.
RUN --mount=type=secret,id=github_token \
    python -m pip install --no-cache-dir --upgrade pip \
    && if [ -s /run/secrets/github_token ]; then \
        export GIT_CONFIG_COUNT=1 \
            GIT_CONFIG_KEY_0="url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" \
            GIT_CONFIG_VALUE_0="https://github.com/"; \
    fi \
    && python -m pip install --no-cache-dir --prefix=/install ".[providers]" ./packages/kor-travel-map-dagster

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp \
    TEMP=/tmp \
    TMP=/tmp \
    DAGSTER_HOME=/opt/dagster/dagster_home

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser \
    && mkdir -p "$DAGSTER_HOME" \
    && chown -R appuser:appuser /app /opt/dagster

COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser docker/dagster.yaml /opt/dagster/dagster_home/dagster.yaml

USER appuser

EXPOSE 12302

CMD ["sh", "-c", "dagster-webserver -m kortravelmap.dagster.definitions -h 0.0.0.0 -p ${KOR_TRAVEL_MAP_DAGSTER_PORT:-12302}"]
