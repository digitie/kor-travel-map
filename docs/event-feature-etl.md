# Event feature ETL

이 문서는 VisitKorea 축제/행사 데이터를 `event` feature로 정리하는 표준 계약이다.

## 범위

`python-krtour-map`은 축제 데이터를 직접 호출하는 wrapper나 adapter를 만들지 않는다. 안정된
`python-visitkorea-api` public client의 `search_festival`과 `iter_pages`를 직접 사용하고,
반환된 typed item을 아래 계약으로 변환한다.

- `Feature(kind="event")`
- `EventDetail`
- `SourceRecord`
- `SourceLink`
- `feature_event_details`

사용자, 여행계획, POI는 TripMate 제품 도메인이며 이 라이브러리에서 관리하지 않는다.
TripMate는 필요할 때 `feature_id`를 참조한다.

## VisitKorea festival full scan

축제 풀스캔 ETL은 `visitkorea_festival_full_scan_job_spec`로 노출한다.

- dataset key: `visitkorea_festival_events`
- provider: `python-visitkorea-api`
- source type: `festival`
- full scan interval: 1일 1회
- default page size: `1000`
- default start date: `2000-01-01`
- page cap: 기본값 없음

풀스캔은 모든 축제자료를 가져오기 위해 provider client의 pagination helper를 사용한다.

```python
client.iter_pages(
    client.search_festival,
    event_start_date,
    page_no=1,
    num_of_rows=page_size,
    max_pages=None,
)
```

운영 중 긴급 제한이 필요한 경우에만 TripMate 실행 config에서 `max_pages`를 넘긴다. 기본
스케줄에서는 `max_pages`를 설정하지 않아 provider가 알려주는 마지막 페이지까지 순회한다.

## 저장 계약

VisitKorea `content_id`는 source natural key로 사용한다. 좌표가 없는 축제도 존재할 수
있으므로 `Feature.coord`는 `None`을 허용한다. 좌표가 있는 경우에는
`python-kraddr-base`의 `PlaceCoordinate(lat, lon)`를 그대로 사용한다.

`feature_event_details`는 행사 기간과 provider 식별자를 담는다.

- `feature_id`
- `event_kind`
- `starts_on`
- `ends_on`
- `timezone`
- `venue_name`
- `tel`
- `content_id`
- `content_type_id`
- `area_code`
- `sigungu_code`
- `payload`

행사 운영시간이 별도로 구조화되는 provider가 있으면 `FeatureOpeningHours`,
`feature_opening_periods`, `feature_special_days` 계약을 함께 사용한다.

## DB 적재

수집과 적재는 같은 라이브러리 안에 있지만 transaction ownership은 TripMate가 가진다.

- `collect_visitkorea_festival_events(client, ...)`: provider client를 직접 호출하고 DTO 묶음을 반환한다.
- `load_visitkorea_festival_result(session, result)`: 수집 결과를 열린 feature DB session에 staged write한다.
- `collect_and_load_visitkorea_festival_events(session, client, ...)`: 수집과 staged write를 한 번에 수행한다.
- `load_visitkorea_festival_events(resource, run)`: Dagster job spec loader. `resource`가 provider client만이면 수집 결과를, `client`와 `session`을 함께 가진 resource면 수집+DB 적재 결과를 반환한다.

`load_feature_rows`는 update-or-insert 방식으로 아래 순서를 보장한다.

1. `source_records`
2. `features`
3. kind별 detail table
4. opening hours, price, weather values
5. `source_links`
6. `provider_sync_state`

호출자는 성공 시 commit, 실패 시 rollback한다. 이 라이브러리는 Dagster daemon이나 schedule을
직접 실행하지 않으며, TripMate가 resource 주입과 운영 정책을 담당한다.

## TripMate boundary

이 라이브러리는 ETL의 세부 수집/정규화 로직과 job spec을 제공한다. 실제 Dagster
`Definitions`, schedule, daemon, resource 주입, 운영 로그, 알림은 TripMate 쪽에서 실행한다.
