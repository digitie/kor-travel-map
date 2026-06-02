FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp \
    TEMP=/tmp \
    TMP=/tmp \
    DAGSTER_HOME=/opt/dagster/dagster_home

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "$DAGSTER_HOME"

COPY pyproject.toml README.md ./
COPY src ./src
COPY packages/krtour-map-dagster ./packages/krtour-map-dagster

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -e . -e packages/krtour-map-dagster

EXPOSE 9013

CMD ["sh", "-c", "dagster dev -m krtour.map_dagster.definitions -h 0.0.0.0 -p ${KRTOUR_MAP_DAGSTER_PORT:-9013}"]
