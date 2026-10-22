# tasks-acceptance 아카이브 — `T-GR-04` (완료)

> `T-GR-04`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-22).
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

## T-GR-04

ADR-109 결정 5(계획 표·항목·완료 단계)·8(admin API). 수정 파일: `alembic/versions/408_kor_travel_geo_releases.py`,
`alembic/head-schema.sql`, `infra/models.py`, `infra/geo_release_repo.py`(신규 — `plan_geo_release`·
`run_config_for_dataset`·항목 전이·`coverage` 호출·`complete_plan`), `infra/feature_geocode_stamp_repo.py`(`coverage()`
신규 — T-GR-01에서 이월; `select_stale_feature_ids(after=)` 호출자를 geo 의존 dataset으로 한정),
`src/kortravelmap/core/feature_operation.py`
(`GEO_DEPENDENT_OPERATION_KEYS` — `DEDICATED_JOB_ONLY_OPERATION_KEYS` :33-41 옆, 런타임 정본),
`tests/lint/test_geo_heavy_assets_declare_the_pool.py`(AST 유도 집합 == 상수 단언 추가 — pool 술어 `_passes_reverse_geocoder`
:81-87은 **불변**(pool 필요 집합 ≠ geo 의존 집합, 과결박 회피); 별도 ① `_passes_geo_callable`(`reverse_geocoder=` 또는
`address_resolver=`에 `None` 상수가 아닌 값 — 현재 술어는 키워드 존재만 봐 `assets.py:643`의 `=None`도 센다)
② asset → `FEATURE_LOAD_SCHEDULE_SPECS.job_name` 매핑(현재 `_geo_heavy_assets()` :101-132는 asset 이름만)
③ 모듈 간 참조 허용 또는 그 한계 단언(현재는 같은 모듈만 잇는다)), `src/kortravelmap/client/__init__.py`(래퍼),
`packages/kor-travel-map-api/src/kortravelmap/api/routers/ops_geo_releases.py`(신규), `api/app.py`(mount, admin
프로필), `packages/kor-travel-map-api/openapi.json`(`scripts/export_openapi.py --profile all`), tests. 의존: T-GR-01.
규모 M. **배포 제약**: 머지 뒤 PinVi admin 스냅샷 재vendor(`apps/api/tests/unit/_kor_travel_map_snapshot_pin.py`
`UPSTREAM_COMMIT`·`SNAPSHOT_SHA256` + `test_kor_travel_map_admin_contract.py` 이중 핀 + `scripts/generate_m05_pair_contract.py`
재실행)가 Map API 배포보다 먼저다(memory `map-admin-openapi-change-needs-pinvi-revendor`).

- `plan_geo_release` 멱등: 같은 토큰·활성 계획으로 두 번 호출 → 행 1개. A→B→A → 두 번째 A에서 `plan_seq=2` 새 행.
  최신 계획 terminal + `coverage(비-skipped).stamped_other + unstamped == 0` → None.
- 항목 생성: `provider_dataset_operations(feature_load, is_enabled) ⋈ is_active` 입력에서 geo 의존은
  `GEO_DEPENDENT_OPERATION_KEYS`로 판정(센서·`/detect` 둘 다 — API 프로세스는 `kortravelmap.dagster`를 import하지
  않는다; lint가 AST 유도 집합과의 동등을 단언하고, 상수에서 하나를 빼면 빨갛다; `assets.py:643`을
  `_reverse_geocoder(context)`로 바꾸면 동등 단언이 빨갛다), **KNPS 5 dataset이 항목 5개가 되고 run_config가 dataset마다
  다르다**, `DISABLED_FEATURE_LOAD_OPERATION_KEYS` → `skipped(disabled)`, 쿼터 민감 → replay run_config, 순서
  ①~⑤(concierge·MOIS 마지막).
- `coverage` 응답에 `excluded_by_skip`·`not_called_by_kind`·`unstamped_non_provider`가 있고 분모가 인자 dataset으로
  한정된다.
