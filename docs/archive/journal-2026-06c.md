# journal 아카이브 — 2026-06-01 ~ 2026-06-02

> `docs/journal.md`에서 분리한 과거 기록(역시간순). 현행 정본은
> [`docs/journal.md`](../journal.md)이며, 전체 아카이브 목록도 거기에 있다.
> 이 파일은 읽기 전용 이력이다 — 새 엔트리는 `docs/journal.md` 상단에 추가한다.

## 2026-06-02 (claude) — ADR-045 문서 정합 2차 패스 (cross-link/stale 정정)

**작업**: 사용자 지시 — 최신 pull 후 문서 전체 재점검, 충돌·보완 반영 후 PR/머지.
codex `49d11cb`(ADR-045 docs 대규모 정합 + ADR-046 추가 + `regions-within-radius.md`
신설) 이후 잔여 불일치를 병렬 감사(Explore ×3)로 수집, 실제 항목만 정정.

- **tripmate-rest-api.md**: 헤더·§6의 stale "미확정 D-1/D-3" 제거(전부 결정됨
  2026-06-02). D-1(infra+`X-Kor-Travel-Map-Service-Token`)/D-3(SemVer+이원 schema)/D-11을
  결정 목록으로 이동, D-11 정본을 `regions-within-radius.md`로 cross-link.
- **agent-guide.md**: ADR 카운트 내부 불일치 정정(16행 "001~044/후보 045" →
  "001~046/후보 047", 58행 "다음 번호 ADR-044" → "ADR-047", 117/124/323행과 정합).
- **postgres-schema.md §3.3**: `ops.feature_update_requests`(ADR-045 계획, alembic
  미구현) 카탈로그 행 추가 — DDL 정본은 openapi-admin-contract §6.1 + data-model §9.8.
- **adr045-open-decisions.md D-11 / adr045-standalone-plan.md T-206a-geo**:
  kor-travel-geo `POST /v2/regions/within-radius` 정본을 `regions-within-radius.md`로 명시.
- **debug-ui-package.md**: 파일명 legacy(구 kor-travel-map-admin) 각주 추가, 내용은
  현 `kor-travel-map-admin` 정본임을 명기.
- **확인(수정 불필요)**: Sprint 4 완료 마커·패키지 rename·테스트 카운트·D-1~D-16
  결정 상태는 모든 entry doc에서 이미 일관. `debug-ui-admin-workflows.md` 존재 확인
  (감사 false-positive 기각). journal/2026-05-29 report의 옛 ADR 카운트는 역사적 기록.

## 2026-06-02 (codex) — ADR-045 D-11 POI 반경 행정구역 조회 + admin 디버깅 UI

**작업**: 사용자 지시 — POI 좌표 기준 주변 `n` km에 포함/교차하는 시군구·읍면동을
반환하는 함수를 kor-travel-map의 ADR-045 방향에 맞춰 구현하고, admin에서 디버깅 가능하게
함.

- **Python API**: `KorTravelGeoRestClient.regions_within_radius`,
  `resolve_regions_within_radius`, `resolve_sigungu_by_radius` 추가. kor-travel-geo REST v2
  `POST /v2/regions/within-radius`를 호출하고 `sido`/`sigungu`/`emd` 응답을 typed
  dataclass로 정규화.
- **Admin API/UI**: `/debug/geocoding/regions/within-radius`와 `/raw` 라우트 추가,
  `/geocoding` frontend에 좌표·반경·level 선택·raw toggle 폼 추가.
- **테스트**: REST body/path/default level/custom level, malformed item, HTTP error,
  admin schema/raw/503/502, frontend form/level toggle e2e를 보강.
- **문서**: `docs/regions-within-radius.md` 신설, OpenAPI 재생성,
  `CHANGELOG.md`/`resume.md` 갱신.

## 2026-06-02 (codex) — ADR-046 정본 전환 + kor-travel-geo v2 주소 정책 문서 정리

**작업**: 사용자 지시 — 호환성 shim 없이 올바른 방향으로 문서를 정리하고,
kor-travel-geo REST API를 v2 기준으로 통일. provider 주소/좌표 정본화 중 발생하는
오류를 admin UI에서 수동 처리하도록 명세.

- **ADR-046 추가**: ADR-045 이행 시 legacy package/path/env/direct import/shared DB/
  TripMate Dagster 호환 shim을 만들지 않고 정본 방향으로 전환. 다음 후보 번호는
  ADR-047.
- **주소 정본 정책**: provider가 제공하는 주소/행정코드는 provenance로만 보존하고,
  저장 정본은 kor-travel-geo REST v2 `POST /v2/reverse`, `POST /v2/geocode` 결과로
  만든 `kortravelmap.dto.Address`로 통일. 좌표+주소가 같이 있으면 좌표 reverse를
  정본으로 삼고 provider 주소와 매칭한다.
- **Admin 수동 처리**: `provider_address_mismatch`, `provider_address_partial_match`,
  `geocode_failed`, `reverse_geocode_failed`, `missing_address`, `missing_bjd_code`
  이슈를 `/admin/issues` 지도/테이블에서 검토하고, 재시도·kor-travel-geo 주소 채택·
  수동 override·ignore/reopen을 할 수 있도록 OpenAPI/UI 사양 보강.
- **문서 정합성**: TripMate 직접 import legacy 본문 제거, Sprint 5 Dagster 소유권을
  kor-travel-map으로 정리, streaming consumer/백업/DB/패키지명/ADR 번호 drift 정정.
- **docs-only 의도** — PR staging 대상은 문서만.

## 2026-06-02 (claude) — ADR-045 비BLOCKER 의사결정 8건 전부 권고대로 확정

**작업**: 사용자 "모두 권고안대로" → 남은 비BLOCKER 8건 확정 + ADR amendment.

- **확정 (모두 권고안)**: D-1(인증=infra SSO/IP + `X-Kor-Travel-Map-Service-Token` pass-
  through) / D-3(SemVer + admin·user schema 이원 drift gate) / D-8(deactivate=
  `prevent_provider_reactivation` 플래그) / D-10(keyset cursor + base64) / D-12
  (React Doctor 단계적) / D-13(shadcn↔marker 분리 + 핀) / D-15(provider 키 docker
  env→resource, 누락 시 asset만 실패) / D-16(CHANGELOG `### API` + SemVer 태깅).
- **ADR amendment**: ADR-005에 D-1 인증 amendment(코드 인증 없음 유지 + infra 계층
  + 토큰 pass-through), ADR-031에 D-3 amendment(OpenAPI 이원화 + SemVer + drift
  gate 2개)를 추가.
- **결정 상태**: `adr045-open-decisions.md` D-1~D-16 **전 항목 결정 완료**(BLOCKER 5
  + 설계/운영 11). 구현 착수 가능.
- 후속 amendment(ADR-003 §후속/ADR-034 Dagster 주체/ADR-040 백업/SPRINT-4·5)는
  해당 구현 시점에 반영(plan §7 표).
- **docs-only** — 코드/게이트 변경 없음.

## 2026-06-02 (claude) — 패키지 rename: kor-travel-map-admin → kor-travel-map-admin (D-9)

**작업**: D-9 결정(즉시 rename, 이름 `kor-travel-map-admin`)을 코드로 실행.

- `git mv packages/kor-travel-map-admin → kor-travel-map-admin` +
  `src/kortravelmap_debug_ui → src/kortravelmap/admin`.
- 토큰 일괄 치환(추적 78파일): `map_debug_ui`→`map_admin` /
  `kor-travel-map-admin`→`kor-travel-map-admin` / `KOR_TRAVEL_MAP_DEBUG_UI`→`KOR_TRAVEL_MAP_ADMIN`
  (env prefix + frontend `NEXT_PUBLIC_*` 포함) / `DebugUiSettings`→`ApiSettings`.
  npm 스크립트 `debug-ui:*`→`admin:*`, frontend 패키지명 `kor-travel-map-admin-frontend`.
- 외부 참조 갱신: 루트 `pyproject.toml`(mypy_path) / `package.json`(workspace) /
  `.github/workflows/{ci,frontend,openapi}.yml`(경로/스텝) / openapi.json 경로 이동.
