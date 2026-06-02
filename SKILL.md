# SKILL — python-krtour-map 에이전트 매뉴얼

> 이 파일은 당신(AI 에이전트)이 작업을 시작하기 전 반드시 읽어야 한다.
> 1회만 읽으면 30분 이상의 디버깅을 줄일 수 있다.

## 1. 정체성

이 저장소(GitHub 이름 `python-krtour-map`, Python 패키지 `krtour.map` — ADR-022)는
**krtour-map 독립 프로그램 + 내부 Python 라이브러리**다. 한국 공공 API
(`python-*-api`)의 결과를 단일 `Feature` 계약으로 정규화하고 독립 PostgreSQL +
PostGIS DB에 저장한다.

ADR-045 이후 TripMate ↔ krtour-map은 **OpenAPI 기반 HTTP**로 연결된다. TripMate는
krtour-map DB에 직접 접근하지 않고 `python-krtour-map`을 운영 코드에서 직접 import하지
않는다. REST/API/admin UI는 **별도 패키지** `krtour-map-admin`
(`packages/krtour-map-admin/`, ADR-020/035/045)로 분리되어 있고 인증 없이 내부망에서
사용한다.

외부 앱 POI 주변 캐시 갱신은 `external_system + target_key + 좌표 + radius_km`로
등록한 cache target을 기준으로 한다. target key가 삭제되면 targeted update에서
제외하고, 여러 target 반경의 교집합 feature/provider scope는 한 번만 갱신한다.
자세한 사양은 `docs/poi-cache-update-targets.md`.

이전(v1) 구현은 `v1` 브랜치에 보존되어 있다. master(main)는 v2 사양으로 처음부터
다시 구현한다(ADR-001).

### 식별자 매핑

| 항목 | 값 |
|------|----|
| GitHub 저장소 | `python-krtour-map` |
| PyPI distribution | `python-krtour-map` |
| Python import (메인) | `from krtour.map import ...` (ADR-022) |
| Python import (디버그 UI) | `from krtour.map_admin import ...` |
| CLI 명령 (있다면) | `krtour-map` |
| 환경변수 prefix | `KRTOUR_MAP_*` |
| PostgreSQL DB 이름 (개발/운영 기본) | `krtour_map` (TripMate 공유 DB 아님, ADR-045) |
| Dagster metadata DB 기본 | `krtour_map_dagster` |
| Postgres schema | `feature`, `provider_sync`, `ops`, `x_extension` |
| 디버그 UI 패키지 | `krtour-map-admin` (별도 Python 패키지, `packages/krtour-map-admin/`, ADR-020) |
| Category 모듈 | `krtour.map.category` (구 `kraddr.base.categories`에서 이전, ADR-023) |

### 개발 환경 (PC, WSL)

형제 라이브러리 (`python-kraddr-geo` / `python-kraddr-base` / `python-knps-api`
등)와 **동일 정책**. 자세히는 `AGENTS.md` §"개발 환경 정책 (PC, WSL)" +
`docs/dev-environment.md`.

