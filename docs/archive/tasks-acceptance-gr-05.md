# tasks-acceptance 아카이브 — `T-GR-05` (완료)

> `T-GR-05`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-23).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-GR-05

ADR-109 결정 5(센서). 수정 파일: `packages/kor-travel-map-dagster/src/kortravelmap/dagster/sensors.py`
(`kor_travel_geo_release_sensor`), `resources.py`(`kor_travel_geo_client_resource` — 센서용 경량 client, T-GR-02에서 이월),
`definitions.py`, `run_scope.py`(필요 시 `dagster/run_key` 조회 헬퍼),
`src/kortravelmap/geocoding.py`(열린 결정 6 승인 시에만 — run 태그 `kor_travel_map.geo_release_plan_id` 보유 run 한정
reverse timeout 1회 재시도 옵션, `trigger_kind=sensor`는 MOIS 이어 달리기 run에도 붙어 판별자가 아니다
`mois_chunked_load.py:1071-1075`; 기각이면 attempt 2로만 복구), `tests/lint/`(효과 테스트·새 pool/limit 태그 없음),
tests. 의존: T-GR-02·04. 규모 M.
열린 결정 3(`default_status`)·6(재시도)·9(완료 전이)·11(기동 방식)에 걸린다 — §T-GR-00 영향 조문 표.

- `address-geocoding.md` §7 "센서" 열의 케이스 전부가 테스트로 있다 — 특히 `data_token` None → 계획 0 + Skip 문구;
  **빈 커서 + 토큰 → 커서에 그 토큰을 기준선으로 기록, 계획 0행·RunRequest 0**(소유자 결정 2026-10-15, ADR-109 결정 5.1 —
  다음 tick에 같은 토큰이면 여전히 0, 다른 토큰이면 계획 1);
  재빌드(토큰 동일) → 계획·RunRequest 0; A→B→A → `plan_seq=2` 계획과 RunRequest ≥ 1; SUCCESS + `budget_exhausted` →
  `done`이 아니라 같은 run_config로 재요청 1건(`converted==0`이면 `failed(no_progress)`); `requested` 3 tick 무run →
  `failed(run_not_launched)`; 활성 `feature_update_request_worker` run → Skip; DISABLED 1개 포함 계획이 sweep 없이 done.
- 효과 테스트: 센서 tick의 외부 효과는 `dataset_version` HTTP 1회 + DB 조회뿐이고 `reverse_geocoder` resource를
  초기화하지 않는다(WARNING 로그 0건); `jobs=` 집합 == `FEATURE_LOAD_SCHEDULE_SPECS` job 집합; 새 pool·limit 태그가
  없다(Manager `dagster.yaml` 변경 0).
- `trigger_kind=sensor` run이 `feature_operation_*` 센서·`map_owned_runs_filter`에서 Map 소유로 집계된다; RunRequest
  태그에 `kor_travel_map.geo_release_plan_id`가 있고 MOIS 이어 달리기 run(`_CONTINUATION_TAGS`)에는 없다;
  `replan` 뒤 RunRequest의 run_key가 유일해 실제 run이 생긴다.
- 격리 스택 e2e: **첫 tick이 기준선을 기록한 뒤**(계획 0) `manual_rebuild` → RunRequest 0건; 소량 delta → 1 tick → 계획 1 → RunRequest 1
  → 커버리지 상승.
