# Airport 원 관측의 SDK0 후처리 intent

## 소유 범위와 단계

Root integration `697160d1019d0491dff3782d00c17feebc73ad71`의 별도 worktree에서 신규
Dagster `airport_snapshot_postprocess.py`, 그 unit, 이 보고서만 추가한다. 기존 codec,
assets.py/etl.py/client/SQL/migration/control/권한·공통 문서는 수정하지 않는다.
신규 파일이고 기존 심볼·signature가 그대로이므로 Codegraph 영향도 생략 조건에 해당한다.
독립 PR/배포·collector 연결은 하지 않으며 전체430 수용 단위에 합성한다.

공유 코드에서 재사용하는 것은 실제 finding 변환과 두 기존 codec, 결과/receipt DTO다.
load 함수, provider SDK/Geo HTTP, DB·환경·파일 조회, 새 시계 생성은 이 adapter에 없다.
Root의 실제 단일 backend transaction과 공개 assets 연결은 아직 미완이다.

## 입력·결과를 다시 만드는 경계

`prepare_airport_snapshot_postprocess`는 명시 canonical root/source/member UUID와
`ProviderDatasetOperationMembership`, 저장된 artifact/context/result bytes 및 expected
pins/root run을 받는다. 기존 observation/result decoder로 원 RestoredAirportObservation와
SnapshotApplyResult를 재생성한다. 원 bundle count와 source_observations가 같아야 하며
기존 1MiB/8KiB/4KiB·2730/깊이 한도를 늘리지 않는다. dataset ID는 양의 PG bigint,
첫 scope는 dataset_wide, operation은 exact str·UTF8 최대256B다.

원 validation 전체 issue를 `_address_validation_findings`로 변환하고 source identity,
linked Feature 및 dropped=False를 유지한다. 같은 dedupe key의 마지막 항목과 정렬 규칙은
기존 client와 같다. 전체 고정 finding 필드와 payload를 정렬된 projection으로 묶어
`airport-postprocess-findings-v1` hash를 만든다. 임의 object serializer를 호출하지 않는다.

cursor는 기존 assets의 정확한 여섯 원 load counter와 원 fetched_at의 loaded_at,
고정 feature_place_transport_airports asset key다. apply14·retired, validation, GeoStats의
원 값·None/빈 값은 재계산하지 않는다. 원 observation_generation을 재시작 retry 번호로
바꾸지 않는다. DB의 last_success_at/last_seen_at 등 처리시각과 원 fetched_at는 다른 축이다.
후처리 완료 반환에도 같은 원 값의 독립 복원본을 사용한다.

## 후보 receipt와 단일 완료 경계

pure prepare의 `receipt_candidate`는 아직 완료 증명이 아니다. JSON exact20키는 version,
domain, root_job_id, source_job_id, import_job_dataset_id, root_run_id, artifact_sha256,
context_sha256, result_sha256, provider_dataset_id, sync_scope, operation_key,
observation_generation, fetched_at, source_observations, findings_observed, findings_unique,
findings_set_sha256, sync_recorded, stale_close_completed다. version1/domain은
`airport-snapshot-postprocess-v1`, 마지막 두 값은 완료 시 기대하는 True다. 전체 canonical
ASCII bytes는4096B 이하다. affected stale-close 수는 재시도 때 달라질 수 있어 stable
receipt에 넣지 않는다. pins/더 풍부한 clock 표현은 원 context/artifact SHA에 결박된다.

`complete_airport_snapshot_postprocess`는 immutable bytes에서 canonical intent를 새로
복원하고 coordinator의 `complete_provider_snapshot_postprocess(intent)`를 정확히 한 번
호출한다. callback이 같은 canonical receipt bytes를 실제 성공 반환해야만 Completion을
만든다. None/다른 bytes/예외·CancelledError는 완료로 바꾸지 않는다. caller가 변경한
nested DTO/Stats/cursor/finding은 backend에 보내지 않고, 완료 반환값도 backend에 넘긴
mutable 값과 alias를 공유하지 않는다. caller는 await 동안 원 intent를 독점 소유한다.

coordinator는 Root가 snapshot/실행 fence에 결박해 구현하는 backend 계약이다. 같은
caller TX에서 fence/latest 검증→finding upsert→sync 성공→stale close→typed mark와
commit을 완료해야 한다. 기존 세 client 메서드를 세 transaction으로 이어 붙이면 안 된다.
기존 sync SQL은 cursor를 무조건 덮고, finding 재upsert는 occurrence_count를 증가시키므로
그 방식은 오래된 worker의 cursor 회귀와 중복 부수효과를 막지 못한다.

Root는 apply TX에서 원 generation의 실제 integrity observation 세대를 source DML 전에
예약하고 facts/result와 함께 commit해야 한다. 더 최신 applied 세대가 있으면 부수효과
전에 superseded 비재시도 오류로 중단해야 한다. 이미 postprocessed이면 stored receipt만
반환하고 upsert/sync/close는0회다. 이 adapter는 그 오류를 전파하며 영구 retry나 새 성공을
만들지 않는다. 단일 TX·DB 최신성·정확히 한 번의 부수효과는 Protocol/순수 모형만으로
입증하지 않으며 실제 backend와 실패 주입 검증이 남았다.

## 실제 순수 결과

신규34 unit가12.25초에 PASS했고, 후속 실제 asyncio Task.cancel 전파1개가4.15초에
PASS했다(34 deselected). 총35개 distinct이며 단일 최종35 실행이라고 합산하지 않는다.
실제 public Airport→기존 converter의 synthetic15×Geo 유무/경고 여부를 사용했다.
무Geo/정상Geo의 receipt 후보는903B, 실제 warning15/issue15의 후보는905B였다.
운영 공항15의 fit/후처리 실행 증거로 확대하지 않는다.

원 clock/generation/14counter/retired/GeoStats, hash의 전체 payload·정렬, alias 분리,
각 backend 단계 예외·취소/부분실패 전파, 단일 callback, 잘못된 완료 proof와 candidate
변조, 모형의 이미 완료 fastpath, superseded 오류 무재시도를 확인했다. 모형의 stage와
rollback은 실제 PG transaction이나 physical pool cleanup의 증거가 아니다.

첫 실행29 PASS/2 FAIL은 None에도 비동일 alias를 요구한 시험 오류였다. 원 로그/XML을
보존하고 None 보존과 가변 Stats의 alias 분리를 구분해 고쳤다. 초기 Ruff의 import/raises
형식도 own 파일에서 수정했다. 최종 Ruff2파일과 strict mypy1파일은 통과했다.
두 독립 source review, Root backend hook/typed mark, 전체 same-TX PG·SDK0 실제 재개,
collector 두 worker/전체 CI·운영 수용은 아직 미완이다. PG/운영 변경은0이다.
