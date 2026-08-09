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
2. `feature.feature_state_transitions`는 Feature FK cascade 없이 business identifier를 보존하는
   append-only 감사 정본이다. runtime은 base Feature INSERT/axis UPDATE 권한을 갖지 않으며
   dedicated NOLOGIN owner의 `create_feature_with_initial_state`/`transition_feature_state`
   security-definer procedure만 실행한다. audit writer trigger도 별도 NOLOGIN owner의
   security-definer function으로, fixed `search_path`와 schema-qualified dependency를 사용한다.
   이 경계가 한 명령의 여러 축 변경을 하나의 이전/이후 full tuple row로 기록한다. procedure는
   role별 structured context를 검증하고 provider principal은 dataset에서 파생한다. admin/user
   principal은 application-authenticated 값임을 명시한다. state procedure는 DML 직전에
   allow-listed `state_procedure_definer`를 `SET LOCAL`하고 audit trigger가 이를 검증한다. audit에는
   invoker `session_user`, context의 state procedure definer, audit trigger의 실제 `current_user`
   (audit writer definer)를 각각 기록하며, runtime에 audit INSERT/UPDATE/DELETE/TRUNCATE 또는
   writer-function direct EXECUTE 권한을 주지 않는다.
3. public은 `(active,published,valid)` 단 하나이며 모든 public reader는 명시 열
   `feature.public_features` view를 사용한다. public DTO는 운영 축을 노출하지 않고 admin DTO/API는
   세 축과 audit timeline을 독립적으로 노출한다. admin state command는 If-Match와 reason을
   요구하는 단일 atomic PATCH이고, 기존 deactivate endpoint는 retire action으로 대체한다.
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
