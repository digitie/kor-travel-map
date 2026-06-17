# ADR-045: kor-travel-map은 Docker 독립 프로그램으로 운영하고 TripMate는 OpenAPI로 연동

- **상태**: accepted (2026-06-01)
- **날짜**: 2026-06-01
- **결정자**: 사용자
- **supersedes**: ADR-003의 TripMate 함수 직접 호출 운영 모델, ADR-035의 "debug-ui"
  범위 표현 일부

### 컨텍스트

초기 v2 설계는 `kor-travel-map`을 TripMate가 같은 Python process에서 import하는
하부 라이브러리로 정의했다. 그러나 admin 기능 범위가 feature 전체 운영, provider
강제 적재, 중복/결측 검토, offline upload, Dagster 기반 업데이트 큐까지 커지면서
다음 요구가 확정됐다.

- kor-travel-map은 TripMate와 별개로 Docker에서 실행되는 **독자 프로그램**이어야 한다.
- DB도 TripMate 공유 DB가 아니라 kor-travel-map이 소유하는 독립 PostgreSQL/PostGIS DB다.
- Dagster도 TripMate와 별개로 kor-travel-map 프로그램 안에 둔다.
- TripMate와 kor-travel-map 사이의 통신은 OpenAPI 기반 HTTP API로 한다.
- OpenAPI는 우선 admin UI를 기준으로 설계하고, TripMate 연동 시 필요한 사용자/서비스
  API를 보완·확장한다.
- Dagster는 feature 업데이트를 수행하는 내부 실행 엔진이며, OpenAPI로 즉시 실행
  또는 큐잉을 제어할 수 있어야 한다.

### 결정

