# prod API live 계약 점검 — concierge export / geo v2

## 범위

- `kor-travel-concierge` 로컬 repo는 `origin/main` `bec63ad2ab39` 기준으로 확인했다.
- `kor-travel-geo` 로컬 repo는 `F:\dev\kor-travel-geo-codex`의 `origin/main`
  `8b7efbe20e92` 기준으로 확인했다. `F:\dev\kor-travel-geo` 자체는 git repo가 아니라
  `data/` 디렉터리만 가진다.
- 두 서비스 live smoke는 prod 설정 기준의 read-only API만 호출했다. DB write, Dagster
  materialize, feature inactive 전환은 실행하지 않았다.

## concierge export

공급자 정본(`docs/feature-export-api.md`)과 현재 `kor-travel-map` fetcher/loader는 같은
계약을 사용한다.

- 경로: `GET /api/v1/features/snapshot`, `GET /api/v1/features/changes`
- 인증: `X-API-Key`
- 응답: envelope 없는 `{items, next_cursor, has_more}`
- page size: `limit` 1 이상 500 이하
- item identity: `provider=kor-travel-concierge-youtube`,
  `dataset_key=youtube_place_candidates`,
  `source_entity_type=extracted_place_candidate`

live smoke 결과:

- `snapshot?limit=1`: 200, `items=1`, `has_more=true`, `next_cursor` 있음
- `changes?limit=1`: 200, `items=1`, `has_more=true`, `next_cursor` 있음
- 첫 item: `operation=upsert`, `candidate_id` 있음, provider/dataset 정합
- `fetch_kor_travel_concierge_youtube_features`로 첫 item read 성공
- `kor_travel_concierge_items_to_bundles` live item 변환 성공:
  `bundles=1`, `inactive_ids=0`, `feature_id` prefix `f_global_p_`

## geo v2

`kor-travel-geo` 최신 v2 정본은 ADR-062 이후 후보 좌표를
`CandidateV2.point = {lon, lat}`(`PointV2`)로 낸다. 기존 `kor-travel-map`
REST 파서는 pre-ADR-062 `point.x/y`만 읽고 있어 `geocode_response_to_coordinate`
경로가 최신 응답에서 좌표를 못 읽는 drift가 있었다.

반영:

- `KraddrPoint` structural Protocol을 `lon`/`lat` 기준으로 정렬했다.
- `_parse_point`는 최신 `lon`/`lat`를 우선 읽고, 구 `x`/`y`는 호환 fallback으로만
  받는다.
- public method 시그니처는 유지했다. `KorTravelGeoRestClient.reverse(x, y, ...)`는
  기존 caller 호환을 위해 인자명을 그대로 두고 wire body는 v2 정본인 `lon`/`lat`로
  보낸다.

live smoke 결과:

- `POST /v2/geocode`: `status=OK`, candidates 1건, 좌표 파싱 성공,
  `point_lonlat=true`
- `kor_travel_geo_address_geocoder`: 좌표 `126.97770627907322,37.56620502187806`
  반환
- `POST /v2/reverse`: `bjd=1114010300`, `sigungu=11140`
- `POST /v2/regions/within-radius`: 시군구 6건, sample `11140,11110,11170`

## 검증

- `python -m pytest tests/unit/test_geocoding.py -q` → 58 passed
- `ruff check src/kortravelmap/geocoding.py tests/unit/test_geocoding.py
  docs/architecture/address-geocoding.md` → passed
- `python -m pytest tests/unit/test_providers_kor_travel_concierge.py
  packages/kor-travel-map-dagster/tests/test_provider_fetchers.py -q` →
  71 passed, 1 skipped (`mois.db` optional import)

