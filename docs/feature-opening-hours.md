# Feature opening hours

이 문서는 Google Docs
[`영업시간 DB 및 DTO 설계 가이드`](https://docs.google.com/document/d/1NMb-qB2I1BxRKrR8duAS28vr_PldzIf75Lvz-OlVU80/edit?tab=t.0)를
feature 공통 자료로 반영한 canonical 설계다.

## 적용 범위

`opening hours`는 `place`에만 묶지 않는다. 축제, 공연, 전시, 캠핑장, 휴게소,
공항 주차장처럼 운영 시간이 붙을 수 있는 모든 `Feature`가 같은 DTO와 DB
테이블을 사용한다.

TripMate는 사용자, 여행계획, POI snapshot을 관리하지만 운영시간 공통 자료의
저장 계약과 변환 함수는 `python-krtour-map`을 사용한다.

## DTO 계약

- `OpeningTime`: Google Places 스타일의 `day`와 `time` 조합이다.
  - `day`: `0=Sunday`부터 `6=Saturday`
  - `time`: 장소 로컬 시간 기준 `HHMM`
- `OpeningPeriod`: 하나의 연속 운영 구간이다.
  - `open`, `close`를 가진다.
  - 자정을 넘는 운영은 하나의 period로 유지한다. 예: 금요일 20:00부터 토요일
    02:00까지는 `open={day:5,time:"2000"}`, `close={day:6,time:"0200"}`.
  - 24/7은 Google Places signature에 맞춰 `open={day:0,time:"0000"}`,
    `close=None`으로만 표현한다.
- `SpecialOpeningDay`: 날짜별 예외 운영시간이다.
  - `is_closed=True`이면 `periods`를 비워야 한다.
  - `is_closed=False`이면 단축/연장 운영 period가 최소 1개 있어야 한다.
- `FeatureOpeningHours`: `timezone`, `periods`, `special_days`,
  `weekday_text`, `open_now`를 묶는 루트 DTO다.

이 모델은 절대 timestamp를 저장하지 않고 feature가 위치한 장소의 로컬 요일과
로컬 시간을 저장한다. DST가 있는 지역까지 확장하더라도 스케줄 정의 자체는
변하지 않고, 현재 영업 여부 계산 시점에만 timezone 변환을 수행한다.

## DB 계약

`feature_opening_periods`는 정규 운영 구간을 SQL에서 검색할 수 있도록 정규화한다.

- `feature_id`
- `period_index`
- `start_weekday`
- `start_time`
- `duration_minutes`
- `timezone`
- `payload`

PostgreSQL 운영 환경에서는 문서 원안처럼 `btree_gist`와 `tsrange`/interval 기반
겹침 방지 제약을 추가하는 것을 권장한다. 라이브러리 metadata는 SQLite 테스트와
TripMate 초기 통합을 위해 portable한 `duration_minutes` 컬럼을 기본 계약으로 둔다.

`feature_special_days`는 정규 운영시간을 날짜 단위로 override한다.

- `feature_id`
- `special_date`
- `is_closed`
- `periods`
- `payload`

특정 날짜의 영업 상태를 계산할 때는 `feature_special_days`를 먼저 확인하고,
매칭되는 날짜가 있으면 `feature_opening_periods`의 정규 패턴을 무시한다.

## Event feature와의 관계

축제/공연/행사는 기간성 자체가 중요하므로 `feature_event_details`가 별도로
`starts_on`, `ends_on`, `event_kind`, VisitKorea `content_id`를 가진다. 운영시간
텍스트나 상세 운영 구간을 얻을 수 있는 provider가 있으면 `FeatureOpeningHours`를
`feature_opening_periods`와 `feature_special_days`에 저장한다.

VisitKorea `searchFestival2` 목록 응답은 날짜와 좌표/주소 중심이므로 일단
`feature_event_details.starts_on`, `feature_event_details.ends_on`을 채우고,
상세 API에서 `playtime`을 구조화할 수 있게 되면 같은 opening-hours 공통 계약으로
확장한다.
