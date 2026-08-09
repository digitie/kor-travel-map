# T-VN-34 — Feature 직교 상태 모델 단일 cutover 계획

- **상태**: proposed — 적대 계획 리뷰 P0 반영본
- **날짜**: 2026-08-09
- **선행**: T-VN-31A/B/C 완료, T-VN-33→T-VN-38 stacked PR 체인
- **후속**: T-VN-36, T-VN-39, T-VN-41F1D-D

## 1. 범위와 병합 규율

T-VN-34는 `status`/`deleted_at`/`user_deleted_at`이 섞어 표현하던 Feature 상태를
`lifecycle_state`, `publication_state`, `quality_state` 세 typed 축으로 교체한다.
`T-VN-40`의 큐레이션 write 모델과는 별개 task다.

현재 T-VN-31A/B/C는 `tasks.md`상 완료됐고, T-VN-33과 T-VN-38은 아직 main에 병합되지 않은
parent stack이다. 따라서 이 task는 T-VN-38 head를 base로 하는 A/B/C draft stack으로 준비한다.
각 PR은 리뷰 단위이지만 A/B만 따로 배포하거나 main에 병합하지 않는다. C head가 모든 변경을
포함한 한 번의 forward-only final cutover가 된다. parent chain이 main에 들어온 뒤 rebase·retarget한
정확한 head만 최종 검증·병합한다.

서비스 전 단계이므로 기존 DB 데이터·old API·old UI·old binary rollback을 보전하지 않는다. 실패한
candidate는 final schema를 fresh rebuild한 뒤 provider ETL로 다시 채운다. dual-write, legacy shadow
trigger, 읽기 호환 shim, held rollback column은 금지한다.

## 2. 정본 상태와 mapping

세 축은 모두 `NOT NULL` typed text + DB CHECK다.

| 축 | 값 | 의미 |
|---|---|---|
| lifecycle | `active`, `retired` | Feature 관측의 운영 생명 여부 |
| publication | `draft`, `published`, `suppressed` | 유효한 active Feature를 공개할 운영 의도 |
| quality | `valid`, `quarantined` | payload/검증 품질 판정 |

공개 정본은 오직 `(active, published, valid)`다. 다음 진리표의 여덟 조합만 허용한다.
`retired`는 반드시 `suppressed`여야 한다. `published + quarantined`는 허용한다. 공개 의도는
보존하되 품질 복구 전에는 노출하지 않으므로, quality 축만 복구해 재공개할 수 있다.

| lifecycle | publication | quality | 허용 | 공개 |
|---|---|---|---|---|
| active | draft | valid | 예 | 아니오 |
| active | draft | quarantined | 예 | 아니오 |
| active | published | valid | 예 | 예 |
| active | published | quarantined | 예 | 아니오 |
| active | suppressed | valid | 예 | 아니오 |
| active | suppressed | quarantined | 예 | 아니오 |
| retired | suppressed | valid | 예 | 아니오 |
| retired | suppressed | quarantined | 예 | 아니오 |
| retired | draft 또는 published | 모든 값 | 아니오 | 아니오 |

legacy backfill은 다음 우선순위로 한 번만 계산한다. 모순 행 수와 tuple별 수를 migration
preflight receipt에 남긴 뒤 final schema를 ETL로 재생성할 수 있으므로 추정 보정하지 않는다.

| 계산 순서 | 규칙 |
|---|---|
| quality | `status='broken'`이면 `quarantined`, 그 외 `valid` |
| lifecycle | `user_deleted_at IS NOT NULL`, `deleted_at IS NOT NULL`, `status IN ('inactive','deleted')` 중 하나면 `retired`, 그 외 `active` |
| publication | lifecycle이 `retired`면 `suppressed`; 그렇지 않고 `draft`면 `draft`, `hidden`이면 `suppressed`, 나머지는 `published` |

