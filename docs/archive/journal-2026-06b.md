# journal 아카이브 — 2026-06-02 ~ 2026-06-10

> `docs/journal.md`에서 분리한 과거 기록(역시간순). 현행 정본은
> [`docs/journal.md`](../journal.md)이며, 전체 아카이브 목록도 거기에 있다.
> 이 파일은 읽기 전용 이력이다 — 새 엔트리는 `docs/journal.md` 상단에 추가한다.

## 2026-06-10 (claude) — cross-repo 완성도·정합성 검토 보고서 4종 (코드無)

사용자 지시: kor-travel-map · TripMate · kor-travel-concierge 3-시스템을 기획자/개발리더 시각에서
교차 검토(사용자 UX/admin UX/API 계약/R&R/문서 정합성), 정본 미반영·보고서만 작성.
형제 repo는 origin/main 임시 워크트리로 실측 (TripMate 로컬 워크트리가 133커밋 stale였음).

- **산출물**: `docs/reports/{service-completeness-review, tripmate-side-actions,
  decisions-needed, consistency-uplift-plan}-2026-06-10.md` 4종 + kor-travel-concierge repo에
  `docs/cross-repo-consistency-actions-2026-06-10.md` 직접 전달.
- **핵심 발견**: ① TripMate batch 파싱이 `items`를 읽음(krtour는 `found`) ② TripMate
  feature 라우터가 구모델 etl_bridge stub에 배선 + 평면 `lon/lat` 미반영 ③ TripMate
  문서의 "krtour HTTP 미존재" 전제(DEC-01)가 노후 — :12301 `/v1`은 완비 상태
  ④ kor-travel-concierge export(T-066)는 미구현이나 계약 스펙은 krtour fetcher와 정렬 확인
  ⑤ reject/tombstone skip 라이프사이클, RustFS 버킷 소유권, 제보 릴레이, 계약 정본
  위치 등 의사결정 9건(D-01~09) 분리 정리.
- 정본(ADR/tasks/resume 등) 반영은 사용자 승인 후 진행. 다음 작업 순서(T-212d/e)는 불변.

## 2026-06-10 (codex) — T-216f/g REST 명명 + 재적재 안전성 + TripMate-agent provider

**작업**: ADR-048/T-216a~e의 REST 명명 정합성을 물리 DB/ORM/repo/API/OpenAPI/frontend type까지
전파하고, 전 표면 계약 정본을 `docs/rest-api.md`로 수렴했다. 이어 재적재 충돌 보강과
TripMate-agent YouTube provider 소비 경계를 구현했다.

- **DB/ORM/repo**: `review_key`→`review_id`, `violation_key`→`issue_id`, ops surrogate
  `*_key`→`*_id`, `import_jobs`/`offline_uploads`/`feature_update_requests` lifecycle
  `state`→`status`. Alembic `0023_t216f_rest_names` 추가.
- **계약 산출물**: OpenAPI admin/user spec과 frontend generated type을 재생성했다.
  `docs/tripmate-rest-api.md`는 소비 매핑 view로 유지하고 세부 계약은 `docs/rest-api.md`에 위임.
- **원격 반영**: #330 재적재 안전성 리포트와 #331 read>>write MV 재검토를 최신 base로 반영하고,
  이어서 재적재 F-2/F-1을 해결했다. 사용자 변경은 `feature_versions.MAX(version)+1` 단조 row로
  보존하고, dedup merge loser는 status override로 provider 재적재 부활을 차단한다.
- **TripMate-agent provider**: `kor-travel-concierge-youtube` canonical provider, `youtube_place_candidates`
  변환 함수, Dagster REST fetch/resource/asset/schedule, fake 기반 unit 테스트를 추가했다.
  `reject`/`tombstone`은 bundle로 적재하지 않고 후속 export ledger에서 상태 전이로 처리한다.
- **문서 재독/정합성 sweep**: 다음 작업 전 README/SKILL/architecture/decisions/tasks/resume/
  provider-contract/external-apis/Dagster 문서를 다시 확인하고 ADR-049, provider env, schedule,
  T-212d 재측정 pass를 반영했다. 다음 순서는 T-212d 재측정/MV 판단이다.

## 2026-06-10 (claude) — read>>write Materialized View 도입 재검토 + 문서 보강 (T-101, 코드無)

사용자 지시: "읽기가 압도적으로 많으므로 MV 도입 검토하고 문서 보완. 코드작업 금지."
실제 read 경로를 코드(`feature_repo.py`)·스키마(alembic `0002`)로 재조사 후 `docs/performance.md
§9.3` 재작성 + `tasks.md` T-101 재타깃.

- **전제 정정**: 원래 §9.3의 "feature + 7 detail flatten" MV는 **무효** — ADR-018로 detail은
  `feature.features.detail` 단일 JSONB(per-kind detail 테이블 없음). 단건/배치/bbox read는 이미
  단일 테이블 조회. 코드의 `AS MATERIALIZED` CTE는 planner 힌트지 영속 MV가 아님(혼동 정리).
- **재타깃 1순위 = 클러스터 rollup MV** `mv_feature_cluster_counts`: viewport 이동마다 재계산되는
  `GROUP BY sido/sigungu/legal_dong_code` 집계를 사전집계. rollup row ≪ feature 본수 → 디스크 유리.
  **의미 변화**(exact-viewport→region-total + region centroid) 택일을 시범 PR에서 확정 필요.
- **2순위 = primary-source LATERAL**(nearby/admin): MV보다 적재 트랜잭션 내 denormalized 유지 컬럼
  (`primary_provider`/`primary_dataset_key`) 권장 — stale 윈도우/refresh job 불요.
- refresh orchestration은 batch gate `mv_refresh`(T-200/T-RV-41)가 이미 존재 → 카탈로그 등록만.
- 코드/마이그레이션 변경 없음. 문서+task 전용. **kor-travel-concierge provider는 API 변경 중이라 보류**
  (추후 재검토). 사용자 변경 feature 버전관리 admin UI(T-215d/T-104 계열)는 별도 진행.

## 2026-06-10 (claude) — 데이터 재적재 안전성 검증 + 문서화 (충돌·결측·엎어쓰기)

사용자 지시로 재적재 안전성 꼼꼼 검증. (분석 초기에 stale `sandbox/claude` 트리를 보고 오판
했다가 origin/main으로 재검증해 정정.) 결과: `docs/reports/data-reload-safety-2026-06-10.md`.

- **엎어쓰기 ✅**: `_UPSERT_FEATURE_SQL` 전 컬럼이 `data_origin='user_request' AND data_version>0`
  이면 보존(provider 재적재가 사용자 편집 안 덮음). 가드 `>0`이라 단조 버전 호환. source_record DO NOTHING.
- **결측 ✅**: snapshot cleanup이 `data_origin<>'user_request'` + `deleted_at IS NULL`만 soft-delete
  (사용자 feature·기삭제분 제외). cursor 실패 시 미전진.
- **충돌 ✅**: ON CONFLICT + advisory lock(offline/import/merge) + dedup queue pending만 갱신.
- **F-1(Medium)**: dedup merge 비영속 — 재적재가 merge된 loser 부활→중복 재생성(가드/redirect 미설정).
- **F-2(요건 gap)**: 버전이 binary v0/v1(write `version=1` 하드코딩). 사용자 요건은 단조
  v0,v1,v2,v3…+디폴트=최신. 스키마(`data_version` Integer≥0)·재적재 가드는 호환, 쓰기만 보강.
- 후속 task T-215d(단조화)·T-104(merge 영속화) 추가. 문서+task 전용.

## 2026-06-09 (codex) — T-216a~e REST 계약 표면 정리

**작업**: 관련도가 높은 `/v1` mount, pagination/envelope, error, REST 표면 명명, OpenAPI/frontend/e2e
갱신을 한 PR 범위로 묶었다.

- **REST 표면**: admin/ops/debug/public feature API를 `/v1`로 clean cut하고, 성공 응답은 공유
  `Meta`(`request_id`, `meta.page`, `meta.cluster`)로 통일했다.
- **명명/파라미터**: `page_size`, `status`, `issue_id`, `review_id`, `log_id`를 REST 표면 정본으로
  맞추고 구 `data.next_cursor`/`meta.count`/`{error:{...}}` shape를 제거했다.
- **검증 표면**: OpenAPI admin/user spec과 frontend generated type/API hook/UI/e2e mock을 새 계약에
  맞췄다. 물리 DB/ORM/repo rename은 T-216f 별도 migration PR로 남긴다.

## 2026-06-09 (claude) — T-210 정리: a 닫기 + b/c/d 외부(TripMate repo) 태그

사용자 질문(T-210 인덱스에 설명 누락 + 불필요한가)에 대응. 인덱스 생성 스크립트가
`T-210x — 설명` em-dash 앞만 잘라 ID만 남은 defect 수정. T-210a는 이번 세션 ADR-048/
rest-api.md/tripmate-rest-api.md 재정비로 흡수 → 닫음(Sprint5 재대조는 T-212e closure). 
T-210b/c/d는 TripMate 저장소 작업이라 외부 태그(추적만), T-210e만 본 저장소 actionable
(T-212e 후 codegen). 문서 전용.

## 2026-06-09 (codex) — T-215c feature change workflow e2e

**작업**: T-215b admin UI의 e2e workflow를 생성 타입 기반 route mock으로 보강.

- **Typed mock**: `components["schemas"]`에서 feature change record/list/write body/response 타입을
  파생해 mock DTO drift를 type-check에서 잡게 했다.
- **Workflow e2e**: pending→approve→applied, immediate mode create→applied,
  update request 생성, delete request 생성→approve, soft delete 완료 표시와 action delete
  필터를 검증한다.
- **Route hygiene**: backend API mock은 Next RSC prefetch를 통과시켜 frontend document 요청과
  admin REST API 요청을 분리했다.

## 2026-06-09 (claude) — T-102 pg_prewarm 부팅 후 warm-up (mechanism)

보류(v2 1차 외) 항목이지만 사용자 지시로 메커니즘 구현. migration 0022(확장) +
`infra/prewarm.py`(`prewarm_relations`, to_regclass 필터·확장 미설치 no-op) + docker-compose
postgres autoprewarm(shared_preload_libraries) + `/ops/health-deep` prewarm 컴포넌트.
통합 3 + ops 7 passed, ruff/mypy(86+25)/drift/lint-imports green. 효과는 도입 조건 충족 시.

## 2026-06-09 (claude) — T-017(maki drift gate) 완료 + T-018(KNPS) close

- **T-017**: `packages/map-marker-react/`는 `maki.ts`/`marker.ts`/`palette.ts`로 이미 추출돼
  있었고(ADR-043 monorepo share), 누락은 **drift gate 테스트**뿐. `test_category_maki_
  consistency.py` 추가 → 실제 drift 검출(Python category maki 46종이 TS MAKI_GLYPH에 없음)
  → maki.ts에 46 글리프 보강 → 2 passed. ADR-029→043 supersede.
- **T-018**: KNPS provider 모듈(`providers/knps.py` point/geometry)+dagster fetcher/asset이
  PR#77/#78로 이미 구현·머지됨. 부모 task만 미체크였어 close. notice source(access_restriction/
  fire_alert)는 후속 ADR로 분리. 회귀 확인.
- tasks.md 인덱스 19건, journal/resume. 문서+테스트.

## 2026-06-09 (claude) — T-RV-53/54 close-out (krforest 휴양림·수목원 / standard_data 박물관·미술관)

**작업**: T-RV-53·T-RV-54 부모 task 닫기. sub-task(a transform / b dagster / c dedup /
d ETL preview)는 2026-06-07 전부 머지 완료, 부모 rollup만 미체크였다. main 산출물 확인 +
회귀(transform 16 + dagster 9 passed) green → 부모 [x]. 실데이터 fetch는 T-212e 이월. 문서 전용.

## 2026-06-09 (codex) — T-215b feature change queue admin UI

**작업**: T-215a에서 추가한 feature add/update/delete change request API를 admin UI에 연결.
작업 단위 PR용으로 T-215b만 닫고, e2e 심화(T-215c)는 별도 PR로 남긴다.

- **Frontend**: `/admin/features/change-requests` route 추가. 목록 필터(state/action/q/limit),
  payload 상세 panel, add/update/delete 요청 form, approve/reject 버튼, nav link를 연결했다.
- **API hook**: `src/api/features.ts`에 OpenAPI 타입 기반 feature change query/mutation hooks를
  추가했다. 중복 REST 경로는 만들지 않고 `/admin/features` + `/admin/features/change-requests*`
  정본 endpoint만 사용한다.
- **Backend schema**: `GET /admin/features/change-requests` meta에 `review_mode`를 추가해
  `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE` 값을 빈 큐에서도 표시한다.
- **OpenAPI**: `openapi.json`과 frontend generated type을 재생성했다.

## 2026-06-09 (claude) — T-214 tail (e/f/g/h): pagination/param·error 규약 + debug health/version 제거

**작업**: 사용자 지시로 T-214e→f→g→h를 한 PR로. (이어서 T-214h 포함 지시.)

- **T-214e(code)**: `/v1/features/search` bbox CSV→분리 4-float, `limit`→`page_size`,
  `_parse_bbox_csv` 삭제. 규약: pageable=page_size+cursor / bounded map=limit / bbox=4-float.
- **T-214f(결정)**: POI cache target write는 admin/operator flow 전용(직접 write 미허용).
- **T-214g(doc)**: 표준 헤더 규약 표(`docs/rest-api.md §4.1`) + 에러 코드 enum 고정.
- **T-214h(code)**: `/debug/health`·`/debug/version` 제거(ADR-048 clean cut, 공용과 중복).
  `health.py`/`version.py` 삭제, app.py/__init__ 정리, test_routers 재작성. frontend
  `useHealth`/`useVersion`을 public `/health`·`/version`(envelope) 소비로 repoint
  (client.ts 타입/경로 + home-client 필드). dedup-review 복수화는 T-216e로 이월.
- **검증**: ruff/mypy --strict(25)/admin pytest **235 passed**/OpenAPI drift/lint-imports/
  frontend gen:types:check·type-check(src+e2e)·eslint green.

## 2026-06-09 (claude) — tasks.md 분리: 진행(tasks.md) / 완료·아카이브(tasks-done.md)

**작업**: tasks.md가 1567줄로 길어 확인이 어려워 분리. 블록(섹션/Phase) 단위로 열린 `[ ]`
항목 유무로 라우팅 — 열린 항목 있으면 tasks.md, 없으면 tasks-done.md. 유실 0(27 open 전부
tasks.md). tasks.md 상단에 "진행 중인 작업 인덱스"(27건) 추가. CLAUDE/AGENTS/SKILL/
agent-guide/README의 백로그 포인터에 분리 반영. 문서 전용.

## 2026-06-09 (claude) — T-214b: 사용자/서비스 API `/v1` prefix 도입

**작업**: `features`/`categories`/`providers` 표면을 `/v1`로 clean cut(ADR-048). PR→머지.

- **백엔드**: `app.py`에서 `include_router(features/categories/providers, prefix="/v1")`
  (mount 1곳 전환, ADR-046). liveness `/health`·`/version`·admin/ops/debug는 비버저닝 유지
  (admin/ops `/v1`은 T-216a). `USER_OPERATIONS`를 `/v1/*`로 갱신(liveness 제외).
- **재생성**: `openapi.json`/`openapi.user.json`(WSL export) + frontend `types.ts`. user spec
  paths 전부 `/v1/*`(+ `/health`·`/version`), admin/ops 비버저닝 유지 확인.
- **frontend 호출부**: `api/features.ts`(in-bbox/detail/weather)·`api/poiCacheTargets.ts`
  (by-target 런타임 문자열 + `paths[...]` 타입)에 `/v1` 적용. Next.js nav route `href="/features"`
  는 프론트 라우트라 그대로. e2e mock `**/v1/features/nearby/by-target**`.
- **테스트**: user-surface 경로 문자열 `/v1` 일괄(문자열 시작 경계로 `/admin/features` 등은 제외).
- **검증**: ruff/mypy --strict(27)/admin pytest **238 passed**/OpenAPI drift/lint-imports/
  frontend gen:types:check·type-check·eslint green. (next build의 `/admin/dagster` prerender
  실패는 Windows 로컬 기존 이슈 — 변경 revert 후에도 동일, CI Linux는 통과.)

## 2026-06-09 (claude) — `/tripmate/*` namespace 제거 → `POST /features/batch` 일반화

**작업**: 사용자 지시("kor-travel-map은 TripMate에만 묶이지 않음 — `/tripmate/` endpoint 제거").
batch를 일반 feature service read로 옮기고 모든 문서·OpenAPI·frontend·테스트를 갱신. PR→머지.

