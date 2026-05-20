# KRMOIS license feature ETL

`python-krmois-api` is the source-of-record for MOIS localdata/raw rows. It keeps
open, closed, cancelled, and unknown-status rows in its own source DB. `python-krtour-map`
does not duplicate those rows into `source_records` for KRMOIS. It reads stable
`python-krmois-api` public models such as `PlaceRecord` and promotes only travel-useful,
currently open rows into feature tables.

## Responsibilities

- `python-krmois-api`: download localdata files, update the MOIS source DB, keep raw/localdata
  detail, and expose open/closed row iterators.
- `python-krtour-map`: convert open `PlaceRecord` rows into `Feature` and `PlaceDetail`,
  delete stale KRMOIS features during full refresh, and provide the Dagster job metadata.
- TripMate: run Dagster, provide the MOIS source DB session, feature DB session, optional
  reverse geocoder, and transaction/alert policy.

No wrapper, adapter, or gateway is added between these packages. Missing endpoint, cursor,
pagination, raw preservation, or status filtering behavior belongs in `python-krmois-api`
first.

## Weekly full update

`krmois_license_feature_full_update_job_spec` describes the TripMate Dagster job.

- schedule: once per week
- source DB sync kind: `localdata_full`
- source DB updater: `python-krmois-api.sync_localdata_source_db(...)`
- open row reader: `python-krmois-api.iter_open_place_records(...)`
- feature loader: `load_krmois_license_feature_result(..., prune_existing=True)`
- closed/cancelled handling: do not keep closed features; remove stale KRMOIS feature rows
  when they are not present in the latest open snapshot

For incremental maintenance or review tools, `python-krmois-api.iter_closed_place_records(...)`
returns closed/cancelled rows from the source DB. `python-krtour-map` also exposes
`delete_krmois_license_features_for_records(...)` so TripMate can remove features for a
closed-only record stream when needed.

## Feature detail contract

KRMOIS-specific physical columns are intentionally avoided. The following values are stored in
`Feature.detail`:

- `selected_source`: provider, source DB, dataset key, service slug, management number, title,
  and local authority code
- `selected_coordinate`: selected WGS84 coordinate plus original EPSG:5174 X/Y when present
- `category_confidence`: confidence of the service-slug to `python-kraddr-base` category mapping
- `match_level`: address/geocoding match level from `AddressMatchReport`
- `visible_status`: always `visible` for promoted KRMOIS rows
- `visible`: `true` for promoted rows
- `license_status`: source status code/name and detail status
- `license_dates`: license/designation/update timestamps
- `address_codes`: original legal-dong/road/building codes and enriched legal-dong match result

`Feature.raw_refs` keeps a lightweight source reference to the MOIS service slug and management
number. Full raw/localdata payload remains in the `python-krmois-api` source DB.

## Excluded service slugs

The following rows stay in the MOIS source DB but are not promoted to map features:

- `beauty_salons`, `barber_shops`
- `laundries`, `medical_laundry`
- `oil_retailers`, `petroleum_alt_fuel_retailers`, `lpg_equipment_manufacturers`
- `animal_hospitals`, `animal_pharmacies`, `pet_grooming`, `animal_boarding`
- `billiard_halls`, `video_viewing_rooms`, `karaoke_rooms`, `golf_practice_ranges`
- `dance_halls`, `dance_academies`, `film_screenings`, `pc_bangs`
- `optical_shops`, `over_the_counter_medicine_stores`

No new `python-kraddr-base` categories are added for the previously discussed pet, urban leisure,
MICE, or life-service gaps as part of this ETL.

## Promoted feature-specific details

`PlaceDetail.facility_info` is shaped by feature group:

- medical: bed/sickbed counts, healthcare worker count, room count, institution type, medical
  subjects
- food: sanitation business status, water supply facility type, business/subtype, area
- lodging: facility scale, area, floors, building usage, multi-use flag
- culture/leisure/activity: culture-sports subtype, designation date, area/floor values
- retail: sales method and facility scale

Business hours are not inferred from MOIS license rows unless a future stable provider model
exposes DTO-compatible opening-hours fields. Image/file assets are also not expected from KRMOIS;
providers with media continue to store binaries in RustFS and metadata in `feature_files`.

## Deferred

The management-number blank-row fingerprint proposal is deferred. Current feature identity uses
the stable `PlaceRecord.mng_no` supplied by `python-krmois-api`. If blank management-number
resynchronization becomes a real data problem, implement and document the fingerprint in
`python-krmois-api` first, then consume that public field here.