`user_change_*`는 Feature 공개 상태가 아니다. 요청의 provenance는
`ops.feature_change_requests`와 version/audit 계열에 남기고 T-VN-34C에서 Feature core에서 제거한다.
반면 `data_origin`과 `data_version`은 T-VN-36이 whole-row freeze를 field override로 물화하고
provider/user ownership을 대조할 입력이다. T-VN-34는 이를 읽거나 삭제하지 않으며, T-VN-36C가
그 대체 정본·effective projection을 검증한 final migration에서 물리 삭제한다.
legacy backfill audit의 `occurred_at`은 `COALESCE(user_deleted_at, deleted_at, updated_at)`이고,
`user_deleted_by`가 있으면 principal로, 없으면 `migration:tvn34`으로 기록한다. reason은
`legacy_user_delete`, `legacy_provider_retire`, `legacy_status_retire`, `legacy_status_map` 중 하나이고,
`user_change_request_id`는 `causation_ref`로 남긴다. timestamp와 request가 서로 모순되거나 request가
존재하지 않으면 migration은 tuple/count를 receipt에 남기고 fail-closed한다. 새 final DB는 ETL로
재생성하므로 임의 추정으로 행을 살리지 않는다.

## 3. DB 무결성과 전이 감사

`feature.feature_state_transitions`는 Feature별 상태 변경의 append-only 정본이다. 0095의 현행
parent schema와 같은 `feature_id TEXT`를 보존형 business identifier로 저장하고, 같은 행에
`feature_uuid UUID`도 반드시 기록한다. Feature table FK는 두지 않는다. Feature hard purge 뒤에도
state audit는 남아야 하므로 `ON DELETE CASCADE`는 금지한다. 따라서 T-VN-39가 legacy TEXT PK/FK를
제거해 final UUID core로 전환할 때도 purge된 audit를 포함해 UUID identity를 잃지 않는다. 0095의
runtime procedure는 현행 TEXT key를 받고 final target procedure는 UUID key를 받는 전환 경계를
명시적으로 유지한다.

- 상태 축과 base Feature `INSERT`는 runtime role에 직접 권한을 주지 않고,
  `feature.create_feature_with_initial_state(...)`와 `feature.transition_feature_state(...)`
  security-definer procedure만 바꾼다. user add/update/delete의 legacy provenance와
  immutable response-shape version snapshot도 runtime이 직접 쓰지 않고, typed
  `feature.materialize_user_feature_change_provenance(...)` procedure가 request·Feature·expected
  revision을 잠가 한 transaction에서 기록한다. 따라서 runtime에는 `feature_versions` INSERT나
  `features_detailed` SELECT를 주지 않는다. 이는 0095 현행 schema의 전환 bridge이며, final target에는
  남기지 않는다. T-VN-36이 field-override effective projection/lineage로 대체한 뒤 legacy request와
  version relation을 물리 제거한다. 이와 마찬가지로 **0095 현행 schema 전환 bridge에서만** provider
  version `0`은 runtime JSON payload를 받지 않는 `feature.materialize_provider_feature_version(...)`
  procedure가 잠긴 Feature와 `features_detailed`에서만 조립한다. user whole-row fence가 provider
  core/subtype 변경을 막은 refresh는 user effective row를 provider baseline snapshot으로 오기록하지
  않도록 그 snapshot을 재기록하지 않고 immutable raw source observation만 최신화한다. T-VN-36 final
  effective projection/lineage가 user/provider version bridge를 함께 대체한다. lifecycle override의 작성·철회 역시
  T-VN-34A의 transitional generic
  `ops.feature_overrides` DML이 아니라 각각 expected revision으로 Feature row를 잠그는 typed
  `author_lifecycle_override(...)`/`revoke_lifecycle_override(...)` command만 사용한다. 0095의 이 여섯
  procedure는 dedicated NOLOGIN owner, fixed `search_path`, schema-qualified dependency,
  `REVOKE EXECUTE FROM PUBLIC`를 사용하며 각 runtime role에 필요한 `EXECUTE`만 grant한다. INSERT와
  transition procedure의 세 축 UPDATE를 DB trigger가 포착한다. 한 UPDATE에서 여러 축을 바꾸면 한
  audit row에 이전/이후 세 tuple 전체를 기록한다.
