# kor-travel-map-admin

`kor-travel-map`의 admin 운영 UI 패키지다. Python FastAPI/OpenAPI 백엔드는
`packages/kor-travel-map-api/`의 `kor-travel-map-api` distribution으로 분리되어 있고,
이 디렉토리는 Next.js admin frontend를 소유한다.

## 실행

```bash
cd packages/kor-travel-map-admin/frontend
npm install
npm run dev
```

기본 포트는 `12305`다. backend API는 기본 `http://127.0.0.1:12301`이며,
frontend는 `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`로 API base URL을 받는다.

## 타입 생성

OpenAPI 기계 정본은 `packages/kor-travel-map-api/openapi.json`이다.

```bash
npm -w packages/kor-travel-map-admin/frontend run gen:types
npm -w packages/kor-travel-map-admin/frontend run gen:types:check
```
