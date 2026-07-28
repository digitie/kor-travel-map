FROM node:22.23.1-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3 AS deps

ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY package.json ./
COPY package-lock.json ./
COPY .npmrc ./
COPY packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY packages/kor-travel-map-admin/frontend/package.json ./packages/kor-travel-map-admin/frontend/package.json
COPY scripts/patch-redocly-openapi-core.mjs ./scripts/patch-redocly-openapi-core.mjs
COPY scripts/verify-next-sharp.mjs ./scripts/verify-next-sharp.mjs
COPY scripts/verify-npm-tree.mjs ./scripts/verify-npm-tree.mjs

RUN npx --yes npm@12.0.1 ci --workspaces --include=optional \
    && npx --yes npm@12.0.1 run verify:npm-tree \
    && npx --yes npm@12.0.1 run verify:next-sharp

FROM node:22.23.1-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3 AS builder

ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

COPY --from=deps /app/package.json ./package.json
COPY --from=deps /app/package-lock.json ./package-lock.json
COPY --from=deps /app/.npmrc ./.npmrc
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY --from=deps /app/packages/kor-travel-map-admin/frontend/package.json ./packages/kor-travel-map-admin/frontend/package.json

COPY packages/map-marker-react ./packages/map-marker-react
COPY packages/kor-travel-map-admin/frontend ./packages/kor-travel-map-admin/frontend
COPY docker/frontend.Dockerfile ./docker/frontend.Dockerfile
COPY scripts/frontend-build-inputs.mjs ./scripts/frontend-build-inputs.mjs
COPY scripts/frontend-source-digest.mjs ./scripts/frontend-source-digest.mjs
COPY scripts/patch-redocly-openapi-core.mjs ./scripts/patch-redocly-openapi-core.mjs
COPY scripts/verify-next-sharp.mjs ./scripts/verify-next-sharp.mjs
COPY scripts/verify-npm-tree.mjs ./scripts/verify-npm-tree.mjs

ARG NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://127.0.0.1:12701
ARG NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=http://127.0.0.1:12702
ARG KOR_TRAVEL_MAP_GIT_COMMIT=development
# T-221b 좌표 picker(/admin/features/new)가 prerender 시점에 fail-fast로 요구 —
# 누락 시 next build 실패 (ADR-046 kor-travel-geo REST, docker-manager 표준 12501).
ARG NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=http://127.0.0.1:12501
ARG NEXT_PUBLIC_VWORLD_API_KEY=
ARG NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=
ENV NEXT_PUBLIC_KOR_TRAVEL_MAP_API=$NEXT_PUBLIC_KOR_TRAVEL_MAP_API \
    NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=$NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL \
    NEXT_PUBLIC_KOR_TRAVEL_MAP_GIT_COMMIT=$KOR_TRAVEL_MAP_GIT_COMMIT \
    NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=$NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL \
    NEXT_PUBLIC_VWORLD_API_KEY=$NEXT_PUBLIC_VWORLD_API_KEY \
    NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=$NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY \
    NEXT_TELEMETRY_DISABLED=1

RUN node scripts/frontend-source-digest.mjs \
    --write packages/kor-travel-map-admin/frontend/src/generated/frontend-build-info.ts

RUN npx --yes npm@12.0.1 -w packages/kor-travel-map-admin/frontend run build

FROM node:22.23.1-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3 AS runner

ARG KOR_TRAVEL_MAP_GIT_COMMIT=development

LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT"

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=12705 \
    HOSTNAME=0.0.0.0

WORKDIR /app

RUN groupadd --system nodejs \
    && useradd --system --gid nodejs --home-dir /app --shell /usr/sbin/nologin nextjs

COPY --from=builder --chown=nextjs:nodejs /app/packages/kor-travel-map-admin/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/packages/kor-travel-map-admin/frontend/.next/static ./packages/kor-travel-map-admin/frontend/.next/static

USER nextjs

EXPOSE 12705

CMD ["node", "packages/kor-travel-map-admin/frontend/server.js"]
