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

`python-krtour-map`은 Dagster package를 필수 dependency로 두지 않는다. 이 라이브러리의 ETL 계약은 Dagster 없이도 테스트 가능해야 하며, Dagster-specific decorator와 `Definitions`는 TripMate에 둔다.

## TripMate 책임

- `dagster dev`, daemon, Docker Compose, 운영 runbook
- `dagster` package import와 `@op`, `@job`, `ScheduleDefinition`, `Definitions` 생성
- DB session/resource 주입
- `etl_run_logs`, 관리자 알림, Telegram outbox 같은 운영 실행 로그
- retry 소진 판단과 실패 알림
- TripMate 제품 DB와 API serving 조립

## 구현 규칙

- 새 feature ETL을 추가할 때 provider API 호출 후 가공/정규화 로직은 `python-krtour-map`에 먼저 둔다.
- TripMate의 `app.dagster_etl`은 `krtour_map.dagster` 계약을 import해서 job/schedule을 생성하고 실행 로그를 남기는 얇은 shell이어야 한다.
- provider별 wrapper/adapter/gateway를 만들지 않는다. 안정된 provider public client와 typed model을 직접 사용한다.
- Dagster 실행 편의를 위해 TripMate에 임시 정규화 함수를 만들지 않는다. 필요한 변환 함수는 `python-krtour-map`에 둔다.
