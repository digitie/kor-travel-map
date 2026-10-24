# ADR115 SQL writer inventory — 413 이후 남은 경계

## 기준과 판정

이 보고서는 운영 조회/DB 실행/코드 수정 없이 `alembic/head-schema.sql`과 첫-party Python SQL 호출부를 대조한 정적 조사다. 기준 소스는 `271ed151685ac60d5a993c46f5f957c3843efdf6`, head oracle SHA256은 `2de8a20a78631f876b034f3cdfedc2e41102047e91ff5da8ac5157bb0c851d47`이다. 413의 새 protocol-first 7개가 반영된 oracle이며, 별도 native1375 및 향후 migration414의 완성본을 포함하지 않는다.

**413은 전수 writer closure가 아니다.** 이름이 같은 2-int protocol gate에 참여하는 legacy SQL 진입은 늘었지만, 직접 호출 가능한 state/create/override 13개와 M05·catalog·receipt 경계가 남아 있다. 이 중 **M05의 Feature→source/head 잠금 역순은 본문으로 확인**했다. 실제 교착 재현·수정은 별도 414 담당자의 작업으로, 이 정적 조사 자체가 실제 deadlock/운영 장애를 측정했다는 뜻은 아니다. 다른 항목은 잠재 충돌·설계/시험 대상으로 구분한다. T-CWRITE 전체 acceptance/활성화·운영 효과·Weather/Transport 전파 완료로 바꾸지 않는다.

기계 목록은 audit `map413-sql-writer-inventory.json`이다. 파일 SHA256은 `b98419b51c763043df216c8e803794d83da1a27f652f994824e61584933a9fa5`다. 235개 application routine 모두의 원문 signature, owner, SECURITY DEFINER 여부, oracle 행, body SHA, 명시 DML 대상, SQL callee, Python SQL wrapper, helper를 포함한 순서 있는 lock event, explicit EXECUTE grantee 및 trigger 연결을 기록했다. SQL helper의 lock을 빼먹으면 순서를 오독할 수 있어 helper 호출도 lock event에 포함했다.

## 수량의 의미

- 전체 routine 235개, 그중 SECURITY DEFINER 136개다.
- 본문에서 명시 INSERT/UPDATE/DELETE/TRUNCATE를 찾은 **정적 DML 후보 76개**다. 호출 전파로 후보 86개가 된다. 이 수는 독립 writer 수나 완료해야 할 PR 수가 아니다. trigger/callee 중복과 동적 SQL, 문자열 참조의 보수적 과대 분류가 있다.
- trigger 연결 194개를 별도 추출했고 연결된 helper 95개를 trigger 부수 효과/검증 계층으로 분류했다. 불변/검증 trigger를 직접 writer entry와 같은 수로 세지 않는다.
- 첫-party Python의 qualified DML 문자열 후보 229곳도 부록 JSON에 남겼다. module SQL constant와 실제 wrapper를 구분하며, 이는 ORM/동적 SQL을 포함한 모든 쓰기 경로의 완결 증명은 아니다.

## 이미 정렬된 경계와 shared 경로

`feature_repo._FEATURE_CURATION_WRITE_LOCK_SQL`(175행)의 MATERIALIZED CTE는 protocol EX → 기존 `feature-curation-write`를 강제한다. `lock_feature_curation_write`(294), provider `upsert_feature`(2692/2722)·source/link 적재·retirement·merge(`merge_repo.apply_feature_merge`,818/835) 계열은 이 Python fence를 먼저 사용한다. 반대로 **직접 SQL CALL은 Python fence를 통과하지 않는다.** DB 권한 preflight의 allowlist는 실행 권한 검사이지 SQL 자동 잠금 삽입 장치가 아니다.

413의 7개는 첫 BEGIN의 protocol EX → 기존 import/global/per-Feature/row 잠금이다. 기존 signature/body/owner/SD/search_path/ACL을 보존하는 migration이며 412의 private recorder/activation은 별도 조건을 가진 기존 진입이다.

