# ADR — Architecture Decision Records

`kor-travel-map`의 누적 ADR. 파일당 1개(`NNN-<slug>.md`)로 둔다. **다음 후보 = ADR-060.**

- ADR은 **프로그램 핵심 구조**(의존 계층·데이터/식별 모델·패키지/서비스 구조·REST 계약·
  운영 모델) 결정만 둔다. provider/ETL·도메인 taxonomy·알고리즘·process·운영 결정은 해당 topic
  문서로 이관했다 — 아래 표의 "→ 이관" 항목(원 맥락은 이관 문서 + git history 보존).
- 순수 개발 규칙(금지·프로세스)은 ADR이 아니라 [`SKILL.md` §4](../../SKILL.md)에 둔다 —
  아래 표의 "→ 개발 규칙" 항목.
- 결정이 뒤집힐 때도 핵심 구조 ADR의 이전 기록은 지우지 않고 `superseded by ADR-XXX`로 표시한다.
- 각 ADR은 PR과 함께 커밋되어 코드/문서/결정이 동기된다.

## 목록

| ADR | 제목 | 위치 |
|-----|------|------|
| ADR-001 | v1은 `v1` 브랜치 보존, main은 orphan v2로 재시작 | [001-v1-branch-preserve-main-orphan-v2.md](001-v1-branch-preserve-main-orphan-v2.md) |
| ADR-002 | 의존 계층 강제 + async-only API | [002-dependency-layer-enforcement-async-only.md](002-dependency-layer-enforcement-async-only.md) |
| ADR-003 | ~~(삭제됨)~~ | 삭제 — ADR-045로 폐기된 소비자 함수-호출 연동 모델 |
| ADR-004 | ORM은 매핑만, 쿼리는 raw SQL `text()` | [004-orm-mapping-only-raw-sql-text.md](004-orm-mapping-only-raw-sql-text.md) |
| ADR-005 | 디버그 REST API는 인증 없음, 내부망 전용 | [005-debug-rest-api-no-auth-internal-only.md](005-debug-rest-api-no-auth-internal-only.md) |
| ADR-006 | provider adapter/wrapper 신규 생성 금지 | → 개발 규칙 ([SKILL.md §4](../../SKILL.md)) |
| ADR-007 | 의존 스택 — Postgres + PostGIS + SQLAlchemy 2 async + GeoAlchemy2 + GeoPandas | [007-dependency-stack-postgres-postgis-sqlalchemy.md](007-dependency-stack-postgres-postgis-sqlalchemy.md) |
| ADR-008 | PostGIS extension은 `x_extension` schema에 격리 | [008-postgis-extension-x-extension-schema.md](008-postgis-extension-x-extension-schema.md) |
| ADR-009 | `feature_id` 결정적 생성 (`make_feature_id`) | [009-deterministic-feature-id.md](009-deterministic-feature-id.md) |
| ADR-010 | weather forecast_style + timeline_bucket 두 축 분리 | → 이관 [etl/weather-feature-normalization.md](../etl/weather-feature-normalization.md) |
| ADR-011 | 작업 큐는 `import_jobs` 영속화 + advisory lock + SKIP LOCKED | [011-import-jobs-advisory-lock-skip-locked.md](011-import-jobs-advisory-lock-skip-locked.md) |
| ADR-012 | 공간 쿼리 ST_Transform 1회·인덱스 컬럼 | → 개발 규칙 ([SKILL.md §4](../../SKILL.md)) |
| ADR-013 | bulk insert는 psycopg.copy_* 우선, 안전 마진 30k 파라미터 | → 이관 [architecture/performance.md](../architecture/performance.md) |
| ADR-014 | 테스트 4단계 + Coverage 목표 | → 이관 [test-strategy.md](../test-strategy.md) |
| ADR-015 | 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap | [015-object-store-s3-compatible-rustfs-first.md](015-object-store-s3-compatible-rustfs-first.md) |
| ADR-016 | Record linkage 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65 | → 이관 [architecture/data-model.md](../architecture/data-model.md) |
| ADR-017 | kind별 보관 정책 (place/route/area 무기한, event +20y, notice +1y 등) | → 이관 [architecture/data-model.md](../architecture/data-model.md) |
| ADR-018 | `Feature.detail` 자유 dict 금지 (`DETAIL_MODELS` 분기 강제) | [018-feature-detail-no-free-dict-detail-models.md](018-feature-detail-no-free-dict-detail-models.md) |
| ADR-019 | KST aware datetime만 허용 | → 개발 규칙 ([SKILL.md §4](../../SKILL.md)) |
| ADR-020 | 디버그/admin UI는 별도 Python 패키지 (`kor-travel-map-admin`) | [020-debug-admin-ui-separate-python-package.md](020-debug-admin-ui-separate-python-package.md) |
| ADR-021 | main 직접 push 금지(PR 필수) | → 개발 규칙 ([SKILL.md §4](../../SKILL.md)) |
| ADR-022 | `krtour` implicit namespace + Python import path `kortravelmap` | [022-krtour-namespace-import-path-kortravelmap.md](022-krtour-namespace-import-path-kortravelmap.md) |
| ADR-023 | kraddr-base category 모듈을 kortravelmap.category로 이전 | → 이관 [architecture/architecture.md](../architecture/architecture.md) |
| ADR-024 | canonical provider name python-mois-api로 정정 | → 이관 [architecture/architecture.md](../architecture/architecture.md) |
| ADR-025 | 디버그 UI frontend는 maplibre-vworld-js 채택 | → 이관 [architecture/debug-ui-package.md](../architecture/debug-ui-package.md) |
| ADR-026 | 본 레포 debug/admin UI를 maplibre-vworld로 통일 + category→maki 단일 매핑 | → 이관 [architecture/debug-ui-package.md](../architecture/debug-ui-package.md) |
| ADR-027 | forest 카테고리 확장 (대피소 PlaceCategory, hazard_zone area, 일반화된 notice_type) | → 이관 [architecture/category.md](../architecture/category.md) |
| ADR-028 | python-knps-api provider 라이브러리 등록 (+ keyless/file-only amendment + SHP/CSV 파싱 책임=knps-api) | → 이관 [etl/knps-feature-etl.md](../etl/knps-feature-etl.md) |
| ADR-029 | 공통 maki marker/category 매핑 npm 패키지 추출 (@kor-travel-map/map-marker-react) | → 이관 [architecture/debug-ui-package.md](../architecture/debug-ui-package.md) |
| ADR-030 | in-memory 캐시 금지(immutable 예외) | → 개발 규칙 ([SKILL.md §4](../../SKILL.md)) |
| ADR-031 | 디버그 패키지 OpenAPI export 정책 (첫 라우터부터 활성화) | → 이관 [architecture/rest-api.md](../architecture/rest-api.md) |
| ADR-032 | Coverage 단계적 상향 일정 (Sprint 1→5) | → 이관 [test-strategy.md](../test-strategy.md) |
| ADR-033 | feature_consistency_reports 단계적 도입 (F1~F3 → F4~F8 + Dagster 게이트) | → 이관 [architecture/data-model.md](../architecture/data-model.md) |
| ADR-034 | provider 9단계 구현 순서 — MOIS 마지막 군 | → 이관 [architecture/architecture.md](../architecture/architecture.md) |
| ADR-035 | 디버그/관리 REST API를 프로덕션에서도 admin/유지보수 UI로 운영 (코드 외부 인증, /admin·/ops·/debug prefix 분리) | → 이관 [deploy.md](../deploy.md) |
| ADR-036 | maplibre-vworld-js 라이브러리 분리 + 버전 핀(v0.1.3, Next.js 16) | → 이관 [architecture/debug-ui-package.md](../architecture/debug-ui-package.md) |
| ADR-037 | 디버그/관리 UI frontend state 관리 — TanStack Query + Zustand | [037-admin-ui-frontend-state-tanstack-query-zustand.md](037-admin-ui-frontend-state-tanstack-query-zustand.md) |
| ADR-038 | GitHub Actions CI/CD 재활성화 — 머지 게이트 다시 켬 | → 이관 [agent-guide.md](../agent-guide.md) |
| ADR-039 | CLI 중복 실행 mutex | → 개발 규칙 ([SKILL.md §4](../../SKILL.md)) |
| ADR-040 | Backup/Restore + 핫스왑 UI | → 이관 [backup-restore.md](../backup-restore.md) |
| ADR-041 | python-kraddr-base 코드 흡수 + 폐기 (PlaceCoordinate 제외) | → 이관 [architecture/architecture.md](../architecture/architecture.md) |
| ADR-042 | 전국관광지정보/전국문화축제 표준데이터를 place/event 1차 source로 채택 (datagokr 경유) | → 이관 [etl/standard-data-feature-etl.md](../etl/standard-data-feature-etl.md) |
| ADR-043 | @kor-travel-map/map-marker-react npm 게시 보류 — 모노레포 내부 share로만 | → 이관 [architecture/debug-ui-package.md](../architecture/debug-ui-package.md) |
| ADR-044 | 관련 라이브러리 로컬(F:\\dev\\) 우선 조회 + 데이터 정합성 책임은 각 라이브러리 | → 이관 [agent-guide.md](../agent-guide.md) |
| ADR-045 | kor-travel-map은 Docker 독립 프로그램으로 운영하고 외부 경계는 OpenAPI | [045-docker-standalone-program-tripmate-openapi.md](045-docker-standalone-program-tripmate-openapi.md) |
| ADR-046 | 정본 방향 전환은 호환 shim 없이 하고 주소는 kor-travel-geo REST v2로 통일 | [046-no-compat-shim-geo-rest-v2.md](046-no-compat-shim-geo-rest-v2.md) |
| ADR-047 | kor-travel-map 로컬 포트를 API 12701, admin UI 12705, Dagster 12702로 고정 (+.env 키 매핑/stop-fixed-ports) | → 이관 [deploy.md](../deploy.md) |
| ADR-048 | REST API versioning을 admin/ops까지 확장하고 envelope·pagination·parameter·response 정합성 표준을 고정한다 (T-214/T-215 위에 보강) | [048-rest-api-versioning-envelope-pagination.md](048-rest-api-versioning-envelope-pagination.md) |
| ADR-049 | kor-travel-concierge-youtube export를 provider로 pull·정규화 | → 이관 [etl/concierge-feature-etl.md](../etl/concierge-feature-etl.md) |
| ADR-050 | concierge provider export 철회 라이프사이클을 inactive 전환으로 처리 | → 이관 [etl/concierge-feature-etl.md](../etl/concierge-feature-etl.md) |
| ADR-051 | 외부 사용자 feature 제안 반영은 기존 admin feature change API 재사용 | → 이관 [architecture/rest-api.md](../architecture/rest-api.md) |
| ADR-052 | ~~(삭제됨)~~ | 삭제 — RustFS 인프라 소유를 외부 오케스트레이터로 위임(형제 인프라 R&R) |
| ADR-053 | kor-travel-concierge provider identity clean cut | → 이관 [etl/concierge-feature-etl.md](../etl/concierge-feature-etl.md) |
| ADR-054 | 배포명은 `kor-travel-map`, Python import root는 `kortravelmap`로 clean cut한다 | [054-package-identity-rename.md](054-package-identity-rename.md) |
| ADR-055 | REST API Python backend와 admin frontend를 별도 패키지로 분리한다 | [055-split-api-backend-admin-frontend-packages.md](055-split-api-backend-admin-frontend-packages.md) |
| ADR-056 | N150/Odroid 병행 multi-platform Docker build (streaming replication 제외) | → 이관 [deploy.md](../deploy.md) |
| ADR-057 | kor-travel-concierge feature_id를 안정 candidate.id에 고정 (bjd/category 식별자 분리) | → 이관 [etl/feature-id-determinism.md](../etl/feature-id-determinism.md) |
| ADR-058 | geocoder-의존 provider feature_id 결정성을 geocoder 필수화(F-01, re-key 없음)로 보장 | → 이관 [etl/feature-id-determinism.md](../etl/feature-id-determinism.md) |
| ADR-059 | 벤더링된 agent/skill 설정의 언어·context-discovery 예외 정책 | → 이관 [agent-guide.md](../agent-guide.md) |

## 새 ADR 작성 규약

> 새 ADR을 추가할 때는 위 포맷을 따른다:
>
> - 번호: ADR-NNN (연번)
> - 상태: proposed | accepted | superseded by ADR-XXX
> - 날짜: YYYY-MM-DD
> - 결정자: <agent | human> 또는 둘 모두
> - 본문: 컨텍스트 / 결정 / 근거 / 결과(긍정) / 결과(부정) / 후속
>
> 기존 ADR을 뒤집을 때는 새 ADR을 추가하고, 옛 ADR의 상태를 `superseded by
> ADR-XXX`로 표시한다 — 기존 본문은 지우지 않는다.