- WSL에서 패키지 재설치(`pip install -e packages/kor-travel-map-admin`) + openapi.json
  재생성(drift EXIT=0).
- ADR-020에 rename amendment 추가(D-9). 라우터 prefix(`/debug`·`/admin`·`/ops`·
  `/features`)는 그대로.
- **검증(WSL)**: ruff clean / mypy --strict main 61 + admin 13 / import-linter 4 kept /
  openapi drift EXIT=0 / main **835 passed** + admin **117 passed**.
- 잔여 토큰 0 확인. claude.json(세션 파일) 스테이징 제외.

## 2026-06-01 (claude) — ADR-045 BLOCKER 의사결정 확정 + kor-travel-geo 시군구 반경 API 설계

**작업**: 사용자가 BLOCKER 5건 결정 → 문서에 확정 반영 + 영향 task/spec 갱신.

- **확정 (D-2/D-6/D-7/D-11/D-14)** — `adr045-open-decisions.md` BLOCKER 섹션 ✅:
  - D-2 = (a) 같은 Postgres, 별도 DB `kor_travel_map_dagster` + 기동 순서 확정.
  - D-6 = 권고대로 — request:job **1:1**, `run_mode=now` lock 충돌 시 **409 +
    retry_after**, sensor 폴링 **15초**.
  - D-7 = **분리** — `/features/*`(공개) + `/admin/features/*`(원문/이력).
  - D-11 = **kor-travel-geo에 신규 엔드포인트 추가** + kor-travel-map REST 호출. kor-travel-map
    경계 테이블(T-205b) 취소.
  - D-14 = **RustFS 무제한 보존**(정리 job 없음).
- **kor-travel-geo `POST /v2/regions/within-radius` 설계**(형제 repo 별도 PR) —
  요청 `{lon,lat,radius_km,levels}` → 응답 `{sigungu:[{code,name,relation}]}`.
  `tl_scco_sig`(이미 적재된 시군구 경계 polygon) PostGIS 교차. kor-travel-map
  `resolve_sigungu_by_radius`가 `KorTravelGeoRestClient`로 호출.
  **기타 코멘트 저장**: (1) `sig_cd`(5자리) = `sigungu_code`(5자리) **동일 체계
  (사용자 확인)** — 매핑 불필요, (2) `levels`는 sigungu 우선·시도/읍면동 확장 여지
  (사용자 확인), (3) reverse에 radius 옵션 얹는 대안은 의미 흐려져 미채택(사용자:
  엔드포인트 늘려도 됨).
- **task 반영**: T-205b 취소, T-206a를 kor-travel-geo 호출로, **T-206a-geo 신규**
  (kor-travel-geo 엔드포인트, 별도 repo). plan §1/§2 + tasks.md + tripmate-rest-api §3.7/§6.
- 비BLOCKER(D-1,3,4,5,8,9,10,12,13,15,16)은 권고안 유지(추후 결정).
- **docs-only** — 코드/게이트 변경 없음. kor-travel-geo 엔드포인트는 그 repo 별도 PR.

## 2026-06-01 (claude) — ADR-045 실행 계획 + 의사결정 + TripMate REST 구체화

**작업**: 사용자 지시 — (1) DB 스키마/로직 추가 구체화, (2) sprint/task/ADR 충돌
정리, (3) TripMate 문서 정리 + 이관 + Dagster 복사·구체화 + 연계 REST 명세. AI
agent가 바로 실행 가능하도록 task를 세분하고, 의사결정 필요분을 문서화.

- **리서치**: 병렬 에이전트 4개로 (A) ADR-045 후속 문서 갭, (B) TripMate 문서/
  Dagster/REST 요구, (C) DB 스키마·로직 갭, (D) sprint/task/ADR 충돌을 수집. 핵심:
  codex가 admin OpenAPI/큐 DDL/Docker 서비스를 이미 명세(`openapi-admin-contract.md`
  등)했고, **빠진 것은 alembic/코드/Dagster/compose 구현 + TripMate REST params/
  returns + 의사결정 10여건**.
- **신규 문서 3종**:
  - `docs/adr045-standalone-plan.md` — 독립 프로그램화 **마스터 실행 계획**. Phase
    1~6(DB 스키마 / 로직 scope resolver / FastAPI 라우터 / Dagster / Docker compose /
    TripMate 연계) + **fine-grained T-205~T-210** + 재사용 자산 + 권장 순서 §8 +
    충돌·정리 표 §7. 기존 명세는 재작성 않고 참조.
  - `docs/tripmate-rest-api.md` — TripMate 호출 REST의 엔드포인트·**params/returns**
    구체화(in-bounds/{id}/batch/search/nearby-by-target/last-sync/feature-update-
    requests/health·version) + 공개 Feature 응답 형태 + 에러 코드.
  - `docs/adr045-open-decisions.md` — **의사결정 대기 D-1~D-16**(BLOCKER 5: Dagster
    DB / 큐 모델 / features admin↔user 분리 / sigungu 경계 / offline 저장).
