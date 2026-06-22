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
# provider repo(python-*-api 13종)는 2026-06-22부로 전부 PUBLIC이라 익명 clone이
# 되므로, 토큰 없이도 `.[providers]` full ETL 이미지가 항상 빌드된다
# (datagokr가 마지막 private였고 public 전환됨 — 이전의 "토큰 없으면 providers 통째
# 스킵" graceful-degradation은 더 이상 불필요).
#
# BuildKit secret `github_token`은 선택사항이다 — 주어지면 GIT_CONFIG_* url.insteadOf로
# 인증 clone을 써서 미인증 rate-limit을 회피하고 provider repo가 다시 private 되어도
# 복원 가능하지만, 없어도 `.[providers]`는 그대로 설치된다. GIT_CONFIG_*는 이 RUN
# 수명에서만 존재하므로 토큰이 레이어/최종 이미지에 남지 않는다.
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

EXPOSE 12702

CMD ["sh", "-c", "dagster-webserver -m kortravelmap.dagster.definitions -h 0.0.0.0 -p ${KOR_TRAVEL_MAP_DAGSTER_PORT:-12702}"]
