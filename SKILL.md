# SKILL — kor-travel-map 에이전트 매뉴얼

> 이 파일은 당신(AI 에이전트)이 작업을 시작하기 전 반드시 읽어야 한다.
> 1회만 읽으면 30분 이상의 디버깅을 줄일 수 있다.

## 1. 정체성

이 저장소(GitHub 이름 `kor-travel-map`, Python 패키지 `kortravelmap` — ADR-022)는
**kor-travel-map 독립 프로그램 + 내부 Python 라이브러리**다. 한국 공공 API
(`python-*-api`)의 결과를 단일 `Feature` 계약으로 정규화하고 독립 PostgreSQL +
PostGIS DB에 저장한다.

ADR-045 이후 PinVi ↔ kor-travel-map은 **OpenAPI 기반 HTTP**로 연결된다. PinVi는
kor-travel-map DB에 직접 접근하지 않고 `kor-travel-map`을 운영 코드에서 직접 import하지
않는다. REST/OpenAPI backend는 **별도 Python 패키지** `kor-travel-map-api`
(`packages/kor-travel-map-api/`, ADR-055), admin UI는
`packages/kor-travel-map-admin/frontend/`로 분리되어 있고 인증 없이 내부망에서 사용한다.

외부 앱 POI 주변 캐시 갱신은 `external_system + target_key + 좌표 + radius_km`로
등록한 cache target을 기준으로 한다. target key가 삭제되면 targeted update에서
제외하고, 여러 target 반경의 교집합 feature/provider scope는 한 번만 갱신한다.
자세한 사양은 `docs/poi-cache-update-targets.md`.

v1 구현은 `v1` 브랜치 보존, main은 v2로 재시작(ADR-001). v1 reference는 루트
`kor-travel-map-spec.docx`(약 80쪽, 새 코드의 입력 아닌 참고용).

식별자(import root `kortravelmap` / DB `kor_travel_map` / CLI `ktmctl` /
env prefix `KOR_TRAVEL_MAP_*` 등) 정본 표 → `AGENTS.md` §식별자.

### 개발 환경 (Linux/WSL)

정본 → `docs/dev-environment.md` + `AGENTS.md` §"개발 환경 정책 (Linux/WSL)".

### 에이전트 worktree + codegraph

worktree 배치·`codegraph init/sync`·MCP 등록·수정 전 영향도 평가 절차 정본 →
`docs/codegraph-worktree.md` + `AGENTS.md` §"에이전트 worktree + codegraph".

## 2. 빠른 시작

부트스트랩 절차 정본 → `README.md` §빠른 시작. 최소 흐름: WSL `/mnt/f/dev/...`
에서 `uv venv && uv pip install -e ".[dev,geo,providers]"` → `docker compose up
-d postgres` (`postgis/postgis:16-3.5`) → `alembic upgrade head` → `pytest -q`.

## 3. 디렉토리 지도

디렉토리 tree 정본 → `README.md` §디렉토리. 메인 패키지 의존 방향:
**category → dto → core → infra → geocoding → providers → client → cli** 한 방향
(import-linter가 CI 강제). `kortravelmap.api`는 별도 distribution이며 메인
라이브러리 계층 계약 밖(ADR-055).

## 4. 절대 하지 말 것 (DO NOT)

1. **의존 방향 역행 금지** — 위 계층을 거스르는 import 금지. import-linter가
   CI에서 실패시킴.
2. **동기 인터페이스 추가 금지** — `AsyncKorTravelMapClient`만 둔다. 동기가 필요하면
   호출자가 `asyncio.run`으로 감싼다 (ADR-002).
3. **`pg_trgm.similarity_threshold` 전역 변경 금지** — 항상 트랜잭션 내부 `SET LOCAL`.
4. **ORM에 비즈니스 로직 금지** — `infra/models.py`는 매핑만. 쿼리는
   `infra/*_repo.py`의 raw SQL `sqlalchemy.text()` (ADR-004).
5. **좌표 순서 혼동 금지** — 모든 외부 인터페이스는 `(lon, lat)`. PostGIS도
   `ST_MakePoint(lon, lat)`. DTO `Coordinate(lat=..., lon=...)`도 alias만 다를 뿐
   API 입력/출력은 `(lon, lat)` 순서로 직렬화.
6. **카테고리/마커 매핑 하드코드 금지** — `category_mappings` DB 테이블 또는
   `Settings`에서 읽음. 라이브러리 default 상수(`KOR_TRAVEL_MAP_CATEGORY_DEFAULTS`)는
   허용하되 DB override가 우선.
