# ADR-055: REST API Python backend와 admin frontend를 별도 패키지로 분리한다

### 상태

Accepted (2026-06-13) — T-226 package identity 정리 이후 추가 사용자 결정.

### 배경

ADR-020/035/045 이후 `kor-travel-map-admin`은 FastAPI REST backend와 Next.js admin UI를
한 디렉토리/패키지 이름 아래 함께 담고 있었다. 그러나 `/v1/features`,
`/v1/categories`, `/v1/providers`, `/v1/public`, `/v1/curated-*`처럼 admin이 아닌
user-facing(공개) REST 표면도 같은 backend가 제공한다. Prometheus 성능 계측도
admin 라우터가 아니라 REST API 전체를 대상으로 한다.

`kor-travel-map-admin`이라는 Python distribution 이름은 backend 책임을 admin UI로
오해하게 만들고, 설정 prefix(`KOR_TRAVEL_MAP_ADMIN_*`)도 API 서버 설정과 frontend
설정을 섞어 보이게 한다.

### 결정

- Python FastAPI/OpenAPI backend distribution은 `kor-travel-map-api`다.
- Python import root는 `kortravelmap.api`다.
- backend 소스와 테스트, OpenAPI export script, `openapi.json`,
  `openapi.user.json`은 `packages/kor-travel-map-api/`에 둔다.
- backend runtime 설정 prefix는 `KOR_TRAVEL_MAP_API_*`다.
- admin frontend는 `kor-travel-map-admin` 이름을 유지하고
  `packages/kor-travel-map-admin/frontend/`에 둔다.
- admin frontend가 호출하는 backend base URL은 `NEXT_PUBLIC_KOR_TRAVEL_MAP_API`다.
- 고정 포트는 ADR-047 그대로 유지한다: API `12701`, admin UI `12705`, Dagster `12702`.
- OpenAPI 전체/admin spec과 user-facing subset spec의 기계 정본은 각각
  `packages/kor-travel-map-api/openapi.json`,
  `packages/kor-travel-map-api/openapi.user.json`이다.
- 구 `kortravelmap.admin`, `kor-travel-map-admin` Python backend install path,
  `KOR_TRAVEL_MAP_ADMIN_*` API 설정, `NEXT_PUBLIC_KOR_TRAVEL_MAP_ADMIN_API` 호환 shim은
  만들지 않는다(ADR-046 clean cut).

### 근거

- backend는 admin route만 담당하지 않는다. public/user-facing REST와 admin/ops/debug REST를
  같은 FastAPI app에서 제공한다.
- admin frontend는 UI 소비자일 뿐 backend Python package identity가 아니다.
- Docker/CI/OpenAPI drift gate가 API backend와 frontend build를 분리하면 변경 영향과
  실패 원인을 더 명확히 추적할 수 있다.

### 결과

- `uv pip install -e packages/kor-travel-map-api`가 backend 설치 명령이다.
- `uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port 12701`가 backend 실행 명령이다.
- `npm -w packages/kor-travel-map-admin/frontend ...`가 admin UI 실행/빌드 명령이다.
- Docker `api` service는 `packages/kor-travel-map-api`를 설치하고, `frontend` service는
  `packages/kor-travel-map-admin/frontend`만 빌드한다.
