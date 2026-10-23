# tasks-acceptance 아카이브 — `T-GR-01` (완료)

> `T-GR-01`의 해제 조건 원문이다. 절은 닫혔고, live 문서
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

## T-GR-01

ADR-109 결정 1·2. 수정 파일: `alembic/versions/407_feature_geocode_stamps.py`(직전 head `406_feature_write_gate`, ADR-111),
`alembic/head-schema.sql`, `src/kortravelmap/dto/geo_dataset.py`(신규 `DatasetRef`·`GeoApplied`),
`infra/models.py`(`FeatureGeocodeStampRow`), `infra/feature_geocode_stamp_repo.py`(신규), `src/kortravelmap/geocoding.py`
(`dataset_version()`, `_RestReverseV2Response.dataset` :935, `GeoCallStats.observed_data_tokens`·`empty[endpoint]`
:1112·`ObservedReverseGeocoder` 기록 :1405), tests. 의존: T-GR-00-LEDGER(원장 분리; 코드 의존 없음 — geo ADR-069 배포와
병렬 가능, `dataset` 없는 응답 허용; 열린 결정 비의존). 규모 S. timeout 재시도 옵션(열린 결정 6)은 T-GR-05로 옮겼다.

- `alembic/head-schema.sql` 재생성이 byte 일치하고 마이그레이션 lint 4종(`test_migrations_keep_the_schema_owner_role`·
  `test_routine_ddl_runs_under_its_owner_role`·`test_receipt_head_check_covers_the_graph_head`·
  `test_migration_revision_ids_fit_the_version_column`)이 초록이다 — 407은 `SET ROLE ktm_feature_schema_owner` 아래
  DDL·`OWNER TO`·RESET ROLE 없음·receipt head CHECK에 자기 revision.
- 스탬프 삽입: 어느 outcome이든 `geo_version_token`/`geo_data_token` NULL은 NOT NULL이 거부한다(NULL 스탬프는
  만들지 않는다 — ADR-109 결정 1).
- `dataset` 필드가 없는 옛 응답 픽스처 → `None`, 있는 픽스처 → `DatasetRef`; `dataset_version()`은
  `POST /v2/dataset/version` 본문 `{}`를 보낸다(효과 테스트).
- `GeoCallStats.empty['reverse']`: 200 응답에 `bjd_code` None인 reverse 2건·정상 3건·전송 실패 1건 픽스처 →
  `calls=6, failures=1, empty=2`(빈 답은 `failures`에 들지 않는다).
- `is_stale`/`select_stale_feature_ids` 5분기(스탬프 없음·`not_called`·`geocoded` 다른 토큰·다른 토큰·같은 토큰)와
  "현재 토큰 None → stale 0건"이 통합 테스트로 고정된다. `decide_outcome`은 `address-geocoding.md` §2 판정 표 전 행.
- `lint-imports` 초록(`DatasetRef`·`GeoApplied`를 `infra`가 import해도 `infra → geocoding` 역행 없음).
- 이 task에서 provider 모듈·`Address`·`ReverseGeocoder` diff 0.
- 구현 메모(2026-10-15, 브랜치 `feat/t-gr-01-geocode-stamps`): 설계 §2의 시그니처와 다르게 쓴 것 — (1) `decide_outcome(
  geo_applied, *, has_coord, provider_code_present, legal_dong_code_present, evidence)`: 판정 표 ④의 "법정동코드가 생겼다"를
  입력으로 받아야 해서 `legal_dong_code_present`를 더했고, MOIS evidence는 `AdminEvidence`를 바꾸지 않으려고 `dto/geo_dataset.py`의
  `GeoAttemptEvidence{reverse_attempted, geocode_obtained_code}`로 받는다(T-GR-03이 `AdminEvidence`와 geocode 분기
  결과에서 만든다 — '받았다'가 '시도했다'를 함의하므로 `geocode_attempted`는 판정에 필요 없어 두지 않는다). (2) `upsert_stamps(session, *, current, outcomes)`:
  run 토큰을 인자로 받아 None·`data_token` None이면 0건(쓰지도 덮지도 않음)을 함수가 강제한다. (3) `coverage()`는
  `excluded_by_skip`이 408의 계획 표에 기대므로 T-GR-04로 미룬다. (3b) `select_stale_feature_ids`에 keyset 커서 `after`(`feature_id > after`)를 더했다(T-GR-04 페이지용). (4) 토큰 형식 CHECK(`dv1-`/`dd1-` + 32 hex)를
  407에 더했다 — 틀린 값이 비교 키가 되면 모든 행이 영구 stale이다. (5) 407은 forward-only다(`alembic/env.py`가 모든
  downgrade를 해석 전에 거부한다 — ADR-021·102). 왕복 확인은 scratch DB에서 손으로 했다(406까지 올림 → head →
  역 SQL로 표·CHECK 원복 + `alembic_version`=406 → 다시 head, PR 본문).
  (6) 응답 `dataset`의 형식 위반은 선택 파싱이라 None으로 삼키고(지오코딩 응답 자체는 쓴다), `dataset_version()`의
  형식 위반은 typed 오류로 올린다(현재 토큰은 엄격). (7) `GeoCallStats.empty`는 endpoint 단위다 — reverse가 비고 region
  fallback이 채우면 `empty['reverse']` 1건이고 fallback은 `regions_within_radius`로 따로 센다(T-GR-03 run 가드가 어느
  분자를 쓸지 정한다). 소유자 결정(2026-10-15, '없음 → 첫 data_token = 기준선')은 ADR-109 결정 5에 기록했다(구현 T-GR-04/05).