| 413 대상 | oracle 행 | 직접 Python wrapper |
| --- | ---: | --- |
| `feature.archive_curation_item_command` | 2222 | `src/kortravelmap/infra/curation_repo.py:4210 archive_curation_item_command` |
| `feature.create_curation_item_command` | 3767 | `src/kortravelmap/infra/curation_repo.py:3823 create_curation_item_command` |
| `feature.create_manual_curation_item_with_feature_command` | 4145 | `src/kortravelmap/infra/curation_repo.py:3918 create_manual_curation_item_with_feature_command` |
| `feature.finalize_provider_curation_root` | 5003 | `src/kortravelmap/infra/feature_operation_repo.py:708 _finalize_authoritative_curation_root` |
| `feature.patch_curation_item_command` | 6910 | `src/kortravelmap/infra/curation_repo.py:4071 patch_curation_item_command` |
| `feature.reclassify_curation_quarantine_command` | 8532 | `src/kortravelmap/infra/curation_repo.py:5013 move_curation_quarantine_items`; `src/kortravelmap/infra/curation_repo.py:5076 confirm_curation_quarantine_standalone` |
| `feature.register_provider_field_shadow_policy` | 9217 | 직접 SQL/배포 owner 호출; Python 업무 wrapper 없음 |

`ops.begin_scoped_feature_write`(12294)는 protocol mode → 정렬한 participant scope → source entity/head FOR UPDATE → link FOR SHARE → Feature FOR UPDATE → membership 재검증 순서다. shared scalar recorder/recompute는 아무 CALL이나 허용하지 않고 같은 TX의 applying attempt/manifest/Feature membership 및 active policy를 검사한다. `_project_provider_field_candidates`는 private callee이고 legacy recorder는 NULL-attempt 분기에서 EX를 사용한다. 이 6개를 단순히 “protocol 호출 문자열 없음”으로 새 무보호 writer로 세면 안 된다.

## 13개 state/create/override entry — protocol 부재와 오류를 구분

아래 13개 본문에는 자체 protocol 진입이 없다. 전부 새 결함이라는 뜻은 아니다. source→link→Feature 순서를 지키는 경로, Feature row/revision만으로 충돌을 직렬화할 수 있는 경로, 신규 identity 경로를 나눠 실제 PG로 증명해야 한다. SQL signature 전체/owner/grantee는 기계 JSON을 정본으로 한다.

| routine | oracle 행 | 실제 잠금/쓰기 순서 | Python/SQL 호출과 기존 보호 |
| --- | ---: | --- | --- |
| `apply_provider_feature_field_patch` | 1113 | current source/head SHARE→link SHARE→Feature UPDATE→base/subtypes | `feature_repo._apply_provider_field_values`2548, 통상 provider `upsert_feature`의 Python EX 아래. SQL 직접 CALL은 자체 EX 없음 |
| `author_feature_field_overrides` | 2413 | domain command SHARE→Feature UPDATE→override/subtype | `admin_feature_repo.author_admin_feature_field_overrides`2650/API admin route1979; phone/address wrapper도 사용. 공통 protocol 없음 |
| `author_lifecycle_override` | 2924 | Feature UPDATE→lifecycle override | merge는 Python EX 아래, transition core도 SQL 내부 호출. SQL 직접 CALL은 자체 EX 없음 |
| `approve_feature_request_with_initial_state` | 1723 | command/request UPDATE→옛 write-all SHARE/per-Feature EX→identity claim→create core | `feature_request_repo.approve_feature_request`242/API route278. domain command는 protocol과 다른 잠금 |
| `create_admin_manual_feature_with_initial_state` | 3243 | command UPDATE→manual identity claim→create core→origin | `admin_feature_repo.create_admin_feature_with_field_overrides`2831. 신규 identity 경로, 자체 protocol 없음 |
| `create_feature_with_initial_state` | 4036 | provider이면 source evidence SHARE→Feature INSERT; manual이면 create | provider/manual/approval SQL callee이며 runtime 직접 EXECUTE도 가능한 정본 core. 자체 protocol 없음 |
| `create_provider_feature_with_initial_state` | 4423 | provider identity claim→create core→alias | `feature_repo.upsert_feature`2692는 EX 보호. 직접 SQL 진입은 claim/alias closure 별도 필요 |
| `purge_manual_feature` | 8007 | command SHARE→manual claim UPDATE→Feature UPDATE→동적 FK 증거 읽기/DELETE·cascade | `manual_feature_purge_repo.purge_manual_feature`148. active scalar DELETE guard와 FK cascade/manifest 관계를 함께 검증해야 함 |
| `reactivate_admin_feature_state` | 8269 | **source/head→link SHARE 후 Feature UPDATE**→override/state/audit | `admin_feature_repo.reactivate_admin_feature_state`2457. 자체 protocol은 없지만 source→Feature 순서를 지킨다. 역순이라는 초기 진단은 철회 |
| `revoke_feature_field_overrides` | 10223 | command SHARE→Feature UPDATE→override UPDATE/base SHARE→effective 복원 | `admin_feature_repo.revoke_admin_feature_field_overrides`2701. revision/override masking·동시 projection 검증 필요 |
| `revoke_lifecycle_override` | 10689 | Feature UPDATE→override | runtime SQL 진입, Python 직접 업무 호출은 추출되지 않음. 내부/직접 권한을 구분 |
| `transition_admin_feature_state` | 11356 | Feature UPDATE→admin context의 transition core→audit | `admin_feature_repo.transition_admin_feature_state`2395. admin 분기에서는 source 증거 잠금을 추가하지 않음 |
| `transition_feature_state` | 11437 | provider context이면 source/head→link SHARE 후 Feature UPDATE; 비-provider는 Feature UPDATE | provider lifecycle은 기존 EX 아래, merge도 EX 아래. 직접 SQL/상위 admin callee는 별도 보호 |

