# `300` candidate provenance은 Docker tag의 재해석을 허용하지 않는다. builder/runtime
# 모두 같은 immutable Python base를 써서 sealed Git archive → image RootFS prefix를
# fresh oracle과 final verifier가 독립적으로 재관측할 수 있게 한다.
FROM python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY alembic/env.py alembic/script.py.mako ./alembic/
COPY alembic/baseline ./alembic/baseline
COPY alembic/versions ./alembic/versions
COPY src ./src
COPY packages/kor-travel-map-api ./packages/kor-travel-map-api

# T-VN-C01(2026-08-18): H35 helper가 저장소에서 사라져 `rm -f`가 필요 없어졌다.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --prefix=/install . ./packages/kor-travel-map-api

FROM python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

# ADR-066 T-VN-01 — API image는 production 배포 아티팩트다. compose 밖에서 바로
# 실행해도 fail-closed 기동 검증이 걸리도록 image 기본 profile을 production으로 둔다.
ARG KOR_TRAVEL_MAP_GIT_COMMIT=development
ARG KOR_TRAVEL_MAP_GIT_TREE=development
ARG KOR_TRAVEL_MAP_DOCKERFILE_SHA256=development
ARG KOR_TRAVEL_MAP_BASE_IMAGE_REFERENCE=python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
ARG KOR_TRAVEL_MAP_BASE_IMAGE_ID=sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT" \
    io.kor-travel-map.application-baseline.candidate-git-tree="$KOR_TRAVEL_MAP_GIT_TREE" \
    io.kor-travel-map.application-baseline.candidate-dockerfile-sha256="$KOR_TRAVEL_MAP_DOCKERFILE_SHA256" \
    io.kor-travel-map.application-baseline.candidate-base-image-reference="$KOR_TRAVEL_MAP_BASE_IMAGE_REFERENCE" \
    io.kor-travel-map.application-baseline.candidate-base-image-id="$KOR_TRAVEL_MAP_BASE_IMAGE_ID"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONNOUSERSITE=1 \
    KOR_TRAVEL_MAP_IMAGE_REVISION="$KOR_TRAVEL_MAP_GIT_COMMIT" \
    KOR_TRAVEL_MAP_API_PROFILE=production

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

COPY --from=builder /install /usr/local
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic/env.py alembic/script.py.mako ./alembic/
COPY --chown=root:root alembic/baseline ./alembic/baseline
COPY --chown=root:root alembic/versions ./alembic/versions
COPY --chown=root:root docker/api-entrypoint.sh ./docker/api-entrypoint.sh
COPY --chown=root:root docker/transition-application-schema-0236-to-300.py /usr/local/bin/ktm-application-schema-handoff
COPY --chown=root:root docker/application-schema-fresh-300.py /usr/local/bin/ktm-application-schema-fresh-300
COPY --chown=root:root docker/application-schema-fresh-finalize.py /usr/local/bin/ktm-application-schema-fresh-finalize
COPY --chown=root:root docker/application-schema-final-permit.py /usr/local/bin/ktm-application-schema-final-permit
COPY --chown=root:root docker/application-schema-contract.py /usr/local/bin/ktm-application-schema-contract
COPY --chown=root:root docker/application-schema-head.py /usr/local/bin/ktm-application-schema
COPY --chown=root:root resources/curations ./resources/curations

RUN chown -R root:root /app/alembic /app/alembic.ini /app/docker/api-entrypoint.sh \
    /app/resources/curations \
    /usr/local/bin/ktm-application-schema-handoff \
    /usr/local/bin/ktm-application-schema-fresh-300 \
    /usr/local/bin/ktm-application-schema-fresh-finalize \
    /usr/local/bin/ktm-application-schema-final-permit \
    /usr/local/bin/ktm-application-schema-contract \
    && find /app/alembic -type d -exec chmod 0555 {} + \
    && find /app/alembic -type f -exec chmod 0444 {} + \
    && find /app/resources/curations -type d -exec chmod 0555 {} + \
    && find /app/resources/curations -type f -exec chmod 0444 {} + \
    && chmod 0444 /app/alembic.ini \
    && chmod 0555 /app /app/docker /usr/local/bin/ktm-application-schema \
    && chmod 0555 /usr/local/bin/ktm-application-schema-handoff \
        /usr/local/bin/ktm-application-schema-fresh-300 \
        /usr/local/bin/ktm-application-schema-fresh-finalize \
        /usr/local/bin/ktm-application-schema-final-permit \
        /usr/local/bin/ktm-application-schema-contract \
        ./docker/api-entrypoint.sh \
    && su -s /bin/sh -c 'test ! -w /app \
        && test ! -w /app/docker/api-entrypoint.sh \
        && test ! -w /app/alembic/baseline \
        && test ! -w /app/resources/curations \
        && ! mv /app/resources/curations/manifest.json /app/resources/curations/replaced.json \
        && test ! -w /usr/local/bin/ktm-application-schema-final-permit' appuser

USER appuser

EXPOSE 12701

ENTRYPOINT ["/app/docker/api-entrypoint.sh"]