- 신규/legacy-backfill 행은 이전 tuple이 NULL인 `initial`/`legacy_backfill` transition만 허용한다.
  일반 transition은 이전/이후 tuple이 모두 유효하고 적어도 한 축이 달라야 한다.
- audit row에는 `transition_kind`, non-empty `reason_code`, authenticated `principal`, nullable
  `causation_ref`, `occurred_at`, 적용 뒤 `row_revision`, `session_user`, `current_user`를 저장한다.
  transition kind는
  `initial|legacy_backfill|provider_sync|admin|user_request|merge|quality_validation|system`만
  허용한다. procedure는 role별 structured transaction-local context를 검증하고, trigger는 missing,
  malformed, unknown kind를 거부한다. provider principal은 procedure가 `provider_dataset_id`에서
  파생한다. provider가 전달하는 dataset/entity/record key는 같은 active dataset과 target Feature의
  source link 및 `source_entity_heads`의 current observation을 procedure가 잠근 상태에서 검증하며,
  audit의 authoritative receipt는 caller JSON이
  아니라 그 `source_records.raw_payload_hash`에서만 파생한다. admin/user principal은 인증 경계가
  검증한 principal만 전달한다. DB는 end-user identity를 독자적으로 증명하지 않으므로
  application-authenticated principal과 DB session identity를 함께 감사한다.
- audit writer trigger function도 procedure와 분리된 dedicated NOLOGIN owner의
  `SECURITY DEFINER`, fixed `search_path`, schema-qualified dependency로 둔다. audit table은
  `REVOKE ALL` 뒤 audit writer owner에만 INSERT를 grant하고 runtime role에는 SELECT만 필요한 범위로
  grant한다. runtime과 PUBLIC에는 trigger function direct EXECUTE를 주지 않는다. audit
  mutation/`TRUNCATE` guard와 catalog privilege assertion을 함께 둔다. migration owner의 DDL 권한은
  운영 runtime 신뢰 경계 밖이며, direct audit DML은 허용하지 않는다.
- nested security-definer 내부의 `current_user`는 가장 안쪽 audit writer owner이므로 state procedure
  owner로 오인하지 않는다. state create/transition procedure는 DML 직전에 allow-listed
  `feature.state_procedure_definer`를 `SET LOCAL`하고, audit trigger는 이 context를 필수 검증해
  `state_procedure_definer`로 기록한다. audit trigger의 실제 `current_user`는 별도
  `audit_writer_definer`로 기록한다. 각 runtime은 독립 login `session_user`로 접속하고 `SET ROLE`
  권한을 갖지 않으며, audit에는 `invoker_role=session_user`도 함께 기록한다. migration/backfill은
  전용 migration role과 `legacy_backfill` context만 허용한다.
- privilege fence의 runtime은 bootstrap/schema owner가 아니다. `ktm_feature_schema_owner` NOLOGIN group이
  dedicated DB와 feature/ops/provider_sync object를 소유하고, Alembic은 별도 LOGIN
  `ktm_feature_migrator`가 `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN`으로만 실행한다. API와 Dagster는 별도
  LOGIN `ktm_feature_api_runtime`/`ktm_feature_dagster_runtime`가 각각
  `KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN`/`KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN`으로 접속해 shared
  NOLOGIN `ktm_feature_runtime`의 최소권한만 얻는다. role membership은 INHERIT·SET FALSE라 runtime
  session이 owner로 승격하지 못한다. runtime login은 superuser, CREATEROLE, BYPASSRLS,
  schema-owner membership을 가질 수 없다. role password는 Alembic이 만들지 않으며 ignored deployment
  secret에서 pre-provision한다. bootstrap ownership transfer는 PostgreSQL system catalog까지 건드리는
  `REASSIGN OWNED`가 아니라 dedicated application DB의 schema/relation/routine/type만 명시적으로
  이전한다. startup preflight는 `session_user=current_user` runtime identity, procedure EXECUTE,
  direct feature/audit/legacy surrogate mutation 거부를 실제 DSN으로 검사하고, runtime login으로
  실제 `load_bundle` provider lineage·version materialization과 admin request materialization을
  실행한다. runtime에는 `feature_versions`, audit, state axis, legacy provenance, generic
  `ops.feature_overrides`의 직접 DML을 grant하지 않는다.