- **backlog 세분**: `docs/tasks.md`에 ADR-045 섹션 + T-205~T-210(Phase별, 각 1-PR).
- **충돌 정리**: SPRINT-5 §2에 ADR-045 트랙 포인터, T-200에 Dagster=kor-travel-map 소유
  주석, ADR-011 §결과(부정) 오참조("ADR-016에서 분리"→"import_jobs 1차 큐 +
  Dagster sensor 폴링, ADR-045 §5") 정정. 나머지 ADR amendment(003/005/031/034/040)
  는 해당 의사결정 확정 시 반영(plan §7 + decisions에 목록).
- README 문서 지도에 신규 3종 등록. resume 다음 한 작업을 plan/decisions 참조로 갱신.
- **docs-only** — 코드/게이트 변경 없음.

## 2026-06-01 (claude) — 문서 전체 정합성 sweep (ADR-045 충돌 + Sprint 4 staleness)

**작업**: 사용자 지시 — 최신 pull 후 문서 전체를 점검해 충돌/갭을 꼼꼼히 정정.
병렬 감사 에이전트 4개로 클러스터별(진입/통합/status/스키마) 충돌·갭을 file:line
수집한 뒤 일괄 수정. codex가 추가한 ADR-045(Docker 독립 + OpenAPI)와 Sprint 4 완료
사실을 진입·status·스키마 문서에 반영.

- **ADR-045 충돌 해소 (함수 직접 호출 → OpenAPI/HTTP, ADR-003 supersede)**:
  - `CLAUDE.md` §1 "이 저장소가 하는 일" 전면 재작성(독립 프로그램 + 논리 서비스 +
    OpenAPI 경계 + admin/API 패키지 framing).
  - `docs/resume.md` "TripMate 연계 (ADR-003) 함수 직접 호출" → ADR-045 OpenAPI.
  - `docs/tripmate-integration.md` legacy 섹션에 ⚠️ DEPRECATED(사용 금지) 배너 강화.
- **Sprint 4 완료 staleness 정정**: CLAUDE/AGENTS/SKILL/README/agent-guide의
  "Sprint 3 완료 / Sprint 4 진입 준비 / PR#114 / ADR 001~044 / 다음 후보 045 /
  fail_under=75" → "Sprint 4(4a+4b) 완료 / PR#142 / 001~045 / 다음 046 /
  fail_under=80(94.12%)". MOIS Step A~D·dedup-merge·F4·phone enrichment·runbook
  추가 사실 반영.
- **status/tracking 동기화**: `resume.md`(다음 한 작업 = ADR-045 독립화) +
  `tasks.md`(머지 history #51~#142 그룹 + ADR 가이드 046) + `sprints/README`·
  `SPRINT-4`(✅완료 + §7 DoD [x]) · `SPRINT-5`(진입조건 [x] + ADR-045 트랙).
- **스키마 갭 정정(코드와 일치화)**: `data-model.md`/`postgres-schema.md`의
  `ops.feature_merge_history` 컬럼명을 alembic 0007 실제값으로
  (history_id→merge_id, loser_id→loser_feature_id(+FK CASCADE), master_id→
  master_feature_id, reviewer→merged_by, +review_id FK SET NULL,
  idx_merge_history_loser 추가). provider_sync_state.cursor(Step B 용도) 주석.
- **ETL 구현현황 추가**: `mois-license-feature-etl.md`(Step A~D 코드 모듈 매핑) +
  `place-phone-enrichment.md`(`kortravelmap.enrichment` 함수) "구현 현황" 노트.
- 과거 append-only 기록(journal/reports/dated)은 그대로 보존(당시 사실 반영).
- **docs-only** — 코드/게이트 변경 없음.

## 2026-06-01 (codex) — ADR-045 독립 프로그램/OpenAPI 전환 + admin 캐시 갱신 사양

**작업**: 사용자 지시에 따라 debug UI/admin 운영 콘솔을 문서화하고, 이어서 운영 모델을
Docker 독립 프로그램 + 독립 PostgreSQL/PostGIS DB + 독립 Dagster + TripMate OpenAPI
연동으로 전환하는 결정을 문서화했다. 코드 변경은 없다.

**문서 보강**:
- `docs/decisions.md`: ADR-045 추가. ADR-003의 TripMate 직접 함수 호출 운영 모델을
  supersede하고, OpenAPI/Docker/독립 DB/Dagster 기준을 확정.
- `docs/debug-ui-admin-workflows.md`: feature 목록/상세/수동추가/비활성화/삭제,
  provider 강제 실행, job progress/cancel, dedup/결측/이슈 지도·테이블, offline upload,
  React Doctor 필수 검증까지 admin UI 구현 사양 작성.
- `docs/openapi-admin-contract.md`: admin 우선 OpenAPI, Dagster feature update request,
  좌표 반경/시군구/provider scope, 즉시 실행/큐잉, Docker 서비스 구조 작성.
- `docs/poi-cache-update-targets.md`: 외부 앱 POI key + 좌표 기반 cache target,
  주변 feature 조회, target 삭제 처리, 교집합 dedup, provider refresh policy/rate limit,
  KST `last_updated_at`, 목록/상세 응답 분리 규칙 작성.
- `docs/architecture.md`, `docs/dagster-boundary.md`, `docs/tripmate-integration.md`,
  `docs/debug-ui-package.md`, `README.md`, `SKILL.md`, `AGENTS.md`, debug-ui README류:
  ADR-045 기준으로 참조와 우선 규칙 정합.

**검증**: Markdown 문서 변경만 수행. `rg`로 주요 legacy 표현을 검색해 새 ADR-045
우선 안내 또는 legacy 배너가 붙었는지 확인.

## 2026-06-01 (claude) — 에이전트 공용 runbook 신설 (agent-workflow / agent-failure-patterns)

**작업**: 사용자 지시 — TripMate(`F:\dev\tripmate`)의 `docs/runbooks/` 컨벤션을 참고해
본 repo에 **에이전트 공용 runbook**을 신설(agent-workflow + agent-failure-patterns
포함, Claude/Codex/Antigravity가 같은 파일 공유).

- **신설 `docs/runbooks/`**:
  - `README.md` — 인덱스 + 에이전트별 분기 표(worktree/`sandbox/<agent>`) + 공통 정책
    (NTFS source of truth / WSL 테스트 / 4 게이트 / main 직접 push 금지).
  - `agent-workflow.md` — 표준 1-PR 흐름(진입 → 브랜치 → NTFS 편집 → WSL rsync+4게이트
    +openapi-drift → 커밋/PR → CI 3버전 green → 머지 → sandbox/<agent>+WSL 동기화) +
    1-PR 체크리스트. 에이전트 중립.
  - `agent-failure-patterns.md` — 본 repo 실사례 패턴: A(CI↔로컬 괴리: WSL venv가
    [dev] extra 가림 / 안 돌린 결과 보고 금지 / 버전별 CI / openapi drift), B(git:
    sandbox 직접 커밋 복구 / WSL 미러 reset / 무관 파일), C(도메인: 자연키 `::` /
    스키마 한정 / CHECK 허용값 / upstream drift ADR-044 / 증분 prune 금지), D(python:
    normalize_phone 관대함 / runtime_checkable 불안정 / Result.rowcount / commit 테스트
    오염 / CJK E501 / future annotations).
- **포인터**: `docs/agent-guide.md` §1 진입 프로토콜에 runbook 9번 추가 +
  `AGENTS.md`에 "에이전트 공용 runbook (필독)" 섹션.
- 출처: 세션 transcript + `MEMORY.md`(wsl-test-venv / playwright-e2e) + PR 회고.
- **docs-only** — 코드/게이트 변경 없음(ruff/mypy/pytest 영향 없음).

## 2026-06-01 (claude) — Sprint 4b: Coverage 80% 완전 달성 (게이트 75→80)

**작업**: ADR-032 Sprint 4 목표인 coverage 80%를 게이트(`fail_under`)에 박음 — Sprint
4b 마지막 항목.

- **측정(WSL, 835 tests 전체)**: 전체 **94.12%**. 모든 tier 목표 상회 — enrichment/
  consistency/status_repo 100%, infra 94~100%, providers 최저 mois 82%·krheritage 87%
  (모두 ≥70 providers tier), dto 92~100%.
- **변경**: `pyproject.toml` `[tool.coverage.report] fail_under` 75 → **80**(ADR-032
  Sprint 4 스케줄 목표). 실측 94.12%라 무위험 상향 — 신규 테스트 불필요(이번 Sprint
  4a/4b PR들이 함께 보강됨). schedule 주석을 Sprint 4=현재로 갱신.
- **검증(WSL)**: `pytest --cov` → "Required test coverage of 80.0% reached. Total
  coverage: 94.12%" / 835 passed.
- **Sprint 4b 3종(F4 / Place phone enrichment / Coverage 80%) 완료. Sprint 4
  (4a+4b) 종료.**

## 2026-06-01 (claude) — Sprint 4b: Place 전화번호 보강 (백그라운드 시작)

**작업**: Place phone enrichment(SPRINT-4 §2.7) — 전화번호 없는 MOIS place 후보 발굴
+ 외부 lookup 결과 보강. 외부 API 호출은 ADR-006상 본 lib가 안 하고 호출자(백그라운드
워커)가 주입.

- **infra/feature_repo**: `find_place_features_without_phone`(detail.phones 빈 place
  후보 조회, generic provider/dataset) + `set_feature_phones`(detail.phones JSONB
  교체).
- **enrichment.py(신규 top-level loader)**: `find_place_phone_candidates`(기본 MOIS
  bulk) + `apply_place_phone_enrichment`(전화번호 정규화+자릿수≥9 검증+dedup+max3 →
  detail.phones 갱신 + enrichment SourceRecord/SourceLink(role='enrichment',
  is_primary_source=False) 적재). 무효/중복/초과/미존재 시 `applied=False`+reason.
  `PhoneEnrichmentCandidate`/`PhoneEnrichmentResult`.
- **client**: `find_place_phone_candidates`(read) + `enrich_place_phone`(write, 한
  transaction).
- 설계: `normalize_phone_number`는 숫자 부족 시 원본 반환(provenance) → enrichment는
  품질 위해 자릿수<9를 invalid로 거른다.
- **테스트**: integration 6(후보 발굴 phone 유무 분기 / 보강+link / 중복 skip /
  무효 / 미존재 / max3).
- **검증(WSL)**: ruff clean / mypy --strict 61 files / import-linter 4 kept / 전체
  **835 passed**(829 → +6).
- **다음**: Coverage 80% 완전 달성(Sprint 4b 마지막).

## 2026-06-01 (claude) — Sprint 4b: ADR-033 F4 정합성 검사 (dedup 백로그 baseline)

**작업**: ADR-033 Phase 1에 **F4**(dedup_review_queue 미해소 백로그 baseline 초과
→ WARN) 추가. SPRINT-4 §2.3. observe-only(적재 차단 없음).

- **infra/consistency**: `_check_f4_dedup_backlog` — pending dedup 수가
  `DEDUP_PENDING_WARN_THRESHOLD`(provisional 1000) 초과 시 WARN, 이하면 OK. F1~F3
  (행별 정적 SQL `CONSISTENCY_CASES`)과 달리 **임계 집계 케이스**라
  `run_consistency_checks`의 분기로 추가(`dedup_pending_threshold` 인자로 override).
  초과 시 count=현재 pending 수 + sample은 total_score 상위 pending review_id.
- baseline는 **provisional** — MOIS Step A bulk가 큐를 채운 뒤 첫 적재 후보 수
  기준 재조정(§2.3 "후반에 baseline 조정"). WARN은 ERROR(F1~F3)를 가리지 않음
  (severity_max 우선순위).
- **테스트**: integration 3(임계 이하 OK / 초과 WARN+sample / F4 WARN과 F1 ERROR
  공존 시 severity_max=ERROR). 기존 clean-data 테스트는 빈 큐 → F4 count=0로 안 깨짐.
- **검증(WSL)**: ruff clean / mypy --strict 60 files / import-linter 4 kept / 전체
  **829 passed**(826 → +3).
- **다음(Sprint 4b 잔여)**: Place phone enrichment 백그라운드 + Coverage 80%.

## 2026-06-01 (claude) — Sprint 4b: dedup 운영 FP 측정 도구 (queue accept/reject)

**작업**: dedup_review_queue의 **운영자 결정** 누적분으로 실 false-positive율을
집계하는 측정 도구. dedup-fp 리포트(대표 평가셋)의 운영 데이터 후속 — 큐가 채워지면
실 FP율이 자동 측정된다.

- **infra/status_repo**: `DedupQueueFpStats` + `dedup_fp_stats(by_status)` 순수
  함수 — confirmed=merged+accepted(진짜 중복), FP=rejected, ignored·pending은 제외.
  `precision=confirmed/resolved`, `fp_rate=rejected/resolved`(resolved=0이면 None).
- **CLI**: `ktmctl status` 출력에 `dedup FP(운영)` 라인 추가 — 기존
  `gather_status_counts`의 dedup_queue_by_status를 재사용(새 쿼리 없음). 검토 완료
  후보 0이면 "검토 완료 후보 없음" 표시.
- **리포트 연결**: `docs/reports/dedup-fp-measurement-2026-06-01.md` §6에 운영 측정
  도구 경로 명시(대표 평가셋 → 실 운영 accept/reject 측정으로 이행).
- **테스트**: unit 7(dedup_fp_stats 6 — empty/pending-only/merged+rejected/accepted/
  ignored-제외/all-rejected + status 포맷 FP 라인 1).
- **검증(WSL)**: ruff clean / mypy --strict 60 files / import-linter 4 kept / 전체
  **826 passed**(819 → +7).
- **Sprint 4b 3종(Step C / Step D / dedup 운영 FP 도구) 완료.** Step A~D 4단계
  lifecycle + dedup 운영 측정까지 닫힘.

## 2026-06-01 (claude) — Sprint 4b: Step D on-demand 상세 라우터 (debug-ui)

**작업**: MOIS Step D(`mois_license_detail`) — debug-ui `GET /debug/mois-license/
{license_id}`. 사용자 명시 트리거 단건 상세, **캐시만·적재 없음**(SPRINT-4 §2.1).

- **infra**: `get_primary_source_detail`(읽기 전용) — `source_entity_id`로 primary
  link 1건을 찾아 원본 provider payload(`source_records.raw_data`) + feature core를
  조립. JSONB(address/detail/raw_data) 디시리얼라이즈. 없으면 None.
- **debug-ui**: `routers/mois_detail.py` — `GET /debug/mois-license/{license_id}`
  (license_id = `{slug}::{mng_no}`). 프로세스 내 TTL 캐시(300s, `clear_detail_cache`)
  — 반복 클릭 시 재조회 회피, **DB write 없음**. 미적재 404. `MoisLicenseDetailResponse`
  (cached 플래그 포함). app.py에 `features_routes_enabled`+`debug_routes_enabled` gate로
  등록. openapi.json 재생성(drift EXIT=0).
- ADR-006: provider 라이브러리 미import — on-demand fetch가 아니라 **적재된 raw_data
  재사용**(MOIS는 DB-backed이라 public REST detail 없음). 운영 데이터 재조회만.
- **테스트**: debug-ui unit 4(마운트/disable unmount/404/상세+캐시 히트) + main
  integration 1(get_primary_source_detail round-trip + None). 
- **검증(WSL)**: ruff clean / mypy --strict main 60 + debug-ui 13 / import-linter 4
  kept / openapi drift EXIT=0 / main **819 passed** + debug-ui **117 passed**.
- **다음**: dedup 운영 FP 측정 도구(queue accept/reject) — Sprint 4b 마지막 항목.

## 2026-06-01 (claude) — Sprint 4b: Step C 폐업/취소 처리 (feature inactive)

**작업**: MOIS Step C(`mois_license_features_closed`) — provider가 폐업/취소 통지한
인허가의 대응 feature를 `status='inactive'`로 전환(ADR-017 — place 무기한 유지,
status만). Sprint 4b 1번째.

- **infra**: `inactivate_features_by_source_entity_ids`(soft-delete inverse — 주어진
  source_entity_id 집합에 **속하는** primary-source feature를 inactive). 빈 집합 no-op.
- **providers/mois**: `license_source_entity_id(record)` 헬퍼(자연키 `{slug}::{mng_no}`,
  변환 없이 폐업 record→feature 매칭 키 추출). 변환기 natural_key도 이 헬퍼로 단일화.
- **mois.py**: `close_mois_license_features`(폐업 record→entity_id→inactivate,
  feature 생성 없음) + `run_mois_license_closed_job`(advisory lock `import:mois:closed`
  + import_jobs + closed dataset cursor 전진) + `MoisClosedJobResult`. inactivation
  대상은 `target_dataset_key`(feature가 사는 bulk), cursor/lock은 closed dataset.
- **client + CLI**: `run_mois_license_closed_job` 메서드 + `import mois --mode closed
  --cursor <값>`. `--cursor` 미지정 → exit 2.
- **테스트**: unit 3(closed 파서 + 포맷 2) + integration 7(close 비활성화/미매칭
  no-op/job+cursor; cli closed inactivate/cursor 누락 exit 2). 
- **검증(WSL)**: ruff clean / mypy --strict 60 files / import-linter 4 kept / 전체
  **818 passed**(810 → +8).
- **다음**: Step D on-demand detail 라우터(debug-ui) + dedup 운영 FP 측정 도구.

## 2026-06-01 (claude) — Sprint 4a: dedup false-positive 측정 + ADR-016 검토

**작업**: dedup scoring(ADR-016) false-positive를 대표 라벨 평가셋으로 측정하고
가중치(0.45/0.35/0.20)·임계값(0.85/0.65) 조정 필요 여부 판단.

- **방법**: 실제 `score_pair`/`classify_decision`로 14쌍(true dup 7 + distinct 7,
  모두 blocking 범위 내 — 100m·같은 bjd·같은 kind로 사전 필터되므로 distinct는
  "가까운 별개 장소") 채점.
- **결과**: AUTO 임계(≥0.85) precision **100% / 오토머지 FP 0건**(핵심 안전속성).
  MANUAL 임계(≥0.65) precision 63.6% / recall **100%**(true dup 7건 전부 큐 진입).
  distinct 7건 중 auto 0 / manual 4 / keep 3.
- **manual FP 4건 원인**: 카테고리 접미사 공유(약국/마트/교회 2글자 → name_sim
  0.67) + 짧은 브랜드명 우연 겹침(스타벅스↔투썸 0.47), 같은 건물·같은 카테고리와
  결합. 모두 AUTO 아래 → 운영자 reject(설계 의도).
- **결론/권고**: **가중치·임계값 변경 없음.** 안전성 검증됨(오토머지 오류 0, true
  dup 누락 0). 검토 큐 noise는 설계 의도(가까운 동일-카테고리 별개 장소). 접미사
  stripping은 접두사 충돌 FP(`강남약국`↔`강남마트`→`강남`)를 새로 만들어 권하지
  않음(`_NAME_SUFFIX_TO_STRIP` 빈 튜플 보수 설정과 일치). production은 운영자
  accept/reject 누적분으로 실 FP율 재측정.
- **산출물**: `docs/reports/dedup-fp-measurement-2026-06-01.md` +
  `tests/unit/test_dedup_fp_measurement.py`(회귀 가드 4건 — 오토머지 FP 0 / true-dup
  recall 100% / manual precision floor 0.55 / auto precision 100%). 코드 변경 없음.
- **검증(WSL)**: ruff clean / mypy --strict / 전체 **810 passed**(806 → +4).
- **Sprint 4a 3종(dedup-merge / Step B / dedup FP) 완료.** 남은 건 Sprint 4b(Step C
  폐업 / Step D detail / dedup 운영 데이터 재측정).

## 2026-06-01 (claude) — Sprint 4a: Step B 증분 적재 + cursor (ProviderSyncState)

**작업**: MOIS Step B(`mois_license_features_history`) 증분 적재 — 변경분만 upsert +
`provider_sync_state` cursor 전진. `provider_sync_state` 테이블은 이미 존재(cursor
JSONB) → **마이그레이션 불필요**.

- **신규 `infra/sync_state_repo.py`**: `SyncState` + `get_sync_state` /
  `record_sync_success`(cursor 전진 + last_success + 연속실패 0, UPSERT) /
  `record_sync_failure`(cursor 미전진 + last_failure + 연속실패 +1). raw SQL
  ON CONFLICT (provider, dataset_key, sync_scope).
- **mois.py**: `load_mois_license_features_incremental`(batched upsert, **prune
  없음** — 증분은 전체 snapshot이 아니라 사라진 record를 비활성화하면 오삭제. 폐업은
  Step C 책임) + `run_mois_license_incremental_job`(advisory lock 직렬화 + import_jobs
  추적 + 성공 시 cursor 전진/실패 시 record_sync_failure) + `MoisIncrementalJobResult`.
- **client + CLI**: `AsyncKorTravelMapClient.run_mois_license_incremental_job` +
  `import mois <file> --mode incremental --cursor <값> [--sync-scope]`. `--dataset-key`
  기본을 None으로 바꿔 모드별 해석(bulk→BULK / incremental→HISTORY). `--cursor` 미지정
  → exit 2. cursor는 `{"last_modified_date": <값>}`로 기록(provider가 다음 시작 위치
  결정, ADR-006).
- **테스트**: unit 3(incremental 파서 + 결과 포맷 2) + integration 9(sync_state_repo 5:
  get-none/success-advance/failure-increment/success-reset/scope-independent; mois_loader
  2: 증분 적재+cursor 전진 / no-prune; cli_import 2: 증분 cursor 영속 / cursor 누락
  exit 2). cli_import teardown TRUNCATE에 `provider_sync_state` 추가(CLI commit 격리).
- **검증(WSL)**: ruff clean / mypy --strict 60 files / import-linter 4 kept / 전체
  **806 passed**(794 → +12).
- **다음**: #3 실적재 후 dedup false-positive 측정 → ADR-016 가중치 조정. (Step C 폐업
  처리 + Step D detail은 Sprint 4b.)

## 2026-06-01 (claude) — Sprint 4a: dedup-merge 명령 + merge primitive (ADR-016)

**작업**: Sprint 4a 두 번째 CLI mutate 명령 `ktmctl dedup-merge`. ADR-016이
명시한 수동 병합 메커니즘(master 선정 + `feature_merge_history`)을 처음 구현했다.

- **신규 스키마(alembic 0007)**: `ops.feature_merge_history(merge_id, master_feature_id,
  loser_feature_id, score, review_id, merged_by, reason, merged_at)`. master/loser
  FK는 feature 하드 삭제 시 CASCADE, review_id FK는 큐 행 삭제 시 SET NULL(이력
  보존). `FeatureMergeHistoryRow` 모델 + alembic 검증 1건.
- **master 선정(core/scoring.py, 순수)**: `select_master(a, b)` — ADR-016 3순위
  (1) 좌표 보유 → (2) `updated_at` 최신 → (3) 원천 우선순위(`SOURCE_PRIORITY`:
  행안부 mois 50 > 국가유산/국립공원/산림청 45 > datagokr 35 > TourAPI 30 > … >
  사용자 0). 완전 동률은 feature_id 사전순(결정적). "좌표 정밀도"는 좌표 보유
  여부로 근사(좌표 있는 쪽 우선).
- **merge primitive(infra/merge_repo.py)**: `apply_feature_merge`(명시 master/loser)
  + `merge_from_review`(큐 후보 → master 자동 선정 → 병합). 단계: loser
  source_links를 master로 재지정(master가 이미 가진 충돌 source_record_key는
  drop) → loser feature soft-delete(`status='deleted'`+deleted_at, ADR-017) →
  history INSERT → 큐 행 `merged` 전이(pending 행만). `MergeError`(미존재/이미
  검토/master==loser). rowcount 대신 RETURNING+fetchall(코드베이스 컨벤션).
- **client + CLI**: `AsyncKorTravelMapClient.merge_dedup_review`(lock 미적용, 한
  transaction) + `ktmctl dedup-merge <review_id> [--merged-by --reason]`.
  **lock은 CLI가 소유**(layering — mutex 헬퍼는 cli) — 별도 lock 세션이
  `dedup-merge:{review_id}` advisory lock을 쥐고 client가 병합 수행. 미획득 시
  skip(exit 3), 미존재/이미 검토 시 exit 2.
- **인터페이스 결정**: SPRINT-4 §2.8 예시 `dedup-merge <feature_id>`는 후보쌍을
  **유일 식별**하는 `<review_id>`로 구체화(한 feature가 여러 pending 쌍에 속할 수
  있어 feature_id는 모호). lock 헬퍼 `dedup_merge_lock_key`는 generic(opaque id).
- **테스트**: unit 9(select_master/source_priority 5 + dedup-merge 파서·포맷 4) +
  integration 9(merge_repo 5: 전체흐름/충돌drop/미존재/이미merged/distinct guard;
  cli_dedup_merge 3: round-trip/lock-skip/unknown-key; alembic 1).
- **검증(WSL)**: ruff clean / mypy --strict 59 files / import-linter 4 kept / 전체
  **794 passed**(776 → +18).
- **다음**: #2 Step B incremental cursor(`ProviderSyncState` 테이블은 이미 존재 —
  cursor JSONB 컬럼 보유, 마이그레이션 불필요). 이어서 #3 dedup false-positive 측정.

