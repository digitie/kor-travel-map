# ADR-048: REST API versioning을 admin/ops까지 확장하고 envelope·pagination·parameter·response 정합성 표준을 고정한다 (T-214/T-215 위에 보강)

- **상태**: accepted
- **날짜**: 2026-06-09
- **결정자**: 사용자
- **관련**: ADR-005(인증=인프라), ADR-035(namespace), ADR-044(provider 충실),
  ADR-045(TripMate OpenAPI 연동), ADR-046(무-shim),
  `docs/architecture/tripmate-rest-api.md`(#317, 외부 `/v1` 정본), `docs/architecture/rest-api.md`(전 표면 보강),
  `docs/reports/api-endpoint-review-2026-06-08.md`(검토 근거), T-214/T-215(#317)

### 컨텍스트

PR #317(T-214/T-215)이 REST API `/v1` 정리의 1차를 이미 끝냈다 — `docs/architecture/tripmate-rest-api.md`를
외부 `/v1` 목표 계약으로 재작성, `/tripmate/feature-update-requests*` alias 제거(admin
단일화), place/event **단건 feature 추가·수정·삭제 admin API**(K-15 해소) + version 0(provider)/
1(user) 분리(`feature.feature_versions`/`ops.feature_change_requests`/
`KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE`). 보안 스킴(P1-B)은 #314로 이미 해소.

`docs/reports/api-endpoint-review-2026-06-08.md` findings를 **전부** 닫으려면 #317 범위 밖의
두 가지가 남는다. (1) #317 T-214b는 **`/admin`·`/ops`·`/debug`를 비버저닝으로 고정**했는데,
사용자는 **admin 표면도 versioning**하라고 지시했다. (2) envelope/pagination/parameter/
response의 **코드 실측 불일치**(라우터별 `*Meta` 중복, page-size 파라미터 3종·캡 3종,
bbox 인코딩 2종, `status`↔`state`, 응답 `*_key`↔`*_id`)가 #317의 고수준 정리 아래에 남아
있다. 본 ADR은 #317 위에 이 두 가지를 보강한다.

### 결정 (#317 위의 delta)

1. **versioning을 전 표면으로 확장.** #317 T-214b/§2.1의 "`/admin`·`/ops`·`/debug` 비버저닝"을
   **supersede**하여 `/v1/admin/*`·`/v1/ops/*`·`/v1/debug/*`도 `/v1` 아래 둔다(사용자 지시).
   liveness `/health`·`/version`만 비버저닝 유지. 외부 표면(`/v1/features`(batch 포함)·
   `/v1/categories`·`/v1/providers`)은 #317 T-214b/d가 진행 중인 그대로. **`/tripmate/*`
   namespace는 제거**(kor-travel-map은 TripMate 전용이 아니다; batch → `/v1/features/batch`).
2. **envelope 공유 모델 — payload와 메타 완전 분리.** 라우터별 `*Meta` 중복을 공유
   `Meta`로 통합한다. `data`는 **payload만**(단건=객체, 목록=`{items:[...]}`, in-bounds=
   `{clusters,items}`, batch=`{found:{feature_id:Feature},missing:[...]}`). **`items`는 list array
   전용**이고 id-keyed map은 `found`처럼 별도 키를 쓴다. **페이지네이션·추적·뷰 해석 메타는
   `meta`로 모은다**: `meta = { duration_ms, request_id, page?: { page_size, next_cursor, total },
   cluster?: { cluster_unit } }`(`page`는 pageable 목록에만, `total`은 opt-in null 기본,
   `cluster`는 in-bounds에만). 즉 `data.next_cursor`/`data.total_count`/`data.cluster_unit`/
   파생 `count`를 **폐기**하고 `meta.page`/`meta.cluster`로 일원화한다(payload=데이터,
   meta=cross-cutting → 확장 시 meta만 늘리면 됨). 성공 응답에도 `request_id`를 실어 오류
   envelope와 대칭.
3. **pagination 단일화(T-214e 심화).** page-size 파라미터를 `page_size`로 통일
   (`limit`/`run_limit`/`event_limit` 폐기), 2-티어 캡(기본 50/200, 지도 nearby 100/500),
   opaque `cursor`. `/v1/features` 평면은 keyset cursor(현재 `limit le=5000` 폐기),
   `/v1/features/in-bounds`는 cursor 없이 `max_items` 하드캡 5000→2000 + 결정적 `feature_id`
   정렬(T-212d). `total`은 `?include_total=true` opt-in(현재 `search`는 항상 COUNT).
4. **parameter 일관성(T-214e 심화).** bbox는 분리 float 4개로 통일(`search` CSV `bbox`
   제거, clean cut). 다중값 필터는 단수 반복(`kind`/`category`/`provider`/`status`). lifecycle 상태
   필드는 `status`로 통일(`import-jobs`/`offline-uploads`/`feature-update-requests`의 `state`
   개명; `severity` 별개 축 유지). issue/violation noun은 외부 표면에서 `issue_*`로 통일.
5. **에러 problem+json(T-214g 보강).** `{error:{…}}`를 RFC 7807 `application/problem+json`
   (`type`/`title`/`status`/`detail` + 확장 `code`/`request_id`/`errors[]`)으로 발전.
   `code`·`request_id`는 problem+json 객체의 **top-level 확장 멤버**로 두고(소비자 파싱 위치
   고정), 코드 enum(`FEATURE_NOT_FOUND`/`INVALID_BBOX`/`TOO_MANY_IDS`/`VALIDATION_ERROR`/
   `RATE_LIMITED`/`LOCK_BUSY`/`DESTRUCTIVE_DISABLED`/`UNAUTHORIZED`/`UPSTREAM_UNAVAILABLE`)을
   확장 `code`로 유지한다.
6. **응답 식별자 접미사 규약 — 의미(본질) 기준 전면 적용.** 호환성/외부 동결 같은 동기는
   두지 않고 **의미**로만 정한다: 시스템 단일 surrogate = `*_id`, **복합/자연키 = `*_key`**.
   응답 본문 전체(외부 read 포함)에 적용 — surrogate인 `review_id`→`review_id`,
   `issue_id`→`issue_id`, `system_log_id`/`api_call_log_id`/`override_id`/`step_id`→
   `*_id`. **`*_key` 유지는 본질이 자연/복합키인 것**: **`cluster_key`(행정구역 코드 sido/
   sigungu/eupmyeondong = 자연키 → 유지, #316 재리뷰 C; 2차의 `cluster_id` 개명을 철회)**,
   복합 자연키 `target_key`(+`external_system`), provider/source 어휘(ADR-044), canonical
   `feature_id`. `lon`/`lat`/`name`/`category`/`marker_*`/`status`는 이미 일관 → 불변.
7. **명명 통일을 코드/DB 레벨까지 전파.** REST 단 개명을 영구 edge 매핑으로 두면 ADR-046
   (무-shim)과 어긋나므로, **surrogate 식별자/상태를 물리 컬럼·ORM 속성·repo 함수/변수까지
   end-to-end 정렬**(테이블별 1-PR migration, codegraph impact 선행). 대상: `review_id`→
   `review_id`, `issue_id`→`issue_id`, ops 로그/내부 키 `*_key`→`*_id`, `state`→`status`.
   **경계(개명 금지 — 자연/복합/provider/canonical)**: `cluster_key`(행정코드 자연키),
   `target_key`(+`external_system`), provider/source 어휘(ADR-044 — `dataset_key`/
   `source_record_key`/`source_entity_id`/`source_dataset_key`/`raw_*`), canonical `feature_id`.
8. **action sub-resource 규약(확장성).** 부수효과 있는 상태 전이(Dagster 트리거/snapshot/
   lock/승인·거절)는 `POST {collection}/{id}/{verb}`(`deactivate`/`cancel`/`run-now`/`approve`/
   `reject`/`load`/`validate`/`swap`), 순수 필드 수정은 `PATCH {id}`, 생성은 `POST {collection}`,
   조회는 `GET`. 이 규약을 계약에 명시해 신규 action도 같은 형태로 확장한다.
9. **정본 관계 — 단일 전 표면 정본으로 수렴.** drift 회피를 위해 **`docs/architecture/rest-api.md`를 전
   표면(외부+admin/ops) 계약 단일 정본**으로 두고, `docs/architecture/tripmate-rest-api.md`는 TripMate
   **소비 매핑 view**로 축소(계약 세부는 rest-api.md로 위임). 기계 정본 =
   `openapi.json`/`openapi.user.json`. 충돌 시 OpenAPI 우선. (수렴은 T-216g.)
10. **좌표 필드명 cross-repo 정렬 = `lon`/`lat`(#316 재리뷰 B).** TripMate 정본(DEC-07)은
    `longitude`/`latitude`지만, krtour는 `lon`/`lat`로 이미 일관하고 대용량 지도 feature
    payload에 terse가 바이트·파싱에 유리하다. **krtour 정본 = `lon`/`lat` 유지**, TripMate가
    DEC-07을 `lon`/`lat`로 하향 정렬해 **경계 매핑 0**으로 만든다.
11. **`feature_id` 값 불변식(#316 재리뷰 D — 안정성 최우선).** 외부 `feature_id` **값**은
    provider 재적재·사용자 편집(#317 v0/v1)·버전 승급·soft delete에도 **절대 바뀌지 않는다**.
    정체성이 바뀌는 사건(bjd 변경 등)은 **id 변경이 아니라 새 feature + link**로 모델링한다.
    이름 동결(#6)과 **별개로 값 불변**을 외부 계약에 명문화한다(소비자가 FK·snapshot 키로 영속).
12. **envelope 불변식(#316 재리뷰 E).** `meta`는 **모든 응답에 항상 present**(단건 GET 포함)
    하고, 모든 응답(성공 `meta` 또는 problem+json)은 `request_id`를 싣는다. `meta.page.next_cursor`
    는 **항상 키로 존재**하고 소진 시 `null`(omit 금지) — 페이지 종료 신호를 계약으로 lock.
13. **`/vN` major 거버넌스(#316 재리뷰 F).** hard cutover 하에서 `/v1`→`/v2`가 유일한 breaking
    수단이므로 규칙을 둔다: **pre-1.0(현재)** = `/v1` 가변, in-place breaking 허용(지금 정리
    방침과 일치). **v1.0.0 GA에서 `/v1` 동결**, 이후 breaking = `/v2` + N-1 동시지원. OpenAPI는
    major별 분리 export.
14. **Base URL과 path 분리(#316 추가 리뷰).** 환경변수 base URL은 host root까지만 포함하고
    `/v1`는 path에 둔다(예: base `http://127.0.0.1:12701` + path `/v1/features/search`).
    base와 path 양쪽에 `/v1`를 중복 삽입하지 않는다.

### 근거

- 사용자가 admin 표면 versioning을 명시 지시 — breaking 분리 수단을 운영 표면에도 둔다.
- 코드 실측 불일치(파라미터 3종·캡 3종·`*Meta` 중복·`total_count` 항상 COUNT)는 #317의
  고수준 정리만으로는 닫히지 않으며, 공유 모델·opt-in count로 예측가능성·비용을 개선한다.
- 내부 어휘를 물리 레벨까지 정렬하면 영구 매핑 shim을 피한다(ADR-046). provider/복합키 경계는
  ADR-044로 보존.

### 결과 (긍정)

- 외부+내부 전 표면이 버전·envelope·pagination·error·명명 규약을 공유한다.
- `*Meta` 통합 + `request_id` 전파로 응답 셰입을 한 곳에서 진화시키고 상관추적을 일관화.

### 결과 (부정)

- admin/ops도 `/v1`로 이동 — #317이 비버저닝으로 둔 결정을 되돌려 라우터 mount·OpenAPI
  export·frontend·docs를 admin/ops까지 일괄 갱신해야 한다.
- 내부 식별자 물리 개명은 테이블별 migration + 큰 mechanical churn(`review_id` 291·
  `issue_id` 118건)을 동반 — codegraph impact 후 단계화.
- **무-호환 clean cut**: envelope 재배치(`data.next_cursor`→`meta.page`)·파라미터/필드 개명·
  좌표명 정렬(`lon`/`lat`)·구 경로 제거가 소비자(TripMate)를 한 번에 깬다. pre-prod 단계라
  의도적으로 수용 — 안정 spec commit에서 소비자가 lockstep으로 추종한다(T-181).

### 전환 정책 — 무-호환 clean cut (#316 2차 리뷰, 사용자 지시)

사용자 지시 = **호환성은 고려하지 않는다. 늦기 전에 일관성·확장성·안정성으로 한 번에
정리한다.** TripMate는 pre-production 소비자이므로 최신 spec을 따라오면 된다.

- **dual-support/deprecation 창 없음**: 구 unprefixed 경로·호환 alias를 유지하지 않고 `/v1`로
  **즉시 단일 전환**한다(이중 코드경로 제거 = 안정성). `/debug/health`·`/debug/version`은
  deprecate가 아니라 **제거**(→ `/health`·`/version`·`/v1/ops/health-deep`로 수렴).
- **개명도 즉시 전면 적용(의미 기준)**: 명명 규칙을 외부 read 포함 한 번에 적용(#6·#7).
  단 `cluster_key`(행정코드 자연키)는 규칙상 `*_key`가 맞아 **유지**(동결이 아니라 본질).
  `longitude`/`latitude`↔`lon`/`lat` cross-repo 정렬도 이 컷에서 처리(#10).
- **기계 정본 + codegen pin**: `openapi.json`/`openapi.user.json`을 기계 정본으로 유지하고,
  `/v1` 안정 commit에서 소비자(T-210e codegen + 계약 테스트)가 그 spec에 핀한다. 이게
  유일한 "안전판"이며, 별도 호환 창은 두지 않는다.
- **에러 `code` 고정**: problem+json top-level 확장 `code`/`request_id` + enum(#5).
- **Base URL은 host root**: `/v1`는 path에만 둔다(#14).

### 후속

- 실행은 `docs/tasks.md` **Phase 6.8 / T-216a~g**로 분해(#317의 T-214/T-215와 별도 번호).
  `docs/architecture/tripmate-rest-api.md` §2.1의 "admin/ops 비버저닝" 문구는 본 ADR로 갱신했다.
- **반영 순서**: 외부+admin `/v1` clean cut(T-216a/b) → 명명·코드/DB 전파(T-216e/f) →
  정본 수렴(T-216g). API shape `/v1` 안정 commit에서 T-210e(codegen) 진행. 소비자(TripMate)는
  안정 spec commit 기준으로 base/에러파싱/파라미터/필드명을 일괄 갱신한다.
