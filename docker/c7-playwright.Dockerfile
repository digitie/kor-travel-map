# Playwright 이미지의 Node는 major만 고정된 apt 판이다. 루트 engines가 정확 Node(.nvmrc,
# ADR-124)이고 .npmrc가 engine-strict이므로, 같은 정확 Node 바이너리를 공식 이미지에서
# 가져와 PATH 앞(/usr/local/bin)에 둔다. 브라우저·Playwright 의존성은 base 그대로다.
FROM node:26.13.1-bookworm-slim@sha256:5df79989ed685e09f0a98019db4cebfb22fb9df1a53c0161664a011f7ff6b0f1 AS exact-node

FROM mcr.microsoft.com/playwright:v1.65.0-noble@sha256:6e3fb709361521eb27161606e6da6d2674e5e89fa16516cb37d6fdd91372273d

COPY --from=exact-node /usr/local/bin/node /usr/local/bin/node

ARG C7_REPOSITORY_COMMIT

WORKDIR /work

COPY package.json package-lock.json ./
COPY .npmrc ./
COPY packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY packages/kor-travel-map-admin/frontend/package.json ./packages/kor-travel-map-admin/frontend/package.json
# workspace의 file:vendor 의존성은 npm ci 전에 exact archive에서 제공해야 한다.
COPY packages/kor-travel-map-admin/frontend/vendor ./packages/kor-travel-map-admin/frontend/vendor
COPY packages/kor-travel-map-user-client/package.json ./packages/kor-travel-map-user-client/package.json
COPY scripts/c7-loopback-ui-proxy.mjs ./scripts/c7-loopback-ui-proxy.mjs
COPY scripts/verify-next-sharp.mjs ./scripts/verify-next-sharp.mjs
COPY scripts/verify-npm-tree.mjs ./scripts/verify-npm-tree.mjs

RUN node -e 'if (!/^[0-9a-f]{40}$/.test(process.argv[1] ?? "")) process.exit(1)' \
      "$C7_REPOSITORY_COMMIT" \
    && npx --yes npm@12.0.1 ci --workspaces --include=optional \
    && npx --yes npm@12.0.1 run verify:npm-tree \
    && npx --yes npm@12.0.1 run verify:next-sharp

COPY packages/map-marker-react ./packages/map-marker-react
COPY packages/kor-travel-map-admin/frontend ./packages/kor-travel-map-admin/frontend
COPY packages/kor-travel-map-user-client ./packages/kor-travel-map-user-client

LABEL io.kortravelmap.c7.repository-commit="$C7_REPOSITORY_COMMIT" \
      io.kortravelmap.c7.playwright-base="mcr.microsoft.com/playwright:v1.65.0-noble@sha256:6e3fb709361521eb27161606e6da6d2674e5e89fa16516cb37d6fdd91372273d"

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /work/packages/kor-travel-map-admin/frontend