## 2026-06-01 (claude) — Sprint 4a: ktmctl import mois 명령 (NDJSON → Step A bulk 적재)

**작업**: Sprint 4a 본 작업 — CLI mutate 명령의 첫 번째인 `ktmctl import mois`
(SPRINT-4 §2.8). 기존 read-only `status`에 이어 MOIS Step A bulk 적재 진입점을 박았다.

- **설계 핵심 (provider record source 주입)**: ADR-006상 CLI는 provider 라이브러리를
  런타임 import하지 않으므로, provider가 외부에서 export한 **provider-neutral
  NDJSON 파일**(한 줄당 JSON object)을 record source로 읽는다. `cli/records.py`의
  `MoisLicenseJsonRecord`(dict → `MoisLicensePlaceRecord` Protocol 만족 `__getattr__`
  래퍼, date 필드 ISO 파싱) + `iter_mois_license_records`(lazy streaming, 빈 줄 skip,
  줄번호 포함 에러).
- **mutex 중복 회피**: `run_mois_license_bulk_job`이 이미 내부에서
  `import:python-mois-api:<dataset>` advisory lock으로 self-serialize(ADR-039) +
  `import_jobs` 추적(ADR-011)하므로, CLI에서 같은 키 mutex를 **다시 감싸지 않는다**
  (자기 충돌 회피). lock 미획득(다른 워커 적재 중)이면 skip → **exit 3**(실패 1과
  구분, 운영 스크립트 재시도 판단용).
