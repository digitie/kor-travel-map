# SKILL — python-krtour-map 에이전트 매뉴얼

> 이 파일은 당신(AI 에이전트)이 작업을 시작하기 전 반드시 읽어야 한다.
> 1회만 읽으면 30분 이상의 디버깅을 줄일 수 있다.

## 1. 정체성

이 저장소(GitHub 이름 `python-krtour-map`, Python 패키지 `krtour.map` — ADR-022)는
**TripMate의 지도 데이터 정규화·저장 하부 라이브러리**다. 한국 공공 API
(`python-*-api`)의 결과를 단일 `Feature` 계약으로 정규화하고 PostgreSQL + PostGIS에
저장한다.

TripMate ↔ `python-krtour-map`은 **함수 직접 호출**로 연결된다. 디버그 REST/UI는
**별도 패키지** `krtour-map-debug-ui` (`packages/krtour-map-debug-ui/`, ADR-020)로
분리되어 있고 인증 없이 내부망에서만 사용한다.

이전(v1) 구현은 `v1` 브랜치에 보존되어 있다. master(main)는 v2 사양으로 처음부터
다시 구현한다(ADR-001).

### 식별자 매핑

| 항목 | 값 |
|------|----|
| GitHub 저장소 | `python-krtour-map` |
| PyPI distribution | `python-krtour-map` |
| Python import (메인) | `from krtour.map import ...` (ADR-022) |
| Python import (디버그 UI) | `from krtour.map_debug_ui import ...` |
| CLI 명령 (있다면) | `krtour-map` |
| 환경변수 prefix | `KRTOUR_MAP_*` |
| PostgreSQL DB 이름 (개발) | `krtour_map` |
| Postgres schema | `feature`, `provider_sync`, `ops`, `x_extension` |
| 디버그 UI 패키지 | `krtour-map-debug-ui` (별도 Python 패키지, `packages/krtour-map-debug-ui/`, ADR-020) |
| Category 모듈 | `krtour.map.category` (구 `kraddr.base.categories`에서 이전, ADR-023) |

### 개발 환경 (PC, WSL)

- **코드/가상환경/git**: WSL ext4 (`~/dev/python-krtour-map/`). NTFS 마운트에서
  직접 작업하지 않는다.
- **데이터(`data/`)**: NTFS의 프로젝트 디렉토리 아래 (예:
  `/mnt/f/dev/python-krtour-map/data/`). ext4에는 심볼릭 링크
  (`ln -s /mnt/f/dev/python-krtour-map/data data`).
- **테스트**: 단위 테스트 픽스처는 소량으로 ext4. 통합/e2e는 NTFS `data/` reference.
- **카피 정책**: 작업이 완료되면 ext4 → NTFS로 rsync. Git source of truth는 ext4.

## 2. 빠른 시작 (코드 작성 단계 이후)

```bash
cd ~/dev/python-krtour-map                            # WSL ext4
sudo apt install -y libgdal-dev gdal-bin              # GeoPandas/loaders용
uv venv && uv pip install -e ".[dev,api,providers]"
uv pip install "gdal==$(gdal-config --version)"
cp .env.example .env && $EDITOR .env                  # KRTOUR_MAP_PG_DSN 채우기
ln -s /mnt/f/dev/python-krtour-map/data data          # NTFS data 참조
docker compose up -d postgres                         # postgis/postgis:16-3.5
alembic upgrade head
python -m pytest -q
```

현 단계(v2 설계)는 위 명령이 의미 있는 산출물을 만들지 않는다. 코드 작성 요청이
들어오면 위 절차로 부트스트랩한다.

## 3. 디렉토리 지도 (계획)