- 마이그레이션 lint 4종 초록(408도 owner role·receipt CHECK·RESET ROLE 없음).
- `openapi.user.json`·`openapi.service.json`이 byte 불변이다(테스트가 export 전후 sha256 비교); `openapi.json`에
  `/v1/ops/geo-releases` 5 operation(슬래시 동사)이 있고 `require_ops_operator`가 붙는다.
- `POST /detect`가 센서와 같은 `plan_geo_release`를 호출한다(단일 정본 테스트 — 함수 identity).
- 완료 단계가 활성 cache target 전부에 `sync_poi_cache_target_feature_links`를 1회 호출하고, `sigungu_code`가 바뀐
  feature 1건의 `same_sigungu` 링크가 새 target으로 옮겨진다. prod 활성 target 수를 PR 본문에 기록한다(가정 검증).
- 구현 메모(2026-10-16, 브랜치 `feat/t-gr-04-geo-release-plan`): (1) **기준선은 DB 행이다** — 처음 관측한 토큰은
  `state='baseline'` 행 1개로 남고 항목이 없다(소유자 결정 2026-10-15). 센서 커서가 없는 `/detect`도 같은 판단을 해야
  해서 상태값 `baseline`을 더했다(설계 표는 4상태). 판정 순서는 `plan_geo_release` docstring(no_token → existing →
  첫 관측=baseline_recorded → 기준선 유지=baseline → 끝났고 잔여 0=already_complete → created). 기준선 행이 **최신 행**일
  때만 "계획 없음"이다 — A→B→A의 두 번째 A는 기준선이 있어도 잔여가 있으면 `plan_seq=2`다. (2) **항목 입력의 kind는
  `refresh`다** — DB에 `feature_load` kind 행이 0건이고 operation key(= job)를 dataset에 결박하는 kind가 `refresh`다(ADR-109
  결정 5.3 표기와 다르다). (3) API 프로세스가 `kortravelmap.dagster`를 import하지 않으므로 계획이 읽는 job 사실을 core에
  둔다 — `FEATURE_LOAD_JOB_OPERATION_KEYS`(job 없는 operation → `skipped(queue_only)`), `GEO_DEPENDENT_OPERATION_KEYS`,
  `FEATURE_LOAD_DISABLED_OPERATION_KEYS`(→ `skipped(disabled)`), `DATASET_CONFIGURED_OPERATION_RESOURCES`(KNPS·datagokr
  fileData의 dataset run_config), `REPLAY_RECORDS_RESOURCES`. 각 값이 Dagster 정의와 같다는 것은 lint
  (`test_geo_heavy_assets_declare_the_pool.py`)가 고정한다 — geo 의존은 AST 유도(None 상수 제외·모듈 횡단·전이·데코레이터
  제외)와의 집합 동등, 나머지는 schedule spec과의 동등. Dagster `DISABLED_FEATURE_LOAD_OPERATION_KEYS`는 그대로 두었다
  (`test_c7_prod_live_runner_contract`가 그 소스 줄을 읽는다). (4) **replay run_config는 T-GR-08 전에는 실행 불가** — records
  resource에 `source_mode`가 아직 없어 Dagster config 검증이 거부한다. T-GR-05 센서는 replay 항목(순서 ④·⑤)을 T-GR-08
  뒤에만 내야 한다. (5) **MCST는 job 하나에 dataset 13개**인데 dataset run_config가 없다 — 항목은 dataset마다 13개지만 run은
  operation 하나로 충분하다. T-GR-05는 같은 `(operation_key, run_config)` 항목을 한 run으로 묶어 낸다(run_key 설계도 그때).
  (6) 항목 UNIQUE는 `(plan_id, operation_key, provider_dataset_id)` — `attempt_seq`는 같은 행에서 단조 증가(재요청·sweep)라
  UNIQUE에 넣지 않았다(설계 표와 다르다). 완료의 "1회 sweep"은 계획의 `sweep_started_at`으로 한 번만 한다(열 추가).
  (7) `coverage()`의 네 칸은 분할이다 — `stamped_current`(현재 토큰 `called|geocoded`) + `stamped_other`(다른 토큰 =
  stale) + `not_called`(토큰 무관, `not_called_by_kind` 합) + `unstamped`. 완료 잔여 = `stamped_other + unstamped`.
  `unstamped_non_provider`는 primary source_link가 없는 좌표 보유 활성 Feature 중 스탬프 없는 것. (8) 링크 재동기화는
  활성 target(삭제 안 됨·update_enabled·refresh_policy≠disabled)을 external_system별로 `resolve_cache_target_keys` →
  `sync_poi_cache_target_feature_links`. `sigungu_by_radius` target이 있으면 geo `sigungu_resolver`가 필요하다(센서가 넘긴다).
  PinVi에 링크 변경을 알리는 stream 이벤트는 큐 executor처럼 request 단위로 남기지 않는다 — prod 활성 target이 0개라
  (2026-10-16 실측: 전체 4·살아 있는 것 0) 지금은 영향이 없고, target이 생기면 T-GR-05에서 다시 본다. (9) `DatasetRef`에
  관측용 `activated_at`·`reference_months`를 선택 필드로 더했다(`dataset_version()`의 `current`에서만 — 형식이 틀리면 버리고
  토큰 판정은 그대로). (10) admin OpenAPI만 바뀌었다(5 operation·스키마 10개 추가, 기존 경로·스키마 불변, user·service
  sha256 불변) — **PinVi admin 스냅샷 재vendor가 Map API 배포보다 먼저**다.