### 다음 PR에서 놓치면 안 되는 caller 선점

`feature_repo.set_feature_phones`5751은 5759에서 Feature FOR UPDATE를 먼저 하고 override CALL을 한다. `feature_address_repo.apply_feature_address_override`134도 194에서 Feature FOR UPDATE를 먼저 한다. **callee에 EX 한 줄만 넣으면 이미 Feature를 잠근 Python caller가 뒤늦게 protocol EX를 기다려 새 ABBA를 만들 수 있다.** 향후 EX 보강은 이 caller의 첫 row lock 전부터 적용하거나, row/revision 기반으로 shared와 안전하게 공존함을 실제 PG로 별도 입증해야 한다. 단순 protocol 부재만으로 13개에 일괄 삽입하지 않는다.

## 확인된 M05 역순 — 414의 우선 범위

- `record_manual_provider_dedup_candidate(uuid,uuid,jsonb,jsonb)`(8771), owner `ktm_manual_provider_dedup_procedure_owner`, detector executor만 공개 EXECUTE(26896): m05 advisory → 두 Feature UUID 정렬 FOR UPDATE → link/entity/head/record FOR SHARE.
- private `resolve_manual_provider_dedup_case(uuid,text,text,bigint,bigint,uuid,text,text,bigint)`(9928): m05/case → 두 Feature FOR UPDATE → current source/head/link FOR SHARE. 직접 runtime EXECUTE는 닫혀 있다.
- 공개 `resolve_manual_provider_dedup_case_v2`(10167): subscription/lease SHARE → 위 private CALL. admin executor에만 공개 EXECUTE(27017). `feature_reference_reconciliation_repo.resolve_manual_provider_dedup_case`444/API route831이 사용한다. detector wrapper `manual_provider_dedup_repo.record_manual_provider_candidate`384도 protocol을 추가하지 않는다.

shared S가 provider source/head UPDATE를 갖고 Feature를 기다리고, M05 M이 같은 Feature UPDATE를 가진 후 source/head SHARE를 기다리면 순환이 성립한다. detector는 Feature 유효성/immutable manual origin/현재 primary source 등의 입력이 유효해야 그 지점에 도달한다. **권한/입력 조건을 제거한 가짜 CALL로 재현하면 안 된다.** session_user=정본 runtime, 실제 executor membership·origin·current source/case/revision이 필요하다. 이 보고서는 lock order를 소스로 확인했으며 실제 40P01 관측은 414 담당자의 새 증거를 기다린다.

414 후보는 detector/public v2/private inner 3개를 한 단위로 보아 first entry EX, EX→기존 M05/row 순서·권한 보존·양방향 대기·cancel/rollback 후 회복을 시험하는 작은 PR이다. 이미 별도 담당자에게 위 소스 근거를 전달했다. 이 보고서 작성자는 구현하지 않았다.

### Reactivate 오독 철회

