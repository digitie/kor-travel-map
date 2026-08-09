# ADR-090: Feature 직교 상태의 final cutover와 DB 전이 감사

- **상태**: accepted
- **날짜**: 2026-08-09
- **결정자**: 사용자 + Codex
- **관련**: ADR-067, ADR-074, ADR-075, T-VN-34

## 컨텍스트

ADR-067은 lifecycle/publication/quality 3축과 단일 공개 projection을 정했지만, 현행
`status`, `deleted_at`, `user_deleted_at`에는 provider retire, 운영자 deactivate, user delete,
merge tombstone이 섞여 있다. 애플리케이션만 audit event를 쓰면 raw SQL writer·migration·fixture가
우회하고, old/new status를 함께 유지하는 dual-write는 공개·재활성화·override 정본을 다시 둘로
나눈다.

서비스 전 단계라 intermediate DB와 old API binary의 호환성·rollback을 보전할 이유가 없다.

## 결정

1. Feature 상태는 `lifecycle_state(active|retired)`,
   `publication_state(draft|published|suppressed)`,
   `quality_state(valid|quarantined)`만 사용한다. `retired`는 반드시 `suppressed`이고,
   `published + quarantined`는 허용한다. 따라서 active의 여섯 tuple과 retired/suppressed의
   두 tuple만 유효하다.
2. `feature.feature_state_transitions`는 Feature FK cascade 없이 현행 TEXT business identifier와
   UUID identity를 함께 보존하는 append-only 감사 정본이다. runtime은 base Feature INSERT/axis UPDATE 권한을 갖지 않으며
   dedicated NOLOGIN owner의 `create_feature_with_initial_state`/`transition_feature_state`
   security-definer procedure만 실행한다. user add/update/delete의 legacy provenance와 immutable
   version snapshot은 별도 typed `materialize_user_feature_change_provenance` procedure가 request,
   Feature, expected revision을 잠근 뒤 원자적으로 기록하므로 runtime은 `feature_versions`의 직접 DML
   권한을 갖지 않는다. 다만 0095/0096 current schema에서 `feature.features_detailed`는 subtype detail을
   조립하는 private read bridge이므로 `feature_repo` non-public detail, admin detail 및 curated detail
   reader에 한해 runtime `SELECT`를 closed allowlist로 준다. 이는 public 권한이 아니며 final target에는
   이 view가 없다. T-VN-34C는 해당 reader를 final typed projection으로 재배선하고 같은 migration에서
   `features_detailed` grant·ACL allowlist·runtime preflight 요구를 제거한다. 이 procedure는 0095 현행
   schema 전환 bridge로만 남기며 final target에는 두지 않는다. T-VN-36의 field-override effective projection/lineage가
   이를 대체한 뒤 legacy request/version relation을 제거한다. 같은 0095 bridge에서 provider version은
   caller payload가 아닌 잠긴 Feature와 canonical detailed projection으로 조립하는
   `materialize_provider_feature_version` procedure만 기록한다. user whole-row fence가 provider
   core/subtype 변경을 막은 refresh는 user effective row를 provider `version=0` baseline으로
   덮지 않고 immutable raw source observation만 최신화한다. T-VN-36의 final effective
   projection/lineage가 두 version bridge를 함께 대체한다. lifecycle override는 generic
   `ops.feature_overrides` DML을 닫고 expected revision/Feature lock을 요구하는 typed author/revoke
   command만 변경한다. audit writer trigger도 별도 NOLOGIN owner의
   security-definer function으로, fixed `search_path`와 schema-qualified dependency를 사용한다.
   이 경계가 한 명령의 여러 축 변경을 하나의 이전/이후 full tuple row로 기록한다. procedure는
   role별 structured context를 검증하고 provider principal은 dataset에서 파생한다. provider receipt는
   caller가 주입하지 않고 검증된 `source_records.raw_payload_hash`에서 파생하며 target Feature의
   source link와 `source_entity_heads`의 current observation까지 같은 lock 범위에서 확인한다. admin/user
   principal은 application-authenticated 값임을 명시한다. state procedure는 DML 직전에
   allow-listed `state_procedure_definer`를 `SET LOCAL`하고 audit trigger가 이를 검증한다. audit에는
   invoker `session_user`, context의 state procedure definer, audit trigger의 실제 `current_user`
   (audit writer definer)를 각각 기록하며, runtime에 audit INSERT/UPDATE/DELETE/TRUNCATE 또는
   writer-function direct EXECUTE 권한을 주지 않는다.
   이 privilege boundary는 bootstrap owner로 접속한 service에는 적용되지 않으므로,
   `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN`, `KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN`,
   `KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN`의 schema/migrator·API/Dagster runtime LOGIN role을
   분리한다. runtime login은 superuser/CREATEROLE/BYPASSRLS와 schema-owner membership을 갖지 않고
   INHERIT·SET FALSE group 권한만 받으며, startup이 procedure-only privilege를 실제 세션으로 preflight한다.
   runtime에는 state/audit/version/legacy provenance/generic override 직접 DML을 grant하지 않으며,
   API와 Dagster login의 실제 provider bundle 적재와 admin command로 이를 검증한다.
   0095의 transitional procedure는 TEXT key를 받고 T-VN-39 final target procedure는 audit에 보존한 UUID key를
   받는다. audit의 두 identity가 hard purge 뒤에도 이 final conversion 근거를 보존한다.
