# journal-2026-08b.md — journal.md 아카이브 (2026-08-01 ~ 2026-08-14)

> `docs/journal.md`에서 2026-08-31 분리(규약 §8). 읽기 전용 이력.

## 2026-08-14 — T-VN-40C: PinVi cutover mapping export를 Map service 경계로 분리

PinVi의 기존 plan/POI가 가진 legacy `curated_feature_id`는 Map의 canonical
`collection_id`/`curation_item_id`와 별도 DB에 있어, 관계를 물리 제거하기 전에 직접 조회
없이 전달할 immutable 증거가 필요하다. Map service에 maintenance-only
`GET /v1/service/curation-cutover/identity-mappings`를 추가했다. 응답은 legacy UUID 순서의
signed keyset, 각 row의 `source_row_hash`, 전체 count와 NFC/UUID framed Merkle root를 함께
돌려준다. cursor가 다른 root/count에 재사용되면 409로 fail-close한다.

snapshot consumer token과 mapping export token은 서로 다른 SHA-256 digest를 써야 하며,
한 scope의 token을 다른 route에 쓰면 403이다. runtime DB role은 mapping relation의 SELECT만
가지고 INSERT/UPDATE/DELETE/TRUNCATE는 계속 없다. 다음 PinVi 단계는 이 OpenAPI를 vendor하고
mapping receipt를 먼저 고정한 다음, 기존 provenance를 1:1 backfill하는 것이다.
## 2026-08-14 — geo 소비자 키가 VWorld 키로 떨어지는 통로 제거 (T-VN-H46B/C)

`kor-travel-geo`에는 성격이 다른 자격증명 두 개가 있다. **VWorld 키**는 geo가 상류
VWorld로 나갈 때 쓰고, **geo public API key**는 소비자가 geo에 인증할 때 쓴다. geo는
VWorld 키를 `401 E0401`로 거절한다. 이름이 비슷해서 설정 사슬이 반복적으로 둘을 이어
왔고, 그때마다 조용히 실패했다.

**prod 장애 실측**: 08-13에 `.env`의 geo 키를 올바른 값으로 고치고 **api만** 재생성해
dagster/daemon 두 컨테이너가 VWorld 키를 든 채 남았다. fail-open이 아니다 —
`preflight()`는 존재·길이만 보므로 리소스 초기화는 통과하고, 첫 요청에서
`GeoAuthNotConfiguredError`가 나며 삼키는 except가 없어 asset step이 통째로 죽는다.
`reverse_geocoder`는 사실상 모든 feature asset의 필수 리소스다. 안 터진 이유는 무결이
아니라 미실행이었다(ETL이 08-07 이후 미가동). 컨테이너 재생성으로 복구했고 세
컨테이너 전부 `POST /v2/reverse` HTTP 200을 확인했다.

**통로는 5곳이 아니라 7곳이었다.** 첫 판은 5곳을 닫고 "다 닫았다"고 적었는데, 적대
리뷰가 `docker-compose.yml`의 프론트 build args·environment 두 줄과
`run-admin-feature-clone-live-acceptance.sh`의 **무조건 대입**(폴백보다 나쁘다)을 찾아냈다.

**더 나쁜 것은 가드가 그 상태에서 초록이었다는 점이다.** 첫 판 가드는
`KOR_TRAVEL_MAP_…` 이름 하나만 앵커로 잡고 `expected=3`으로 개수를 못박았다. 좁은
앵커의 개수를 고정하니 "다 찾았다"는 착시까지 만들었다 — 이 저장소가 반복해서 당한
바로 그 구조다. 대상 이름 전부를 훑고 개수는 고정하지 않도록 다시 썼다. 대입식의
우변만 잘라 내므로 `unset A B`나 `--build-arg` 목록이 이어쓰기로 합쳐지는 경우에
오탐하지 않는다. 변조 시험: 수정 전 6개 파일 판에서 8/8 검출, 현행에서 8/8 통과.

**폴백을 없앤 자리에 올바른 경로를 넣었다.** `load-env.sh`가
`NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`를 아무것도 없는 데서 채우지 않게 되어,
`.env.example` 대로 `KOR_TRAVEL_MAP_…`만 설정한 개발자의 admin UI가 영구히 키를 잃을
뻔했다. 두 이름은 같은 자격증명의 별칭이므로 양방향으로 채운다.

**빈 키의 실패 모드도 고쳤다.** geo는 키가 없으면 401이 아니라 400 `E0100 field=key`를
돌려주는데, 프록시가 그대로 흘려보내면 화면에 "invalid request data"로 보여 자격증명
누락이 아니라 요청 형식 오류처럼 읽힌다. 명시적 503 + 사유 코드로 단락시킨다.

가드가 **못 하는 것**도 문서에 적었다: 중간 변수 우회, 운영자 `.env` 파일 자체(**08-13
사고의 실제 원인이 그 축이라 이 가드는 그 사고를 막지 못했을 것이다**),
docker-manager의 compose.
## 2026-08-14 — alembic squash(0200) + prod 지오코딩 복구

T-VN-36 PR #973이 `c76ceb7a`로 병합된 최신 `main` 위에 T-VN-40 설계 커밋만
재배치했다. ADR-092는 source-rule 자동 결과를 admin-only 후보 lifecycle로,
공식·수동 공개 membership을 `curation_collections/items`의 단일 정본으로 분리한다.
사용자 승인에 따라 A/B/C는 하나의 forward-only implementation PR/release로 이어서 구현한다.
상세 설계는 candidate stable identity `(rule_id, source_entity_key, feature_id)`, immutable
transition audit, source-head proof, typed promotion/reject command, 전용 procedure owner,
legacy 물리 제거와 Map/PinVi/n150 acceptance를 고정한다.
PinVi가 소비하는 legacy curated detail snapshot은 canonical `curation_item_id` 기반의
typed direct projection으로 같은 release에서 이관하고, legacy cache/path/type를 함께 제거한다.

구현 전 독립 적대 리뷰 2명이 설계와 현 writer를 전수 대조해, UUID로 잘못 적은 domain command,
기존 item lost update, same-state source audit 불능, accepted link pointer 누락, PinVi snapshot의
신뢰/공개 술어 누락, merge↔provider lock inversion, raw DML 회수 뒤 import/manual/merge 42501,
generation completeness와 role bootstrap 공백을 확인했다. 정본은 bigint command claim,
candidate/collection/item 세 revision, exact source transition matrix, trusted decision 원자 생성,
T-VN-36 effective input digest, 공통 Feature advisory fence, 전체 canonical writer의 typed procedure,
API/Dagster executor 분리로 보강했다. ADR-061의 auto-publish와 machine-readable removal/OpenAPI
계약도 ADR-092의 same-release cutover에 맞췄다.
## 2026-08-13 — T-VN-36: 새 T-VN-34 위 재배치 + 같은 부류 결함 전수 점검

`feat/tvn34-state-model`(`693c5355`)을 새 base로 잡고 T-VN-36 고유 24개 commit만 다시
얹었다(`--onto`, 옛 tvn34 67개는 폐기). 파생 산출물(OpenAPI export, contract SHA,
migration graph)은 마지막에 재생성했고 문서(journal/resume/tasks)는 합집합으로 병합했다.
alembic은 `0104_tvn36_final_fence` 단일 head다.

리베이스보다 큰 수확은 T-VN-34에서 확립한 결함 부류를 T-VN-36에도 전수로 걸어 본 것이다.

- **notice reconcile SQL이 통째로 죽어 있었다.** T-VN-36이 `notice_update` CTE를 caller의
  field patch로 옮기면서 바깥 SELECT의 `old_valid_end_time`이 `lifecycle_outcomes`
  projection에서 빠졌다 — 모든 notice reconcile 경로가 `UndefinedColumn`으로 실패했다
  (통합 18건). 리베이스 이전 tvn36 tip에도 있던 결함이다.
- **override procedure arity 미추종.** `0104`가 `p_request_id`를 지운 뒤 admin writer만
  새 서명을 따랐고 주소·전화 writer는 옛 12-slot CALL을 그대로 썼다(`UndefinedFunction`).
- **오류 매핑이 죽은 코드였다.** `_raise_field_override_procedure_error`가 새 base가 지운
  `_pg_error_attribute`를 호출해 `NameError`가 됐다. `_driver_constraint_identity`로
  통일하고, P0002/40001/23514가 실제로 도메인 오류가 되는지 실 DB로 확인하는 통합
  테스트를 넣었다(종전에는 그 축이 없었다).
- **HTTP idempotency ledger 이름 붕괴.** create/patch/field-override 세 라우트가 한
  operation(`admin.feature.override.author`)을 공유해 ledger의 route 유일성과 ETag replay
  계약이 깨졌다. 라우트별 이름을 되살리고, override author를 부를 수 있는 operation
  allow-list를 DB 쪽(`0100`/`0104`)에서 넓혔다.
- **정적 차단선이 제 세대만 봤다.** `test_tvn34c_feature_state_inventory`가 `0097`의
  DROP COLUMN만 읽어 `0104`가 지운 `data_origin`/`data_version`에는 무방비였다. 두 cutover
  migration을 함께 읽도록 넓혔다.
- **frontend 계약 미추종.** `type-check`/`lint`가 red였다 — 제거된 OpenAPI 스키마를 참조하는
  live spec, mock의 `data_origin`/`data_version`/`versions`/`change_requests`, 그리고 파일
  전체를 무력화하던 `@ts-nocheck`. change-request 표면 전용 spec과 fixture를 지우고
  `@ts-nocheck`을 제거했다. PATCH가 correction basis를 무효화하는 새 계약도 반영했다
  (T-VN-36 이후 PATCH는 그 자리에서 row_revision을 올린다).
- **0104가 지운 것을 쓰던 테스트 전수 정리.** whole-row provenance bridge를 쓰는 T-VN-34
  세대 테스트에는 tvn36이 이미 쓰던 skip guard를 붙이고, `feature_versions` 권한 축은
  후속 gate로 넘겼다. `0027`의 `data_origin='user_request'` 제외 가드는 head 동등 술어가
  없어 재현하지 않는다고 명시했다.
## 2026-08-12 — T-VN-38 병합과 완료 task 아카이브 정리

