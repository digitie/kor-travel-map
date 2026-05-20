# Korea Heritage feature ETL

`python-krtour-map` adds Korea Heritage Administration data as `place`, `area`,
and `event` features. Provider calls stay in the stable public API surface of
`python-krheritage-api`; this library does not create `KheritageWrapper`,
`HeritageAdapter`, or a TripMate-only gateway.

## Source libraries

- Provider package: `python-krheritage-api`
- Import module: `krheritage`
- Canonical provider name: `python-krheritage-api`
- Accepted alias for older local folder naming: `python-kheritage-api`

The provider must own endpoint coverage, typed models, pagination, cursor
handling, exceptions, and raw payload preservation. `python-krtour-map` only
converts provider public models into feature/source/detail/file rows.

## Dataset keys

| dataset_key | Purpose | Feature output |
| --- | --- | --- |
| `search_list` | Heritage summary/detail models from `SearchKindOpenapiList` and `SearchKindOpenapiDt` | `place` or `area` |
| `gis_spca` | Legacy GIS location API from `gis-heritage.go.kr/openapi/xmlService/spca.do` | coordinate/boundary enrichment |
| `gis_3070426` | Public-data heritage spatial dataset with coordinate, area, regulation scope, and media metadata | `area` boundary/detail enrichment |
| `event_list` | Korea Heritage event list such as `selectEventListOpenapi` | `event` |
| `15145324` | Notice/public-announcement source candidate | future `notice` enrichment |
| `15041861` | Intangible heritage event/source candidate | future `event` enrichment |

## Feature mapping

The source natural key for heritage records is:

```text
ccbaKdcd-ccbaAsno-ccbaCtcd
```

Mapping rules:

- National treasure, treasure, registered heritage, and most folklore/tangible
  records become `place` features.
- Historic site, historic/scenic site, scenic site, buried heritage, and records
  with GIS geometry become `area` features.
- Natural monument without a boundary remains a `place`; habitats or protected
  zones with GIS geometry become `area`.
- Intangible heritage training centers and venues become `place`; performances
  and education programs become `event`.
- Event rows use the provider event id (`sn`) as the source entity id.

KRMOIS remains the broad base dataset for commercial/place rows. Korea Heritage
records are `primary` when they create a heritage feature directly, and can be
linked as `enrichment` by a host merge process when the same real-world place is
already promoted from another source.

## DB schema

Heritage place rows use the existing `features`, `source_records`,
`source_links`, `feature_place_details`, and `feature_files` tables.

Heritage area rows use `feature_area_details`:

| Column | Meaning |
| --- | --- |
| `feature_id` | FK to `features.feature_id`, also the primary key |
| `area_kind` | `heritage_area`, `natural_heritage_area`, or provider-specific area kind |
| `boundary_source` | `gis_3070426`, `gis_spca`, or another public dataset key |
| `area_square_meters` | Provider area value when present |
| `regulation_scope` | Protection/regulation scope text |
| `administrative_office` | Managing office or administrator |
| `description` | Area description/content text |
| `geometry` | GeoJSON-like geometry payload |
| `payload` | Provider detail payload and match metadata |

Images, videos, narrations/audio, and document assets are not stored in feature rows.
They are uploaded to RustFS and represented by 1:N `feature_files` rows. `python-krheritage-api`
keeps only typed media URL/raw model ownership; RustFS upload/list/config logic lives in
`python-krtour-map`.

## Dagster boundary

This library owns the ETL body and normalized DB load helpers:

- `collect_krheritage_heritage_features(items, ...)`
- `load_krheritage_heritage_result(session, result, ...)`
- `load_krheritage_heritage_features(resource, run)`
- `collect_krheritage_events(items, ...)`
- `load_krheritage_event_result(session, result, ...)`
- `load_krheritage_events(resource, run)`

TripMate owns actual Dagster execution, schedules, resources, and operational
alerts. It should pass `krheritage` public clients or already-collected provider
models, the feature DB session, optional RustFS store, optional file fetcher, and
optional reverse geocoder callable.

When a `krheritage.HeritageClient` is passed as a resource, the ETL body consumes
the provider public API directly:

- heritage place/area scan: `client.heritage.iter_all_details(...)` or
  `client.search.iter_all_details(...)`
- event scan: `client.event.iter_months(...)`
- GIS coordinate/boundary source: `client.gis.spca(...)` is available to the
  caller as a provider model source and should be fed into the same normalize/load
  flow once matched to a heritage natural key

Supported run config keys are forwarded to the provider client without adding a
TripMate wrapper: `page_size`, `max_pages`, `ccba_kdcd`, `ccba_ctcd`,
`ccba_asno`, `st_ccba_asdt`, `st_ccba_aedt`, `ccba_cndt`, `ccba_mnm1`,
`search_year`, `search_month`, `months_back`, and `months_ahead`. Camel-case
API keys such as `ccbaKdcd` are normalized to the provider service's snake-case
arguments before calling the public client.

Job specs exported by this library:

- `krheritage_heritage_full_scan_job_spec`: weekly full scan, tags include
  `schedule:weekly`, `feature:place`, and `feature:area`.
- `krheritage_event_full_scan_job_spec`: daily full scan, tags include
  `schedule:daily` and `feature:event`.

Schedules are enabled when one of `KHERITAGE_API_KEY`, `KRHERITAGE_API_KEY`, or
`DATA_GO_KR_SERVICE_KEY` is available.

## Address and coordinates

Coordinates use `python-kraddr-base` `PlaceCoordinate` through the local
`Coordinate` alias. The order is `lat`, then `lon` at object construction time,
while DB rows remain explicit `latitude` and `longitude` columns.

Address enrichment follows the shared `AddressMatchReport` flow. Provider
address text and coordinate-derived legal-dong information are preserved in
`Feature.detail.address_codes` rather than adding provider-specific DB columns.

## python-krheritage-api requirements

The provider package should expose stable public models with these fields or
equivalent aliases:

- `HeritageKey.ccba_kdcd`, `ccba_asno`, `ccba_ctcd`, `natural_key`
- `HeritageSummary` / `HeritageDetail`: `key`, `name_ko`, `longitude`,
  `latitude`, `image_url`, `domain`, `category`, `location_text`,
  `designated_at`, `manager`, `content`, and `raw` or `model_dump(mode="json")`
- `HeritageEvent`: `sn`, `title` or `sub_title`, `sub_title2`, `starts_on`,
  `ends_on`, `place`, `address`, `tel_name`, `contents`, `main_image`,
  `longitude`, `latitude`
- `GeoFeature`: `geometry` plus `properties` containing a stable id for area
  source identity

If a required endpoint, field, pagination helper, exception, or raw payload rule
is missing, fix it in `python-krheritage-api` first. Do not add temporary
provider wrappers in TripMate or `python-krtour-map`.