1. **운영 단위**
   - kor-travel-map은 Docker Compose 또는 단일 배포 묶음으로 실행되는 독립 프로그램이다.
   - 논리 서비스는 `api`(FastAPI/OpenAPI), `frontend`(Next.js admin UI),
     `dagster`(feature update orchestration), `postgres`(독립 PostGIS DB),
     선택 `rustfs`(객체 저장소)로 나눈다.
   - `kor-travel-map-admin` 패키지는 구 `kor-travel-map-admin`에서 rename 완료된
     **kor-travel-map admin/API 프로그램**이다. 역할은 "debug UI"를 넘어 독립
     프로그램의 API/admin 표면을 제공한다(ADR-020 amendment, PR#148).

2. **TripMate 연동**
   - TripMate는 `kor-travel-map`을 직접 import하지 않는다.
   - TripMate는 kor-travel-map OpenAPI client를 생성해 HTTP로 feature 조회/상세/업데이트
     요청을 호출한다.
   - TripMate는 kor-travel-map DB에 직접 연결하지 않는다.
   - TripMate 도메인 테이블은 `feature_id`를 외부 참조 값으로 저장할 수 있지만 FK는
     TripMate DB 안에서 걸지 않는다.

3. **OpenAPI 우선순위**
   - 1차 OpenAPI는 admin UI가 쓰는 API를 기준으로 작성한다.
   - admin API는 `/admin/...`, `/ops/...`, `/features/...`, `/debug/...` prefix를
     사용한다.
   - TripMate 사용자/서비스 연동 API는 admin API를 재사용하되, 필요한 응답 경량화,
     공개 필드 제한, batch 조회, 캐시 헤더 등을 후속으로 추가한다.
   - OpenAPI schema drift gate는 계속 유지한다(ADR-031).

4. **독립 DB**
   - 운영 DB 이름 기본값은 `kor_travel_map`.
   - schema는 기존 `feature`, `provider_sync`, `ops`, `x_extension`을 유지한다.
   - 필요하면 Dagster metadata는 같은 PostgreSQL instance의 별도 DB
     `kor_travel_map_dagster` 또는 별도 schema로 둔다. 운영 단순성을 위해 Docker Compose
     기본값은 같은 Postgres container 안의 별도 DB를 권장한다.

5. **독립 Dagster**
   - Dagster asset/job/schedule은 TripMate가 아니라 kor-travel-map 프로그램 소유다.
   - provider 정기 적재, feature 업데이트, consistency check, dedup candidate refresh,
     offline upload load는 kor-travel-map Dagster가 실행한다.
   - admin API는 Dagster run을 직접 만들거나 `ops.import_jobs`에 queue item을 만들고,
     Dagster sensor/worker가 이를 claim해 실행한다.
   - 동일 provider/dataset/scope 또는 destructive job은 ADR-039 advisory lock을
     적용한다.

6. **OpenAPI 기반 feature update 요청**
   - admin UI 또는 TripMate는 OpenAPI로 feature update request를 만들 수 있다.
   - 지원 scope:
     - `feature_ids`: 특정 feature_id 목록 업데이트.
     - `center_radius`: 특정 좌표 중심 반경 `n` km 안의 feature 업데이트.
     - `sigungu_by_radius`: 특정 좌표 중심 반경 `n` km와 교차하거나 그 안에 있는
       시군구를 계산하고, 해당 시군구의 feature를 업데이트.
     - `bbox`: bbox 안의 feature 업데이트.
     - `provider_dataset`: 특정 provider/dataset/sync_scope 업데이트.
   - 실행 방식:
     - `run_mode="queued"`: queue에 등록 후 worker/Dagster가 순서대로 실행.
     - `run_mode="now"`: 가능한 즉시 실행. 단 lock이 잡혀 있으면 409 또는 queued
       fallback 정책을 명확히 반환.
     - `dry_run=true`: 대상 feature/provider count와 예상 작업만 계산하고 실행하지 않음.

7. **Frontend stack**
   - admin frontend는 Next.js, React, TypeScript, TanStack Query, Zustand, Zod,
     React Hook Form, shadcn/ui, maplibre-vworld-js, `@kor-travel-map/map-marker-react`를
     표준 stack으로 쓴다.
   - 서버 상태는 TanStack Query, 클라이언트 UI 상태는 Zustand, form 검증은
     React Hook Form + Zod resolver, 공통 UI primitive는 shadcn/ui를 사용한다.
   - frontend 작업 후에는 React Doctor를 실행하고 결과를 검토·개선해야 한다.

### 근거

- admin/운영 기능이 커지면 TripMate process 안에 라이브러리로 끼워 넣는 방식은
  배포·장애 격리·DB 소유권이 흐려진다.
- 독립 DB와 OpenAPI는 TripMate와 kor-travel-map의 데이터/운영 책임을 명확히 나눈다.
- Dagster가 kor-travel-map 내부에 있으면 provider rate limit, 정합성 검사, offline
  upload load, feature update queue를 한 곳에서 제어할 수 있다.
- OpenAPI를 admin UI 기준으로 먼저 만들면 실제 운영 화면이 API 계약을 계속 검증한다.
  TripMate 연동 API는 이후 필요한 공개 범위에 맞춰 얇게 확장하면 된다.

### 결과 (긍정)

- kor-travel-map 배포, DB migration, provider key, Dagster schedule을 TripMate와 독립적으로
  운영할 수 있다.
- TripMate는 HTTP/OpenAPI client만 알면 되므로 언어·프로세스·DB 경계가 명확하다.
- admin UI와 TripMate가 같은 OpenAPI 기반 계약을 공유하므로 schema drift를 줄인다.
- 지리 범위 기반 업데이트를 queue로 제어할 수 있어 운영자가 문제 구역만 즉시
  재적재할 수 있다.

### 결과 (부정)

- HTTP boundary가 생겨 직렬화/네트워크 비용과 장애 지점이 늘어난다.
- OpenAPI versioning, client generation, backward compatibility 관리가 필요하다.
- 기존 문서의 "TripMate 함수 직접 호출/공유 DB" 표현을 ADR-045 기준으로 정리해야
  한다.
- Docker Compose, Dagster metadata DB, migration 순서까지 운영해야 한다.

### 후속

- `docs/architecture/architecture.md` 큰 그림을 독립 프로그램 모델로 갱신.
- `docs/architecture/debug-ui-package.md`와 `docs/debug-ui-admin-workflows.md`에 standalone,
  OpenAPI, frontend stack, React Doctor, Dagster queue 제어 사양 반영.
- `docs/architecture/dagster-boundary.md`를 TripMate-owned Dagster에서 kor-travel-map-owned Dagster로
  갱신.
- `docs/tripmate-integration.md`는 OpenAPI 연동 문서로 재작성 또는 supersede banner
  추가.
- Docker Compose 운영 문서와 admin-first OpenAPI 계약 문서 추가.