7. **응답 셰입 임의 변경 금지** — 메인 라이브러리 DTO는 `data/meta/error` 같은 HTTP
   래핑 키를 갖지 않는다. 래핑은 OpenAPI backend(`kor-travel-map-api`) 책임.
8. **외부 API 키 평문 커밋 금지** — 모두 `SecretStr`. `.env`는 권한 600 또는
   systemd `EnvironmentFile`/vault.
9. **provider adapter/wrapper 신규 생성 금지** — public client 직접 사용.
   부족하면 provider 라이브러리에서 안정화. `KmaWrapper`/`OpiNetGateway` 같은
   클래스 금지. (구 ADR-006 → 본 §4 룰로 통합.)
10. **`feature_id` raw string concat 금지** — 항상 `make_feature_id(...)`.
11. **공간 쿼리 술어에서 좌표 형변환 금지** — 입력 좌표는 CTE/파라미터로
    **한 번만** `ST_Transform`해서 상수로 굳히고, 술어는 `ST_DWithin(t.coord_5179,
    p.geom, :radius_m)`처럼 인덱스 있는 컬럼을 그대로 둔다. `ST_Transform`이 술어
    안에 들어가면 GIST 인덱스를 못 타고 매 행 변환이 돌아간다. **반경 검색은
    `coord_5179`(meter) 기준**. (구 ADR-012 → 본 §4 룰로 통합.)
12. **SQLAlchemy bulk `insert().values(rows)` 파라미터 폭주 금지** — PostgreSQL
    프로토콜은 한 쿼리당 최대 65,535개 파라미터. row × column이 ~30,000 이상이면
    `psycopg.copy_*` 또는 `gdal.VectorTranslate(... PG_USE_COPY=YES)`로 전환.
    안전 마진은 한도의 절반(30k) 권장.
13. **작업 큐 상태를 in-memory만 신뢰 금지** — 적재 작업은 `import_jobs` 테이블
    영속화. lifespan startup에서 `state IN ('queued','running')` 잔존 행을
    `failed`로 마크. `pg_try_advisory_lock` + `FOR UPDATE SKIP LOCKED`로 다중
    워커 안전.
14. **디버그 API/UI 패키지에 인증 추가 금지** — 내부망 전제. 외부 노출이
    필요해지면 네트워크 계층(SSO 게이트웨이 / IP allowlist / Cloudflare
    Tunnel)에서 보호.
15. **메인 라이브러리(`kortravelmap`)에 FastAPI/Uvicorn import 금지** — ADR-020.
    HTTP 서버 코드는 `packages/kor-travel-map-api/`에만 둔다.
16. **데이터/원천 파일을 git에 커밋 금지** — `data/`는 `.gitignore`. NTFS 보관.
17. **시간 직접 사용 금지** — 모든 datetime은 KST aware (Asia/Seoul). naive
    datetime을 DTO에 넣지 않는다. `kst_now()` 사용.
18. **`Feature.detail`을 자유 dict로 사용 금지** — 항상 `PlaceDetail`/`EventDetail`
    등 Pydantic 모델 인스턴스 → `.model_dump()`. 자유 dict 우회 path 금지.
19. **main에 직접 push 금지** — 모든 변경은 feature branch + PR (구 ADR-021 →
    본 §4 룰로 통합). `git push origin main` 절대 금지. 브랜치 명명: `feat/<topic>` /
    `fix/<topic>` / `chore/<topic>` / `docs/<topic>` / `refactor/<topic>` /
    `adr/<short>`. PR 작성: `gh pr create --title ... --body ...`.
20. **`kor_travel_map` flat import 금지** — 항상 `import kortravelmap as ktm`
    또는 `from kortravelmap import ...` (ADR-054). `src/kor_travel_map/` 디렉토리
    만들지 말 것.
21. **`src/krtour/` namespace 부활 금지** — T-226 이후 `kortravelmap`이 유일한
    import root다. `src/kortravelmap/__init__.py`는 public root로 유지한다.
22. **PinVi 도메인 모델을 본 라이브러리에 정의 금지** — 사용자/여행계획/POI는
    PinVi.
23. **GitHub Actions CI green 통과 전 머지 금지** — ADR-038 (2026-05-27
    재활성화). `.github/workflows/{ci,lint,openapi}.yml` 모두 통과 + 1 review.
    "쓰지마"였던 2026-05-26 시기 패턴은 폐기.
24. **CLI 중복 실행이 위험한 명령에 mutex 없이 머지 금지** — 구 ADR-039 → 본 §4
    룰로 통합. `import`/`dedup-merge`/`backup`/`restore`/`alembic upgrade`는
    PostgreSQL `pg_try_advisory_lock` 기반 mutex 박음. read-only / `--dry-run` 예외.