조사 초기에 lock helper 호출을 제외한 FOR UPDATE 행 요약을 보고 Reactivate를 Feature→source로 잘못 전달했다. 실제 본문은 `lock_current_provider_feature_source_evidence`를 먼저 호출한다. helper는 source/head→link SHARE를 취득하므로 해당 ABBA 주장은 철회했고 root/414 담당자에게 즉시 정정했다. Reactivate 제품을 이 오독 때문에 수정하지 않았다. 최종 위험 확정 목록에는 M05만 남긴다.

## 나머지 SECURITY DEFINER·catalog/receipt 계층

다음 41개는 effective Feature writer 13개와 다른 분류다. 기존 feature-write-all/per-Feature/m05/catalog/curation-import 키는 새로운 protocol 키와 **같은 gate가 아니다**. 그러나 catalog/receipt 쓰기 또는 row 잠금만 있다는 이유로 데이터 손상이라고 단정하지도 않는다. 아래/기계 JSON에 caller/callee를 남겼으므로 별도 closure 검증 때 재사용한다.

| auxiliary entry | oracle 행 | 직접 Python wrapper 또는 SQL callee 연결 |
| --- | ---: | --- |
| `feature.ack_feature_reference_reconciliation_event` | 444 | SQL caller: `feature.ack_feature_reference_reconciliation_event_v2` |
| `feature.ack_feature_reference_reconciliation_event_v2` | 568 | `src/kortravelmap/infra/feature_reference_reconciliation_repo.py:287 ack_feature_reference_reconciliation_event` |
| `feature.append_theme_feature_candidate_transition` | 651 | SQL caller: `feature.materialize_theme_candidate_generation`, `feature.promote_theme_feature_candidate`, `feature.reject_theme_feature_candidate` |
| `feature.apply_curation_import_items_command` | 692 | `src/kortravelmap/infra/curation_repo.py:6465 _apply_curation_import_items_command` |
| `feature.archive_curated_source_command` | 1843 | `src/kortravelmap/infra/curated_repo.py:746 archive_curated_source_command` |
| `feature.archive_curated_source_rule_command` | 1951 | `src/kortravelmap/infra/curated_repo.py:925 archive_curated_source_rule_command` |
| `feature.archive_curated_theme_command` | 2048 | `src/kortravelmap/infra/curated_repo.py:573 archive_curated_theme_command` |
| `feature.archive_curation_collection_command` | 2159 | `src/kortravelmap/infra/curation_repo.py:3781 archive_curation_collection_command` |
| `feature.claim_curation_catalog_command_effect` | 3007 | SQL caller: `feature.archive_curated_source_command`, `feature.archive_curated_source_rule_command`, `feature.archive_curated_theme_command`, `feature.archive_curation_collection_command`, `feature.archive_curation_item_command`, `feature.create_curated_source_command`, `feature.create_curated_source_rule_command`, `feature.create_curated_theme_command`, `feature.create_curation_collection_command`, `feature.create_curation_item_command`, `feature.create_manual_curation_item_with_feature_command`, `feature.patch_curated_source_command`, `feature.patch_curated_source_rule_command`, `feature.patch_curated_theme_command`, `feature.patch_curation_collection_command`, `feature.patch_curation_item_command`, `feature.reclassify_curation_quarantine_command` |
| `feature.claim_curation_import_plan_command` | 3037 | `src/kortravelmap/infra/curation_repo.py:6039 claim_curation_import_plan_command` |
| `feature.complete_curation_import_plan_command` | 3168 | `src/kortravelmap/infra/curation_repo.py:6080 complete_curation_import_plan_command` |
| `feature.create_curated_source_command` | 3402 | `src/kortravelmap/infra/curated_repo.py:611 create_curated_source_command` |
| `feature.create_curated_source_rule_command` | 3455 | `src/kortravelmap/infra/curated_repo.py:786 create_curated_source_rule_command` |
| `feature.create_curated_theme_command` | 3550 | `src/kortravelmap/infra/curated_repo.py:452 create_curated_theme_command` |
| `feature.create_curation_collection_command` | 3604 | `src/kortravelmap/infra/curation_repo.py:3634 create_curation_collection_command` |
| `feature.create_curation_import_plan_command` | 3680 | `src/kortravelmap/infra/curation_repo.py:5981 create_curation_import_plan_command` |
| `feature.create_curation_rule_reconcile_receipt` | 3918 | SQL caller: `feature.archive_curated_source_command`, `feature.archive_curated_source_rule_command`, `feature.archive_curated_theme_command`, `feature.create_curated_source_rule_command`, `feature.patch_curated_source_rule_command` |
| `feature.lease_feature_reference_reconciliation_event` | 5350 | SQL caller: `feature.lease_feature_reference_reconciliation_event_v2` |
| `feature.lease_feature_reference_reconciliation_event_v2` | 5449 | `src/kortravelmap/infra/feature_reference_reconciliation_repo.py:204 lease_feature_reference_reconciliation_event` |
| `feature.materialize_theme_candidate_generation` | 5762 | SQL caller: `feature.archive_curated_source_command`, `feature.archive_curated_source_rule_command`, `feature.archive_curated_theme_command`, `feature.create_curated_source_rule_command`, `feature.finalize_provider_curation_root`, `feature.patch_curated_source_rule_command`, `feature.sync_concierge_theme_catalog` |
| `feature.patch_curated_source_command` | 6508 | `src/kortravelmap/infra/curated_repo.py:666 patch_curated_source_command` |
| `feature.patch_curated_source_rule_command` | 6583 | `src/kortravelmap/infra/curated_repo.py:844 patch_curated_source_rule_command` |
| `feature.patch_curated_theme_command` | 6720 | `src/kortravelmap/infra/curated_repo.py:496 patch_curated_theme_command` |
| `feature.patch_curation_collection_command` | 6816 | `src/kortravelmap/infra/curation_repo.py:3694 patch_curation_collection_command` |
| `feature.promote_theme_feature_candidate` | 7355 | `src/kortravelmap/infra/curation_candidate_repo.py:353 promote_theme_candidate` |
| `feature.provision_feature_reference_reconciliation_subscription` | 7913 | `src/kortravelmap/infra/feature_reference_reconciliation_repo.py:328 provision_feature_reference_reconciliation_subscription` |
| `feature.refresh_curated_source_observation` | 9095 | SQL caller: `feature.finalize_provider_curation_root` |
| `feature.reject_feature_request` | 9350 | `src/kortravelmap/infra/feature_request_repo.py:355 reject_feature_request` |
| `feature.reject_theme_feature_candidate` | 9565 | `src/kortravelmap/infra/curation_candidate_repo.py:322 reject_theme_candidate` |
| `feature.resolve_curation_import_collection_command` | 9831 | `src/kortravelmap/infra/curation_repo.py:6107 _resolve_curation_import_collection_command` |
| `feature.seal_provider_curation_snapshot_receipt` | 10735 | `src/kortravelmap/infra/feature_operation_repo.py:672 _seal_authoritative_curation_snapshot` |
| `feature.submit_feature_request` | 10851 | `src/kortravelmap/infra/feature_request_repo.py:129 submit_feature_request` |
| `feature.sync_concierge_theme_catalog` | 10965 | SQL caller: `feature.sync_concierge_catalog_after_observation` |
| `feature.touch_curation_import_collection_command` | 11302 | `src/kortravelmap/infra/curation_repo.py:6175 _touch_curation_import_collection_command` |
| `ops.append_provider_feature_attempt_event_command` | 12124 | `src/kortravelmap/infra/feature_operation_repo.py:823 append_dagster_feature_attempt_event` |
| `ops.ensure_provider_feature_operation_command` | 12720 | `src/kortravelmap/infra/feature_operation_repo.py:531 ensure_dagster_feature_operation` |
| `ops.fill_provider_cancellation_starts_command` | 12917 | SQL caller:  |
| `ops.finish_provider_feature_membership_command` | 12982 | `src/kortravelmap/infra/feature_operation_repo.py:727 finish_dagster_feature_membership` |
| `ops.record_curation_import_manual_feature_child` | 13709 | `src/kortravelmap/infra/curation_repo.py:6372 _record_manual_children_linkage` |
| `ops.transition_provider_cancellation_job_command` | 14633 | SQL caller:  |
| `ops.transition_provider_feature_operation_terminal_command` | 14797 | `src/kortravelmap/infra/feature_operation_repo.py:877 reconcile_dagster_feature_run`; `src/kortravelmap/infra/feature_operation_repo.py:1188 abandon_dagster_feature_run` |