- `active → retired`는 일반 상태 명령과 provider tombstone에서 허용한다. `retired → active`는
  재적재 전용 명시 transition으로만 허용하며, publication은 자동 복원하지 않는다.

이 설계는 raw SQL writer까지 state audit과 DB session identity를 강제한다. application event만
쓰는 방식은 repository·migration·fixture direct SQL가 우회할 수 있으므로 채택하지 않는다.

## 4. reader·writer·REST 계약

공개 reader(detail, batch, bbox, search, nearby, cluster, collection)는 `feature.public_features`만
사용한다. 이 view는 명시 열 목록으로 정의하고, `features_detailed` 재생성 순서와 `pg_depend`를
migration test로 고정한다. `SELECT *`를 통해 새 운영 상태가 public payload에 새어 나가지 않는다.

현재 core의 point `coord`/`coord_5179`와 category/keyset/text index는 3축을 직접 partial predicate로
표현할 수 있다. 반면 route/area geometry는 typed subtype table에 있고 3축은 core table에 있으므로,
PostgreSQL partial GiST가 두 relation을 join해 public predicate를 직접 표현할 수 없다. T-VN-34B는
`feature_routes`와 `feature_areas`에만 `public_ready` DB-owned projection flag를 둔다. core point와
text/category/keyset index는 `WHERE lifecycle_state='active' AND publication_state='published' AND
quality_state='valid'`를, route/area GiST는 `WHERE public_ready`를 쓴다.

state create/transition procedure와 route/area subtype INSERT·feature-id reattachment trigger는 모두
parent Feature row를 먼저 `SELECT ... FOR UPDATE`로 잠그고 same transaction에서 tuple/flag를 계산한다.
state procedure는 lock을 유지한 채 기존 route/area flag를 갱신하고, subtype trigger는 lock 뒤의
현재 tuple로 NEW flag를 강제 산출하므로 update×insert의 MVCC stale cache 경쟁을 만들지 않는다.
subtype trigger는 supplied `public_ready`를 항상 덮어쓰며 runtime에는 `UPDATE(public_ready)`와
`TRUNCATE`/trigger-disable 권한을 주지 않는다. route/area runtime 권한은 table-level `UPDATE`/`INSERT`가
아닌 allowed business column의 column-list grant만 사용하고 `public_ready`는 명시적으로 제외한다.
`has_table_privilege(..., 'UPDATE')`와 `has_column_privilege(..., 'public_ready', 'UPDATE')`가 모두
false인 catalog gate, direct flag UPDATE의 SQLSTATE `42501`, trigger-controlled insert/reattach/state update
동등성을 integration test로 고정한다. public query는 cache만 신뢰하지 않고 항상
`public_features`의 core predicate/join을 최종 visibility fence로 유지한다. core tuple이 유일한
정본이고, 양방향 `EXCEPT ALL`은 flag·public view·core predicate drift의 regression proof다. full GiST로
상태 join 비용을 숨기거나, subtype에 독립적인 상태 정본을 만들지 않는다.

public DTO와 query에는 legacy `status`를 두지 않는다. service batch 상태는 다음처럼 DB tuple에서
계산한다: base 없음=`missing`, `lifecycle=retired`=`retired`, active이지만 public predicate 불만족=
`suppressed`, public이며 revision 동일=`unchanged`, 나머지=`found`. transport error는 기존처럼
503이고 `missing`으로 합성하지 않는다.

