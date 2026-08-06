FROM mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948

ARG C7_REPOSITORY_COMMIT

WORKDIR /work

COPY package.json package-lock.json ./
COPY .npmrc ./
COPY packages/map-marker-react/package.json ./packages/map-marker-react/package.json
COPY packages/kor-travel-map-admin/frontend/package.json ./packages/kor-travel-map-admin/frontend/package.json
COPY packages/kor-travel-map-user-client/package.json ./packages/kor-travel-map-user-client/package.json
COPY scripts/patch-redocly-openapi-core.mjs ./scripts/patch-redocly-openapi-core.mjs
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
      io.kortravelmap.c7.playwright-base="mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948"

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /work/packages/kor-travel-map-admin/frontend

# C7 runner는 generated OpenAPI의 exact-triple 계약을 우회할 수 없다. executor
# image 자체가 e2e type gate를 통과해야만 n150에서 live preflight를 시작할 수 있다.
RUN npm run type-check:e2e
