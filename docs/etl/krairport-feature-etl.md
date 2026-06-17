# krairport-feature-etl.md — KRAirport 공항 메타데이터 → place ETL

본 문서는 KRAirport(`python-krairport-api`)의 번들 공항 메타데이터를 `place`
feature로 적재하는 ETL이다. 공항 메타데이터 목록(`client.airports()`)은 **번들
정적 데이터**라 credential 없이 쓸 수 있다(knps와 동일 keyless).

코드 정본: `src/kortravelmap/providers/krairport.py`.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-krairport-api` (`KRAIRPORT_PROVIDER_NAME`) |
| dataset_key | `krairport_airports` (`DATASET_KEY_AIRPORTS`) |
| Feature.kind | `place` |
| source_entity_type | `airport` |
| 상세 테이블 | `feature_place_details` |
| category | **`06050000`** `TRANSPORT_AIRPORT` (`AIRPORT_CATEGORY`, `docs/architecture/category.md` §4) — Tier path: 교통 > 공항 |
| place_kind | `airport` (`AIRPORT_PLACE_KIND`) |
| marker_icon | `airport` (maki — `mapbox_maki_icon_or_none("06050000")`; `_DEFAULT_AIRPORT_ICON` fallback도 `airport`) |
| marker_color | `P-10` (`AIRPORT_MARKER_COLOR`) |
| 코드 entrypoint | `kortravelmap.providers.krairport` |
| 갱신 주기 | 정적 메타데이터 → 월 1회 |
| MOIS dedup | 후보 없음 |

## 2. 범위 / 책임

- `python-krairport-api` (`import krairport`): 번들 공항 메타데이터
  (`AirportMetadata`) 제공, keyless.
- `kor-travel-map`: typed model → `Feature(kind=place)` + `PlaceDetail`.
- kor-travel-map Dagster: schedule.

## 3. 변환 계약

```python
from kortravelmap.providers.krairport import airports_to_bundles

bundles = await airports_to_bundles(
    airports,                        # AirportMetadataItem Protocol iterable
    fetched_at=kst_now(),
    reverse_geocoder=reverse_geocoder,
)
# bundle.feature: Feature(kind=place, category="06050000")
# bundle.feature.detail: PlaceDetail(place_kind="airport", facility_info=...)
# bundle.source_record + source_link
```

## 4. 필드 매핑

| provider 필드 | DTO 저장 위치 |
|--------------|--------------|
| `name_korean` | `Feature.name` 우선 (`normalize_korean_text`) |
| `name_english` | 한글명 없을 때 `Feature.name` fallback + `PlaceDetail.facility_info["name_english"]` |
| `code` (IATA) | natural key (`source_entity_id`) |
| `icao_code` | `PlaceDetail.facility_info["icao_code"]` |
| `municipality` | `Address.admin` fallback (소재 도시명) |
| `coordinate` (provider `Coordinate`) | `Feature.coord` (`.lat`/`.lon` → `Decimal`) |
| 전체 row | `source_records.raw_data` |

이름 우선순위: `name_korean` → `name_english` → `code`.
`facility_info`는 None 값을 제외하고 채운다.

## 5. natural key / feature_id

안정키는 **공항 코드(`code`, IATA)** — 예 `ICN`. 도로명 주소가 없어 좌표 reverse로
bjd를 보강한다.

```text
source_entity_id = item.code              # 예: "ICN"
feature_id = make_feature_id(
    bjd_code=<reverse-geocoded>, kind="place",
    category="06050000",
    source_type="python-krairport-api:krairport_airports",
    source_natural_key=item.code,
)
```

## 6. feature_id 안정성 (F-01 caveat)

`make_feature_id`는 `bjd_code` + `category`를 식별자에 embed한다. 공항 변환은
provider가 도로명 주소를 주지 않아 **`bjd_code`를 공항 좌표의 reverse geocoding으로
늦게 얻는다** — `reverse_geocoder`는 optional(Dagster resource 기본 None)이라 geocoder
유무·출력 변동 시 같은 공항이 `f_global_…`↔`f_<bjd>_…`로 갈려 재import 시 중복
(soft-delete-old + new-feature)이 날 수 있다. 즉 feature_id는
**geocoder-conditional**(조건부 결정성)이다. natural key(IATA `code`)는 안정적이므로,
ADR-057 anchoring(stable source key + 고정 identity category, bjd는 가변 속성)을 적용하면
이 비멱등은 해소된다(어느 provider에 확대할지는 backlog 결정).

상세: `docs/reports/full-consistency-audit-2026-06-16.md` §3 F-01 +
`docs/architecture/provider-contract.md` §6.

## 7. 후속

- 공항 운영 정보(터미널/주차/연계 교통) 보강 — provider 추가 endpoint 검토.
- 항공기상(`python-krairport-api` / KMA 연계) → `WeatherValue` 부착.
- 공항 feature에 ADR-057 anchoring 적용 시 F-01 비멱등 해소(backlog).