- 구현 메모 2(2026-10-16, #1331 적대 리뷰 2인 반영 — 미배포라 408 안에서 바꿨다): (11) **항목 모양 = run 단위**
  (소유자 위임 결정): 1행 = `(operation_key, run_config)` + `provider_dataset_ids bigint[]`. 위 (5)의 "MCST 13 항목을
  run 하나로 묶기"는 이것으로 해소됐다(MCST 항목 1개·dataset 13). 배열이라 dataset FK가 없다 — dataset은 지우지 않고
  비활성화만 한다(408 docstring). UNIQUE는 `(plan_id, operation_key, provider_dataset_ids)`. (12) `attempt_seq`는 UNIQUE
  밖 그대로(결정 — 시도 이력은 Dagster tag). (13) **완료 후 무한 재계획 차단**: 계획 표 전체의 최신 행이 이 토큰의
  `done`이면 잔여가 남았어도 `already_complete`(테스트: 잔여 1을 남기고 끝난 뒤 detect → 새 계획 0). (14) **롤백 전
  계획 정리**: 잔여 0으로 `already_complete`를 낼 때 다른 토큰의 활성 계획을 먼저 `superseded`(테스트: A→B→A, 재스탬프
  없음). (15) `replan`은 최신 관측 토큰의 기준선 아닌 계획만 — 그 외 409, 없음만 404(`GeoReleaseNotFound`).
  (16) `complete_plan(…, sigungu_resolver=)`는 필수 인자이고, 활성 `sigungu_by_radius` target이 있는데 None이면 쓰기
  전에 `GeoReleaseResolverRequired`(전에는 링크 재동기화 도중 실패해 transaction 전체가 되돌아갔다). 링크 테스트에
  `center_radius` target(within_radius 링크 유지)을 더했다. (17) **replay 게이트는 코드다** — core
  `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS`(지금 빈 집합, T-GR-08이 채움); 항목·API에 `launch_blocked_reason =
  replay_not_launchable_before_t_gr_08`. 위 (4)는 이것으로 대체된다. (18) API `state`·`state_reason`은 `Literal`이고
  `state_reason`은 408 CHECK 어휘(disabled·no_geo_dependency·queue_only·operator·sweep·run_not_launched·no_progress·
  run_failed)다. (19) lint docstring에 한계(이름 매칭·최상위 모듈만·replay resource 부분집합)를 적었다.