- **코드**: `tripmate_router`(prefix `/tripmate`) 제거. `POST /tripmate/features/batch` →
  `POST /features/batch`(`features_router`). service-token은 router-level → **route-level
  `dependencies=[Depends(require_service_token)]`로 유지**(generic 토큰이라 TripMate 종속
  아님, #314 보안 통제 보존). `USER_OPERATIONS` allowlist·app.py wiring·`__init__` export·
  핸들러/스키마 docstring 갱신.
- **재생성**: `openapi.json`/`openapi.user.json`(WSL `export_openapi.py --profile all`) +
  frontend `types.ts`(Windows `npm run gen:types`). `/features/batch` + ServiceToken 유지,
  `/tripmate` 0건 확인.
- **테스트**: `test_auth.py`/`test_features_router.py`/`test_export_openapi.py` 경로 갱신
  (`test_feature_update_requests_router`의 `/tripmate/feature-update-requests` 부재 검증과
  `external_system="tripmate"` 데이터값은 유지).
- **문서**: rest-api.md(§0/§1.2/§1.3/§1.7/§2.2/§5), tripmate-rest-api.md, decisions.md
  (ADR-005/045 D-1·ADR-048), tasks.md(T-214d 완료), openapi-admin-contract.md,
  debug-ui-admin-workflows.md, tripmate-integration.md, CHANGELOG. (reports/* 과거 스냅샷 보존.)
- **검증**: ruff/mypy --strict(27)/44 tests/OpenAPI drift/lint-imports(4) green.

## 2026-06-09 (codex) — PR #316 3차 잔여 정합성 반영

**작업**: PR #316 추가 리뷰의 잔여 2건(batch `items` map 충돌, in-bounds `cluster_unit` 위치)과
기존 문서 포인터 drift를 반영했다.

- Batch 조회는 service-to-service 표면 `POST /v1/tripmate/features/batch`로 고정하고,
  id-keyed map은 list `items[]`와 충돌하지 않게 `data.found`로 분리했다.
- in-bounds `cluster_unit`은 payload가 아니라 `meta.cluster.cluster_unit`으로 이동했다.
- base URL은 host root까지만 포함하고 path가 `/v1`를 명시하도록 고정했다.
- `docs/tripmate-rest-api.md`를 전면 축소해 TripMate 소비 매핑 view로 만들고, 전 표면 계약 정본은
  `docs/rest-api.md` 하나로 수렴했다.
- AGENTS/SKILL/README/tasks ADR 번호 포인터를 001~048 accepted / 다음 049로 정렬했다.

## 2026-06-09 (claude) — ADR-048 #316 TripMate 재리뷰(A–F) 반영 + 2차 오류 정정

**작업**: PR #316에 올라온 TripMate-소비자 재리뷰(호환성→정합성 입장 전환, A–F)를 판단·반영.
무-호환 방향과 정렬되며, **2차의 `cluster_key→cluster_id` 개명이 오류**임을 잡아줬다. PR까지, 보류.

- **(C) `cluster_key` 자연키로 재분류 → 유지(2차 `cluster_id` 철회)**. 코드 확인
  (`feature_repo.py` rollup): `cluster_key`={행정코드 컬럼}(sido/sigungu/eupmyeondong) = **자연키**
  → §3.1 규칙상 `*_key`가 맞음. "동결/compat"이 아니라 **본질**로 분류.
- **(B) 좌표명 cross-repo 정렬 = `lon`/`lat`**(ADR-048 #10): TripMate DEC-07(`longitude`/
  `latitude`)을 `lon`/`lat`로 하향 — 경계 매핑 0, terse payload.
- **(D) `feature_id` 값 불변식 명문화**(§3.2, #11): provider 재적재·편집·버전승급·soft delete에
  값 불변. 정체성 변경=새 feature+link. (소비자 FK/snapshot 영속 — 안정성 최우선.)
- **(E) envelope 불변식 lock**(§3.3, #12): `meta`/`request_id` 항상 present, `next_cursor`
  항상 키(소진 시 `null`, omit 금지).
- **(F) `/vN` major 거버넌스**(§1.2, #13): pre-1.0 in-place breaking, v1.0.0 GA에서 `/v1`
  동결→이후 `/v2`+N-1, OpenAPI major별 export.
- **(A) clean cut**: 2차에서 이미 dual-support 제거 — 재리뷰의 모순 지적(shim 금지↔alias)
  해소 확인. ADR-048 결정 #6/#7 정정 + #10~#13 신설, rest-api.md §1.2/§3.1/§3.2/§3.3/§5/§7/§8,
  T-216c~g. **검증**: 문서 전용(코드 없음).

## 2026-06-09 (claude) — ADR-048 무-호환 재검토(#316 2차): 일관성·확장성·안정성 우선

**작업**: 사용자 지시 "호환성 신경쓰지 말고 늦기 전에 일관성/확장성/안정성으로 정리". 앞서
호환성 동기로 넣은 hedge들을 걷어내고 ADR-048/rest-api.md/T-216을 재정리. PR까지, 머지 보류.

- **외부 read "동결" carve-out 제거**: 명명 규칙을 의미 기준으로 전면 적용 —
  `cluster_key`→`cluster_id`(외부 read여도 단일 식별자). `*_key` 유지는 근거 있는 것만
  (복합 자연키 `target_key`, provider 어휘 ADR-044, canonical `feature_id`).
- **envelope payload/meta 완전 분리**: `data`=payload만, 페이지네이션은
  `meta.page{page_size,next_cursor,total}`로 일원화. `data.next_cursor`/파생 `count` 폐기.
- **dual-support/deprecation 창 제거 → `/v1` clean cut**: 구 unprefixed/alias 미유지,
  `/debug/health`·`/debug/version` 제거. 이중 코드경로 제거(안정성).
- **action sub-resource 규약 명문화**(부수효과=POST verb / 순수수정=PATCH) + **단일 정본
  수렴**(rest-api.md, tripmate-rest-api.md는 소비 view로 축소 — T-216g).
- ADR-048 결정 #2/#6/#8/#9 개정 + "전환 정책(무-호환)" 절로 "소비자 안전" 대체. T-216a~g.
- **검증**: 문서 전용(코드 없음).

## 2026-06-09 (claude) — ADR-048: REST versioning admin/ops 확장 + 정합성 표준(+ #317 reconcile)

**작업**: #317(T-214/T-215, 머지됨)의 REST `/v1` 1차 정리 위에 사용자 지시 2건을 반영 —
**admin도 versioning(`/v1`)** + envelope/pagination/parameter/response 정합성 심화 + 코드/DB
명명 전파. PR #316을 #317 머지본 위로 reset/재작성(rebase 대신). PR까지, 머지 보류.

- **ADR-048**(신규): #317 위 delta — (1) `/v1`를 admin/ops/debug까지 확장(#317 T-214b의
  admin 비버저닝 supersede, 사용자 지시), (2) envelope 공유 `Meta{duration_ms,request_id}`+
  `ListData[T]`, (3) `page_size` 단일·2-티어 캡·`total_count` opt-in, (4) bbox 분리-float·
  `state`→`status`·issue noun, (5) RFC7807 problem+json, (6) 응답 `*_key`→`*_id`, (7) 코드/DB
  명명 전파(내부 소유, provider/복합키 경계 ADR-044).
- **`docs/rest-api.md`**(신규): 전 표면 카탈로그 + 정합성 표준. 외부 `/v1` 정본은
  `docs/tripmate-rest-api.md`(#317)로 위임, §2.1 versioning 문구를 ADR-048로 갱신.
- **#317 reconcile**: tripmate-alias 제거·feature CRUD(K-15)·version 0/1을 카탈로그에 반영.
  내가 앞서 만든 Phase 8/T-214a~l(중복 충돌)을 폐기하고 **Phase 6.8 / T-216a~f**로 재정의.
- **#316 TripMate-소비자 리뷰 반영**: 외부 dual-support 전환 창(구 unprefixed alias +
  `deprecated`/`Sunset`), problem+json `code`/`request_id` top-level 확장 멤버 + enum 고정,
  **외부 소비 read 필드 동결**(`feature_id`/`cluster_key`/`target_key`/FeatureSummary —
  `*_key`→`*_id`는 내부 ops/admin만), 반영 순서(외부 `/v1` 먼저→admin `/v1`은 외부 무영향)를
  ADR-048 "소비자 안전" 절 + rest-api.md + T-216에 명시.
- **검증**: 문서 전용(코드 없음).

## 2026-06-08 (codex) — REST API v1 계약 정리 + feature CRUD admin API

**작업**: `docs/reports/api-endpoint-review-2026-06-08.md`와 TripMate repo
`docs/integrations/kor-travel-map-rest-api.md`를 종합해 REST API 정본 문서와 후속 task를 정리하고,
사용자 요청 place/event feature 추가·수정·삭제 API를 admin 영역에 구현.

- `docs/tripmate-rest-api.md`: `/v1` 목표 계약, envelope/error/parameter 규약, endpoint naming,
  중복 제거, 누락 API, 현재 구현 gap을 한 문서로 재작성.
- 사용자 결정 반영: `/tripmate/feature-update-requests*`는 TripMate/user 표면이 아니라
  `/admin/feature-update-requests*` 운영 표면으로 이동. TripMate 사용자 제안 큐는 TripMate
  app DB가 소유하고, 운영자 승인 후 admin API로 refresh scope를 실행한다.
- `docs/openapi-admin-contract.md`, `docs/tripmate-integration.md`,
  `docs/poi-cache-update-targets.md`, `docs/architecture.md`,
  `packages/kor-travel-map-admin/README.md`의 충돌 문구를 정리.
- `/tripmate/feature-update-requests*` alias를 코드/OpenAPI user profile에서 제거하고
  `/admin/feature-update-requests*`만 남겼다.
- `/admin/features`에 `POST`, `/admin/features/{feature_id}`에 `PATCH`/`DELETE`,
  `/admin/features/change-requests*` 승인/거절 API를 추가했다. 기본은
  `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE=require_review`, 설정이 `immediate`면 같은
  transaction에서 바로 적용한다.
- `feature.features`에 `data_origin`/`data_version`/`user_change_*` metadata,
  `feature.feature_versions`, `ops.feature_change_requests`를 추가했다. provider reload는
  version 0 snapshot을 갱신하고, 사용자 요청 version 1 effective row와 soft delete를
  덮거나 되살리지 않는다.
- `docs/tasks.md`: `T-214a~h`, `T-215a~c`를 정리했다. `T-214a`, `T-214c`, `T-215a`는 완료.

**검증**: admin feature repo 통합 테스트, admin router/export OpenAPI 단위 테스트, ruff/mypy,
OpenAPI drift check를 수행.

## 2026-06-08 (claude) — 앱 레벨 service-token 인증(ADR-045 D-1 B안)

**작업**: API 리뷰 [P1] "보안 스킴 미선언" 후속. 사용자 결정 = D-1 B안(infra + 앱 레벨
defense-in-depth). 운영 1차 인증은 여전히 infra(proxy SSO/IP allowlist)이고 그 위에 얇은
앱 방어를 옵션으로 추가.

- settings: `service_token`(SecretStr, opt-in) + `admin_destructive_enabled`(kill-switch, 기본 True).
- `map_admin/auth.py`: `require_service_token`(`APIKeyHeader` `X-Kor-Travel-Map-Service-Token` + **상수시간**
  `hmac.compare_digest`; 토큰 미설정이면 통과=하위호환) + `require_admin_destructive_enabled`.
- app.py 와이어링: **순수 service-to-service `/tripmate/*`**에만 service token 강제. **공용 read
  surface(`/features`·`/categories`·`/providers`)는 브라우저 admin UI도 써서 앱 토큰 강제 안 함**
  (이 구분이 핵심 — 안 그러면 브라우저 UI가 깨짐). 파괴적 `/admin`(restore/swap/deactivate/POI
  delete)에 kill-switch.
- OpenAPI `securitySchemes.ServiceToken` 자동 선언 + `/tripmate/*` operation `security`(user.json
  포함 — TripMate 계약 문서화, P1 해소). types.ts(파괴적 endpoint 403 응답) 재생성.
- 테스트 `test_auth.py` 8건: dependency 단위(미설정 통과/일치/불일치 401/kill-switch 403) +
  TestClient(OpenAPI 스킴, /tripmate 401, 미설정 비차단, /features 비게이트, 파괴적 403).
- ADR-005 amendment + tripmate-rest-api §1 갱신.
- **검증**: ruff + mypy --strict(admin 27) + admin 234 + auth 8 + frontend gen:types/type-check
  (src+e2e)/eslint/build + OpenAPI drift green.

## 2026-06-08 (codex) — T-212d 사후 리뷰 반영

**작업**: PR #313 머지 후 PR issue comment로 달린 T-212d 사후 상세리뷰를 확인하고 후속 보강.

- `/features/in-bounds`: 공간 후보 CTE는 유지하면서 `LIMIT` subset 안정성을 위해
  `feature_id ASC` 결정적 정렬을 복구.
- `test_t212d_perf_explain.py`: 대표 bbox/admin sort=name 경로를 `enable_seqscan=on` 상태로
  검증해 planner가 base table `Seq Scan`을 선택하지 않는지 확인하고, sort=name 인덱스
  (`idx_features_lower_name_keyset`) EXPLAIN 케이스 추가.
- dedup/enrichment review cursor는 첫 두 page disjoint를 넘어 전체 순회 결과가 DB 정렬셋과
  1:1로 일치하는지 검증.
- 성능 문서/리포트에 `feature_files` 임시 DDL, Alembic 일반 `CREATE INDEX` 잠금 유의 사항,
  `idx_import_jobs_state` 대량화 재검토 포인트를 명시.

## 2026-06-08 (codex) — T-212d seeded PostGIS 성능 baseline

**작업**: 사용자 지시대로 main 재동기화 후 T-212d DB/API 성능 baseline과 hot path 튜닝을 진행.

- 로컬 live DB는 alembic `0016`, `features/source_records/source_links/import_jobs` 각 1건,
  `consistency_reports`/`dedup_review_queue` 0건이라 성능 baseline으로 부적합함을 확인.
- `0020_t212d_perf_keyset_indexes`: feature updated/status/name/opening_hours, import_jobs,
  consistency reports/violations, dedup/enrichment review queue keyset 인덱스 보강.
- `/features/in-bounds` 공간 후보 CTE, `/features/search` trigram 후보 CTE, dedup/enrichment
  review 및 F7 consistency UUID tie-breaker keyset 정렬로 EXPLAIN 인덱스 사용을 고정.
- 신규 통합 테스트 `test_t212d_perf_explain.py`: 3,200 feature + provider/source/ops/review
  live-like seed로 `/features/search`, `/features/in-bounds`, `/features/nearby`, `/admin/features`,
  `/ops/import-jobs`, dedup refresh, consistency F4/F6/F7/F8, review list EXPLAIN 검증.

**검증**: T-212d 전용 ruff + EXPLAIN 통합 4 passed, 관련 통합 45 passed, 관련 단위 44 passed.

**다음**: T-212e live full reload에서 실제 provider/offline upload 볼륨, Dagster run, Playwright
실스택 smoke, backup/restore smoke를 최종 리포트로 보강.

## 2026-06-08 (claude) — 리뷰 반영: admin e2e mock을 생성 OpenAPI 타입에 바인딩 (#308)

**작업**: 내가 #308에 남긴 리뷰 finding(mock이 OpenAPI 스키마로 검증되지 않은 수작업 JSON →
백엔드 DTO 변경 시 silent drift) 반영.

- `admin-ops.spec.ts`의 수작업 `OfflineUploadRecord`/`PoiCacheTargetRecord` 타입을 생성된
  `components["schemas"][...]`에 바인딩 → 백엔드 DTO가 바뀌면 mock factory가 타입 불일치로
  컴파일 실패해 drift를 컴파일 타임에 감지.
- 기존 `tsconfig.json`은 `src/**`만 include해 e2e가 type-check 대상이 아니었음 → `e2e/tsconfig.json`
  추가 + `type-check` 스크립트를 `tsc --noEmit && tsc -p e2e/tsconfig.json --noEmit`로 확장(+
  `type-check:e2e`). 이제 frontend CI `type-check`가 e2e mock 계약까지 검증.
- **검증**(Windows Node): gen:types:check(drift 0) + type-check(src + e2e) + eslint + next build green.
  (mock이 실제 스키마를 그대로 만족 — 추가 churn 없음.)

## 2026-06-08 (claude) — 리뷰 반영: Dagster run drilldown 보강 (#291)

**작업**: 내가 #291에 남긴 상세리뷰 findings 반영.

- **이벤트 윈도잉(중간)**: `eventConnection(limit:N)`이 `afterCursor` 없이 **앞쪽 N개**만 가져와
  긴 run의 **실패 이벤트(뒤쪽)가 잘릴 수 있던** 문제 → GraphQL에 `$afterCursor` 추가 +
  엔드포인트에 `after` 쿼리파라미터(`event_cursor`로 전진). 프론트 Run detail에 이벤트
  **이전/다음 페이지** 컨트롤(cursor stack, run 전환 시 `key`로 remount 리셋).
- **str(error)(minor)**: GraphQL top-level errors를 `str(dict)`로 노출하던 것 → `_graphql_error_message`로
  `message`만 추출(파이썬 repr 누수 방지).
- **폴링(minor)**: `useDagsterRunDetail` `refetchInterval`을 함수로 — run status가 terminal
  (SUCCESS/FAILURE/CANCELED)이면 폴링 중단.
- 테스트: `after`→`afterCursor` 전달 / GraphQL error message 추출 단위 테스트 추가, 기존 변수
  assertion 갱신. OpenAPI(+`after` param)/types.ts 재생성.
- **검증**: ruff + mypy --strict(admin 26) + admin 226 + frontend gen:types/eslint/tsc/build +
  drift-check green.

## 2026-06-08 (claude) — 리뷰 후속: opinet POI-타깃 scope 계약 수정 (#304)

**작업**: PR #304 리뷰(codex) actionable finding — `_opinet_poi_target_bboxes`의 POI target
선택 SQL이 잘못됨.

- **P1**: `external_system='opinet'` 필터는 틀림. `external_system`은 provider명이 아니라 **외부
  호출자**(tripmate 등, `docs/poi-cache-update-targets.md`). 이대로면 실제 TripMate 등록 target이
  전부 무시되고 poi_cache_target 모드가 "활성 target 없음"으로 실패. → external_system 필터 제거,
  **모든** 외부 시스템의 활성 target을 대상으로.
- **P2**: active 정의 누락. `scope_repo.resolve_cache_target_keys`는 `deleted_at IS NULL` +
  `update_enabled` + `refresh_policy<>'disabled'`를 모두 본다. 새 fetcher는 `update_enabled`만
  봐서 disabled target도 enumeration에 들어감. → `refresh_policy<>'disabled'` 추가.
- 추가: target이 `provider_overrides`에서 opinet dataset(`python-opinet-api:opinet_fuel_station_details`)
  을 `targeted_policy='disabled'`로 옵트아웃했으면 제외(파라미터 바인딩 JSONB 조회).
- 통합 테스트 회귀 보강: external_system=`tripmate`/`kakao`(둘 다 포함) + disabled-policy/update-off/
  deleted/opinet-optout(모두 제외) seed로 계약 위반 방지.
- **검증**: ruff + mypy --strict(map 85/dagster 13) + lint-imports + dagster 87 + unit+lint 966
  (coverage 81%) + `test_opinet_poi_scope` 실 PostGIS green.

## 2026-06-08 (codex) — T-212b admin UI mutation e2e 완료

**작업**: PR#291(Dagster 드릴다운)과 PR#277(admin UI 핵심 화면)을 머지한 뒤, T-212b 마지막
잔여인 offline upload/POI cache target 주요 mutation e2e를 별도 PR로 분리.

- `/admin/poi-cache-targets` Playwright flow: target upsert(`PUT`) → 목록 반영 → row 선택 →
  `/features/nearby/by-target` 조회 → target delete(`DELETE`) 요청과 row 제거 확인.
- `/admin/offline-uploads` Playwright flow: CSV multipart upload(`POST`) → preview 조회 →
  validation 실행(`POST /validate`) → `validated` 필터 전환 → Dagster load 실행(`POST /load`)
  alert 확인.
- route mock은 backend DB/RustFS/Dagster 상태와 분리해 브라우저 상호작용, 요청 method/path/body,
  envelope 응답 shape, React Query invalidation 후 화면 상태 변화를 고정한다.

**상태**: `docs/tasks.md`의 T-212b 체크리스트 완료 처리. 실스택/실데이터 검증은 T-212e에서
별도 수행.

## 2026-06-08 (claude) — 리뷰 후속: enrichment-review 페이지네이션 UI (#299)

**작업**: PR #299 리뷰(digitie) non-blocker 메모 — enrichment-review 프론트가 `page_size 100`까지만
보고 cursor/next UI 없음. 대량 검토 시 다음 페이지 접근 필요.

- `enrichment-review-client.tsx`: cursor stack 상태(2페이지부터 cursor 누적) + `page_size 50` +
  `이전`/`다음` 버튼(다음은 응답 `next_cursor` 있을 때만 활성, 이전은 stack pop) + 페이지 인덱스/
  건수 표시. status 필터 변경 시 1페이지로 reset. 기존 `useEnrichmentReviews`의 `cursor` 파라미터
  활용(API 변경 없음).
- e2e smoke(admin-ops.spec)에 `이전 페이지`/`다음 페이지` 버튼 가시성 assertion 추가.
- **검증**(Windows Node): gen:types:check(drift 0) + eslint + tsc --noEmit + next build
  (/admin/enrichment-review prerender) green.

## 2026-06-08 (claude) — 리뷰 후속: airkorea 측정소 composite key (#300/#301)

**작업**: PR #300/#301 리뷰(digitie) actionable finding — 대기질 측정소 identity/측정값 join이
`station_name` 단독이라 전국 비유일(`중구`가 여러 시도). 같은 이름 측정소가 한 feature로 접히거나
측정값이 다른 지역 feature에 붙을 수 있음(asset의 `{source_entity_id: feature_id}` dict가 동명을
덮어씀, #301).

- `providers/airkorea.py`: `_canonical_sido`(주소/시도명 첫 토큰 → 약식 시도, `_SIDO_CANONICAL`
  전체/약식 매핑) + `_station_key`(`station_name::<sido>` composite, ADR-009 `::`). station bundle
  natural key = composite(addr 시도), measurement Protocol에 `sido_name` 추가 +
  `air_quality_to_weather_values`가 `(sido_name, station_name)` composite로 조회. dagster asset은
  source_entity_id 기반 map이라 자동 composite-key화(코드 변경 불필요).
- 테스트: 단위 `test_same_station_name_in_different_sido_are_distinct`(서울/대구 `중구` 별개 feature
  + 측정값 정확 join) + 통합 `test_airkorea_asset_distinct_features_for_same_station_name`(asset
  레벨, 동명 2 측정소 → 2 feature/2 WeatherValue 값 안 섞임). asset metadata는 `_add_output_metadata`
  guard 헬퍼로 직접 호출 호환.
- **검증**: ruff + mypy --strict(map 85/dagster 13/admin 26) + lint-imports + unit+lint 966
  (coverage 81%, airkorea.py 93%) + full 1172 + admin/dagster 311 green.

## 2026-06-08 (claude) — 리뷰 후속: enrichment 결정 race 수정 (#297/#298)

**작업**: PR #297 리뷰(digitie) actionable finding — `decide_enrichment_review()`가 SELECT 후
accepted면 link 적재→UPDATE 순서라, 동시 결정 시 reject가 status를 잡아도 accept가 link를 새겨
`changed=False`(409)인데 link는 커밋될 수 있음. #298 API도 같은 root cause.

- 수정: `_SELECT_ROW_SQL`에 `FOR UPDATE` 추가 → 같은 review_id 동시 결정을 행 잠금으로 직렬화.
  먼저 잠근 transaction이 commit할 때까지 다른 결정은 대기 후 갱신된 status(non-pending)를 보고
  side-effect 없이 changed=False 반환("상태 점유 → side-effect" 순서). accepted link 적재 실패
  시 같은 transaction이라 상태 변경도 rollback.
- 통합 테스트 `test_concurrent_decide_no_accepted_link_leak`: 같은 pending 행에 accept/reject
  동시(asyncio.gather, 2 세션) → 정확히 하나만 changed, 최종 ENRICHMENT link 존재 ↔ 최종
  status='accepted' 정합 검증.
- **검증**: ruff + mypy --strict(map 85) + lint-imports + unit+lint 965(coverage 81%) +
  enrichment_review_repo 9(race 포함) + admin router 5 green.

## 2026-06-08 (claude) — T-RV-04b opinet-3 POI-타깃 scope (→ T-RV-04b 완전 종료)

**작업**: opinet wiring 3/3 = POI-타깃 모드. `fetch_opinet_stations`의 `poi_cache_target` 분기 연결.

- `_opinet_poi_target_bboxes(settings)`: sync fetcher라 `settings.pg_dsn`(async)을 sync psycopg
  DSN(`+asyncpg`→`+psycopg`)으로 바꿔 `ops.poi_cache_targets`에서 `external_system='opinet'` +
  `update_enabled` + non-deleted target(lon/lat/radius_km) 조회 → `_center_radius_to_bbox`(위도 1°
  ≈111km, 경도 cos(lat) 근사)로 bbox 변환. 짧은 connect/dispose.
- `fetch_opinet_stations` poi 분기: target bbox들을 기존 `_enumerate_opinet_stations`로 enumerate
  (target 간 겹침 uni_id dedup). 활성 target 없으면 명확 guard.
- 테스트: 단위(`_center_radius_to_bbox` math / poi enumerate via monkeypatched bboxes + fake opinet
  dedup / empty targets guard) + 통합(`test_opinet_poi_scope`: 실 PostGIS에 opinet target seed→
  commit→sync 조회로 bbox 반환, 비활성/타 시스템 제외 검증).
- **검증**: ruff + mypy --strict(map 85/dagster 13/admin 26) + lint-imports + unit+lint 965
  (coverage 81%) + full 1169 + dagster 87 green.

**→ T-RV-04b 완전 종료**: provider 8종(datagokr/krheritage/krex×2/mois/knps×2/opinet) live wiring
완료. opinet은 bbox + POI-타깃 2 scope(settings 선택). T-RV-04b 및 후속 program(T-RV-50~55) 모두
종결.

## 2026-06-08 (claude) — T-RV-04b opinet-2 bbox fetcher + scope settings

**작업**: opinet wiring 2/3 = bbox 모드. OpiNet은 전국 dump가 없어 `iter_stations_in_bbox`
(aroundAll 격자 근사)로 영역 enumerate.

- settings: `opinet_scope_mode`(disabled/bbox/poi_cache_target) + `opinet_scope_bbox`
  (`min_lon,min_lat,max_lon,max_lat`) + `opinet_scope_radius_m`(≤5km).
- `fetch_opinet_stations`(provider_fetchers): `disabled`→guard, `bbox`→`OpinetClient.
  iter_stations_in_bbox` 1영역 enumerate(`_enumerate_opinet_stations`로 uni_id dedup, finally
  close), `poi_cache_target`→opinet-3 대기 guard. `_parse_opinet_bbox` 검증(4값/숫자/min<max).
- resource `opinet_stations` guard→live override(기존 `feature_place_opinet_stations` asset이
  그대로 record 소비). 가드 예시 테스트는 아직 미wiring인 `krheritage_items`로 교체.
- **검증**: ruff + mypy --strict(map 85/dagster 13/admin 26) + lint-imports + unit+lint 965
  (coverage 81%) + full 1168 + dagster 85(opinet fetcher 6 케이스) green.

**다음**: opinet-3 POI-타깃 모드(설정 DSN 동기 DB로 opinet POI cache target 읽어 bbox enumerate).
완료 시 **T-RV-04b 완전 종료**.

## 2026-06-08 (claude) — T-RV-04b opinet-1 ADR-044 Protocol 재정렬

**작업**: T-RV-04b 마지막 1건(opinet wiring) 착수. 사용자 결정 = bbox + POI-타깃 둘 다 지원(3 PR
중 1번째 = ADR-044 재정렬). `iter_stations_in_bbox`가 yield하는 provider `Station`을 krtour
Protocol이 그대로 만족하도록 정렬.

- `OpinetStationItem` Protocol을 provider `Station` 필드명에 정렬: station_name→`name`,
  brand_code→`brand`(BrandCode enum), 단일 address→`address_road`/`address_jibun`, Decimal
  longitude/latitude→`lon`/`lat`(float). `tel`/`lpg_yn`은 `StationDetail`에만 있어 Protocol 필수에서
  제외 → transform이 `getattr`로 보강(있을 때만, N+1 detail은 후속).
- `stations_to_bundles`/`_station_item_to_bundle`(`_brand_code` 헬퍼 추가) + ETL fixture(`_Station`)
  + `etl_live._OpinetStationAdapter`/`_adapt_opinet_station`(NEW_ADR→road, VAN_ADR→jibun, KATEC→
  WGS84 float) + 단위(opinet_stations 16)·통합(dagster_feature_etl)·live adapter 테스트 갱신.
- **검증**: ruff + mypy --strict(map 85/admin 26) + lint-imports + unit+lint 965(coverage 81%,
  opinet.py 80%) + full 1168 + admin/dagster 303 green.

**다음**: opinet-2 settings+bbox fetcher+bespoke asset → opinet-3 POI-타깃 모드. 완료 시 T-RV-04b
완전 종료.

## 2026-06-08 (claude) — T-RV-55d-2 airkorea 대기질 orchestration (→ T-RV 후속 program 완료)

**작업**: 55d-1 provider 위에 적재 orchestration(2 PR 중 2번째, 마지막). 측정소 weather feature +
오염물질별 WeatherValue를 한 transaction에 적재.

- client `load_air_quality(station_bundles, weather_values)`: load_bundles(측정소 weather feature,
  FK 선결) → load_weather_values(air_quality 값)를 한 transaction에. `AirQualityLoadResult`
  (infra/feature_repo, FeatureLoadResult + 값 카운트) — assets가 client 무거운 import 없이 쓰도록
  infra에 둠.
- dagster: `fetch_airkorea_stations`(stations 페이지네이션) + `fetch_airkorea_air_quality`(17개
  시도 `sido_measurements` 순회) + `feature_weather_airkorea_air_quality` asset(stations+measurements
  두 stream → 측정소 bundle 변환·station_name→feature_id 매핑 → WeatherValue 변환 → load_air_quality)
  + resource spec×2/guard→live + definitions REQUIRED_RESOURCE_KEYS + ETL preview×2.
- **검증**: ruff + mypy --strict(map 85/dagster 13/admin 26) + lint-imports + unit+lint 965
  (coverage 81%) + full 1168 + admin 224 + dagster 79 + airkorea ETL preview(weather kind /
  air_quality WeatherValue) + load_air_quality integration green.

**→ T-RV-55(보조 dataset) + T-RV-04b 후속 program(T-RV-50~55) 전체 완료.** place 5종(55a~e) +
대기질 측정값(55d) + enrichment review(52) + dedup 수동 UI(51) + maplibre(50) + krforest(53)/
박물관미술관(54) 모두 머지. **남은 미해결 항목 없음.**

## 2026-06-08 (claude) — T-RV-55d-1 airkorea 대기질 provider (station=weather feature)

**작업**: 사용자 결정(대기질을 지금 구현, 측정소=weather feature)에 따라 `providers/airkorea.py`
신규(2 PR 중 1번째). 대기질은 장소가 아니라 측정값이라 기존 WeatherValue 패턴 재사용.

- `air_quality_stations_to_bundles`(측정소 → **weather kind** FeatureBundle): category `99000000`
  (KMA 특보와 동일 비-place placeholder, ADR-018상 weather=detail 없음), 좌표 reverse로 bjd 보강,
  안정키 = 측정소명. `AirQualityStationItem` Protocol.
- `air_quality_to_weather_values`(측정 row → 오염물질별 `WeatherValue`): `weather_domain=air_quality`
  (기존 enum), `forecast_style=observed`, metric PM10/PM2_5/O3/NO2/SO2/CO/CAI(단위 μg/m³·ppm·score),
  grade(1~4)→severity(좋음~매우나쁨), `observed_at`=data_time(naive면 KST 보정). KMA value 변환
  미러(`station_feature_ids` 매핑, source_record_key param). 결측 오염물질/미매핑 측정소 skip.
  `AirQualityMeasurementItem` Protocol.
- **검증**: ruff + mypy --strict(map 85/dagster 13/admin 26) + lint-imports + unit+lint 965
  (coverage 81%, airkorea.py 96%) green.

**다음**: 55d-2 orchestration(client `load_air_quality` + dagster fetcher/asset/resource/definitions
+ ETL preview + 테스트) → **T-RV 후속 program 전체 완료**.

## 2026-06-08 (claude) — T-RV-52c-3 축제 enrichment 검토 frontend (→ T-RV-52 완료)

**작업**: 52c admin API 위에 운영자 검토 UI(3 PR 중 3번째, 마지막). dedup-review 페이지 미러
(단, enrichment은 병합 아님 → master 선택 UI 없이 accept/reject/ignore만).

- `src/api/enrichment.ts`: `useEnrichmentReviews`(list) + `useEnrichmentDecisionMutation`
  (accept→applied 시 feature 캐시 무효화). 타입은 생성된 `types.ts`의 `EnrichmentReview*` 스키마.
- `app/admin/enrichment-review/`(page + client): status 필터 + 1차(datagokr)/2차(visitkorea)
  양측 + name_score + accept/reject/ignore. nav 항목(admin-shell `LinkIcon`) + e2e smoke
  (admin-ops.spec, 헤딩/필터/컬럼 검증).
- **검증**(Windows Node): `gen:types:check`(drift 0) + `tsc --noEmit` + `next build`(route
  `/admin/enrichment-review` 등록 확인) + `eslint` green.

**→ T-RV-52(visitkorea 축제 enrichment) 전체 완료**: 52a provider + 52b krtour wiring + 52c
review 큐/admin API/frontend. 자동 매칭(≥0.90)은 즉시 적재, 모호 밴드는 운영자 수동 검토.

**다음(우선순위 가이드 후속)**: 남은 큰 항목은 **55d airkorea 대기질**(place feature 아님 — 설계
결정 사용자 대기). 그 외 T-RV-04b 후속 program(T-RV-50~55) place dataset/enrichment/dedup UI는
전부 완료.

## 2026-06-08 (claude) — T-RV-52c-2 축제 enrichment 검토 admin API

**작업**: 52c-1 backend 위에 운영자 검토 HTTP surface(3 PR 중 2번째). dedup-review 라우터
미러(단, 병합 아님 → advisory lock/merge 분기 없음).

- `list_enrichment_reviews`(infra/admin_feature_repo): `ops.enrichment_review_queue` + 1차
  target feature LEFT JOIN(kind/category/coord), status/provider/name_score/q 필터 +
  name_score DESC cursor 페이지네이션. `EnrichmentReviewRow`/`EnrichmentReviewPage`.
- `enrichment_review` router(packages/kor-travel-map-admin): `GET /admin/enrichment-review`(list) +
  `PATCH /admin/enrichment-review/{review_id}`(decision accepted/rejected/ignored — accept는
  `decide_enrichment_review`로 ENRICHMENT link 적재, 이미 검토 시 409). routers/__init__ + app
  등록.
- OpenAPI 재생성(`export_openapi.py --profile all`): openapi.json만 +558(enrichment-review
  경로/스키마), openapi.user.json은 /admin 제외라 변동 없음. drift-check green.
- **검증**: ruff + mypy --strict(map 84/dagster 13/admin 26) + lint-imports + unit+lint 959
  (coverage 81%, admin_feature_repo 85%) + admin 220 + dagster 75 + integration
  (list_enrichment_reviews + router 4) green.

**다음**: 52c-3 frontend(`admin/enrichment-review` 페이지 + api 훅 + `types.ts` 재생성 +
Windows Playwright e2e). (55d airkorea 설계 결정은 사용자 대기.)

## 2026-06-08 (claude) — T-RV-52c-1 축제 enrichment 검토 큐 backend (matcher 밴드 + infra)

**작업**: visitkorea↔datagokr 축제 enrichment 매칭을 dedup-review처럼 **수동 검토**하기 위한
backend 도메인/infra slice(3 PR 중 1번째). 자동 확정 임계(0.90) 미만·검토 하한(0.70) 이상의
**모호한 밴드**를 큐로 영속화.

- **matcher**(providers/visitkorea): `ScoringFestivalMatcher.best_match`(임계 비의존 최고점)
  추출로 `match()` 리팩터 + `festival_to_review_candidates`(auto/review/drop 3분류,
  `FestivalMatchPlan`/`FestivalReviewCandidate`). 자동 적재 동작은 기존과 동치(임계만 명시).
- **infra**: migration `0019_enrichment_review_queue`(`ops.enrichment_review_queue`, UNIQUE
  (target_feature_id, source_provider, source_dataset_key, source_entity_id), JSONB source_record)
  + `EnrichmentReviewQueueRow`(models) + `infra/enrichment_review_repo.py`(enqueue/pending/decide).
  accept는 보관된 `SourceRecord` 복원 → ENRICHMENT `SourceLink` 적재. **ADR-020**: infra가
  providers를 import하지 않도록 enqueue 입력은 generic `EnrichmentReviewInput`(SourceRecord dto만),
  client가 `FestivalReviewCandidate`→input 매핑(`load_source_record_links` 패턴).
- **client**: `refresh_festival_enrichment_reviews`(한 transaction: candidate 로드→밴드 분류→auto
  적재+review 큐 upsert) + `list_pending_enrichment_reviews` + `resolve_enrichment_review`.
- **검증**: ruff + mypy --strict(map 84/dagster 13/admin 25) + lint-imports + unit+lint 959
  (coverage 81%, visitkorea 97%) + integration(enrichment_review_repo 7 + client_orchestration 6)
  + full 1160 green.

**다음**: 52c-2 admin API(`/admin/enrichment-review` list + decide) → 52c-3 frontend(dedup-review와
유사 페이지 + OpenAPI 재생성 + Playwright). (55d airkorea 설계 결정은 사용자 대기.)

## 2026-06-08 (claude) — T-RV-55e krairport 공항 풀스택 (신규 provider 모듈, keyless)

**작업**: ADR-034 보조 dataset 4번째 — 공항 메타데이터(python-krairport-api). 신규
`providers/krairport.py`.

- `airports_to_bundles`(place, category `TRANSPORT_AIRPORT 06050000`, place_kind `airport`) +
  `AirportMetadataItem` Protocol. 좌표는 provider `Coordinate`(`.lat`/`.lon` float) 중첩 객체로
  와서 `_coord_of`가 getattr로 추출(None 안전). 도로명 주소 없어 좌표 reverse로 bjd 보강,
  안정키 = 공항 코드(IATA `code`). facility_info에 icao_code/name_english 보존.
- `fetch_krairport_airports`(sync, **keyless** — `client.airports(active=True)`는 번들 정적
  메타데이터라 credential 없이 동작. key 있으면 kac/iiac에 주입하되 본 fetcher는 bundled만
  yield) + `feature_place_krairport_airports` asset + resource spec(setting_names 없음 → 항상
  live)/guard→live + definitions + ETL preview entry.
- **MOIS dedup 없음**(MOIS PROMOTED 42 슬러그에 공항 없음).
- **검증**: ruff + mypy --strict(map 83/dagster 13/admin 25) + lint-imports + unit 951(coverage
  81%, krairport.py 97%) + dagster 73 + krairport preview(06050000/airport) green.

**다음(T-RV-55)**: 55d airkorea 대기질은 **측정값이라 place feature 아님 — 설계 결정 선행**
(WeatherValue 패턴 vs 별도 vs skip). 55a~55e place 보조 dataset 5종 완료. (52c enrichment UI
trailing.)

## 2026-06-08 (claude) — T-RV-55c khoa 해수욕장 풀스택 (신규 provider 모듈)

**작업**: ADR-034 보조 dataset 3번째 — 해양수산부 해수욕장정보(python-khoa-api). 신규
`providers/khoa.py`.

- `beaches_to_bundles`(place, category `TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND 01020300`,
  place_kind `beach`) + `OceanBeachInfoItem` Protocol. provider `OceanBeachInfo`는 도로명 주소가
  없어 좌표 reverse만으로 bjd 보강(주소 geocode 경로 미사용), admin=sido+gugun, 안정키
  `name::sido::gugun` 파생.
- `fetch_khoa_beaches`(sync — `OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES` 시도 순회 + 시도별
  `oceans_beach_info(sido, page_no)` 페이지네이션) + `feature_place_khoa_beaches` asset + resource
  spec/guard→live + definitions + ETL preview entry.
- **MOIS dedup 없음**(MOIS PROMOTED에 해수욕장 슬러그 없음).
- **검증**: ruff + mypy --strict(map 82/dagster 13/admin 25) + lint-imports + unit 942(coverage
  80.92%) + dagster 72 + khoa preview(01020300/beach) green.

**다음(T-RV-55)**: 55d airkorea 대기질(측정값이라 place 아님 — 설계 선행) → 55e krairport 공항.
(52c enrichment UI trailing.)

## 2026-06-08 (claude) — T-RV-55b 주차장(parking) 풀스택

**작업**: ADR-034 보조 dataset 2번째 — 전국주차장표준데이터(datagokr). tourist와 동일 4-step,
공용 `_standard_place_to_bundle` helper 재사용.

- `parking_lots_to_bundles`(place, category `TRANSPORT_PARKING 06010000`, place_kind `parking`) +
  `PublicParkingLotItem` Protocol. 안정키 `prkplce_no`(없으면 instt_code→name::road 파생).
  facility_info에 prkplce_se/prkcmprt/parkingchrge_info 보존.
- `fetch_standard_parking_lots`(sync, `parking.iter_all()`) + `feature_place_standard_parking_lots`
  asset + resource spec/guard→live + definitions + ETL preview entry.
- **MOIS dedup 없음**: MOIS PROMOTED 42 슬러그에 주차장이 없어 dedup 후보 없음 → pair 미추가.
- **검증**: ruff + mypy --strict(map 81/dagster 13/admin 25) + lint-imports + unit 939(coverage
  80.81%) + dagster 70 + parking preview(cat 06010000) green.

**다음(T-RV-55)**: 55c khoa 해수욕장(조사 선행) → 55d airkorea 대기질(측정값, place 아님 — 별도
설계) → 55e krairport 공항. (52c enrichment UI는 trailing.)

## 2026-06-08 (claude) — T-RV-55a 관광지(tourist_attraction) 풀스택

**작업**: ADR-034 보조 dataset 1번째 — 전국관광지표준데이터(datagokr). museum과 동일 4-step.

- **transform**: `standard_data`에 공용 `_standard_place_to_bundle` helper(관광지/주차장 공유) +
  `tourist_attractions_to_bundles`(place, category `TOURISM 01000000`, place_kind `tourist_attraction`)
  + `PublicTouristAttractionItem` Protocol. 안정키 `instt_code`(없으면 `name::road` 파생).
- **asset/fetcher**: `fetch_standard_tourist_attractions`(sync, `tourist_attraction.iter_all()`) +
  `feature_place_standard_tourist_attractions` asset + resource spec/guard→live + definitions.
- **dedup**: `DEFAULT_DEDUP_SCOPE_PAIRS`에 관광지↔MOIS `tourism_businesses`(01000000) pair(기본 4건).
- **ETL preview**: `etl_fixtures`에 `datagokr_tourist_attractions` entry.
- **검증**: ruff + mypy --strict(map 81/dagster 13/admin 25) + lint-imports + unit 936(coverage
  80.74%) + dagster 68 green.

**다음(T-RV-55)**: 55b 주차장(parking, 동일 패턴) → 55c khoa 해수욕장 → 55d airkorea 대기질(측정값
이라 place 아님, 별도 설계) → 55e krairport 공항. (52c enrichment UI는 별도 trailing.)

## 2026-06-07 (claude) — T-RV-52b-3 visitkorea enrichment asset → T-RV-52b 완료

**작업**: 축제 enrichment 통합(3부, 52b 완료) — visitkorea fetcher + DB-coupled orchestration +
asset.

- **fetcher** `fetch_visitkorea_festival_events`(sync — `KrTourApiClient`도 sync):
  `iter_pages(search_festival, <올해 1/1 KST>, num_of_rows=100)` 페이지네이션, `TourItem` yield.
  credential `data_go_kr_service_key`, finally `close()`.
- **client** `load_festival_enrichment(items, *, fetched_at, name_threshold=0.9)`: 한 transaction에서
  적재된 datagokr 축제(`STANDARD_DATA_PROVIDER_NAME`/`datagokr_cultural_festivals`/kind event)를
  `list_dedup_refresh_features`(limit 50k)로 candidate 로드 → `ScoringFestivalMatcher` → `festival_to_
  enrichment_links` → `load_source_record_links`. 1차 미적재면 candidate 0 → enrichment 0.
- **asset** `feature_event_visitkorea_enrichment`(`EnrichmentLoadResult` 반환, feature 미생성) +
  resource spec(`visitkorea_festival_events`)/guard→live + definitions 등록.
- **검증**: ruff + mypy --strict(map 81/dagster 13) + lint-imports + dagster 66 + unit 932 +
  coverage 80.68%. fetcher fake(KrTourApiClient) + asset 등록 + live key 단위.
- **후속**: overview/homepage는 detailCommon에서만 → matched item N+1 detail 보강은 후속(현재
  enrichment = 이미지/content_id/event date + SourceRecord/Link).

**T-RV-52b 완료**(b-1 matcher / b-2 load infra / b-3 asset). **다음**: T-RV-52c(매칭/enrichment 검토
UI) → T-RV-55(보조 5종).
## 2026-06-07 (codex) — T-212b Dagster tick/run 실패 드릴다운

**작업**: `/admin/dagster`의 자체 운영 요약을 Dagster tick/run 실패 원인까지 drilldown할
수 있게 보강했다. 기존 Dagster webserver iframe은 유지하고, backend는 Dagster GraphQL을
읽기 전용으로만 호출한다.

- **backend**: `GET /ops/dagster/summary`에 schedule/sensor 최근 tick 3건을 추가하고,
  `GET /ops/dagster/runs/{run_id}`를 추가했다. run detail은 `runOrError`의 run summary,
  event log, PythonError payload를 `{data, meta}` envelope로 반환한다. SSRF allowlist와
  `unavailable/error/not_found` 응답 패턴은 기존 Dagster 라우터와 동일하게 유지.
- **frontend**: `src/api/dagster.ts`에 generated type 기반 `useDagsterRunDetail` hook을 추가.
  `/admin/dagster`는 schedule/sensor tick의 run id와 recent run row를 선택해 `Run detail`
  panel에서 event/failure를 조회한다. run이 없거나 Dagster GraphQL이 500이어도 summary alert,
  empty state, iframe이 유지된다.
- **OpenAPI/docs**: `openapi.json`/`types.ts` 재생성, `openapi-admin-contract.md`,
  `debug-ui-admin-workflows.md`, frontend README, `tasks.md` T-212b-3 체크리스트 갱신.
- **검증**: `pytest -s packages/kor-travel-map-api/tests/test_dagster_router.py -q` 8 passed,
  `ruff check` green, `mypy packages/.../dagster.py` green, OpenAPI `--profile all --check`
  green, frontend `gen:types:check`/`type-check`/`lint`/`build` green. React Doctor는 exit 0,
  optional warning만 남음(기존 shadcn/ui export·label/native-select, Dagster iframe sandbox
  false positive). Windows Playwright:
  `E2E_BASE_URL=http://172.26.51.35:9014 npm -w packages/kor-travel-map-admin/frontend run e2e -- e2e/dagster.spec.ts`
  1 passed. 스크린샷은 `C:\Users\digit\AppData\Local\Temp\krtour-dagster-drilldown-9014-ready.png`.

**다음**: T-212b-3 잔여인 offline upload/POI cache target 주요 mutation e2e 또는 T-212d
perf baseline.

## 2026-06-07 (claude) — T-RV-52b-2 load_enrichment_links client/repo

**작업**: 축제 enrichment 적재 인프라(2부). enrichment는 feature를 만들지 않고 기존 1차
feature(datagokr 축제)에 `SourceRecord`+`SourceLink`(enrichment role)만 잇는다.

- `infra/feature_repo.py`: `EnrichmentLoadResult`(counts+merge) + `load_source_record_links(
  session, pairs: Iterable[tuple[SourceRecord, SourceLink]])` — 의존 방향(infra가 providers 미의존)
  때문에 generic dto 쌍을 받아 `upsert_source_record`+`upsert_source_link` 순 적재.
- `client`: `load_enrichment_links(enrichments: Iterable[FestivalEnrichment])` — providers의
  `FestivalEnrichment`를 `(source_record, source_link)`로 unpack해 한 transaction(session.begin)으로
  적재. `source_link.feature_id` FK(1차 적재 선행) 필요, 실패 시 rollback.
- **검증**: ruff + mypy --strict(81 files) + lint-imports(4 kept) + 단위 3건(merge/insert·update
  카운트/empty, mock upsert로 DB 없이).

**다음(52b-3)**: `fetch_visitkorea_festival_events` fetcher + `feature_event_visitkorea_enrichment`
asset(datagokr 축제 candidate 로드 → `ScoringFestivalMatcher` → `festival_to_enrichment_links` →
`load_enrichment_links`).

## 2026-06-07 (antigravity) — TripMate 연계 REST API 분석 및 버전 prefix/추천 API 제안 문서화

**작업**: TripMate와의 안정적 연계 및 버전 독립성을 위해 REST API를 정리하고 일관성·확장성·유지보수성 측면의 개선점을 문서화.

- **신규 리포트 추가**: `docs/reports/tripmate-api-improvement-analysis-2026-06-07.md`에 API 목록과 일관성(cache target prefix tripmate 이전, GET /features 셰입 비일관성), 확장성(prices/paths/autocomplete API 및 batch 조회 다변화), 유지보수성(v1 prefix 도입) 관점의 분석 내용을 기록.
- **정본 문서 반영**: `docs/tripmate-rest-api.md`에 향후 개선 및 리팩토링 검토 사항 섹션(§7)을 추가하여 상기 제안 사항(v1 prefix 도입 계획 등)을 명문화.
- **아티팩트 생성**: 동일한 내용의 분석 보고서 [tripmate_api_analysis.md](file:///C:/Users/digit/.gemini/antigravity/brain/ee4a8fca-db00-4d2a-8cb0-6795335d5022/tripmate_api_analysis.md)를 conversation artifacts 폴더에 작성.

## 2026-06-07 (claude) — T-RV-52b-1 ScoringFestivalMatcher (축제 enrichment 매칭)

**작업**: 축제 enrichment(point 5)의 DB-coupled 매칭 1부 — visitkorea 축제를 적재된 datagokr
축제에 매칭하는 기본 `FestivalMatcher` 구현.

- `providers/visitkorea.py`: `FestivalCandidate`(feature_id+name) + `ScoringFestivalMatcher` —
  이름 Jaro-Winkler 유사도(ADR-016 `core.scoring.name_similarity`)로 최고점·임계값(기본 0.90,
  보수적) 이상 후보 매칭. `VisitKoreaFestivalItem` Protocol이 좌표/bjd를 노출 안 해 **이름-only**
  (축제명 변별력 높음). 매칭 결과는 `_FestivalMatch`(FestivalMatch Protocol 구현, frozen 아님 —
  Protocol mutable 속성). `providers/__init__` re-export.
- **검증**: ruff + mypy --strict(81 files) + lint-imports + 단위 8건(정확매칭/임계값 미달/빈 title/
  최고점 선택/blank 후보/임계값 검증) + 전체 unit 929 + coverage 80.72%.

**다음(52b-2/3)**: `load_enrichment_links` client/repo(`upsert_source_record`+`upsert_source_link`
재사용) → `fetch_visitkorea_festival_events` fetcher + `feature_event_visitkorea_enrichment` asset
(datagokr 축제 candidate 로드 → matcher → `festival_to_enrichment_links` → load).

## 2026-06-07 (claude) — T-RV-52a visitkorea provider 보강(TourItem festival/detail 필드)

**작업**: 축제 enrichment(point 5)를 위한 provider 보강(cross-repo). krtour
`VisitKoreaFestivalItem` Protocol은 `event_start_date`/`event_end_date`/`overview`/`homepage`
속성을 요구하나 provider `TourItem`에 없어 구조적 미충족이었다.

- **`python-visitkorea-api#17`(merged, v0.2.0)**: `TourItem`에 4필드 추가 —
  `event_start_date`/`event_end_date`(searchFestival `eventstartdate`/`eventenddate`를 `_tour_item`
  에서 promote, str YYYYMMDD, 비축제는 None) + `overview`/`homepage`(detailCommon 보강용, list
  응답엔 보통 None, raw에 있으면 채움). 기존 API 호환(필드 추가만). ruff/mypy --strict/pytest 96
  passed(신규 2). origin/main 이동으로 rebase(AGENTS.md/.codegraph 정리) 후 머지.
- **설계 메모**: `overview`/`homepage`는 detailCommon에서만 오므로, 52b 매칭된 축제 item에 한해
  N+1 `detail_common(content_id)` 호출로 보강한다(전체 축제 N+1 회피).

**다음(52b — krtour)**: `fetch_visitkorea_festival_events` fetcher + DB-coupled `FestivalMatcher`
(로드된 datagokr 축제와 name+region fuzzy 매칭, ADR-016) + enrichment asset
(`festival_to_enrichment_links`) + client `load_enrichment_links`. 52c는 dedup-review와 동일 UI에서
매칭/enrichment 검토. **enrichment는 feature-load와 달리 DB-coupled(1차 datagokr 적재 선행)이라
별도 설계 — 다음 턴 집중 구현.**

## 2026-06-07 (claude) — T-RV-54c+54d 박물관/미술관 MOIS dedup + ETL preview → T-RV-54 완료

**작업**: 박물관/미술관 MOIS dedup scope + admin ETL preview 등록(54c+54d 묶음 PR).

- **54c dedup**: `DEFAULT_DEDUP_SCOPE_PAIRS`에 left `{data.go.kr-standard, datagokr_museums}` ↔
  right `{python-mois-api, categories [01040000]}` pair 추가. MOIS `museums_and_art_galleries`는
  `01040000`(문화시설)으로 적재되므로 그 카테고리로 좁힘. 기본 pair 3건(knps↔krheritage,
  krforest↔mois, museum↔mois).
- **54d ETL preview**: `etl_fixtures.FIXTURE_REGISTRY`에 `data.go.kr-standard/datagokr_museums`
  entry(`_Museum` fixture + `museums_to_bundles` convert) 추가 → `/debug/etl` 노출.
- **검증**: ruff + mypy --strict(dagster 13 / admin 25) + dagster maintenance 3 + etl router 25 +
  `run_fixture_preview`(count 2, cats 01040100 박물관/01040200 미술관) 확인.

**T-RV-54 완료**(54a transform / 54b asset+fetcher / 54c MOIS dedup / 54d ETL preview).
**다음**: T-RV-52 visitkorea 축제 enrichment(provider 보강 선행) 또는 T-RV-55 보조 데이터소스.

## 2026-06-07 (claude) — T-RV-54b 박물관/미술관 feature-load asset + fetcher

**작업**: 박물관/미술관 Dagster feature-load asset 연결(54a transform 소비).

- **fetcher** `fetch_standard_museums`(sync generator — datagokr client는 sync):
  `DataGoKrClient(api_key).museum_art.iter_all()` yield, credential `data_go_kr_service_key`,
  `finally: close()`.
- **resources**: `standard_museums` spec(provider python-datagokr-api, dataset datagokr_museums) +
  guard→live override.
- **assets**: `feature_place_standard_museums`(`museums_to_bundles` 소비, provider data.go.kr-standard)
  + `FEATURE_LOAD_ASSETS` 등록.
- **definitions**: REQUIRED_RESOURCE_KEYS에 standard_museums 추가.
- **검증**: ruff + mypy --strict(13 files) + lint-imports + dagster 64 passed(fake museum_art 2 +
  asset 등록 + live key).

**다음**: T-RV-54c(museum↔MOIS dedup pair `01040000`/`01040100`/`01040200` ↔ MOIS
museums_and_art_galleries 01040000) → 54d(ETL preview).

## 2026-06-07 (claude) — T-RV-54a 박물관/미술관(standard_data) transform

**작업**: ADR-034 9단계 박물관/미술관 변환(`standard_data.py` 확장, provider datagokr `museum_art`
READY).

- `museums_to_bundles`(place) + `PublicMuseumArtItem` Protocol(`PublicMuseumArtGallery` 정합:
  fclty_nm/fclty_type/rdnmadr/lnmadr/lat·lon float/oper_phone_number/homepage_url/instt_code).
- category는 `fclty_type` 기준 박물관(`01040100`)/미술관(`01040200`) 분기(`_resolve_museum_category`),
  미상 시 부모 문화시설(`01040000`). place_kind `museum`, marker = category maki(or `museum`) +
  `MUSEUM_MARKER_COLOR`(P-09). 좌표 float→Decimal, 안정키 `instt_code`(없으면 `name::road` 파생).
  `STANDARD_DATA_PROVIDER_NAME` 공개 alias 추가. `providers/__init__` re-export.
- **검증**: ruff + mypy --strict(81 files) + lint-imports(4 kept) + 단위 7건 + 전체 unit 921 +
  coverage 80.64%.

**다음**: T-RV-54b(`fetch_standard_museums` fetcher + `feature_place_standard_museums` asset +
resource) → 54c(museum↔MOIS dedup pair) → 54d(ETL preview).

## 2026-06-07 (claude) — T-RV-53d krforest ETL preview 등록 → T-RV-53 완료

**작업**: krforest를 admin 디버그 ETL preview 레지스트리에 등록(데이터소스별 debug UI surface).

- `etl_fixtures.FIXTURE_REGISTRY`에 `krforest_recreation_forests`/`krforest_arboretums` 2 entry +
  fixture dataclass(`_RecreationForest`/`_Arboretum`) + builder + `*_to_bundles` convert 추가 →
  `/debug/etl/providers`·`/debug/etl/{provider}/{dataset}/preview`에 자동 노출(dry-run place
  FeatureBundle, DB write 없음). dedup은 dedup-review UI(T-RV-51a)에 자동 노출.
- **검증**: ruff + mypy --strict admin(25 files) + etl router 25 passed + `run_fixture_preview`
  실행(recreation 2건·arboretum 1건, kind=place) 확인.
- **NOTE**: ETL preview 레지스트리는 Sprint-2 provider(datagokr/kma/opinet/krex)만 있었고
  knps/krheritage/mois도 미등록 상태 — 후속 정리 후보로 tasks에 기록.

**T-RV-53 완료**(53a transform / 53b asset+fetcher / 53c MOIS dedup / 53d ETL preview).
**다음**: T-RV-54 박물관/미술관(standard_data, datagokr museum_art) — 동일 4-step.

## 2026-06-07 (claude) — T-RV-53c 자연휴양림↔MOIS dedup scope

**작업**: 휴양림이 MOIS 콘도/관광숙박과 중복 가능(ADR-034 8단계) → `DEFAULT_DEDUP_SCOPE_PAIRS`에
pair 추가. left `{python-krforest-api, krforest_recreation_forests}` ↔ right `{python-mois-api,
categories [03010100 관광숙박, 03020100 전문리조트, 03020200 종합리조트]}`로 MOIS side를 관련
LODGING 카테고리로 좁혀 대규모 MOIS 전체 비교를 회피. 기본 dedup 실행 시 자동 큐 적재.

- **수목원(arboretum) 제외 근거**: MOIS PROMOTED 42 슬러그에 식물원/수목원이 없어(`mois.py`
  PROMOTED_CATEGORY_BY_SLUG 확인) dedup 후보가 없다 → arboretum↔MOIS pair 미추가.
- **검증**: ruff + mypy --strict(13 files) + dagster 단위(기본 pair 2건: knps↔krheritage,
  krforest↔mois) green.

**다음**: T-RV-53d(krforest admin UI: ETL preview + feature 상세 + dedup 노출).

## 2026-06-07 (claude) — T-RV-53b krforest feature-load asset + fetcher wiring

**작업**: 휴양림/수목원 Dagster feature-load asset 연결(53a transform 소비).

- **fetcher**(`provider_fetchers.py`, async generator — `ForestClient`가 async):
  - `fetch_krforest_recreation_forests` — `client.iter_pages(client.travel.standard_recreation_forests,
    num_of_rows=1000)` 페이지네이션, `StandardRecreationForest` yield.
  - `fetch_krforest_arboretums` — `client.travel.recreation_forest_arboretums()`(SHP→tuple) yield.
  - credential = `data_go_kr_service_key`(env `DATA_GO_KR_SERVICE_KEY`), `finally: aclose()`.
- **resources**: `krforest_recreation_forests`/`krforest_arboretums` spec + guard→live override.
- **assets**: `feature_place_krforest_recreation_forests`/`feature_place_krforest_arboretums`
  (`recreation_forests_to_bundles`/`arboretums_to_bundles` 소비) + `FEATURE_LOAD_ASSETS` 등록.
- **definitions**: REQUIRED_RESOURCE_KEYS에 2키 추가.
- **검증**: ruff + mypy --strict(map 81 / dagster 13) + lint-imports + dagster 62 passed(fake
  ForestClient fetcher 3 + asset 등록 + live key). arboretum SHP는 provider geo extra 의존(실 fetch
  검증 T-212e).

**다음**: T-RV-53c(krforest↔MOIS dedup pair를 `DEFAULT_DEDUP_SCOPE_PAIRS`에 append) → 53d(admin UI).

## 2026-06-07 (claude) — T-RV-53a krforest(휴양림/수목원) transform 신설

**작업**: ADR-034 8단계 휴양림/수목원 데이터소스의 변환 계층(`providers/krforest.py`) 신설
(provider `python-krforest-api` READY).

- **transforms**(place, `standard_data` 패턴 미러):
  - `recreation_forests_to_bundles` — 휴양림, category `LODGING_RECREATION_FOREST`(03030000),
    place_kind `recreation_forest`. provider `StandardRecreationForest`(institution_code/name/
    address/lat·lon float/phone/homepage/forest_type) 소비.
  - `arboretums_to_bundles` — 수목원/식물원, category `TOURISM_BOTANICAL`(01030000), place_kind
    `arboretum`. provider `ForestSpatialPoint`(SHP point) 소비.
- **Protocol** `RecreationForestItem`/`ForestSpatialItem`. 좌표 WGS84 float→`Decimal(str)` 변환
  (Coordinate는 Decimal). 안정키 `institution_code`(없으면 `name::sido`/`name::region` 파생,
  ADR-009 `::`). `PlaceDetail`(phones≤3 / facility_info에 forest_type·homepage 보존).
  marker는 category maki(`mapbox_maki_icon_or_none` or `park`) + `KRFOREST_MARKER_COLOR`(P-05).
- `providers/__init__` re-export(import 알파벳 순 krex→krforest→krheritage).
- **검증**: ruff + mypy --strict(81 files) + lint-imports(4 kept) + 단위 9건 + 전체 unit 914
  passed + coverage 80.53%.

**다음**: T-RV-53b(`fetch_krforest_*` fetcher + `feature_place_krforest_*` asset + resource;
arboretum SHP file 경로) → 53c(krforest↔MOIS dedup pair를 `DEFAULT_DEDUP_SCOPE_PAIRS`에 append)
→ 53d(admin UI).

## 2026-06-07 (claude) — T-RV-51b 기본 dedup scope baked (config 없이 cross-provider dedup)

**작업**: `refresh_dedup_candidates_op`이 그동안 Dagster run config의 `pairs`/`sibling_scopes`로만
scope를 받아(기본 빈 목록) 운영자가 매번 config를 넘겨야 했다 → 기본 scope를 코드에 baked.

- `maintenance.py`: `DEFAULT_DEDUP_SCOPE_PAIRS`(현재 **knps↔krheritage** 1쌍 — 동일 사찰/문화재가
  양 provider에 중복 적재 가능, ADR-034 6단계) + `DEFAULT_DEDUP_SIBLING_SCOPES`(현재 없음) 상수.
  op은 `pairs`/`sibling_scopes`가 **둘 다 비면** 기본값 적용 → run config 없이도 cross-provider
  dedup이 돈다. canonical provider name(`python-knps-api`/`python-krheritage-api`) 사용. 실제 중복만
  threshold(0.65) 이상 큐 적재되므로 비중복은 노이즈 안 됨.
- **확장 규약**: 신규 MOIS-sibling provider(krforest 휴양림/수목원·standard_data 박물관/미술관)는
  해당 feature-load PR에서 `{left:{provider:<new>}, right:{provider:python-mois-api}}` pair를
  `DEFAULT_DEDUP_SCOPE_PAIRS`에 append(ADR-034 8/9단계).
- **검증**: ruff + mypy --strict(13 files) + lint-imports + dagster suite 59 passed/1 skip(빈
  config→기본 pair 적용 단위 추가).

**T-RV-51 완료**(51a merge UI + 51b 기본 scope). **다음**: T-RV-53 krforest(휴양림/수목원)
feature-load — transform→asset→MOIS dedup→admin UI 세분화 PR.

## 2026-06-07 (claude) — T-RV-51a dedup merge master 선택 UI (수동 처리)

**작업**: dedup 수동처리 UI 완성(point 4). `dedup-review` 화면이 그동안 accept/reject/ignore만
지원하고 merge는 "master 선택 UI 필요한 후속"으로 비워져 있었다 → merge 액션을 추가했다.

- **frontend-only**(backend PATCH `decision=merged`+`master_feature_id` + `merge_dedup_review`의
  `select_master` 자동 선정은 기구현, API/types 무변): `dedup-review-client.tsx`에 merge 버튼 +
  inline master 선택 패널(`A: <name>·좌표✓` / `B: <name>·좌표✓` / **자동 선정** / 취소).
  - 자동 선정: `master_feature_id` 미전달 → backend `select_master`(좌표→updated_at→provider
    우선순위, ADR-016).
  - 수동: feature A/B의 `feature_id`를 master로 전달. 좌표 보유 여부(`select_master` 1순위)를
    버튼에 힌트로 표기.
- **검증**: `tsc --noEmit` + `eslint .` + `next build`(/admin/dedup-review 포함 13페이지) green.
  기존 e2e(render smoke: heading + status select) 유지.

**다음**: T-RV-51b(maintenance.py 기본 dedup scope baked) → 이후 데이터소스(krforest/museum/
visitkorea)에서 소스별 MOIS dedup scope 추가.

## 2026-06-07 (claude) — T-RV-50 maplibre-vworld-js v0.1.3 최신화

**작업**: maplibre-vworld-js 최신 dependency 업데이트(point 6). frontend 핀이 이미 최신 **태그**
v0.1.2였고, `v0.1.2..main` diff는 **docs-only**(consumer feature catalog #46 + tasks #45, `src/`·
`dist`·public API 동일).

- **maplibre repo**: v0.1.2 이후 docs 커밋을 캡처하는 **v0.1.3** patch 릴리스 cut
  (`maplibre-vworld-js#47` merged → `v0.1.3` 태그 push). 기능 변경 없음.
- **krtour frontend**: `package.json` 핀 `#v0.1.2`→`#v0.1.3`. public API 불변이라 **map wrapper
  코드 수정 불필요**(features-client.tsx 등 그대로).
- **검증**: `npm ls maplibre-vworld` → `0.1.3 (git+...#2a13ce0)` resolve 확인 + `tsc --noEmit`
  green + `next build` 13 페이지(/features의 maplibre 렌더 포함) green. 기능 동일이라 Windows
  Playwright e2e 거동 불변(CI type-check+build 게이트가 권위 검증).

**다음**: T-RV-51 dedup 수동처리 UI 완성 + 기본 scope.

## 2026-06-07 (claude) — T-RV-50 시리즈 프로그램 구체화 (데이터소스 전수 + dedup UI + maplibre)

**작업**: 사용자 지시(T-RV-04b 및 후속 관련 모든 task 완료까지 진행, 7개 요구사항)에 따라
provider 라이브러리 surface 전수 조사 후 `docs/tasks.md`에 **T-RV-50~55** 프로그램을 PR 단위로
구체화했다(이 PR은 plan-only).

- **조사 결론**: ADR-034 9단계 중 1~7 완료. 미구현 = krforest(휴양림/수목원, 모듈 없음) /
  standard_data 박물관·미술관(festival만) / visitkorea 축제 enrichment(모듈 있음·미wiring).
  dedup 인프라 성숙(scoring/queue/admin router+`dedup-review` page)하나 merge master 선택 UI 미완
  + 기본 scope 미설정. provider READY 판정: krforest(`ForestClient.travel.standard_recreation_forests`
  →`StandardRecreationForest`), datagokr museum(`museum_art.iter_all`→`PublicMuseumArtGallery`).
  visitkorea NEEDS-FIX: `search_festival`→`TourItem`에 eventstart/end date·overview·homepage 미노출
  (detail_common N+1) → provider 보강 PR 예정.
- **프로그램**: T-RV-50 maplibre 최신화 / T-RV-51 dedup 수동 UI+기본 scope / T-RV-52 visitkorea
  enrichment(provider+krtour+UI) / T-RV-53 krforest / T-RV-54 museum / T-RV-55 point-7 후속.

**다음**: T-RV-50부터 순차 PR(격리 sandbox + 게이트 전수, provider 수정은 해당 repo PR+머지 선행).

## 2026-06-07 (codex) — T-212b admin UI 핵심 화면 보강

**작업**: T-212b admin UI lane 착수. 이미 T-212c에서 backend 계약이 닫힌 표면을
frontend 운영 화면으로 연결했다.

- **Admin features**: `/admin/features` route 추가. `GET /admin/features` 기반 검색/
  status/kind/issue/sort/page size/cursor table, 선택 상세(`GET /features/{id}`),
  weather panel(`GET /features/{id}/weather`), 단건 deactivate mutation.
- **Admin issues**: `/admin/issues` route 추가. 목록 필터(q/status/severity/type/
  provider/dataset/bbox), 상세 payload/feature snapshot, resolve/ignore/reopen/
  retry_geocode/retry_reverse_geocode/apply_kor_travel_geo_address/manual_override action.
- **Ops logs**: `/ops/logs` route 추가. `GET /ops/system-logs`와
  `GET /ops/api-call-logs` 조회 탭, 필터, cursor.
- 기존 `/features` 상세 panel에 weather card 노출. sidebar nav, frontend README,
  `admin-ops.spec.ts` smoke 추가.
- 기존 `/admin/dagster` Recent runs의 run id를 Dagster webserver run detail 링크로
  연결.

**검증**: WSL Node 20.20.2. `npm run type-check` ✅, `npm run lint` ✅, env 명시
`npm run build` ✅, `npm run doctor` 실행 및 diff 확인(잔여 10건은 기존 shadcn/ui
primitive/기존 Dagster iframe 탐지/기존 unused detail hook), `npm run test` ✅
(테스트 파일 없음). `http://127.0.0.1:9014` dev server에서 `/admin/features`,
`/admin/issues`, `/ops/logs`, `/features` HTTP 200 확인. Windows 호스트 Playwright
`admin-ops.spec.ts` 9 passed.

**다음**: T-212b 잔여는 Dagster schedule/sensor tick history/backend-backed failure
detail API/UX 후속.

## 2026-06-07 (codex) — Sprint 5 운영 진입 잔여 task 상세화

**작업**: 사용자 지시로 Sprint 5 최종 운영 진입까지 남은 작업을 1-PR 단위로 상세화.

- 신규 리포트 `docs/reports/sprint5-final-task-breakdown-2026-06-07.md` 추가.
- 잔여 축을 `T-RV-04b-opinet-krtour-wiring`, `T-212b-admin-ui-completion`,
  `T-212d-perf-baseline-and-tuning`, `T-212e-live-full-reload-final-verification`,
  `T-210-tripmate-integration-cleanup`, `Sprint 5 closure`로 정리.
- `docs/tasks.md`는 진행 중 요약과 Phase 6/7 하위 task를 최신 main 기준으로 상세화.
- `docs/sprints/SPRINT-5.md`는 상태를 최종 운영 진입 진행 중으로 갱신하고 §4.1에
  잔여 task 순서와 DoD 링크를 추가.
- 다음 구현 후보는 실데이터 없이 시작 가능한 `T-212d` seeded PostGIS perf baseline.

## 2026-06-07 (claude) — T-RV-04b opinet provider 라이브러리 보강(#8) + 조사 결론

**작업**: opinet(주유소/유가) wiring 차단 해소를 위해 사용자 지시(“AI agent로 라이브러리
직접 보강”)대로 **provider `python-opinet-api`를 직접 보강**(cross-repo).

- **조사 결론**: OpiNet OpenAPI에 지역/전국 단위 주유소 목록(bulk) 엔드포인트가
  **물리적으로 없음**. station 반환 공개 API는 `aroundAll`(반경≤5km)/`lowTop10`(top20)/
  `detailById`(단건)뿐, `areaCode`는 코드만·`avg*`는 가격 집계만. PDF 미검증 17종도 전부
  가격 집계/이름 검색. `python-opinet-api#7`에 코멘트로 기록.
- **provider 보강**(`python-opinet-api#8` merged, **v0.2.0**): `iter_stations_in_bbox()`
  (sync+async) 추가 — WGS84 bbox를 `aroundAll` 반경 원 격자(간격 `radius*√2`로 셀 모서리까지
  덮음)로 호출하고 `uni_id` dedup하는 **근사 enumeration**. 빈 셀(`OpinetNoDataError`) skip.
  한계(면적 비례 호출수 급증→bounded 권장, `tel`/`lpg_yn` 부재→`get_station_detail` N+1)를
  README/docstring 명시. test(격자 coverage 수학/√2 간격/invalid/dedup/empty-skip/async) +
  ruff + mypy --strict + 전체 pytest 183 passed. pre-existing 미사용 `import os` 제거.
- **krtour 영향**: opinet은 전국 nightly bulk가 비현실이므로 **bounded bbox 또는 POI-타깃**
  모델로 wiring해야 한다(후속). krtour `OpinetStationItem` Protocol을 provider `Station`
  (name/brand enum/lon·lat float, tel·lpg_yn 없음)에 ADR-044 재정렬 + settings-gated bbox
  fetcher가 남은 작업. docs(tasks)에 후속으로 기록.

**상태**: 이로써 T-RV-04b provider live fetcher wiring은 **opinet krtour-side wiring 1건만
후속**으로 남고(datagokr/krheritage/krex×2/mois A+B/knps×2 전부 merged), opinet provider
라이브러리 보강은 완료. **다음 자율 작업: T-212d perf 부분 진행**(seeded PostGIS EXPLAIN
수집 + 인덱스 후보 분석/문서화; 실 볼륨 측정은 T-212e).

## 2026-06-07 (claude) — T-RV-04b mois Phase A LOCALDATA 소스 DB sync (mois 마무리)

**작업**: MOIS 인허가 **Phase A**(LOCALDATA 다운로드→소스 DB 적재) 구현. Phase B
fetcher(`fetch_mois_license_records`)가 읽는 SQLite 소스 DB를 채우는 단계로, mois를
완결한다.

- **신규 모듈** `mois_source_sync.py`:
  - 순수 helper `sync_mois_source_db(settings, *, service_slugs=None, org_code=None,
    batch_size=1000) -> MoisSourceSyncSummary`. lazy `import mois`(ADR-044). 대상 DB는
    `settings.mois_source_db_path`(미설정 시 `ProviderCredentialMissing`, Phase B와 동일
    계약, 부모 디렉터리 자동 생성). `mois.create_sqlite_schema(engine)` →
    keyless `mois.LocalDataFileClient()` → `mois.sync_localdata_source_db(session, client,
    service_slugs=sorted(PROMOTED_SERVICE_SLUGS), commit=True)`. provider 결과를 krtour
    경계 dataclass `MoisSourceSyncSummary`(scanned/upserted/open/closed/unknown count)로
    복사. engine/session/client finally 정리.
  - Dagster `@op mois_localdata_source_sync`(config: service_slugs/org_code/batch_size,
    `MAINTENANCE_RETRY_POLICY`) + `@job` + 주간 `ScheduleDefinition`
    (`mois_localdata_source_sync_weekly_schedule`, `0 4 * * 1` KST, **STOPPED**).
  - `definitions.py`에 job/schedule 등록.
- **정정(ADR-044)**: 기존 문서가 Phase A에 `data_go_kr_service_key`가 필요하다고
  적었으나, provider `LocalDataFileClient`는 공개 파일 포털(`file.localdata.go.kr`)에서
  받으며 **생성자에 API key 파라미터가 없다 — keyless**. Phase A는 네트워크만 필요.
- **future-import 주의**: Dagster `@op`는 `context` 타입힌트를 런타임 class로 검증하므로
  본 모듈은 `from __future__ import annotations`를 쓰지 않는다(maintenance.py와 동일).

**테스트**: `test_mois_source_sync.py` — fake `mois` 모듈(create_sqlite_schema/
LocalDataFileClient/sync_localdata_source_db) 기반 helper 검증 5건(기본 slug 정렬+commit+
close, custom slug/org/batch 전달, parent dir 생성, db_path 미설정 raise) + op 메타데이터
1건. `test_definitions.py`에 job/schedule 등록 2건 추가. 게이트: `ruff` ·
`mypy --strict kortravelmap.dagster`(13 files) · `lint-imports`(4 kept) · dagster+unit
`963 passed, 1 skipped`(mois optional). 실데이터 검증은 T-212e.

**다음**: T-RV-04b 잔여는 opinet(차단, `python-opinet-api#7` bulk/region endpoint 대기).
mois는 Phase A/B 모두 완료.

## 2026-06-07 (claude) — T-RV-04b ⑥ knps point/geometry live fetcher (provider 보강)

**작업**: KNPS(국립공원/트래킹) point + geometry live fetcher wiring. krtour의
best-guess 컬럼 매핑이 실 헤더(`명칭_한글(KOR_NM)`, `경도(LONGITUDE)` 등)와 어긋나는
문제를, 사용자 지시(“knps는 미완성… 적극적으로 python-knps-api를 수정하며 진행”)에
따라 **provider 라이브러리를 보강**해 해결했다.

- **provider** `python-knps-api#7`(merged, **v0.2.0**): 헤더 정규화 typed record
  `KnpsPlaceRecord`/`KnpsGeoRecord` + read 메서드 `client.files.read_place_records(key)`·
  `read_geo_records(key)` 추가. source_id 우선순위
  `ID_CD→STN_ID→OBJECTID→SEQNO→NO→row-hash`. 실 스키마 3종(standard `(CODE)` 헤더 /
  weather_stations / trails 한글 props)을 라이브로 확인 후 정규화. krtour `KnpsPointRecord`/
  `KnpsGeometryRecord` Protocol을 구조적으로 충족 → krtour transform 무변, best-guess
  컬럼 매핑은 dead.
- **fetcher** `fetch_knps_point_records`/`fetch_knps_geometry_records`: **async
  generator**(다운로드/파싱이 async). `KnpsClient().files.read_*(dataset_key)` await 후
  record yield, `finally: await client.aclose()`. keyless 공개 파일셋이라 credential 불요.
- **resources**: `build_provider_record_live_resource` 시그니처를
  `Iterable[Any] | AsyncIterator[Any]`로 확장(asset `_record_batches`는 이미 sync/async
  iterable 모두 지원). `knps_point_records`/`knps_geometry_records` guard→live 교체.
- **settings/definitions**: `knps_point_dataset_key`(기본 `knps_visitor_centers`)·
  `knps_geometry_dataset_key`(기본 `knps_trails`) 추가. `SETTINGS_VALUE_RESOURCES` +
  `_settings_value_resource`로 fetcher와 asset의 `knps_*_dataset_key` resource가 같은
  `KorTravelMapSettings` 값을 보게 해 불일치 제거.

**테스트**: dagster `test_provider_fetchers.py`에 fake knps client(async
`read_place_records`/`read_geo_records` + `aclose`) 기반 yield/close/dataset-key 검증 3건,
`test_definitions.py` `_LIVE_PROVIDER_RESOURCE_KEYS`에 knps 2키 추가. 게이트:
`ruff` · `mypy --strict`(kortravelmap 80 files / kortravelmap.dagster 12 files) ·
`lint-imports`(4 kept) · dagster+unit `952 passed, 1 skipped`(mois optional) ·
coverage `80.31% ≥ 80`. 실 fetch 검증은 T-212e.

**다음**: mois 마무리(Phase A — LOCALDATA download + `sync_localdata_source_db`
Dagster op/스케줄). 이후 잔여 T-RV-04b는 opinet(차단, `python-opinet-api#7` 대기).

## 2026-06-07 (codex) — T-209 final backup/restore safety automation

**작업**: 사용자 지시에 따라 T-209 계열을 마무리한다. T-212 계열과 T-RV-04b는 Claude
Code 진행 범위라 제외한다.

- **Mutex**: `scripts/with-pg-advisory-lock.py`를 추가하고 backup/restore/swap script가
  PostgreSQL advisory lock `maintenance:backup-restore`를 잡도록 보강한다.
- **Restore verification**: `scripts/docker-restore-verify.sh`가 staging app DB
  `feature.features` count, Dagster table count, RustFS file count를 확인한다.
  `scripts/docker-restore.sh`는 restore 완료 후 기본으로 이 검증을 실행한다.
- **Hot-swap env switch**: `scripts/docker-restore-swap.sh`가 검증된 staging DB/volume을
  가리키는 `.env.restore-swap`을 생성하고, `KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY=1`에서만
  compose 서비스를 재기동한다. `docker-compose.yml`은 RustFS volume name override를
  지원한다.
- **Admin API**: `/admin/restore/{backup_id}/swap`은 manual-required 응답 대신 command
  plan을 반환하고, `execute=true` + command enabled일 때 swap script를 실행한다.
- **문서/테스트**: `docs/backup-restore.md`, `docs/tasks.md`, `docs/resume.md`를
  T-209 완료 상태로 갱신하고 script/admin router 회귀 테스트를 보강한다.

## 2026-06-07 (claude) — T-RV-04b ⑤ mois_license_records (Phase B fetcher)

**작업**: MOIS 인허가 live fetcher(Phase B). provider `mois.db.PlaceRecord`이 krtour
`MoisLicensePlaceRecord` Protocol(~45필드)을 **전부 충족**(clean match, datagokr류) —
재조정 불요. mois 본체 transform 무변.

- **fetcher** `fetch_mois_license_records`: 신규 설정 `mois_source_db_path`(env
  `KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH`)의 **미리 sync된 MOIS 소스 SQLite DB**에 sqlite
  engine+Session 열고 `mois.db.iter_open_place_records(session,
  service_slugs=PROMOTED_SERVICE_SLUGS)` stream, finally close/dispose. DB 미설정/부재 시
  `ProviderCredentialMissing` 명확 실패. resource guard→live.
- **test**: temp sqlite DB에 `mois.db.Base.create_all` + PlaceMaster row(open/closed) 삽입해
  실제 `iter_open_place_records` 실측(영업중만 yield) + engine/session cleanup proxy 검증,
  DB 미설정/부재 guard. test_definitions live key.
- **설정 단순화**: 서브에이전트가 env 이름 맞추려 쓴 `AliasChoices`를 컨벤션(prefix+필드명
  =`KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH`)으로 교체(일관성).
- **Phase A(잔여)**: LOCALDATA 다운로드→소스 DB 적재(`LocalDataFileClient` +
  `sync_localdata_source_db`) Dagster op/스케줄은 별도. 네트워크+키 필요, 실데이터=T-212e.
- **gate**: ruff + mypy --strict(kortravelmap 80 / dagster 12) green, drift green, dagster
  fetcher 19 green, unit coverage 80.31%.
- **현황**: T-RV-04b 5/7 provider wiring 완료(datagokr/krheritage/krex×2/mois). opinet
  ⏸(provider 이슈 #7), knps 잔여, mois Phase A 잔여.

## 2026-06-07 (claude) — T-RV-04b ④ krex_traffic_notices + opinet 차단

**krex_traffic_notices**(ADR-044 재정렬, 사용자 재량 기본값): `KrexTrafficNoticeItem`
Protocol을 provider `Incident` 실제 shape로 재정렬, krtour-side 파생을 transform으로:
notice_id=`::` 복합키(route_no/incident_type/started_at + payload_hash), title 합성
(`[노선] incident_type`), notice_type=`normalize_notice_type`(미매핑 시 "traffic"),
valid_from/until=`_parse_krex_datetime`(다중 포맷 방어적, KST), severity=None,
source_agency="한국도로공사", coord=None(coordless notice — raw_address=route로 strict
검증 통과). fetcher=`KrexClient(ex_api_key).traffic.incident` 페이지네이션. 단위+통합+
admin etl 테스트 갱신. **잔여**: EX incidentType 숫자코드 매핑 테이블(krtour follow-up),
일시적 incident의 영속화는 재실행 갱신+valid_until 만료로 처리(설계 메모).

**opinet 차단**: `aroundAll`(반경 5km)만 있고 bulk/지역 station 목록 엔드포인트 없음 →
전국 enumeration ~2만 호출 비현실. **provider 이슈 `python-opinet-api#7`** 등록(지역/bulk
엔드포인트 래핑 요청). 라이브러리 보강 전까지 wiring 보류(또는 POI 주변 타깃 모델 전환은
product 결정).

**gate**: ruff + mypy --strict(kortravelmap 80 / dagster 12) green, krex+admin+dagster 86 +
통합 dagster etl green, unit coverage 80.31%(krex.py 91%).

**다음(사용자 순서 1→2→3 중)**: mois(Phase B fetcher: 미리 sync된 MOIS 소스 SQLite DB →
`iter_open_place_records(PROMOTED_SERVICE_SLUGS)`; Phase A sync op + `mois_source_db_path`
설정). knps(파일 파서).

## 2026-06-07 (claude) — T-RV-04b ③ krex_rest_areas (ADR-044 재정렬 + 파생 자연키)

**작업**: krex 휴게소 live fetcher. `RestArea` model에 안정 식별자·주소가 없음을 확인
(provider 파서/fixture 모두 부재) → 사용자 결정대로 **option 2(krtour 파생 자연키)**.

- **자연키**: `_rest_area_natural_key` = `name::route_name::direction`(normalize). 처음
  `|` join으로 했다가 ADR-009 `_validate_component`이 `|`를 예약(ID 구분자)해 거부 →
  mois(`{slug}::{mng_no}`)와 동일 `::`로 수정.
- **Protocol 재정렬(ADR-044)**: `KrexRestAreaItem`을 `RestArea` 실제 필드명으로
  (highway_name→route_name, tel→phone_number, longitude/latitude→lon/lat), uni_id·address
  제거. `_rest_area_item_to_bundle` 입력 read + 자연키 사용처 전부 갱신(출력 DTO 계약 불변,
  address=None). admin `etl_fixtures.py`/`etl_live.py` krex 어댑터 + 그 테스트도 갱신.
- **wiring**: `fetch_krex_rest_areas`(`KrexClient(go_api_key=krex_go_api_key).restarea.
  list_all` 페이지네이션) + resource guard→live + dagster 단위(fake) + test_definitions.
- **provider upstream**: `RestArea`에 안정 id·address 노출은 직접 수정 대신 **상세
  GitHub 이슈 `python-krex-api#7`**로 등록(사용자 지시: 라이브러리 수정 건은 AI agent
  작업용 이슈로). 노출되면 파생키→안정키 교체 가능.
- **gate**: ruff + mypy --strict(kortravelmap 80 / dagster 12) green, krex unit + admin etl +
  dagster(78) + 통합 dagster etl green, unit coverage 80.22%(krex.py 91%).
- **다음**: krex_traffic_notices(Incident 대거 미충족 — provider 이슈 필요), opinet/mois/knps.

## 2026-06-07 (claude) — T-RV-04b ② krheritage_events (ADR-044 재조정 + cross-repo)

**작업**: krheritage_events live fetcher. 검증 결과 provider model `HeritageEvent`이
krtour `KrHeritageEvent` Protocol과 불일치(필드명 starts_on/place/address ≠
start_date/venue_name/location_text, `raw` 부재)임을 발견 → ADR-044 cross-repo 재조정.

- **upstream PR `python-krheritage-api#4`(merged)**: `HeritageEvent.raw` 주입(sibling
  IntangibleRecord/legacy/research 모델과 정합, downstream source_records.raw_data용).
  provider repo ruff/mypy/pytest(25) green.
- **krtour 재조정**: `KrHeritageEvent` Protocol property를 provider 실제 필드명으로 재정렬
  (start_date→starts_on, end_date→ends_on, venue_name→place, tel→tel_name,
  location_text→address). `_event_to_bundle` 입력 read 5곳 갱신(출력 EventDetail 계약 불변).
  `test_providers_krheritage.py` fake event 필드명 갱신.
- **wiring**: `fetch_krheritage_events`(`HeritageClient.event.iter_months()` provider 기본
  rolling window) + resource guard→live. dagster fetcher 단위(fake) + test_definitions
  live key.
- **gate**: ruff + mypy --strict(kortravelmap 79 / kortravelmap.dagster 12) green, krheritage
  transform+dagster 43 + 39 dagster suite green, unit coverage 80.23%(krheritage.py 83%).
- **교훈**: 감사의 "ASSUMED CLEAN"은 신뢰 불가 — provider는 wiring 전 model↔Protocol
  실검증 필수. datagokr 외 전부 mismatch 가능성. 사용자 승인으로 provider 레포 편집 가능.
- **다음**: krex(2)/opinet/mois/knps — 각 provider model 실검증 + 재조정/정책. 동일 cross-repo
  패턴 적용 가능.

## 2026-06-07 (codex) — T-209e-c backup/restore admin surface

**작업**: T-209e backup/restore 묶음의 admin router/UI 표면을 추가한다. T-212 계열과
T-RV-04b는 Claude Code 진행 범위라 제외한다.

- **Artifact helper**: `kortravelmap.infra.backup`이 `data/backups/<backup_id>` manifest,
  checksum count, directory size를 읽어 최신순으로 정렬한다.
- **Admin API**: `/admin/backups`, `/admin/backups/{backup_id}`,
  `/admin/restore/{backup_id}`, `/admin/restore/{backup_id}/swap`을 추가한다. backup/restore
  실행은 기본 plan-only이며 `KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED=true` opt-in에서만
  host command를 실행한다.
- **Admin UI**: `/admin/backups`에서 artifact 목록, manifest 요약, backup/restore command
  plan, manual-required hot-swap 경계를 보여준다.
- **검증**: NTFS `ruff check .`, OpenAPI `--profile all --check`, frontend
  `gen:types:check`/`type-check`/`lint`, React Doctor verbose(새 파일 경고 없음),
  production build 통과. ext4 `ruff check .`, OpenAPI check, `lint-imports`,
  `mypy --strict`, admin package 전체 `214 passed`, unit 전체 `894 passed`.
- **잔여**: ADR-039 advisory lock critical section, staging restore 후 smoke/count check
  자동화, 운영 DSN/volume hot-swap 자동 실행은 후속으로 남긴다.

## 2026-06-07 (codex) — T-RV-37 잔여 hygiene

**작업**: PR 리뷰 후속 LOW 묶음 `T-RV-37` 잔여 hygiene을 정리한다.

- **Admin naming**: frontend `DebugUiApiError`와 `/version`의 `debug_ui` 필드를
  `ApiClientError`/`admin`으로 rename하고 OpenAPI/frontend type drift를 갱신한다.
- **Search count**: `FeatureSearchPage.total_count`를 실제 검색 조건 전체 매칭 수로
  채우도록 repo SQL과 router/integration 테스트를 보강한다.
- **Offline upload**: upload create의 `detected_encoding`은 `None`으로 저장해 parser
  fallback에 맡기고, Dagster launch repository selector는
  `KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_NAME` /
  `KOR_TRAVEL_MAP_API_DAGSTER_REPOSITORY_LOCATION_NAME` 설정으로 이동한다.
- **Runtime hygiene**: custom CORS middleware를 제거해 `CORSMiddleware`로 일원화,
  router/Dagster의 S3 store factory 중복을 main infra helper로 통합, kor-travel-geo
  timeout을 설정화, frontend production `NEXT_PUBLIC_*` 누락은 fail-fast 처리한다.
- **제외**: `admin_issues.py` timeout은 T-212, `T-RV-04b` provider live fetcher wiring은
  별도 Claude Code 범위라 이번 PR에서 건드리지 않는다.
- **다음**: T-RV-37 PR/CI/merge 후 사용자 지시에 따라 `T-209e-c`로 이동한다.

## 2026-06-07 (claude) — T-RV-04b provider 적합성 감사 (datagokr 외 전부 결정 선행)

**작업**: datagokr(#261) 이후 provider를 순차 wiring하려다, krex_rest_areas에서
`RestArea` model이 `KrexRestAreaItem` Protocol을 2/8만 만족(uni_id·address 없음)함을
발견. 사용자 지시("이미 구현됐는지 확인하면서")에 따라 나머지 provider 전수 적합성 감사
수행.

- **리포트**: `docs/reports/t-rv-04b-provider-fetcher-audit-2026-06-07.md` — provider별
  Protocol↔model 일치 + bulk fetch 가능 여부 매트릭스.
- **결론**: datagokr만 clean. 나머지 6종은 설계 결정 선행:
  - krex_rest_areas/traffic = Protocol↔model 불일치(ADR-044 재조정: upstream PR 또는
    krtour Protocol 재정렬 + uni_id 자연키 결정).
  - opinet = bulk 없음(grid 검색 정책), mois = SpatiaLite DB파일 refresh 정책,
    knps = keyless 파일셋 파서 어댑터, krheritage = GIS 보강 루프(events는 비교적 깨끗).
- **미수행(의도적)**: 불일치 Protocol에 wiring(런타임 AttributeError) / krtour Protocol·
  transform 무단 재작성(정규화 계약 변경 — dedup/idempotency 영향) / opinet·mois 정책
  무단 결정 — 전부 설계 결정이라 사용자에게 상신.
- **다음**: 결정 후 krheritage_events(모델 실검증)부터, 이어 krex 재조정/opinet 정책 등.

## 2026-06-07 (claude) — T-RV-04b ① datagokr 축제 live fetcher

**작업**: provider live fetcher wiring을 provider 순차로 시작. 첫 provider =
datagokr 전국문화축제표준데이터.

- **패턴 확립**: `provider_fetchers.py` 신설 — `fetch_datagokr_cultural_festivals(settings)`
  (sync 제너레이터, `importlib.import_module("datagokr")` lazy import로 provider 패키지를
  하드 의존/`mypy` 노출에서 분리[ADR-006/044], credential 없으면 `ProviderCredentialMissing`).
  `resources.build_provider_record_live_resource(spec, fetch)` — guard와 동일 shape이나
  credential 있으면 `fetch(settings)` iterable 반환, 없으면 guard 메시지 그대로 raise(무해 degrade).
- **wiring**: `PROVIDER_RECORD_RESOURCE_DEFINITIONS["datagokr_cultural_festivals"]`만
  guard→live 교체(opinet/krex/krheritage/mois/knps는 guard 유지 — 후속 provider).
  `DataGoKrClient.festival.iter_all()`이 `CulturalFestivalItem` Protocol 충족 record yield.
- **검증**: dagster 단위(fake DataGoKrClient: yield + close, credential-missing, live/guard
  resource) + `test_definitions` guard→live 반영. ruff + `mypy --strict -p kortravelmap.dagster`
  + dagster suite 37 passed. provider 패키지 키 없이도(테스트 fake) 통과.
- **확인**: 다른 provider에 기존 live fetcher 구현 없음(중복 아님). 다음 provider부터도
  "이미 구현됐는지 확인 후 추가" 원칙 유지.
- **다음**: opinet(area scope + station detail fetch 정책) → krex → krheritage → mois → knps.

## 2026-06-07 (claude) — 운영 로그 조회 표면 (T-212c-API-04 → T-212c 완료)

**작업**: T-212c 마지막 조각인 system/API-call 로그 조회 표면을 구현. 백킹 테이블이
없어 스키마부터 신설.

- **마이그레이션 `0018_ops_logs`**: `ops.system_log`(level CHECK/source/event/message/
  detail jsonb/request_id) + `ops.api_call_log`(method/path/status_code/duration_ms/
  request_id/error_code). PK `x_extension.gen_random_uuid()`(ADR-008 schema-isolated),
  keyset/필터 인덱스. down_revision=0017, 단일 head.
- **`infra/log_repo.py`**(ADR-004 raw SQL): `record_system_log`/`record_api_call`(INSERT
  RETURNING, commit은 호출자) + `list_system_logs`/`list_api_call_logs`(ops_repo와 동일
  base64 keyset cursor, level/source/q·method/min_status/path 필터).
- **`routers/ops_logs.py`**: `GET /ops/system-logs`·`GET /ops/api-call-logs`(ops tag,
  `ops_routes_enabled`, `{data:{items,next_cursor}, meta:{count,duration_ms}}`).
- **opt-in 미들웨어**: `ApiSettings.api_call_log_enabled`(기본 off) True일 때만 등록.
  요청마다 method/path/status/duration/request_id를 best-effort 적재(`_record_api_call_safe`
  가 단기 세션 열어 INSERT, 모든 예외 swallow → 요청 절대 안 깨짐). 기본 off라 오버헤드 0.
- **error envelope**: `app.py` 중앙 handler가 이미 모든 오류를 `{error:{code,message,
  details,request_id}}` + `X-Request-ID`로 통일(T-212c error contract = 기구현 확인).
- **검증**: log_repo 단위(96%) + ops_logs 라우터 단위 + 미들웨어 단위 + PostGIS 통합
  (마이그레이션 0018 적용 + record/list/cursor/filter 실측). drift green, ruff/mypy
  --strict -p kortravelmap green, unit coverage 80.23%, admin pytest 206, lint-imports green,
  frontend type-check/gen:types:check green. admin-only → openapi.json만.
- **→ T-212c 완료.** 다음: T-212d(성능 baseline)/T-212e(실데이터)는 라이브 스택/실데이터
  필요, T-212b admin UI는 codex lane.

## 2026-06-07 (claude) — `/ops/health-deep` deep readiness (T-212c-API-03)

**작업**: T-212c 중 deep readiness 엔드포인트를 구현. liveness용 public `/health`
(DB-free 정적 200)와 분리해 실제 DB/PostGIS를 친다.

- **`GET /ops/health-deep`**(ops tag, `ops_routes_enabled`): `_check_database`(`SELECT 1`)
  + `_check_postgis`(`pg_extension` 버전) 점검 → `{data:{status, checks[{component,
  status, detail}]}, meta:{duration_ms}}` envelope. 한 컴포넌트라도 error면 전체
  `status=degraded` + HTTP 503(body는 그대로, 모니터링이 컴포넌트별 상태를 읽음).
  `SQLAlchemyError`만 잡아 detail에 축약 보존.
- **검증**: ops 단위 2(ok 200 / degraded 503, 헬퍼 monkeypatch) + PostGIS 통합 2
  (`_check_database`/`_check_postgis` 실측). admin-only → openapi.json만, types.ts 재생성.
- **문서**: contract §4 ops tag + tasks T-212c 체크. **T-212c-API-04(system/API call
  log 조회)는 백킹 테이블 부재 → 스키마 설계 선행 필요로 분리**.
- **다음**: T-212c error envelope 전수 점검 또는 log 스키마 설계, 그 외 T-212d/e.

## 2026-06-07 (claude) — `/admin/issues` 목록 q/bbox 필터 (T-DA-13 deferred 마무리)

**작업**: T-DA-13에서 미뤘던 목록 `q`/`bbox` 필터를 `ops_repo` 확장으로 구현.

- **`ops_repo.list_ops_integrity_issues`**: `q`(message/feature_id/source_record_key
  ILIKE) + `bbox`(연결 feature 좌표 EXISTS 서브쿼리, ADR-012 STORED `coord` 4326
  GiST `&&` + `x_extension.ST_MakeEnvelope`; feature_id 없는 이슈는 bbox 시 제외) 파라미터
  추가.
- **`routers/admin_issues.py`**: `q` 쿼리 + `bbox` CSV(`min_lon,min_lat,max_lon,max_lat`,
  `_parse_bbox_csv` 검증 → 422) 노출, repo로 전달. openapi/types 재생성.
- **검증**: ops_repo 통합 테스트 신설(bbox 포함/제외 + 다른 지역 0건 + q message/feature_id
  매칭, PostGIS 실측), 라우터 단위(q/bbox passthrough + bbox 422) 추가. ruff/mypy/
  lint-imports green, 단위 coverage ≥80%, drift green, frontend gates green.
- **문서**: contract §4.1 필터 목록 갱신(bbox/q deferred 제거), tasks T-DA-13.
- **다음**: T-212c(API error/log contract + `/ops/health-deep` + log 조회 표면).

## 2026-06-07 (claude) — T-DA-13 `/admin/issues` 구현 (DA-D-04 = T-212)

**작업**: ADR-046 주소/좌표 이슈 운영자 수동 처리 API `/admin/issues`를 구현. T-DA-15/16/18
envelope 통일을 사전작업으로 끝낸 뒤 T-212 핵심을 착수했다(사용자 결정: 전체 액션 한 번에).

- **신규 `routers/admin_issues.py`**: GET 목록(`ops_repo.list_ops_integrity_issues`
  keyset cursor, 필터 issue_type/provider/dataset_key/severity/status/feature_id), GET 단건
  (`integrity_violation_repo` + feature 주소/좌표 스냅샷), PATCH 7 action —
  resolve/ignore/reopen(`set_data_integrity_violation_status`),
  retry_geocode/retry_reverse_geocode(kor-travel-geo 정/역지오코딩 candidate 반환, 상태 무변),
  apply_kor_travel_geo_address(역지오코딩 결과를 정본 주소로 적용 + resolve),
  manual_override(요청 address/coord/행정코드 적용 + resolve). 모두 `{data, meta}` envelope.
  kor-travel-geo 호출은 `_forward_geocode`/`_reverse_geocode` 모듈 헬퍼 뒤(base URL 미설정 503,
  httpx 오류 502). 상태충돌 409, 검증 422, 미존재 404.
- **신규 `infra/feature_address_repo.py`**(ADR-004 raw SQL): `get_feature_address_snapshot`
  + `apply_feature_address_override`(FOR UPDATE 잠금 → 제공 필드만 `feature.features` UPDATE,
  좌표는 `ST_SetSRID(ST_MakePoint())` 4326 → 변경 field_path별 `ops.feature_overrides`
  active upsert, source_value=직전 값, ON CONFLICT (feature_id, field_path) WHERE status='active').
- **검증**: 라우터 단위 14(repo monkeypatch) + **PostGIS 통합 3**(override SQL 실측 —
  단위는 repo를 mock하므로 SQL은 통합 테스트에서만 실행). CI ruff(src tests) green,
  `mypy --strict -p kortravelmap`(78 files) green, lint-imports green, 전체 admin pytest
  196 + 신규 17 green. openapi.json에 `/admin/issues` 2 path 추가(admin-only,
  user spec 무변), types.ts 재생성, frontend type-check/gen:types:check green.
- **문서**: contract §4 표 + §4.1 "구현 완료"로 갱신(bbox/q 필터 deferred 명시), tasks
  T-DA-13 ✅. **DA-D-04 = T-212 핵심 API 완료.**
- **다음**: admin UI(승인/거절/지도 검토)는 **T-212b**(codex lane) — 겹치지 않게 조율.
  남은 T-212: b(UI)/c(error·log contract)/d(성능)/e(실데이터). bbox/q 목록 필터는
  `ops_repo` 확장 후속.

## 2026-06-06 (codex) — T-RV-27/40/41 운영 hardening + consistency F6

**작업**: 남은 PR 리뷰 후속 중 같은 운영 hardening/performance 범위인 T-RV-27,
T-RV-40, T-RV-41을 한 PR로 묶어 반영한다.

- **T-RV-27**: Docker compose host publish 기본값을
  `KOR_TRAVEL_MAP_DOCKER_BIND_HOST=127.0.0.1`로 제한했다. 컨테이너 내부 listen은 유지하되
  host 모든 interface 노출은 명시 opt-in + 네트워크 보호 전제로 문서화했다.
- **T-RV-40**: F6 opening_hours consistency SQL이 `feature.features`를 4회 읽지 않도록
  `candidate_features` CTE + 단일 `CROSS JOIN LATERAL` period expansion으로 통합했다.
- **T-RV-41**: MV `CONCURRENTLY` 전제를 T-101 체크리스트와 performance/Dagster 문서에
  `UNIQUE` 인덱스 + 최초 비-concurrent populate 후 전환으로 고정했다.
- **문서**: tasks, resume, PR#153~179/181~233 리뷰 리포트, Docker/deploy/Dagster 문서를
  완료 상태에 맞춰 갱신했다.
- **다음**: T-RV 잔여는 `T-RV-37` 잔여 hygiene과 `T-RV-04b` provider live fetcher
  wiring이다.

## 2026-06-06 (claude) — T-DA-18 nux-seen envelope (DA-D-03 코드 전환 완료)

**작업**: T-DA-16 중 발견한 `POST /ops/dagster/nux-seen` flat bare를 `{data, meta}`로
통일. 이로써 **DA-D-03 전면 통일(T-DA-15/16/18) 코드 전환 완료**.

- **`/ops/dagster/nux-seen`**: `DagsterNuxSeenData` 분리 + envelope. 4개 return
  (error/unavailable/graphql-error/ok)을 `_nux_seen_response` 헬퍼로 wrap
  (`meta.duration_ms`, summary와 동일 `DagsterDetailMeta` 재사용).
- **frontend**: `useMarkDagsterNuxSeen`는 응답 본문 미소비 → 소비측 무변, types만 재생성.
- **test**: nux-seen 2개(`posts_mutation`, `rejects_invalid_graphql_override`)를
  `body["data"]`/`meta`로 갱신.
- **gate**: drift green, ruff/mypy --strict green, dagster+export_openapi pytest
  8 passed, frontend type-check/gen:types:check/eslint green.
- **문서**: contract §3.1을 "전면 통일 완료(예외=GET /features 호환 1건)"로 갱신,
  tasks T-DA-18 ✅.
- **다음**: **T-DA-13 `/admin/issues`**(DA-D-04 = T-212) — `ops.data_integrity_violations`
  기반 GET 목록/GET 단건/PATCH(action) 운영 워크플로 구현.

## 2026-06-06 (claude) — T-DA-16 envelope 통일 ⑤ dagster summary + mois detail (T-DA-16 완료)

**작업**: T-DA-16 마지막 enumerated 단건 bare 2건을 `{data, meta}`로 통일 →
**T-DA-16 완료**.

- **`/ops/dagster/summary`**: flat `DagsterSummaryResponse` → `DagsterSummaryData`로
  분리하고 envelope. 3개 return(error/unavailable/ok) 전부 `_summary_response`
  헬퍼로 감쌈(`meta.duration_ms`).
- **`/debug/mois-license/{id}`**: `MoisLicenseDetailData`(record) + `meta.{cached,
  duration_ms}`로 분리. 프로세스 캐시는 Data를 저장하고 hit/miss에 따라 `meta.cached`
  설정(기존 `model_copy(cached=True)` 대체).
- **frontend**: `dagster-client.tsx` `const data = summary.data?.data` 한 줄로 하위
  `data?.X` 전체 흡수, `home-client.tsx`는 `dagsterData` alias 도입. mois는 프런트
  소비처 없음. openapi/types 재생성.
- **test**: dagster summary 3개 + mois 1개를 `body["data"]`/`meta`로 갱신.
  nux-seen 테스트는 그대로(아직 bare).
- **추가 발견**: `POST /ops/dagster/nux-seen`도 flat bare → DA-D-03 "예외 없음"에
  걸리나 감사 미열거. 스코프 유지 위해 envelope 미적용하고 **T-DA-18**로 분리 기록.
- **gate**: drift green, ruff/mypy --strict green, dagster+mois+export_openapi
  pytest 12 passed, frontend type-check/gen:types:check/eslint green.
- **문서**: contract §3.1 단건 bare 예외를 nux-seen만 남김, tasks T-DA-16 ✅ +
  T-DA-18 신설.
- **다음**: (소) T-DA-18 nux-seen → **T-DA-13 `/admin/issues`**(DA-D-04 = T-212).

## 2026-06-06 (claude) — T-DA-16 envelope 통일 ④ ops metrics/import-job 단건

**작업**: T-DA-16 잔여 단건 bare 중 ops 라우터 2건을 `{data, meta}`로 통일.

- **`/ops/metrics`**: flat 본문 → `OpsMetricsData`로 분리하고
  `OpsMetricsResponse{data, meta(duration_ms)}`로 감쌈. `_metrics_response`에
  `started_at` 전달.
- **`/ops/import-jobs/{job_id}`**: `{data}`만 있던 응답에 `meta.duration_ms` 추가
  (`OpsDetailMeta` 신설, list `OpsListMeta`와 별개).
- **frontend**: `home-client.tsx`·`consistency-client.tsx`에서 `metrics.data?.X` →
  지역 alias `metricsData = metrics.data?.data` 도입 후 `metricsData?.X`로 정리.
  import-job 단건은 `meta` 추가가 가산적이라 소비측 무변. openapi/types 재생성.
- **test**: `test_ops_router` metrics 검증을 `body["data"]`/`meta.duration_ms`로 갱신.
- **gate**: drift green, ruff/mypy --strict green, ops+export_openapi pytest 7 passed,
  frontend type-check/gen:types:check/eslint green.
- **문서**: contract §3.1 bare 예외에서 metrics/import-jobs 제거.
- **다음**: T-DA-16 잔여 `/ops/dagster/summary` + `/debug/mois-license/{id}` →
  T-DA-13 `/admin/issues`.

## 2026-06-06 (claude) — T-DA-15/16 envelope 통일 ③ poi-cache-targets (T-DA-15 완료)

**작업**: DA-D-03 세 번째 family로 `/admin/poi-cache-targets` list/detail 응답을
`{data, meta}` envelope로 수렴. 이로써 **T-DA-15(3 flat list 통일) 완료**.

- **list**: `{count,items,next_cursor}` → `data.{items,next_cursor}` +
  `meta.{count,duration_ms}`. **detail GET**: bare `PoiCacheTargetRecord` →
  기존 `PoiCacheTargetResponse{data, meta}` 재사용(put/delete와 동일 envelope).
- **frontend**: `poiCacheTargets.ts` `fetchPoiCacheTarget`/`usePoiCacheTarget`
  반환형 → `PoiCacheTargetResponse`, `poi-cache-targets-client.tsx` list accessor
  (`.meta.count`, `.data.items`, `.data.next_cursor`). `openapi.json`/`types.ts`
  재생성(admin-only → `openapi.user.json` 무변).
- **test**: openapi schema 검증 `PoiCacheTargetListResponse.properties == {data, meta}`
  + `PoiCacheTargetListData.next_cursor`로 갱신.
- **gate**: drift green, ruff/mypy --strict green, poi router+export_openapi pytest
  14 passed, frontend type-check/gen:types:check/eslint green.
- **문서**: contract §3.1 list 예외 비움(전부 완료), T-DA-15 ✅ 마킹.
- **다음**: T-DA-16 잔여 단건 bare(`/ops/metrics`·`/ops/dagster/summary`·
  `/debug/mois-license/{id}`·`/ops/import-jobs/{id}` meta) → T-DA-13 `/admin/issues`.

## 2026-06-06 (claude) — T-DA-15/16 envelope 통일 ② offline-uploads

**작업**: DA-D-03 두 번째 family로 `/admin/offline-uploads` list/detail 응답을
`{data, meta}` envelope로 수렴(write/preview/validation/load는 이미 enveloped).

- **list**: `{count,items,next_cursor}` → `data.{items,next_cursor}` +
  `meta.{count,duration_ms}`. **detail GET**: bare `OfflineUploadRecord` →
  `OfflineUploadDetailResponse{data, meta(duration_ms)}`.
- **frontend**: `offlineUploads.ts` hook 반환형/accessor(`.data.items`,
  `.data.state`), `offline-uploads-client.tsx`(`selectedUpload.data?.data`,
  `.meta.count`, `.data.items`). `openapi.json`/`types.ts` 재생성(offline-uploads는
  admin-only라 `openapi.user.json` 무변).
- **gate**: drift green, ruff/mypy --strict green, offline router+export_openapi
  pytest 23 passed, frontend type-check/gen:types:check/eslint green.
- **문서**: contract §3.1 예외에서 offline-uploads 제거, tasks.md family 체크.
- **다음**: 잔여 family `/admin/poi-cache-targets`(list+detail) → 단건 bare
  (`/ops/metrics`·`/ops/dagster/summary`·`/debug/mois-license/{id}`·
  `/ops/import-jobs/{id}` meta) → T-DA-13 `/admin/issues`.

## 2026-06-06 (claude) — T-DA-15/16 envelope 통일 ① feature-update-requests

**작업**: DA-D-03 전면 통일의 첫 family로 `/admin/feature-update-requests`와
`/tripmate/feature-update-requests` 응답 셰입을 `{data, meta}` envelope로 수렴.

- **list**: `{count, items, next_cursor}` flat → `data.{items,next_cursor}` +
  `meta.{count,duration_ms}` (기존 enveloped 라우터 admin-features/ops-import-jobs와
  동일 패턴). detail GET 2종(admin/tripmate): bare `FeatureUpdateRequestRecord` →
  `FeatureUpdateRequestDetailResponse{data, meta}`.
- **frontend**: `updateRequests.ts` hook 반환형/accessor(`.data.items`,
  `.data.state`), `feature-update-requests-client.tsx`(`.meta.count`,
  `.data.items`) 갱신. `openapi.json`/`openapi.user.json`/`types.ts` 재생성.
- **gate**: drift `--profile all --check` green, ruff/mypy --strict green, admin
  router+export_openapi pytest 16 passed, frontend `type-check`/`gen:types:check`/
  eslint green.
- **문서**: contract §3.1 현행 예외 목록에서 feature-update-requests 제거, tasks.md
  T-DA-15/16 family 진행 체크.
- **다음**: 잔여 family `/admin/offline-uploads`, `/admin/poi-cache-targets`, 이후
  단건 bare(`/ops/metrics`·`/ops/dagster/summary`·`/debug/mois-license/{id}`·
  `/ops/import-jobs/{id}` meta 추가) 통일 → T-DA-13 `/admin/issues`.

## 2026-06-06 (codex) — T-212a 전체점검 inventory + e2e gap matrix

**작업**: ADR-045 전체점검(T-212) 진입을 위해 최신 main 기준 API/UI/Dagster/DB/e2e
표면을 inventory로 재분류한다.

- **Report**: `docs/reports/t-212a-inventory-gap-matrix-2026-06-06.md`를 추가했다.
- **Inventory**: admin OpenAPI 43 path, user OpenAPI 13 path, frontend route 10개,
  Dagster assets/jobs/sensors/schedules/resources, PostGIS/성능 검증 표면을 정리했다.
- **Gap matrix**: `/admin/features`, `/admin/issues`, backup/restore admin UI,
  weather card UI, admin envelope/error/log contract, EXPLAIN/React Doctor baseline,
  full reload 실데이터 검증을 T-209e-c/T-212b~e 후속으로 분리했다.
- **다음**: T-209e-c admin backup/restore router + hot-swap UI 또는 T-212b admin UI
  완결성 보강.

## 2026-06-06 (codex) — T-RV-38/39 consistency count semantics

**작업**: PR#181~#233 리뷰 후속 중 consistency 관측 metrics의 count 의미를 정리한다.

- **F4**: dedup backlog WARN은 임계 초과 이벤트로 `count=1`만 기록하고, 실제 pending
  수와 threshold는 `metadata.pending_count`/`metadata.threshold` 및
  `summary.case_metadata.F4`에 분리했다.
- **F8**: `feature_files` row 하나가 active feature 누락과 object snapshot 누락을
  동시에 만족해도 distinct metadata row 1건으로만 count한다. 유형별 `sample_ids`는
  유지하고 metadata breakdown을 추가했다.
- **문서**: `docs/tasks.md`와 `docs/reports/pr-181-233-review-2026-06-06.md`에서
  T-RV-38/39를 완료 표시하고, 남은 T-RV-40/41의 추적 위치를 유지했다.
- **검증**: `TMPDIR=/tmp .venv/bin/python -m pytest tests/unit/test_infra_consistency.py tests/integration/test_consistency_reports.py tests/unit/test_cli_consistency_report.py packages/kor-travel-map-dagster/tests/test_maintenance.py -q`,
  `ruff check .`, `mypy --strict`, `lint-imports` 통과.
- **다음**: T-RV 잔여는 `T-RV-40`(F6 perf → T-212d), `T-RV-41`(MV CONCURRENTLY 전제
  → T-101), `T-RV-04b`다.

## 2026-06-06 (codex) — mcp-telegram 작업 완료 알림 셋업

**작업**: 단위 작업이 완료될 때마다 Telegram으로 짧은 요약과 PR 링크를 보낼 수
있도록 `mcp-telegram` MCP 설정과 문서를 추가한다.

- **MCP 설정**: `.codex/config.toml`, `claude.json`, `antigravity.json`,
  `.gemini/mcp.json`에 `mcp-telegram` 서버를 추가했다.
- **Secret handling**: Telegram credential은 tracked 설정/문서에 쓰지 않고,
  각 worktree 루트의 로컬 `.env.mcp-telegram`에만 둔다.
- **Wrapper**: `scripts/mcp_telegram_start.py`가 `.env.mcp-telegram`을 읽은 뒤
  `mcp-telegram start` 또는 `login` 같은 하위 명령을 실행한다.
- **문서**: `AGENTS.md`, `SKILL.md`, `docs/codegraph-worktree.md`,
  `docs/runbooks/agent-workflow.md`, `docs/resume.md`에 완료 알림 원칙과 셋업을
  명시했다.

## 2026-06-06 (codex) — T-209e-b staging cold restore 자동화

**작업**: T-209e backup/restore 독립 DB 묶음에서 cold backup 산출물을 비파괴 staging
대상으로 복원하는 자동화 경로를 추가한다.

- **Restore script**: `npm run docker:restore -- <backup_id>`가
  `scripts/docker-restore.sh`를 실행해 app DB는 `kor_travel_map_restore`, Dagster metadata
  DB는 `kor_travel_map_dagster_restore`, RustFS archive는 `kor-travel-map-rustfs-restore`
  Docker volume에 복원한다.
- **Safety**: 운영 DB 이름(`kor_travel_map`, `kor_travel_map_dagster`)으로 직접 restore하면 즉시
  실패한다. 기존 staging 대상 재생성도 `KOR_TRAVEL_MAP_RESTORE_RECREATE=1` opt-in을 요구한다.
- **Verification**: restore 전 `meta/SHA256SUMS`를 검증하고, static unit test로 script
  contract와 runbook 문구를 고정한다.
- **다음**: T-209e-c admin backup/restore router + hot-swap UI 또는 T-212 전체점검.

## 2026-06-06 (claude) — T-213e weather card (T-213 완료 7/7)

**작업**: T-213 묶음 마지막. weather value 적재/조회 + weather card 전체 스택.

- **migration** alembic `0017_feature_weather_values`: `feature.feature_weather_values`
  (PK 결정적 `weather_value_key`=ADR-010 identity, feature FK CASCADE, card 복합 인덱스
  `(feature_id, forecast_style, metric_key, valid_at DESC)` + `valid_at` BRIN=ADR-013).
- **repo** `infra/weather_repo.py`: `load_weather_values`(멱등 upsert),
  `build_weather_card(feature_id, asof, freshness_seconds)` — (forecast_style,
  metric_key)별 `COALESCE(valid_at,observed_at,issued_at)` 최신 DISTINCT ON + asof 필터
  + `source_styles` source trace + `is_stale`(기본 6h).
- **endpoint** `GET /features/{feature_id}/weather`(user spec) + **client**
  `build_weather_card`/`load_weather_values`.
- 검증: PostGIS 통합 2(load/card/asof/freshness/idempotent + empty), alembic upgrade
  0017 체인, router unit 2(Decimal→float). 격리 sandbox에서 OpenAPI drift/frontend
  types/ruff/mypy/lint-imports green.
- **T-213a~h 전부 완료** — TripMate 요구사항 후속 묶음 종료.

## 2026-06-06 (claude) — T-213c bbox clustering (server region rollup)

**작업**: T-213 묶음 여섯 번째. `/features/in-bounds` 서버 클러스터링.

- **설계 결정**: client-side·grid bucket 대신 **행정구역 rollup**. feature에 이미
  있는 `sido_code`/`sigungu_code`/`legal_dong_code`를 GROUP BY → geometry 계산 없이
  region별 count + 평균 좌표(대표 마커). 한국 행정구역 수가 bounded라 row 폭주 없음.
- **repo** `cluster_features_in_bbox(bbox, cluster_unit, kinds, categories, limit)`:
  cluster_unit allowlist→고정 코드 컬럼(injection 불가), bbox는 stored `coord` GIST
  `&&`(ADR-012, 술어 변환 없음), `avg(ST_X/ST_Y)` 대표 좌표.
- **endpoint**: `/features/in-bounds`에 `cluster_unit`(sido|sigungu|eupmyeondong) 쿼리.
  미지정 시 `zoom`으로 유도(≤7 sido/≤10 sigungu/≤13 eupmyeondong/≥14 개별). 응답에
  `clusters[]` 추가(`cluster_unit` None이면 `items`, 아니면 `clusters`+`items=[]`).
- 테스트: router unit 4(cluster/zoom 유도/고줌 개별/invalid 422), PostGIS rollup 2.
  OpenAPI drift/frontend types/ruff/mypy/lint-imports green. 다음: **T-213e**(weather
  card — T-213 마지막).

## 2026-06-06 (codex) — T-201b Phase 2 dry-run report CLI

**작업**: ADR-033 Phase 2(F1~F8 + Dagster gate)를 운영 enable 전에 dry-run으로
검증하고 첨부할 수 있는 report 경로를 추가한다.

- **CLI**: `ktmctl consistency-report`를 추가했다. 기본은 `persist=false` dry-run이며,
  Markdown/JSON 출력, `--persist`, `--fail-on-error`, F4/F5/F7 threshold override를
  지원한다.
- **F8 snapshot**: `--known-file-objects` JSON/JSONL로 RustFS/S3 object snapshot을 받아
  `feature_files` metadata와 양방향 비교한다.
- **Client**: `AsyncKorTravelMapClient.run_consistency_report()`가 F5/F7/F8 옵션을 전달한다.
- **Report**: `docs/reports/t-201b-phase2-dry-run-report-2026-06-06.md`를 첨부한다.
- **다음**: T-213 계열은 별도 에이전트가 진행 중이므로 비 T-RV 후보는 T-209
  Docker/daemon polish.

## 2026-06-06 (codex) — T-RV-34/35 Dagster sensor/asset 실행 품질

**작업**: PR#153~#179 리뷰 후속 중 Dagster sensor drain/failure hardening과
feature-load/maintenance retry·chunk 적재를 닫는다.

- **Sensor drain**: `feature_update_request_queue_sensor`가 dead cursor를 갱신하지 않고,
  queued request를 batch peek해 tick 1회에 최대 10개 worker run을 요청한다.
- **Failure hardening**: failure sensor는 request 실패 상태 반영이나 notifier 호출이
  실패해도 sensor 자체를 실패시키지 않고 로그를 남긴 뒤 원래 실패 메시지를 반환한다.
- **MOIS bulk**: MOIS record resource는 batch 단위로 FeatureBundle 변환/DB load를 수행해
  대용량 record를 한 번에 materialize하지 않는다.
- **RetryPolicy**: 모든 feature-load asset과 consistency/dedup maintenance op에 exponential
  retry policy를 추가했다.
- **검증**: Dagster unit 19 passed, feature update/client/Dagster ETL integration 16 passed,
  `ruff`, `mypy --strict`, `lint-imports` 통과.
- **다음**: T-RV 잔여는 `T-RV-04b`, 새 백로그 `T-RV-38~41`, T-RV-37 잔여 hygiene이다.
  `T-RV-27`은 production hardening 전까지 deferred 유지.

## 2026-06-06 (claude) — T-213g provider export + `/providers/{provider}/last-sync`

**작업**: T-213 묶음 다섯 번째. provider 데이터 신선도 표면 + client/provider helper.

- **repo**: `sync_state_repo.list_sync_states(provider, dataset_key=None,
  sync_scope=None)` 추가(기존 `get_sync_state`는 단건).
- **endpoint** `GET /providers/{provider}/last-sync`(`routers/providers.py`, 신규):
  `items[]`(dataset_key/sync_scope/status/last_success_at/last_failure_at/
  consecutive_failures) + count. **내부 cursor는 비노출**(provider 증분 상태).
  provider/dataset/scope 필터, 매칭 0건이면 **404**. features gate 하 mount, user spec 포함.
- **client**: `get_sync_state`/`list_sync_states`(read) + `record_sync_success`/
  `record_sync_failure`(write, session.begin()) helper 4종.
- **provider re-export**: `kortravelmap.providers`에 knps(point/geometry 변환, dataset,
  PROVIDER_NAME)/krheritage(items/events 변환, classify/resolve, dataset, PROVIDER_NAME,
  MARKER_COLOR) 추가.
- 테스트: providers router 3(spec/404/200 cursor-exclude), providers export 1,
  PostGIS list 통합 1, client unit. OpenAPI drift/frontend types/ruff/mypy/lint-imports
  green. 다음: **T-213c**(bbox clustering — 마지막 전, 설계 결정 동반).

## 2026-06-06 (claude) — T-213h public `GET /health` / `GET /version`

**작업**: T-213 묶음 네 번째. TripMate liveness/version 표면을 루트 경로에 추가.

- `routers/public_status.py`(신규): `GET /health`(liveness — 의존 없는 정적 200,
  `{data:{status:"ok",service:"kor-travel-map"},meta}`) + `GET /version`
  (`{data:{version(admin), kor_travel_map_version(lib), openapi_version, commit},meta}`,
  commit=env `KOR_TRAVEL_MAP_GIT_COMMIT`).
- **항상 mount**(features gate 무관) — liveness probe가 DB 없는 부팅·DB 장애에도
  동작해야 하므로. DB/RustFS/Dagster **deep readiness**는 후속(`/ops/health-deep`)로
  분리(liveness를 DB-free로 유지). 기존 `/debug/health`·`/debug/version`은 그대로.
- user OpenAPI subset(`/health`,`/version`) + `openapi.*.json`/frontend `types.ts`
  재생성. router unit 5(spec presence/liveness/version/env commit/feature-off mount).
- 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports green.
  다음: **T-213g**(provider export + last-sync).

## 2026-06-06 (claude) — T-213f `GET /categories` 카탈로그 표면

**작업**: T-213 묶음 세 번째. `kortravelmap.category` 144건 정적 카탈로그를 HTTP로 노출.

- **endpoint** `GET /categories`(`routers/categories.py`, 신규) — code/depth/tier
  1~4/label/path/parent/sort_order/is_active/maki_icon. `include_counts`/`active_only`
  면 repo `category_feature_counts`(GROUP BY count)로 `db_feature_count`/`db_active`
  합침. 정적 카탈로그는 모듈 로드 시 1회 구성(ADR-030). `features_routes_enabled`
  gate, user OpenAPI subset(`USER_OPERATIONS`)에 추가 + `openapi.*.json`/frontend
  `types.ts` 재생성.
- **drift gate**: `@kor-travel-map/map-marker-react`의 `maki.ts`가 **name→glyph**(category→maki
  아님)라 ADR-029 원안의 category↔TS 1:1 게이트가 그대로 안 맞음 → 완화형으로 적용:
  (1) Python 카탈로그 self-consistency(maki∈values, 144), (2) TS maki name kebab 유효성,
  (3) 핵심 provider maki(fuel/restaurant/cafe/park/monument/shelter/star/marker)
  글리프 커버. (`tests/unit/test_category_catalog_contract.py`)
- **doc reconcile**: 코드 실측으로 `category/__init__.py` docstring tier 개수
  (Tier2 30→**34**, Tier4 33→**29**)와 `category.md` icon 개수(55→**57**)를 정정.
- **테스트**: admin router 3(spec/static 144/counts merge), main contract 3, PostGIS
  counts 통합 1. 격리 sandbox에서 OpenAPI drift/frontend types/ruff/mypy/lint-imports
  green. 다음: **T-213h**(public health/version).

## 2026-06-06 (claude) — T-213b 좌표 기준 `/features/nearby` 구현

**작업**: T-213 묶음 두 번째. 사용자 현재 위치/추천용 좌표 기준 주변 feature 조회를
repo→client→endpoint→OpenAPI까지 추가했다(T-213d read parity 위에).

- **repo**: `features_nearby(lon, lat, radius_m, kinds, categories, statuses,
  providers, sort, limit, cursor)` + `_NEARBY_COORD_CTE_SQL`. ADR-012: 입력 좌표를
  `origin` CTE에서 **1회만** 5179 변환(`ST_Transform(ST_SetSRID(ST_MakePoint))`)하고
  술어는 STORED `coord_5179`에 `ST_DWithin`. candidates 컬럼/cursor/정렬은 by-target
  nearby와 동일 → `_nearby_row`/`_nearby_cursor_params`/`_encode_nearby_cursor`/
  `NearbyFeaturePage` 재사용(additive, 기존 target SQL 무수정).
- **client**: `AsyncKorTravelMapClient.features_nearby` 위임.
- **endpoint**: `GET /features/nearby` — public `NearbyFeatureSummary`(내부 필드 누출
  없음, T-RV-08 정합) + `origin` echo. `radius_m`≤100km, lon/lat 범위, sort enum 검증.
  user OpenAPI subset에 추가(`USER_OPERATIONS`), `openapi.json`/`openapi.user.json` 재생성.
- **테스트**: PostGIS 통합 4건(필터/거리·cursor 페이징·invalid·EXPLAIN ADR-012 stored
  coord_5179 술어/ per-row transform 부재) + admin router unit(422 검증 + spec presence)
  + client unit + export user-paths 갱신. 격리 WSL sandbox에서 OpenAPI drift green,
  ruff/mypy/lint-imports green, 통합 4 passed(Docker).
- **메모**: 소량 데이터에서 planner가 GiST 대신 seqscan을 골라 인덱스 *이름* 단언은
  fragile → ADR-012 본질(술어 대상=stored 5179, 입력만 1회 변환)로 검증. 다음: **T-213f**.

## 2026-06-06 (claude) — T-213d AsyncKorTravelMapClient read parity (TripMate 후속 선행)

**작업**: 사용자 지시로 T-213 묶음을 하나씩 진행. **선행/prereq인 T-213d**부터 처리.
`AsyncKorTravelMapClient`에 read 메서드 3개를 추가해 admin 라우터/repo가 쓰던 read path를
client 표면으로도 노출했다(API/Dagster 내부·테스트가 같은 path 재사용).

- `get_features(feature_ids)` → `infra.feature_repo.get_feature_rows_by_ids`
  (soft-deleted 제외, TripMate batch 계약).
- `search_features(q|bbox, kinds, categories, limit, cursor)` → repo `search_features`
  (`FeatureSearchPage`).
- `features_nearby_poi_cache_target(target_id, radius_km, …, sort, cursor)` → repo
  동명 함수(`NearbyFeaturePage`, ADR-012 STORED `coord_5179` 술어).
- **위임만**이라 새 SQL/스키마/endpoint 없음. 의존 방향(client → infra) 정상.
- 테스트: DB 미접근 unit 3건(repo/세션 monkeypatch로 pass-through 검증). 격리 WSL
  sandbox(`~/dev/kor-travel-map-claude`, codex 공유 sandbox와 분리)에서
  ruff/pytest(5 passed)/mypy/lint-imports green.
- 좌표 기준 `/features/nearby`(T-213b), weather card(T-213e), provider last-sync
  (T-213g)가 이 client 표면을 재사용한다. 다음: **T-213b**.

## 2026-06-06 (codex) — T-209b-a Dagster Postgres instance storage 고정

**작업**: Dagster schedule/run/event storage가 `$DAGSTER_HOME` SQLite로 폴백하지 않도록
Docker와 로컬 admin-stack의 instance config를 같은 PostgreSQL 기준으로 고정했다.

- **Shared config**: `docker/dagster.yaml`의 unified `storage.postgres` 설정을
  `KOR_TRAVEL_MAP_DAGSTER_PG_URL` 기준으로 유지하고, 로컬 `run-admin-stack.sh`도 같은 파일을
  `$DAGSTER_HOME/dagster.yaml`로 설치하게 했다.
- **Local DB init**: `run-admin-stack.sh`가 시작 전 `kor_travel_map_dagster` DB 존재를
  확인하고 없으면 생성한다.
- **Daemon split**: 로컬 stack도 `dagster dev` 대신 `dagster-webserver`와
  `dagster-daemon`을 분리 실행하고, daemon pid 생존 여부를 readiness 뒤 확인한다.
- **Docs/tests**: Docker runbook, Dagster boundary, Dagster package README를 갱신하고
  `tests/unit/test_docker_dagster_runtime.py`에 local admin-stack 회귀 테스트를 추가했다.
- **다음**: T-201b Phase 2 dry-run report 또는 T-209 Docker/daemon polish.

## 2026-06-06 (codex) — T-RV-31/32/33 router/executor 정확성

**작업**: PR#153~#179 리뷰 후속 중 runner savepoint와 router DTO 정확성을 닫는다.

- **Executor savepoint**: provider runner 1회 실행을 `session.begin_nested()`로 감싸,
  runner가 일부 DB write 뒤 실패해도 해당 write는 rollback되고 request/job/target 실패
  메타데이터만 바깥 트랜잭션에서 기록되게 했다.
- **Regression**: PostGIS 통합 테스트에서 runner가 feature/source record를 적재한 뒤
  예외를 던지는 경로를 검증하고, 적재 feature가 남지 않는지 확인했다.
- **Admin issue schema**: `AdminFeatureIssueRecord`를 `extra="forbid"`로 전환해 OpenAPI
  `additionalProperties=false`와 frontend generated type index signature 제거를 반영했다.
- **Nearby 좌표 계약**: `/features/nearby/by-target`은 repo SQL의 `f.coord IS NOT NULL` +
  `f.coord_5179 IS NOT NULL` 필터로 `lon/lat` 필수 public DTO 계약을 유지한다. 해당 SQL
  보장을 단위 테스트로 고정했다.
- **다음**: 남은 T-RV 실행 품질 묶음은 `T-RV-34/35`다. `T-RV-27`은 production
  hardening 전까지 deferred 유지.

## 2026-06-06 (claude) — PR #181~#233 코드 리뷰 (비-T-RV 실질 PR)

**작업**: 직전 리뷰(`pr-153-179-review-2026-06-04.md`) 이후 머지 PR을 상세 리뷰.
사용자 지시대로 **Claude Code 리뷰 backlog 구현 PR(`fix/t-rv-*`)과 본인 문서 감사
PR(#227/#230, T-DA)은 리뷰 생략**. 정본: `docs/reports/pr-181-233-review-2026-06-06.md`.

- **대상**: #181 T-208i / #182 T-205d / #183 T-209b / #184 T-200 batch gate /
  #213 T-202 / #215 T-203 / #216 F6 / #218 F5 / #219 F7 / #231 F8 + 문서 PR.
- **결과**: 신규 지적 **전부 LOW**(관측 전용 WARN 케이스 count 의미/성능). HIGH/MED
  결함 없음. 검토 중 세운 risk 2개(F5 join fan-out, F7 score 스케일)는 schema
  ground truth(`provider_refresh_policies` 복합 PK / `dedup_review_queue.total_score`
  `Numeric(5,2)` CHECK 0~100)로 **결함 아님** 확정. F6 `HHMM` 가정도 DTO와 일치.
- **신규 task**: `T-RV-38`(F8 double-count), `T-RV-39`(F4 count 혼입),
  `T-RV-40`(F6 4× 풀스캔 perf → T-212d), `T-RV-41`(MV CONCURRENTLY 전제 → T-101).
- 검증: 리뷰/문서만 추가(코드 무변경). 변경: docs/reports 신규 + docs/{tasks,journal}.md.

## 2026-06-06 (codex) — TripMate 요구사항 대조 task 반영

**작업**: TripMate `docs/kor-travel-map-requirements.md`를 현재 kor-travel-map `origin/main`
(`ae67a88`, PR#232 이후) 기준으로 재대조하고 후속 task를 등록했다.

- **리포트**: `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`를 추가해
  TripMate K-1~K-14를 이미 충족/부분 충족/신규 task로 재분류했다. TripMate 문서의
  기준선 `b775c74`는 ADR-045 OpenAPI 독립 프로그램화 이전 상태라 그대로 백로그화하지
  않았다.
- **Tasks**: `docs/tasks.md`에 `T-213a~h`를 추가했다. 일반 좌표 기준
  `/features/nearby`, bbox clustering, client read parity, weather card, category
  catalog, provider export/sync state/last-sync, public health/version을 후속으로 분리했다.
- **Contract 정리**: `docs/tripmate-rest-api.md`와 `docs/tripmate-integration.md`에서
  현재 user OpenAPI 7개 path와 아직 미구현인 last-sync/health/weather/category/nearby
  일반 좌표 표면을 task ID와 함께 명시했다. #232의
  `/tripmate/feature-update-requests*` 공개 경로 분리도 반영했다.
- **원칙**: 최신 사용자 지시대로 호환성/최소 수정이 아니라 완성도, 안정성, 확장성,
  성능을 우선하는 기준을 T-213 설명에 반영했다.
- **다음**: 기존 순서대로 `T-209b-a` Dagster schedule/run/event storage PostgreSQL
  강제 전환 구현을 진행한다.

## 2026-06-06 (codex) — T-RV-29/30 user OpenAPI + generated frontend types

**작업**: PR#153~#179 리뷰 후속 중 공개 OpenAPI/admin frontend 계약 drift를 닫는다.

- **User OpenAPI**: TripMate/user spec에서 `/admin/feature-update-requests*`를 제거하고
  `/tripmate/feature-update-requests*` 전용 경로를 추가했다. admin UI 경로는 admin spec에
  그대로 유지한다.
- **Drift guard**: `USER_OPERATIONS` 경로/메서드가 full OpenAPI에 없으면 user profile
  생성이 실패하도록 하고, export unit test로 고정했다.
- **Frontend types**: `openapi-typescript` 생성물 `src/api/types.ts`를 커밋하고
  `src/api/*` DTO를 `paths`/`components` 파생 타입으로 전환했다. frontend CI에
  `npm run gen:types:check`를 추가했다.
- **UI safety**: generated 타입의 optional nullable 표현에 맞춰 Dagster run timestamp,
  Dagster errors, dedup distance, feature 좌표 렌더링을 안전하게 처리한다.
- **React Doctor**: optional warning 7건은 기존 shadcn/ui primitive export 구조와
  Dagster iframe sandbox false positive 성격으로 확인했다.

## 2026-06-06 (codex) — T-201b-d F8 file object orphan 정합성 검사

**작업**: ADR-033 Phase 2의 마지막 케이스인 `F8` file object orphan WARN을
`run_consistency_checks()`에 추가한다.

- **Integrity**: `feature.feature_files` metadata와 객체 저장소 snapshot
  (`known_file_objects`)을 비교해 metadata-only/object-only/삭제 feature 연결을
  WARN으로 보고한다.
- **호환 경계**: 현재 Alembic head에는 `feature.feature_files` 테이블이 아직 없으므로
  테이블 부재 시 기존 호출은 OK로 유지한다. 객체 snapshot이 주입되면 object-only
  orphan은 `object_missing_metadata`로 보고한다.
- **테스트**: F8 비교 helper와 table-missing 경계를 unit test로 고정하고, PostGIS
  integration에서 임시 `feature.feature_files` metadata와 snapshot mismatch 3종을
  검증했다.
- **검증**: `TMPDIR=/tmp pytest -s tests/unit/test_infra_consistency.py -q` 14 passed,
  `TMPDIR=/tmp pytest -s tests/integration/test_consistency_reports.py -q` 12 passed.
- **Runbook**: Windows Git rebase/merge continue가 Vim을 열고 멈추는 패턴을
  `docs/runbooks/agent-failure-patterns.md` B4와 `agent-workflow.md`에 추가했다.
  앞으로 continue류 명령은 `git.exe -c core.editor=true ... --continue`를 표준으로 쓴다.
- **다음**: 사용자 지시에 따라 `T-209b-a`를 바로 진행한다. T-201b Phase 2에서 남은
  범위는 dry-run report다.

## 2026-06-06 (claude) — 문서 정합성 후속: README 상태 블록 포인터화 (T-DA 마감)

**작업**: PR#227(T-DA 감사) 후속. 1차 감사에서 누락했던 `README.md`도 entry doc
이므로 DA-D-01(A)를 동일 적용한다.

- README 상단 "현재 상태 (… PR#156 이후 기준)" 블록이 PR#155/#156 번호 + "Sprint 4
  완료 / Sprint 5 진행 중" narrative를 박고 있었다(반복 drift 클래스). → 잘 바뀌지
  않는 기준값(고정 포트/ADR 현황/frontend/운영 모델)만 남기고, 진척 정본은
  `docs/resume.md`+`docs/tasks.md`를 가리키는 포인터로 대체.
- "## 빠른 시작 (Sprint 4 완료 — …)" 헤더의 sprint 스냅샷도 제거.
- 이로써 entry doc 4종(CLAUDE/AGENTS/SKILL/README) 상태 블록 drift 정리 완료.
- 검증: 문서만 수정(코드 무변경). 변경 파일: README.md, docs/{tasks,journal}.md.
## 2026-06-06 (codex) — T-209b-a Dagster schedule storage PostgreSQL 전환 task 등록

**작업**: Dagster가 `.dagster/schedules/schedules.db-*` SQLite 파일을 내부 schedule
storage로 쓰는 경로를 PostgreSQL로 전환하는 즉시 실행 task를 추가한다.

- **Task**: `docs/tasks.md`에 `T-209b-a`를 추가했다. 기존 `T-209b`의 후속 범위를
  쪼개 Docker standalone과 로컬 admin-stack의 Dagster instance storage를
  `kor_travel_map_dagster` PostgreSQL로 강제 전환하는 작업으로 정의했다.
- **범위**: `schedule_storage`, `run_storage`, `event_log_storage` 모두
  `dagster_postgres`/`KOR_TRAVEL_MAP_DAGSTER_PG_URL` 기반으로 맞추고, webserver와 daemon이
  같은 config/DB를 공유해야 한다.
- **DoD**: schedule state toggle의 PostgreSQL 지속성, `dagster instance info` 또는
  동등 smoke, `$DAGSTER_HOME/.dagster/schedules/schedules.db-*` 미생성 확인,
  compose/runbook 회귀 테스트.
- **다음**: 즉시 `T-209b-a` 구현. T-201b-d F8과 T-RV-29/30은 그 뒤로 미룬다.

## 2026-06-06 (claude) — 문서 전수 정합성 감사 + drift 수정 (T-DA)

**작업**: 사용자 지시로 `origin/main`(PR#225) 기준 문서 전체를 읽고 논리적
불일치·Task 문서 불일치·stale·빠진 부분을 감사. 결과를
`docs/reports/docs-consistency-audit-2026-06-06.md`(T-DA-01~11, DA-D-01/02)로 정리하고
무쟁점 항목을 같은 PR에서 수정.

- **감사 방식**: 문서 주장(claim)을 코드 ground truth(`.env.example`,
  `docker-compose.yml`, `alembic/versions/*`=0001~0016, `src/kortravelmap/category`)와
  대조. 예: category 개수는 `len(PLACE_CATEGORY_DEFINITIONS)=144`로 실측.
- **의사결정**: DA-D-01 = "현 단계/현 위치" 상태 블록을 `resume.md`/`tasks.md`
  포인터로 대체(반복 drift 원인 제거). DA-D-02 = 무쟁점 수정까지 한 PR로 반영.
- **수정(반영 완료)**: CLAUDE.md §2 전면 갱신(8888→12201, ADR 001~047/다음 048,
  PR#149 narrative 제거 → 포인터) / AGENTS.md "코드 작성 단계"(PR#156) 포인터화 /
  sprints/README "현 위치"(PR#149) 포인터화 + Sprint5 "🟢 진행 중" /
  category.md·debug-ui-package.md·decisions.md ADR-030 개수 라벨 141→**144** /
  architecture.md 큰그림 의존체인에 `category` 추가 / decisions.md ADR-002·025·036에
  현행 기준 교차참조 note(역사 본문 보존).
- **외부 노출 API 점검(사용자 요청, §8)**: 생성 spec `openapi.json`(35 path)/
  `openapi.user.json`(7 path) ↔ contract 대조. 발견: ① `/admin/issues`(ADR-046 주소
  이슈 수동 처리 write/action)가 contract §4.1 "필수 엔드포인트"로 명세됐으나 미구현
  (읽기 `/ops/consistency/issues`만)=T-DA-13. ② `/admin/providers` 미구현(T-207b
  취소)인데 §4 표에 캐비엇 없음=T-DA-14. ③ list 응답 셰입 이원화 `{data,meta}`(7) vs
  `{count,items,next_cursor}`(3)=T-DA-15, 단건 envelope 불일치(user subset
  feature-update-requests/{id}만 bare)=T-DA-16.
- **추가 의사결정**: DA-D-03 = **전면 통일**(모든 admin 응답 `{data,meta}`) — 본 PR은
  contract §3.1에 표준+현행예외 명시(문서), 코드 전환은 별도 PR(T-DA-15/16).
  DA-D-04 = **T-212 묶음** — `/admin/issues`는 contract §4·§4.1 "미구현(계획)" 배지만
  반영, 구현은 T-212b/c.
- **검증**: 본 배치는 문서/주석만 수정(코드·스키마 무변경). 변경 파일:
  CLAUDE.md, AGENTS.md, SKILL.md, docs/{tasks,journal,resume,category,architecture,
  decisions,debug-ui-package,openapi-admin-contract,sprints/README}.md + 신규 리포트.

## 2026-06-06 (codex) — T-RV-23 후속 offline upload ORM unique constraint 동기화

**작업**: PR#225에서 추가한 `ops.offline_uploads` checksum idempotency migration과
SQLAlchemy ORM 모델 정의를 맞춘다.

- **ORM sync**: `OfflineUploadRow`에
  `uq_offline_uploads_provider_dataset_scope_checksum` unique constraint를 추가해
  migration과 모델 metadata의 drift를 제거했다.
- **Regression**: ORM metadata가 해당 unique constraint 이름과 컬럼 순서를 유지하는지
  단위 테스트로 고정했다.
- **범위 제한**: DB migration, API behavior, OpenAPI schema는 PR#225 범위 그대로
  유지한다. 이번 변경은 ORM mapping 보완만 포함한다.

## 2026-06-06 (codex) — T-RV-23 offline upload idempotency/load TOCTOU

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 offline upload checksum idempotency와
load 중복 실행 TOCTOU를 닫는다.

- **Checksum idempotency**: upload body 기준 SHA-256을 DB metadata에 저장하고,
  `provider/dataset_key/sync_scope/checksum_sha256` unique constraint를 추가했다.
  중복 생성 시 방금 쓴 object는 보상 삭제하고 `OFFLINE_UPLOAD_DUPLICATE` 409 envelope로
  기존 upload metadata를 반환한다.
- **Load preclaim**: `/load`는 Dagster launch 전에 `ops.import_jobs`를 생성하고
  `offline_uploads.state='loading'`, `load_job_id=<job_id>`를 같은 트랜잭션에서
  선점한다. launch 실패 시 job/upload 상태를 각각 `failed`/`load_failed`로 닫는다.
- **Dagster semantics**: `offline_upload_load` op는 advisory lock busy를 성공 no-op로
  처리하지 않고 `Failure`로 기록한다. 이미 preclaimed된 `loading + load_job_id` row는
  기존 job을 재사용한다.
- **테스트**: offline upload router/Dagster/core/PostGIS 묶음 `42 passed`, `ruff check`,
  `mypy --strict`, `lint-imports`, OpenAPI all profile check를 수행했다.
- **남은 범위**: T-RV-27은 production hardening 전까지 skip/deferred다. 다음 후보는
  T-201b-d F8 또는 T-RV-29/30이다.

## 2026-06-05 (codex) — T-RV-25 offline upload store 재사용

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 offline upload store client 재사용 계약을
닫는다.

- **Store cache**: offline upload router는 `request.app.state.offline_upload_store`를
  우선 사용하고, 없을 때만
  `KorTravelMapSettings()`와 S3 client를 1회 생성해 `app.state`에 캐시한다.
- **Route coverage**: `create`, `preview`, `validate` 경로가 같은 cached store를
  사용한다. `load`는 Dagster launch만 수행하므로 store를 만들지 않는다.
- **Shutdown**: cached store가 boto3-like `s3_client.close()`를 제공하면 FastAPI
  lifespan 종료 시 닫는다.
- **Regression**: 같은 app에서 연속 upload 요청이 store builder를 1회만 호출하는지와
  shutdown close를 단위 테스트로 고정한다.
- **문서**: `docs/tasks.md`, PR#153~#179 리뷰 리포트, `docs/resume.md`에서 T-RV-25를
  완료 상태로 맞추고, 남은 offline upload 후속을 T-RV-23(checksum/idempotency + load
  TOCTOU)로 좁힌다.

## 2026-06-05 (codex) — T-RV-24 후속 offline upload ORM state check 동기화

**작업**: T-RV-24에서 만든 offline upload 상태 단일 계약을 ORM check constraint까지
확장한다.

- **ORM sync**: `OfflineUploadRow`의 `ck_offline_uploads_state`가
  `OFFLINE_UPLOAD_STATE_VALUES`를 참조하게 해 core 상태 tuple과 SQLAlchemy 모델의
  상태 목록 drift를 줄인다.
- **Test**: 상태 tuple 순서/집합과 ORM check constraint 포함 값을 단위 테스트로
  고정한다.
- **범위 제한**: DB migration은 추가하지 않는다. 현재 enum-like check 값은 기존
  migration과 동일하며, 이번 변경은 Python ORM 모델의 single-source 정렬이다.
- **남은 범위**: T-RV-23(checksum/idempotency + load TOCTOU)과 T-RV-25(store reuse)는
  아직 남아 있다.

## 2026-06-05 (codex) — T-RV-24 offline upload 상태 계약 단일화

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 offline upload state/format set drift를
줄인다.

- **State contract**: `kortravelmap.core.offline_upload_states`를 추가해
  `uploaded`/`validating`/`validated`/`validation_failed`/`loading`/`loaded`/
  `load_failed`/`cancelled` 전체 상태와 load/validation 전이 set을 한 곳에 둔다.
- **Layer sync**: admin router, `kortravelmap.offline_upload`, `infra.offline_upload_repo`가
  더 이상 각자 `LOADABLE_STATES`/tabular format set을 복붙하지 않는다.
- **Reserved state**: validation 상태는 이미 validate API/job producer가 있으므로 dead
  상태가 아니다. `cancelled`만 offline upload cancel API가 붙기 전까지 reserved terminal
  state로 문서화한다.
- **테스트**: 상태 집합 단위 테스트를 추가하고 offline upload unit/integration/router
  회귀 테스트로 기존 전이 동작을 확인한다.
- **남은 범위**: T-RV-23(checksum/idempotency + load TOCTOU)과 T-RV-25(store reuse)가
  offline upload 묶음의 다음 후보로 남아 있다.

## 2026-06-05 (codex) — T-RV-22 offline upload write rollback

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 offline upload object orphan 방지
경로를 분리한다.

- **Rollback**: `POST /admin/offline-uploads`에서 RustFS/S3 object write가 성공한 뒤
  `ops.offline_uploads` metadata insert가 실패하면 같은 요청에서 방금 쓴 object만
  보상 삭제한다.
- **D-14 경계**: 정상 등록된 offline upload 원본은 계속 무기한 보존한다. 이번 삭제는
  DB row가 만들어지지 않은 write-rollback 전용 예외이며 lifecycle cleanup/purge가 아니다.
- **Store API**: `S3ObjectStore.delete_object()`를 추가해 boto3 S3 호환
  `delete_object`를 async wrapper로 제공한다.
- **테스트**: fake S3 store 삭제 단위 테스트와 router metadata insert 실패 rollback
  테스트를 추가했다.
- **남은 범위**: T-RV offline upload 묶음 중 T-RV-23(idempotency/load TOCTOU),
  T-RV-24(state constant drift), T-RV-25(store reuse)가 남아 있다.

## 2026-06-05 (codex) — PR#153~#179 리뷰 리포트 상태 동기화

**작업**: `docs/reports/pr-153-179-review-2026-06-04.md`에서 실제 반영됐지만 표에
미반영으로 남은 항목을 2026-06-05 `origin/main` 기준으로 정리한다.

- **완료 표시**: T-RV-01/02/03, T-RV-05~21, T-RV-26, T-RV-28, T-RV-36,
  T-RV-37a~37e를 취소선+`✅ 반영` 상태로 맞췄다.
- **부분 완료 분리**: T-RV-04는 `T-RV-04a` guard resource/env mapping 완료와
  `T-RV-04b` provider public client live fetcher 잔여로 분리했다.
- **처리 순서**: 완료된 HIGH 항목을 권장 순서에서 제거하고, 남은 T-RV-04b,
  T-RV-23~25, T-RV-29~35, T-RV-37 잔여 hygiene 중심으로 재정렬했다.

## 2026-06-05 (codex) — T-201b-c F7 dedup score 회귀 정합성 검사

**작업**: ADR-033 Phase 2 중 cross-provider dedup score regression을 관측하는 `F7`
WARN 케이스를 분리한다.

- **Integrity**: `run_consistency_checks()`가 pending `dedup_review_queue` 후보 중
  양쪽 feature의 primary source provider가 서로 다른 pair만 검사한다.
- **Baseline**: 큐에 저장된 `total_score`를 baseline으로 삼고, 현재 feature의
  이름/좌표/카테고리를 `core.scoring.score_pair()`로 재계산한 점수가 baseline보다
  기본 10점 이상 낮아지면 WARN으로 보고한다.
- **Scope**: 같은 provider/sibling 후보와 이미 검토 완료된 행은 F7 대상에서 제외한다.
- **Test**: PostGIS integration에서 baseline 대비 현재 score 회귀, 같은 provider 제외,
  baseline delta OK 경계를 검증한다.
- **CI 보강**: F7 row 집계를 순수 helper로 분리하고 `run_consistency_checks()`의
  F1~F7 + persist 단위 경로를 추가 검증해 unit coverage gate를 안정화했다.
- **남은 범위**: T-201b 전체 완료까지 F8(file object orphan)과 dry-run report 보강이
  남아 있다.

## 2026-06-05 (codex) — T-201b-b F5 provider last_success SLA 정합성 검사

**작업**: ADR-033 Phase 2 중 provider sync cursor 지연을 관측하는 `F5` WARN 케이스를
분리한다.

- **Integrity**: `run_consistency_checks()`가 active `provider_sync_state`의
  `last_success_at`을 검사한다. 성공 기록이 없거나 SLA를 넘기면 severity=`WARN`으로
  보고한다.
- **Policy**: 기본 SLA는 24시간이고, `ops.provider_refresh_policies.system_interval_seconds`
  가 있으면 provider/dataset 정책값을 우선한다. `enabled=false` policy는 대상에서 제외한다.
- **Test**: PostGIS integration에서 기본 24시간 SLA 초과, provider policy interval 적용,
  disabled policy 제외를 검증한다.
- **남은 범위**: T-201b 전체 완료까지 F7(dedup score 회귀), F8(file object orphan),
  dry-run report 보강이 남아 있다.

## 2026-06-05 (codex) — T-RV-19 POI/cache target cursor/schema 안정화

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-19를 반영한다.

- **List cursor**: `list_poi_cache_targets`를 `updated_at DESC, target_id DESC`
  keyset page로 바꾸고, admin REST `GET /admin/poi-cache-targets`에 `cursor`와
  `next_cursor`를 추가했다.
- **Request schema**: `PUT /admin/poi-cache-targets/{external_system}/{target_key}`의
  `provider_overrides`와 `metadata`를 typed/상한 schema로 좁히고, Pydantic reserved
  field 충돌을 피하도록 내부 필드는 `metadata_`+alias로 다룬다.
- **Admin UI**: `/admin/poi-cache-targets` 목록 hook과 화면에 cursor 전달, 이전/다음
  pagination, 저장 후 첫 페이지 복귀를 반영했다.
- **테스트/문서**: repo cursor unit test, router validation/list cursor test,
  OpenAPI/POI target 계약 문서와 T-RV 리뷰 리포트를 갱신했다.

## 2026-06-05 (codex) — T-201b-a F6 opening_hours 정합성 검사

**작업**: ADR-033 Phase 2 중 DB 외부 의존이 없는 `F6` opening hours 모순 검사를 먼저
분리한다.

- **Integrity**: `run_consistency_checks()`의 정적 SQL 케이스에 `F6`를 추가했다.
  같은 요일 period에서 `open.time > close.time`이면 severity=`ERROR`로 보고한다.
- **허용 경계**: 다음 요일로 넘어가는 자정 통과 구간과 close가 없는 24/7 표현은 위반으로
  보지 않는다.
- **Test**: unit 케이스 목록과 PostGIS integration에서 F6 위반/정상 구간을 검증한다.
- **남은 범위**: T-201b 전체 완료까지 F5(provider SLA), F7(dedup score 회귀),
  F8(file object orphan)과 dry-run report 보강이 남아 있다.

## 2026-06-05 (codex) — T-203 PR CI workflow full matrix

**작업**: Sprint 5 운영 진입 gate 중 PR CI workflow를 required check 친화 구조로
분리한다.

- **CI**: `.github/workflows/ci.yml`에서 기존 `pytest (Python X)` matrix check 이름은
  유지하되 unit/lint/admin/dagster unit test만 실행하게 좁혔다.
- **CI**: PostGIS 통합 테스트는 `pytest integration (PostGIS)`, fixture replay는
  `pytest fixture replay` 별도 always-on job으로 분리했다.
- **CI**: `openapi-drift`와 frontend `type-check + next build (Node 20)` workflow의
  path filter를 제거해 모든 PR에서 check가 생성되도록 했다.
- **Docs/Test**: branch protection/runbook/task/sprint 문서를 T-203 이후 required check
  기준으로 갱신하고, workflow 구조 회귀 테스트를 추가했다.

## 2026-06-05 (codex) — T-204 branch protection 설정 가이드

**작업**: Sprint 5 운영 진입 gate 중 GitHub `main` branch protection 운영자 매뉴얼을
분리한다.

- **Runbook**: `docs/runbooks/branch-protection.md`를 추가해 PR 필수, approval 1개,
  branch up-to-date, force-push/delete 차단, squash merge 기준을 문서화한다.
- **Required checks**: 현재 always-on check(`lint`, Python 3.11/3.12/3.13 pytest)와
  path-filtered check(`openapi-drift`, frontend build)를 분리했다.
- **T-203 경계**: path-filtered check는 T-203에서 모든 PR에 neutral/success check가
  생성되도록 바꾼 뒤 branch protection required check로 승격한다고 명시한다.

## 2026-06-05 (codex) — T-202 pre-commit hook 정착

**작업**: Sprint 5 운영 진입 gate 중 pre-commit hook을 정착한다.

- **Journal gate**: `scripts/check_journal_update.py`가 staged `src/` 또는 `tests/`
  계열 변경을 감지하고 `docs/journal.md`가 함께 staged되지 않았으면 commit을 막는다.
  `BYPASS=1`은 의도적 1회 우회로만 허용한다.
- **Static gate**: `scripts/run-precommit-check.sh`가 `.venv` Python을 우선 사용해
  staged Python 파일 대상 `ruff format --check`, `mypy --strict`, `lint-imports`를
  실행한다. 전체 ruff format baseline 정리는 충돌 위험 때문에 별도 PR로 남긴다.
- **설정/문서**: `.pre-commit-config.yaml`과 개발환경 문서에 `pre-commit install`,
  `pre-commit run`, journal gate 우회 기준을 추가했다. hook 설치는 WSL `/mnt/f`가
  아니라 Windows Git/Git Bash 기준으로 한다.

## 2026-06-05 (codex) — T-RV-20 feature update request schema 검증

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-20을 반영한다.

- **Scope schema**: `POST /admin/feature-update-requests`의 `scope`를 `type`
  discriminator 기반 `feature_ids`, `center_radius`, `sigungu_by_radius`, `bbox`,
  `provider_dataset`, `cache_target_keys` union으로 검증한다.
- **Policy/list guard**: `update_policy`는 알려진 필드만 허용하고,
  `providers`/`dataset_keys`는 list 상한을 둔다.
- **Frontend 계약 정렬**: admin frontend 생성 payload가 legacy root `lon`/`lat`가 아니라
  `center: {lon, lat}` 형태의 `center_radius` scope를 보내도록 맞췄다.
- **OpenAPI/test**: admin/user OpenAPI 산출물을 재생성하고, legacy scope shape,
  unknown policy key, 과도한 provider filter list가 enqueue 전에 `422`로 거절되는지
  라우터 unit test로 고정했다.

## 2026-06-05 (codex) — T-209e-a standalone cold backup

**작업**: T-209e backup/restore 독립 DB 묶음 중 충돌 가능성이 낮은 cold backup
단위를 먼저 분리한다.

- **백업 스크립트**: `npm run docker:backup`이 `scripts/docker-backup.sh`를 실행해
  `kor_travel_map` app DB, `kor_travel_map_dagster` Dagster metadata DB, RustFS volume을
  `data/backups/<backup_id>/` 아래에 저장한다.
- **안전 경계**: API/frontend/Dagster/RustFS writer service가 실행 중이면 기본 중단하고,
  운영자가 `KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING=1`로 opt-in한 경우에만 best-effort
  snapshot을 허용한다. restore는 이번 PR에서 실행하지 않는다.
- **문서/테스트**: `docs/backup-restore.md`와 Docker/deploy runbook에 산출물 구조,
  checksum 검증, 수동 cold restore 경계를 적고, 정적 회귀 테스트로 3종 백업 대상과
  비파괴 범위를 고정한다.

## 2026-06-05 (codex) — T-RV-37e Docker image hygiene

**작업**: T-RV-37 cleanup 중 Docker 이미지 multi-stage/non-root/standalone 항목을
처리한다.

- **Python images**: `api`와 `dagster` Dockerfile을 builder/runtime stage로 분리하고,
  runtime stage는 `appuser`로 실행한다. editable install 대신 builder stage에서
  package install 결과만 runtime으로 복사한다.
- **Frontend image**: Next.js `output: "standalone"`을 활성화하고 runner stage에서
  `.next/standalone` `server.js`를 `nextjs` 사용자로 실행한다.
- **문서/테스트**: Docker runbook에 runtime image 기준을 추가하고, Dockerfile 정적 회귀
  테스트로 multi-stage/non-root/standalone 조건을 고정한다.

## 2026-06-05 (codex) — T-RV-37d ops cursor decode 예외 축소

**작업**: T-RV-37 cleanup 중 `infra.ops_repo._decode_cursor`의 broad exception catch를
구체 예외 처리로 바꾼다.

- **예외 범위**: base64 decode, UTF-8 decode, JSON parse, payload shape,
  `datetime.fromisoformat` 실패를 구체적으로 구분해 `ValueError("invalid ... cursor")`로
  감싼다.
- **회귀 테스트**: wrong-kind cursor, `at` 누락, invalid datetime, non-object payload가
  DB query 실행 전에 거절되는지 unit test로 고정했다.

## 2026-06-05 (codex) — T-RV-37c map-marker-react dependency metadata 정합

**작업**: T-RV-37 cleanup 중 `@kor-travel-map/map-marker-react`의 `maplibre-vworld`
peer dependency와 배포 설명을 정리한다.

- **Peer dependency**: `maplibre-vworld` peer range를 `^0.1.2`에서 `0.1.2`로 고정해
  workspace devDependency의 git tag pin(`github:digitie/maplibre-vworld-js#v0.1.2`)과
  의미를 맞췄다.
- **Lockfile**: root `package-lock.json`의 workspace package entry도 같은 peer range로
  갱신했다.
- **Skeleton test**: 아직 테스트 파일이 없는 skeleton 패키지의 `npm run test`가
  `--passWithNoTests`로 성공 종료되도록 했다.
- **README**: ADR-043 기준 npm registry 게시 보류와 git URL/workspace 공유 기준을
  명시했다.

## 2026-06-05 (codex) — T-RV-21 Dagster router hardening

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-21을 반영한다.

- **GET safety**: `GET /ops/dagster/summary`에서 Dagster `setNuxSeen` mutation을
  제거했다. NUX 처리는 명시적인 `POST /ops/dagster/nux-seen` endpoint로 분리했다.
- **SSRF guard**: `KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS` allowlist를 추가하고
  Dagster URL scheme/userinfo/query/fragment/host와 GraphQL `/graphql` path를
  네트워크 호출 전에 검증한다.
- **Client lifecycle**: Dagster GraphQL 호출은 FastAPI lifespan/app state에서 공유하는
  `httpx.AsyncClient`를 사용한다.
- **Frontend**: `/admin/dagster`는 summary가 정상 조회되면 POST endpoint를 한 번 호출해
  iframe NUX 처리를 유지한다.
- **테스트**: Dagster router unit test와 OpenAPI schema를 새 계약으로 갱신했다.

## 2026-06-05 (codex) — T-RV-37b Dagster purge schedule 문서 정리

**작업**: T-RV-37 cleanup 중 실제 구현과 어긋난 `dagster-boundary.md` purge
job/schedule 문서를 제거한다.

- **Asset/job 표**: 구현 없는 `feature_purge_weather_old`,
  `feature_purge_notice_old` 행을 제거했다.
- **Schedule 표**: 구현 없는 `purge notice old (>1y)` 정기 schedule 행을 제거했다.
- **정책 명시**: ADR-045 D-14의 무기한 보존 기준에 맞춰 purge는 TTL·삭제 정책과 실제
  Dagster job이 같이 들어오기 전까지 schedule 표에 추가하지 않는다고 적었다.

## 2026-06-05 (codex) — T-RV-37a shell script 실행 셸 문서화

**작업**: T-RV-37 cleanup 중 `scripts/*.sh` Bash 전용 실행 셸 문서화를 반영한다.

- **개발환경 문서**: `docs/dev-environment.md`에 WSL/Git Bash 실행 기준과
  PowerShell WSL 위임 예시를 추가했다.
- **Docker runbook**: `npm run docker:*`, `admin:stack`, `ports:stop`이 Bash script를
  호출한다는 점과 직접 PowerShell 실행 금지를 명시했다.
- **Runbook 인덱스**: 공통 정책 표에 `scripts/*.sh` 실행 셸 기준을 추가했다.
- **범위 제한**: PS 래퍼는 만들지 않고 문서화만으로 T-RV-37a를 닫는다.

## 2026-06-05 (codex) — T-RV-36 Dagster dependency hygiene

**작업**: PR#153~#179 리뷰 후속 Dagster 패키지 위생 항목 중 T-RV-36을 반영한다.

- **메인 패키지 핀**: `kor-travel-map-dagster` runtime dependency를
  `kor-travel-map==0.2.0-dev`로 고정해 같은 릴리스 조합을 명시했다.
- **S3 의존성**: `offline_upload_store` resource가 직접 import하는
  `boto3`/`botocore`를 Dagster 패키지 runtime dependencies에 추가했다.
- **pytest 설정**: 패키지 로컬 `pyproject.toml`에도 `asyncio_mode="auto"`를 추가해
  루트 설정에만 의존하지 않게 했다.
- **테스트/문서화**: pyproject metadata 회귀 테스트와 패키지 README 설치 기준을
  추가했다.

## 2026-06-05 (codex) — T-RV-26 Docker healthcheck/readiness

**작업**: PR#153~#179 리뷰 후속 Docker 항목 중 T-RV-26을 반영한다.

- **API healthcheck**: `api` 컨테이너가 내부 `http://127.0.0.1:{port}/debug/health`를
  확인하도록 했다.
- **Frontend healthcheck**: `frontend` 컨테이너가 Node `fetch()`로 Next root `:12305`를
  확인하도록 했다.
- **Dagster healthcheck**: `dagster` webserver가 내부 root URL을 응답하는지 확인한다.
- **Readiness order**: `frontend.depends_on`을 `api: condition: service_healthy`로
  전환했다.
- **테스트**: compose 회귀 테스트가 세 healthcheck와 frontend readiness dependency를
  검증한다.

## 2026-06-05 (codex) — T-RV-28 frontend Docker npm ci

**작업**: PR#153~#179 리뷰 후속 Docker 항목 중 T-RV-28을 반영한다.

- **Lockfile**: 루트 `package-lock.json`을 커밋 대상으로 전환해 frontend workspace
  의존성 해석을 고정한다.
- **Docker build**: `docker/frontend.Dockerfile`은 lockfile을 build context에 포함하고
  `npm install` 대신 `npm ci --workspaces --include=optional`을 사용한다.
- **Ignore 정리**: `.gitignore`와 `.dockerignore`에서 `package-lock.json` 제외를 제거해
  git과 Docker build context 기준을 맞춘다.
- **문서화**: Docker runbook, 배포 메모, review report, tasks/resume를 lockfile 기반
  build 기준으로 갱신한다.
- **검증**: `docker compose build frontend`가 `npm ci`와 Next production build까지
  통과했고, `docker compose config --quiet`와 `git diff --check`도 통과했다.

## 2026-06-05 (codex) — T-RV-18 router typed error mapping

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-18을 반영한다.

- **Feature update request**: `SigunguResolverUnavailable`을 추가해 kor-travel-geo resolver
  설정 누락을 타입으로 표현하고 HTTP `503`으로 매핑한다. 미분류 enqueue 예외는
  generic 500 메시지로 숨긴다.
- **Dedup merge**: `MergeNotFoundError`와 `MergeConflictError`를 `MergeError` 하위
  타입으로 추가했다. dedup review merge 라우터는 404/409를 문구 substring이 아니라
  타입으로 결정한다.
- **오류 노출 방지**: 알 수 없는 `MergeError`와 enqueue exception은 내부 메시지를
  API 응답에 그대로 노출하지 않는다.
- **테스트**: feature update/dedup review 라우터 unit test와 merge repo integration
  test를 보강했다.

## 2026-06-05 (codex) — T-RV-17 상태전이 guard

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-17을 반영한다.

- **Admin feature**: `deactivate_feature`가 `status='deleted'` 또는 `deleted_at IS NOT
  NULL` feature를 inactive로 되살리지 않고 `FeatureStateConflict`를 올린다. 라우터는
  이 예외를 HTTP `409`로 매핑한다.
- **Integrity issue**: `set_data_integrity_violation_status`가
  `resolved`/`ignored` terminal 상태를 다른 상태로 되돌리지 않으며, 같은 terminal
  상태 재호출 시 기존 `resolved_at`을 보존한다.
- **Offline upload**: validation/load mark/finish 쿼리에 source-state guard를 추가했다.
  `loaded` 상태는 더 이상 loadable로 취급하지 않아 중복 Dagster launch와
  `loaded -> loading` 역전이를 차단한다.
- **테스트**: admin feature repo/router, integrity issue lifecycle, offline upload
  repo/router/load orchestration focused unit/integration test를 추가·갱신했다.

## 2026-06-05 (codex) — T-RV-16 dedup refresh master 신호/keyset

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-16을 반영한다.

- **Schema/DTO**: `Feature.coord_precision_digits`와
  `feature.features.coord_precision_digits`를 추가했다. DB trigger가 coord 보유 row의
  기본 precision을 6으로 보강하고, coord가 없으면 precision을 `NULL`로 정리한다.
- **Dedup refresh**: `DedupRefreshFeature`가 `updated_at`, `coord_precision_digits`,
  `as_master_candidate()`를 노출한다.
- **Keyset**: dedup refresh 조회는 `updated_at DESC, feature_id DESC` cursor와
  `idx_features_dedup_refresh_keyset` partial index를 사용해 limit 반복 스캔을 피한다.
- **Dagster config**: maintenance dedup refresh scope에서
  `cursor_updated_at`/`cursor_feature_id`를 받을 수 있게 했다.
- **정책 문서화**: 최소 수정/호환성보다 완성도, 최적 구조, 확장성, 안정성을 우선하는
  코드 수정 원칙을 `SKILL.md`와 `docs/agent-guide.md`에 명시했다.

## 2026-06-05 (codex) — T-RV-15 scope resolver count/preview 분리

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-15를 반영한다.

- **Dry-run count**: `count_features_matching_scope`가 공간/시군구/provider/feature id
  scope에서 전체 feature row 대신 `count(*)` 계열 SQL로 총 match 수를 계산한다.
- **Preview 상한**: dry-run matched scope는 기본 1000개 feature preview만 보존하고,
  잘린 경우 `feature_preview_count`, `feature_preview_limit`,
  `feature_preview_truncated`를 기록한다.
- **전체 집계 유지**: provider/dataset fanout과 sigungu code는 preview가 아니라 전체
  scope 기준 별도 SQL로 집계한다.
- **테스트**: `preview_limit=1`에서도 전체 `feature_count`와 provider/dataset
  집계가 3개를 유지하는 PostGIS integration test를 추가한다.

## 2026-06-04 (codex) — T-RV-14 dedup merge review row 잠금

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-14를 반영한다.

- **저장소 동작**: `merge_from_review`와 admin `merge_dedup_review`가
  `ops.dedup_review_queue` review row를 `FOR UPDATE`로 잠근 뒤 pending 상태를
  확인한다.
- **경합 차단**: 자동 master 선정 경로와 수동 master 지정 경로 모두 같은 row lock
  규칙을 사용해 동시 merge TOCTOU를 차단한다.
- **테스트**: Postgres `lock_timeout` 기반 integration test로 기존 row lock 보유 시
  두 merge 경로가 대기/실패하는지 검증한다.
- **정책**: T-RV-27(admin API bind/노출)은 production 레벨 hardening 전까지 구현하지
  않고 skip/deferred로 문서 추적만 유지한다.

## 2026-06-04 (codex) — T-RV-13 UUID default 스키마 한정

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-13을 반영한다.

- **Model/migration source**: bare `gen_random_uuid()`가 남아 있던
  `feature_consistency_reports`, `dedup_review_queue`, `import_jobs`,
  `feature_merge_history` default를 `x_extension.gen_random_uuid()`로 통일했다.
- **Migration**: `0014_uuid_default_schema`는 기존 DB의 네 default를
  schema-qualified expression으로 변경한다.
- **Tests**: alembic head 적용 후 Postgres catalog의 ops UUID default expression이
  모두 `x_extension.gen_random_uuid()`인지 검증한다.

## 2026-06-04 (codex) — T-RV-12 dedup pair 순서 독립 unique

**작업**: PR#153~#179 리뷰 후속 MED 항목 중 T-RV-12를 반영한다.

- **Schema invariant**: `ops.dedup_review_queue`에 `ck_dedup_pair_order`
  (`feature_id_a < feature_id_b`)를 추가해 canonical 방향만 저장한다.
- **Migration**: `0013_dedup_pair_order_invariant`는 기존 self-pair를 제거하고,
  unordered duplicate는 검토 완료 행 우선으로 하나만 남긴 뒤 canonical 방향으로
  정규화한다.
- **Repo behavior**: `dedup_repo`가 후보 pair를 upsert 전에 canonicalize하고,
  self-pair는 큐에 적재하지 않고 `skipped`로 처리한다.
- **Tests**: reversed pair upsert가 기존 canonical row를 갱신하는지, self-pair가
  skip되는지, DB check가 비정규 방향 직접 insert를 막는지 검증한다.

## 2026-06-04 (codex) — T-RV-10 keyset cursor 정밀도

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-10을 반영한다.

- **Feature search cursor**: q 검색 cursor는 DB `score::text`를 보존하고,
  `(-score, feature_id)` row-tuple 비교로 `ORDER BY score DESC, feature_id ASC`와
  같은 축을 사용한다.
- **Dedup review cursor**: `total_score` `NUMERIC` cursor를 string으로 운반하고,
  predicate와 `ORDER BY`의 review key 축을 모두 `review_id::text`로 통일했다.
- **Tests**: 같은 score/total_score를 가진 여러 행을 `page_size=1`로 끝까지 넘기는
  PostGIS integration test를 추가해 skip/dup 회귀를 잠갔다.

## 2026-06-04 (codex) — T-RV-05/11 feature update lock 경합

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-05/11을 반영한다.

- **run-now lock**: `run_mode=now` 생성/재큐잉이 동일 scope advisory lock 점유를
  감지하면 `409 LOCK_BUSY`로 응답한다. 응답에는 `Retry-After: 15`와
  `details.retry_after_seconds=15`를 포함한다.
- **Executor scope lock**: feature update executor가 실행 중
  `feature_update_scope_advisory_key(...)` 기반 scope lock을 보유해 API preflight가
  실제 실행 경합을 감지한다.
- **Queue claim**: `claim_next_update_request`가 queue advisory lock 경합을
  `FeatureUpdateQueueLockBusy` 예외로 올려 빈 큐 `None`과 구분한다.
- **Tests**: admin router unit, PostGIS queue/scope lock integration, executor scope
  lock 보유 integration test로 회귀를 잠갔다.

## 2026-06-04 (codex) — T-RV-04a Dagster provider resource guard

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-04의 1차 guard를 반영한다.

- **Provider resource guard**: feature-load provider record key 9개에 기본 guard
  resource를 등록했다. code location은 로드되고, materialize 시 provider/package/env
  안내가 포함된 명확한 `RuntimeError`를 낸다.
- **Settings/env**: `KorTravelMapSettings`에 `data_go_kr_service_key`, `opinet_api_key`,
  `krex_ex_api_key`, `krex_go_api_key`를 추가하고 `.env.example`,
  `scripts/load-env.sh`, `docker-compose.yml`에 전달 매핑을 추가했다.
- **Tests**: provider env mapping과 secret 값 미노출, definitions guard 등록을 검증한다.
- **잔여**: T-RV-04b에서 provider별 public client live fetcher를 실제 record iterable로
  연결한다.

## 2026-06-04 (codex) — T-RV-03 Dagster resource lifecycle

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-03을 반영한다.

- **Resource lifecycle**: `kor_travel_map_client_resource`를 generator resource로 전환해
  Dagster run/tick 종료 후 `AsyncEngine.dispose()`를 호출한다.
- **Async teardown**: Dagster sync resource teardown 지점에 이미 event loop가 있으면
  별도 thread에서 async dispose를 실행하고 예외를 다시 올린다.
- **Tests**: fake engine/fake client 기반으로 DB 없이 resource 종료 시 dispose 호출을
  검증한다.
- **잔여**: T-RV-04 provider public client/service key resource wiring은 다음 Dagster
  resource PR 후보로 남긴다.

## 2026-06-04 (codex) — T-RV-01/02 Dagster metadata DB + daemon split

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-01/02를 반영한다.

- **Docker**: `dagster` 서비스를 `dagster-webserver` 실행으로 명시하고,
  `dagster-daemon` 서비스를 추가했다.
- **Metadata DB**: `dagster-db-init` 서비스가 같은 Postgres container 안에
  `kor_travel_map_dagster` DB 존재를 보장한다.
- **Dagster storage**: `docker/dagster.yaml`을 추가해 `KOR_TRAVEL_MAP_DAGSTER_PG_URL` 기반
  `storage.postgres`를 설정하고, `kor-travel-map-dagster`에 `dagster-postgres` 의존성을
  추가했다.
- **Tests**: `tests/unit/test_docker_dagster_runtime.py`가 compose split, Postgres
  storage 설정, dependency를 고정한다.

## 2026-06-04 (codex) — T-RV-08 public response field hardening

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-08을 반영한다.

- **Feature detail**: public `FeatureDetailResponse`에서 `coord_5179_srid`,
  `parent_feature_id`, `sibling_group_id`를 제거했다.
- **By-target**: `/features/nearby/by-target` 응답에서 target `target_id`,
  `refresh_policy`, `update_enabled`, `next_eligible_refresh_at`과 item
  `primary_provider`, `primary_dataset_key`를 제거했다.
- **OpenAPI**: `packages/kor-travel-map-api/openapi.json`과 `openapi.user.json`을
  재생성했고, user spec schema 누출 회귀 테스트를 추가했다.
- **문서**: `docs/tripmate-rest-api.md`, `docs/poi-cache-update-targets.md`,
  `docs/openapi-admin-contract.md`를 public fieldset 기준으로 정렬했다.

## 2026-06-04 (codex) — T-RV-07 admin/ops router gate

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-07을 반영한다.

- **Settings**: `ApiSettings.admin_routes_enabled`와 `ops_routes_enabled`를 추가했다.
  둘 다 unset이면 `features_routes_enabled`를 따른다.
- **Admin API**: DB 없는 부팅 검증에서 `features_routes_enabled=False`를 주면
  `/features/*`뿐 아니라 DB 의존 `/admin/*`, `/ops/*`, `/ops/dagster/*` 라우터도 함께
  mount하지 않는다.
- **Tests**: `test_routers.py`에 OpenAPI path 제거와 404 회귀 테스트, admin/ops 명시
  opt-in 테스트를 추가했다.
- **사용자 결정**: T-RV-27(admin API `0.0.0.0` bind/노출)은 production 레벨 hardening
  전까지 구현하지 않고 deferred/skip으로 문서 추적한다.

## 2026-06-04 (codex) — T-RV-06 admin API error envelope

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 T-RV-06을 반영했다.

- **Admin API**: `create_app()`에 `StarletteHTTPException`과 `RequestValidationError`
  handler를 등록해 에러 응답을 `{error:{code,message,details,request_id}}`로 통일했다.
- **Request ID**: `X-Request-ID` 요청 헤더가 있으면 같은 값을 응답 헤더와 envelope에
  되돌리고, 없으면 UUID를 생성한다.
- **Validation**: FastAPI 기본 422를 `VALIDATION_ERROR` code와 `details.errors`로
  변환한다.
- **Tests**: `test_error_envelope.py`를 추가하고, admin router 테스트의 `detail`
  고착 assertion을 `error.message` 기준으로 교정했다.

## 2026-06-04 (codex) — T-RV-09 offline upload 크기 상한

**작업**: PR#153~#179 리뷰 후속 HIGH 항목 중 첫 처리 순서인 T-RV-09를 반영했다.

- **Settings**: `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES`를 추가했다. 기본값은
  `104857600` bytes(100 MiB)다.
- **Admin API**: `POST /admin/offline-uploads`가 `Content-Length`로 명백히 큰 multipart
  요청을 먼저 `413`으로 차단하고, 실제 `UploadFile.read()`도 `max_bytes + 1`까지만
  수행해 무제한 메모리 read를 막는다.
- **환경 전파**: `.env.example`, `scripts/load-env.sh`, `docker-compose.yml`의 API/
  Dagster 환경에 같은 키를 추가했다.
- **문서**: `docs/tasks.md`, `docs/openapi-admin-contract.md`,
  `docs/debug-ui-admin-workflows.md`, `docs/feature-files-rustfs.md`, `CHANGELOG.md`에
  상한 정책과 `413` 계약을 기록했다.
- **범위 유보**: S3 multipart streaming, object orphan 보상, upload store 재사용은
  store protocol/API 상태전이를 건드리는 T-RV-22/23/25와 함께 후속 처리한다. 이번 PR은
  무제한 read/OOM surface를 닫는 최소 운영 안전장치다.
- **사용자 결정**: T-RV-27(admin API `0.0.0.0` bind/노출)은 production 레벨 외부 노출
  전까지 구현하지 않고 deferred로 문서 추적한다. 다음 구현 후보는 T-RV-06/07/08이다.

## 2026-06-04 (codex) — T-200 Batch DAG + 정합성 게이트

**작업**: T-205d batch 컬럼 위에 root/child/gate orchestration을 추가했다.

- **Core/Repo**: `infra.jobs_repo`에 기존 import job batch 연결/목록 조회 유틸을
  추가하고, `infra.batch_dag.run_batch_dag_consistency_gate`를 새로 만들었다.
- **Gate**: 기존 실제 적재 job id를 `child_job_ids`로 받아 root `full_load_batch`
  아래 연결한다. child가 모두 `done`이면 `consistency_check`를 실행하고,
  `severity_max=ERROR`이면 `mv_refresh`를 차단한다.
- **MV refresh**: `OK/WARN`이면 `mv_refresh` import job을 기록한다. 현재 운영
  materialized view 카탈로그가 없으면 `skipped:no_materialized_views` payload로 남긴다.
- **Dagster**: `full_load_batch_consistency_gate` job/op를 추가하고 definitions에 등록했다.
- **문서**: `tasks`, `dagster-boundary`, `adr045-standalone-plan`, `SPRINT-5`,
  `resume`, `CHANGELOG`를 T-200 완료 범위로 갱신했다.
- **검증**: unit coverage 재현 `800 passed` / `80.59%`, Dagster package `17 passed`,
  PostGIS integration `tests/integration/test_batch_dag.py tests/integration/test_jobs_repo.py`
  `14 passed`, repo-wide `ruff`/`mypy`/import-linter, `git diff --check` 통과.
- **다음**: T-201b Phase 2(F5~F8 gate + 운영 MV 카탈로그/정책)와 T-209 잔여를 닫은 뒤
  T-212 전체점검으로 이동한다.

## 2026-06-04 (codex) — T-209b run-admin-stack 안정화

**작업**: PR#182 머지 후 서버 재기동에서 `scripts/run-admin-stack.sh`가 Next ready
로그를 남겼는데도 wrapper PID/readiness false negative로 실패하고, shell 종료 뒤
background 프로세스가 내려가는 문제를 재현했다.

- **수정**: `run-admin-stack.sh`가 서비스 시작 전 `alembic upgrade head`를 실행한다.
- **수정**: API/frontend/Dagster background 실행을 `setsid` + `nohup`으로 분리한다.
- **수정**: readiness는 wrapper PID 생존 여부보다 URL 응답을 우선한다. launcher PID가
  먼저 종료돼도 timeout 전까지 URL readiness를 계속 확인한다.
- **검증**: `bash -n`, 수정된 `scripts/run-admin-stack.sh` 실제 실행(API `12301`,
  Web `12305`, Dagster `12302` readiness 통과), API/Web/Dagster smoke HTTP 200,
  `git diff --check` 통과.
- **범위**: Dagster metadata DB 분리/init와 daemon/schedule 운영은 T-209b 후속으로
  계속 남긴다.

## 2026-06-04 (codex) — T-205d import_jobs batch 컬럼

**작업**: T-200 Batch DAG 선행 스키마로 `ops.import_jobs`에 `load_batch_id`와
`parent_job_id` self-FK를 추가했다.

- **DB/Repo**: `alembic 0012_import_jobs_batch_columns`, `ImportJobRow`,
  `infra.jobs_repo`에 batch/parent 생성·반환 경로를 추가했다. batch/parent 조회용
  partial index `idx_import_jobs_load_batch_created`, `idx_import_jobs_parent_created`도
  함께 추가했다.
- **Ops API/UI**: `/ops/import-jobs` 목록/상세 응답에 `load_batch_id`와
  `parent_job_id`를 포함하고, query filter를 추가했다. admin UI 목록에는 batch/parent
  필터와 축약 id 컬럼을 노출했다.
- **문서**: `docs/tasks.md`, `docs/data-model.md`, `docs/postgres-schema.md`,
  `docs/dagster-boundary.md`, `docs/openapi-admin-contract.md`,
  `docs/debug-ui-admin-workflows.md`, `docs/resume.md`, `CHANGELOG.md`를 갱신했다.
- **검증**: unit coverage 재현 `792 passed` / `80.56%`, admin package `132 passed`,
  Dagster package `15 passed`, targeted migrated PostGIS integration `13 passed`, mixed
  unit/integration `22 passed`, repo-wide `ruff`/`mypy`/import-linter, OpenAPI
  `--profile all --check`, frontend `type-check`/`lint`/`build`, React Doctor full scan
  (기존 optional warning 7개) 통과.
- **다음**: T-200 Batch DAG + consistency gate 구현으로 이동한다.

## 2026-06-04 (codex) — T-208i offline CSV/TSV validation + bjd 보강

**작업**: admin UI #9의 offline upload 선행 task를 CSV/TSV까지 확장했다. 업로드 API는
JSON/JSONL 외 CSV/TSV를 허용하고, tabular 원본은 preview → validation job → Dagster
load 순서로 처리한다.

- **Core/API**: `kortravelmap.offline_upload`에 column mapping, preview, validation issue,
  validation import job, validation payload 기반 CSV/TSV parser/load를 추가했다.
  `GET /admin/offline-uploads/{upload_id}/preview`,
  `POST /admin/offline-uploads/{upload_id}/validate`,
  `GET /admin/offline-uploads/{upload_id}/validation`을 admin OpenAPI에 노출했다.
- **법정동코드 보강**: `AddressResolver`와 kor-travel-geo REST v2 geocode response → `Address`
  변환을 추가했다. offline CSV/TSV, MOIS, datagokr 표준데이터, OpiNet, KREX,
  krheritage 변환 경로에서 `bjd_code`가 없으면 주소 geocode 또는 좌표 reverse로
  보강한다.
- **Dagster**: `offline_upload_load` op가 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` 설정 시
  kor-travel-geo resolver/reverse geocoder를 열어 CSV/TSV load에 주입한다.
- **Admin UI**: `/admin/offline-uploads`에 CSV/TSV mapping form, header/sample preview,
  validation issue table, validation 완료 전 load gate를 추가했다.
- **문서**: OpenAPI/admin workflow/README/changelog/resume/tasks를 T-208i 기준으로
  갱신했다. ADR-045 전체점검은 `T-212a`~`T-212e`와
  `docs/reports/adr-045-overall-audit-plan-2026-06-04.md`로 분리했다.
- **검증**: unit-only coverage `792 passed` / `80.54%`, integration/admin/dagster
  `293 passed`, targeted backend/provider/router unit `114 passed`, offline upload
  PostGIS integration `4 passed`, repo-wide `ruff`/`mypy`/import-linter, frontend
  `type-check`/`lint`/`build`, React Doctor full scan(기존 optional warning 7개),
  Windows Next dev server + WSL API 조합의 admin/ops Playwright e2e `6 passed`,
  OpenAPI admin/user drift check를 확인했다. 전체 integration에서 발견한 기존 PostGIS
  extension CASCADE fixture 충돌도 함께 보정했다.
- **다음**: PR 생성 후 GitHub Actions 결과를 확인하고 실패를 반영한다. 머지 후
  T-205d → T-200/T-201b 순서로 진행한다.

## 2026-06-04 (claude) — PR#153~#179 ADR-045 구현 배치 상세 코드 리뷰

**작업**: 사용자 지시 — 최신 레포 재독 후 리뷰 없이 머지된 PR 전부 상세 리뷰,
반영 항목을 task로 문서화 후 PR/머지. 대상은 ADR-045 독립 프로그램화 구현 배치
27건(#153~#179, `9720ca8..62e8a68`, 225파일 +39885). 영역별 병렬 리뷰
에이전트 6개(infra repo / Dagster / admin router / offline-upload /
geocoding·alembic·client / docker·OpenAPI·frontend)로 수집.

- **산출**: `docs/reports/pr-153-179-review-2026-06-04.md` 신설 — HIGH 11 +
  MED 25 + LOW 묶음 1을 `T-RV-NN` task로 정리(파일위치·근거·권장 fix·처리 순서).
  `docs/tasks.md`에 "코드 리뷰 후속 백로그" 섹션으로 HIGH/MED 요약 + 리포트 링크.
- **HIGH 핵심**: D-2 Dagster 별도 DB/daemon 미구현(SQLite 폴백), D-15 provider
  resource 미구현(feature-load asset 실행 불가), D-6 run-now 409 락 미구현,
  에러 envelope 전무, admin 라우터 무조건 mount, D-7 공개 응답 누출, offline
  업로드 크기 상한 부재(OOM), keyset cursor float 정밀도, admin API 0.0.0.0 노출.
- **검증된 정상**: geocoding 라우터 제거 clean(dangling 없음), alembic 0007~0011
  단일 head·ADR-012 준수, D-14 무제한 보존 준수, core offline 레이어 청결,
  ADR-022/006 위반 0. (리포트 §4)
- **문서 전용 PR**(코드 미변경) — 후속 구현은 T-RV-NN로 분리 진행.

## 2026-06-03 (codex) — T-208h offline uploads API/UI

**작업**: admin UI #9의 선행 작업으로 `/admin/offline-uploads*` API와 기본 upload
화면을 구현.

- **Admin API**: `POST /admin/offline-uploads` multipart upload, `GET` 목록,
  `GET /{upload_id}` 상세, `POST /{upload_id}/load` Dagster launch를 추가했다.
  현재 upload 형식은 JSON/JSONL `FeatureBundle` 파일이다.
- **RustFS 저장**: API가 먼저 `upload_id`를 만들고
  `offline-uploads/{upload_id}/{filename}` key에 bytes를 저장한 뒤,
  같은 id로 `ops.offline_uploads` row를 생성한다.
- **Dagster 실행**: load endpoint는 DB row 상태를 확인한 뒤 Dagster GraphQL
  `launchRun`으로 `offline_upload_load` job을 실행한다. run id/status를 API 응답
  metadata로 반환한다.
- **목록/상세 repo**: `infra.offline_upload_repo`에 keyset list page와 optional
  `upload_id` insert를 추가했다.
- **Admin UI**: `/admin/offline-uploads` 화면과 nav 항목, `offlineUploads.ts` typed
  hook, `FormData` POST helper를 추가했다. 업로드, state/provider/dataset filter,
  상세 panel, load 버튼을 제공한다.
- **OpenAPI**: admin/user OpenAPI 산출물을 `--profile all`로 갱신했다. user subset에는
  내부 offline upload API를 포함하지 않는다.
- **검증**: backend/admin/Dagster/offline upload focused pytest `21 passed`, targeted
  `ruff`, 전체 strict `mypy`, `lint-imports`, OpenAPI drift check, frontend
  `type-check`, `lint`, `build`, React Doctor full scan 통과. React Doctor optional
  warning 7개는 기존 shadcn/ui primitive와 Dagster iframe rule로 분류했다.
- **Live smoke**: WSL 실제 서버(API `12301`, web `12305`, Dagster `12302`)에서 multipart
  upload → RustFS `krtour-uploads` 저장 → Dagster `offline_upload_load` run
  `SUCCESS` → DB `upload_state=loaded`, `job_state=done`, `progress=100`을 확인했다.
- **Windows Playwright**: WSL IP fallback으로 `admin-ops.spec.ts` 6/6 통과. 새
  `/admin/offline-uploads` route smoke를 추가했다.
- **다음**: 9번 admin UI 최신화 우선순위를 최상위로 두고 T-208i CSV/TSV validation +
  column mapping wizard부터 진행.

## 2026-06-03 (codex) — T-208b RustFS offline upload store wiring

**작업**: admin UI #9 offline upload 화면의 선행조건으로, Dagster
`offline_upload_load` job이 실제 RustFS/S3 호환 object store에서 원본 파일을 읽을 수
있도록 T-208b 잔여 resource wiring을 구현.

- **S3 호환 store**: `kortravelmap.infra.file_store.S3ObjectStore`를 추가했다.
  boto3 호환 client의 `get_object`/`put_object`를 `asyncio.to_thread`로 감싸고,
  읽기/쓰기 실패는 `FileStoreError`로 표준화한다.
- **설정 정렬**: `KorTravelMapSettings`에
  `KOR_TRAVEL_MAP_OBJECT_STORE_{ENDPOINT_URL,BUCKET,REGION,ACCESS_KEY_ID,SECRET_ACCESS_KEY,
  PUBLIC_BASE_URL,PREFIX}`와 `KOR_TRAVEL_MAP_OFFLINE_UPLOAD_{BUCKET,PREFIX}`를 맞췄다.
  offline upload 기본 bucket은 ADR-045 D-14 정본인 `krtour-uploads`다.
- **Dagster resource**: `kortravelmap.dagster.resources`를 추가하고,
  `offline_upload_store_resource`가 환경변수 기반 boto3 client와
  `krtour-uploads` bucket store를 기본 제공하게 했다. 테스트/운영 특수 배포는 기존처럼
  resource override가 가능하다.
- **Docker/RustFS**: `docker-compose.yml`에 `rustfs`, `rustfs-perms`,
  `rustfs-init`를 추가했다. RustFS host port는 API `12101`, console `12105`이고,
  `rustfs-init`가 `kor-travel-map`과 `krtour-uploads` bucket을 생성한다.
- **검증**: `S3ObjectStore`/Dagster resource/definitions/offline upload Dagster unit
  `8 passed`, targeted `ruff`, targeted `mypy`, `docker compose config --quiet` 통과.
  Docker RustFS를 실제 기동해 `rustfs-init` bucket 생성(`kor-travel-map`,
  `krtour-uploads`)과 `S3ObjectStore.write_bytes/read_bytes` put/get smoke를 확인했다.
- **다음**: admin UI #9 선행으로 `/admin/offline-uploads*` multipart upload/list/detail/
  load API와 upload 화면을 먼저 연결한다. CSV/TSV column mapping wizard는 그 다음
  별도 task로 진행한다.

## 2026-06-03 (codex) — T-208g offline upload load job

**작업**: admin offline upload API/UI의 선행 DB/job 계약으로, 객체 저장소에 이미
저장된 원본 파일을 Dagster가 읽어 PostGIS에 적재하는 T-208g를 구현.

- **DB 계약**: `ops.offline_uploads` 테이블(alembic 0011)과
  `infra.offline_upload_repo`를 추가했다. provider/dataset/scope, storage backend/key,
  byte size/checksum, detected format/encoding, validation/load `import_jobs` FK,
  state를 보존한다.
- **Parser/load orchestration**: `kortravelmap.offline_upload`가 JSON/JSONL
  `FeatureBundle` dump를 읽는다. `Feature.detail` dict 금지(ADR-018)는 kind별 detail
  DTO hydrate로 지키고, size/checksum 검증 뒤 `load_bundles`를 호출한다.
- **직렬화/진행 상태**: provider/dataset/scope advisory lock을 잡고,
  `ops.import_jobs`를 `running → done|failed`로 전이한다. checksum/parser/load 실패는
  `offline_uploads.state='load_failed'`와 failed job row로 남긴다.
- **Client/Dagster**: `AsyncKorTravelMapClient.run_offline_upload_load_job`와 Dagster
  `offline_upload_load` job을 추가했다. job은 `upload_id` config와
  `offline_upload_store` resource를 받는다.
- **범위 명시**: multipart upload/validate/load admin API, CSV/TSV column mapping
  wizard는 후속이다. 이번 PR은 API/UI가 사용할 영속 DB와 Dagster load 경로를 먼저
  닫는다. 실제 RustFS resource wiring은 후속 T-208b에서 처리했다.
- **검증**: parser/Dagster definitions unit `8 passed`, migrated PostGIS integration
  `2 passed`.
- **다음**: T-208b 잔여 RustFS/provider 실제 resource wiring 또는
  `/admin/offline-uploads*` API/UI 선행 task 분리.

## 2026-06-03 (codex) — T-208f consistency/dedup refresh job

**작업**: T-211b admin UI 최신화 머지 후, 독립 Dagster 운영 완성 선행 task인
T-208f를 진행.

- **DB 기준 dedup 입력 조회**: `infra.dedup_refresh_repo`를 추가해 활성 feature를
  primary source의 provider/dataset scope 기준으로 읽고, `Coordinate(lon, lat)`를
  포함한 `DedupInput` 값 객체로 변환한다.
- **Client orchestration**: `AsyncKorTravelMapClient`에 pair refresh,
  sibling refresh, consistency report 실행 메서드를 추가했다. 후보 큐 upsert는 기존
  `enqueue_dedup_candidates`를 그대로 사용하고, 검토 완료 행 보존 규칙도 유지한다.
- **Dagster job**: `consistency_dedup_refresh` job을 추가했다.
  `refresh_dedup_candidates` op가 `pairs`/`sibling_scopes` config를 처리하고,
  `run_consistency_check` op가 이어서 F1~F4 report를 저장한다.
- **Schedule**: `consistency_dedup_refresh_daily_schedule`을 `Asia/Seoul`
  `45 5 * * *`, 기본 `STOPPED`로 등록했다. 운영 enable 전까지 자동 실행하지 않는다.
- **경계 명시**: 이번 작업은 ADR-033 Phase 2 gate/swap 차단이 아니라 관측/refresh
  job이다. Phase 2의 F5~F8 + swap 차단은 후속으로 유지한다.
- **검증**: Dagster maintenance/definitions unit `5 passed`, PostGIS client 경로
  integration `5 passed`.
- **다음**: T-208g offline upload load job.

## 2026-06-03 (codex) — T-211b admin UI 최신화 구현

**작업**: admin UI 최신화 우선순위를 최고로 올린 뒤, T-211a의 선행 API/gap 정리를
바탕으로 실제 운영 화면을 구현.

- **App shell**: `AdminShell`, `StatusBadge`, format helper를 추가해 `/`, `/ops/*`,
  `/admin/*`, `/admin/dagster`, `/etl`을 같은 운영 navigation 안에서 이동하게 했다.
- **홈 dashboard**: 기존 health/version 중심 skeleton을 feature/import job/dedup/
  integrity issue/Dagster summary 중심 운영 홈으로 교체했다.
- **Dagster 화면**: `/admin/dagster`가 Dagster webserver iframe embed를 유지하면서
  asset group, recent run, schedules, sensors 정보를 자체 UI로 보여준다.
- **신규 route**: `/ops/import-jobs`, `/ops/consistency`, `/admin/dedup-review`,
  `/admin/feature-update-requests`, `/admin/poi-cache-targets`를 추가했다.
- **Feature 화면 연결**: 기존 `/features` 지도/테이블은 유지하고 jobs/update/target/
  dedup/Dagster 운영 화면 링크를 header action으로 추가했다.
- **고정 포트 정리**: WSL 일반 사용자에게 PID가 숨겨진 root listener 또는 Windows
  `node.exe`/`wslrelay.exe`가 12305를 점유해 stale UI가 보이는 경우가 있어
  `scripts/stop-fixed-ports.sh`에 WSL root/Windows listener 정리를 추가했다.
- **WSL IP e2e fallback**: localhost relay가 사라진 상태에서도 Windows Playwright가
  WSL 서버를 직접 검증할 수 있도록 `scripts/load-env.sh` 기본 CORS origin에
  `http://<WSL-IP>:12305`를 포함하고, admin FastAPI CORS 응답/preflight 헤더 보강을
  추가했다.
- **e2e 갱신**: home e2e를 새 운영 홈 계약에 맞추고, 신규 admin/ops route smoke를
  추가했다. API 행 수보다 title/filter/form/table 같은 운영 표면을 검증한다.
- **검증**: source/WSL frontend `type-check`, `lint`, `test`, `build`, React Doctor
  통과. Windows Playwright e2e는 API/Dagster를 WSL IP로, web을 Windows
  `127.0.0.1:12305`로 띄운 구성에서 16/16 통과했다. React Doctor optional warning은
  source 7건(기존 shadcn/ui primitive export/multi component, label false positive,
  Dagster iframe sandbox rule false positive)이고, `.git` 없는 WSL mirror full scan은
  미사용 detail hook까지 포함해 12건을 보고한다.
- **다음**: T-208f consistency/dedup refresh job. 이후 T-208g offline upload load job.

## 2026-06-03 (codex) — T-211a admin UI 선행 gap audit/API 계약

**작업**: 사용자 지시로 admin UI 최신화 우선순위를 최고로 올리고, 실제 화면 구현 전
선행 gap audit과 frontend typed API hook layer를 보강.

- **Gap audit**: `docs/admin-ui-modernization-gap-audit.md` 신규. route별로 T-211b에서
  바로 구현 가능한 화면, 사용할 API/hook, backend gap을 분리했다.
- **Frontend API**: `importJobs.ts`, `ops.ts`, `dedup.ts`, `updateRequests.ts`,
  `poiCacheTargets.ts`를 추가하고 `features.ts`에 `/admin/features` 목록/비활성화
  hook을 보강했다.
- **공통 client**: `client.ts`에 `getJson`/`postJson`/`putJson`/`patchJson`/
  `deleteJson`, `pathWithQuery`를 추가해 admin/ops module의 fetch 동작을 통일했다.
- **테스트 스크립트**: frontend `npm test`가 Playwright e2e spec을 Vitest로 잘못
  수집하지 않도록 `e2e/**`를 제외했다. e2e는 기존 `npm run e2e`로 실행한다.
- **문서 정리**: import job 조회 정본을 `/ops/import-jobs`로 고정했다.
  `/admin/import-jobs` cancel/events/stream은 후속 쓰기/이벤트 계약으로 분리한다.
- **검증**: frontend `type-check`, `lint`, `test`, `build`, Python `ruff`/`mypy`/
  `lint-imports`, OpenAPI drift check 통과. WSL mirror에서도 같은 gate를 확인했다.
  React Doctor는 exit code 0이나 optional warning을 보고했다. 내용은 기존 shadcn/ui
  primitive 구조(label, variant export, multi component)와 기존 Dagster iframe
  sandbox 경고이며, T-211b 화면 재작업에서 함께 정리한다.
- **다음**: T-211b admin UI 최신화 구현. Dagster iframe embed와 자체 summary UI,
  feature/update request/ops 화면을 최신 문서 기준으로 보완한다.

## 2026-06-03 (codex) — T-208d Dagster provider schedules

**작업**: ADR-045 Phase 4 T-208d. kor-travel-map-owned Dagster code location에 provider별
Feature 적재 schedule을 등록.

- **Schedules**: `kortravelmap.dagster.schedules` 신규. 현재 구현된 Feature 적재 asset
  9개에 대해 `define_asset_job` + `ScheduleDefinition`을 만든다.
- **Timezone/분산**: 모든 schedule은 `execution_timezone="Asia/Seoul"`이고, 외부 API
  호출이 같은 분에 몰리지 않도록 분/요일을 분산했다.
- **운영 기본값**: schedule `default_status`는 `STOPPED`다. 로컬 개발 중 실 provider
  호출을 막고, 운영 배포에서 필요한 schedule만 enable한다.
- **Definitions**: `Definitions`에 Feature load jobs/schedules를 등록했다. 기존
  `feature_update_request_worker` job과 queue/failure sensor는 유지한다.
- **문서**: Dagster README, `dagster-boundary.md`, ADR-045 task 계획, tasks/resume,
  admin OpenAPI 예시 count를 갱신했다.
- **검증**: Dagster definitions smoke + schedule 등록 테스트 targeted `3 passed`,
  targeted ruff/mypy 통과.
- **다음**: 사용자 지시에 따라 admin UI 최신화 선행 task를 최우선으로 진행한다.
  다음 task는 T-211a admin UI gap audit/API 계약 보강.

## 2026-06-03 (codex) — T-207g OpenAPI admin/user 이원화

**작업**: ADR-045 Phase 3 T-207g. admin 전체 OpenAPI와 TripMate/user-facing subset
OpenAPI를 별도 산출물로 관리하고 drift gate를 이원화.

- **Export profile**: `packages/kor-travel-map-api/scripts/export_openapi.py`에
  `--profile admin|user|all`을 추가했다. 기본 admin profile은 기존
  `packages/kor-travel-map-api/openapi.json`을 유지한다.
- **User spec**: `packages/kor-travel-map-api/openapi.user.json`을 추가했다. 포함 경로는
  `/features/in-bounds`, `/features/{feature_id}`, `/features/search`,
  `/features/nearby/by-target`, `/tripmate/features/batch`,
  `/admin/feature-update-requests` POST,
  `/admin/feature-update-requests/{request_id}` GET이다.
- **Prune**: user spec은 사용되는 `components.schemas`만 재귀적으로 남기고
  `/debug/*`, `/ops/*`, `/admin/features*` 같은 내부 운영 API schema는 제외한다.
- **CI**: `.github/workflows/openapi.yml` drift check를 `--profile all --check`로
  바꿔 admin/user spec을 함께 비교한다.
- **검증**: OpenAPI export unit `1 passed`, `--profile all --check`, ruff targeted
  통과.
- **다음**: T-208d Dagster schedules(KST cron, 부하 분산).

## 2026-06-03 (codex) — T-207e TripMate/public feature read API

**작업**: ADR-045 Phase 3 T-207e. TripMate와 사용자-facing 지도/상세/검색이 사용할
public feature read API를 admin OpenAPI에 연결.

- **In-bounds**: `GET /features/in-bounds` 추가. 기존 `GET /features` bbox raw 응답은
  admin frontend 호환용으로 유지하고, 새 endpoint는 `{data, meta}` envelope와
  `category` 반복 필터를 제공한다.
- **Detail**: `GET /features/{feature_id}`를 `{data, meta.duration_ms}` envelope로
  전환하고 `updated_at`을 포함했다. admin frontend 상세 fetch는 `body.data`를 읽도록
  갱신했다.
- **Batch**: `POST /tripmate/features/batch` 추가. `feature_ids` 1~200개를 받아
  soft-deleted feature를 제외한 상세 dict와 `missing` 목록을 반환한다.
- **Search**: `GET /features/search` 추가. `q` 또는 `bbox`를 필수 scope로 받고,
  `q`는 `pg_trgm` `%` 연산자와 transaction-local threshold를 사용한다. bbox 술어는
  `coord && ST_MakeEnvelope`만 사용한다.
- **Repo/OpenAPI**: `feature_repo.get_feature_rows_by_ids`,
  `feature_repo.search_features`를 추가하고 `packages/kor-travel-map-api/openapi.json`을
  재생성했다.
- **검증**: feature router + repo unit `22 passed`, PostGIS feature repo 통합
  `7 passed`, 통합 targeted `29 passed`, ruff, mypy targeted, OpenAPI `--check`,
  frontend ESLint/type-check 통과.
- **다음**: T-207g admin/user OpenAPI 이원화와 drift gate 갱신.

## 2026-06-03 (codex) — T-207d ops consistency/jobs/metrics API

**작업**: ADR-045 Phase 3 T-207d. 운영 화면과 admin UI polish가 공통으로 사용할
`/ops/*` 조회 API를 추가.

- **Ops repo**: `infra.ops_repo` 추가. `ops.import_jobs`,
  `ops.feature_consistency_reports`, `ops.data_integrity_violations`를 read-only raw SQL로
  조회하고 `created_at`/`started_at`/`detected_at` 기준 keyset cursor를 제공한다.
- **Metrics**: `GET /ops/metrics` 구현. feature/source/import job/dedup 상태 집계,
  dedup FP 통계, 열린 data integrity issue 집계, 최근 consistency report를 반환한다.
- **Jobs**: `GET /ops/import-jobs`, `GET /ops/import-jobs/{job_id}` 구현. Dagster
  worker와 feature update request가 남긴 `ops.import_jobs` 상태를 운영 UI가 직접 볼 수
  있게 했다.
- **Consistency**: `GET /ops/consistency/reports`,
  `GET /ops/consistency/issues` 구현. 기존 batch report(F1~F4)와 Phase 2 issue 큐를
  같은 ops namespace에서 조회한다.
- **OpenAPI**: `packages/kor-travel-map-api/openapi.json`을 재생성하고 계약 문서를
  갱신했다.
- **검증**: `/ops` 라우터 unit `5 passed`, PostGIS ops repo 통합 `3 passed`, ruff,
  mypy targeted 통과.
- **다음**: T-207e `/features/*` + `/tripmate/features/batch`.

## 2026-06-03 (codex) — T-207c admin features/dedup backend

**작업**: ADR-045 Phase 3 T-207c. 운영자가 feature를 검색/검토하고 비활성화, provider
재활성화 방지 override, dedup review 결정을 수행할 backend API를 추가.

- **Admin features**: `GET /admin/features` 구현. `q`, kind/category/status/provider/
  dataset_key, coord/issue 여부, issue type, updated range, sort/order, keyset cursor를
  지원하고 primary source와 열린 issue summary를 반환한다.
- **Deactivate + override**: `POST /admin/features/{feature_id}/deactivate` 구현.
  `status='inactive'` 전환, `ops.feature_overrides` active status override 생성,
  `prevent_provider_reactivation` 플래그를 추가했다.
- **Provider upsert 보호**: `feature_repo.upsert_feature`가 active status override가
  있는 feature의 status/deleted_at을 provider payload로 덮지 않도록 수정했다.
- **Dedup review**: `GET/PATCH /admin/dedup-review` 구현. accepted/rejected/ignored는
  queue status 전이, merged는 `dedup-merge:{review_id}` advisory lock 안에서 기존
  `feature_merge_history` merge path를 호출한다.
- **OpenAPI/DB**: `alembic 0010`으로 `ops.feature_overrides`를 추가하고
  `packages/kor-travel-map-api/openapi.json`을 갱신했다.
- **검증**: admin features/dedup 라우터 unit `8 passed`, PostGIS admin feature repo
  통합 `3 passed`, ruff, mypy, OpenAPI `--check` 통과.
- **후속**: 수동 feature 생성과 영구 삭제는 `ops.admin_audit_log` 설계 후 별도 작업.
  다음 작업은 T-207d `/ops/*` consistency/jobs/metrics.

## 2026-06-03 (codex) — T-208e Dagster feature update sensor

**작업**: ADR-045 Phase 4 T-208e. `ops.feature_update_requests` 큐를 kor-travel-map-owned
Dagster run으로 연결하는 polling sensor와 worker job을 추가.

- **Queue sensor**: `feature_update_request_queue_sensor` 추가. 15초 간격으로
  `AsyncKorTravelMapClient.peek_next_update_request()`를 호출해 다음 queued request를 상태
  변경 없이 확인하고, request id를 `RunRequest` config/tag에 싣는다.
- **Worker job**: `feature_update_request_worker` + `execute_feature_update_request` op
  추가. 기존 `AsyncKorTravelMapClient.execute_feature_update_request()`를 호출하며 실제
  provider refresh는 `feature_update_runner` resource가 담당한다.
- **Failure path**: executor가 request를 `failed`로 닫은 경우에도 Dagster run을
  `Failure`로 종료해 Dagster UI와 request/import job 상태가 같이 보이게 했다.
  `feature_update_request_failure_sensor`는 run tag의 request id를 기준으로
  `fail_update_request()`를 best-effort 호출하고 선택 notifier resource로 알림 payload를
  전달한다.
- **Client/repo**: sensor가 claim race를 만들지 않도록 `peek_next_update_request`를
  repo/client에 추가하고, failure sensor용 `fail_update_request` client 메서드를 추가했다.
- **Task 결정**: T-207b는 사용자 결정에 따라 구현하지 않음으로 닫고, T-207c/d/e는
  T-208e 이후 순서로 진행한다.
- **검증**: Dagster package unit `9 passed`, feature update repo/client PostGIS 통합
  `14 passed`, ruff, mypy 통과.

## 2026-06-03 (codex) — T-207f POI/cache target API

**작업**: ADR-045 Phase 3 T-207f. 외부 앱 POI를 `external_system + target_key`
정본 키로 등록/삭제하고, key 기준 주변 feature summary를 OpenAPI로 조회하는 backend
API를 추가.

- **Admin router**: `PUT/GET/DELETE /admin/poi-cache-targets/{external_system}/{target_key}`
  와 `GET /admin/poi-cache-targets` 구현. 같은 normalized 좌표 upsert는 idempotent,
  다른 좌표는 기본 409이고 `on_conflict='move'`에서 이동한다.
- **Nearby features**: `GET /features/nearby/by-target` 구현. target 기본 radius 또는
  query `radius_km`를 사용하고 `kind`, `category`, `status`, `provider`, `sort`,
  `cursor`, `page_size`를 지원한다.
- **PostGIS**: 주변 조회는 target/feature의 stored `coord_5179`에 직접
  `ST_DWithin`/`ST_Distance`를 적용한다. 공간 술어에 `ST_Transform`을 넣지 않았다.
- **OpenAPI**: `packages/kor-travel-map-api/openapi.json`을 재생성했다.
- **검증**: admin router unit `8 passed`, PostGIS nearby/cursor 통합 테스트
  `3 passed`, ruff/mypy 통과.
- **다음**: T-208e Dagster sensor가 `run_mode='now'`/queued request를 실제 실행기로
  연결한다.

## 2026-06-03 (codex) — T-207a feature update admin API

**작업**: ADR-045 Phase 3 T-207a. `kor-travel-map-admin`에 feature update request 운영
REST 라우터를 추가해 OpenAPI 기반 생성/조회/취소/재요청 표면을 연결.

- **Router**: `/admin/feature-update-requests` POST(dry-run/actual), GET(list),
  `/{request_id}` GET, `/{request_id}/cancel`, `/{request_id}/run-now` 구현.
- **Run-now**: 기존 request payload를 `run_mode='now'` 새 request로 재큐잉한다.
  provider runner 직접 실행은 API 레이어가 맡지 않고, T-208e 이후 Dagster sensor가
  queue에서 감지해 실행한다.
- **kor-travel-geo**: `sigungu_by_radius` scope는 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`이 있을
  때 REST v2 `/v2/regions/within-radius` resolver를 주입한다. 설정 누락은 503으로
  명확히 반환한다.
- **List filter**: `state`, `scope_type`, `provider`, `dataset_key`, 생성일 범위,
  keyset `cursor`/`page_size`를 지원한다.
- **OpenAPI**: `packages/kor-travel-map-api/openapi.json`을 재생성했다.
- **검증**: admin router unit `8 passed`, admin package 전체 `94 passed`,
  `tests/integration/test_feature_update_repo.py` 필터 통합 테스트 포함 targeted
  `17 passed`, ruff/mypy 통과.
- **다음**: T-207f `/admin/poi-cache-targets` + `/features/nearby/by-target`.

## 2026-06-03 (codex) — T-206d feature update request 실행 본체

**작업**: ADR-045 독립 프로그램화 후속 T-206d. `ops.feature_update_requests` queued
request를 실제 provider/dataset refresh 실행 계획으로 분해하고, runner 주입형 실행기로
request/import job 상태 전이와 POI target link 갱신을 연결.

- **Executor**: `infra.feature_update_executor` 신규. `build_feature_update_execution_plan`,
  `execute_next_feature_update_request`, `execute_feature_update_request`를 제공한다.
  provider API client/Dagster는 import하지 않고 `ProviderDatasetRefreshRunner`로 주입받는다.
- **Scope**: `scope.type='cache_target_keys'` resolver 추가. active
  `ops.poi_cache_targets` 주변 feature를 PostGIS `coord_5179`로 계산하고,
  missing/deleted/disabled key를 `matched_scope`에 기록한다.
- **Policy**: `ops.provider_refresh_policies`의 `enabled`, `source_kind`,
  `targeted_policy`와 target `provider_overrides`를 실행 계획에 적용한다. rate-limit
  값은 runner/Dagster resource가 provider 호출을 제한할 수 있도록 scope metadata로
  전달한다.
- **Target link**: 실행 성공 후 target 주변 feature를 다시 해석해
  `ops.poi_cache_target_feature_links`를 재계산하고, target
  `last_requested_at`/`last_refreshed_at`/`last_failed_at`을 갱신한다.
- **Client**: `AsyncKorTravelMapClient.execute_next_feature_update_request` /
  `execute_feature_update_request` 추가. T-207a admin run-now와 T-208e Dagster sensor가
  이 표면을 공유한다.
- **검증**: `tests/integration/test_feature_update_executor.py`와
  `test_scope_repo.py` target scope 테스트로 runner 기반 DB 적재, request/job `done`,
  target link/refresh 타임스탬프, `follow_system` skip을 확인했다.
- **다음**: T-207a `/admin/feature-update-requests` 라우터.

## 2026-06-03 (codex) — T-205c Phase 2 ops 스키마

**작업**: ADR-045 독립 프로그램화 후속 T-205c. request 실행 본체와 admin/Dagster
운영 화면이 필요한 Phase 2 ops 테이블을 PostGIS migration + ORM + raw SQL repo로
구현.

- **Schema**: `alembic 0009_phase2_ops_tables`로
  `ops.data_integrity_violations`, `ops.poi_cache_targets`,
  `ops.poi_cache_target_feature_links`, `ops.provider_refresh_policies` 추가.
- **Repo**: `integrity_violation_repo`, `poi_cache_target_repo`,
  `provider_refresh_policy_repo` 추가. 각 repo는 raw SQL `text()`만 사용하고 commit은
  호출자에게 맡긴다.
- **POI target**: `external_system + target_key` active unique key, generated
  `coord_5179`, move 시 기존 feature links 비활성화, soft delete 구현.
- **Integrity queue**: 주소/좌표/F5~F8 이슈 1건 = 1행으로 기록하고
  `open`/`acknowledged`/`resolved`/`ignored` 상태 전이를 지원.
- **검증**: targeted PostGIS integration
  `tests/integration/test_phase2_ops_schema.py tests/integration/test_phase2_ops_repos.py`
  → `8 passed`.
- **다음**: T-206d request 실행 본체에서 `cache_target_keys` scope와 provider
  refresh/rate-limit 정책 적용을 연결한다.

## 2026-06-03 (codex) — T-206a-geo 재검증

**작업**: ADR-045 T-206a-geo. 형제 repo `kor-travel-geo`의
`POST /v2/regions/within-radius` 구현과 optional 실제 PostGIS 테스트가 현재 main
기준으로 kor-travel-map 요구를 만족하는지 재확인.

- **Repo 상태**: `kor-travel-geo` main을 최신 `origin/main`으로 fast-forward.
  `/v2/regions/within-radius`, `AsyncAddressClient.regions_within_radius()`,
  `region_radius_parts` accelerator, `tests/integration/
  test_optional_real_postgres_regions.py`가 main에 존재함을 확인.
- **Targeted test**: WSL mirror에서
  `.venv/bin/python -m pytest tests/unit/test_v2_api.py tests/integration/
  test_optional_real_postgres_regions.py -q -s` → `15 passed, 1 skipped`.
  skip은 현재 shell에 `KOR_TRAVEL_GEO_TEST_PG_DSN`이 없어 optional 실제 DB 테스트가
  건너뛴 것이다.
- **Server smoke**: `http://127.0.0.1:12201/v2/regions/within-radius`에
  `{"lon":127.0,"lat":37.5,"radius_km":1,"levels":["sigungu"]}`를 POST해 `200 OK`,
  `sigungu[0].code="11650"`, `name="서초구"`, `relation="contains"` 응답 확인.
- **결론**: 추가 kor-travel-geo 코드 PR 없이 T-206a-geo는 이미 구현·노출·테스트 경로가
  준비된 상태다. kor-travel-map은 REST v2 계약과 resolver 주입 경계를 유지하고, 다음
  작업은 T-205c Phase 2 스키마다.

## 2026-06-03 (codex) — feature update client 표면

**작업**: ADR-045 독립 프로그램화 후속 T-206c. `infra.feature_update_repo`의 request
lifecycle을 `AsyncKorTravelMapClient` public Python 표면으로 노출해 admin API와 Dagster가
같은 transaction 경계를 사용하게 준비.

- **Client**: `enqueue_feature_update_request`, `get_update_request`,
  `list_update_requests`, `cancel_update_request`를 추가. dry-run은 DB row/import job을
  만들지 않고 preview만 반환하고, 실제 enqueue/cancel은 client가
  `session.begin()`으로 transaction을 소유한다.
- **Public export**: 문서에서 사용하던 `from kortravelmap import AsyncKorTravelMapClient`
  경로를 실제 top-level export로 맞췄다.
- **운영 경계 정정**: client/module 설명에서 TripMate 직접 import/ADR-003 함수 호출
  표현을 ADR-045 기준(OpenAPI 연동, client는 kor-travel-map API/Dagster 내부용)으로 정리.
- **검증**: PostGIS migrated DB에서 dry-run preview, enqueue, get/list, cancel
  lifecycle을 `tests/integration/test_client_orchestration.py`에 추가. smoke import는
  top-level client export를 확인한다.
- **문서 정정**: RustFS 로컬 표준 포트를 S3 API `12101`, console `12105`로 반영.
  `.env.example`, README, AGENTS/SKILL, object store/RustFS/배포/runbook 문서의
  9000/9001 예시를 정리했다.
- **다음 순서 조정**: T-206c 다음에는 형제 repo `kor-travel-geo`의
  T-206a-geo(`/v2/regions/within-radius`)를 재검증/보완하고, 그 뒤 T-205c Phase 2
  스키마와 T-206d 실행 본체로 진행한다.

## 2026-06-03 (codex) — feature update request 큐 repository

**작업**: ADR-045 독립 프로그램화 후속 T-206b. `ops.feature_update_requests` row를
`ops.import_jobs`와 연결해 Dagster/admin API가 공유할 request lifecycle repository를
추가.

- **Repository**: `infra/feature_update_repo.py` 신규. `enqueue_feature_update_request`,
  `claim_next_update_request`, `start_update_request`, `finish_update_request`,
  `cancel_update_request`, `get_update_request`, `list_update_requests`를 제공한다.
- **Dry-run**: `dry_run=True`는 `scope_repo.count_features_matching_scope`로
  `matched_scope`만 계산하고 DB row/import job을 만들지 않는
  `FeatureUpdateRequestPreview`를 반환한다.
- **큐 전이**: 실제 enqueue는 `ops.import_jobs(kind='feature_update_request')`와
  `ops.feature_update_requests`를 같은 transaction에 생성한다. claim은
  `priority DESC, created_at ASC` + `FOR UPDATE SKIP LOCKED` + advisory lock으로
  running 전이하고, start/finish/cancel은 연결 import job 상태도 함께 갱신한다.
- **목록 조회**: D-10 결정대로 `created_at DESC, request_id DESC` keyset cursor를
  base64 opaque cursor로 구현했다.
- **검증**: PostGIS migrated DB에서 dry-run 무쓰기, enqueue FK/payload, priority
  claim/import job running 전이, advisory lock 점유 시 claim skip, start/finish/cancel,
  keyset pagination, 잘못된 cursor 예외를 통합 테스트로 확인.
- **문서 정정**: kor-travel-geo REST API 로컬 포트 기준을 `http://127.0.0.1:12201`로
  정정했다. README/SKILL/AGENTS/환경 예시/스크립트/현재 참조 문서/CLI help/live test
  기본값에서 이전 `8888` 표기를 제거.

## 2026-06-03 (codex) — feature update scope resolver

**작업**: ADR-045 독립 프로그램화 후속 T-206a. Feature update request의 dry-run과
후속 queue bridge가 사용할 scope resolver를 추가.

- **Resolver**: `infra/scope_repo.py` 신규. `feature_ids`, `center_radius`, `bbox`,
  `sigungu_by_radius`, `provider_dataset` scope를 `ScopeResolution`으로 해석하고
  `matched_scope` JSON payload를 생성.
- **공간 쿼리**: `center_radius`는 입력 좌표를 CTE에서 한 번만 EPSG:5179로 변환한 뒤
  `coord_5179`에 `ST_DWithin`을 적용한다(ADR-012). bbox는 `coord && ST_MakeEnvelope`
  패턴을 따른다.
- **kor-travel-geo 경계**: `sigungu_by_radius`는 `infra`가 kor-travel-geo/http client를 직접
  import하지 않고, 호출자가 주입한 async resolver의 5자리 `sigungu_code` 결과만
  사용한다. 실제 REST 호출은 `kortravelmap.geocoding.resolve_sigungu_by_radius` 또는
  admin/Dagster resource 책임.
- **범위 제외**: `cache_target_keys`는 `ops.poi_cache_targets` 테이블이 필요한 Phase 2로
  남긴다.
- **검증**: 실제 PostGIS migrated DB에서 FeatureBundle 적재 후 feature id 필터,
  반경, bbox, provider/dataset, 주입 resolver 기반 시군구 scope를 통합 테스트로 확인.

## 2026-06-03 (codex) — feature update request 스키마

**작업**: ADR-045 독립 프로그램화 후속 T-205a. OpenAPI/admin UI가 만드는 feature
update request를 Dagster/import job과 연결하기 위한 `ops.feature_update_requests`
테이블 기반을 추가.

- **DB**: Alembic `0008_feature_update_requests` 추가. `scope_type` 6종,
  `run_mode`(`queued`/`now`), 상태 5종 CHECK, JSONB 기본값, `job_id`
  `ON DELETE SET NULL`, state/priority/created/job 인덱스를 반영.
- **ORM**: `FeatureUpdateRequestRow`를 `infra.models`와 `infra.__init__` export에
  추가. ORM은 매핑만 유지하고 enqueue/claim 로직은 T-206b로 분리.
- **검증**: PostGIS migrated DB에서 defaults/FK/CHECK/index 계약을 검증하는
  통합 테스트 추가.
- **문서**: `openapi-admin-contract.md`, `data-model.md`, `postgres-schema.md`,
  `tasks.md`, `resume.md`를 T-205a 상태로 갱신. `sigungu_by_radius` 설명은
  kor-travel-map 내부 경계 테이블 fallback이 아니라 kor-travel-geo REST v2
  `/v2/regions/within-radius` 호출 기준으로 정리.

## 2026-06-02 (codex) — Docker Dagster 내부 URL 분리

**작업**: PR#157 머지 후 Docker stack 기동 검증 중 API 컨테이너의
`/ops/dagster/summary`가 `unavailable`을 반환하는 문제를 확인하고 수정.

- **원인**: `.env`의 로컬 `KOR_TRAVEL_MAP_API_DAGSTER_URL=http://127.0.0.1:12302`이
  compose interpolation에 그대로 사용되어 API 컨테이너 안에서 자기 자신을 조회.
- **수정**: Docker compose는 `KOR_TRAVEL_MAP_DOCKER_API_DAGSTER_URL`을 읽어 API 컨테이너
  내부 `KOR_TRAVEL_MAP_API_DAGSTER_URL`로 주입. 기본값은 `http://dagster:12302`.
- **문서**: Docker runbook, debug UI env 표, `.env.example`에 로컬/public URL과
  Docker 내부 URL의 분리 원칙 추가.

## 2026-06-02 (codex) — admin UI Dagster 운영 화면

**작업**: 사용자 지시 — admin UI를 최신 문서의 ADR-045 독립 Dagster 운영 모델에 맞춰
보강하고, Dagster 관리 화면 embed와 자체 요약 UI를 추가.

- **Backend**: `GET /ops/dagster/summary` 추가. `KOR_TRAVEL_MAP_API_DAGSTER_URL`
  기준 Dagster GraphQL에서 version, repository/code location, asset group,
  schedule/sensor, 최근 run을 읽어 `DagsterSummaryResponse`로 정규화. summary 성공 시
  embedded Dagster 화면의 첫 실행 모달을 접기 위해 `setNuxSeen`을 best-effort 호출.
- **Frontend**: `/admin/dagster` 추가. 좌측은 admin 자체 요약 카드, code location/
  asset group, recent run 표를 렌더하고 우측은 Dagster webserver를 iframe으로 embed.
- **홈 보강**: `/`에서 Dagster 상태 요약과 `/admin/dagster` 진입 링크를 표시.
- **운영 설정**: 로컬 스크립트는 `http://127.0.0.1:12302`, Docker API 컨테이너는
  `http://dagster:12302`를 기본 Dagster URL로 사용. embedded 관리 화면의 첫 실행
  telemetry 안내를 피하기 위해 `DAGSTER_DISABLE_TELEMETRY=yes`와 `dagster.yaml`
  `telemetry.enabled: false` 기본 생성을 추가.
- **검증**: Dagster router unit test, admin backend 전체 pytest, ruff,
  `mypy --strict -p kortravelmap.api`, frontend type-check/lint/build 통과. OpenAPI
  JSON 갱신. Windows Playwright e2e(`dagster.spec.ts`, `home.spec.ts`) 6개 통과.
  데스크톱/모바일 스크린샷으로 Dagster embed 렌더와 NUX 모달 제거 확인. React Doctor는
  신규 경고를 해소했으며, 남은 optional warning은 기존 shadcn/base-ui primitive 구조
  경고와 iframe `sandbox` 속성 false-positive.

## 2026-06-02 (codex) — Docker/포트 표준화

**작업**: 사용자 지시 — API `12301`, admin UI `12305`, Dagster `12302` 고정 포트 원칙을
코드/문서/스크립트/Docker에 반영하고, `.env`의 서비스 키를 실행 환경변수로 주입.

- **포트 표준화**: `ApiSettings.port`, CORS origin, frontend `dev/start`,
  Playwright 기본 baseURL, frontend API client fallback을 `12301`/`12305` 기준으로 수정.
- **Docker**: `docker-compose.yml`, `docker/api.Dockerfile`,
  `docker/frontend.Dockerfile`, `docker/dagster.Dockerfile`, `.dockerignore` 추가.
  compose는 PostGIS + API + frontend + Dagster 1차 구성을 제공하고 API 기동 전
  `alembic upgrade head`를 실행.
- **스크립트**: `scripts/load-env.sh`가 `.env`의 provider key를
  `KOR_TRAVEL_MAP_API_*`/`NEXT_PUBLIC_*`로 매핑. `stop-fixed-ports.sh`,
  `run-admin-stack.sh`, `docker-build.sh`, `docker-up.sh` 추가.
- **문서**: ADR-047, Docker runbook, 배포 메모, tasks/resume/changelog와 현재 운영
  문서의 포트 기준 갱신.
- **검증**: admin router pytest, ruff, mypy, frontend type/lint, `docker compose config`,
  Docker image build 3종, compose 기동 스모크(API `12301`, frontend `12305`, Dagster
  `12302`) 통과.

## 2026-06-02 (codex) — kor-travel-map Dagster Feature ETL 1차 구현

**작업**: 사용자 지시 — TripMate 구현을 참고하지 않고 kor-travel-map 자체 Dagster로
feature update/ETL을 관리하도록 1차 code location과 검증 경로 구현.

- **Dagster 패키지**: `packages/kor-travel-map-dagster/` 신설. `dagster dev -m
  kortravelmap.dagster.definitions` 진입점과 Feature 적재 asset 9종을 등록. 메인
  `kortravelmap` 패키지는 Dagster import 없음.
- **ETL 흐름**: provider API wrapper를 새로 만들지 않고, Dagster resource가 제공한
  provider record iterable을 기존 변환 함수(`cultural_festivals_to_bundles`,
  `stations_to_bundles`, `rest_areas_to_bundles`, `traffic_notices_to_bundles`,
  `heritage_*_to_bundles`, `license_records_to_bundles`,
  `knps_*_records_to_bundles`)에 전달. 이후 주소/좌표 검증을 거쳐
  `AsyncKorTravelMapClient.load_feature_bundles`로 PostGIS 적재.
- **주소/좌표 검증**: 좌표가 있는 bundle은 kor-travel-geo reverse 결과의 `bjd_code`가
  있어야 하며, provider 주소 문자열과 reverse 행정구역명이 다르면 적재 전 실패.
- **검증 추가**: Dagster definitions smoke/unit test와 실제 PostGIS 통합 테스트
  추가. 통합 테스트는 9개 asset runner를 Dagster context로 실행하고 feature/source
  9건 커밋, `coord_5179` SRID, `legal_dong_code`/`sigungu_code` 적재를 확인.
- **CI**: `kor-travel-map-dagster` editable install, package unit pytest, ruff/mypy 대상에
  Dagster 패키지 추가.

## 2026-06-02 (codex) — kor-travel-geo `/v2/regions/within-radius` 재정합

**작업**: 사용자 지시 — kor-travel-geo repo의 최신 REST v2 계약을 다시 확인하고,
kor-travel-map geocoding client를 실제 구현된 `/v2/regions/within-radius`에 맞춰 보정.
Sprint 기준 이미 테스트된 geocoding 표면만 수정.

- **kor-travel-geo 확인**: `kor-travel-geo` `origin/main`의
  `src/kraddr/geo/api/routers/v2.py`, `dto/v2.py`, `client.py`,
  `tests/integration/test_optional_real_postgres_regions.py`를 기준으로 endpoint와
  DTO를 재확인. `RegionWithinRadiusLevel=("sido","sigungu","emd")`,
  `relation=("contains","overlaps")`가 정본.
- **kor-travel-map 보정**: `KorTravelGeoRestClient.regions_within_radius`,
  `resolve_regions_within_radius`, `resolve_sigungu_by_radius`를 최신 계약에 맞추고,
  `RegionV2.sig_cd`/`eup_myeon_dong` 파싱과 bjd 누락 시 `sigungu_code` fallback을
  추가.
- **실데이터 확인**: 로컬 kor-travel-geo REST `http://127.0.0.1:12201` +
  T-027 최종 적재 DB(`tl_scco_ctprvn=17`, `tl_scco_sig=255`, `tl_scco_emd=5067`)
  기준 `POST /v2/regions/within-radius`가 HTTP 200. 샘플
  `(lon=126.978, lat=37.5665, radius_km=3.0, levels=sigungu+emd)`에서
  `sigungu` 6건, `emd` 190건을 반환했고, kor-travel-map parser/helper도 같은 응답을
  정상 파싱.
- **검증**: `pytest tests/unit/test_geocoding.py -q -s` 51 passed,
  `pytest tests/unit -q -s` 744 passed, `ruff check .`, `mypy src/kortravelmap`,
  `lint-imports` 통과.

## 2026-06-02 (codex) — admin frontend stack 전환 + geocoding admin 표면 제거

**작업**: 사용자 지시 — frontend를 문서화된 stack(Next.js 16 + React 19 +
TanStack Query + Zustand + Zod + React Hook Form + shadcn/ui +
`maplibre-vworld-js`)으로 전환하고, geocoding 전용 내용은 kor-travel-geo 프로젝트에서만
보도록 kor-travel-map-admin 표면을 정리.

- **Frontend**: shadcn/ui component registry(`components.json`, `src/components/ui/*`,
  `globals.css`)를 추가하고 홈/ETL preview/Feature 지도 화면을 새 stack 기준으로
  재구성. ETL form은 React Hook Form + Zod, API state는 TanStack Query, map/view
  상태는 Zustand, Feature 지도는 `maplibre-vworld-js` + `@kor-travel-map/map-marker-react`.
- **Geocoding 경계**: kor-travel-map-admin의 `/debug/geocoding/*` router, frontend
  `/geocoding` 화면, geocoding 전용 e2e/router/live 테스트 제거. 메인
  `kortravelmap.geocoding` client와 provider 주소 보강 문서는 유지.
- **React Doctor**: `doctor` script + `doctor.config.json` 추가. MapLibre listener
  cleanup, page metadata wrapper, `toSorted`, padding 정리, `FieldError` stable key를
  반영. 잔여 optional warning은 shadcn 생성 컴포넌트 구조 관련.
- **실행 위치 문서화**: frontend dev/prod 서버는 WSL에서 실행하고, Windows는
  Playwright e2e 검증용 Chromium 실행에만 사용한다고 README/dev-environment에 명시.
  `which node`/`which npm`이 `/mnt/c/Program Files/nodejs/...`로 잡히면 안 되며,
  WSL nvm Node를 활성화해야 한다는 체크도 추가.
- **검증**: frontend `type-check` / `lint` / `build` 통과, React Doctor error 0
  (optional warning 6), admin OpenAPI drift check 통과, admin pytest
  `83 passed`(`--capture=no`, NTFS capture tmpfile 회피), ruff clean. Windows
  Playwright e2e는 WSL backend `0.0.0.0:8087` + WSL frontend
  `0.0.0.0:8610` production `next start` 기준 `11 passed`.
- **회고 보강**: 본 세션에서 반복된 CLI/환경 실수(Windows npm PATH 혼입,
  Linux optional native dependency 누락, `0.0.0.0` 실행 파라미터, unquoted
  `env PATH`, workspace binary 위치, `.next/dev/lock`, broad `pkill -f`,
  검증 없이 Ready 로그만 신뢰, Windows stale Node `:8610` 점유로 Playwright가
  WSL 서버 대신 오래된 Windows 서버를 보는 문제)를
  `docs/runbooks/agent-failure-patterns.md` §F와 `docs/dev-environment.md` §8.2,
  frontend README 체크리스트로 문서화.