PR [#971](https://github.com/digitie/kor-travel-map/pull/971)이 `8dc2b24a`로 머지됐다.
최종 source `bef509d`에서 GitHub CI 8개가 모두 green이었고, n150 전용
`ktm-tvn38-db:18732` clone의 destructive Live UI E2E는 main/recovery 각각 2/2,
`phase=passed`, BLOCKED 없음으로 끝났다. consumer·DB 적대 리뷰 2인은 P0/P1=0을
재확인했다.

`tasks.md`는 열린 백로그만 둔다는 규칙에 맞춰 이미 병합된 `T-VN-33`(#966),
`T-VN-37`(#968), `T-VN-38`(#971) 및 `T-VN-H45` 완료 기록을 `tasks-done.md`로
이관했다. 열린 prod 배포·운영 후속·T-VN-34/36/40/41만 남겼다.
## 2026-08-12 — T-VN-38: immutable fact/current-summary CI 구조 계약 보강

#971의 integration CI가 T-VN-38 이후에도 옛 `provider` 문자열 fact, nullable source lineage,
BRIN/current-row index, outer terminal page limit을 가정하는 테스트·도구를 발견했다. core hash
규칙은 바꾸지 않고 Dagster provider 응답 경계에서 `date`/`time`/`Decimal`을 canonical JSON으로
정규화했다. Alembic metadata와 raw-DDL structural contract에는 source entity/record 복합 UNIQUE와
current weather/price summary 및 rebuild receipt를 명시했고, card/anchor fixture는 canonical
ingestion과 freshness SLA를 통해 current pointer를 만든다.

동일 패턴으로 H35 price index fingerprint, weather access-index audit, tier-2 bbox candidate CTE의
pre-page count, source-record 수명 단언과 `docs/architecture`의 과거 current-row 설명을 전수
정리했다. 이 문서·코드 보강은 별도 문서 PR로 분리하지 않으며 #971 final CI, 재실행 n150 clone
live, 적대 리뷰 재승인이 끝날 때까지 완료로 간주하지 않는다.
## 2026-08-12 — T-VN-38: 반복 n150 clone live 실행의 checkpoint 복원 고정

직전 성공 live가 UI 삭제의 soft-delete 감사 Feature 6건을 의도적으로 남겨, 후속 candidate가
Playwright 시작 전에 trusted checkpoint와 `feature_total`이 다르다고 fail-closed 되는 것을
n150에서 재현했다. 이 상태는 prod와 무관한 `ktm-tvn38-db:18732` clone의 정상적인 이전
acceptance 결과였지만, 정상 `run`에 signed dump 복원이 없어 같은 clone을 반복 검증할 수 없었다.

정상 path도 dump의 경로·권한·SHA·archive를 검증한 뒤 dedicated clone만
`pg_restore --clean --exit-on-error --single-transaction`으로 복원하고 login fence와 시작
snapshot을 만든다. abort의 restore-first 경계와 대칭을 유지하며, restore 실패나 이후 drift는
BLOCKED/성공 result 없이 중단한다. unit 47개, Bash/Ruff/redaction gate와 최종 n150 main/recovery
각 2/2를 통과했다. final `e68b00ef`의 consumer·DB 적대 리뷰 2인은 P0/P1 없이 GO를 확인했다.
## 2026-08-12 — T-VN-38: T-VN-33 병합 뒤 projection·동결 gate 재검증

T-VN-33의 squash merge를 기준으로 T-VN-38의 고유 32개 commit만 다시 얹고,
`0095_tvn33_tvn38_head_merge`가 유일한 Alembic head임을 fresh upgrade로 확인했다.
target catalog fingerprint와 T-VN-33 reference artifact도 새 head에 맞춰 재동결했다.

적대 DB 리뷰가 두 결함을 발견해 같은 패턴까지 함께 정리했다.

- price current projection은 전역 desired 집합을 만들면서 advisory lock이 없어 오래된
  writer가 더 새 pointer를 되돌릴 수 있었다. weather와 대칭인
  `projection:current-price-summary` transaction advisory lock 및 contention 회귀를
  추가했다. global mutable projection inventory는 weather·price 두 개뿐임을 확인했다.
- frozen artifact SHA 검증에서 빠졌던 CRLF bytes guard를 9개 artifact mapping 전체에
  복구했다.

projection index gate도 receipt-backed current read의 실제 선두 access path
`pk_current_price_summary`를 단언하도록 고쳤다. fresh migration·weather/price·target
contract 묶음 104개, API weather/price 34개, OpenAPI generated type check와 frontend
TypeScript check가 통과했다. DB와 consumer 적대 리뷰는 모두 P0/P1 없이 GO다.
## 2026-08-12 — T-VN-38: T-VN-33 병합 기준 Alembic head 수렴

T-VN-33의 `0092_tvn33_offline_cleanup`와 T-VN-38A의
`0092_weather_current_summary`가 같은 `0091`에서 분기한 사실이 병합 기준
rebase에서 드러났다. 빈 `0095_tvn33_tvn38_head_merge`가 두 선행 revision을 함께
요구해 Alembic head를 하나로 수렴시킨다. target catalog·OpenAPI baseline은 이 결선
결과로 다시 동결하며, 이후 T-VN-34는 이 merge revision을 `down_revision`으로 삼는다.
## 2026-08-11 (3) — T-VN-33 최종 적대 리뷰 APPROVE, 잔여 P2 처리, 게이트 25/25

**리뷰 3렌즈 전원 APPROVE · P0/P1 0건.** 세 렌즈 모두 실측으로 판정했다 — 검증 신뢰성
렌즈는 변이 26건을 심어 25건 KILLED를 확인했고, API 렌즈는 `openapi-typescript` 재생성
결과가 체크인된 `types.ts`와 **0바이트 차이**임을 확인했다. 데이터·스키마 렌즈는 triple
세 열을 가진 5개 테이블 전부가 삼중(또는 4열)으로 수렴해 pair 모양 유일성이 하나도
남지 않았음을 전수 확인했고, `ops.managed_files` 가드 분리가 안전한 근거도 실측으로
확인했다(registry는 관측 전용이고 물리 객체를 지우는 경로가 없다).

승인 뒤에도 P2 8건 중 6건을 처리했다. 이 브랜치가 **스스로 세운 규칙을 자기 코드가
어기는 자리**들이었다.

- **0092의 새 트리거가 writer와 정면으로 충돌했다.** `NULL → dataset_id`(최초 귀속)까지
  "ownership is immutable"로 거부하는데 `file_registry._UPSERT_SQL`은 재등록 시 소유자를
  붙이는 CASE를 구현한다. `scan_s3_location`은 그 호출을 `registry_guard`로 감싸지 않아
  예외가 그 pass 등록분을 통째로 롤백시킨다. 귀속은 rebinding이 아니므로 NULL→값만
  허용하고 값→다른 값·값→NULL은 계속 거부한다.
- **계약↔head 대조 게이트에 index 축이 없었다.** 축을 켜자 4건이 나왔고 셋은 계약이
  낡은 것(그중 하나는 pair 시대 index 이름), 하나는 계약이 옳았다(varchar/text 표기
  차이 — allowlist로 기록). 하한과 allowlist 양방향 `==`로 fail-open도 막았다.
- **`allowed_sync_scopes=[]`로 접는 분기**가 같은 응답이 낸 membership 행을 같은 응답의
  capability가 거짓 사유로 거부했다. `target_grids` 축에서만 닫혀 있던 것을 전 scope로
  넓혔다.
- **제출 직전 fail-closed 가드가 3축 중 2축만 봤다.** dataset만 남아 있으면 통과했다 —
  형제 operation이 disable된 뒤의 제출을 그대로 흘려보낸다. 삼중으로 좁히고 어느 축이
  사라졌는지 사유로 구분한다.
- **selector와 "scope를 고를 수 있는가"를 갈랐다.** `effect="sync_scope"` 분기를
  `target_grids` 선언 밖으로 넓히면서 `selector="poi_cache_targets"`를 상수로 남겨,
  POI target이 하나도 없는 dataset에 "범위 계약: 활성 POI target"이 그려졌다. 서버는
  selector를 `target_grids` 선언과 동치로 내고 프론트 게이트는 selector를 보지 않는다.
- 병렬 갈래가 서로의 변경을 못 봐서 생긴 **낡은 서술 4건**도 정정했다(주석이 서버가 더는
  내지 않는 상태를 기술하거나 존재하지 않는 분기 수를 셌다).

**flake 2건을 없앴다** — 둘 다 "부하 탓"으로 넘길 수 있었던 red다.

- 감사 계획 테스트의 `assert not sort_nodes`가 비결정적이었다(같은 트리·같은 명령으로
  한 번 red 한 번 green, 단독 8 passed). ANALYZE·`force_generic_plan`을 이미 걸고 있으니
  통계 문제가 아니라 top-N 정렬과 index-ordered 경로의 비용이 팽팽한 것이다. 단언을
  정렬 유무가 아니라 **유계성**(정렬 행·훑은 행·버린 행 각각 ≤64)으로 바꿨고, 약화가
  아님을 `DROP INDEX` 회귀로 확인했다.
- write-cost 실측이 40k INSERT를 상태별 **한 번씩** 재고 2% 마진으로 비교했다. 벽시계
  측정에서 부하는 시간을 늘리기만 하므로 최솟값이 간섭 없는 비용에 가장 가깝다 —
  batch는 40k 그대로 두고 회차를 3회로 늘렸다. 20k×3 안은 효과 크기가 함께 줄어
  ratio 1.02x로 임계에 붙어 기각했다(색인 유지 비용은 행 수에 비례한다).
  이 테스트는 T-VN-33 범위 밖이지만 머지 게이트를 비결정적으로 만들어 함께 고쳤다.

**최종 게이트 25/25 GREEN**: unit+lint 2192 · api 1101(cov 77.64%) · dagster 530/3skip
(85.23%) · integration **1049 passed / 0 skipped**(geo live 실제 실행) · vitest 37파일 302 ·
frontend 9종.
## 2026-08-11 — T-VN-36: T-VN-34 rebase와 final-fence 동결 재검증

T-VN-36A~D를 T-VN-33 cleanup·T-VN-38 current summary·T-VN-34 final state cutover가
수렴된 `0095_tvn33_tvn38_head_merge` 체인 위로 재배치했다. Alembic은
`0104_tvn36_final_fence` 단일 head로 수렴했다.

T-VN-33 ownership reference, final target catalog, admin OpenAPI baseline은 이전 base의
digest를 그대로 신뢰하지 않고 fresh PostGIS 적용값과 현재 generated spec에서 다시 동결했다.
T-VN-36 final fence와 target freeze 게이트가 통과했다. PinVi `8f7fef1`의 user/admin-detail
contract pin-consistency를 rebase source `c1fa5a4d`에서 다시 검증하고, vendor 바이트와
admin-detail deterministic subset은 그대로인 paired receipt로 고정했다.
## 2026-08-11 — T-VN-34: 최신 T-VN-33/T-VN-38 rebase와 migration 선형화

T-VN-33의 `0092_tvn33_offline_cleanup`와 T-VN-38 weather/price chain은 공통
`0091`에서 갈라져 있었다. upstream T-VN-38이 두 branch를
`0095_tvn33_tvn38_head_merge`로 수렴시킨 뒤, T-VN-34A state spine의
`down_revision`도 그 merge revision으로 옮겼다. fresh upgrade는 T-VN-33 cleanup,
T-VN-38 summaries, T-VN-34 state/public/final cutover를 하나의 head로 적용한다.

T-VN-33 ownership reference와 admin OpenAPI의 bytes 변동은 target catalog와 OpenAPI
baseline freeze가 fail-close로 검출했다. 실제 PostGIS 적용값으로 동결을 다시 만들고,
state/runtime/post-cutover contract를 재실행했다. PinVi user/admin-detail vendor receipt는
새 Map source commit을 기준으로 다시 대조했다. user/admin-detail 바이트는 각각
`eca7ee…`/`ea4adb…`로 유지됐고, PinVi `197bcee`의 핀만 실행 source
`901939bf`로 갱신했다. full admin OpenAPI는 `d2e0add…`로 receipt에 고정했다.
## 2026-08-11 — T-VN-38: 최신 T-VN-33 위 rebase와 Alembic head 수렴

T-VN-33의 `0092_tvn33_offline_cleanup`가 T-VN-38A의
`0092_weather_current_summary`와 같은 `0091`에서 분기한 사실이 rebase 뒤 fresh
upgrade에서 드러났다. 둘 중 하나를 생략하면 정리 또는 immutable summary schema가
빠지고, 그대로 두면 Alembic `head`가 두 개가 된다. 빈
`0095_tvn33_tvn38_head_merge`가 두 선행 revision을 함께 요구하도록 수렴시켰다.

영향도는 T-VN-33의 provider lineage/OpenAPI·Dagster·모델 파일과 T-VN-38의 현재
weather/price projection 계약이 겹치는 지점으로 한정했다. target catalog와 OpenAPI
baseline은 이 결선 결과로 다시 동결하며, 이후 T-VN-34는 이 merge revision을
`down_revision`으로 삼아 선형 stack을 계속한다.
## 2026-08-11 (2) — T-VN-33 33-E: 격리 fresh 재적재 + n150 live 확인

전체 25게이트 GREEN 위에서, **비어 있는 PostGIS에 최종 스키마만으로 다시 세운 DB**에
대고 API와 admin UI를 실제로 태웠다. n150에 격리 컨테이너를 띄웠고(prod 스택은 건드리지
않는다) 브라우저는 정책대로 n150에서 돌렸다.

**① fresh 재적재** — 빈 PostGIS 16.9/3.5 → `alembic upgrade head` → `0092_tvn33_offline_cleanup`.
`alembic current == heads`, `alembic check` = "No new upgrade operations detected"
(모델과 스키마 사이 drift 0). 시드 실측: dataset 64 · 활성 63 · operation 79 ·
활성 refresh operation 56 · scope 행 59 · refresh operation이 없는 dataset 8.

**② API live 12/12** — 삼중이 실제로 강제된다: 없는 `operation_key` → 404, 없는
`sync_scope` → 404, exact triple → 200. `detail_url`은 67/67 행이 세 축을 담는다.
preview(fixture) 200, refresh-policy PUT 200. 비활성 dataset 정책 PUT은
**409 `INACTIVE_DATASET_MUTATION_DISABLED`** — 라운드11이 orphan 오분류에서 갈라낸
typed 오류가 live에서 그대로 나온다.

**③ admin UI live 10/10 (n150 브라우저)** — 그리드 67행, `operation` 열 존재,
operation_key 값이 화면에 56회 렌더. 상세 토글 aria-label이 삼중을 담는다
(`… dataset_wide feature_event_datagokr_cultural_festivals_job 상세 열기`).
console error 0. 서버가 `canonical`이라 답한 행을 화면이 "잔존 행"이라 말하는 8라운드
BLOCKER 회귀도 live에서 0건이다.

**④ 라운드12 수정의 live 확인** — 실행 가능한 refresh scope가 없는 dataset(#12
`google-places-api-new/place_phone_enrichment`, `operation_key` 없음)에서 '지금 갱신'이
**disabled**이고 사유가 "이 dataset에는 실행 가능한 refresh runner가 없습니다."로 뜬다.
같은 화면의 정상 dataset(#1)은 **활성**이다 — 과잉 차단이 아님을 대조군으로 확인했다.
고치기 전에는 이 버튼이 활성이었고 눌러도 요청도 오류도 없이 아무 일도 일어나지 않았다.

**남은 것**: Dagster는 이 격리 환경에 없으므로 schedule/run 축은 확인하지 않았다
(화면은 "Dagster 스케줄 소스 연결 불가"를 정직하게 표시한다 — 조용히 삼키지 않는다).
## 2026-08-11 — T-VN-33 라운드11~12: "좁게 돌려서 green"을 구조로 막았다

11라운드까지의 근인은 하나로 수렴한다. **게이트 green의 의미가 주장보다 작았다.**
12라운드는 그 층을 닫는 데 썼고, 전수 감사 57건 중 적대 검증이 반려한 15건을 처리했다.

**BLOCKER 1 — catalog exact-set 게이트가 CI 경로에서 red였다.** 단독 실행은
`14 passed`, `pytest tests/integration` 통째 실행은 `4 failed`. session-scoped 공유
`migrated_engine`에 형제 fixture가 handler 없는 활성 refresh operation을 commit하는데,
게이트는 **카탈로그 전역 성질**을 단언했다. 다섯 갈래가 전부 CI 스텝보다 좁은 범위에서
green을 봐서 아무도 못 봤다. 게이트를 전용 database + alembic head로 옮겨 순서 독립으로
만들었고, "공유 DB가 오염돼도 결과 불변" + "진짜 drift에는 여전히 red"를 한 테스트에서
둘 다 단언한다 — 오염 회피가 fail-open으로 가면 고친 게 아니다.
→ **규칙: 카탈로그 전역 성질을 단언하는 테스트는 공유 DB에 쓰지 않는다.**

**BLOCKER 2 — 0092의 docstring이 거짓이었고 downgrade가 실제로 실패했다.** "제약/함수
정의만 건드리므로 되돌릴 수 있다"고 적었지만 UNIQUE를 4열→3열로 **좁히는** 것은 데이터
의존이고, 실패를 유발하는 상태를 만드는 것이 하필 같은 revision의 upgrade다.
0090/0091 관례대로 forward-only로 되돌렸다. 저장소에 downgrade 경로를 도는 테스트가 한
건도 없어서 그 진술이 적대 검증 전까지 살아남았다 — `tests/unit/test_migration_forward_only.py`로
게이트를 세웠다.

**비활성 dataset의 정리 경로가 막혀 있었다.** `reject_inactive_provider_dataset`이
DELETE에서도 OLD쪽 활성 검사를 돌아 카탈로그 행을 지울 수 없었다. DELETE는 새 실행을
거는 write가 아니라 정리이므로 면제했다(참조 무결성은 FK RESTRICT가 계속 지킨다 —
양방향 실측 단언). 감사 기록 누락의 원인은 OLD쪽이 아니라 **NEW쪽** assert였다 —
registry hook이 UPSERT라 INSERT/UPDATE로 걸린다. `ops.managed_files`를 활성 가드에서
빼고 소유권 immutable 전용 가드로 교체했다. registry는 storage의 거울이지 실행 축이
아니다. (넓은 면제는 불가능했다 — `expected-rejections-v1.json`의
`inactive_dataset_existing_operation_update`가 executable contract로 못박고 있다.)

**계약↔head 대조 게이트가 `CREATE OR REPLACE` 본문 변경을 못 잡았다.** 대조 범위가
`after − before` 차집합이라 `target-schema-v1.sql`이 이미 만든 함수의 본문 교체는 통과했고,
하필 이번에 바꾼 함수가 정확히 그 경우였다. fixture를 확장해 닫고 fail-open 하한을
실측값(제약 76 · 트리거 23 · 함수 22)으로 올렸다 — 옛 하한 19는 `CREATE CONSTRAINT
TRIGGER` 4문을 누락해, 그 4개가 계약에서 통째로 사라져도 통과하는 값이었다.

**선언된 실행 scope가 없는 dataset을 '갱신 가능'으로 투영하던 것을 고쳤다.** 화면에서
'지금 갱신'이 활성이었고, 누르면 요청도 오류도 없이 아무 일도 일어나지 않았다. 원인은
degrade payload가 정상 dataset-wide capability와 **다섯 필드 중 넷이 같고 `reason`만
달랐던** 것이다 — 프론트 게이트는 허용 경로에서 `reason`을 읽지 않는다. 계약에
`effect: "none"`을 추가하고 `is_refreshable`을 `refresh_scopes` 기준으로 좁혔다.
요청 dialog도 같은 필드로 막는다(`catalog-selection.ts` — 그 축은 테스트가 0건이었다).

**무방비 축을 회귀로 덮었다.** MOIS source precheck fail-open(모듈 전체를 monkeypatch한
테스트뿐이라 fail-open이 전 게이트에 안 보였다 — 실 DB 회귀 7건으로 대체),
`_advisory_key`의 sync_scope 성분, 주소 clue 우선순위 3건, MCST slug 미지 키 거부.
전부 변이를 심어 KILLED를 실증했다.

**주석에 박힌 실측 수치를 지웠다.** `74개 dataset 중 17/18개`가 8곳 이상에 서로 다른
값으로 남아 있었고, 그중 하나는 Pydantic docstring이라 `openapi.json`/`types.ts`로
공개 계약에 실려 나갔다. 개수는 DB마다 다르다(0089 legacy harvest) — 성질만 남겼다.
## 2026-08-10 — T-VN-34: 최신 T-VN-33 → T-VN-38 체인 재base 재검증

신규 T-VN-33 head `21b1758b`를 기준으로 T-VN-38을 `2e78d623`까지 먼저 재base하고,
T-VN-34의 전용 63개 commit을 그 위로 재base했다. 중간 merge는 만들지 않았다. T-VN-33의
provider dataset/source 정본 강화와 T-VN-38의 current summary가 함께 적용된 fresh migration에서
target freeze·공개 projection·상태 spine·runtime ACL을 검증했다.

재base가 드러낸 두 drift도 같이 바로잡았다. 날씨 current-summary 검증은 실행 시각보다
과거인 receipt를 만드므로 테스트 fixture의 freshness 시각을 상대 시각으로 고정했고,
runtime의 `feature_versions` ACL은 read 허용과 insert 거부를 별도 catalog probe로 검증하도록
바꿨다. OpenAPI freeze hash도 현재 생성 spec에 맞춰 재고정했다.
## 2026-08-10 — T-VN-36 A–D 단일 PR: 설계 착수

T-VN-34C 완료 head `b03d5a4f` 위에서 `feat/tvn36-abcd-field-overrides`를 만들었다. 기존
T-VN-36C에 섞여 있던 destructive freeze fence와 live acceptance는 36D로 명시 분리하지만,
A–D는 하나의 forward-only Draft PR/release로만 병합한다.

ADR-091은 provider base ledger, field override intent, typed effective storage를 같은 정본의
세 층으로 고정한다. whole-row `data_origin` fence와 `feature_versions` bridge는 36D에서만
제거하며, source 재적재와 immutable request replay로 mapping할 수 없는 legacy 행은 추정하지
않고 fail-closed한다.
## 2026-08-10 — T-VN-34C: n150 fresh destructive live gate 통과

immutable snapshot은 Map 실행 source `fe12e8da`와 PinVi `e37eda94`를 `git archive`로만 넣어
fresh `0097` PostGIS를 만들고, 실제 Dagster runtime ETL 후 Noble Playwright destructive
admin main/recovery를 실행했다. C7은 계획한 두 시나리오 모두 통과했고 PinVi public probe까지
성공했다. run/seed 식별자는 해시로만 결과에 남겼다.

성공 뒤 runner의 자동 recovery cleanup을 독립 확인했다. `BLOCKED.json`, 해당 compose
container, volume이 모두 없으며 이전 실패 snapshot도 각각 recover 완료 상태다. 따라서
기존 clone DB·host browser를 쓰지 않는 T-VN-34C final-live acceptance가 충족됐다.
## 2026-08-10 — T-VN-34: T-VN-38 위 rebase와 fresh live 실행 경계 재고정

T-VN-34의 state cutover는 T-VN-38 base 위에서만 재배치한다. Map OpenAPI full bytes가
달라지면 artifact gate가 즉시 재동결을 요구하며, Map/PinVi의 user/admin-detail vendor
pair도 source revision·vendor hash·deterministic admin subset으로 다시 대조한다.

n150 live gate는 기존 clone DB runner를 재사용하지 않는다. final migration보다 앞선
DB나 호스트 browser runtime을 사용하지 않고, root-owned snapshot의 fresh DB·Dagster
runtime ETL·Playwright executor·PinVi probe를 같은 isolated compose run으로 묶는다.
실패하면 `BLOCKED.json`을 보존하고 `recover`만 허용한다. 이 경계의 로컬 static gate는
통과했지만 destructive n150 실행과 recovery evidence는 별도 완료 조건이다.
## 2026-08-09 — T-VN-33 적대 리뷰 7·8라운드: 감사기를 감사했다

두 라운드 모두 REJECT였고, 8라운드는 리뷰어 둘이 **독립으로 같은 BLOCKER**를 찍었다.
그 BLOCKER는 한 줄이다 — `scope.operation_key === selection.operationKey`. 왼쪽은
API 원본 `string | null`, 오른쪽은 UI가 `null → ""`로 정규화한 값이다. `null === ""`은
false이므로 **refresh operation이 없는 catalog 전용 dataset 17~18개의 상세가 통째로
렌더되지 않았다**. 화면은 서버가 `catalog_state="canonical"`이라 답한 행을 두고
"ETL 카탈로그에 없는 잔존 행입니다"라고 표시했다.

세 가지가 이걸 못 잡았다. TypeScript는 `string | null === string` 비교를 막지 않는다.
e2e 픽스처에 `operation_key: null` 행이 하나도 없었다. 그리고 파일 자신이 "경계 밖에서
operation_key를 직접 읽지 않는다"고 규약을 적어 두고 세 곳에서 어겼다 — 규약을 적는
것과 지키는 것은 다른 일이고, 지키게 만드는 것은 또 다른 일이다.

더 큰 것은 검증 쪽이다. **vitest 36파일 285케이스가 어느 워크플로에도 걸려 있지
않았다.** 이 브랜치가 추가한 프론트 테스트 ~900줄을 포함해서다. 미러링 감사기는 이
사각을 원리적으로 볼 수 없었다 — CI→로컬 방향만 보고 "저장소에 있는 테스트가 어느
게이트에도 없다"는 반대 방향을 보지 않기 때문이다. 그래서 게이트 스크립트는 이 누락을
**충실히 미러링**하며 green을 냈다. CI와 로컬에 넣자마자 옛 계약을 못 박고 있던 테스트가
하나 잡혔다. 게이트에 넣는 것이 곧 검증이다.

그리고 감사기 자신이 "게이트가 실패할 수 있는가"를 전혀 보지 않았다. `|| true` 하나로
mypy·integration·openapi·next build 어느 것이든 무력화해도 조각은 그대로라 침묵했다.
스크립트는 `py()` 주석에 "파이프를 걸지 마라 — exit code가 마지막 명령의 것이 되어
게이트가 늘 통과한다"고 그 실패 모드를 **적어 두고 있었다**. 아는 것과 검사하는 것은
다르다. 리뷰어가 설계한 변이 14종 중 12종이 생존했고, 면제표의 "echo는 실패를 만들 수
없으므로 미러링 대상이 아니다"라는 서술도 거짓이었다 — 코드가 하던 일은 "echo인 명령"이
아니라 "echo를 **포함한** 명령"의 면제였고, `bash verify.sh && echo done`으로 진짜
차단 스텝을 밀수할 수 있었다.

7·8라운드를 합쳐 변이 배터리는 20 → **32/32**가 됐다. 도달성 판정(실행문을 지우고
주석만 남기면 안 잡히던 것), 실패 억제 토큰, pytest 경로 축소, 면제 접두+`&&` 구간
판정, 워크플로 헤더 파싱까지 각각 변이로 못을 박았다.

부수적으로, 복사 실패를 치명으로 바꾸자마자 숨어 있던 결함이 즉시 드러났다 —
`next build` 산출물의 끊어진 심링크 때문에 `cp -r`가 non-zero로 끝나고 있었고, 그전까지
파이썬 게이트는 **일부만 복사된 트리** 위에서 돌고 있었다. 삼키는 코드는 결함을 없애지
않고 미룬다.

제품 쪽 잔여 수정은 딥링크(3축 강제 → 유일하면 수용·모호하면 거부), 실행 타임라인의
fail-open 필터(세 축이 안 차면 dataset 필터까지 버려 전 시스템 실행을 보여줬다), 요청
dialog의 형제 operation 임의 선택, MOIS 제출 차단 복구(표시만 복구돼 있었다), 비활성
dataset 정책 PUT 500 → 409다. 상세와 근거는
`docs/reports/t-vn-33-live-product-defects-2026-08-08.md` 35~49번.
## 2026-08-08 (3) — T-VN-33 기능 게이트 GREEN + 설계 재검토 4건

전체 스위트가 **4,534 passed / 6 failed**로 수렴했다(시작 298). 6건은 전부 컨테이너
환경 노이즈다 — `docker` CLI 바이너리 부재로 죽는 compose 테스트 5건(`FileNotFoundError:
'docker'`)과, 40k INSERT 두 번의 벽시계 비율을 2% 허용오차로 비교하는 부하 민감 테스트
1건이다. 후자는 단독 실행 시 통과하고, 내 브랜치는 그 파일도 GiST 인덱스도 안 건드렸다.

사용자가 우선순위를 바꿔 지시했다 — 호환성·최소수정·기존 계약 유지보다 **설계적 우수성**을
앞에 두라고. 그에 맞춰 "계약이 이러니까 맞췄다"로 내렸던 판단들을 되짚었고, 그 과정에서
결함 4건이 더 나왔다.

가장 값어치 있었던 것은 **ORM PK가 DB보다 좁게 선언돼 있던 것**이다.
`provider_dataset_operation_scopes`의 DB PK는 triple인데 ORM은 2열만 `primary_key=True`로
뒀다. 처음에는 이것을 "identity map이 두 행을 접는다"로 정당화했는데 **그 근거는 틀렸다** —
이 저장소는 raw SQL 전용이고(ADR-004) 이 class를 ORM 방식으로 쓰는 코드가 0건이라 그
시나리오는 도달하지 않는다. 적대 리뷰가 A/B로 진짜 이유를 밝혔다: **alembic autogenerate가
PK 제약을 비교 대상에 넣지 않아** ORM PK를 pair로 되돌려도 `alembic check`와 기존 메타데이터
테스트가 모두 통과한다. 즉 아무 게이트도 이 어긋남을 보지 못하고 있었다. 게다가 내가 쓴
단위 테스트가 **틀린 2열 모양을 단언해 그 어긋남을 고정**하고 있었다. 부류 전체를 막는 게이트를 세우고(mapped table 전수 대조) A/B로 증명했다.

두 번째는 **하드 500**이다. `_group_dataset_execution_snapshot_rows`가 SQL이 triple로
partition해 내보낸 행을 pair로 다시 묶어 `RuntimeError`를 낸다. 스키마 변경 없이
카탈로그에 refresh operation 하나를 더 등록하는 평범한 작업만으로 재현된다. 이걸
단정하기까지 두 번 헛짚었다 — 처음엔 "병합·오귀속"이라 과장했는데 SQL은 이미 triple로
partition하고 있었고, 다음엔 반대로 "refresh-only CHECK가 막아 도달 불가"라고 물러섰는데
그 CHECK가 막는 것은 *preview*이지 *복수 refresh*가 아니었다. 최종 판정은 롤백 트랜잭션
실측(두 refresh operation이 같은 scope를 공유할 수 있음)과 A/B 재현으로 세웠다.

**하지 않기로 한 것 2건도 같은 무게로 기록해 둔다.** offline_uploads 멱등키를 4열로
올리는 안은 구현까지 갔다가 되돌렸다 — 업로드 요청 표면에 operation 입력이 없고 두 INSERT
경로 모두 리졸버를 쓰는데 그 리졸버가 모호하면 조용히 고르지 않고 실패시킨다. 즉 operation만
다른 두 upload를 만들 방법 자체가 없어 죽은 폭이었다. SQLSTATE 통일(38 대 1)도 분기하는
소비자가 없어 접었다. 지시가 "설계 우선"이어도, 동작이 안 바뀌는 변경으로 freeze
아티팩트를 흔드는 건 설계 개선이 아니다.
## 2026-08-08 (2) — T-VN-33 통합 전량 전환 완료, 제품 결함 25건 이상 수정

- **라이브 실행이 잡은 결함은 전부 단위 테스트로는 안 잡히는 종류였다.** 세 가지 기제다:
  ① SQL은 문자열이라 mypy도 단위 테스트도 안 본다(`sr` alias 유실 2건 — 정합성 검사와
  dedup 조회가 파스 단계에서 죽었다), ② 트리거·제약은 DB에만 있다(`BEFORE UPDATE`가
  `RETURN OLD`를 해서 **두 ops 테이블의 모든 UPDATE가 조용히 버려지고** 있었다 — rowcount는
  1이라 호출자는 성공으로 본다), ③ 코드와 제약이 서로 반대로 갔다(`provider_dataset` scope는
  파이썬이 triple을, DB check가 자연키를 요구해 **어느 형태로도 쓸 수 없었다**).
- 고친 것 중 파급이 큰 순: `pipeline_repo`의 미투영 열 한 줄(projection 전체 26건),
  `sr` join 2줄(38건), dagster sync-state 이관(provider ETL asset 전부), `sync_scope="default"`
  (MOIS 적재가 데이터를 다 쓰고 cursor에서 rollback), 재적재 idempotency(`prior` CTE의
  `FOR UPDATE`가 자기 문장에 가려져 feature가 매 관측마다 재기록), 데드락(전역 singleton
  clock 행과 scope 행의 공유→배타 승격이 엇갈림), event 감사 인덱스(dense shape에서
  10,481 buffer/75ms → 225/0.31ms).
- **테스트는 55 + 18 = 73개 파일을 최종 스키마로 옮겼다.** 통합 실패가 298 → 16 → 0
  경로로 줄었다. 마지막 16건 중 10건은 제품이 아니라 **테스트 오염**이었다 —
  `test_dagster_feature_etl`의 TRUNCATE 목록에 `source_entities`가 없어 entity가 링크 없이
  남고 정합성 F1(orphan)이 다른 테스트에서 켜졌다. T-VN-33이 head를 끼우면서 record
  CASCADE가 더 이상 entity를 지우지 않게 된 것이 원인이다.
- **커버리지 공백 2건을 메웠다.** notice 재등장 테스트가 **바이트 동일** 경로만 검증해
  결함이 있어도 통과했고(내용이 바뀐 재등장은 `became_current=True`라 적재가 subtype을
  덮어써 lifecycle이 "직전에 닫혀 있었다"를 관측할 수 없다), 등대 판정의 catalog pair 축은
  테스트가 아예 없었다. 둘 다 결함 코드에서 새 테스트만 실패함을 A/B로 증명했다.
- geo live 테스트 5건은 T-VN-33과 무관한 환경 미비였다. 막히는 지점이 셋이고 셋 다
  오진을 유발한다 — 자세한 것은 `dev-environment.md` §10.7에 남겼다. Map public API key는
  VWorld 키가 **아니고**, 정본은 n150 `~/.secrets/`이며, 테스트가 읽는 변수는
  `LIVE_KOR_TRAVEL_GEO_BASE_URL`이다(다른 변수만 넘기면 원인은 주소인데 메시지는 키를
  가리킨다).
- 미수정으로 남긴 것: API 표면이 identity triple 중 2/3만 노출한다(에이전트 보고 6건).
  `OfflineUploadRecord`에 `operation_key`가 없어 409가 알려준 operation을 어느 read 표면과도
  대조할 수 없고, `PipelineProviderDatasetIdentityRecord`도 그것을 버려 operation만 다른 두
  member가 같은 객체로 보인다 — 같은 커밋의 `OpsDatasetProviderDataset`이 정확히 그 실패
  모드를 주석으로 경고하며 non-null로 두고 있어 내부 불일치다.
## 2026-08-07 (2) — 통합 테스트 live 실행이 잡은 P0: 두 ops 테이블이 조용히 불변

- **`ops.import_jobs`와 `ops.feature_update_requests`의 모든 UPDATE가 조용히 버려지고
  있었다.** `reject_inactive_import_job_members` / `reject_inactive_feature_update_request_members`가
  `BEFORE DELETE OR UPDATE` 트리거인데 무조건 `RETURN OLD`를 했다. BEFORE UPDATE에서 OLD를
  돌려주면 그 행은 **OLD 값으로 기록된다** — rowcount는 1이라 호출자는 성공으로 본다.
  결과: job 상태 전이(queued→running→done), generation 증가, heartbeat, 취소가 전부
  무효였다. `start_update_request`가 request를 돌려주는데 job은 `queued`인 상태를 실측으로
  잡았고, `UPDATE ... SET generation = generation + 1`을 두 번 돌려도 값이 1인 것으로 확인했다.
  `RETURN NEW`(DELETE만 OLD)로 고쳤고, 같은 형태의 BEFORE UPDATE 트리거 8개를 전수 확인해
  나머지는 모두 예외를 던지는 정상 fence임을 확인했다.
- 이 결함은 **단위 테스트로는 잡히지 않는다** — SQL 문자열은 옳고, 트리거가 붙은 실제 DB에서만
  드러난다. 두 적대 리뷰어가 "통합 테스트를 머지 전에 한 번 돌려라"라고 지적한 것이 정확했다.
- freeze 계약이 pair 시대 산물이라 member 테이블에 `operation_key`가 없었다. scope PK와
  member 4개 테이블의 식별자·FK를 triple로 올리고(멱등키는 3열 유지), violation fixture와
  freeze 테스트 insert도 따라 올렸다. 지문 7종은 fixture가 스스로 계산한 값으로 재생성했다.
- `test_feature_update_repo.py`는 T-VN-33 이전 계약으로 쓰여 있었다. membership helper 추가,
  제거된 배열 필터 검증 테스트 삭제, advisory key 호출부 변환으로 52건 중 41건이 통과한다.
  EXPLAIN 단언은 동작 검증으로 바꿨다 — fixture 규모(4,000행)에서 계획 모양을 못박으면
  코드가 아니라 planner를 테스트하게 된다(계획 실측치는 docstring에 기록으로 남겼다).
## 2026-08-07 — T-VN-33 구현 완결: merge 유실 자산 복구 + freeze 계약 divergence 4건

- **merge에서 T-VN-37 자산 둘이 조용히 사라져 있었다.** `feature_repo.py` 충돌을 tvn33 쪽으로
  채택하면서 frozen H35 SQL이 통째로 없어졌는데 `frozen_h35_schema=True` 호출부(3곳)는 남아
  있었다 — 리허설이 현행 필터를 받아 0079 세대에 없는 `source_entity_heads`·`provider_datasets`를
  참조하므로 실행 즉시 죽는 상태였다. `origin/main`에서 복구했고 sha256 `e934cdb8` / 15,672
  bytes로 T-VN-37의 핀과 일치한다. reconcile CTE의 `MATERIALIZED` 장벽도 함께 복구했다
  (없으면 갱신 대상 feature마다 CTE 재실행 — 3,045 notice에서 87.9초 대 0.35초).
- **freeze fingerprint를 실제로 재현해 guard divergence를 잡았다.** `touch_provider_dataset`
  계열이 `now()`(트랜잭션 시작 시각)를 써서 한 트랜잭션 안의 두 갱신이 같은 `updated_at`을
  받고 있었고, identity-update guard의 SQLSTATE가 계약과 달랐으며, ADR-069 근거 문구 누락과
  죽은 변수 잔존이 있었다. membership guard의 `operation_key IS NULL` wildcard 3곳도 제거했다 —
  두 member 테이블 모두 NOT NULL이라 죽은 분기였고 비등식 join이라 scope PK를 못 탔다.
- **적대 리뷰가 그 정렬 작업의 두 오류를 잡았다.** ①처음 대조는 fingerprint 대상
  `_TARGET_FUNCTIONS` 19개만 봐서 좁았다. 전수 31개로 넓히니 의미 차이가 4건 더 있었다 —
  member-active guard 2개에서 계약이 `scope.operation_key = member.operation_key` 등식을
  빠뜨려 무관한 sibling operation 하나가 비활성이면 member까지 막히는 형태였다(이 건은
  **마이그레이션이 옳고 계약이 낡았다** — 계약을 고쳤다). 나머지 2건은 마이그레이션을 계약에
  맞췄다. ②"바이트 동일"은 **거짓이었다** — 실제로 잰 것은 공백 정규화 기준이고, 31개 전부
  들여쓰기가 다르다(마이그레이션은 Python 문자열 안, 계약은 flush-left). 현재 보증은
  **공백 정규화 기준 31/31 동일**이다.
- **curation CSV를 자연키로 되돌렸다.** `provider_dataset_id`는 `GENERATED ALWAYS AS IDENTITY`고
  0089 legacy sweep이 그 DB의 실데이터까지 훑어 seed하므로 값이 DB마다 다르다. 이 CSV는
  저장소에 sha로 고정돼 어느 DB에나 적용되므로 surrogate를 파일에 박으면 **다른 DB에서 다른
  dataset을 가리킨다**. 해석은 적재 시점 1회 질의로 옮기고 미해석 pair는 hard-fail한다.
- `is_primary_source` ↔ `source_role` 불일치 preflight 추가(prod 0건, 한 행 뒤집어 발화 확인).
  offline_uploads의 FK·멱등키·ORM을 scope PK와 같은 triple로 정렬. perf_gate seeder를 최종
  스키마로 옮겨 실제 실행 확인.
- **0090이 재실행 안전하지 않았다(P0).** `notice_lineage_states.notice_lifecycle_scope_id`
  `ADD COLUMN`에 `IF NOT EXISTS`가 없었다. 0090은 중간에 `autocommit_block`으로 커밋되고 그
  시점 stamp는 아직 `0089`이므로, 뒤이어 0091이 실패하면 재시도가 여기서 `42701
duplicate_column`으로 죽는다 — forward-only라 되돌릴 길도 없다. 0091까지 적용 후 stamp를
  0089로 되돌려 재현하고, 고친 뒤 재시도가 head까지 도달하는 것을 확인했다. `CREATE INDEX
CONCURRENTLY` 16개는 앞의 `DROP INDEX CONCURRENTLY IF EXISTS`가 이미 담당하므로 건드리지
  않았다(`IF NOT EXISTS`를 얹으면 실패가 남긴 INVALID 인덱스를 건너뛴다).
- offline upload writer 2개가 `:operation_key`를 bind하면서 값을 넘기지 않아 모든 업로드가
  `StatementError`로 죽는 상태였고, `ON CONFLICT`도 넓힌 멱등키와 어긋나 있었다. 멱등키는
  계약이 선언한 3열로 되돌리고(폭을 넓힌 근거는 실제 요구가 아니라 추측이었다), operation은
  scope에서 유도하되 모호하면 실패시킨다. live에서 create/reserve/중복/모호 4경로 확인.
- curation 자연키 되돌림이 `packages/kor-travel-map-api`에 전파되지 않아 라우터가 삭제된
  필드를 참조하고 있었다. `mypy --strict -p kortravelmap.api`를 안 돌린 탓이라 이제 두
  타깃을 모두 돌린다.
- event 타임라인 인덱스가 keyset tiebreaker(`event_id DESC`)와 부분 술어
  (`quarantined_at IS NULL`)를 잃어 페이지마다 Sort가 붙고 격리 행을 훑고 있었다. 복구했다.
- 검증: prod 복원본(732,678 record) 위 0083 → 0091 완주, 재시도 시나리오 1회, 계약 대비
  guard **공백 정규화 기준 31/31 동일**, fingerprint 7/7 일치, 단위 2,081 pass(잔여 6건은
  컨테이너 파일·docker CLI 환경 노이즈), mypy --strict 두 타깃(145 + 67 files), ruff clean,
  통합 3,011개 수집 오류 0. 통합 테스트 본체는 live DB가 필요해 실행하지 않았다.
- fingerprint 재현은 fixture의 jsonb type codec이 없으면 7종이 전부 어긋난다. `origin/main`
  대조군으로 장치를 먼저 검증했고, 그 덕에 "환경 탓"이라는 오판과 divergence를 덮는
  재생성을 둘 다 피했다.
## 2026-08-06 (codex) — 사용자 지시로 T-VN-33 WIP 정리·중단

- 진행 중이던 schema/core/API/frontend 에이전트를 중지하고, T-VN-33/F1D 변경은 미스테이징·미커밋
  상태로 보존했다. rebase, push, CI, n150/컨테이너/DB mutation은 수행하지 않았다.
- batch audit의 physical triple·sync-state·pipeline/API/UI/runtime·trigger/fixture P0와 검증
  한계를 `reports/t-vn-33-hold-snapshot-2026-08-06.md`에 기록했다. `[~]` task는 완료가 아니라
  WIP 중단 표식이다.
- T-VN-41 F1D-D final live acceptance는 T-VN-33 merge와 final-schema ETL 재적재가 선행된다는
  순서를 유지한다.
## 2026-08-06 (codex) — T-VN-33 normal-path P0 재개방, T-VN-41 final gate 유지

- actual 구현을 대상으로 한 적대 리뷰가 UI dataset detail/preview의 자연키 route,
  direct ID scope 해석 불능, geo scope의 pair/rank 축약, request snapshot의
  `operation_key` 누락과 정적 Dagster worker registry를 P0로 확인했다. 이들은
  호환 fallback이 아니라 exact membership 전달 경로로 한 번에 제거한다.
- 후속 batch audit는 job snapshot·active plan·pipeline read model도
  `(provider_dataset_id, sync_scope)`로 `operation_key`를 축약하고 rank-select한다는 P0를
  확인했다. ADR-088의 실행 identity를 triple로 명시하고, dataset member에는 예외 없이
  non-null composite FK를 강제한다. operation 없는 generic import job은 dataset member 행을
  만들지 않으므로 nullable/wildcard `operation_key` 예외를 두지 않는다.
- DB 검토는 `0090`이 `source_records.provider/dataset_key`를 삭제한 뒤에도 살아 있는
  `issue_curation_source_rule_decision()` trigger가 그 column을 읽음을 확인했다. migration에서
  `source_records → source_entities → provider_datasets` 정본 join으로 trigger function을
  교체하고, final-schema fixture를 일괄 전환한다.
- T-VN-41 F1D-D의 n150 final live E2E는 T-VN-33 merge와 final-schema ETL 재적재가 선행
  조건이라는 순서를 유지한다. 중간 DB 복구/보존은 수행하지 않는다.
## 2026-08-06 (codex) — T-VN-33 contract gate P0=0 통과

- 스키마 5차와 마이그레이션 4차 적대 리뷰가 모두 P0 GO를 냈다. 마지막 P0였던
  `ON DELETE CASCADE` indirect owner guard의 parent-부재 오판은 non-deferrable FK에서
  referential action으로만 가능한 DELETE로 한정해 처리했다. notice lineage, integrity run,
  curated rule 3경로의 활성 parent cascade 양성 회귀를 빈 PostGIS target에서 실행한다.
- inactive dataset을 가진 feature update request parent 상태 변경도 `23514`로 거부하는
  독립 fixture를 추가했다. artifact unit과 target freeze는 13건 통과했으며, migration
  리뷰는 import job의 member/event cascade도 실제 PostGIS probe로 확인했다.
- T-VN-33A/B/C는 draft PR #966 하나에 계속 누적한다. 다음 단계는 actual migration/model/
  writer/reader/API cutover이며, 테스트 전 누적 구현 delta를 다시 적대 리뷰한다.
## 2026-08-06 (codex) — T-VN-33 3차 P0 contract 재설계

- 3차 적대 리뷰가 확인한 reverse capability/control-plane, scope authorization, nullable
  owner clear, inactive delete, parent lifecycle, exact membership cardinality를 한 checkpoint로
  재설계했다. capability JSON은 산출 metadata만 남기고 refresh scope는
  `provider_dataset_operation_scopes` 정규 child로 이동했다.
- 모든 scope 의존 row는 `(provider_dataset_id, sync_scope)` FK와 enabled operation/dataset
  parent-lock guard를 사용한다. inactive dataset의 old/new direct·indirect ownership mutation,
  source-record-derived integrity violation, parent status mutation, delete, active A→B 재귀속도
  DB가 거부한다.
- import job은 `root|single|multiple`, feature update request는 `single|multiple` mode와
  deferred completeness trigger로 member 수를 강제한다. 빈 PostGIS contract suite는 artifact
  7건과 target freeze 5건이 통과했으며, 다음 단계는 두 리뷰어의 4차 P0=0 재판정이다.
## 2026-08-06 (codex) — T-VN-33 P0 계약 보완 및 재리뷰 제출 준비

- 2차 적대 리뷰의 inactive write, operation/capability 이중 정본, history/head 집계,
  incomplete ownership matrix, removal manifest P0를 target contract에 반영했다.
  `tvn33-reference-ownership-v1.sql`이 sync/notice/curation/job/request/policy/upload/
  integrity/POI/enrichment/file의 dataset ownership을 FK·membership·parent-lock guard로
  실행 가능하게 고정한다.
- event가 다른 import job의 dataset member를 참조하지 못하도록 복합 FK를 추가했고,
  integrity violation의 source record/dataset 불일치와 direct·indirect inactive write를
  SQLSTATE fixture로 검증한다. source record history 2건과 head 1건의 정상 case도
  completeness invariant가 허용함을 빈 PostGIS DB에서 확인했다.
- T-VN-33A/B/C는 초안 PR #966 하나에만 누적하며, 두 적대 리뷰어가 P0=0 GO를 내기 전에는
  actual migration/model/API 구현을 시작하지 않는다.
## 2026-08-06 (codex) — T-VN-33 target contract 실행 검증

- ADR-088의 versioned capability/operation, immutable source record, `observed_at` head,
  inactive dataset 공용 write guard를 target DDL·invariant·rejection fixture에 고정했다.
  direct dataset FK guard는 operation, entity, notice state, weather history/summary까지
  동일 SQLSTATE `23514`로 검증한다.
- 빈 PostGIS DB에서 target freeze 통합 3건과 artifact unit 7건이 통과했다. 이 동결 계약은
  T-VN-33 구현 시작 전 적대 스키마·마이그레이션 재리뷰에 제출했다.
## 2026-08-06 (codex) — T-VN-33 A/B/C 단일 PR 설계와 적대 검토 결선

- 사용자 지시에 따라 provider dataset A/B/C를 각각의 PR로 나누지 않고, schema/backfill·전
  writer/reader cutover·legacy fence/removal manifest를 **하나의 PR**로 처리하도록 tasks를
  재편했다.
- 적대 스키마·마이그레이션 리뷰는 초기안에 공통 P0를 냈다. DB capability/operation 정본 부재,
  immutable record와 재관측 UPDATE의 충돌, 빈 DB seed 부재, 9개라는 불완전한 FK roster와
  multi-dataset job/request의 scalar FK 오용이다.
- ADR-088과 T-VN-33 단일 PR 계획이 이를 해소했다. versioned seed와 DB catalog/handler
  exact-set gate, entity/head가 소유하는 observation freshness, full reference matrix와
  membership table, canonical CHECK/FK·legacy fence·3 revision forward-only migration을
  구현 계약으로 고정했다. weather/price와 typed notice fact는 순서대로 T-VN-38/T-VN-37에서
  원자 전환한다.
## 2026-08-06 (codex) — T-VN-41F1D-C3 n150 파기형 rebuild 결선

- Manager PR #167의 최신 Map typed-subtype pin으로 n150 `rebuild-pinned` generation을 committed했다.
  Map application `0087_route_area_subtypes`, Map Dagster `29b539ebc72a`, PinVi `20260804_0049` schema
  head와 일곱 runtime container health를 확인했다.
- Manager v7 journal은 Map fixture `armed → consumed → finalized`, PinVi canonical cancel의 정확한
  `409 PIPELINE_CANCELLATION_UNSAFE`, final `committed` phase를 보존했다. 로그인 POST는 `200`과
  session cookie를 반환했고, data-independent n150 live UI E2E는 운영 홈·파이프라인 6건, Feature
  목록·지도 초기 surface 10건을 통과했다.
- 의도적으로 비어 있는 새 DB에서 고정 curated/feature ID를 요구한 기존 suite 실패는 C3 runtime failure와
  분리한다. final-schema ETL 재적재 뒤 F1D-D acceptance에서 다시 실행한다.
## 2026-08-06 (codex) — F1D-C0a·F1J-A 완료 이관과 남은 C3 정렬

- Map application schema head artifact(PR #963)와 Map-owned cancel-probe fixture lifecycle(PR #960)의
  병합을 완료 이력으로 이관했다. 두 PR의 구현·검증 결과는 유지하고, 진행 중 task에서는 제거했다.
- 구 compatible-pair를 남은 delivery 단위로 두지 않는다. F1J-B/C는 Docker Manager
  `T-VN-41F1D-C3` 하나로 재정렬했으며, v5 durable transaction이 Map fixture
  ensure→한 번의 canonical cancel→immutable receipt→finalize를 실제 호출할 때만 완료된다.
## 2026-08-06 (codex) — T-VN-41F1D-C0a 후보 Map application schema head artifact 구현

- 후보 API image에 `ktm-application-schema head`를 추가했다. command는 Python installation
  prefix의 package data graph만 읽고 application/Alembic migration module, DB, credential,
  cwd/source mount를 전혀 사용하지 않는다. 성공은
  `kor-travel-map.application-head.v1` 한 줄 JSON, invalid/ambiguous graph는 sanitized error
  JSON으로 fail-close한다.
- graph artifact는 source `alembic/versions`의 top-level `revision`/`down_revision` literal을
  AST로 읽어 생성하며 generator `--check`가 checked-in equality를 고정한다. top-level side
  effect 미실행, cwd decoy 무시, zero/multiple/unknown head 거부와 API image command/package-data
  결선을 unit regression으로 추가했다.
- 적대 리뷰 P1/P2를 반영해 generator와 image command 모두 root 도달성뿐 아니라 DFS cycle
  부재와 단일 terminal head를 검증하게 했고, Docker Manager와 같은
  `^[0-9a-z][0-9a-z_.-]{0,127}$` revision 문법의 경계·거부 회귀를 고정했다.
## 2026-08-06 (codex) — T-VN-41F1D-C0 Dagster storage migration artifact 완료

- 후보 image에 `ktm-dagster-storage head|migrate`를 추가했다. `head`는 이미지에 실제
  설치된 Dagster package graph만 읽어 JSON으로 attest하고, `migrate`는 같은
  `DAGSTER_HOME`/`dagster.yaml`/metadata DSN으로 `dagster instance migrate` 뒤
  `public.alembic_version` 정확히 한 행을 대조한다. Map application Alembic·source SHA는
  storage head 정본이 아니다.
- Compose one-shot을 webserver/daemon의 선행 조건으로 연결하고 모든 외부 overlay의
  순서를 고정했다. 실제 후보 image와 빈 격리 PostgreSQL에서 head, migration JSON,
  `public.alembic_version`이 모두 `29b539ebc72a`로 일치했다. Dagster package와 Docker
  runtime 회귀 pytest 666건(선택 provider 의존성 누락 3건 skip), ruff, Python 3.13 strict
  mypy, import-linter를 통과했다.
## 2026-08-06 (1) — T-VN-35 A-D: kind별 typed subtype 분해 (ADR-086)

- `feature.features`의 `detail` JSONB·`geom`을 **제거**하고 kind별 typed
  subtype 5종(`feature_places`/`_events`/`_notices`/`_routes`/`_areas`)으로
  분해. 응답용 `detail`/`geom`은 `feature.features_detailed` 뷰가 조립한다 —
  값이 두 곳에 있지 않으므로 drift라는 개념이 사라진다(shadow 병행 폐기).
  alembic 0084→0086, 세 revision 모두 단일 트랜잭션.
- **배타 arc**: core `UNIQUE(feature_id, kind)` + subtype `kind` 상수 CHECK +
  `(feature_id, kind)` 복합 FK. 한 feature는 최대 한 subtype에만 존재하고,
  subtype 행이 있는 동안 **core kind 변경이 FK 위반으로 막힌다** — provider
  upsert의 `kind = EXCLUDED.kind`가 kind를 조용히 바꾸던 구멍(실측)이 코드
  규율이 아니라 DB 계약으로 닫혔다. 35B "혼합 kind row 거부"의 구현.
- **원안 재해석 2건**(근거 실측): point subtype 미생성(coord는 4개 kind 공유라
  kind 상수 CHECK 불가 → 배타 arc 파괴, place 96.6%·event 82% non-null이라 거의
  모든 read가 조인 강제) · `parent_feature_id`/`sibling_group_id` core 유지
  (prod 사용 0행). price/weather subtype도 미생성(detail 전수 `{}`).
- **무손실 실증**(prod 복원본 731,765행, head→0083→head 왕복): place 729,972 ·
  event 1,246 · price 97 · weather 305 = **731,620행 md5 바이트 동일**, notice
  `valid_start_time` **145/145 동일**, 시각 외 notice 필드 전부 동일.
  마이그레이션 실측 시간: 전진 54s·역행 4m55s·재전진 1m10s.
- 대조가 결함 3건을 잡았다 — `jsonb_strip_nulls`의 중첩 null 소실,
  `EventDetail.sigungu_code` 컬럼 누락, **세션 TimeZone 의존성**
  (`to_jsonb(timestamptz)`가 GUC로 렌더 — 같은 공지가 Asia/Seoul `+09:00`,
  UTC `+00:00`, America/New_York `-04:00`). KST 고정 렌더로 해소.
- **notice 시간 CHECK는 두지 않는다**: provider가 미래 시행 공지를 철회하면
  end < start가 실재한다(실측 `start=2026-07-13/end=2026-06-02`) — CHECK를
  걸면 KREX notice ETL asset이 죽는다. `EventDetail`은 순서를 실제로 강제하므로
  event 쪽에만 CHECK를 둔다. 즉 "DTO 불변식이 있는 곳에만 CHECK".
- **적대 리뷰 2인 반영(P0×2·P1×6·P2×6)**. 가장 큰 둘:
  ① create validator가 정규화 결과를 `object.__setattr__`로 되꽂아
  `model_dump(exclude_unset=True)`에서 통째로 빠졌다 — 즉 정규화가 **한 번도
  반영되지 않았고** detail 없는 생성은 500, review 모드에선 그 change request가
  영구 승인 불가였다. 계약 판정을 write 경계(`subtype_params`, kind DTO 검증)
  하나로 모으고 위반은 `SubtypeDetailError`→422로 옮겼다.
  ② 0086이 geometry 없는 route/area를 조용히 건너뛴 뒤 `DROP COLUMN detail`을
  해서 **복구 불가능한 소실**이 됐다. 0084~0086에 선점검을 넣어 위반 행의
  feature_id와 함께 멈춘다(실패는 되돌릴 수 있고 소실은 되돌릴 수 없다).
- 죽은 인덱스 2종(`idx_features_yt_*`)은 이관하지 않는다 — 옛 경로에 값이 있는
  행이 prod **0건**(실제 위치는 `detail.payload.…` 1,481행)이고, 경로를 고쳐도
  유일한 소비자 `detail_selector`는 경로가 런타임 값이라 매칭 불가다.
- 성능: 술어는 subtype GiST를 타야 한다(뷰 컬럼을 술어에 쓰면 Hash Left Join
  2단 퇴화 — EXPLAIN 실측). admin bbox **4158ms → 411ms**.
- 응답 스키마는 user·service **바이트 동일**. admin은 `AdminFeature*Request`의
  `geom` 제거(받아서 payload에 넣고 적용하지 않던 필드) + create description.
- 배포 선행: orchestrator `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
  `0087_route_area_subtypes`로 올려야 한다(안 올리면 api가 DB를 건드리기 전에
  exit 1이고 dagster/daemon도 뜨지 않는다).
- 문서에만 존재하던 테이블 5종(`feature_place_details` 등, 참조 0건)을 제거했다.
  `feature_places`가 실제로 생기면서 이름이 겹쳐 purge·복구 런북 SQL이 위험해졌다.
- 배터리 판정 주의: `test_domain_command_ledger`의 docker fence 2건은
  **origin/main도 같이 실패**한다(같은 조건 baseline 2 failed / 23 passed 동일 —
  이 박스의 docker-in-docker 문제). `test_batch_dag.py`는 격리 실행에서 전량
  통과하고 전체 스위트 동시 실행에서만 흔들린다(docker.sock 경합).
  `test_h35_exact_surface_network_free_rehearsal`도 main에서 같이 실패한다 —
  "외부 접속 없음" socket guard가 컨테이너 안 testcontainers의 bridge IP를
  외부로 판정한다(CI는 localhost라 무관).
- **진짜 회귀 1건**(CI 통합 job에서도 동일 재현): `test_batch_dag` 5건이
  consistency 게이트에 막혔다. 뿌리는 `test_admin_feature_repo`의 잠금
  테스트가 rollback이 아니라 **커밋**한다는 것 — `migrated_engine`은 session
  scope 공유 DB다. 종전엔 core 행에 `detail`이 딸려 남았지만 subtype 전환 뒤엔
  core만 남아 세션 내내 F2("subtype 결측") 위반으로 떠 있었고, 뒤따르는 batch
  DAG의 게이트가 mv_refresh를 막았다. 모듈 쌍 bisect로 확정(그 조합만 5건
  재현, 나머지 3조합 전부 통과). 프로덕션 writer가 core+subtype을 한
  트랜잭션에서 쓰므로 시드도 그렇게 맞췄다 — **F2 축 자체는 옳으므로 완화하지
  않았다**.
- 겸사겸사 게이트 실패 메시지가 막은 축의 코드·건수·표본 id를 남기게 했다.
  `severity_max=ERROR`만으로는 운영자가 무엇을 고쳐야 할지 알 수 없고 그동안
  배치가 멈춰 있게 된다.
## 2026-08-06 (3) — T-VN-41F1J-A: response-loss 재개 증빙 보강

Manager 적대적 리뷰가 PinVi cancel HTTP 응답이 유실된 뒤 Map `consumed` state를 읽어도 journal에
기록하지 못해 재시도가 영구 정지하는 경계를 발견했다. Map lifecycle receipt의 capability generation을
`2`로 올리고, `consumed`/`finalized`에서만 immutable `canonical_unsafe_outcome`(exact `409`, code,
root job ID, cancellation ID)을 반환하도록 보강했다. 이 값은 fixture consume SQL이 canonical unsafe
cancellation root/member/error를 확인한 뒤에만 존재하므로 Manager는 DB 접근이나 cancel POST 재발송 없이
durable receipt를 확정하고 finalize를 재개할 수 있다.

fixture integration 2건과 API auth/OpenAPI target 8건이 새 DTO 포함으로 통과했다. generated full/service
OpenAPI와 admin TypeScript client type도 함께 재생성했다.

후속 재리뷰에서 event audit의 fixture kind join이 ordered partial index를 포기하게 만들고, join을
제거하면 raw SQL fixture event가 노출될 수 있음을 확인했다. 이를 읽기 예외로 우회하지 않고 migration
`0084`의 DB trigger로 fixture job event의 INSERT/job ID 변경을 거부했다. application writer 거부와
직접 SQL 제약을 함께 검증해 audit ordered partial-index 경로를 유지한다. `job_id` 단일 filter의
PostgreSQL 비용 계획은 기존처럼 최대 64행 bounded sort를 허용하며, join 도입이나 무제한 sort는 허용하지 않는다.
적대적 리뷰 1인은 새 trigger의 INSERT 책임과 기존 identity trigger의 job ID 불변 책임 분리,
두 SQL 경계 통합 검증과 planner 상한을 재검토해 GO로 판정했다.

PR CI가 검출한 `contracts/vnext/openapi-diff-v1.json`의 admin/service baseline SHA drift도
현재 generated artifact와 immutable outcome route를 대조해 재고정했다. Wave 2 대상 diff의
counts는 바꾸지 않았고 artifact fingerprint test 7건으로 freeze 갱신을 검증했다.
## 2026-08-06 (2) — T-VN-41F1J-A: Map durable fixture 구현·검증

- **수명주기/DB**: migration `0084_c6c_cancel_probe_fixtures`로 transaction ID를
  PK로 하고 fixture job/canonical cancellation을 각각 유일 FK로 결박했다. `armed →
consumed → finalized` 전이와 시각은 CHECK로, 동시 ensure는 transaction advisory
  lock으로 보장한다. 서비스 전 단계이므로 downgrade는 fixture 이력을 보전하지 않고
  table을 제거하며, 백업·복원은 최종 schema에서만 검증한다.
- **취소·격리**: 실제 PinVi cancel의 canonical
  `PIPELINE_CANCELLATION_UNSAFE` terminal 기록 transaction 안에서만 fixture를
  consume한다. fixture job은 일반 worker/claim/stale recovery/list projection에서
  제외하되, cancellation resolver의 lineage에서는 보이도록 두어 정확한 409 검증을
  방해하지 않는다. finalize는 cancellation history를 지우지 않고 job만 terminal로
  닫는다.
- **service 경계**: `ops:fixture` token과 `service:docker-manager` actor는
  ensure·receipt·finalize exact path/method에만 결박했다. PinVi `ops:cancel`과
  BFF/service token은 사용할 수 없다. full/service OpenAPI에는 audit 가능한 route를,
  user artifact에는 제외하며 capability generation은 2다.
- **리뷰 보강**: 적대적 리뷰 1인이 찾아낸 normal pipeline/ops/live event projection
  누출과 Alembic metadata 드리프트를 수정했다. fixture event를 강제로 만든 회귀에서
  generic event stream·live 최신 event·job별 live snapshot 모두 비노출이고, generic
  event writer도 거부한다. C7 attestation은 fixture token의 cursor-secret 재사용도
  거부한다. root env/API README도 3-token 계약으로 정정했다.
- **검증**: Postgres migration을 포함한 fixture integration 2 passed, `alembic check`
  clean, API auth 88 passed, settings/route/OpenAPI target과 export `--check`, strict
  mypy·ruff·import-linter 통과. 적대적 코드 리뷰 1인은 차단/주요 이슈 없음으로
  최종 판정했다. 첫 GitHub CI에서 확인된 정적 기대 4건(reserved kind, ops event
  projection, cancellation lineage CTE, admin/service OpenAPI baseline)은 설계를
  우회하지 않고 fixture 격리 계약을 직접 단언하도록 보강했으며 대상 회귀 5건이
  통과했다.
## 2026-08-06 (1) — T-VN-41F1J: Map-owned cancel-probe fixture 결정

- **관측/판정**: 신뢰된 F1D 한 회차는 `login=200 → etl_summary=200 → provider_sync=200 →
cancel=404`까지 도달했다. 따라서 Manager runtime, PinVi 세션, read surface는 원인이
  아니며, 설정된 정적 probe job UUID에 Map import job이 없었다. 후보를 다시 실행하지
  않고 fixture lifecycle을 고친 뒤 새 pair에서 재개한다.
- **결정**: fixture의 생성·상태·소비·종결은 Map 소유 DB와 전용 service OpenAPI가 소유한다.
  Manager는 transaction ID만 보내고 동적 job ID를 받는다. PinVi는 보유한 `ops:cancel`로
  보통 취소를 수행할 뿐 fixture 생성 권한을 얻지 않는다. `ops:fixture` token은
  Map↔Manager 전용이며, generic worker/recovery/read projection은 fixture kind를 보지 않는다.
- **검증 계약**: 취소 뒤 성공은 넓은 4xx/5xx가 아니라 정확한
  `409 PIPELINE_CANCELLATION_UNSAFE` 하나다. 이 응답과 canonical cancellation history를
  보존한 finalize까지 durable receipt로 남긴다. 상세는 ADR-084와
  `architecture/c6c-cancel-probe-fixture.md`가 정본이다.
## 2026-08-05 (13) — H43 배포 후 기준점·외부 사본 + H44 복원 드릴 1회차 완주

- **H43**: 값 전환 배포 후 기준점 `2026-08-05-h43-postdeploy-0083.dump`
  (489MB, manifest: head 0083 · features/aliases/public 각 731,765 ·
  pair_mismatch 0 · orphan 0) 채취 + **dev box 외부 사본 첫 반출**
  (`~/ktm-h43-external/`, sha256 대조 OK — 단일 host 사본 한계 첫 해소).
  정기화·retention·자동 반출은 manager **#148** 기안(배포 직전 fence dump
  관례 명문화 포함).
- **H44 드릴 1회차 완주**: 격리 PostGIS(WSL)에서 확장 4종 선생성 →
  `pg_restore`(확장 스키마 충돌 1건만 — 정상) → **manifest 완전 일치** →
  `session_replication_role=replica`로 alias 5건 결손 주입 →
  `missing_alias=5` 관측 검출 → 정본 재생성 replay → 4축 0·행수 원복.
  절차·함정(확장 충돌 정상 오류, 컨테이너 `/dev/shm` 64MB 병렬 집계 실패)을
  `docs/backup-restore.md` §10으로 고정, 주기 규약("migration 릴리스 뒤 +
  월 1회") 명문화 — 실행 트리거만 잔여.
- 부수: #956(live fixture 재표집)·#957(tasks 정리) 머지.
## 2026-08-05 (12) — live e2e fixture 재표집 (구표본 전멸 발견)

- ④ 착수 중 발견: `_fixtures.ts`의 FEATURE_IDS 150건(전부 구세대 `_w_`)이
  **prod에 전무** — 8/4 전면 재생성 + KMA weather 재설계로 표본이 값 전환
  이전부터 이미 사멸해 있었다(1:1 표기 전환 불가). 현행 prod에서 public
  kind 층화 재표집(30×5: event/notice/place/price/weather), 값은 UUID
  정본(새 표면 — dual-read가 URL/검색 수용). CURATED_IDS 40·IMPORT_JOB 3·
  KINDS_PRESENT·PRESENCE(issues 1730 외 0) 동반 갱신, e2e tsc green.
- 라이브 검증은 관례대로 저작-머지 후 n150 per-file 저부하 플로우에서 수행.
## 2026-08-05 (11) — NEW-5: dagster entrypoint DB 세대 기계 인터록

- dagster-entrypoint에 **읽기 전용** 게이트: DB alembic revision == 이미지
  head일 때만 기동(0083 배포 때 사람이 지키던 "api 먼저" 순서의 기계화 —
  ADR-083 유예 해소). DB가 뒤면 "deploy the api container first", chain
  밖이면 stale 즉시 실패, 연결 오류만 retry. EXPECTED_HEAD는 설정 시 추가
  대조(set-but-empty 거부), MIGRATION_MODE 거부 — api-entrypoint 규약
  lockstep. dagster.Dockerfile에 alembic.ini/alembic COPY(패키지는 기존
  runtime 의존, `.dockerignore` `**/__pycache__/` 동봉).
- **적대 리뷰 2인 반영**: F1(H, 양측 공통) — external overlay 3종의
  `depends_on: !override`가 base의 api(service_healthy) 의존을 지워 fresh
  up 3모드에서 게이트 경주 → overlay에 명시 재기입 + 실제 Compose resolver
  merged-config 테스트(3모드, `!reset` env_file overlay로 clean checkout
  해석). F2 heads 실패 증거 재실행 표출, F3 성공 경로 실 python 검증 복원,
  F4 branched alembic_version 전용 문구, F6 MODE 거부.
- 런북: dagster 게이트 실패 문구 4종·**"migration 배포 = dagster 이미지
  재빌드 의무" 불변식**(구세대 러닝 컨테이너는 다음 재시작에서 stale 영구
  크래시루프 — 지연 기폭)·장기 migration healthcheck 창(~220s) 한계·
  `--entrypoint sh` 디버깅 우회 기재. dm 권장 3건(base EXPECTED_HEAD
  기본값·dagster EXPECTED_HEAD 주입·runbook)은 dm#128 후속.
## 2026-08-05 (10) — T-VN-32C PR-2 prod 배포 — 값 전환 라이브

- **배포**(`8c5bdcf8`, dm#128 기록): 4-이미지(api·dagster·daemon·**ui** —
  admin types 반영) 빌드 → api 먼저 → 나머지, 4/4 healthy. migration 무추가
  (EXPECTED_HEAD=0083 유지). H30B 게이트는 기완료 확인으로 충족.
- **사후 검증(실측)**: 공개 상세 응답 feature_id = UUID 정본(v7)·legacy path
  해석 유지 · service batch echo 표기 보존(legacy in→legacy out, UUID in→UUID
  out) + `trip_card.feature_id == item echo` 등식(리뷰 F1 수정분) 정상.
- **curated snapshot 재물질화**: 활성(curated) 500건 전량 UUID 전환, 2회차
  멱등(0 rewrite). 비활성 334건 스냅샷은 materializer 커버리지 밖 동결
  보존(감사 표면 — legacy 잔존 의도).
- **잔여 후속**: ④ live e2e fixture 재생성(새 표면 기준, n150 per-file
  저부하) ⑤ PinVi user 스냅샷 재고정 PR(+NEW-2 CLI 플래그·NEW-3
  derivation_enforced 배선 동봉 — 진행 중) ⑥ dagster entrypoint
  EXPECTED_HEAD 기계 인터록(NEW-5, dm base compose 기본값 갱신과 동타이밍).
## 2026-08-05 (9) — T-VN-32C PR-2 머지 (#952) — 값 전환 코드 완결

- **머지** `8c5bdcf8` (CI 8/8, 적대 리뷰 2인 GO). 리뷰 라운드 요약:
  R1(응답 계약) F1(H) trip_card.feature_id ↔ item echo 등식 정렬(PinVi 런타임
  강제 등식 — 자체 테스트가 파열 조합을 정답으로 고정했던 사각), F2 대문자
  UUID fast-path, F3 dedup refresh cursor 정규화, F4-F7 문서/주석. R2(write·
  운영) H1(블로커) scope 해석의 라우터 선실행이 autobegin으로
  `session.begin()` 충돌 → 전건 500(실세션 라우트 테스트 부재로 은폐) —
  해석을 서비스 트랜잭션 안(lock 직후·fingerprint 전)으로 이동 + 실세션
  회귀 테스트, M1 batch 형식 위반의 per-item 격리 복원, M2 해석-후-
  fingerprint 명시 결정.
- **CI 실결함 2건**(로컬 배터리가 은폐): h35 rehearsal의 0063 고정 스키마에서
  PR-2 추가 `f.feature_uuid` UndefinedColumnError — 로컬은 network-free
  가드가 sibling-DB 연결을 먼저 차단해 "환경 산물"로 오판됐던 진짜 결함.
  matcher·mark-removals SQL을 pre-uuid 변형으로 분리(`pre_uuid_schema`
  파라미터, h35 CLI만 True — ADR-075 역사 표면 보존) + 변형 핀 unit 테스트.
  교훈: **가드가 먼저 끊는 실패는 그 뒤의 실결함을 은폐한다** — CI 토폴로지
  실행이 정본.
- **배포는 아직**: 게이트 = H30B 재검증 선행 → api → dagster → ui(types
  재빌드 필수) → curated snapshot asset 1런(etag churn 1회) → live e2e
  fixture 재생성 → PinVi user 스냅샷 재고정 PR(+유예 ②·NEW-3·NEW-5).
  관측 항목: 32B 기간 저장된 UUID 표기 scope 레코드 잔존(R2 L4).
## 2026-08-05 (8) — T-VN-32C PR-2: 응답 feature_id 값 UUID 전환 구현 (read 단일 원자 릴리스)

- **치환 코어**: `api/identity_projection.py`(response_feature_id/
  uuid_substituted_row — 결측 fail-close) + 전 read 표면 치환: features
  (bbox/in-bounds/search/nearby/by-target/상세/단건 weather·price card/area
  contained/상세 curations[]), weather(forecast target·변환기 4종 — timeline
  행은 anchor UUID 주입), public_views(beach/festival/marker + 상세 path
  해석 S12/S13), curations(공개·admin item/group/candidate·import preview +
  S11), curated(공개 detail 5종 + admin 뷰), admin_features(목록/지도/상세
  feature record/단건 card), mois_detail·dedup·enrichment(+repo projection
  additive). **불변**: cursor keyset 전부 legacy 축, batch/weather-batch
  echo·path echo·requested_feature_id·감사 레코드·2차 참조(parent/sibling)·
  operator raw lineage 보존 — 명문은 ADR-083 §결정 6 + integration-map §3.2.
- **write/scope 경계 해석 전수 배선**(조사 에이전트 전수 인벤토리 기반):
  P0 — S1 pipeline scope(fingerprint 전 bulk 해석·미해석 422
  FEATURE_REF_UNRESOLVED), S2/S3 service batch 2종(해석 조회 + 요청 표기
  echo — PinVi state=missing 오답 차단), W1 admin create의 UUID feature_id
  422(유령 PK 차단), W3 sibling_group_id feature-UUID 충돌 가드. P1/P2 —
  W2 parent 해석(+미해석 422), W4 dedup merge master 해석, W5-W8 curated/
  curation/CSV 정규화, S4-S10 검색·필터 정규화(admin q UUID fast-path =
  `uq_features_feature_uuid` 등가 — #639 회귀 방지), S11-S13 공개 path 해석.
  infra: `resolve_feature_identities_bulk`(고정 왕복 2회)·
  `legacy_id_for_filter`·`feature_uuid_in_use`·`is_canonical_uuid_ref`.
- **snapshot·계약**: curated snapshot 빌더 UUID화(재물질화는 기존 dagster
  asset 1런 — 158행<limit 500, etag churn 1회 계획 비용). OpenAPI admin/user
  재생성(description-only, **service 무변경** — PinVi config 회전 불요),
  types 2종 재생성+TSC green, openapi-diff baseline/핀 회전, ADR-083 작성.
- **테스트**: API 라우터 53건 정합+회귀 단언 4계열(로컬 1076 passed), 통합
  신규 13건(4계열 cursor gapless+UUID·값==저장 uuid·echo 등식·W1/W2/scope
  422·fast-path) + curated R6·EXPLAIN fast-path 등가.
## 2026-08-05 (7) — T-VN-32C PR-1 머지 + 쌍 PR 머지 + 0083 prod 배포 완주

- **Map PR-1 #950 머지** `2a8642bde10ef0cd384001fb72b1a3fc9fb5ae81` (CI 8/8,
  적대 리뷰 2인 최종 GO). **PinVi 쌍 PR pinvi#430 머지** `6325d814`(squash):
  golden 재vendor(merge SHA 원본, bytes `dc0a6595…` — nonderived_v1 포함) +
  `_UPSTREAM_MAP_COMMIT` 재핀 + nonderived_v1 독립 재계산 테스트(leaf·합산
  root·정렬) + contract-staleness에 shared golden 2종 drift 감시(유예 ③) +
  F4 모순 docstring 정정. 잔여 유예 ②(CLI `--accept-uuid-literals`)·NEW-3
  (`derivation_enforced` 배선)은 PR-2 동봉 — PinVi journal 2026-08-05 참조.
- **0083 배포 게이트 완주** (docstring 순서 준수): PinVi 배포(`6325d814`, 3
  컨테이너 healthy) → 사전 점검 쿼리 0/0(alias 731,731) → Map `2a8642bd`
  빌드(`t32c-2a8642bd`) → override `EXPECTED_HEAD=0083` 회전 → **api 먼저**
  (0082→0083 단일 트랜잭션 적용, healthy) → 사후 검증(head·CASCADE FK·UNIQUE·
  파생 CHECK 제거·`uuid_generate_v7()` v7 레이아웃 실측·mismatch/orphan 0) →
  dagster·daemon → checksum `derivation_enforced: false` 실측(731,733 — 라이브
  insert 흐름 정상). ui 이미지는 재빌드 안 함(#950 frontend는 type-only).
- **사고 1건(즉시 복구·DB 무접촉)**: `compose up -d pinvi-*`가 override 없이
  의존성 map-api를 base 설정(낡은 EXPECTED_HEAD=0078)으로 재생성 → entrypoint
  인터록이 기동 거부(설계 의도대로 fail-closed). override 포함 재기동으로
  복구. 재발 방지 메모는 dm#128 코멘트에 기록(override 상시 포함 + base
  기본값 갱신 후보).

**다음 한 작업**: **PR-2(응답 값 전환 — read 표면 단일 원자 릴리스, 설계 §4)**
— projection dual-select·깔때기 치환·write 수신 UUID 해석·admin fast-path·
curated 재물질화·e2e fixture·PinVi user/admin 스냅샷 재추출 + 유예 ②·NEW-3·
dagster entrypoint 기계 인터록(NEW-5) 동봉.
## 2026-08-05 (6) — T-VN-32C PR-1: 비파생 UUIDv7 정본 generator (0083) 구현·리뷰 반영

- **설계**: 4축 병렬 조사 워크플로(응답 표면 62곳 인벤토리/0080~0082 제약/
  PinVi 결합/내부 소비자) → 종합 설계. 값 전환은 PR-1(write측: generator)과
  PR-2(read측: 응답 값 전환 — 단일 원자 릴리스)로 분해. 채택: projection
  dual-select + 깔때기 치환(PR-2), 비파생 **UUIDv7**(app 정본
  `make_feature_uuid` + SQL 안전망 `feature.uuid_generate_v7()` 동일 레이아웃),
  0083은 파생 CHECK 2종 해제 + **선언적 사본 일치**(복합 UNIQUE + CASCADE
  복합 FK), PinVi 파생 등식은 계약 개정(golden derivation.rule + nonderived_v1
  벡터 — 기존 4벡터·root 무변경).
- **적대 리뷰 2건 반영**(둘 다 조건부 NO-GO → 전량 반영):
  - R1(정확성·DB): **H1** RI 트리거 이름순서 의존 실측(NO ACTION 복합 FK +
    CASCADE 공존 시 OID 자릿수 역전에서 DELETE 23503 — CI는 구조적으로 못
    잡음) → 복합 FK **ON DELETE CASCADE**. **H3** replica-mode orphan alias +
    재-INSERT의 조용한 사본 불일치(비파생 세계 순수 신규 계열) →
    `count_features_missing_identity`에 `alias_pair_mismatch` 축 신설 + 0083
    사전 점검 쿼리 명문화. **M1** admin add 경로 DO NOTHING의 RETURNING 존재
    = insert 증거 → sent/inserted 배선(죽은 검사 소생). **M2** 731,600행
    잠금 실측(UNIQUE 0.6s+60MB·ACCESS EXCLUSIVE) → CONCURRENTLY 인덱스 →
    USING INDEX·FK NOT VALID→VALIDATE 분해(0080 규율 준수). **M4** 배선 회귀
    테스트(upsert가 kwargs를 실제 전달 — conflict-update는 이름 변경으로
    short-circuit 회피). **M5** SQL v7를 set_byte 명시 관용구 +
    `x_extension.gen_random_uuid()` 한정으로 재작성(난수 비트 의존 제거 —
    초안의 이중 호출·byte8 zeroing 결함도 이 재작성에서 함께 소거).
    M3/L 서술 정정 일체.
  - R2(계약·rollout): nonderived 벡터 PinVi 독립 재계산 **일치 실측**(leaf·
    root·순서). **F6** checksum 응답에 `derivation_enforced: false` 세대
    표식(소비자 기계 판정 축). **F7** service 500 설명의 파생 문구 정정.
    **F1** PinVi cutover UUID 리터럴 자기-정본화를 **opt-in**
    (`accept_uuid_literals`, 기본 off) + `self_mapped_refs` 분리 집계·샘플로
    재설계(무검증 UUID 조용한 정본화 차단). **F8** dagster 선행 배포 금지
    (entrypoint에 migration 게이트 없음 — 코드 0083+DB 0082면 신규 write 전면 23514) — 0083 docstring·배포 절 명문화. F4 PinVi 문구 모순 정정.
- OpenAPI admin/service 재생성(user 무변경 — user-client 무접촉), freeze
  baseline·artifact sha 재고정, admin frontend types 재생성. perf gate에
  0083 covering index 등가 집합 반영.
- 검증: unit 2015 · API 1082 · 통합(경계/shadow/fence/perf/consistency) 56 ·
  전체 통합 sweep 896/9(실패 9 전부 전대비 기존·환경 — 기록), ruff·mypy
  --strict(143/65) clean.
- **배포 게이트(불변)**: PR-1 머지 → PinVi 쌍 PR(golden 재vendor 포함)
  머지+**배포** → Map 0083 배포(api 먼저 → dagster). 앱 단독 롤백 불가(0083
  downgrade 동반 — NOT VALID CHECK는 UPDATE에도 강제).
## 2026-08-05 (5) — H45 판정 완료: KMA 전 job SUCCESS 전환 + 근본 원인 2(평문 HTTP 사멸)

- **근본 원인 2 발견 절차**: #943 배포 후에도 실패 지속 → 같은 컨테이너·같은 키
  단건 프로브 20/20 정상과의 모순 → **scheme 대조 실측: `http://apis.data.go.kr`
  = ReadTimeout 25s hang, `https://` = 200/0.16s** — provider lib 3계열의 기본
  base URL이 전부 평문 http였고 data.go.kr 평문 경로가 사멸. mid만 생존(호출
  수 소수·간헐 통과), 단건 https 프로브 정상, job 첫 격자 즉사가 전부 설명됨.
- **정본 수정(ADR-044 경로)**: python-kma-api#23(`63e9bcda` — KmaClient/
  DataGoKrClient https) + python-airkorea-api#6(`a206282c` — 기본 URL 5종
  https), 각 142/122 passed. Map #948(`70c58576`) 핀 bump + **alembic <1.19
  천장 핀 동봉**(1.19.0이 2026-08-04 당일 릴리스로 CheckConstraint naming-
  convention 비교를 바꿔 `alembic check`가 이중 접두 diff 보고 — 1.18.5 통과/
  1.19.0 2회 재현 실측, floating dep의 두 번째 당일 파손. 1.19 적응은 백로그).
  dagster 2종만 재빌드·재배포(`h45b-70c58576`), 컨테이너 내
  `kma base: https://` 실측.
- **판정(재배포 후 첫 주기들)**: kma_weather_alerts **SUCCESS 23:15→00:15
  연속** · kma_short_forecast **SUCCESS 23:20→00:20 연속** · ultra_short_
  nowcast **SUCCESS 23:45** · ultra_short_forecast **SUCCESS 23:50** — **만성
  실패 KMA 4종 전부 전환**. 실적재 실측: feature_weather_values 555 →
  **56,310**(python-kma-api **55,755** 유입 개시), weather features 187 →
  **305**(KMA 자체 grid feature 생성 — own-grid Phase 1 prod 실작동 개시).
  #943의 경계 재시도는 전환 이전 구간에서 텔레메트리 실작동을 실증했고
  간헐 장애 방어층으로 유지된다.
- **airkorea 잔여**: https에서도 FAILURE — 단 원인이 hang이 아니라 **실응답
  HTTP 504 `SERVICETIMEOUT_ERROR`(코드 05)** = AirKorea 백엔드 자체가
  게이트웨이 뒤에서 죽어 있는 상태(수동 프로브에서 504→수분 후 200 회복도
  실측 — 간헐). 재시도 분류·소진·전파가 설계대로 동작. **코드 소관 아님 —
  upstream 회복 시 스케줄이 자체 수렴**. 관찰 항목으로만 유지.
- **H42 최종 수치 고정(2026-08-05 00:30Z)**: features **731,724** = public
  731,724 = aliases 731,724(1:1 불변 유지) · weather_values 56,310 ·
  curation_items 4,910(링크 4,640) · CSV 미해석 270(구성: H31 구조 확정 103 +
  visitkorea/khoa 스케줄 수렴 대기 — 대기분은 상시 운영 수렴). **H42 판정
  완료 — 41C prod enable 선행 조건 충족**. H45도 판정 완료로 종결(백로그
  ①③④는 tasks 유지, ② lib 정본 https는 이번에 완료).
## 2026-08-05 (4) — prod 배포(Map c0afaa4e·PinVi 3ff54b8b) + 32C cutover checksum 일치

사용자 지시("진행")로 배포 게이트를 직접 열었다. 전 과정 실측 기록:

- **Map 배포**: `~/regen-build/c0afaa4e/` export 빌드(4 이미지, 리비전 라벨 실측) →
  write path 정지 → **write-fence rollback 기준점** `2026-08-05-prefence-0082.dump`
  (sha `d367fbd1…`, features 731,600 — H43 잔여 이행, ADR-075 정합) → 태그 회전
  (`prev-2b2dee95` 롤백 보존) → api 재기동. entrypoint가 `0079→0082` 자동 적용:
  **UUID backfill 731,600/731,600(100%)·중복 0·aliases 731,600(1:1)**, EXPECTED_HEAD
  게이트 통과(durable override `~/map-deploy-override.yml`=`0082` + geo/opinet env
  보존 — compose 정본 갱신은 dm#128 요청). 검증: 공개 표면 `feature_uuid` 병행
  노출 실측, alias-map checksum 표면 가동(root `8bd9534a…`), admin/quarantine/ops
  smoke green. 주의 실측: 0080 backfill(수 분)이 healthcheck 유예보다 길어
  일시 unhealthy 표기 — 컨테이너는 정상, migration 완료 후 healthy 복귀.
- **PinVi 배포**: 함정 실측 — `.env` `PINVI_REPO_DIR`가 frozen release export
  (`pinvi-release-4943282`)를 가리켜 git 체크아웃 갱신만으로는 **구코드가
  빌드**됨(1차 배포에서 신규 모듈 부재로 발각). 새 export `pinvi-release-3ff54b8`
  - `.env` `PINVI_REPO_DIR`/`PINVI_SOURCE_REVISION` 갱신으로 수리, 리비전
    `3ff54b8b` 실측·`20260804_0049` 적용. sync enable은 `false` 유지(41C 게이트).
- **32C cutover(dry→real)**: `pinvi-feature-uuid-cutover` — **양 저장소 독립
  checksum 일치**(PinVi 재계산 root `8bd9534a…` = Map 서버 root, alias_count
  731,600). trip_day_pois **26행 UUID shadow 채움**(매칭 4 ref), unmatched 10건은
  전부 e2e 합성·재생성 전 구세대 참조(NULL 유지+보고 — 설계 검증 그대로).
  발견: checksum 호출 ~21s(731k merkle) vs PinVi 기본 timeout 10s →
  `PINVI_KOR_TRAVEL_MAP_TIMEOUT_SECONDS=90` 주입으로 해소(정본화 백로그).
- **H42 잔여 소화**: CSV5 재import(authoritative replace) 486행 전량 재통과 —
  미해석 290→**270**. 잔여 구성: lighthouse 103(H31 취소로 구조적 확정),
  tourism 120(visitkorea 미적재), arboretum 29·heritage 18(스케줄 수렴 대기).
  quarantine/admin/공개 smoke green(위). **H45 판정 개시**: 신규 이미지에서
  재시도 텔레메트리 실작동 실측(`upstream retry … grid 60,127: attempt 1/2`),
  첫 주기 alerts·airkorea는 upstream 열화 창과 겹쳐 FAILURE — 수 주기 관찰 계속.
- **32C 다음(값 전환 tail)**: checksum 게이트 통과로 Map 응답 `feature_id` 값
  UUID 전환·비파생 generator 채택·0080 CHECK/0079 트리거 재평가 +
  user/admin-detail 스냅샷 재추출이 열렸다 — 별도 PR(적대 리뷰 2).
## 2026-08-05 (3) — H45 착지(#943)·user-client 수리(#944)·H43 기준선 dump

- **T-VN-H45 머지**: #943 `8c74d911`(8/8 green). 재리뷰 판정 — 리뷰 1 GO
  ("요구보다 나은 반영": retries=1 산술 정산·predicate 쿼터 거부·예산 방어),
  리뷰 2 조건부 GO → 필수 N-1(mid 비대칭 회귀: retries=1만 받고 경계 재시도
  부재로 유일 성공 경로가 4→2 시도 약화) 반영: mid land/temp 2 호출 래핑으로
  전 경로 경계당 4 시도 균일화. 권고 반영: 경계 backoff 2→15s(예산이 비용
  120s/run으로 상한 — lib 내부 ~2s 소진과 독립 시행화), kma 실 lib 계약
  테스트(retryable/failure_kind 값 고정 — 무음 해제 방지), on_retry 예외 격리
  (logger 실패가 원 예외를 못 덮게), runner 2곳 kwargs 단언, coalesce 후속
  백로그. 판정 음성 시 다음 수 순서를 etl §8.1에 명문화(backoff 상향 → 격자
  축소 → lib 정본). 최종 553 passed·mypy strict 144·ruff·lint-imports clean.
- **[main 잠복 결함 발견→수리] user-client types 재생성 누락**: #940이 user
  표면(feature_uuid 병행 노출 additive)을 바꾸며 admin frontend types만
  재생성 — `packages/kor-travel-map-user-client/src/types.ts`가 stale로 main에
  들어가 **모든 코드 PR의 type-check가 실패**하는 상태였다(#943에서 실측,
  로컬 재현으로 툴 버전 요인 배제). #944로 재생성만 분리 머지. 교훈: OpenAPI
  user 표면 변경 시 admin frontend와 user-client **두 곳** types 재생성.
- **T-VN-H43 기준선 dump**: n150 `~/backups/kor-travel-map/
2026-08-05-h43-baseline.dump` — 435MB/54.7s, sha256 `717790c0…8a04e286`.
  manifest 실측: head `0078` · features 731,599 · source_records 732,279 ·
  source_links 731,599 · weather_values 555 · **public_api_keys 1**(소실 재발
  방지 스코프 확인). `pg_restore -l` 690항목 판독. live dump라 3종 묶음 정합은
  비보장 — vNext cutover rollback 기준점은 배포 직전 write fence 뒤 별도
  생성(runbook §9 신설, n150 수동 절차 정본화). 실복원 드릴은 H44.
- dm#128 갱신 코멘트: 다음 배포 이미지는 `8c74d911` 이후 권장(H45 포함,
  head 변동 없음 `0082`).
## 2026-08-05 (2) — T-VN-H45: KMA/airkorea 만성 실패 근본 원인 격리 + 강건화 구현

- **원인 확정 절차**: KST 자정 쿼터 리셋 후에도 실패 지속 → dagster 컨테이너
  내부에서 동일 key로 4개 upstream(초단기실황/단기예보/특보/에어코리아) 직접
  프로브 전부 HTTP 200 정상(20격자 실측 p50 0.10s·max 0.27s·20/20) → 그런데
  같은 시각 ultra job은 또 실패. 즉 key·쿼터·upstream 무결인데 job만 죽는다
  = **구조 결함**. 실패 run(6d73bd70) 스택 실측: `raise_for_kma_network_error`
  → `KmaRequestError(retryable=True, network)` — 지배 실패는 재시도 가능
  분류가 맞다(리뷰 1 H-1 요구 증거). kma_weather는 격자 N(187+)건을
  부분실행-금지로 순차 호출, 예외 1건이면 step 실패 → step 재시도 3회는
  전량 재실행. 시도당 생존확률 p^N — 간헐 오류율에서 사실상 0. mid만
  살아남는 이유(호출 수 소수)와 단건 프로브 정상도 이 모델이 설명.
  (부수 실증: airkorea 프로브 중 504 `SERVICETIMEOUT_ERROR` 실물 관측 후
  수분 내 회복 — 간헐성의 직접 증거.)
  **정정(적대 리뷰 1·2 H)**: 초기 서술 "lib 재시도 없음"은 오류 — kma/airkorea
  lib은 transport 재시도(기본 retries=3 → 4 시도)를 이미 소유한다. 결함은
  "재시도 부재"가 아니라 **경계 재시도의 부재 + 레이어 산정 없는 timeout**.
- **수정(H45, 리뷰 2건 반영판)**: 신규 `dagster/upstream_retry.py` — 단건
  호출 경계 유한 재시도 **attempts 2**(지수 backoff 2→20s cap) + client 주입
  `retries=1`로 **레이어 곱셈 정산**(경계당 HTTP 상한 2×2=4 — 도입 전 lib
  단독 4와 동일). **quota/rate_limit 재시도 금지**(kma resultCode 22 계열 —
  일일 한도 보호와 충돌 방지, airkorea `AirKoreaRateLimitError` 제외).
  **run 재시도 예산 8**(상관 장애 early abort — 소진 후 즉시 전파). 재시도·
  예산 소진 **warning 텔레메트리**(kma는 context.log, fetcher는 module
  logger). 적용 4경계: kma 격자(async — backoff만 loop 양보), airkorea
  stations(리뷰 1 M-3 — air_quality asset이 먼저 읽는 경계)·시도×페이지,
  kma alerts 페이지(lazy는 경계 안 list 소진). timeout 주입은 4 생성 지점
  전부(스케줄 resource 2 + admin 재적재 runner 2 — 리뷰 1 M-4)·기본 20s
  (병적 상한 187격자 ≈ 4.4h < run 한도 6h — 산식은 settings·etl 문서).
  airkorea 분류 degrade는 warning으로 가시화 + 실 lib 이름 계약 테스트.
  **부분 실행 금지·원예외 identity·cursor 비전진 경로 불변**.
- 검증: unit 18종(분류·쿼터 거부·backoff cap·예산·원예외 identity·
  cancellation 1회 호출/무sleep — 리뷰 1 M-6 변이 보강·상수 핀) + asset
  배선 회귀 2종 + fetcher 회귀(재시도 수렴·비재시도 즉시 전파·kwargs 도달
  단언 — 리뷰 2 M-5) + 실 lib 이름 계약. `.env.example`·
  `docs/etl/kma-weather-etl.md` §8.1 정산 문서화(리뷰 2 M-7).
- 잔여(의도적): 동일 결함군 khoa 등 잔여 다건 루프 fetcher 확대는 배포 후
  실측 보고 결정. **provider lib 정본 수정 백로그**(리뷰 2 M-8 권고):
  python-kma-api의 resultCode 22 `retryable=True` 오분류 + 200-body XML
  envelope 경로는 lib PR로 — tasks.md H45 절 기록.
- prod 효과는 다음 이미지 배포 게이트(dm#128 타이밍) — 배포 후 스케줄
  SUCCESS 전환이 판정 기준. H42의 KMA axis는 H45로 분리.
## 2026-08-05 (1) — H42 중간 실측: MOIS 수렴 완전·opinet 완료·공개 API key 소실→재발급

- **MOIS bulk 수렴 완전**: source_entities 702,955 = linked 702,955 = distinct
  features 702,955 (3중 일치 실측). run 자체는 `Exceeded maximum runtime of
21600 seconds`(dagster 6h run 한도)로 FAILURE 마감이지만 데이터는 완주 —
  향후 동급 bulk는 run tag `dagster/max_runtime` 상향 또는 한도 재검토 필요.
  chain 로그의 licenses "비정상 종료"는 이 한도 마감의 표식.
- **opinet 완료**: 용인·수원 bbox(126.92,37.05,127.45,37.38) 934건, job
  SUCCESS. 주유소는 kind='place'/category 06020000으로 적재되어 공개 표면
  bbox+category 조회 실측(3건 반환). opinet chain은 1차 8h 대기 한도 초과
  자멸 후 24h로 상향 재기동해 완주.
- **[결손 발견→복구] 공개 API key 전면 소실**: `ops.public_api_keys` 0행 —
  재생성 때 소실된 뒤 재발급 없이 방치되어 **공개 사용자 표면 전체가 401**
  상태였다. admin proxy secret 경로(`POST /v1/admin/public-api-keys`,
  actor=claude-h42-restore)로 재발급(label `h42-regen-restore`, id `7e8224d0…`,
  hint `fOda8M`). **원문 key는 n150
  `~/.secrets/kor-travel-map-public-api-key`(600)에만 저장** — 채팅/로그
  무노출. H43 백업 스코프에 `ops.public_api_keys` 포함 필수(이번 소실의
  재발 방지) + key 소비자 결선은 사용자 결정 대기.
- **공개 표면 smoke**: 발급 key로 features bbox(수원 MOIS 음식점 3건)·opinet
  주유소 3건 반환. `feature.public_features` = 731,599 전행 공개(trusted-link
  게이트 통과) — unlinked source_entities **0건**(전 provider).
- **weather 축 실태**: feature_weather_values 555행 전부
  `python-krex-api/rest_area_weather` — **KMA forecast 값 0**. forecast 앵커
  NONE은 KMA-술어상 정상 동작. 원인은 KMA 4종(short/ultra×2/alerts)+airkorea
  의 매주기 upstream transport 실패(`KmaRequestError: KMA request failed`,
  `data.go.kr request failed`, `AirKoreaNetworkError: timed out` — env key
  결선은 존재). KST 자정 쿼터 리셋 후 스케줄 수렴을 감시 중 — 리셋 후에도
  지속 실패면 key/계약 축으로 재조사.
- 부수 관측: `feature_operation_reconciliation_sensor`가 KNPS registry
  conflict(`KNPS fetcher/asset resource dataset snapshot 불일치`,
  `feature_place_knps_points_job`) 관측 오류 1건을 반복 보고 — H42 판정 시
  재확인 대상.
## 2026-08-04 (10) — T-VN-32 쌍 PR 착지 (Map #940 + PinVi #428) + ⓪ L7 스캔 0건

- **Map #940 머지** `e12494bd`(8/8 green). 막판 CI 2건 해소: ① codex #935의
  `0079_cache_target_writer_drain`과 두-head 충돌 → 본 체인을
  `0080_feature_uuid_shadow`→`0081_uuid_dual_read`→`0082_legacy_write_fence`로
  재번호·재부모화(내용 무변경, 참조 11파일 일괄, 단일 head 실측 + 31 passed).
  ② frontend `gen:types` 미재생성(`target_feature_uuid` additive) 재생성.
- **PinVi #428 머지** `3ff54b8b`(squash — merge commit 금지 저장소). 유예
  마무리 실행: alias golden 핀 `_UPSTREAM_MAP_COMMIT`=merge SHA +
  contract-pin-consistency에 alias 핀 checkout·byte-diff 단계, service
  snapshot 재추출(sha `144b4335…` — merge SHA 원본과 sha256 동일 실측,
  cache-target operation diff **무변경** → codex n150 paired live proof 유효),
  `_ARTIFACT_COMMIT`·`_FUNCTIONAL_OWNER_COMMIT`(ancestor 게이트: 직전 owner
  `9b945ce8…`는 merge SHA의 ancestor)·config·`.env.example` 회전. 검증: 계약
  3본 15 passed + 필터 155 passed + ruff clean.
- **⓪ L7 사전 스캔**(TCP read-only): prod `feature.features` 467,697행 중
  canonical UUID 형태(36자 hyphenated) legacy `feature_id` **0건** — dual-read
  UUID-정본 우선 해석의 shadowing 여지 없음. cutover 전제 클리어.
- **배포 결선 예고**: docker-manager#128 — 다음 Map 배포 시
  `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를 `0078…`→`0082_legacy_write_fence`
  로, PinVi sync enable 시 `…EXPECTED_OPENAPI_SHA256`/`…EXPECTED_SOURCE_
REVISION` 회전(Map 먼저 순서 제약 — 역순은 fail-close). 기존 #109/#111/#114
  는 CLOSED 확인.
- 병행: H42 MOIS licenses feature job 적재 중(총 467,697 증가 중), opinet
  chain은 MOIS 종료 marker 게이트 대기.
## 2026-08-04 (9) — T-VN-32C 적대 리뷰 1 반영 (H1/H2/M3/M4/L6/L7)

미머지 branch이므로 0080/0081은 새 revision 없이 제자리 수정.

- **H1 [차단급] alias 파생 CHECK 축 오류**: 0080
  `ck_feature_aliases_uuid_dual_derivation`이 `f(feature_id)` 축이었는데 32C
  checksum 계약은 `f(alias)` 축 — `alias ≠ feature_id`인 독성 행
  (`uuid=f(feature_id)`)이 DB를 통과해 이관 표면 전체를 영구 fail-close시키고
  0081 fence가 그 행 삭제까지 막는다(리뷰어 실측). CHECK를
  `f(alias)` 축으로 재축 + `ck_feature_aliases_legacy_identity`
  (`alias_kind <> 'legacy_feature_id' OR alias = feature_id`) 신설 — 닫힌
  kind 기간의 실질 불변식을 DB로. 모델 metadata 동반 정합. 독성 행 2계열
  INSERT가 23514로 거부됨을 실측하는 회귀
  (`test_poison_alias_rows_are_rejected_by_db_checks`) 추가, identity
  boundary drift 단언은 CHECK 2종 대안 일치로 재정의(보고 이름은 PG 내부
  순서 소관).
- **H2 [높음] COLLATE "C" 회귀 방어 0**: conftest PostGIS가 alpine(musl,
  byte==default 순서)이라 COLLATE 제거 변이가 생존. glibc 이미지
  (`postgis/postgis:16-3.5`) 전용
  `test_alias_map_collation_glibc.py` 신설 — 다국어 9행 세트(대/소문자·기호·
  é·가나다·f_*/feature: 계열)로 ① keyset 페이지 순서==checksum 정렬==byte
  순서 단언(COLLATE 제거 변이는 en_US 순서로 갈라져 사망) ② default와
  `COLLATE "C"` 순서가 실제로 다름을 단언(같으면 판별력 없음을 사유 명시
  skip — musl 가드).
- **M3**: `feature_aliases`에 `BEFORE TRUNCATE … FOR EACH STATEMENT` 거부
  트리거(`trg_feature_aliases_no_truncate` — 저장소 `trg_*_no_truncate` 패턴)
  0081 추가 + TRUNCATE 거부 회귀.
- **M4**: 0081 docstring의 "구조적으로 존재하지 않는다" 과장 정정 —
  trigger-respecting 세션 한정, `session_replication_role=replica`(superuser)
  우회 가능, `count_features_missing_identity` 정기 관측이 방어선. tasks.md
  32C 운영 점검 목록에 반영.
- **L6**: alias UPDATE fence 단언을 분기 고유 문구("행은 불변입니다")로 좁혀
  DELETE fence와 구분(변이 등가성 해소).
- **L7**: 32C 잔여 절차에 ⓪ "cutover 전 legacy feature_id의 canonical UUID
  형태 값 실재 스캔 1회"(경계 해석 UUID-정본 우선의 shadowing 확인) 추가
  (tasks.md·resume.md).
- freeze artifact 무영향(0080/0081 CHECK·트리거는 전환기 구조물 — artifact
  bytes 미변경, unit sha 게이트 green 확인).
- **검증(CI-parity python:3.13 컨테이너)**: unit(alias_map 8 + freeze
  artifact 7) 15 passed · fence(독성 행·TRUNCATE 포함 12)+32A shadow
  migration+identity boundary+alembic 일관성 **33 passed** · glibc collation
  판별 신규 모듈 **2 passed**(skip 아님 — glibc에서 default≠"C" 순서 실측 +
  keyset/checksum이 byte 순서 유지) · ruff clean.
## 2026-08-04 (8) — T-VN-32C(1/2) alias-map 이관 표면·checksum 계약·legacy write fence

> PinVi 쌍 branch `feat/tvn32c-uuid-alias`(pinvi 저장소)와 한 쌍이다. rollout이
> 32C 안에 둔 "양 저장소 checksum 일치 → Map 응답 UUID 전환"은 두 PR 머지·이관
> 실행 뒤에만 가능한 운영 게이트라, 본 커밋은 32C의 전반부(표면·계약·fence)다.

- **"DB-to-DB 이관" 표면 판단**: ADR-068 결정 4의 "PinVi는 검증된 alias map으로
  소비 데이터를 DB-to-DB 이관"은 런타임 REST alias lookup(결정 3이 금지)이
  아니라 **Map DB의 alias 전량을 PinVi DB로 옮기는 bulk 계약**이다. PinVi의
  기존 Map 소비는 전부 HTTP(OpenAPI 경계 — CLAUDE.md)이고 cache-target
  reconciliation이 이미 service 표면에서 snapshot+merkle 대조를 쓰므로, 이관
  표면도 **service read 2종**으로 착지: `GET /v1/service/feature-alias-maps`
  (canonical keyset 페이지, limit≤1000) + `/checksum`(전체 merkle root·count).
  route_policy SERVICE + `require_service_token` 게이트, read-only라
  feature_operation_registry 등록 대상 아님(registry는 write 소관). ADR-068
  결정 3의 "alias lookup은 전환·복구 경계에서만" — 바로 그 경계다.
- **feature-alias-map-v1 checksum 계약** (`core/feature_alias_map.py` 순수 +
  `contracts/feature-alias-map-v1-golden.json` — cache-target-source-v1 golden
  패턴): row=(alias, feature_uuid, alias_kind). alias는 trim·비어있지 않음·
  **NFC 정규형 아니면 거부**(정규화하지 않음)·≤256자, uuid는 canonical
  lowercase hyphenated 36자만, kind는 닫힌 집합('legacy_feature_id').
  leaf = `sha256("KTMFAMLEAF\0"‖u32be(len alias)‖alias‖u32be(len kind)‖kind‖
uuid raw 16B)`, 정렬은 alias UTF-8 byte 오름차순(중복 거부), node =
  `sha256("KTMFAMNODE\0"‖L‖R)` 홀수 승격, 빈 map = `sha256("KTMFAMEMPTY\0")`.
  파생 검증(`feature_uuid == uuid5(namespace, alias)`)은 checksum과 분리된
  별도 함수 — 둘 다 통과해야 "검증된 alias map". golden은 ASCII 2 + é/가나다
  (NFC byte-order 비교차) 4-vector + empty/odd-promotion root. PinVi가 vendored
  사본으로 **독립 구현 재계산** 대조(`app/core/feature_alias_contract.py`,
  namespace도 상수 복사가 아니라 basis 문자열 재파생).
- **repo 층** `infra/feature_alias_map_repo.py`: keyset 페이지(`COLLATE "C"` —
  NFC byte order와 동일)와 전량 checksum. 조회 행이 canonical/파생 계약을
  위반하면 `FeatureAliasMapIntegrityError`로 fail-close(HTTP 500
  FEATURE_ALIAS_MAP_INTEGRITY) — DB 층 보장(0079/0080/0081)이 뚫린 상태에서
  이관을 계속하지 않는다. 페이지 pull 중 write drift는 소비자 root 불일치
  재시도로 감지(window 동안 fence 유지는 rollout 소유).
- **legacy write fence** (alembic `0082_legacy_write_fence`, 전부 DB 트리거
  fail-close): ① alias map 불변 — `feature_aliases` UPDATE 전면 거부 + 직접
  DELETE 거부(참조 feature가 이미 사라진 FK CASCADE 경유만 허용 — removal
  manifest "alias 유지" fence). ② identity 불변 — `features.feature_id/
feature_uuid` UPDATE 거부(재키잉은 soft-delete+신규 행). ③ legacy-only
  write(uuid 없는 행 저장)는 기존 0079 fill 트리거+NOT NULL+0080 CHECK로
  **구조적으로 불가능**함을 유지 — 32B가 "32C 재평가"로 이월한 0079 트리거
  2종은 **유지** 결정(fill은 CHECK가 요구하는 유일값만 쓸 수 있어 우회로가
  아니라 강제 메커니즘, AFTER alias는 INV-068-01 원자 보장; 제거 시 무결성
  이득 없이 raw seed 37파일만 파괴). _\*f_* 신규 발급 경로 fence는 의도적으로
  32C 잔여로 순서 고정_* — 발급 중단은 비파생(비저장) generator 채택과
  불가분이고, 그 채택은 신규 행 응답에 UUID 값을 조기 누출시켜 rollout의
  "checksum 일치 후 응답 전환" 순서를 위반하며, provider upsert idempotency
  재결선(파생 resolve 또는 T-VN-33 자연키)이 필요하다. 부속: `COLLATE "C"`
  keyset index(모델 metadata 동반 — alembic check 게이트 정합).
- **artifact**: OpenAPI admin/service 재생성(user 무변경 — sha 동일 확인),
  `openapi-diff-v1.json` baseline sha 재고정 + revisions 개정(이관 표면은
  Wave 2 목표 diff 항목 아님 — 존치·폐기는 T-VN-39 removal manifest 소관,
  ADR-068 enum/status 항목은 32C 잔여 목표로 존치). unit artifact sha 상수
  재고정. freeze DDL(target-schema-v1)은 무변경 — fence는 전환기 구조물.
- **32C 잔여(쌍 PR 머지 뒤 순서)**: ① PinVi 배포 + `pinvi-feature-uuid-cutover`
  실행(검증된 이관) → ② 양 저장소 checksum 일치 확인 → ③ Map 응답 `feature_id`
  값 UUID 전환 + 비파생 generator 채택 + 0080 CHECK·0079 트리거 제거 재평가 →
  ④ PinVi vendored snapshot 3종(user/service/admin-detail) 재추출·핀 갱신(핀은
  Map merge SHA — rollout pinvi_snapshot_revendor 3×yes). legacy ID·FK 체인
  물리 제거는 T-VN-39 removal manifest 그대로.
- **검증(CI-parity python:3.13 container, PostGIS 16-3.5 testcontainers)**:
  ruff check clean · mypy --strict main(140)/api(63) clean · lint-imports 4
  kept · unit+lint 1,991 passed(신규 test_feature_alias_map 8 포함 — 잔여 2
  실패는 test_docker_dagster_runtime의 docker CLI 부재 env 한정, 본 branch
  무접촉 파일) · api 패키지 1,076 passed(신규 test_feature_alias_maps_router
  7 포함, coverage 78.84%≥70) · export --check drift 0 · 신규 통합
  test_legacy_write_fence 12 passed(기록 정정 — 적대 리뷰 F4; alias UPDATE/직접 DELETE 거부·cascade
  허용·identity 불변·same-value 통과·fill 원자성·checksum 독립 재계산 일치·
  keyset 완전 순회·파생 불일치/비-NFC fail-close·downgrade 왕복) + alembic
  metadata 일관성 2 passed(COLLATE index의 반영 정합은 컬럼 index 선언으로
  해소 — models.py 주석). 32B-명명 회귀 세트(fence·32A migration·feature_repo
  load/primary·freeze·alembic 일관성/upgrade·공개 view 2종·notice 2종·nearby·
  in-bounds·perf tier1·h35) **137 passed / 1 failed** — 유일 실패
  `test_h35_exact_surface_network_free_rehearsal`은 loopback-only socket
  guard가 DooD(docker-socket-in-container) 환경에서 testcontainers DB host가
  loopback이 아니라서 발화한 것(같은 run의 나머지 h35 계열은 전부 green,
  본 branch 무접촉 파일 — CI ubuntu 직결 docker에서는 loopback이라 무해).
  **전체 통합 sweep 완주**: 1차 run 12 failed/881 passed에서 32B 원판
  identity boundary 2건이 0081 fence의 의도 동작과 충돌함을 발견해 재정의
  (별도 커밋 — UPDATE drift는 fence 선행 거부 + 파생 CHECK 관측은 INSERT
  drift 경로로 이전, alias 결측 관측은 fence 트리거 일시 해제 시뮬레이션)
  → 최종 run **10 failed / 883 passed (0:21:28)**. 잔여 10건 전부 env 분류:
  ⑴ `test_dedup_with_kraddr_geo_live` 5건 — 32B가 base 재현으로 명시한
  live kor-travel-geo 인증 미결선 env 그대로, ⑵ `test_domain_command_ledger`
  2건 — 검증 컨테이너에 docker CLI 부재(detached docker effect), ⑶ h35
  network-free 1건 — DooD loopback guard(상기), ⑷ pipeline
  cancellation/projection 2건 — 32B가 base 재현으로 명시한 lock-poll env·
  부하 flake 계열(두 run에서 같은 모듈의 다른 테스트가 번갈아 실패 —
  단독/저부하 green 계열). 32C 관련 실패 0.
## 2026-08-04 (7) — T-VN-32B Map consumer-first dual read/write

> 사용자 지시(작업 중 우선순위 변경): 호환성·기존 계약 유지보다 **설계적
> 우월성·최적화·유지보수성** 우선, 대대적 코드/schema 변경 허용. 단 PinVi 대면
> 표면의 배포 순서는 rollout artifact(consumer-first)를 유지하고, freeze
> artifact와 어긋나는 변경은 artifact 개정을 같은 커밋에 포함한다. 이에 따라
> 초기 additive-최소 구현을 세 곳에서 강화했다(아래 ①경계 전면 적용·④CHECK
> fence·notice ids 표면 제거).

- **경계 alias 해석 — 단일 메커니즘, 전 경로 적용**: `infra/feature_identity.py`
  신설 — `resolve_feature_identity(session, ref)`가 legacy `f_*` alias·
  canonical UUID 양쪽 참조를 `FeatureIdentity(feature_id, feature_uuid)` 정본
  키 쌍으로 해석(UUID-정본 조회 우선, miss 시 alias fallback — legacy id가
  UUID처럼 보여도 놓치지 않는 결정적 순서). 형식 계약(`validate_feature_ref` —
  빈 문자열/공백 패딩/256자 초과)은 422, 미해석은 404.
  `kortravelmap.api.feature_ref.resolve_feature_ref_or_error` 공용 헬퍼를 모든
  feature `{feature_id}` 경로 handler 첫 줄에 배치 — user detail·sources·
  observations history·weather·price·contained-features / admin detail·
  revision·weather·price·PATCH·DELETE·deactivate. 해석 뒤 내부 전달·조인은
  정본 키로만(ADR-068 결정 3 "alias lookup은 경계 전용"). 해석 성공이 행
  존재를 함의하므로 operator lineage의 별도 존재 확인(`_operator_feature_or_404`
  - `get_feature_row` 쿼리 1회)은 제거 — 경로당 쿼리 수 동일하게 유지하면서
    메커니즘은 하나로 수렴. auth 의존성보다 뒤(handler 본문)라 FastAPI 의존성
    평가 순서에 의존하지 않는다.
- **dual read (additive)**: alembic `0081_uuid_dual_read`가 `public_features`
  view의 SELECT * 컬럼 목록을 재고정해 `feature_uuid`를 노출(공개 술어 무변경 —
  3축 교체는 34B 소관, downgrade는 information_schema 기반 명시 컬럼 재생성으로
  0079 downgrade 선행 조건 유지). repo read는 전부 view/base에서
  `CAST(feature_uuid AS text)`를 **select 목록에만 추가**(join/술어 무변경 —
  EXPLAIN 회귀 없음): 단건 `_FEATURE_ROW_COLUMNS_SQL`·bbox 2종·contained·
  search 2종·nearby 2종·service batch(`base.feature_uuid`)·admin 목록/상세.
  응답 additive: user detail/search/in-bounds/nearby item + service
  `POST /features/batch` item(4/5 state) + `POST /features/weather/batch` item
  (거대 bitemporal 조회 SQL은 재작성하지 않고 `get_feature_uuid_map` 병행
  해석 — 관심사 분리) + admin 목록/상세. **응답 `feature_id` 값은 legacy
  유지** — rollout이 응답 UUID 전환을 32C("양 저장소 checksum 일치 후")로
  고정한 consumer-first cutover 규율.
- **notice lineage dual — 표면 교체**: `public_active_notice_feature_identities`
  가 `{feature_id: feature_uuid}`를 반환하는 단일 표면. 기존
  `public_active_notice_feature_ids`는 **제거**(호환 shim을 남기지 않음 —
  잔여 호출자였던 통합 테스트 5곳을 identities로 이행).
- **신규 write — 파생 규칙의 DB 강제(fail-close by construction)**: dual 기간
  정본 신규 행 generator를 **uuid5 파생으로 결정**(32A가 32B 소관으로 이월한
  UUIDv7 여부 — 결정론이 KTM/PinVi 독립 계산·checksum 대조의 전제라 legacy id
  소멸 전 미채택). 이 규칙을 app 검사에만 두지 않고 `0080`이 CHECK 2종
  (`ck_features_feature_uuid_dual_derivation` ·
  `ck_feature_aliases_uuid_dual_derivation`)으로 저장 경계에서 강제 — 파생값과
  다른 어떤 write도 SQLSTATE 23514로 거부된다(비용: pgcrypto SHA-1 1회/row,
  ~µs). 32A의 "임의 명시 uuid 존중" 열린 계약은 의도적으로 닫았고 해당 32A
  통합 테스트를 fail-close 계약으로 재정의했다. provider upsert
  (`_UPSERT_FEATURE_SQL`)·admin add(`_APPLY_FEATURE_ADD_SQL`)는 `feature_uuid`
  를 writer 명시 INSERT + RETURNING 대조(`verify_feature_uuid` →
  `FeatureIdentityInvariantError`) — DB fence 위의 관측 계층. 0079 트리거
  2종은 raw SQL seed 경로 편의 fill로 유지(파생 강제는 CHECK 소관, 트리거
  제거는 32C write fence 시점 재평가 — 0079 docstring 갱신).
  `count_features_missing_identity`가 uuid/alias 결측 관측(INV-068-01 현행판).
  CHECK 2종은 dual 기간 한정 fence — 32C에서 비파생 generator 채택과 함께
  제거한다(ADR-075 단계 fence 규율, 0080 docstring 근거).
- **OpenAPI·diff artifact 개정**: 3 spec 재생성(additive 필드·전 경로 dual
  수용·422 응답), `openapi-diff-v1.json` baseline sha256 3종 재고정 +
  `revisions` 배열로 개정 사유 기록(diff 항목·counts 무변경 — ADR-068
  enum/status 항목은 32C 목표 상태 존치, CHECK fence의 32C 제거 계획 명시).
  unit artifact bytes 상수 재고정. PinVi vendored snapshot 재추출은 rollout대로
  32C 쌍 PR 소관 — 미변경.
- **32C/39 이월 명시**: 내부 FK 체인(source_links/curation/price/weather)의
  UUID 조인 재작성·referencing table shadow uuid(rollout이 legacy FK 체인
  fence=32C·제거=39로 고정) · 응답 `feature_id` 값 UUID 전환 · legacy write
  fence·트리거/CHECK 제거 · legacy ID 물리 제거(T-VN-39 removal manifest).
- **동반 수정 2건**: ① perf gate tier1 frozen response shape 재고정(public
  detail·service batch에 `feature_uuid` — 실패 메시지 절차대로 의도적 계약
  변경 갱신). ② **H35 cutover 도구의 head 등호 고정 해제** — `_h35_schema`의
  `repository_alembic_head` 검사가 저장소 head == 0078 등호였는데, 32A(0079)가
  head를 전진시킨 순간부터 preflight/migrate가 영구 rejected였다(본 branch
  잠복 회귀 — base 커밋 5d4db58c에서 재현 확인). 캠페인 도구는 target에 앵커
  하도록 수정: lineage 포함(조상) 판정 + upgrade도 `head`가 아니라
  `TARGET_SCHEMA(0078)`까지만. h35 unit/통합 81건 green.
- **검증**: unit 1,981 passed(identity 순수 계약 11 신규) · api 패키지 1,069
  passed(경계 dual 수용·422·additive 노출·404 재정의, 공용 echo-resolver
  conftest) · 신규 통합 9 passed(`test_feature_identity_boundary.py` — 양형식
  해석·미존재·형식 오류·view/단건/bbox/batch/notice 병행 노출·upsert/admin-add
  원자성·CHECK drift 거부·alias 결측 invariant 관측) · 32A migration 8(명시
  uuid fail-close 재정의) · feature_repo 26 · freeze 3 · alembic 일관성/공개
  view/notice(방어 cast·lifecycle)/nearby/in-bounds 회귀 73 · 전체 통합 suite
  green · export --check drift 0 · ruff/mypy --strict(main+api)/lint-imports
  clean.
## 2026-08-04 (6) — T-VN-32A UUID identity shadow (schema·deterministic backfill)

- **alembic `0080_feature_uuid_shadow`**: `feature.features.feature_uuid` shadow
  컬럼(nullable 추가 → 결정적 backfill → NOT NULL + `uq_features_feature_uuid`) +
  `feature.feature_aliases`(alias text PK · legacy `feature_id` text FK ·
  `feature_uuid` · `alias_kind` · created_at, freeze `target-schema-v1.sql` §4의
  대응 제약명 `pk_feature_aliases`/`fk_feature_aliases_feature`/
  `ck_feature_aliases_{alias,kind}_canonical`/`idx_feature_aliases_feature` 정합).
  기존 `f_*` PK·FK·읽기 경로 무변경(consumer-rollout 32A "읽기 경로 무변경").
- **freeze 미정 3건 결정**(0079 docstring에 근거 기록): ① backfill/shadow 생성기
  `uuid5(FEATURE_UUID_NAMESPACE, legacy_id)`, namespace =
  `uuid5(NAMESPACE_URL, 'kor-travel-map:feature-uuid:v1')` =
  `75d60e13-2779-5b06-a920-6b1b892a7c84` — 두 저장소 독립 계산·재실행 동일(32C
  checksum 전제), DB server default는 두지 않음(정본 신규 행 generator·UUIDv7
  여부는 32B 소관). ② alias_kind 닫힌 CHECK `('legacy_feature_id')` — writer의
  임의 kind 발명 fail-close, 확장은 additive migration. ③ alias FK ON DELETE
  CASCADE — alias/uuid는 재계산 가능한 파생값, feature 종속 행 freeze 정본
  패턴과 일관(ADR-075 "alias 제거 금지"는 cutover-era DDL 규율로 별개).
- **신규 INSERT 경로**: features INSERT는 repo 2곳 + 통합 테스트 37개 파일의
  직접 seed — 경로별 SQL 수정 대신 트리거로 일괄 보장(BEFORE INSERT fill /
  AFTER INSERT alias 원자 생성, NULL일 때만 채워 32B writer 명시 값과 호환).
  infra upsert SQL은 수정 불필요 판단. SQL uuid5는 uuid-ossp 없이 pgcrypto
  `digest(...,'sha1')` 수동 구성(`feature.feature_uuid_from_legacy` IMMUTABLE) —
  Python 정본 `core/ids.feature_uuid_from_legacy`와 고정 벡터 상호 대조.
- **검증**: unit 1,970 passed(고정 벡터 2개 신규) · 신규 통합 8 passed(backfill
  완전성·UNIQUE/NOT NULL·alias 1:1·INV-068-01~04 freeze artifact 그대로 실행
  (05는 33A 컬럼 참조라 제외 명시)·별도 DB 결정론·downgrade 무손실 왕복·upsert
  원자 생성) · alembic_upgrade + bundle_persist 23 passed · freeze 3 passed ·
  metadata consistency(`alembic check`) + feature_repo_load + row_revision
  30 passed · ruff/mypy --strict/lint-imports clean. codegraph MCP는 이 세션에
  미결선이라 grep 기반 영향도 조사로 대체(write 경로 2곳·SELECT * 부재 확인).
## 2026-08-04 (5) — T-VN-31 freeze 적대 리뷰 2건 반영

- **정합성 리뷰(F-1~F-11) 반영**: 발명분 회수 — retired∧draft state CHECK 제거
  (0059는 교집합 술어만 정본화, 조합 집합은 T-VN-34A 미정), subtype 무술어 GiST
  8개 제거(D-12 결정 3 "공개 술어 partial만" 정본 위반이므로 인덱스 0개 고정 +
  설계 공백 미정 주석), weather summary identity에서 timeline_bucket 제외(0060
  정본 "분류 결과라 identity 제외"), price summary known_at 제거(ADR-078에 price
  bitemporal 결정 없음). 정본 명시분 반영 — user surface status→3축 enum diff
  (현행 user spec의 status 노출 실측)+T-VN-34 user snapshot 재-vendor yes,
  weather 유효기간 `valid_during tstzrange`(ADR-072 결정 2), soft-delete 흡수처
  `feature.feature_state_transitions` 신설(ADR-067 결정 5), ADR-073 결정 1 배타
  열거에 따라 features 목록·by-target·providers*·public/beaches*·festivals*·
  contained-features를 removed로 이동, projection 역할 분리(ADR-069 결정 4)·
  detail-snapshot PinVi 런타임 소비(H07D)·재-vendor 정본 귀속(user/admin은
  ADR-079, service는 ADR-081) 명시.
- **실행성 리뷰(D1~D4) 반영**: invariant 파서 fail-open 봉합(trailer 개수 대사),
  machine-readable phase 태그(pre-backfill/post-backfill/both) + 파서 필수 검증,
  openapi-diff surface별 counts + unit 대조(2차 방어), current_weather_summary
  surrogate PK(bigint identity — replica identity·price 대칭).
- 카운트 변경: invariant 44→43, violation fixture 9→8(3축 조합 case는 CHECK
  미정이라 구현 PR로 이월, NULLS NOT DISTINCT case는 history tuple의 실 NULL
  동치로 교체). fingerprint·bytes sha 전부 재고정.
## 2026-08-04 (3) — T-VN-31A/B/C vNext target freeze
## 2026-08-04 (4) — T-VN-31A/B/C vNext target freeze

- **Wave 2 barrier freeze 완료.** ADR-066~075·보고서 §3/§4/§8·tasks 정의를
  실행 가능한 artifact 8개(`contracts/vnext/`)로 고정 — 목표 DDL(빈 PostGIS
  자기완결), 불변식 44 assertion(H35 preflight 6종 패턴), catalog fingerprint
  (H35 7 카테고리), OpenAPI diff(surface×change, baseline sha256 핀), consumer
  rollout(write-fence·호환 폐기·PinVi 3 snapshot 재-vendor), 위반 fixture 9 case
  - 기대 SQLSTATE/제약명, recovery preflight(writer registry·fence 증거·PITR
    판정·Merkle v1).
- **정직성 원칙**: ADR이 침묵하는 세부(UUID 생성기 버전, alias_kind 값 집합,
  subtype 공간 인덱스의 partial 표현, anchor 정밀 술어, capability shape,
  summary reconciliation 등)는 발명하지 않고 `-- 미정(T-VN-XX 구현 소관)` /
  `"deferred-to-implementation"`으로 표기.
- **drift fail-close**: 통합 테스트(빈 PostGIS 새 DB에서 DDL 적용→불변식 0→
  fixture별 기대 SQLSTATE 거부→fingerprint 재계산 일치) + unit 테스트(artifact
  bytes sha256 상수 고정, 현행 spec baseline sha256, diff 참조 operation 실존,
  rollout/preflight JSON shape) — unit job이 매 PR 실행되어 31A/B drift를 막는다.
- 검증: ruff clean, unit 전체 1,963 passed, freeze 통합 3 passed,
  `mypy --strict` clean.
## 2026-08-04 (3) — 이월 기록: H35·T-VN-41 prod live 검증 미수행 → H42~H44 신설 (docs-only)

- **이월 기록** — 이번 사이클에 수행하지 못하고 넘어간 것 2건을 명시한다.
  ① **H35 prod live 검증**: 재생성 후 공개 표면 DB 실측(4,620)까지만 했고, prod live
  검증(공개 API·admin UI live 스모크, quarantine 0 확인, 재적재 수렴 후 최종 판정)은
  하지 않았다. ② **T-VN-41 prod live 검증**: codex 소관 41C "prod consumer enable +
  live 증명"은 경계 조건(docker-manager 재pin #109 = `2b2dee95` 완료 + CSV5/재적재
  안정화) 뒤로 미뤄졌다. 배치: tasks.md Lane A **a2(운영 연속성)** 신설 —
  `T-VN-H42`(provider 재적재 완주·수렴 검증, **H35 live 검증 잔여를 AC로 흡수**,
  41C prod enable 선행 조건·지금부터 스케줄 수렴 감시) → `T-VN-H43`(prod 백업 체계 —
  TCP 경로 정기 dump·sha256·보존, H42 완주 직후 rollback 기준선) → `T-VN-H44`(복원
  리허설 드릴 정기화 — H30B `~/h30b/` 하네스 재사용). Lane B T-VN-41 절의 41C 경계
  주석도 갱신했다.
## 2026-08-04 (2) — CSV5 재적재 완료 + T-VN-H30B 재정의판 실증 완료

- **CSV5 전량 적재** (#934 이후): 486행/batches 5 — tourism-100 224 · heritage 85 ·
  arboretum 72 · lighthouse 105(provenance sidecar 결박, 필드명 `provenance_file`).
  공개 표면(trusted) **4,620** = source_rule 4,424 + csv_explicit_feature_id 196.
  **결정론적 feature_id 재현 실증** — explicit id가 재생성 feature와 그대로 해석.
  미해석 290행은 대상 provider 미적재분(스케줄 후 재import로 수렴). import 기본이
  dry_run=true(query param)인 것 실측. H35 실행 4단계 종료.
- **T-VN-H30B(재정의판) 완료.** 새 snapshot(`krtour_map_0078_20260804T023104Z.dump`,
  sha256 `b5ab83dd…`) → scratch 복원 → concierge changes artifact 8p/1,481행 채취
  (chain 검증·sha256) → 결손 1,481 주입(inactive) → network-free replay로 **완전 회복
  (교집합 1,481/신규 0/미복구 0), 2회차 멱등(변화 0)** → finding 수치
  (observed=unique=upserted=105)·violation 분포(admin_code_stale 60 linked = dual 축
  실작동) → scratch 실 API 인증 `/admin/issues` 실호출 FK·last_seen 정합.
  종전 하네스 부재가 조사에서 확정돼("2000→2458" 명령 기록은 저장소에 없음 — 철회문만
  잔존) build_asset_context 패턴으로 신규 조립.
- 프로브 교훈: geo-postgres 컨테이너 재시작 후 컨테이너 로컬 소켓이 앱 TCP 인스턴스와
  다른 것을 가리켜 "krtour_map 없음" 허위 경보 — **DB 프로브는 앱과 같은 TCP 경로로
  통일**한다. 컨테이너 내 이중 postgres 현상은 이상 신호로 기록.
## 2026-08-04 (codex) — 0079 추가에 따른 H35 synthetic regression 계약 정렬

- PR #935의 GitHub PostGIS gate는 858 passed/5 skipped 뒤 H35 preflight가
  `repository_alembic_head=0078`을 요구해 하나만 실패했다. writer-drain `0079`가 실행되기
  전의 fail-close라 H35의 오래된 목표 schema 상수 drift로 판정했다.
- H35 prod cutover는 사용자 결정에 따라 계속 폐기 상태다. 다만 CI regression harness가
  latest Alembic head를 구성하지 못하는 결함은 남길 수 없으므로, 목표 revision과 forward
  boundary를 `_h35_schema_version.py`의 `0079`/`schema_0079`로 단일화했다.
- semantic catalog fingerprint를 실제 isolated PostGIS head migration에서 다시 계산하고
  writer-drain lease·instigation·run의 relation/column/constraint/FK/index를 포함했다.
  적대 리뷰 P1은 CSV5의 migrate receipt가 `schema_after=0079`뿐 아니라
  `schema_before=0063`도 exact해야 한다고 지적했고, 0078→0079 intermediate receipt 거부
  회귀로 반영했다. marker fixture도 전용 collection 한 개만 변이하도록 고쳤다. H35 unit
  65건과 `0063→0079→CSV5→GC→verify`, head partial probe, quarantine boundary·preflight
  rehearsal 4건(총 69건)이 통과했다. n150/prod 연결·변경은 없었다.
## 2026-08-04 (codex) — T-VN-41D isolated durable writer-drain 완료

- Map migration `0079`가 lease·instigation snapshot·run cancellation CAS를 `ops` schema에
  정규화했고 private API-image command는 exact stdin JSON과 single receipt stdout만 허용한다.
  begin/attest 응답 유실 뒤 begin 재호출도 durable receipt operation을 CAS로 되돌려 같은 owner의
  recovery chain을 계속할 수 있게 했다.
- 단일 적대 리뷰의 P0 2건(begin null key·금지된 positional argv)과 P1 3건(rollback daemon
  선기동, recovery pair re-attestation 누락, late run 미cancel)을 모두 반영했다. backup rollback은
  webserver-only Map restore receipt를 fsync한 뒤 daemon을 열며, diagnostic/cutover recovery는
  exact prior pair attestation 전에는 archive/재기동하지 않는다.
- strict command 5건, isolated PostgreSQL migration/CAS 3건, Manager phase/recovery 143건과
  actual ephemeral Docker Compose frozen-runner rehearsal 1건을 통과했다. rehearsal은 production
  Compose·host network·production DB를 사용하지 않았다.
## 2026-08-04 — prod 재생성 실행 + 재적재 concierge 축 복구 + T-VN-H22 단일 PR

- **재생성 실행 완료.** `main@2b2dee95`(#931 entrypoint 게이트 포함)로 이미지 3종 재빌드
  → 빌드 단계 수동 게이트(`alembic heads`=`0078`) 통과 → `krtour_map` DROP/CREATE →
  compose recreate → **빈 DB에서 `0078` 직행 10초**, 3컨테이너 healthy.
- 실행 중 실측 함정 2건: ① manager `.env`가 root 소유 → `sudo docker compose`.
  ② **신규 DB에서 `CREATE EXTENSION`은 superuser 전용** — 앱 계정 alembic이 `0001`에서
  거부됨. CI(testcontainers)는 앱 유저가 superuser라 이 경로를 못 잡는다. superuser로
  postgis·pg_trgm·pgcrypto·pg_prewarm + `GRANT USAGE` 사전 생성으로 해소, #109에
  프로비저닝 절차로 기록. **정지된 구 컨테이너 start 금지** — 구 이미지가 빈 DB를 다시
  `0072`로 올린다.
- **재적재 concierge 축 완료.** geo API key 미결선(전 provider ETL blocker — manager
  compose가 BASE_URL만 결선)을 발견, 사용자 확인 후 `/tmp` override로 주입(영구 결선
  #114). concierge provider job + `curated_features_refresh` 성공 →
  features 1,481 · curated 4,424 · **공개 표면 4,424건 복구**.
- **T-VN-H40 완결.** 재적재분 link decision 4,424건 **전부 `match_basis=source_rule`** —
  `0073` 트리거의 prod 실증. 잔여 provider는 일일 스케줄, CSV 5종은 feature 적재 후.
- **T-VN-H22A/B/C 단일 PR 구현** (사용자 지시로 보류 해제). 계약 확정: "후보
  theme/source"=병렬 표시(추천 아님), 격리 근거=marker 정본 술어+역참조 재구성,
  ADR-048 봉투. 백엔드: read 2 + reclassify command(§906 inventory 68→69, 사전 심어진
  quarantine barrier 충족, lock 후 marker 재검증). 프론트: 49B 관용 패널 + mocked 6건
  (manifest 276→284 — main의 기존 drift 278·기존 실패 7건은 tvn41 잔여로 불간섭) +
  live spec 저술. **격리 스택 HTTP 파괴 검증 9흐름 전부 통과**(409 fail-close 무변경·
  terminal replay·빈 격리 DELETE·marker 2키만 제거 등).
- codex tvn41 병행 판정(사용자 질의): 격리 스택 작업은 지금 병행 무방(파일 충돌은 의도된
  핀 2개뿐 — registry write 수·mocked manifest). **41C prod consumer enable만** 재pin
  (#109)+CSV5 후가 경계.
## 2026-08-04 — prod 0072 배포 사고: 공개 표면 0건 → 복구 대신 폐기·재생성 결정

- **사고.** T-049 완료 확인차 prod를 읽었더니 alembic head가 `0072_curation_provenance`,
  공개 큐레이션 item **0건**(정상 3,265), link decision 3,266건 전부 `legacy_unattributed`.
  데이터 자체는 무손상(items 3,530 · collections 71 · themes 68) — 링크 신뢰도 판정에서
  전부 탈락한 상태.
- **원인.** pin(`map_release_revision=4a764a4f`)과 달리 **7/31 빌드(`0bdecb1f`, alembic
  head `0072`) 이미지가 배포**됐다. `docker/api-entrypoint.sh`가 기동마다 무조건
  `alembic upgrade head`를 돌려 `0063 → 0072`로 올린 뒤 **오류 없이** 끝났다 — 그 이미지
  기준으론 head까지 간 게 맞으니까. `0073`(링크 3,043건 복구)이 이미지에 없어 복구가
  안 일어났다. H35 문서가 경고한 "0072에서 공개 표면 전멸"이 정규 cutover **밖에서**
  실현된 것. UI는 롤백본(`c8ed6164`), api는 `0bdecb1f`, pin은 `4a764a4f` — 3자 제각각.
- **결정 (사용자).** 복구하지 않는다. **폐기 후 재생성** — 서비스 전이라 살릴 필요 없음.
  빈 DB `upgrade head` → `0078` 직행, `0063→0078` 데이터 마이그레이션 위험 구간 통째
  소멸. **H35 cutover·typed helper·결합 barrier가 사문화**됐다(tasks.md 재정의 블록).
- **폐기 전 아카이브.** `n150:~/backups/krtour_map_0072_20260803T203706Z.dump` 1.2G,
  sha256 기록. 격리 clone **복원 검증 완료**(pg_restore 오류 0줄, 1,817초). 요령: postgis
  이미지는 init 완료(`ready` 로그 2회) 후 **새 DB를 만들어** 복원 — `POSTGRES_DB`에는
  확장이 미리 심어져 dump의 `x_extension` 배치와 충돌한다. 1차 시도는 init 재시작 창에서
  복원을 시작해 446개 오류로 죽었다. 이 덤프는 H22C 파괴적 live e2e 픽스처 후보.
- **재발 방지.** PR #931 — entrypoint에 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`(이미지
  head가 다르면 **DB 연결 전에** 죽음 — 이번 사고는 이 값만 있었으면 잡혔다) +
  `MODE=none`(orchestrator가 migration 소유 시). 회귀 4건은 종료 코드가 아니라 **upgrade
  실행 여부**를 stub 흔적 파일로 판정. Docker-manager 쪽 image↔pin 일치 게이트는 이슈
  #109로 요청(이미지에 revision 라벨이 정확히 박혀 있었으므로 대조만 했으면 잡혔다).
- **tvn41 영향도 (서브에이전트 실측).** T-VN-41 무영향 — 스택 3개 전부 자체
  map-db(`kor_travel_map`) + 자체 네트워크, prod(`krtour_map`) 무참조, live spec 기대값
  env 주입, `0079+` 브랜치 없음. 사문화되는 건 codex #924의 H35 helper뿐. 오히려 재생성
  후 41C consumer enable의 schema 선행조건이 충족된다. codex는 8/2 #924 머지 후 활동
  정지로 보임.
- **부수 사고 2건.** ① 주 작업 트리에 **파일 100개 삭제 staged**(migration `0069~0078`
  10개, ADR-080/081 포함) — 조사 에이전트가 발견, 전부 복원. 그대로 커밋됐으면 T-VN-41
  migration이 main에서 사라질 뻔했다. ② 신규 npm high 권고 2건(brace-expansion·fast-uri)
  으로 audit gate가 전 PR에서 실패 시작 — PR #932(lockfile patch bump)로 해소.
## 2026-08-03 — H22 착수 전 실측: 격리 대상 0건, 구조상 0건 (PR #929)

- Lane A 다음 항목 T-VN-H22A(quarantine read model)를 시작하기 전에 **규모부터 쟀다.**
  계획이 전제한 "격리된 canonical-only item"이 이 DB에는 **하나도 없다.**
- 라이브 prod 읽기 전용 실측 — `curation_items` 3,530건이 **2×2의 대각선만** 채운다:
  legacy-marker collection 52개는 `curated_features` 투영본 3,044건만, CSV collection은
  네이티브 486건만 담는다. 격리는 **비대각 칸**(legacy 안의 네이티브)을 요구하는데 비어
  있다. dangling collection 참조 0. 격리 clone에 `0065`를 실제로 적용해도 0개/0건.
- `legacy:quarantine`·`migration_quarantine` marker 생성자는 `0065` **하나뿐**이고
  1회성이라 **배포 후에도 영구 0건**이다. 조사가 함께 경고한 "배포 직후 `[0065 격리]`
  collection이 admin UI에 설명 없이 등장" 문제도 collection 자체가 안 생겨 소멸한다.
- **내 informational 쿼리에 3값 논리 버그가 있었다** — `NOT (metadata->>'migrated_from'
= '…' OR key LIKE 'legacy:%')`는 키가 없는 collection에서 `NULL OR false = NULL` →
  `NOT NULL = NULL`로 걸러져 "legacy 밖 486건"을 0으로 보고했다. 격리 건수는 `0065`와
  같은 **긍정형** 술어를 써서 영향 없었지만, 합이 3,044 ≠ 3,530으로 안 맞아 잡았다.
- **전제를 배포 게이트에 박았다 — 단, 경계 앞에.** H35 **preflight**가
  `quarantine_candidates_before`를 0으로 검사한다. `0065`의 격리 술어
  `legacy_projection_id IS NULL`은 그 컬럼의 유일한 backfill 때문에 `0063`에서
  "`curated_features`에 대응 행 없음"과 동치라, 컬럼 없이도 같은 집합을 고를 수 있다.
- **첫 설계는 틀렸고 적대 리뷰가 반증했다.** 나는 검사를 verify에 hard check로 두면서
  "격리가 생기면 어차피 `public_items_verify`가 깨지니 원인만 이름으로 바꾸는 것"이라고
  적었다. 실측 결과 **격리 1건이 생겨도 공개 수는 3,043 그대로**였다 — 격리 조건은
  `status`·`source_present`·accepted link 어느 것도 요구하지 않아 공개 집합과 독립이다.
  즉 그것은 원인 라벨링이 아니라 **경계 뒤의 새 거부 경로**였고, 거기서 거부되면 출구가
  없다(csv5는 accepted prior receipt 요구 / migrate 재실행은 `schema_before=0063` 요구인데
  DB는 이미 `0078` / `0065` downgrade는 durable state에 fail-close). **#925에서 내가
  잡아냈던 index signature 함정과 같은 계열을 내가 다시 만들었다.** 경계 뒤에는
  `quarantine_collections`·`quarantine_items`를 관측치로만 남긴다.
- 회귀는 "0이다"를 확인하지 않는다 — 시드에 legacy-marker collection이 아예 없어 공회전이
  된다. 대신 **legacy collection 안에 네이티브 item을 실제로 만들어** ① `0063`에서 후보로
  잡히고 ② head까지 밀면 `0065`가 실제로 격리하며(두 술어가 같은 것을 고른다는 증거)
  ③ 그런데도 verify의 check는 늘지 않는지를 함께 고정한다. preflight receipt가 실제로
  거부하는지는 별도 회귀로 본다. ③은 변이로 확인했다 — verify에 hard check를 되돌려
  넣으면 깨진다.
- **H22A/B/C 종결 여부는 사용자 결정으로 남겼다** — 축소가 아니라 대상 소멸이라 임의로
  닫지 않는다. 착수하게 될 경우 먼저 풀어야 할 모호함 3건은 `docs/tasks.md`에 적었다
  (특히 "후보 theme/source"는 대응 스키마가 없고, 추천으로 읽으면 같은 항목의
  "자동 target 추정 금지"와 충돌한다).
## 2026-08-03 — H35 적대 리뷰에서 helper 결함 2건 (PR #925)

- 최종 exact HEAD `d50bb2c5`에 적대 리뷰어 2명 + refute/reproduce 검증(15 에이전트).
  **리뷰어 findings 6건은 전부 기각**됐고 synthesizer가 직접 측정하며 찾은 2건이 남았다.
  둘 다 격리 컨테이너에서 독립 재현했다 — 리뷰의 실제 가치는 findings 목록이 아니라
  검증 과정에서 나왔다.
- **결함 ①** `_INDEX_SIGNATURES`의 `kind = 'weather'::text`가 어떤 DB와도 일치하지 않는다.
  `feature.features.kind`가 `character varying`이라 PostgreSQL이 항상
  `((kind)::text = 'weather'::text)`로 deparse한다. 이 index가 영구 non-canonical →
  head에서 partial probe 통과 불가(수정 전 실패 1 → 후 7건 전부 통과).
  → `run_migrate`의 forward 재개 경로가 죽는다. migrate commit 뒤 receipt 유실 시
  csv5도 못 가고 migrate도 영구 rejected → 남은 출구가 PITR 없는 prod의 dump 복원.
- **결함 ②** 공개 카운트에 `source_present`가 빠져 de-publish를 못 잡는다.
  실측: item 1건 source-absent → 실제 API 3,042인데 게이트는 3,043 유지.
  **내가 이슈 #99에 올린 SQL도 같은 결함이라 정정했다.**
- 기존 회귀가 못 잡은 이유: 단위는 합성 `_states()` 맵, 리허설은 `_PRE_REVISION`에서만
  probe — **실제 `pg_get_indexdef`를 head에서 검사하는 경로가 없었다.** 회귀 3건 추가,
  전부 변이로 falsifiability 확인.
- **n150 실행은 하지 않았다.** 승인은 받았지만 pin된 `d50bb2c5`가 이 결함을 포함하고,
  orchestration 소유자인 Docker-manager가 실제 cutover를 여러 차례 시도해 전부 pre-forward
  fail-close 후 rollback한 뒤 지금은 T-049 진단 도구를 구현 중이다(PR #100/#101 머지).
- Docker-manager 이슈 #99에 확정 gate 값 + 이번 결함 + pin 갱신 요청을 남겼다.
## 2026-08-03 — H35 §5 gate 실 prod 데이터 실측 (0063→0078)

- runbook §5 선언값을 실제 prod 백업 clone에서 확인했다(prod 무접촉, 포트 노출 없음):
  preflight `0063` / 3,265 · migrate `0078_cache_target_gc_observe` / 3,043 / invalid index 0 ·
  csv5 파일 5 / accepted 222 / rejected 0 / 3,265 — **전 항목 일치**.
- 재검증이 필요했던 이유: 내 이전 실측은 `0074` head 기준인데 그 뒤 `0075~0078`이 추가됐다.
  **`0075~0078`이 curation 공개 표면을 바꾸지 않는다**가 추론에서 실측으로 확정됐다.
- 파일별 accepted: arboretum 44 / heritage 67 / kt100-2023 51 / kt100-2025 58 / lighthouse 2.
- **이 실측의 한계를 runbook §10.1에 명시했다** — helper를 우회해 마이그레이션과
  `import_curation_rows`를 직접 호출한 것이라 §11의 "network-free 리허설"(helper 경유)을
  대체하지 않는다. transaction UUID 체인을 안 태웠으므로 §5.3 멱등 계약도 검증하지 않는다
  (helper 우회 시 CSV 재호출로 decision 222건 증가, 공개 item은 3,265 불변 — append-only
  성질상 예상되는 동작이지만 멱등 판정은 helper 경유로만 한다).
- 소요 70.9초는 dagster 없는 개발 환경 수치라 배포 시간 근거로 쓰지 않는다(기존 폐기 방침 유지).
- T-VN-41(#917/#923/#924) codex 머지 완료 확인, n150 load 11.6 → **0.76** 정상화.
## 2026-08-02 (codex) — H35 scope validator legacy delegate P1 해소

- function catalog 대상을 proname allowlist에서 exact schema-qualified regprocedure inventory로 바꿨다.
  relay/append-only 함수와 top-level scope validator에 더해 `_0074(text,jsonb)`와
  `_0052(text,jsonb)`가 반드시 존재하고 full semantic payload가 일치해야 한다.
- 실제 PostGIS에서 `feature_ids`, `center_radius`, `sigungu_by_radius`, `bbox`, `provider_dataset`,
  `cache_target_keys`의 대표 valid/invalid를 top/0074/0052에 모두 호출했다. generation-7의 512자
  target key는 top-level만 승인하고 legacy delegate는 거부하는 migration 경계도 고정했다.
- 두 delegate를 각각 같은 signature의 false body + 다른 config/volatility/parallel/security/strict로
  교체하고, 원본을 rename한 뒤 같은 이름의 `(text,text) RETURNS text`로 바꾼 경우를 모두
  `0075_0078_functions_semantic` 실패·mutation 0으로 거부했다.
- 새 PostgreSQL 16 function catalog fingerprint와 전체 H35 리허설을 갱신했고 실제 리허설이 통과했다.
## 2026-08-02 (codex) — H35 NO-GO semantic catalog·실제 PostGIS 음수 행렬

- `0075~0078` table/column/constraint/index/trigger/function/sequence를 structured PostgreSQL catalog로
  읽고 canonical SHA-256을 비교한다. 이름만 같은 오정의, invalid/not-ready index, disabled trigger,
  function body/config drift와 relay sequence/scope validator drift를 모두 fail-close한다.
- 실제 PostGIS 리허설은 `0063→0078→CSV5→GC→verify`를 수행한다. generation-7의 ready stream,
  source head, current/expired referenced/unreferenced snapshot, reconciliation, terminal outbox/delivery/claim을
  seed하고 GC 삭제·참조 보존·동일 transaction replay·deterministic observation과 exact 16-key receipt/
  14-key evidence를 검증했다.
- 구조 drop·동명이형과 stale/expired/mixed/invalid Merkle, non-ready stream, reconciliation/outbox/claim/
  delivery backlog, foreign observation, chain skip를 모두 evidence 미발급·runtime/외부 event/DB mutation
  0으로 거부한다.
- argv 검증 전 DB/CSV/GC 구현을 eager import하던 entrypoint를 유효 request dispatch 뒤 lazy import로
  바꿨다. NTFS 부하에서도 15초 보안 경계 timeout을 늘리지 않고 invalid argv가 결정적으로 종료되며,
  실패했던 단일 case 3회 반복이 모두 통과했다.
- runbook/tasks의 후반 canonical 순서를 `csv5 → gc → Map API·Map Dagster web·Map Dagster daemon·
PinVi API·PinVi Dagster final fence → Map verify → PinVi final boundary`로 맞췄다.
## 2026-08-02 (codex) — H35 contract CI fixture 후속

- 세 Python CI가 공통으로 실패한 `test_phase_chain_accepts_exact_receipts`를 조사했다. 기존 fixture의
  receipt에 새 exact key가 없고 verify가 여전히 csv5를 직접 prior로 사용한 계약 drift였다.
- 생산 validator는 유지하고 fixture에 `cache_target_evidence: null`과 `gc` receipt를 추가해
  `preflight→migrate→csv5→gc→verify`를 재현했다. contract unit 46건과 대상 Ruff가 통과했다.
## 2026-08-02 (codex) — H35 GC·final cache-target evidence 구현

- typed receipt chain을 `preflight→migrate→csv5→gc→verify`로 바꾸고 모든 receipt의 exact top-level
  key에 `cache_target_evidence`를 포함했다. accepted verify 외에는 항상 `null`이다.
- `gc`는 신규 ledger/migration 없이 기존 bounded client를 호출한다. deterministic observation run ID,
  기존 advisory lock·batch transaction·멱등 observation을 유지하고 final backlog 0, referenced 보존,
  stored/fresh referenced 일치만 승인 기준으로 삼았다. lock 연결과 batch 연결을 함께 쓰도록 helper
  pool을 2개로 제한했다.
- final verify는 HTTP 없이 하나의 read-only repeatable-read PostgreSQL view에서 PinVi stream과 최신
  unexpired snapshot을 읽는다. snapshot item과 live source head Merkle를 각각 재계산해 header/count/
  material watermark와 모두 비교하고 reconciliation/outbox/claim/delivery backlog, GC backlog와
  deterministic observation이 모두 수렴했을 때만 exact v1 증적을 발급한다.
- runbook/tasks의 다섯 helper와 최종 exact HEAD 단일 적대 리뷰 규칙을 정렬했다. 테스트와 manager
  orchestration은 별도 소유자에게 남겼으며 아직 리뷰를 요청하지 않는다.
## 2026-08-02 (codex) — H35 Agent A helper·image boundary 구현

- `scripts/h35/h35_cutover.py`를 thin entrypoint로 만들고 contract/schema/CSV5 private module 3개로
  분리했다. schema와 CSV5는 서로 import하지 않으며 public surface는 main과 typed contract뿐이다.
- request/prior receipt를 exact key·digest·phase chain으로 검증한다. argv/request 오류와 내부 실패는
  raw 입력·예외·DSN을 반사하지 않는 stdout JSON 한 줄이며 stderr는 항상 비운다.
- live DB identity v1은 canonical transaction UUID, 고정 role `map_application`, DB 이름, PostgreSQL
  system identifier를 NUL framing한 SHA-256이다. DB에서 매 phase 재계산하며 요청값은 receipt에
  echo하지 않는다.
- `0064`/`0068`/`0069` 재진입은 해당 down-revision의 canonical index statement prefix와 단일 invalid
  residue만 허용한다. wrong-revision·mixed family·unknown invalid index는 mutation 전에 거부한다.
- canonical CSV5 manifest/asset hash, 5개·486행·accepted 222/rejected 0, 공개 `3,265`와 exact complete
  state 멱등성을 한 transaction에서 검증한다. API image에는 helper와 `resources/curations`만 좁게
  copy하고 OCI revision을 helper source revision과 결속했다.
- 검증: focused Ruff, strict mypy, import-linter, curation unit 36개, 기존 0064/0068/0069 migration
  integration 3개 통과. 전체 black-box/scratch rehearsal은 독립 Agent B 소유로 남긴다.
## 2026-08-02 (codex) — H35×T-VN41 보정 설계 재기준화

- 과거 H35 runbook은 두 차례 `NO_GO` 뒤 삭제된 2,841줄 실행 초안이며 현재 `scripts/h35/`도
  `0072`/`0078` 일부만 검증한다. 둘 다 prod 실행 근거로 쓰지 않도록 새 tracked runbook을
  **구현·승인 전 실행 금지** 상태로 만들었다.
- Docker-manager가 H35 전체 one-process global lock·mode `0600` journal·결합 backup/restore를
  소유하고, Map은 `preflight`/`migrate`/`csv5`/`verify` typed helper만 소유하도록 경계를 고정했다.
- exact gate는 공개 `3,265→3,043`, CSV5 accepted `222`/rejected `0`, 공개 `3,265`다. `0075`
  기존 행 identity/NFC/trim/length/CHECK/FK preflight와 `0075~0078` schema/index/outbox/GC verify를
  추가했다.
- Map helper 구현과 black-box/리허설 검증을 Agent A/B 독립 소유 파일로 분리했다. 이 문서 exact
  head의 적대 리뷰 2건 전에는 구현과 n150 실행을 시작하지 않는다.
## 2026-08-02 (codex) — T-VN-41 command principal clean cut

- source PUT/DELETE와 refresh create는 exact `cache-target:command`만 허용한다.
- `cache-target:consumer` umbrella는 enum·validator·인증 fallback에서 clean cut 제거한다. command
  principal의 consumer·snapshot·recovery 접근도 `403`으로 고정한다.
- 인증 의미가 달라지는 breaking contract로 판단해 service OpenAPI 재핀과 PinVi contract generation 7을
  요구한다. generation 6 조합으로 command 표면을 활성화하지 않는다.
- settings literal/registry와 인증 fallback에서 consumer umbrella를 제거하고 source PUT/DELETE·refresh
  create 세 route를 command scope로 바꿨다. 한 canonical binding의 command/consumer/restore/recovery
  exact 역할 profile, 전역 system owner/digest/principal uniqueness, configured protected secret digest
  분리를 설정 검증으로 고정했다. 같은 `consumer_id`는 한 canonical sorted system tuple만 소유하고 여러
  system은 union binding으로 표현한다. public VWorld/API key와 네 역할 digest 충돌도 기동을 막는다.
- 17개 service operation의 OpenAPI `x-required-service-scope`와 caller role 표를 추가했다. command writer는
  PUT/DELETE 후 source GET과 refresh `Location` polling GET에서 consumer credential로 전환한다. 같은
  inventory가 runtime passed scope를 검증하며 모든 51개 wrong-role 조합은 service/metadata 호출 전에
  `403`이다. request-bound helper는 scope-only 검사 뒤에만 metadata를 조회한다.
- generation 7 exact pair pin을 command writer/backfill/consumer 활성화의 사전 조건으로 옮겼다. Map
  service OpenAPI SHA는 `622ea54c98e9b0c09592cf84aced36227992c6bdf256742a3532b892f0efccf2`이며 PinVi
  재핀은 아직 미완료다.
- command→read/claim/ack/nack/snapshot/restore/recovery direct route와 비command role→command route,
  제거된 consumer umbrella, invalid registry, cross-binding ACK/NACK를 회귀로 고정했다. router 172건,
  OpenAPI export 12건,
  API strict mypy 61개 파일, 대상 Ruff, OpenAPI all drift, frontend generated types check가 통과했다.
## 2026-08-02 (codex) — T-VN-41C referenced snapshot 보존 추세 alert

- job metadata history 조회는 Dagster storage retention과 retry attempt에 결합되므로 운영 정본으로 쓰지
  않았다. `0078_cache_target_gc_observe`가 run ID unique/identity PK/count CHECK/시간 index를 가진 bounded
  observation table을 추가한다.
- GC 전역 lock을 보유한 마지막 observation transaction에서 exact referenced count와 run ID를 함께
  기록한다. 같은 run retry는 최초 row, 직전 acquired, 적격 baseline 분류를 재사용한다. 짧은/비전진 표본은 다음
  baseline으로 승격하지 않고 overlap skip은 기록하지 않는다. 90일 이전 관측은 새 표본 기록 때 정리한다.
- Dagster config는 절대 item/header ceiling, 시간당 증가 ceiling, 최소 관측 간격, 이력 보존일을 검증한다.
  exact current/previous/growth-baseline/delta/rate/threshold/reason metadata와 warning을 남긴다. 감소는 직전 acquired 대비 간격과 무관한
  inventory-loss, skip/unavailable/nonforward는 별도 observation issue로 구분한다.
- 관측 table은 파생·폐기 가능하다. app-only rollback은 0078 schema/data를 보존해 forward recovery하고,
  명시적 0077 downgrade만 table을 버리며 0078 재-upgrade가 빈 기준선부터 재개한다.
- Dagster/client 단위 17건, PostgreSQL baseline/loss/clock/config-change/advisory/retry/retention/raw CHECK 및 ORM/DB parity 11건,
  0078 app-preserve·downgrade·forward 1건과 Alembic metadata 2건이 통과했다. targeted Ruff,
  strict mypy 131개 source file, import-linter 4개 contract도 통과했다.
## 2026-08-02 (codex) — T-VN-41 NFC-equivalent snapshot poison 차단

- 적대 리뷰에서 `é`와 `e\u0301` 같은 raw text head가 별개로 저장된 뒤 Merkle NFC identity에서 충돌해
  generic/reconciliation snapshot을 지속적으로 실패시키는 P1을 확인했다.
- source/refresh/ops scope API는 trim되지 않았거나 non-NFC인 identity를 `422 VALIDATION_ERROR`로 거부한다.
  stream/POI/feature-update repository도 같은 규칙을 적용하고 물리 DB는 root target, stream, source head,
  feature-update scope CHECK로 우회 insert를 막는다. scope `target_key` 상한은 root와 같은 512자로 합쳤다.
- API 호출 전 거부, raw DB constraint, 512자 refresh, canonical 1행 snapshot 성공을 실제 PostgreSQL
  회귀로 고정했다.
## 2026-08-01 (codex) — T-VN-41 fixed snapshot 내구성·수명 보강

- n150 isolated live E2E에서 일반 snapshot 첫 page가 200/UUID를 반환하지만 route session이 commit하지
  않아 header/items가 rollback되고 다음 cursor가 사라지는 P1을 재현했다.
- service route가 snapshot 생성·상태 검사·응답 DTO 구성을 한 transaction으로 묶고, 독립 request
  session에서 동일 UUID/root의 다음 page가 보이는 실제 PostGIS HTTP 회귀를 추가했다.
- generic 생성은 try-lock single-flight와 epoch/source-material watermark로 snapshot을 재사용한다.
  `cache_target.state_applied`만 재사용을 무효화하며 link/refresh/stream-reconciled event는 전체 복사를
  만들지 않는다. 재사용 cursor는 safe replay lower-bound라 consumer가 이후 event를 inbox receipt로
  중복 제거한다.
- 단일 READ COMMITTED statement가 material writer lock을 기다리며 pre-wait head에 더 높은 global cursor를
  결합할 수 있는 P0를 stream `FOR SHARE` barrier 별도 statement로 막았다. snapshot header는 global
  cursor와 material watermark를 분리 저장하고 현재 material watermark와 exact equality로만 재사용한다.
  이어서 서로 다른 target writer의 미커밋 낮은 relay를 더 높은 global cursor가 추월할 수 있는 P0를
  발견했다. 모든 outbox writer transaction이 head/target/link 접근 전에 stream `FOR UPDATE`를 획득하고,
  여러 system이면 정렬 순서로 모두 선취한다. 이 stream → head/target/link 순서가 각 system cursor를
  해당 stream의 commit-safe contiguous prefix로 만든다. global sequence는 번호 uniqueness만 제공하며
  서로 다른 stream 사이의 commit 순서를 의미하지 않는다.
- DB `BEFORE INSERT` trigger가 stream lock 뒤 명시적 global sequence에서 relay를 배정한다.
  Identity/default의 trigger 전 번호 할당 race를 제거하고 raw/future writer에도 같은 불변식을 강제한다.
- barrier 전에 5초 lock timeout과 30초 statement timeout을 설정해 hung writer가 advisory single-flight를
  무기한 점유하지 못하게 한다. timeout은 `503 snapshot_barrier_timeout + Retry-After: 1`로 변환한다.
- barrier 이후 capture/persist 30초 초과는 `503 snapshot_build_timeout + Retry-After: 1`로 구분한다.
- fresh/reuse handoff 전 75분, PinVi 수신 시 60분 traversal window를 이중 검증한다. 경합과 수명 부족은
  각각 `503 snapshot_busy`, `503 snapshot_ttl_too_short`와 `Retry-After: 1`로 fail-fast한다.
- reuse miss 시 system별 미만료·미참조 generic snapshot을 최대 2개로 제한한다. 세 번째 copy는 oldest
  expiry 기반 `429 snapshot_capacity_exceeded + Retry-After`로 거부해 유효 cursor 보존과 live storage
  상한 `2 × stream cardinality`를 함께 만족한다.
- capture는 최대 100,001행만 읽고 100,000 item을 넘으면 Python tuple/Merkle 생성 전에
  `413 snapshot_item_limit_exceeded`로 fail-close한다. bounded streaming/material 공유는 #922가 소유한다.
- 만료·미참조 snapshot만 item/header 제한 배치로 정리한다. reader header share lock과 GC의
  parent+item `SKIP LOCKED`를 결합해 header 읽기와 item 읽기 사이 CASCADE/직접 DELETE race를 막는다.
  reconciliation이 참조하는 snapshot은 terminal 상태도 immutable 감사 영수증으로 보존한다.
- hourly background GC는 전역 try-lock, system round-robin, batch별 commit과 time/statement/no-progress
  예산을 사용한다. exact remaining/total/unexpired/referenced count는 종료 시 한 번만 관측하고 overlap
  skip에서는 unknown이다. 기본 2백만 item은 실행당 상한이므로 production enable 전에 n150 soak와
  schedule enable이 필수다.
- physical connection lock을 정식 지원하도록 advisory helper 타입을 `AsyncSession | AsyncConnection`으로
  넓혔다. codegraph는 `try_advisory_lock` caller 18개, `advisory_lock` caller 20개, 영향 59 symbols를
  확인했고 기존 caller는 모두 `AsyncSession`, 신규 GC caller만 `AsyncConnection`이다.
## 2026-08-01 — H35 게이트 ① 실증, 그리고 내가 정한 게이트 값이 틀렸음을 발견

- 격리 clone에서 **실제 import 경로**를 태워 게이트를 재현했다(HTTP/인증만 제외):
  배포 전 **3,265** → 마이그레이션 직후 **3,043**(-222) → CSV 재import 후 **3,265**(±0).
  CSV 222행 전량 채택(미채택 0), `csv_explicit_feature_id` decision 222건 생성.
- **게이트 값 정정.** 1차 실행이 3,265로 나와 내가 문서에 박은 기대값 3,266에 1
  모자랐다. 추적하니 그 1건은 `[빵이네] 강원도여행정보`(`selection_origin=admin`,
  **`item_status='rejected'`**)였고, 공개 목록 술어는 `i.status = 'included'`를
  요구한다(`curation_repo.py:589`) — **애초에 공개 표면에 없던 항목**이다.
- 즉 **3,266은 "링크 수"이지 "공개 노출 수"가 아니다.** 링크 수를 게이트로 쓰면
  정상 배포에서도 FAIL이 뜬다. 게이트를 공개 목록과 같은 술어(`status='included'` +
  collection public/published + theme public + trusted decision)로 바꿨다.
- 같은 이유로 **공백은 223이 아니라 222**다. 내 공백 측정 쿼리가 `status <> 'archived'`만
  걸러 `rejected`를 포함시킨 오류였다.
- 교훈: 코드 경로로 "복구된다"까지는 맞게 확정했지만(222행 전량 채택으로 확인됨),
  **그 결과를 판정할 게이트 값 자체를 실행 없이 정한 것이 오류였다.**
## 2026-08-01 — #918·#919 머지, H35 배포 절차 확정

- 두 PR 모두 8/8 CI green으로 머지(`origin/main` = `e1afb1cf`). `0073`(H40) +
  `0074`(H41)가 main에 있다.
- 격리 restore clone(`0064~0074`)에서 재측정: trusted **3,266 → 3,043**.
  (~~공백 223건~~ → **정정: 공개 공백은 222건.** 위 게이트 실증 항목 참조.)
  H41 FK 4개 CASCADE, item PK 재작성 성공 확인.
- **복원 스크립트 자체의 결함을 먼저 잡았다** — `postgis/postgis` 베이스 이미지가
  초기화 때 postgis류 extension을 `public`에 깔아 두는 탓에, 덤프의
  `CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA x_extension`이 **조용히 no-op**
  되고 geometry 컬럼을 쓰는 테이블(`feature.features` 등)이 통째로 안 만들어졌다.
  복원 전에 그 extension들을 먼저 지우도록 고쳐 `feature.features` 1,030,661행 복원 확인.
  (`--clean --if-exists`는 오히려 topology 스키마 이중 생성으로 죽어서 쓰지 않는다.)
- **223건 복구 경로를 추론에서 확정으로 바꿨다.** #907/#910이 자동 링크를 조여서
  재import가 안 붙을 가능성이 있었는데, `_RESOLVE_FEATURES_BATCH_SQL`의 첫 UNION 분기가
  명시 `feature_id`로 정확히 1행을 내고 `_adopted_match`가 그것만 채택한다 — 조인 것은
  `address_hint` 단독 링크이고 명시 경로는 그대로다.
- **소요 시간 수치 2개를 모두 폐기했다.** 1,754초(이전)와 79.9초(이번) 둘 다 dagster가
  도는 상태에서 쟀는데 실제 배포는 dagster를 멈추고 돌린다 — 조건이 다르다. B′는
  시간제한 없는 일회성 컨테이너를 쓰므로 정확한 초수가 애초에 필요 없다.
- n150 재측정은 **중단**했다. 4코어에 load 11.6/iowait 44.7%였고, 조사해 보니 고장이
  아니라 T-VN-41 lane이 Playwright buildx 빌드 + 라이브 스택 2벌을 **지금 쓰고 있는**
  것이었다(컨테이너 9개, `RestartCount=0`, 1분 전 재생성됨). 정리 불가라 판단하고
  내 프로세스·컨테이너만 회수했다.
- 앞서 "swap 고갈은 위험 신호"라고 한 것은 **정정한다** — sudo로도 VmSwap을 잡은
  프로세스가 없고 `available` 7.9Gi다. 유휴 스왑이지 메모리 압박이 아니다.
## 2026-08-01 (codex) — T-VN-41 immutable target source receipt

- cache-target DELETE 성공 뒤 응답 유실로 같은 command를 exact retry하면 source ledger replay가
  historical target identity를 버려 `target_id`/`entity_tag`가 `null`이 되던 결함을 수정했다.
- n150에 적용된 `0075`를 수정하지 않고 선형 migration `0076_cache_target_receipt`을 추가했다. applied
  source event마다 당시 `target_lock_version`을 append-only ledger에 고정한다. 기존 active는 immutable
  outbox ETag, DELETE는 delete transaction timestamp가 일치하는 tombstone만 backfill하며 drift는
  migration을 중단한다.
- replay는 mutable target row의 현재 version을 읽지 않는다. tombstone 사후 UPDATE 뒤에도 ledger의
  historical UUID/version으로 최초 strong ETag를 exact 복원하고, source/outbox material 불일치는
  fail-close한다.
- PUT/DELETE response는 non-null UUID `target_id`, `entity_tag`, 양의 `target_sequence` 전용 DTO를 사용해
  generation 4-tuple을 완성한다. GET read DTO만 deleted head의 nullable identity/sequence를 유지하며
  OpenAPI와 생성 TypeScript를 같은 계약으로 갱신했다.
## 2026-08-01 (codex) — T-VN-41 migration rebase 선형화

- PR #917의 46개 commit을 최신 main에 rebase했다. 기능 commit은 range-diff에서 동일했고,
  `test_alembic_upgrade.py`는 main의 동적 head 탐지를 보존했다.
- main에 새 `0073`/`0074`가 있으므로 cache-target migration을
  `0075_cache_target_outbox`로 재번호화하고 `0074_curation_item_rekey_cascade`를 parent로 삼았다.
  병렬 head나 호환용 merge revision은 두지 않았다.
- 새 PostGIS DB에서 전체 체인 upgrade/downgrade를 실행하고, focused 회귀는 직접 predecessor
  `0074`에서 `0075`로 올린 뒤 다시 `0074`로 내려 H40/H41 스키마를 보존하는 경계를 고정했다.
## 2026-08-01 — T-VN-H40 `0073` 구현: source-rule link provenance

- `0072`가 공개 표면 fail-close를 넣으며 기존 link을 전부 `legacy_unattributed`로
  이관해, 격리 restore clone 실측에서 공개 노출 가능 link이 **3,266 → 0**이 됐다.
  concierge projection 3,044건은 근거가 실재하므로(`source_record_key` 100% 도달)
  `0073`이 `match_basis`에 **`source_rule`** 을 더하고 검증 통과분만 승격한다.
- `forward_recovery` 재사용은 하지 않았다 — merge 전용 의미라 빌려 쓰면 왜곡이다.
- 트리거는 `curated_features`가 아니라 **`curation_items`** 에 달았다.
  `sync_curated_feature_collection()`은 link 생성 지점이 둘이고 merge/detach 불변식이
  얽힌 800줄이라, 불변식이 사는 자리에 거는 편이 두 지점과 미래 writer를 함께 덮는다.
- **승인 근거 판정이 두 곳에 다른 모양이었다** — 공개 표면 denylist, merge whitelist.
  값이 늘 때 whitelist만 뒤처지면 공개 표면이 노출하는 link을 merge가 끊는다.
  `infra/curation_link_basis.py` 한 곳으로 모으고 양쪽 whitelist로 맞췄다.
- **읽기로 낸 결론 2건이 실행으로 뒤집혔다.** `0065`의 함수 정의가 파일에 두 번
  나오는데 downgrade 본문을 최신으로 읽어, "트리거가 item을 DELETE 후 INSERT하므로
  RESTRICT로 writer가 죽고 decision이 누적된다"고 봤다. 컨테이너에 `0072`를 올려
  재현하니 UPDATE·DELETE 모두 정상이었다. 실제 정의는 targeted UPDATE +
  `ON CONFLICT DO NOTHING`이다. 누적 축은 그래도 회귀 테스트로 고정했다.
- 게이트: unit **1821 passed**, 관련 integration **91 passed**,
  `ruff`/`mypy --strict`(123 files)/`lint-imports`(4 kept). 새 통합 테스트 6건은
  **변이 2회**로 falsifiability를 확인했다 — 검증 술어를 빼면 fail-close 2건,
  재진입 가드를 빼면 누적·멱등 3건이 죽는다.
- `test_alembic_upgrade.py`가 head revision을 리터럴로 박아 마이그레이션 추가마다
  깨졌다. ScriptDirectory에서 계산하도록 바꿨다.
## 2026-08-01 (codex) — T-VN-41 restore fence stream-scoped FK

- exact head `0399d680`에서 codegraph sync/impact를 실행하고 restore fence와 reconciliation ORM,
  0073 clean migration, 관련 PostGIS 회귀로 변경 범위를 한정했다.
- reconciliation에 `(external_system, request_id)` unique key를 추가하고 fence의 nullable request
  참조를 같은 두 열의 composite FK로 교체했다. count/UUID CHECK와 `MATCH SIMPLE`을 조합해
  `0/null`은 유지하면서 다른 stream UUID의 INSERT와 referenced parent stream UPDATE를 막는다.
- migration은 reconciliation table 생성 시 unique key를 먼저 만들고 late fence FK를 생성한다.
  downgrade는 fence FK를 먼저 제거한 뒤 reconciliation table을 내려 순환 의존을 남기지 않는다.
- clean migration metadata와 ORM constraint name/column order/delete rule을 exact 검증하고,
  same-stream fence/replay 및 raw cross-stream `23503` 음성 회귀를 고정했다.
- focused PostGIS/migration **21건**, Ruff, strict mypy **1 file**, import-linter **4 contracts**,
  OpenAPI all-profile drift check가 통과했다. service OpenAPI SHA-256은 변경 전후
  `4bca03b2f67a24a9e36b628561a6e598955a208420eb8e9f30e7a0c16a701066`으로 동일하다.
## 2026-08-01 (codex) — T-VN-41 restore fence receipt HTTP 상관 불변식

- codegraph sync 후 `CacheTargetRestoreFenceRecord`의 schema/route 영향을 확인하고 HTTP
  응답 계약으로 변경을 한정했다.
- Pydantic after validator는 count `0` iff UUID `null`, count `1` iff UUID non-null을
  강제하며 두 valid/두 invalid 조합을 schema 회귀로 고정한다.
- OpenAPI 3.1 object-level `oneOf`도 `0/null`, `1/format: uuid` 두 branch만 허용해 PinVi가
  필드 상관관계를 기계 검증할 수 있다. recovery operation ID도 UUID schema/runtime 계약으로
  좁혀 임의 문자열 producer 결과를 fail-close한다.
- API/OpenAPI 집중 회귀, targeted Ruff, strict mypy, diff-check와 admin type 생성 검증을 통과했다.
## 2026-08-01 (codex) — T-VN-41 restore fence active reconciliation supersession

- exact head `0755070d`와 clean 상태에서 시작해 `CacheTargetRestoreFenceResult`와
  `CacheTargetReconciliationResult` codegraph impact를 확인했다.
- 0073 clean schema/ORM에 terminal `superseded` lifecycle, `restore_fenced` 사유, stream별 active
  partial unique index를 추가했다. fence는 stream lock 아래 claim/delivery/reconciliation을 함께
  종결하고 seal/completion도 같은 stream→request lock 순서로 맞췄다.
- append-only fence receipt는 `invalidated_claim_count`, delivery/reconciliation superseded count와
  nullable request UUID를 저장한다. repository와 service response는 exact replay에서도 최초 receipt와
  version을 반환한다.
- PostGIS 회귀는 preparing/running 양쪽의 lifecycle shape, old snapshot/seal/completion 거부, phase
  불변 replay와 새 epoch begin 성공을 검증한다. API 회귀는 fence 응답의 모든 audit field를 고정한다.
- 관련 PostGIS/migration **20건**, API/OpenAPI **52건**, targeted Ruff, strict mypy **5 files**,
  import-linter **4 contracts**가 통과했다.
## 2026-08-01 (codex) — T-VN-41 restore fence superseded terminal 보강

- exact `e315bfc4`, `origin/main` behind 0에서 시작하고 stream/outbox/model codegraph impact를 수정 전에
  실행했다. 각 직접 영향은 file symbol 1개였으며 migration, reconciliation, API/admin 소비 경계를
  추가로 추적했다.
- 0073 clean schema와 ORM delivery 상태에 terminal `superseded`/`superseded_at`을 추가했다. fence는
  새 epoch보다 낮은 pending/retry/leased/dead 전부를 원자 종결하고 audit count를 receipt에 보존한다.
- claim은 current epoch의 nonterminal만 잠그고, old dead는 DLQ/replay와 reconciliation dead gate에서
  제외한다. NACK도 fence와 같은 stream→claim lock 순서를 사용한다. stream/API/admin aggregate는
  `superseded_count`를 backlog와 별도로 노출한다.
- PostGIS 회귀는 delivered 보존과 네 non-delivered 상태 supersession, active claim 무효화, old dead
  조회/replay 불가, exact fence replay의 version 불변, 새 epoch event claim 도달을 한 흐름으로 검증한다.
## 2026-08-01 (codex) — T-VN-41 reconciled request receipt 보강

- 지정 branch `feat/tvn41-cache-target-generation-outbox`의 exact head `6427358d`와 clean 상태,
  `origin/main` behind 0을 확인해 rebase를 생략했다.
- 임시 worktree의 codegraph를 1회 초기화하고 reconciliation producer와 API schema impact를 수정 전에
  실행했다. 두 파일 모두 codegraph 직접 영향은 file symbol 1개였고 실제 소비 경계인 repo/API/
  OpenAPI 테스트를 함께 고정했다.
- 성공 `cache_target.reconciled` payload에 `request_id`를 추가하고 strict typed payload union에서 exact
  `{request_id, snapshot_id, actual_merkle_root, expected_merkle_root, status, version}`를 강제했다.
  repo integration은 payload 전체와 `source_payload_fingerprint == expected root`를 단언한다.
- API/OpenAPI 회귀는 request/snapshot UUID format, 추가 필드 금지, 여섯 required field와 claim
  직렬화를 검증한다. 계약 문서는 request→fixed snapshot→terminal receipt 인과관계를 명시했다.
- admin one-step reconciliation receipt와 operation 조회에 request-bound `snapshot_id`를 노출했다.
  isolated live는 receipt UUID가 초기 설정 snapshot과 다르고 최종 `last_snapshot`과 같은지 검증하며,
  중간 `running` 상태 관측은 요구하지 않는다.
- focused API **50건**, PostgreSQL integration **1건**, targeted strict mypy **2 files**가 통과했다.
  functional owner와 생성 artifact는 PinVi contract pin provenance를 위해 별도 commit으로 확정한다.