- **코드/git**: Windows NTFS (`F:\dev\python-krtour-map\`). 브랜치 전환,
  커밋, PR 준비는 Windows Git(`git.exe`) 기준으로 수행한다.
- **에이전트 worktree**: Codex `F:\dev\python-krtour-map-codex\`, Claude
  `F:\dev\python-krtour-map-claude\`, Antigravity
  `F:\dev\python-krtour-map-antigravity\`.
- **데이터(`data/`)**: NTFS의 프로젝트 디렉토리 아래
  (`F:\dev\python-krtour-map\data\`). git에는 넣지 않는다.
- **테스트**: PostGIS/testcontainers/e2e처럼 Linux 실행 환경이 필요하면 NTFS
  소스를 WSL ext4 샌드박스(`~/dev/python-krtour-map/` 등)로 복사해서 실행한다.
- **카피 정책**: 테스트 실행 및 배포 전 NTFS → WSL ext4로 `rsync`한다. Git
  source of truth는 NTFS다.

### 에이전트 worktree + codegraph

각 AI 에이전트는 자기 전용 git worktree + 로컬 codegraph 인덱스를 가진다.
ChatGPT Codex → `F:\dev\python-krtour-map-codex\`, Claude Code →
`F:\dev\python-krtour-map-claude\`, Google Antigravity 2.0 →
`F:\dev\python-krtour-map-antigravity\`. 작업마다 worktree 안에서 브랜치만
새로 (`git switch -c feat/<topic> main`), `.codegraph/`는 worktree마다 1회
`codegraph init -i` 후 이후엔 `codegraph sync`로 증분 동기. `.codegraph/`는
`.gitignore`. 자세히는 `docs/codegraph-worktree.md` + `AGENTS.md` §"에이전트
worktree + codegraph".

#### CodeGraph Commands (빠른 참조)

- `codegraph init -i` — 인덱싱 초기화 (worktree마다 1회)
- `codegraph status` — 동기화 상태 확인
- `codegraph sync` — 브랜치 전환/pull 후 증분 동기
- `codegraph impact <file>` / `callers <sym>` / `callees <sym>` — 영향도

#### MCP 서버 등록

`codegraph install --yes`로 자동, 또는 `~/.claude.json`(Windows:
`C:\Users\<user>\.claude.json`)의 `mcpServers`에 `{"codegraph": {"type":
"stdio", "command": "codegraph", "args": ["serve", "--mcp"]}}` 블록 수동
추가. `npx -y @colbymchenry/codegraph serve --mcp` 대안도 가능. Codex CLI /
Cursor / opencode / Hermes는 `codegraph install --print-config <target>`로
각자 snippet 출력. 자세히는 `docs/codegraph-worktree.md` §6.

#### 수정 전 영향도 평가 (DO 룰)

코드 컴포넌트(특히 `Feature` DTO / `make_feature_id` / provider 변환 함수 /
`core/scoring.py` / `infra/models.py`) 수정 전에 **반드시** codegraph로
영향도를 먼저 평가한다 — MCP에서는 `codegraph_explore` 도구, CLI에서는
`codegraph callers <sym>` + `codegraph impact <file>` + `codegraph callees
<sym>` 조합. 신규 파일만 추가하고 기존 심볼 시그니처가 그대로면 생략 가능.
자세히는 `docs/codegraph-worktree.md` §7.

## 2. 빠른 시작

```bash
cd /mnt/f/dev/python-krtour-map                       # WSL에서 NTFS 소스 확인
git.exe -C F:/dev/python-krtour-map status            # Git은 Windows Git 기준
rsync -a --delete --exclude .git --exclude .venv \
  --exclude data /mnt/f/dev/python-krtour-map/ ~/dev/python-krtour-map/
cd ~/dev/python-krtour-map                            # WSL 테스트 샌드박스
ln -sfn /mnt/f/dev/python-krtour-map/data data        # NTFS data 참조
sudo apt install -y libgdal-dev gdal-bin              # GeoPandas/loaders용
uv venv && uv pip install -e ".[dev,api,providers]"
uv pip install "gdal==$(gdal-config --version)"
cp .env.example .env && $EDITOR .env                  # KRTOUR_MAP_PG_DSN 채우기
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

packages/krtour-map-admin/      ← 별도 Python 패키지 (ADR-020)
  pyproject.toml
  src/krtour/                      ← 같은 namespace 공유 (NO __init__.py)
    map_admin/
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

`krtour-map-admin` 패키지는 OpenAPI backend/admin UI이며, 내부 구현에서
`krtour.map.client`(`AsyncKrtourMapClient`)를 호출한다. 라우터가 메인 패키지의
`infra/`/`providers/`를 직접 우회하지 않는다.

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
7. **응답 셰입 임의 변경 금지** — 메인 라이브러리 DTO는 `data/meta/error` 같은 HTTP
   래핑 키를 갖지 않는다. 래핑은 OpenAPI backend(`krtour-map-admin`) 책임.
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
    HTTP 서버 코드는 `packages/krtour-map-admin/`에만 둔다.
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
    (ADR-022). `src/krtour_map/` 디렉토리 만들지 말 것 — `src/krtour/map/`.
21. **`src/krtour/__init__.py` 생성 금지** — PEP 420 implicit namespace.
    파일이 생기는 순간 자매 distribution과 namespace 충돌 (`tests/unit/
    test_no_namespace_init.py`에서 차단).
22. **TripMate 도메인 모델을 본 라이브러리에 정의 금지** — 사용자/여행계획/POI는
    TripMate.
23. **GitHub Actions CI green 통과 전 머지 금지** — ADR-038 (2026-05-27
    재활성화). `.github/workflows/{ci,lint,openapi}.yml` 모두 통과 + 1 review.
    "쓰지마"였던 2026-05-26 시기 패턴은 폐기.
24. **CLI 중복 실행이 위험한 명령에 mutex 없이 머지 금지** — ADR-039 accepted.
    `import`/`dedup-merge`/`backup`/`restore`/`alembic upgrade`는 PostgreSQL
    `pg_try_advisory_lock` 기반 mutex 박음. read-only / `--dry-run` 예외.
25. **`@krtour/map-marker-react` npm registry 게시 금지** — ADR-043. 모노레포
    내부 git share만. `packages/map-marker-react/package.json` `"private": true`.
26. **kraddr-base의 `PlaceCoordinate` import 금지** — ADR-041. 좌표 DTO는
    `krtour.map.dto.Coordinate` 단일 source. kraddr-base 흡수 작업에서 명시적
    제외 대상.

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
- [ ] frontend 작업이면 `npm run lint` / `npm run type-check` / `npm run build` /
      `npm run doctor` 실행 후 React Doctor 결과 검토·개선

## 8. 첫 5분 진입 프로토콜

새 세션이 들어오면 이 순서로 읽는다:

1. `README.md` — 정체성, 빠른 시작, 문서 지도
2. `SKILL.md` — DO NOT, 도메인 어휘
3. `docs/sprints/README.md` — Sprint 1~5 + ADR-034 9단계 순서
4. `docs/architecture.md` — 의존 방향, 데이터 흐름
5. `docs/resume.md` — "다음 한 작업"
6. `docs/journal.md` 최신 3건 — 직전 컨텍스트
7. 관련 ADR (`docs/decisions.md` 001~046 모두 accepted; 다음 후보 047)
8. 직결 docs (provider 추가면 `docs/provider-contract.md`, 현재 sprint면
   `docs/sprints/SPRINT-N.md` 등)

## 9. 코드 작성 단계 (Sprint 4 완료 / Sprint 5 + ADR-045 진입 준비)

본 저장소는 T-014 승인 (2026-05-25, PR#16) 이후 **코드 작성 단계**다.
2026-06-02 현재 main은 PR#149까지 머지되었고 Sprint 4(4a+4b) 완료 상태다.

- Sprint 2 완료: 축제/날씨/유가/휴게소 provider + ETL live 11/11 dataset.
- Sprint 3 완료: KNPS/krheritage, PostGIS 적재/조회, consistency report,
  dedup queue, `AsyncKrtourMapClient`, `/features` debug UI.
- Sprint 4 완료: MOIS Step A~D lifecycle(bulk/incremental/closed/detail),
  `krtour-map dedup-merge` + `ops.feature_merge_history`(alembic 0007),
  dedup 운영 FP 통계, ADR-033 F4, Place phone enrichment, coverage 80% 달성.
- ADR-045 D-1~D-16 결정 완료. `krtour-map-debug-ui` 호환 경로/env/import,
  TripMate 직접 import, 공유 DB, TripMate-owned Dagster 호환 shim은 만들지 않는다
  (ADR-046).
- Geocoding 현재 정본: kraddr-geo REST v2 `POST /v2/{reverse,geocode}`, 로컬 기본
  `http://127.0.0.1:9001`.
- RustFS 로컬 표준: S3 API `9003`, console `9004`.
- Frontend 현재 정본: Next.js 16 + React 19 + `maplibre-vworld-js#v0.1.2`,
  Windows Playwright e2e.

신규 코드는 항상 PR로 (ADR-021). 각 PR은 `pytest -q` + `ruff check` +
`mypy --strict` + `lint-imports` + `docs/journal.md` + `docs/resume.md`
업데이트 (해당 시 ADR/CHANGELOG/OpenAPI 동기). `python-krtour-map-spec.docx`
(루트, 약 80쪽)는 v1 + SPEC V8 정합 reference로만 사용 — 새 코드의 입력
아닌 *참고용*.

**다음 단계**: ADR-045 독립 프로그램화(Docker compose + admin-first OpenAPI +
독립 Dagster) + Sprint 5 (MOIS-sibling provider + Phase 2 게이트). 자세히는
`docs/sprints/SPRINT-5.md` + `docs/resume.md` + ADR-045.