- **geocoder 선택 보강**: `--geocoder-url` 주면 httpx + `KorTravelGeoRestClient` →
  `kor_travel_geo_reverse_geocoder`로 좌표 → bjd_code 역지오코딩 보강. 미지정 시 mois
  `legal_dong_code`만 사용. client 수명은 async 컨텍스트 소유(ADR-002).
- **산출물**: `cli/records.py` 신규 + `cli/main.py` import 서브명령
  (`--dataset-key`/`--batch-size`/`--geocoder-url`/`--source-checksum`). 상수는
  정본 모듈(`providers.mois.DATASET_KEY_BULK`/`mois.DEFAULT_BATCH_SIZE`)에서 직접
  import(client는 별칭 비노출).
- **테스트**: unit 17(records 파싱 11 + import 파서/포맷 6) + integration 2(NDJSON
  round-trip 적재 PROMOTED 2건/EXCLUDED skip + advisory lock 점유 시 skip·미적재).
- **검증(WSL)**: ruff All checks passed / mypy --strict 58 files / import-linter 4
  kept / 전체 **776 passed**(757 → +19).
- **다음**: `ktmctl dedup-merge <feature_id>` — manual merge. merge primitive
  (생존 feature로 supersede + source_link 재지정 + dedup_review_queue 상태 갱신)이
  아직 없어 infra 1차 함수 설계부터 필요(별도 PR). 또는 Step B incremental cursor.