admin surface만 세 축과 audit timeline을 반환·필터·수정한다. public response에는 `status`도 axes도
없다. admin list/detail/map은 `lifecycle_state`, `publication_state`, `quality_state`를 필수로
반환하고, 세 repeated filter는 AND로 결합한다. 상태 수정은
`PATCH /v1/admin/features/{feature_id}/state`의 하나의 atomic command이며 If-Match revision,
`reason_code`, 하나 이상 바뀌는 축을 요구한다. admin UI는 하나의 status badge/dropdown 대신 세
badge·AND filter·명시 state command를 제공한다.

기존 `POST /deactivate`는 제거하고 state command의 `retire` action으로 대체한다. 이는
`(retired,suppressed,<기존 quality>)` 한 tuple을 한 revision으로 쓴다. axis별 writer와 우선권은
다음 표가 정본이다.

| writer | lifecycle | publication | quality | reactivation/override 규칙 |
|---|---|---|---|---|
| provider sync | 자기 source의 initial·retire만 | 신규 initial만 | 변경 금지 | current record의 DB-derived receipt와 Feature-source link가 증명되고, active `lifecycle_state=retired` override가 없을 때만 재적재 procedure로 `active` 전이 가능 |
| admin/user request | retire 및 명시 reingest | draft/published/suppressed | 수동 quarantine/복구 | retire/merge는 typed command로 current/직전 audit revision에만 맞는 `lifecycle_state=retired` override를 만들며 provider는 이를 해제할 수 없다 |
| quality validator | 변경 금지 | 변경 금지 | valid/quarantined | admin quality override가 있으면 validator는 source verdict만 기록하고 effective quality를 덮지 않는다 |
| merge | loser retire만 | suppressed만 | 보존 | `merge_loser` lifecycle override를 만들며 explicit merge undo 또는 reingest만 revoke 가능 |
| Dagster tombstone | provider와 같은 retire | 변경 금지 | 변경 금지 | dataset/source membership을 procedure가 검증한다 |

기존 `field_path='status'` override는 T-VN-34A에서 typed `lifecycle_state` override로 옮긴다.
admin/user retire와 merge retire는 generic upsert가 아닌 Feature lock·expected revision을 요구하는
typed author command로 그 active override를 원자적으로 만든다. 이 command는 source value를 임의로
받지 않고 현재 lifecycle 또는 해당 current state를 만든 exact audit revision의 이전 lifecycle과만
일치시킨다. `retired → active`는
`POST /v1/admin/features/{feature_id}/state/reactivate`가 expected revision, reason, active current
source evidence를 받아 typed revoke command로 override를 철회하고 시행하는 경우만 가능하다. provider reappearance는
override를 revoke하지 못한다. provider와 admin/quality concurrent update, override revoke와 source
refresh 경쟁은 feature row lock 아래 하나의 procedure로 직렬화해 revision/audit 한 쌍을 남긴다.

admin-only reader도 public view로 기계 치환하지 않는다. `public`, `selectable(active+valid)`,
`admin_any` 세 predicate를 이름과 SQL로 분리해 draft/suppressed 검토 대상이 사라지지 않게 한다.

## 5. 작업·PR 분할과 병렬 소유권

| task/PR | 책임 | 소유권 | 배포 가능 여부 |
|---|---|---|---|
| T-VN-34A | target contract freeze, migration spine, tuple mapping/preflight, transition audit trigger, typed lifecycle override와 core/producer writer 전환, runtime/migrator DB principal·startup preflight 및 DB integration | agent A: Alembic·models·DTO/core/client·infra provider writer·runtime bootstrap·contract SQL/test | stack 내부 전용 |
| T-VN-34B | `public_features` explicit projection, trigger-owned route/area `public_ready` projection flag와 explicit column ACL, public/service classifier, core point `WHERE 3축` 및 route/area `WHERE public_ready` spatial partial GiST와 core category/keyset/text B-tree/GIN index EXPLAIN, reader integration | agent B: public/admin repository reader·service/API read schema·performance tests | stack 내부 전용 |
| T-VN-34C | admin state command, OpenAPI/type/UI, remaining admin/merge/Dagster writer, fixtures/live runner, final migration에서 legacy status 계열·index 물리 삭제 | 통합 소유: API/frontend/live E2E 및 final migration | C head만 배포·병합 가능 |

