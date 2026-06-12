# PR#1~#21 신규 소스·문서 상세 리뷰

작성일: 2026-05-25  
기준 브랜치: `origin/main` (`55c584c`, PR#21 merge 직후)  
검토 범위: PR#1~#21의 GitHub metadata, merge commit, 변경 파일, 현재 `origin/main`의
소스·문서·테스트 상태

## 1. 요약

PR#1~#21은 v2 설계 저장소를 실제 Sprint 1 코드 작성 상태로 옮긴 흐름이다. 큰
방향은 일관적이다.

- PR#1~#16: governance, ADR, provider ETL 문서, Sprint 계획, monorepo skeleton을
  정리했다.
- PR#17~#21: `src/kortravelmap/` PEP 420 namespace, `category`, `dto`, `core`,
  `infra` 바닥 코드를 순차적으로 추가했다.
- PR-only, `kortravelmap` namespace, debug-ui 분리, provider wrapper 금지, PostGIS
  중심 설계 같은 핵심 결정은 현재 코드 방향과 대체로 맞는다.

가장 먼저 보완할 항목은 다음이다.

1. **ADR-018 `Feature.detail` 자유 dict 금지 미충족**  
   `Feature.detail` 타입이 Pydantic union이라 `{"feature_id": ..., "place_kind":
   ...}` 같은 dict가 모델로 자동 변환된다. 문서와 테스트 이름은 dict 거부를
   약속하지만, 현재 구현은 완전한 dict 차단이 아니다.

2. **ADR-019 KST aware datetime 강제 범위가 좁다**  
   `Feature.created_at/updated_at/deleted_at`만 naive를 막는다. `NoticeDetail.
   valid_start_time`, `NoticeDetail.valid_end_time`, `RawDataRef.fetched_at`은
   naive datetime을 받을 수 있다. 또한 `Feature` validator는 UTC aware datetime도
   허용해 "KST aware"와 "timezone aware"가 섞여 있다.

3. **문서 상태 표기가 Sprint 1 이전 상태로 남아 있다**  
   `README.md`, `SKILL.md`, `docs/agent-guide.md`, `docs/tasks.md`, `docs/resume.md`
   일부가 "코드 작성 금지", "Sprint 1 진입 직전", "PR#21 open"을 계속 말한다.
   AGENTS 지침과 현재 `docs/sprints/README.md`는 Sprint 1 active이므로 신규
   에이전트 진입 시 혼란이 생긴다.

4. **PR#21 기준 전체 lint/type gate는 아직 green이 아니었다**
   `ruff check .`는 long line, unused import, broad `pytest.raises(Exception)`,
   import sort, `dto -> core` 역참조를 검출한다. `mypy --strict -p kortravelmap`은
   현재 로컬 venv에서 `pydantic_settings` 미설치로 실패했다. 이 중 상당수는
   PR#22가 해결해 main에 merge되었다.

5. **`Feature.category` 검증이 문서보다 느슨하다**  
   문서는 `PlaceCategoryCode` 8자리 value를 요구하지만 DTO는 `min_length=1`만
   본다. provider 변환이 들어오기 전에 `kortravelmap.category` 기반의 strict
   validator 또는 "임시 loose mode" 결정을 명시해야 한다.

## 2. PR별 추적 리뷰

| PR | 상태 | 핵심 변경 | 리뷰 |
|----|------|-----------|------|
| #1 | merged | ADR-021/022/023, PR-only, `kortravelmap` namespace, category 이전 결정, `docs/category.md` 신설 | v2 작업 규율을 세운 핵심 PR이다. 이후 모든 PR이 branch+PR로 들어오게 된 점은 좋다. 다만 #1 이전 direct commit 2건은 역사 기록으로 남아 있어, README/agent guide에는 "현재 기준"과 "역사 기록"을 더 분리하는 편이 좋다. |
| #2 | merged into #1/#3 흐름 | v1 문서 14건을 v2 기준으로 이관 | GitHub상 base가 `chore/pr-workflow-namespace-rename-category-migration`이라 first-parent main에는 직접 보이지 않고 #3을 통해 포함된다. 추적 리포트나 tasks merge history에는 이 특수 구조를 명확히 적어야 한다. |
| #3 | merged | #2 문서 이관분을 main으로 합류 | 실제 main 입장에서는 #2의 대형 문서 이동을 품은 PR이다. 이후 리뷰 시 #2와 #3을 중복 산정하지 않도록 "PR#2 = nested PR, PR#3 = main 합류"로 기록하는 것이 좋다. |
| #4 | merged | ADR-024, `python-mois-api` canonical name, `docs/mois-feature-etl.md` | `krmois` → `mois` 정정은 적절하다. 남은 역사적 `krmois` 언급은 ADR 맥락이면 유지하되, 사용 예시는 계속 `mois`로 sweep해야 한다. |
| #5 | merged | `outdoor` → `forest`, category Tier 1~4 catalog, KNPS dataset 계획 | forest/KNPS 범위가 좋아졌다. 이후 ADR-027/028로 이어지는 전제 PR이라, category 코드와 maki icon drift gate가 중요하다. |
| #6 | merged | ADR-025/026, debug UI와 TripMate UI `maplibre-vworld` 통일, frontend skeleton | Kakao 제거, VWorld key 공유, maplibre stack 통일 결정은 일관적이다. 단 PR#11에서 Vite → Next.js로 정정되므로 #6 문서의 오래된 Vite 표현은 #11에서 완전히 제거되었는지 계속 확인해야 한다. |
| #7 | merged | `docs/tasks.md` 최신화 | 작은 bookkeeping PR. 이후 tasks가 다시 stale해졌으므로 tasks 문서는 "작업 중 PR" 섹션을 자주 고치는 운영 부담이 있다. |
| #8 | merged | ADR-030~033 proposed, 캐시 금지, OpenAPI export, coverage schedule, consistency reports | Sprint 1 이후 CI에서 자동 강제되어야 하는 결정들을 잘 선행했다. PR#21 시점에는 아직 import-linter와 workflow가 활성화되지 않아 PR#22가 필수 후속이다. |
| #9 | merged | ADR-027 proposed, forest category/notice_type 확장 | `LODGING_MOUNTAIN_SHELTER`, `hazard_zone`, `access_restriction`, `fire_alert` 방향은 KNPS/forest 요구와 맞다. PR#18/#19에서 코드로 반영되었다. |
| #10 | merged | CHANGELOG, Sprint docs, ADR-029 npm skeleton, OpenAPI export skeleton, pyproject enforcement 주석 | 많은 결정을 한 번에 넣은 큰 PR이다. skeleton과 실제 강제 시점이 섞여 있으므로 후속 PR에서 "placeholder"와 "active gate"를 분리해 관리해야 한다. |
| #11 | merged | debug UI frontend를 Next.js로 정정 | stack 통일 결정이 명확해졌다. `packages/kor-travel-map-admin/frontend`는 skeleton이므로 실제 라우터/API 타입 동기화는 Sprint 2 첫 라우터 PR에서 재검증이 필요하다. |
| #12 | merged | ADR-028, `python-knps-api` provider 등록, `docs/knps-feature-etl.md` | 외부 provider repo와 양방향 PR 원칙을 명시한 점이 좋다. 본 저장소의 wrapper 금지 원칙을 깨지 않고 downstream ETL 계약만 잡은 것도 맞다. |
| #13 | merged | tasks merge history 표 신설 | PR tracking 가시성은 좋아졌지만, 현재 `docs/tasks.md`가 PR#21 open이라고 말하는 등 stale 위험이 확인됐다. 자동화 또는 PR template 체크가 필요하다. |
| #14 | merged | ADR-034, Sprint 2~5 계획, provider 9단계 순서 | MOIS-독립 → MOIS bulk → MOIS sibling 순서는 dedup 리스크 관리에 적절하다. Sprint plan과 provider-contract가 같은 순서를 말하는지 계속 동기화해야 한다. |
| #15 | merged | governance sweep, DO NOT bug fix 3건 | 지침 정합성을 높인 PR이다. 그러나 `SKILL.md`와 `docs/agent-guide.md`에는 이후 코드 작성 단계 진입을 반영하지 못한 문단이 남았다. |
| #16 | merged | T-014 Sprint 1 진입, ADR 027~034 accepted, `fail_under=50` | 설계 전용 단계에서 코드 작성 단계로 넘어간 기준 PR이다. 이후 문서의 "현재 상태" 문단은 이 PR을 기준으로 전부 갱신되어야 한다. |
| #17 | merged | `src/kortravelmap/` scaffolding, `settings.py`, namespace lint, smoke tests | PEP 420 namespace와 `src/krtour/__init__.py` 차단은 적절하다. `KorTravelMapSettings`는 최소 필드로 시작했지만 문서의 richer settings와 차이가 커서 "Sprint별 추가 예정" 주석을 유지해야 한다. |
| #18 | merged | `category` 144건 이전, tests | category source-of-truth를 본 repo로 가져온 핵심 코드 PR이다. 다만 Python category ↔ npm marker package mapping drift gate는 아직 없다. Sprint 2 전후로 꼭 들어가야 한다. |
| #19 | merged | `dto` foundation, Feature/detail/notice/area/coordinate/opening hours | DTO 기반이 빠르게 생겼다. 하지만 `Feature.detail` dict 자동 파싱, category loose validation, datetime validator 범위 누락이 보인다. Sprint 2 provider 입력이 들어오기 전 보완하는 편이 좋다. |
| #20 | merged | `core` exceptions, `make_feature_id` | `make_feature_id`가 dto에 의존하지 않도록 둔 점은 import-linter 관점에서 좋다. 다만 source record/hash 함수는 아직 placeholder라 provider PR 전에 반드시 추가되어야 한다. |
| #21 | merged | `infra` skeleton, CRS 변환, async engine/session, testcontainers PostGIS | PostGIS/testcontainers 바닥을 놓은 PR이다. `pyproj.Transformer` cache는 ADR-030 narrow 예외와 맞다. 아직 ORM/repo/Alembic은 없으므로 integration smoke는 schema/extension 검증 수준이다. |

## 3. 코드 리뷰 상세

### 3.1 `Feature.detail` dict 차단

문서와 테스트는 "자유 dict 금지"를 말한다. 그러나 현재 타입은 다음 union이다.

```python
detail: PlaceDetail | EventDetail | NoticeDetail | RouteDetail | AreaDetail | None
```

Pydantic은 dict 입력을 union 내부 모델로 자동 파싱할 수 있다. 예를 들어
`{"feature_id": "place:1", "place_kind": "cafe"}`는 `PlaceDetail`로 변환될 수 있다.
현재 `tests/unit/test_dto_feature.py`의 dict 거부 테스트는 `feature_id`가 빠진 dict라
우연히 실패한다. provider 변환에서 raw dict를 넘겨도 통과할 수 있으므로 ADR-018
게이트로는 부족하다.

보완:
- `detail`에 `mode="before"` field validator를 추가해 dict 입력을 명시적으로 거부.
- 또는 `Feature` 생성 API는 detail 모델 인스턴스만 받는다고 문서화하고 테스트를
  `{"feature_id": ..., "place_kind": ...}` 케이스로 강화.
- DB 저장 직전에는 `detail.model_dump()`만 허용하고 dict path를 별도 금지.

### 3.2 datetime 정책

ADR-019와 AGENTS 지침은 "KST aware datetime"을 요구한다. 현재 구현은 다음 문제가
있다.

- `Feature`의 세 timestamp만 naive를 막는다.
- `NoticeDetail.valid_start_time`, `NoticeDetail.valid_end_time`, `RawDataRef.fetched_at`
  은 validator가 없다.
- `Feature` validator는 UTC aware도 허용한다. 테스트도 UTC 허용을 명시한다.
- README와 `docs/tripmate-integration.md` 예시는 `datetime.utcnow()`를 사용한다.

보완:
- `dto/_time.py` 또는 공통 helper에 `validate_kst_aware_datetime()`을 두고 모든
  DTO datetime 필드에 적용.
- "KST만 허용"인지 "aware면 허용하고 직렬화 전 KST로 변환"인지 ADR-019 문구와
  테스트를 하나로 맞춘다.
- README/TripMate 예시는 `kst_now()` 또는 `datetime.now(ZoneInfo("Asia/Seoul"))`로
  교체한다.

### 3.3 category 검증

`Feature.category`는 `min_length=1`만 검증한다. 문서와 DB 모델은 `PlaceCategoryCode`
8자리 값을 요구한다. category source-of-truth가 PR#18에서 들어왔으므로 DTO가 아래 중
하나는 해야 한다.

- strict: `is_known_category_code(value)`로 검증.
- transitional: unknown provider category를 허용하되 `Feature.category_raw` 같은
  별도 필드에 두고 정규 category는 `00000000`으로 fallback.
- settings-driven: category mapping DB가 준비될 때까지 DTO는 8자리 pattern만 강제.

Sprint 2 첫 provider 변환 전에 결정해야 downstream 데이터 품질이 흔들리지 않는다.

### 3.4 import-linter 활성화

PR#21 기준 `dto/feature.py`가 `from ..core import kst_now`를 사용해 `dto -> core`
역참조가 생긴다. open PR#22가 `dto/_time.py`로 옮겨 해결 중이다. 이 패턴은 맞다:
낮은 레이어에서 쓰는 helper는 가장 낮은 필요한 레이어에 정의하고, 상위 레이어에서
re-export만 한다.

보완:
- PR#22 merge 후 `lint-imports`를 PR 필수 check로 지정.
- `kortravelmap.cli`처럼 아직 없는 레이어는 실제 모듈 추가 전까지 layers 계약에서
  제외하거나 placeholder package를 먼저 만든다.

### 3.5 ID 생성 함수

`make_feature_id`는 결정성, 구분자 검증, `global` fallback, SHA1 `usedforsecurity=False`
를 갖춰 Sprint 1 scope에 적절하다. 다만 provider 적재 직전에는 다음이 필요하다.

- `make_source_record_key`
- `make_payload_hash` canonical JSON 규칙
- `FeatureBundle` DTO
- source record/link DTO와 repo 계약

이들이 없으면 Sprint 2 provider 변환 함수가 다시 임시 문자열 조립을 하게 될 위험이
있다.

### 3.6 infra skeleton

`infra/crs.py`와 `infra/db.py`의 scope는 명확하다. `normalize_async_dsn()`은
testcontainers와 운영 DSN 양쪽을 다루기 쉽다. 추가 보완 후보는 다음이다.

- `make_async_engine()`에서 `connect_args`, `execution_options`, `pool_recycle` 같은
  운영 옵션 확장 여지를 settings와 맞춰 두기.
- 통합 테스트 fixture의 `ALTER DATABASE test SET search_path`는 testcontainers DB 이름
  가정에 기대므로, 추후 DB 이름이 바뀌면 `ALTER ROLE` 또는 session-level `SET
  search_path`가 더 안전하다.
- Sprint 2 Alembic 첫 revision에서 extension/schema 생성 책임을 fixture와 migration
  중 어디에 둘지 명확히 나누기.

## 4. 문서 리뷰 상세

### 4.1 현재 상태 문단 drift

다음 문서는 PR#16 이후 상태와 맞지 않는다.

- `README.md`: "v2 설계 단계 — Sprint 1 진입 직전", "문서/설계 전용",
  "proposed 027~034"로 표기.
- `SKILL.md`: "코드 작성 금지 (현 단계)"와 예외 목록이 Sprint 1 active 상태와 충돌.
- `docs/agent-guide.md`: 코드 작성 금지 단계가 "현재"라고 되어 있고, NTFS 임시
  허용 문구가 남아 있다.
- `docs/resume.md`: PR#21을 "현재 open"으로 표기.
- `docs/tasks.md`: 진행 중 PR이 PR#21로 남아 있다.

보완:
- PR#22 merge 여부와 관계없이 별도 governance sweep으로 "현재 상태" 문단을
  Sprint 1 active / PR#22 open 또는 merged 상태로 갱신한다.
- "역사 기록"인 문단과 "현재 지침" 문단을 분리한다.
- 신규 에이전트 진입 문서의 source of truth는 `AGENTS.md` + `docs/resume.md`로
  통일한다.

### 4.2 README 책임 경계

README 책임 목록에는 "디버그 REST API (옵션, 인증 없음, 내부망 전용)"이 들어 있다.
바로 위에는 debug REST/UI가 별도 패키지라고 설명하지만, 책임 목록만 보면 메인
라이브러리가 REST를 소유하는 것처럼 읽힐 수 있다.

보완:
- "별도 패키지 `kor-travel-map-admin`의 debug REST/UI 계약 제공"처럼 표현을 바꾼다.
- 메인 라이브러리 책임 목록에는 "debug REST API" 대신 "debug UI가 호출할 public
  client/DTO 제공"을 둔다.

### 4.3 검증 문서와 실제 명령

README/SKILL 검증 명령은 `python -m pytest`, `ruff`, `mypy`, `lint-imports`를 말한다.
PR#21 기준 전체 `ruff check .`는 실패한다. PR#22가 CI/lint를 도입 중이지만,
문서에는 다음이 필요하다.

- Sprint 1에서는 unit만 필수인지, integration은 Docker/testcontainers 환경에서만
  필수인지 명시.
- OpenAPI export는 Sprint 2 첫 라우터 전까지 placeholder라 failure policy가
  `continue-on-error`임을 명시.
- 로컬 venv bootstrap (`pydantic-settings`, `asyncpg`, `import-linter`) 설치가 빠진
  환경에서 어떤 실패가 expected인지 적기.

## 5. 검증 결과

검토 중 로컬 ext4 작업본에서 확인한 명령 결과:

| 명령 | 결과 | 메모 |
|------|------|------|
| `.venv/bin/python -m pytest tests/unit -q -s` | 실패: 118 passed, 4 skipped, 3 failed | 로컬 venv에 `pydantic_settings`가 없어 `KorTravelMapSettings` smoke 3건 실패. `asyncpg` 미설치로 DB engine 테스트 4건 skip. |
| `.venv/bin/python -m ruff check .` | 실패: 28건 | long line, unused import, import sort, broad `pytest.raises(Exception)`, `dto -> core` relative import 등. PR#22가 대부분 보완 중. |
| `.venv/bin/python -m mypy --strict src/kortravelmap` | 실패 | file path 실행 방식에서 module name 중복 (`map.*` / `kortravelmap.*`). `-p kortravelmap` 방식 권장. |
| `.venv/bin/python -m mypy --strict -p kortravelmap` | 실패 | 로컬 venv의 `pydantic_settings` 미설치로 import error. |
| `.venv/bin/lint-imports` | 실패 | 로컬 venv에 `lint-imports` executable 없음. PR#22에서 CI/pytest wrapper 추가 중. |

검증 실패 중 일부는 로컬 venv가 최신 dev dependency를 설치하지 않은 문제다. 그러나
`ruff check .`와 import-linter 역참조는 PR#21 코드 자체의 gate 미활성 상태를 드러낸다.

## 6. 우선순위별 보완안

### P0 — Sprint 2 provider 입력 전 차단

- `Feature.detail` dict 입력 차단 테스트를 실효 케이스로 강화하고 구현 보완.
- 모든 DTO datetime 필드에 KST/aware 정책 validator 적용.
- `Feature.category` 검증 정책 결정 후 최소한 8자리 pattern 또는 known category
  검증 추가.
- `make_source_record_key`, `make_payload_hash`, `FeatureBundle`, `SourceRecord`,
  `SourceLink`를 첫 provider PR보다 먼저 추가.

### P1 — Sprint 1 종료 gate

- PR#22 merge 완료: CI workflows, `lint-imports`, `ruff`, `mypy`, coverage XML.
- README/SKILL/agent-guide/tasks/resume의 현재 상태 drift 수정.
- `docs/tasks.md` merge history를 PR#1~#22 기준으로 갱신하고, nested PR#2 구조를
  명시.
- PR template 또는 checklist에 "journal/resume/tasks 최신화"를 기계적으로 체크.

### P2 — Sprint 2~3 안정화

- category Python ↔ `@kor-travel-map/map-marker-react` TypeScript mapping drift gate 추가.
- `KorTravelMapSettings` 문서와 실제 필드 차이를 Sprint별 checklist로 분리.
- integration fixture와 Alembic migration의 schema/extension 책임 경계 문서화.
- provider별 fixture 최소 3건 룰을 PR template에 넣기.

## 7. 최신 동기화 메모

검토 시작 시점과 리포트 최초 작성 직후 재동기화 시점에는 PR#22가 open
상태였으나, 충돌 해결 시점에는 PR#22가 main에 merge된 상태였다.

- PR#22: `feat/sprint1-pr22-ci-workflows-import-linter`
- 제목: "Sprint 1 PR#22: CI workflows + import-linter 활성화 (Sprint 1 scaffolding 종료)"
- 1차 확인: 2026-05-25 11:12 KST 근처 GitHub metadata
- 최초 리포트 작성 전 재동기화: 2026-05-25 11:28 KST, `origin/main=55c584c`,
  PR#22 state=`OPEN`
- 충돌 해결 재동기화: 2026-05-25 18:08 KST, `origin/main=01333cc`
  (PR#22 merge commit)
- PR#22 merged: 2026-05-25 09:02:14 UTC, state=`MERGED`
- 주요 보완: CI workflow 3개, `tests/lint/test_import_linter.py`, `dto/_time.py`,
  `dto -> core` 역참조 해소, ruff broad exception 정리, import-linter 활성화