```
src/krtour/                        ← PEP 420 implicit namespace (NO __init__.py, ADR-022)
  map/                             ← 메인 패키지 (FastAPI 의존 없음)
    __init__.py
    category/  — kraddr-base에서 이전된 PlaceCategory(Code)/maki icon (ADR-023)
    dto/       — pydantic v2 입력/출력 (DB·FastAPI 의존 없음)
    core/      — 비즈니스 로직 (Protocol에만 의존)
    infra/     — DB 어댑터 (SQLAlchemy 2 async, raw SQL, Alembic 동반)
    providers/ — provider별 raw → DTO 변환 (wrapper 신규 생성 금지)
    client.py  — AsyncKrtourMapClient (라이브러리 진입점)
    cli/       — typer CLI (옵션)

packages/krtour-map-debug-ui/      ← 별도 Python 패키지 (ADR-020)
  pyproject.toml
  src/krtour/                      ← 같은 namespace 공유 (NO __init__.py)
    map_debug_ui/
      __init__.py
      app.py     — FastAPI app + uvicorn entrypoint
      routers/   — 디버그 엔드포인트
      deps.py    — AsyncKrtourMapClient 주입
      settings.py
      views/     — (옵션) 정적 UI

alembic/, sql/
tests/{unit,integration,e2e,fixtures}/
docs/
```

메인 패키지의 의존 방향: **category → dto → core → infra → providers → client → cli**
한 방향. `import-linter`가 CI에서 강제한다. `krtour.map.api`는 존재하지
않는다 (ADR-020).

`krtour-map-debug-ui` 패키지는 `krtour.map.client`(`AsyncKrtourMapClient`)만
import해서 함수 호출한다. 메인 패키지의 `infra/`/`providers/`를 직접 부르지
않는다.

## 4. 절대 하지 말 것 (DO NOT)

1. **의존 방향 역행 금지** — 위 계층을 거스르는 import 금지. import-linter가
   CI에서 실패시킴.
2. **동기 인터페이스 추가 금지** — `AsyncKrtourMapClient`만 둔다. 동기가 필요하면
   호출자가 `asyncio.run`으로 감싼다 (ADR-002).
3. **`pg_trgm.similarity_threshold` 전역 변경 금지** — 항상 트랜잭션 내부 `SET LOCAL`.
4. **ORM에 비즈니스 로직 금지** — `infra/models.py`는 매핑만. 쿼리는
   `infra/*_repo.py`의 raw SQL `sqlalchemy.text()` (ADR-004).
5. **좌표 순서 혼동 금지** — 모든 외부 인터페이스는 `(lon, lat)`. PostGIS도
   `ST_MakePoint(lon, lat)`. DTO `Coordinate(lat=..., lon=...)`도 alias만 다를 뿐
   API 입력/출력은 `(lon, lat)` 순서로 직렬화.
6. **카테고리/마커 매핑 하드코드 금지** — `category_mappings` DB 테이블 또는
   `Settings`에서 읽음. 라이브러리 default 상수(`KRTOUR_MAP_CATEGORY_DEFAULTS`)는
   허용하되 DB override가 우선.
7. **응답 셰입 임의 변경 금지** — 라이브러리 DTO는 `data/meta/error` 같은 HTTP
   래핑 키를 갖지 않는다. 래핑은 호출자(TripMate) 책임.
8. **외부 API 키 평문 커밋 금지** — 모두 `SecretStr`. `.env`는 권한 600 또는
   systemd `EnvironmentFile`/vault.
9. **provider adapter/wrapper 신규 생성 금지** — public client 직접 사용.
   부족하면 provider 라이브러리에서 안정화. `KmaWrapper`/`OpiNetGateway` 같은
   클래스 금지.
10. **`feature_id` raw string concat 금지** — 항상 `make_feature_id(...)`.
11. **공간 쿼리 술어에서 좌표 형변환 금지** — 입력 좌표는 CTE/파라미터로
    **한 번만** `ST_Transform`해서 상수로 굳히고, 술어는 `ST_DWithin(t.coord_5179,
    p.geom, :radius_m)`처럼 인덱스 있는 컬럼을 그대로 둔다. `ST_Transform`이 술어
    안에 들어가면 GIST 인덱스를 못 타고 매 행 변환이 돌아간다. **반경 검색은
    `coord_5179`(meter) 기준**.
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
15. **메인 라이브러리(`krtour.map`)에 FastAPI/Uvicorn import 금지** — ADR-020.
    HTTP 서버 코드는 `packages/krtour-map-debug-ui/`에만 둔다.