## 2026-06-01 (claude) — krex 휴게소 라이브 적재 재검증 (upstream entrpsNm fix 후)

**작업**: 사용자가 `python-krex-api`의 `entrpsNm` 미추종(ADR-044 provider 책임)을
수정 완료 → 휴게소 적재 라이브 테스트 재실행.

- **upstream fix 확인**: `python-krex-api` PR#6(`fix/restarea-entrpsNm-field`,
  `ea4c08d`) origin 머지 → 로컬 체크아웃 `F:\dev\python-krex-api` ff pull(`72b74d7`).
  `client.py`가 `_required(row, "entrpsNm", "restAreaNm", "serviceAreaName")`로
  `entrpsNm` 우선 처리.
- **재검증(WSL, testcontainers postgis 16-3.5 + alembic 0001~0006)**: 휴게소 60건
  fetch(좌표 60/60) → `rest_areas_to_bundles` 60 변환 → `load_bundles` 60 적재.
  DB features 60 / `coord_5179` SRID=5179 60/60 / category `06040101` 60/60 —
  **PASS**. 자연키 `휴게소명::노선::방향`(3-part `_rest_area_natural_key`, 좌표
  미포함). 이 데이터셋은 노선·방향이 None이라 사실상 휴게소명(+bjd_code)이 식별키
  — 좌표는 feature_id/dedup에 무관(source_record payload_hash에만), 동명 휴게소는
  좌표가 달라도 dedup 충돌. 본 lib 코드 변경 없음(변환은 최초부터 정상).
- **문서**: `docs/reports/provider-live-test-2026-06-01.md` §2/§4/§6/§7 갱신 — krex
  ❌→✅ 60, 후속 항목 완료 처리. 라이브 스크립트는 임시(`scripts/_live_krex_*`)로
  작성 후 제거(provider lib는 런타임 의존 아님, ADR-006).

## 2026-06-01 (claude) — provider 다종 실데이터 라이브 적재 테스트 + notice alias 보강

**작업**: geocoder v2 전환에 이어 kma/opinet/krforest 등 다른 provider DB 적재를
실데이터로 검증(사용자 지시). 서비스키는 각 라이브러리 `.env`.

- **결과**: opinet(유가 54, place 06020000) / krheritage(국가유산 12, place
  01070100) / datagokr(축제 20, event 01000000) / kma(특보 7, notice 99000000)
  4종 변환·적재·5179 generated 검증 ✅. krex는 upstream 라이브러리 파싱
  에러(`entrpsNm` 필드명 미추종, ADR-044 provider 책임), krforest는 본 lib provider
  모듈 미구현(ADR-034 Sprint 5)으로 제외.
- **본 lib 수정(실데이터 발견)**: `dto/notice.py` `_ALIAS_MAP`에 KMA 기상특보 종류
  추가 — `호우`/`대설`(base) → heavy_rain/heavy_snow, 전용 canonical 없는 7종
  (`강풍`/`풍랑`/`태풍`/`건조`/`한파`/`폭풍해일`/`황사`) → generic `weather_alert`.
  누락 시 `weather_alerts_to_notice_bundles`가 NoticeDetail ValidationError로 적재
  실패하던 갭. unit test 1건 추가.
- **검증(WSL)**: mypy --strict 57 / ruff All checks passed / import-linter 4 kept /
  전체 **757 passed**. 상세: `docs/reports/provider-live-test-2026-06-01.md`.

## 2026-06-01 (claude) — geocoding kor-travel-geo v1 → v2 전면 전환

**작업**: 사용자 지시 — geocoder API를 v1(`GET /v1/address/*`, vworld level 파싱)
에서 v2(`POST /v2/{reverse,geocode}`, provider-neutral structured field)로 **완전
대체**. v2는 `CandidateV2.address.legal_dong_code` 등을 직접 제공해 level4LC 파싱이
사라진다.

- **산출물**:
  - `src/kortravelmap/geocoding.py` 전면 재작성 — Protocol(`KraddrAddressV2`/`KraddrRegionV2`/`KraddrCandidateV2`/`KraddrReverseV2Response`/`KorTravelGeocodeV2Response`) + `reverse_response_to_address`/`geocode_response_to_coordinate`(이름 유지, v2 응답 입력) + `KorTravelGeoRestClient`(`base_path='/v2'`, POST body) + 팩토리. v2 reverse도 road_name_code 제공.
  - debug-ui `routers/geocoding.py` — reverse `type` 파라미터 제거, geocode `refine` 제거·`fallback` 기본 `none`, raw path `GET /v1/address/*`→`POST /v2/*`. `settings.py` 설명 갱신. openapi.json 재생성(drift green).
  - 테스트: `tests/unit/test_geocoding.py`(41) + debug-ui geocoding router 4파일 v2 wire shape로 재작성(서브에이전트). `docs/address-geocoding.md` §3.1 v2 매핑표.
- **검증(WSL)**: mypy --strict main 57 + debug-ui 12 / ruff All checks passed / import-linter 4 kept / openapi drift EXIT=0 / 전체 main **756 passed** + debug-ui **158 passed**. v2 실연동(`127.0.0.1:12201`): reverse 종로구 → bjd 1111014700, geocode 왕복 정상.

## 2026-06-01 (claude) — geocoder 보강 라이브 재검증 (kor-travel-geo REST)

**작업**: MOIS 실데이터 라이브 테스트의 미검증 항목(geocoder 보강 실연동)을
kor-travel-geo REST(`127.0.0.1:12201`, 사용자 기동)로 검증.

- `bakeries` 영업중 + 좌표O + legal_dong=None 200건 → `KorTravelGeoRestClient`(httpx
  주입) + `kor_travel_geo_reverse_geocoder` + `cached_reverse_geocoder`를
  `license_records_to_bundles`에 주입.
- 결과: geocoder 미주입 0/200 bjd → **주입 200/200(100%) bjd 보강, f_global_* 0**.
  '원더쿠키' → bjd 1111014700(재동), feature_id `f_1111014700_p_*` 실제 법정동
  bucket. §4 설계 예측(ADR-009)이 실데이터로 100% 확인.
- 주의: `KorTravelGeoRestClient(base_path='/v1')`가 prefix를 붙이므로 httpx base_url은
  `/v1` 미포함(`http://host:12201`)로 줘야 함(중복 404 방지).
- 상세: `docs/reports/mois-live-test-2026-06-01.md` §5 추가. 코드 변경 없음.

## 2026-06-01 (claude) — dedup MOIS self-sibling (within-set pairwise)

**작업**: SPRINT-4 §2.2 — 한 dataset 안에서 같은 사업장이 2슬러그로 중복 등록된
경우(MOIS self-sibling)를 탐지해 dedup queue 적재.

- **산출물**:
  - `core/dedup.py` — `find_sibling_candidates(features)` within-set pairwise(i<j, self-pair/대칭 제외) + 공통 `_score_candidate` helper로 `find_dedup_candidates`와 스코어링 공유.
  - `AsyncKorTravelMapClient.sync_sibling_candidates` — 탐지 → `ops.dedup_review_queue` upsert (cross-provider `sync_dedup_candidates`와 같은 enqueue 경로).
  - tests: unit 6(같은 사업장 2슬러그/고유쌍/self-pair 제외/KEEP_SEPARATE/빈·단일/auto_merge 제외) + integration 1(MOIS 2슬러그 적재 → sibling 탐지 → 큐 적재 + FK).
- **검증(WSL)**: mypy --strict 57 files / ruff All checks passed / import-linter 4 kept / 신규 unit 6 + integration 1 / 전체 **751 passed, 5 skipped**.