- `promote_theme_feature_candidate`7355는 옛 write-all/per-Feature → catalog/source/head/link SHARE → Feature SHARE → candidate/collection UPDATE 순서다. `materialize_theme_candidate_generation`5762는 옛 write-all EX/catalog → source/head/link/Feature SHARE → candidate 갱신이다. 현재 scalar shared의 source→Feature 순서와 같은 부분은 있지만, catalog/candidate closure를 manifest가 대표한다는 증거는 아직 아니다.
- `merge_lock_curation_collections`6477은 직접 Feature를 쓰지 않고 collection 행을 잠근다. Python `merge_repo.apply_feature_merge`835의 protocol EX 선행을 별도로 확인했다.
- `ops.transition_provider_cancellation_job_command`14633은 cancellation/member/run 행을 잠근 뒤 413의 `finalize_provider_curation_root`를 CALL한다. callee는 EX-first지만 outer routine 전체가 protocol-first라는 뜻은 아니다. shared/native TX가 이 cancellation/job 상태와 함께 잠기는지를 별도 점검해야 하며, 현재 보고서는 새 ABBA로 확정하지 않는다.
- lease/ack/subscription, import/operation/cancellation receipt·event clock는 자체 metadata/receipt writer다. 이를 Feature 실효값 writer와 합산하거나 모든 API를 전역 EX로 묶으면 불필요한 경합을 만들 수 있다.
- `feature.sync_subtype_public_ready`11266은 원래 Feature UPDATE가 가진 부모 row lock 아래 subtype readiness를 갱신하는 trigger다. 별도 공개 writer가 아니다. policy statement barrier/reject/projection deferred guard는 fail-closed 검증 계층이다. trigger가 있다는 사실만으로 모든 전역 잠금 순서·manifest 완전성을 증명하지 않는다.