16. **데이터/원천 파일을 git에 커밋 금지** — `data/`는 `.gitignore`. NTFS 보관.
17. **시간 직접 사용 금지** — 모든 datetime은 KST aware (Asia/Seoul). naive
    datetime을 DTO에 넣지 않는다. `kst_now()` 사용.
18. **`Feature.detail`을 자유 dict로 사용 금지** — 항상 `PlaceDetail`/`EventDetail`
    등 Pydantic 모델 인스턴스 → `.model_dump()`. 자유 dict 우회 path 금지.
19. **main에 직접 push 금지** — 모든 변경은 feature branch + PR (ADR-021).
    `git push origin main` 절대 금지. 브랜치 명명: `feat/<topic>` /
    `fix/<topic>` / `chore/<topic>` / `docs/<topic>` / `refactor/<topic>` /
    `adr/<short>`. PR 작성: `gh pr create --title ... --body ...`.
20. **`krtour_map` flat import 금지** — 항상 `from krtour.map import ...`
    (ADR-022). `src/krtour/map/` 디렉토리 만들지 말 것 — `src/krtour/map/`.
21. **`src/krtour/__init__.py` 생성 금지** — PEP 420 implicit namespace.
    파일이 생기는 순간 자매 distribution과 namespace 충돌 (`tests/unit/
    test_no_namespace_init.py`에서 차단).
22. **TripMate 도메인 모델을 본 라이브러리에 정의 금지** — 사용자/여행계획/POI는
    TripMate.

## 5. 자주 묻는 작업

| 작업 | 시작 파일 |
|------|-----------|
| 새 provider 추가 | `dto/<provider>.py` → `core/<provider>.py` → `infra/<entity>_repo.py` → `providers/<provider>.py` → `docs/<provider>-feature-etl.md` + ADR |
| 새 raw SQL 쿼리 튜닝 | `infra/*_repo.py`의 `_SQL` 상수. EXPLAIN은 통합 테스트에서 검증 |
| 새 detail 필드 추가 | `dto/<detail>.py` Pydantic 모델 → DDL 컬럼/JSONB key → ADR |
| 새 에러 코드 추가 | `core/exceptions.py` + (디버그 API라면) `api/responses.py` 매핑 |
| 외부 API 호출 (provider) | `httpx.AsyncClient` + `tenacity` 재시도. 키는 `Settings`에서 `SecretStr`로. 호출은 provider 라이브러리에 맡김 |
| 인덱스 변경 | Alembic migration + EXPLAIN 통합 테스트 + ADR + `docs/performance.md` 갱신 |

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

- [ ] `pytest -q` 통과 (단위 + 일부 통합)
- [ ] `ruff check .` / `mypy --strict` / `lint-imports` 통과
- [ ] `docs/journal.md`에 작업 항목 추가 (역시간순)
- [ ] `docs/resume.md`의 진척도 갱신
- [ ] 의사결정이 있었다면 `docs/decisions.md`에 ADR 추가
- [ ] 사용자 가시 변경이면 `CHANGELOG.md` 갱신
- [ ] DTO/스키마 변경이면 OpenAPI export 재실행
       (디버그 API 라우터 노출 시점부터 적용)

## 8. 첫 5분 진입 프로토콜

새 세션이 들어오면 이 순서로 읽는다:

1. `README.md` — 정체성, 빠른 시작, 문서 지도
2. `SKILL.md` — DO NOT, 도메인 어휘
3. `docs/architecture.md` — 의존 방향, 데이터 흐름
4. `docs/resume.md` — "다음 한 작업"
5. `docs/journal.md` 최신 3건 — 직전 컨텍스트
6. 관련 ADR (`docs/decisions.md`)
7. 직결 docs (provider 추가면 `docs/provider-contract.md` 등)

## 9. 코드 작성 금지 (현 단계)

설계·문서화 단계에서는 `src/`, `tests/`, `alembic/`, `scripts/`에 코드를
작성하지 않는다. 별도의 코드 작성 요청이 있을 때까지 본 저장소는
**문서·계약·결정의 저장소**다. `python-krtour-map-spec.docx`(루트, 약 80쪽)는
v1 산출물과 SPEC V8 정합을 담은 reference이며 새 코드의 입력으로만 사용한다.
