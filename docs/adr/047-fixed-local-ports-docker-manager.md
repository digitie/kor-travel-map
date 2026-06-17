# ADR-047: kor-travel-map 로컬 포트는 docker-manager 기준 API 12701, admin UI 12705, Dagster 12702로 고정

- **상태**: accepted
- **날짜**: 2026-06-02
- **개정**: 2026-06-12 — Postgres host `5432`, RustFS S3 API `12101`,
  kor-travel-geo API `12201`/Web UI `12205`, kor-travel-map API `12301`, 관리 보조(Dagster)
  `12302`, Web UI `12305`로 재고정.
- **개정**: 2026-06-13 — PC 개발 host `5432`는 공유 PostGIS 서버 인스턴스로 고정하고,
  kor-travel-map standalone local Postgres publish 기본값은 `15432`로 분리한다.
  공유 DB만 쓰는 Docker 기동은 `KOR_TRAVEL_MAP_DB_EXTERNAL=true`로 둔다.
- **개정**: 2026-06-13 — `kor-travel-docker-manager`가 소유한 공유 로컬 인프라와
  관측 스택을 기준으로 kor-travel-map API/admin UI/Dagster 포트를
  `12701`/`12705`/`12702`로 재고정한다. kor-travel-geo API/Web UI는
  `12501`/`12505`, 공유 PostGIS host는 `5432`, RustFS S3/console은
  `12101`/`12105`, 관측 스택은 Grafana `12205`·cAdvisor `12301`·Prometheus
  `12401`을 따른다.
- **결정자**: 사용자
- **관련**: ADR-020, ADR-035, ADR-045

### 컨텍스트

ADR-045 이후 kor-travel-map은 Docker 독립 프로그램 + 독립 DB/Dagster + admin UI를 함께
운영한다. 이전 문서와 스크립트에는 debug API `8087`, frontend `8610`, Dagster 기본
포트 같은 값이 섞여 있었고, Windows/WSL 하이브리드 검증에서 stale 프로세스가 같은
포트를 점유하면 브라우저가 다른 서버를 보는 문제가 반복됐다.

사용자는 API, 웹, Dagster 포트를 항상 일정하게 유지하고, 해당 포트를 점유한
프로세스가 있으면 종료 후 다시 올리라고 지시했다.

### 결정

1. kor-travel-map의 로컬/개발/compose 기본 포트는 docker-manager 포트 정책에 맞춰
   다음으로 고정한다.
   - API(FastAPI `kor-travel-map-api`): `12701`
   - 추가 관리 포트(Dagster): `12702`
   - admin UI(Next.js): `12705`
   - Postgres host: `5432`(container도 `5432`)
   - RustFS S3 API: `12101`(console은 `12105`, RustFS container 내부 console은 `9001`)
   - kor-travel-geo API/Web UI: `12501` / `12505`
   - 관측 스택(docker-manager): Grafana `12205`, cAdvisor `12301`, Prometheus `12401`
2. `scripts/stop-fixed-ports.sh`는 기본으로 `12701`, `12705`, `12702` listener를 찾아
   종료한다. 로컬 stack과 Docker stack 기동 스크립트는 먼저 이 스크립트를 실행한다.
3. `.env`의 기존 provider service key 이름은 `scripts/load-env.sh`와
   `docker-compose.yml`에서 `KOR_TRAVEL_MAP_API_*`/`NEXT_PUBLIC_*` 환경변수로 매핑한다.
   평문 키는 git에 커밋하지 않는다.
4. Docker compose 1차 서비스는 `postgres`, `api`, `frontend`, `dagster`다. API
   컨테이너는 기동 전 `alembic upgrade head`를 실행한다. Dagster metadata DB 분리,
   daemon/schedule 운영, RustFS/backup 묶음은 후속 T-209b/T-209e에서 확장한다.

### 근거

- 포트를 고정해야 TripMate OpenAPI 연동, Windows Playwright, WSL 서버, Docker compose
  검증이 같은 주소를 바라본다.
- 점유 프로세스를 명시 종료한 뒤 기동해야 stale Next.js/uvicorn/Dagster 프로세스가
  검증 결과를 오염시키지 않는다.
- `.env`는 provider repo별 키 이름이 이미 다르므로, 실행 스크립트가 표준 env 이름으로
  한 번 매핑하는 편이 운영 실수를 줄인다.

### 결과 (긍정)

- 문서, 설정, 스크립트, Docker compose가 같은 포트 표준을 사용한다.
- `npm run admin:stack`, `npm run docker:up`, `npm run ports:stop`으로 같은 규칙을
  반복 실행할 수 있다.
- Docker image build와 local dev stack이 같은 `.env` 키 매핑을 공유한다.

### 결과 (부정)

- 기존 `8087`/`8610`을 직접 쓰던 로컬 북마크와 스크립트는 수정해야 한다.
- `docker compose config`나 compose 로그는 환경변수를 출력할 수 있으므로, 서비스 키가
  들어간 출력은 PR/문서에 붙이지 않는다.

### 후속

- admin UI Dagster 관측/관리 화면 1차는 `/admin/dagster` +
  `GET /ops/dagster/summary`로 보강했다. feature update queue와 sensor/worker 연결은
  별도 후속으로 둔다.
- Dagster metadata DB 분리, daemon/schedule/sensor 운영, RustFS/backup compose 확장은
  T-209b/T-209e에서 이어간다.