## 2026-06-01 (claude) — kor-travel-map CLI 골격 + status 명령

**작업**: SPRINT-4 §2.8 CLI entry-point 신설. read-only `status` 명령 + argparse
프레임. mutate 명령(`import`/`dedup-merge`)은 provider record source 주입 설계 후
후속.

- **산출물**:
  - `src/kortravelmap/cli/main.py` — `kor-travel-map` argparse(`build_parser`) + `status` 서브명령(`KorTravelMapSettings.pg_dsn`/`--dsn`로 engine → `AsyncKorTravelMapClient.status_counts` → 출력) + `main(argv)` entry-point.
  - `infra/status_repo.py` — `gather_status_counts`(features 활성/비활성/kind별 + source_records provider별 + import_jobs state별 + dedup_queue status별) + `StatusCounts`. read-only raw SQL(ADR-004).
  - `AsyncKorTravelMapClient.status_counts` + `pyproject.toml [project.scripts] kor-travel-map`.
  - tests: unit 5(parser/format) + integration 2(빈/데이터).
- **검증(WSL)**: mypy --strict 57 files / ruff All checks passed / import-linter 4 kept(cli layer) / 신규 unit 5 + integration 2 / 전체 **744 passed, 5 skipped**. `ktmctl --help` 실동작 확인(entry-point 등록).

## 2026-06-01 (claude) — MOIS Step A 실데이터 라이브 테스트

**작업**: Sprint 4a MOIS 파이프라인을 행안부 LOCALDATA 실데이터로 end-to-end
검증 (사용자 지시). 서비스키는 `F:\dev\python-krmois-api\.env`
(`DATA_GO_KR_SERVICE_KEY`) — 단, 파일 다운로드 경로(`LocalDataFileClient`,
`file.localdata.go.kr`)는 키 불필요.

- **변환**: 4 PROMOTED 슬러그(bakeries/traditional_temples/public_baths/
  museums_and_art_galleries) 실데이터 변환 — category/place_kind 매핑 docs §6.1과
  100% 일치, 좌표 96~99% 보유(EPSG:5174→WGS84 mois 변환). EXCLUDED(pet_grooming)
  영업중 200건 → 0건 skip.
- **적재**: public_baths 300건 testcontainers PostGIS 적재 → 재조회 300, coord_5179
  generated SRID=5179(ADR-012), source_records 300. alembic 0001~0006 적용.
- **발견(데이터 정합성)**: 파일 다운로드 CSV에 법정동코드 컬럼 부재 →
  `legal_dong_code` 전부 None → geocoder 미주입 시 `f_global_*` bucket. 본 lib는
  좌표 reverse geocoding으로 보강 설계(ADR-009) — 운영 시 kor-travel-geo geocoder 주입
  필수. `opn_authority_code`는 bjd 미사용(payload만) 확인.
- 상세: `docs/reports/mois-live-test-2026-06-01.md`. (geocoder 보강 실연동 +
  OpenAPI 경로 법정동코드는 후속 — kor-travel-geo REST 미기동.)

## 2026-06-01 (claude) — CLI mutex 첫 도입 (cli layer 신설, ADR-039)

**작업**: SPRINT-4 §2.8 — `src/kortravelmap/cli/` layer 신설 + advisory lock 기반
CLI 명령 mutex. import-linter layered 최상위에 cli 추가.

- **산출물**:
  - `src/kortravelmap/cli/__init__.py` + `cli/mutex.py` — `mutex_lock`(blocking)/`try_mutex_lock`(non-blocking) async ctx (`infra.advisory_lock` 얇은 래퍼) + lock key 헬퍼(`import_lock_key`/`dedup_merge_lock_key`/`alembic_upgrade_lock_key`, §2.8 컨벤션).
  - `pyproject.toml` import-linter layers에 `kortravelmap.cli` 최상위 추가(`cli → client → providers → geocoding → infra → core → dto → category`).
  - `tests/unit/test_cli_mutex_keys.py`(4) + `tests/integration/test_cli_mutex.py`(3 — 상호배제/release/독립 키).
- **검증(WSL)**: mypy --strict 55 files / ruff All checks passed / import-linter 4 kept(cli layer 강제) / 신규 unit 4 + integration 3 / 전체 **737 passed, 5 skipped**.
- 실제 CLI 명령(`ktmctl import` 등 argparse/entry-point)은 후속 PR.

## 2026-06-01 (claude) — MOIS Step A streaming 배치 적재 (source DB 연결 준비)

**작업**: Step A bulk 적재를 대용량 source DB 스트림 대응 streaming 배치로 전환.
ADR-006상 mois를 import 안 하므로 iterator는 호출자 주입 — `records`로
`mois.db.iter_open_place_records(...)`를 그대로 넘기면 Step A가 완성된다.

- **산출물**:
  - `kortravelmap.mois`: `_batched` helper + `DEFAULT_BATCH_SIZE=500`. `sync_mois_license_features_bulk`/`run_mois_license_bulk_job`/client 메서드에 `batch_size` 인자 추가 — `batch_size`개씩 변환·upsert하며 snapshot key만 누적(메모리 바운드), 전체 적재 후 prune.
  - `infra/feature_repo.py`: `FeatureLoadResult.merge`(배치 결과 누적) + `load_bundles`도 `.merge()`로 정리.
  - `tests/unit/test_mois_batched.py`(7 — _batched 분할/순서/빈, merge 합산/항등) + `test_mois_loader.py` +1(batch_size=2 streaming 적재+prune 동치).
- **검증(WSL)**: mypy --strict 53 files / ruff All checks passed / import-linter 4 kept / 신규 unit 7 + integration 1 / 전체 **730 passed, 5 skipped**.

## 2026-06-01 (claude) — MOIS Step A 작업 통합 (advisory lock + import_jobs)

**작업**: advisory lock + import_jobs(앞 entry들) 위에 MOIS Step A bulk 적재를
작업 추적 + 단일 워커 직렬화로 감싸는 오케스트레이션.

- **산출물**:
  - `infra/jobs_repo.py` `start_import_job` — queue를 거치지 않고 곧바로 `state='running'` INSERT(self-driven inline job; enqueue+claim queue-worker 경로와 구분).
  - `kortravelmap.mois.run_mois_license_bulk_job` — `try_advisory_lock("import:python-mois-api:<dataset>")`로 단일 워커 직렬화(미획득 시 `acquired=False` skip) → `start_import_job`(running) → `sync_mois_license_features_bulk`(변환·upsert·snapshot prune) → `finish_import_job`(done/예외 시 failed+re-raise) + `MoisBulkJobResult`.
  - `AsyncKorTravelMapClient.run_mois_license_bulk_job` — client 진입점(한 transaction).
  - `tests/integration/test_mois_loader.py` +2 — done 추적+sync / lock 보유 중 skip(작업·feature 미생성).
- **검증(WSL)**: mypy --strict 53 files / ruff All checks passed / import-linter 4 kept / 신규 integration 2 / 전체 **722 passed, 5 skipped**.

## 2026-06-01 (claude) — ops.import_jobs 작업 큐 + jobs_repo (ADR-011)

**작업**: advisory lock helper 위에 ADR-011 작업 큐 영속화. 프로세스 재시작
안전성 + 다중 워커 직렬화(SKIP LOCKED). data-model.md §9.1 DDL 그대로.

- **산출물**:
  - `alembic/versions/0006_import_jobs.py` — `ops.import_jobs`(job_id/kind/payload/state/progress/current_stage/source_checksum/error_message/started_at/finished_at/heartbeat_at/created_at) + state/progress CHECK + 3 인덱스(state·kind_state·heartbeat partial).
  - `infra/models.py` `ImportJobRow` ORM.
  - `infra/jobs_repo.py` — `enqueue_import_job` / `claim_next_import_job`(advisory lock + `FOR UPDATE SKIP LOCKED`로 가장 오래된 queued→running) / `heartbeat_import_job` / `finish_import_job`(done→progress 100/failed/cancelled) / `recover_stale_running_jobs`(lifespan 복구 — heartbeat 만료 running→failed) + `ImportJob` dataclass.
  - `infra/__init__.py` export (jobs_repo + 누락됐던 soft_delete_features_not_in_snapshot 보강).
  - `tests/integration/test_jobs_repo.py`(9) — enqueue/claim FIFO/빈 큐 None/heartbeat/finish done·failed/invalid state raise/recover stale·fresh.
