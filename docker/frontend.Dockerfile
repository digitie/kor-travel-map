FROM node:22-bookworm-slim AS deps

ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY package.json ./
COPY package-lock.json ./
COPY packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY packages/krtour-map-admin/frontend/package.json ./packages/krtour-map-admin/frontend/package.json

RUN npm ci --workspaces --include=optional

FROM node:22-bookworm-slim AS builder

ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

COPY --from=deps /app/package.json ./package.json
COPY --from=deps /app/package-lock.json ./package-lock.json
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY --from=deps /app/packages/krtour-map-admin/frontend/package.json ./packages/krtour-map-admin/frontend/package.json

COPY packages/map-marker-react ./packages/map-marker-react
COPY packages/krtour-map-admin/frontend ./packages/krtour-map-admin/frontend

ARG NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API=http://127.0.0.1:12301
ARG NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL=http://127.0.0.1:12302
# T-221b 좌표 picker(/admin/features/new)가 prerender 시점에 fail-fast로 요구 —
# 누락 시 next build 실패 (ADR-046 kraddr-geo REST, 로컬 표준 12201).
ARG NEXT_PUBLIC_KRADDR_GEO_BASE_URL=http://127.0.0.1:12201
ARG NEXT_PUBLIC_VWORLD_API_KEY=
ENV NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API=$NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API \
    NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL=$NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL \
    NEXT_PUBLIC_KRADDR_GEO_BASE_URL=$NEXT_PUBLIC_KRADDR_GEO_BASE_URL \
    NEXT_PUBLIC_VWORLD_API_KEY=$NEXT_PUBLIC_VWORLD_API_KEY \
    NEXT_TELEMETRY_DISABLED=1

RUN npm -w packages/krtour-map-admin/frontend run build

FROM node:22-bookworm-slim AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=12305 \
    HOSTNAME=0.0.0.0

WORKDIR /app

RUN groupadd --system nodejs \
    && useradd --system --gid nodejs --home-dir /app --shell /usr/sbin/nologin nextjs

COPY --from=builder --chown=nextjs:nodejs /app/packages/krtour-map-admin/frontend/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/packages/krtour-map-admin/frontend/.next/static ./packages/krtour-map-admin/frontend/.next/static

USER nextjs

EXPOSE 12305

CMD ["node", "packages/krtour-map-admin/frontend/server.js"]
