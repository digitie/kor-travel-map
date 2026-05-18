# Dagster 경계

`python-krtour-map`은 API 수집 결과를 feature/source/weather/price 계약으로 가공하는 ETL 단계의 공통 로직을 가진다. 실제 Dagster process, daemon, UI, schedule 실행은 TripMate가 가진다.

## python-krtour-map 책임

- Dagster op에 전달되는 실행 context DTO: `DagsterEtlExecution`, `DagsterEtlRun`
- ETL job metadata 계약: `EtlJobSpec`, `EtlRunIdentity`
- logical datetime, `run_type`, 수동 backfill config 파싱
- provider/data 부재를 실패가 아닌 skip으로 표현하는 `EtlSkip`
- loader 결과를 Dagster metadata/log payload에 넣기 위한 `json_ready`
- download/log directory resolution helper
- feature/source/weather/price DTO와 DB row 변환
- provider typed model을 feature 계약으로 정규화하는 순수 함수
- PostGIS blocking과 scoring 기준, dedup review payload, data integrity violation payload
- provider sync cursor와 retry 가능한 checkpoint row helper

`python-krtour-map`은 Dagster package를 필수 dependency로 두지 않는다. 이 라이브러리의 ETL 계약은 Dagster 없이도 테스트 가능해야 하며, Dagster-specific decorator와 `Definitions`는 TripMate에 둔다.

## TripMate 책임

- `dagster dev`, daemon, Docker Compose, 운영 runbook
- `dagster` package import와 `@op`, `@job`, `ScheduleDefinition`, `Definitions` 생성
- DB session/resource 주입
- `etl_run_logs`, 관리자 알림, Telegram outbox 같은 운영 실행 로그
- retry 소진 판단과 실패 알림
- Odroid 단일 worker 환경의 concurrency=1 실행 설정
- TripMate 제품 DB와 API serving 조립

## 구현 규칙

- 새 feature ETL을 추가할 때 provider API 호출 후 가공/정규화 로직은 `python-krtour-map`에 먼저 둔다.
- TripMate의 `app.dagster_etl`은 `krtour_map.dagster` 계약을 import해서 job/schedule을 생성하고 실행 로그를 남기는 얇은 shell이어야 한다.
- provider별 wrapper/adapter/gateway를 만들지 않는다. 안정된 provider public client와 typed model을 직접 사용한다.
- Dagster 실행 편의를 위해 TripMate에 임시 정규화 함수를 만들지 않는다. 필요한 변환 함수는 `python-krtour-map`에 둔다.
- 중복 판단과 검수 queue 저장은 이 라이브러리의 `dedup_review_queue` 계약을 사용한다.

## VisitKorea festival full scan

축제/행사 수집은 `visitkorea_festival_full_scan_job_spec`로 노출한다. 이 job spec은
TripMate가 실제 Dagster `ScheduleDefinition`을 만들 때 사용할 메타데이터이며, 라이브러리
자체가 Dagster daemon을 실행하지 않는다.

- 실행 주기: 1일 1회
- dataset key: `visitkorea_festival_events`
- provider: `python-visitkorea-api`
- pagination: `iter_pages(client.search_festival, ...)`로 마지막 페이지까지 순회
- 기본 `max_pages`: 없음

TripMate 운영 config에서 `max_pages`를 넘기면 긴급 제한용으로만 사용한다. 기본 full scan은
모든 축제자료를 가져오는 것을 우선한다.