- 구현 메모(2026-10-16, 브랜치 `feat/t-gr-05-geo-release-sensor`): (1) 센서는 `dagster/geo_release_sensor.py`다
  (`sensors.py`는 큐 센서 모듈이라 따로 뒀다). **판정은 공용 함수뿐** — 감지·계획은 `client.create_geo_release_plan`
  (#1331 `plan_geo_release`, `/detect`와 같다), 기준선·멱등·끝난 토큰·롤백 정리는 그 함수 몫이라 센서 테스트는 그 결과를
  따르는지만 본다(계획 규칙 자체는 통합 테스트). 커서는 쓰지 않는다 — 기준선은 DB 행이다. (2) **항목 = run 1개**(MCST는
  run 1개·dataset 13개, 상태도 항목 하나). (3) **replay 게이트**: `launch_blocked_reason`이 있는 항목은 내지 않고 Skip
  사유에 `위치:operation=사유`로 남긴다 — 지금은 replay 항목 전부(MOIS·datagokr fileData·standard_data)가 막혀 있어 그
  항목이 남은 계획은 완료되지 않는다(T-GR-08이 `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS`를 채우면 이어진다). (4) **상한**:
  tick 300초, 진행 중 run 1개(`GEO_RELEASE_MAX_IN_FLIGHT`) — geo 의존 job은 전부 `GEO_HEAVY_POOL`(limit 1)이라 어차피
  직렬이고, 여러 개를 내면 pool 줄만 길어진다. 새 pool·limit 태그 없음. 기본 STOPPED(소유자 지시). (5) **완료**:
  `complete_geo_release_plan(…, sigungu_resolver=)` — resolver는 그 tick의 geo client(`resolve_sigungu_by_radius`)다.
  sensor resource는 DB client 하나뿐이고(`reverse_geocoder` resource를 초기화하지 않는다) geo HTTP는 tick 안에서 연
  짧은 client로 `dataset/version` 1회(완료 tick에만 sigungu 조회). (6) 전이: SUCCESS → done; MOIS `budget_exhausted`면
  `mois_load_continuation_decision`(단일 정본)이 이어 달리라고 하면 다음 `attempt_seq`로 되돌리고(상한 12) 아니면
  `failed(no_progress)`; 비-MOIS 실패는 1회 자동 재요청 뒤 `failed(run_failed)`; `requested` 900초(3 tick) 무run →
  `failed(run_not_launched)`. run 조회 키는 RunRequest에 단 `kor_travel_map.geo_release_run_key`(`map_owned_runs_filter`),
  run_key = `geo_release/{token}/{plan_seq}/{operation}/{position}/{attempt}` — replan은 `plan_seq`가 달라 유일하다.
  (7) 범위 밖으로 남긴 것: PinVi에 링크 변경을 알리는 stream 이벤트(메모만), 열린 결정 6(geo-release run 한정 timeout
  재시도 — 미승인이라 attempt 2로만 복구), 격리 스택 e2e(배포 뒤).
- 구현 메모 2(2026-10-16, #1332 적대 리뷰 2인 반영): (8) **MOIS 이중 이어 달리기 차단** — `mois_load_continuation_sensor`는
  마지막 run에 `kor_travel_map.geo_release_plan_id`(상수는 `run_scope.GEO_RELEASE_PLAN_ID_TAG`)가 있으면 Skip한다(ADR-109
  5.5 문장 정정). 지금은 MOIS가 replay 게이트에 막혀 잠복이지만 T-GR-08부터 실제로 난다. (9) **supersede 고아 정리** — 계획이
  닫힐 때 그 계획의 `requested` 항목은 `failed(superseded)`; **CANCELED는 재요청 없이 `failed(canceled)`**. 두 사유를
  어휘에 더하느라 **migration 409**(`409_geo_release_item_reasons` — 408은 배포 경로에 있어 고치지 않았다)와 admin
  OpenAPI의 `state_reason` enum이 바뀐다(**PinVi 재vendor 필요**). (10) **geo client 생성은 `geocoding.open_geo_client(settings)`
  하나** — 운영 API와 센서가 쓴다. acceptance 머리의 `kor_travel_geo_client_resource`(센서용 경량 resource) 대신 이
  helper다(소유자 위임 결정 — resource를 두면 센서가 tick마다 쓰지 않을 client를 초기화하고, helper는 tick 안에서만 산다).
  (11) **replay가 막힌 계획은 T-GR-08 전까지 `running`으로 둔다**(소유자 위임 결정 — skip으로 바꾸지 않는다). 센서를 켜도
  replay 항목(MOIS·datagokr fileData·standard_data)이 든 계획의 완료를 기대하지 말 것. (12) 운영 메모: `attempt_seq`는 단조라
  sweep 뒤에도 재요청 상한(비-MOIS 2, MOIS 12)이 누적된다; `failed(run_not_launched)`·`failed(canceled)`는 최종 상태다(센서가
  다시 내지 않는다 — 운영자 `replan`).
