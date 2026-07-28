# kor-travel-map-admin

`kor-travel-map`의 admin 운영 UI 패키지다. Python FastAPI/OpenAPI 백엔드는
`packages/kor-travel-map-api/`의 `kor-travel-map-api` distribution으로 분리되어 있고,
이 디렉토리는 Next.js admin frontend를 소유한다.

## 실행

```bash
# 저장소 루트의 Linux/WSL 셸에서
source ~/.nvm/nvm.sh && nvm use 22.23.1
npx --yes npm@12.0.1 ci --workspaces --include=optional
npx --yes npm@12.0.1 run verify:npm-tree
npx --yes npm@12.0.1 -w packages/kor-travel-map-admin/frontend run dev
```

기본 포트는 `12705`다. backend API는 기본 `http://127.0.0.1:12701`이며,
frontend는 `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`로 API base URL을 받는다.

## 타입 생성

OpenAPI 기계 정본은 `packages/kor-travel-map-api/openapi.json`이다.

```bash
npx --yes npm@12.0.1 -w packages/kor-travel-map-admin/frontend run gen:types
npx --yes npm@12.0.1 -w packages/kor-travel-map-admin/frontend run gen:types:check
```