- **검증(WSL)**: mypy --strict 53 files / ruff All checks passed / import-linter 4 kept / 신규 integration 9 + alembic 0006 upgrade green / 전체 **720 passed, 5 skipped**.

## 2026-06-01 (claude) — advisory lock helper (ADR-011 기초)

**작업**: ADR-011 작업 큐 직렬화 / ADR-039 CLI mutex의 공통 기초인 PostgreSQL
advisory lock 헬퍼 추가. 사용자 결정에 따라 **helper만** (import_jobs 테이블 +
jobs_repo는 후속).

- **산출물**:
  - `src/kortravelmap/infra/advisory_lock.py` — `advisory_lock(session, key)`(blocking, `pg_advisory_lock`/`pg_advisory_unlock`) + `try_advisory_lock(session, key)`(non-blocking `pg_try_advisory_lock`, acquired bool yield) async context manager + `advisory_lock_key`(문자열 → BLAKE2b 8바이트 → signed int64 결정적 해시). session-level lock은 finally에서 명시 unlock(commit 자동해제 X).
  - `infra/__init__.py` export.
  - `tests/unit/test_advisory_lock_key.py`(3) + `tests/integration/test_advisory_lock.py`(3, 두 세션 상호배제/release/int 키).
- **conftest 방어 보강**: `pg_engine`에 `ALTER ROLE CURRENT_USER SET search_path`
  추가. bare `AsyncSession`이 connection을 recycle하면 asyncpg reset이
  connect-event의 session-level search_path를 지워 후속 unqualified `ST_*`가
  깨지던 잠복 버그 해소(advisory 테스트가 노출, migrated_engine과 동일 방어).
- **검증(WSL)**: mypy --strict 52 files / ruff All checks passed / import-linter 4 kept / 신규 unit 3 + integration 3 / 전체 **711 passed, 5 skipped**.

## 2026-06-01 (claude) — Sprint 4a MOIS snapshot prune (delete_not_in)

**작업**: loader(앞 entry)에 이어 Step A bulk snapshot soft-delete 추가. 사용자
결정에 따라 **snapshot delete_not_in만** (advisory lock / import_jobs / mois source
DB iterator는 후속).

- **산출물**:
  - `infra/feature_repo.py` — `soft_delete_features_not_in_snapshot(session, *, provider, dataset_key, source_entity_type, snapshot_source_entity_ids)`. 주어진 primary source의 활성 feature 중 snapshot에 없는 것을 `status='inactive'` + `deleted_at`으로 비활성화(ADR-017, place 무기한 유지). raw SQL `UPDATE ... WHERE feature_id IN (… source_links ⨝ source_records … NOT IN snapshot)` + RETURNING count. 이미 비활성은 skip(idempotent).
  - `kortravelmap.mois` — `delete_mois_license_features_not_in`(mois 래퍼) + `sync_mois_license_features_bulk`(변환→upsert→prune 한 단위 of work) + `MoisBulkSyncResult`(load 카운트 + deactivated).
  - `AsyncKorTravelMapClient.sync_mois_license_features_bulk` — client 진입점(한 transaction).
  - `tests/integration/test_mois_loader.py` +3 (snapshot 누락 soft-delete + idempotent / sync 1콜 load+prune / 빈 snapshot 전체 비활성화).
- **검증(WSL)**: mypy --strict 51 files / ruff All checks passed / import-linter 4 kept / integration 6(+3) / 전체 **705 passed, 5 skipped**.

## 2026-06-01 (claude) — Sprint 4a MOIS loader (변환 → 적재 오케스트레이션)

**작업**: MOIS provider 변환 코어(앞 entry)에 이어 적재 loader 추가. 사용자
결정에 따라 **loader 모듈만** (advisory lock / snapshot delete_not_in / mois
source DB iterator는 후속 PR).

- **산출물**:
  - `src/kortravelmap/mois.py` — `load_mois_license_features_bulk(session, records, *, fetched_at, dataset_key, reverse_geocoder)`. `providers.mois.license_records_to_bundles`(async 변환) → `infra.load_bundles`(idempotent upsert) 얇은 오케스트레이션. mois 라이브러리 런타임 import 안 함(Protocol 입력). commit은 호출자/감싼 transaction 소유(ADR-002/004).
  - `AsyncKorTravelMapClient.load_mois_license_features_bulk` — client 진입점(한 transaction).
  - `tests/integration/test_mois_loader.py` — testcontainers PostGIS 3건: PROMOTED 적재+EXCLUDED/미매핑/비영업 skip / 재적재 idempotent(feature 수 불변) / 전부 skip 시 빈 결과.
- **검증(WSL)**: mypy --strict 51 files / ruff All checks passed / import-linter 4 kept / 신규 integration 3 / 전체 **702 passed, 5 skipped**.

## 2026-06-01 (claude) — Sprint 4a 진입: MOIS provider 변환 코어

**작업**: ADR-034 9단계 ⑦ — MOIS 인허가(LOCALDATA) provider 변환 코어 추가. `python-mois-api`(`import mois`)의 `PlaceRecord`를 place `FeatureBundle`로 정규화. 사용자 지시에 따라 **변환까지만** (적재/dedup/CLI mutex는 후속 PR).

- **산출물**:
  - `src/kortravelmap/providers/mois.py` — structural Protocol `MoisLicensePlaceRecord`(`mois` 런타임 import 안 함, ADR-006) + async `license_record_to_bundle` / `license_records_to_bundles`(reverse_geocoder 보강). PROMOTED 42 슬러그만 승격 + `PROMOTED_CATEGORY_BY_SLUG`/`PROMOTED_PLACE_KIND_BY_SLUG` (docs §6.1, category 31코드 `_definitions` 검증). EXCLUDED 21 + 미매핑 + 비영업 skip. facility_info(building/medical/food/culture_sports).
  - `tests/unit/test_providers_mois.py` (23 test).
  - `providers/__init__.py` mois export + `__all__`.
- **설계 결정 2건**: ① 자연키 구분자 `::` (`make_feature_id`/`make_source_record_key`가 `|` 금지 → kma 패턴) ② marker_color `P-01` (미사용 팔레트). `docs/mois-feature-etl.md` §8 `|`→`::` 정정.
- **검증(WSL)**: mypy --strict 50 files / ruff All checks passed / import-linter 4 kept / 신규 23 test / 전체 699 passed·5 skip. 좌표는 mois가 변환한 WGS84 그대로(ADR-012/044, 좌표계 변환 X), legal_dong_code 1차 bjd_code·없으면 역지오코딩(ADR-009).
## 2026-06-01 (codex) — PR review 누락 보강 + 문서 정합성 sweep

**작업**: 사용자 지시 "4일전 PR부터 검색해서 리뷰를 달지 않은 PR에는 상세리뷰"에
따라 2026-05-28 이후 PR #45~#114를 GitHub에서 조회했다. review submission이 없던
PR #61~#114에 한국어 사후 상세 리뷰를 등록했고, 재조회 결과 review 누락 PR 0건을
확인했다.

**문서 보강**:
- `AGENTS.md`/`SKILL.md`/`docs/sprints/SPRINT-4.md`: 이미 accepted인 ADR-035/039/040/041을
  proposed로 표기하던 문구를 정정.
- `docs/address-geocoding.md`/`docs/resume.md`/`docs/sprints/README.md`: geocoding 현재
  endpoint 정본을 REST `/v1/address/*` + 로컬 `http://127.0.0.1:12201`로 명확히 하고,
  서비스 메타 버전 2.0과 endpoint prefix v1이 서로 다른 축임을 명시.
- `docs/address-geocoding.md`: `PlaceCoordinate` 잔존 예시를 `Coordinate`로 교체.
- `docs/tasks.md`: 오래된 Sprint 2 진행 중 문구를 PR#114 기준 현재 상태와 Sprint 4 4a
  다음 작업으로 갱신.

**검증**: review 누락 목록 재조회 결과 없음. 문서 변경은 `ruff format --check` 대상이
아니므로 Markdown 링크/키워드 검색과 `git diff --check`로 확인.