3. public은 `(active,published,valid)` 단 하나이며 모든 public reader는 명시 열
   `feature.public_features` view를 사용한다. public DTO는 운영 축을 노출하지 않고 admin DTO/API는
   세 축과 audit timeline을 독립적으로 노출한다. admin state command는 If-Match와 reason을
   요구하는 단일 atomic PATCH이고, 기존 deactivate endpoint는 retire action으로 대체한다. geometry가
   route/area geometry가 subtype table에 분리돼 core predicate를 직접 partial GiST로 만들 수 없으므로,
   그 두 subtype에만 core tuple trigger가 갱신하는 `public_ready` projection flag를 둔다. 새 subtype
   attach만 Feature row를 `FOR UPDATE`로 잠가 current tuple에서 flag를 산출한다. 이미 연결된 subtype은
   `feature_id`/identity를 DB에서 immutable로 막고 payload·geometry update는 cache를 보존하며, core
   axis trigger만 existing cache를 바꾼다. 그러므로 route/area UPDATE가 parent lock을 기다리고 state
   transition이 subtype lock을 기다리는 역순 tuple cycle(`40P01`)이 구조적으로 사라진다.
   `WHERE public_ready` GiST는 performance cache일 뿐 state 정본이 아니며 public query는 core/view를
   최종 visibility fence로 유지한다. core point와 text/category/keyset index는 3축 partial predicate를
   직접 사용한다. route/area runtime grant는 allowed business column의 column-list만 부여하고
   `public_ready` table/column UPDATE를 모두 거부한다. core/view/flag 양방향 invariant는 cache
   동등성의 regression proof다.
4. legacy `status`와 soft-delete/user-change core metadata는 T-VN-34C의 한 final migration에서
   모든 reader/writer/API/UI/OpenAPI/PinVi/live fixture를 전환한 뒤 물리 삭제한다.
   `data_origin`/`data_version`/whole-row freeze는 T-VN-36의 field-override materialization 입력이므로
   T-VN-36C가 대체 정본을 검증한 뒤 삭제한다. dual-write, shadow column, legacy trigger, old-binary
   rollback은 만들지 않는다.

## 근거

세 축은 공개 의도, 생명 주기, 품질 실패를 독립적으로 표현한다. DB trigger audit은 모든 writer를
같은 증거 경계에 묶고, security-definer procedure와 typed lifecycle override는 provider 재등장이
운영자 retire를 덮는 경쟁을 제거한다.

## 결과

- **긍정**: public predicate·인덱스·service batch·admin 조작이 하나의 tuple 정본을 공유한다.
  상태 전이의 application principal·DB session identity·reason/revision이 모든 write 경로에서 남고,
  purge 뒤에도 audit가 보존된다.
- **부정**: T-VN-34A/B draft는 단독 배포할 수 없고, final migration은 API/UI/Dagster/PinVi를 함께
  재생성·검증해야 한다.
- **후속**: T-VN-34A/B/C는 stack에서 준비하고, C exact head를 fresh rebuild·ETL·n150 isolated
  live E2E로 증명한다.

## 기존 결정과의 관계

ADR-067의 3축과 단일 공개 projection은 유지한다. 다만 그 문서의 shadow 보존 rollback 경로는
본 ADR의 forward-only final cutover로 대체한다. ADR-075의 보존 우선 규율도 이 task의
서비스 전 destructive rebuild 범위에서는 적용하지 않는다.