agent A/B는 서로의 소유 파일을 되돌리지 않고, 공유된 contract SQL과 generated OpenAPI를 기준으로
자주 rebase한다. migration-bearing changes는 전역 순서를 지킨다. C가 아닌 PR은 review-ready
draft이며 실행 환경에 적용하지 않는다.

## 6. 최종 migration과 제거 manifest

C의 final migration은 같은 deployment unit에서 다음을 실행한다.

1. 새 3축·tuple CHECK·transition table/trigger를 만들고 mapping diagnostic과 backfill audit를 수행한다.
2. 모든 writer/readers가 axes와 public view만 사용함을 static inventory 및 focused integration으로
   증명한다.
3. legacy `status`, `deleted_at`, `user_deleted_at`, `user_change_kind`, `user_change_status`,
   `user_change_request_id`, `user_deleted_by`, `user_change_reason`와 그것에 의존하는
   CHECK/index/trigger/query를 물리 제거한다. `data_origin`/`data_version`/whole-row freeze는
   T-VN-36A-C가 field override provenance와 effective projection으로 대체한 뒤 T-VN-36C에서
   별도로 제거한다.

`consumer-rollout-v1.json`과 T-VN-39의 removal manifest에는 위 객체가 이미 제거됐음을 기록한다.
T-VN-39에 오래 보관할 compatibility surface는 남기지 않는다.

## 7. 검증 matrix

| 구간 | 필수 증거 |
|---|---|
| contract/DDL | 여덟 허용 tuple과 네 retired illegal tuple 전수, runtime direct Feature INSERT/axis UPDATE와 direct audit INSERT/UPDATE/DELETE/TRUNCATE가 DB에서 거부됨, create/transition procedure는 정확히 한 audit을 만듦, no-op/missing/malformed context 거부, runtime/migrator identity·owner/EXECUTE/table grant catalog assertion; actual/target artifact SHA와 violation fixture 갱신 |
| mapping/audit | 모든 legacy tuple과 contradictory diagnostic, create/backfill/provider/admin/user-request/merge/Dagster transition의 old/new tuple·principal·invoker/state-procedure/audit-writer DB identity·reason·revision 검증, feature purge 뒤 audit 보존 |
| public/read | 여덟 tuple × detail/batch/bbox/search/nearby/cluster/category/collection public leak 0, batch 5-state, admin predicate 분리, status reference normal-path gate, view/core/route-area `public_ready`의 양방향 `EXCEPT ALL` regression proof, two-session axis-update×subtype-insert interleaving, direct flag UPDATE `42501`과 table/column privilege catalog gate |
| 성능 | core point bbox 4326/5179·nearby와 route/area `WHERE public_ready` geom partial GiST, core category/keyset/text hot predicate가 exact 3축 partial predicate를 사용한다는 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` gate |
| API/UI | OpenAPI all export/check, Map/PinVi generated client compile, admin state command If-Match conflict, axes filter/badge/timeline browser e2e, provider refresh×admin retire/override revoke×quality validator race |
| final live | n150 isolated candidate에서 final head fresh PostGIS + provider ETL 재적재, destructive admin/public/PinVi live E2E 메인·recovery, cleanup/physical legacy catalog zero |

## 8. 계획 리뷰 반영

두 적대 계획 리뷰의 P0를 반영했다. T-VN-31 barrier 미완료라는 지적은 현재 task index에서
T-VN-31A/B/C가 완료되어 있어 기각했다. 반면 inactive/deleted 의미 혼합, writer/override
split-brain, view 조기 전환, legacy held rollback, OpenAPI/PinVi/live fixture status 결합은 모두
위 mapping·single-cutover·hard removal·verification 규칙으로 수용했다.