25. **`@kor-travel-map/map-marker-react` npm registry 게시 금지** — ADR-043. 모노레포
    내부 git share만. `packages/map-marker-react/package.json` `"private": true`.
26. **kraddr-base의 `PlaceCoordinate` import 금지** — ADR-041. 좌표 DTO는
    `kortravelmap.dto.Coordinate` 단일 source. kraddr-base 흡수 작업에서 명시적
    제외 대상.
27. **codegraph 영향도 평가 없이 핵심 컴포넌트 수정 금지** — `Feature` DTO /
    `make_feature_id` / provider 변환 함수 / `core/scoring.py` / `infra/models.py`
    수정 전 `codegraph_explore`(또는 CLI `codegraph callers`/`impact`/`callees`)로
    영향도를 먼저 평가한다. 신규 파일만 추가하고 기존 심볼 시그니처가 그대로면
    생략 가능. 절차 정본 → `docs/codegraph-worktree.md` §7.

## 5. 자주 묻는 작업

| 작업 | 시작 파일 |
|------|-----------|
| 새 provider 추가 | `dto/<provider>.py` → `core/<provider>.py` → `infra/<entity>_repo.py` → `providers/<provider>.py` → `docs/etl/<provider>-feature-etl.md` + ADR |
| 새 raw SQL 쿼리 튜닝 | `infra/*_repo.py`의 `_SQL` 상수. EXPLAIN은 통합 테스트에서 검증 |
| 새 detail 필드 추가 | `dto/<detail>.py` Pydantic 모델 → DDL 컬럼/JSONB key → ADR |
| 새 에러 코드 추가 | `core/exceptions.py` + (디버그 API라면) `api/responses.py` 매핑 |
| 외부 API 호출 (provider) | `httpx.AsyncClient` + `tenacity` 재시도. 키는 `Settings`에서 `SecretStr`로. 호출은 provider 라이브러리에 맡김 |
| 인덱스 변경 | Alembic migration + EXPLAIN 통합 테스트 + ADR + `docs/architecture/performance.md` 갱신 |

## 6. 도메인 어휘

| 약어 | 의미 |
|------|------|
| Feature | 통합 지도 객체 (place/event/notice/price/weather/route/area 7 kind) |
| feature_id | 결정적 PK. 포맷 `f_{bjd_code}_{kind[0]}_{sha1(input)[:16]}` |
| BJD_CD | 법정동코드 10자리 (시도2 + 시군구3 + 읍면동3 + 리2) |
| SourceRecord | provider 원천 row (raw_data + payload_hash 보존) |
| SourceLink | Feature ↔ SourceRecord 연결 + source_role |
| source_role | base_address / base_coordinate / primary / enrichment / correction / duplicate_candidate / media / weather_context |
| dataset_key | provider 내 데이터셋 식별자 (예: `search_list`, `gis_spca`, `visitkorea_festival_events`) |
| ProviderSyncState | provider별 증분 sync cursor 상태 (PK provider+dataset_key+sync_scope) |
| dedup_review_queue | Record Linkage 임계값 0.65~0.85 수동 검토 큐 |
| import_jobs | 적재 작업 상태 영속 테이블 (lifespan recovery 대상) |
| WeatherValue | feature 시계열 날씨 값 (forecast_style + timeline_bucket 분리) |
| forecast_style | nowcast / ultra_short / short / mid / observed / index / advisory |
| timeline_bucket | KMA식 조회 축 ultra_short / short / mid (unique key에는 포함 X) |
| PricePoint / PriceValue | 가격 지점 (메타) + 시계열 값 |
| FeatureFile | 1:N 객체 저장소 메타데이터 (RustFS 등 S3 호환) |
| coord_5179 | EPSG:5179 (meter) 좌표 컬럼. 반경 검색은 항상 이 컬럼에 적용 |
| coord (EPSG:4326) | WGS84 좌표 컬럼. 응답 직렬화 전용 |

## 7. 작업 후 체크리스트

정본 → `AGENTS.md` §작업 후 체크리스트 (`pytest -q`/`ruff`/`mypy --strict`/
`lint-imports` + `docs/journal.md`·`docs/resume.md` + 해당 시 ADR/CHANGELOG/
OpenAPI/frontend `npm` 게이트).

## 8. 첫 5분 진입 프로토콜

읽기 순서 정본 → `CLAUDE.md` §3.

## 9. 코드 작성 단계

진척/스프린트 상태·"다음 한 작업"의 단일 정본 → `docs/resume.md` + 백로그
`docs/tasks.md`(완료 아카이브 `docs/tasks-done.md`). 이 문서에는 자주 바뀌는
PR 번호/완료여부를 박지 않는다.