## 후속 작은 PR의 권장 순서

1. **414 M05 3entry**: 검증된 Feature→source 역순을 EX-first로 격리하고 실제 runtime role·양방향 대기·기존 성공 의미·실패 복구를 증명한다. 현재 별도 담당자가 소유한다.
2. **state/field override 경계**: 위 13개 중 admin state/lifecycle와 field override를 나눠 검증한다. 먼저 direct CALL·caller 선점 여부를 고정한 실제 PG 시험을 만든다. EX fallback 선택 시 phone/address의 첫 Feature lock 전까지 함께 배선한다. 기존 override masking·기대 revision·401/403·rollback 정책을 바꾸지 않는다.
3. **identity create/purge closure**: create core/provider/manual/approval와 purge를 별도 PR로 다룬다. claim/alias/new Feature·FK cascade/삭제 방어 및 inactive/active 정책을 명시한다. 새 scalar용 모델 밖 신규 creation/merge/purge를 shared라고 선언하지 않는다.
4. **catalog/cancellation outer entry**: candidate generation/promote·curation import·취소→finalize 상위 phase와 shared manifest의 경계를 실제 lock graph로 확인한다. SQL callee만 EX가 있다고 outer caller의 선점까지 해결됐다고 표시하지 않는다.

각 단계는 기존 public/private EXECUTE·SECURITY DEFINER owner/search_path와 SQL 성공·재시도 상태를 보존하고, 같은 Feature/서로 다른 Feature·같은 source/여러 source·rollback/cancel·늦은 worker에 대한 실제 PG 반증을 요구한다. 초기 gate를 더한다고 scoped 병행성이 완성되거나 CPU 절감이 측정된 것으로 세지 않는다. 기본 OFF·정책 seed0·mixed binary drain 전 활성 금지와 모든 T 체크박스 미완을 유지한다.

## 증거와 한계

원본 기계 JSON은 전수 235행을 보존하며 signature 전체를 손으로 축약하지 않았다. SQL DML 정규식/AST 호출 연결은 탐색 보조다. overload/간접 동적 SQL/DDL·trigger NEW 대입·SQL planner의 join lock 순서/ORM writer의 완전성을 증명하지 않는다. 핵심 7/13/M05/shared begin 및 source helper의 순서는 본문과 Python caller를 직접 읽었다. 운영 접속·새 PostGIS·새 PR·제품 수정은 0건이다.
