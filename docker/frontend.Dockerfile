FROM node:22-bookworm-slim

ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY package.json ./
COPY packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY packages/krtour-map-admin/frontend/package.json ./packages/krtour-map-admin/frontend/package.json

RUN npm install --workspaces --include=optional

COPY packages/map-marker-react ./packages/map-marker-react
COPY packages/krtour-map-admin/frontend ./packages/krtour-map-admin/frontend

ARG NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API=http://127.0.0.1:9011
ARG NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL=http://127.0.0.1:9013
ARG NEXT_PUBLIC_VWORLD_API_KEY=
ENV NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API=$NEXT_PUBLIC_KRTOUR_MAP_ADMIN_API \
    NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL=$NEXT_PUBLIC_KRTOUR_MAP_DAGSTER_URL \
    NEXT_PUBLIC_VWORLD_API_KEY=$NEXT_PUBLIC_VWORLD_API_KEY \
    NEXT_TELEMETRY_DISABLED=1

RUN npm -w packages/krtour-map-admin/frontend run build

WORKDIR /app/packages/krtour-map-admin/frontend
EXPOSE 9012

CMD ["npx", "next", "start", "--port", "9012", "--hostname", "0.0.0.0"]
