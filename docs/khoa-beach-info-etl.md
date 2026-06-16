# khoa-beach-info-etl.md — KHOA 해수욕장정보 → place ETL

본 문서는 KHOA(국립해양조사원) 해수욕장 정보를 `place` feature로 적재하는 ETL이다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-khoa-api` |
| dataset_key | `khoa_beaches` (`providers/khoa.py:64` `DATASET_KEY_BEACHES`) — feature_id / source_record_key에 박힘 |
| Feature.kind | `place` |
| source_entity_type | `beach` |
| 상세 테이블 | `feature_place_details` |
| 코드 entrypoint | `kortravelmap.providers.khoa`, `kortravelmap.beaches` |
| 갱신 주기 | 1일 1회 |
| data.go.kr | `15058519` |
| endpoint | `http://apis.data.go.kr/1192000/service/OceansBeachInfoService1/getOceansBeachInfo1` |

## 2. 범위 / 책임

- `python-khoa-api`: REST 호출, typed model (`OceanBeachInfo`), pagination.
- `kor-travel-map`: typed model → `Feature(kind=place)` + `PlaceDetail`,
  이미지 → RustFS.
- kor-travel-map Dagster: schedule.

## 3. dataset 매핑

| 항목 | 값 |
|------|----|
| natural key | `정점명::시도::구군` 조합 (ADR-009 `::`, `providers/khoa.py:149`) |
| FeatureKind | `place` |
| category | **`01020300`** `TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND` (`providers/khoa.py:67` `BEACH_CATEGORY`) — Tier path: 관광 > 자연명소 > 해안/섬 |
| place_kind | `beach` |
| marker_icon | `beach` |
| marker_color | `P-07` (하늘색) |
| `KHOA_OCEANS_BEACH_INFO_FULL_SCAN_INTERVAL_DAYS` | 1 |

> **category 코드 divergence (C-04, DA-D-07 후속)**: 코드 실측은
> `01020300 TOURISM_NATURAL_LANDSCAPE_COAST_ISLAND`(`providers/khoa.py:67`)이며 위
> 표는 이에 정렬했다. 다만 전용 분류 `01050100 TOURISM_NATURE_BEACH`(해수욕장)가
> 의도였을 가능성이 있다 — 어느 쪽이 정본인지는 DA-D-07에서 확정한다(여기서 코드를
> 임의로 뒤집지 않음).

## 4. 필드 매핑

| provider 필드 | DTO 저장 위치 |
|--------------|--------------|
| `sidoNm` | feature 이름 prefix + natural key 부분 |
| `gugunNm` | feature 이름 + natural key 부분 |
| `staNm` | feature 이름 본체 + natural key 부분 |
| `lat`, `lon` | `Feature.coord` (WGS84) |
| `beachWid` (해변 폭) | `feature_place_details.facility_info["beach_width_m"]` |
| `beachLen` (해변 길이) | `facility_info["beach_length_m"]` |
| `beachKnd` (해변 종류) | `facility_info["beach_type"]` |
| `linkAddr` (관련 URL) | `features.urls.homepage` |
| `linkNm` (관련 사이트명) | detail payload |
| `linkTel` (연락처) | `PlaceDetail.phones[0]` |
| `beachImg` (이미지 URL) | RustFS 적재 후보 (`FeatureFileSource`) |
| 전체 row | `source_records.raw_data` |

## 5. 주소·좌표

- 좌표: WGS84 그대로 `Coordinate(lon=..., lat=...)`.
- 주소: 기본 `Address(display_address=f"{sidoNm} {gugunNm}")` — 시도/구군 한글만.
- reverse geocoder 권장 — 정확한 `legal_dong_code` + `road_name_code` 보강.

> **feature_id 안정성 caveat (F-01)**: KHOA 원본은 source-native 행정코드를 주지
> 않아 `bjd_code`가 reverse-geocode로 산출된다. feature_id가 이 `bjd_code`를
> 포함하므로 결과적으로 **geocoder 의존적**이다 — geocoder 버전/응답이 바뀌면 동일
> 정점의 feature_id가 흔들릴 수 있다. 상세는
> `full-consistency-audit-2026-06-16.md` F-01 참조.

## 6. 파일 (RustFS)

```python
def khoa_beach_to_file_sources(item, *, feature_id, source_record_key):
    if not item.beach_img or not item.beach_img.startswith(("http://", "https://")):
        return []                            # 상대 경로/파일명만은 payload만
    return [FeatureFileSource(
        feature_id=feature_id, source_url=item.beach_img,
        role="primary", display_order=0, file_type="image",
        provider="python-khoa-api",
        dataset_key="khoa_beaches",          # providers/khoa.py:64 DATASET_KEY_BEACHES
        source_record_key=source_record_key,
    )]
```

## 7. DB 적재

provider 변환 entrypoint은 `providers/khoa.py`의 `beaches_to_bundles`이고,
적재 orchestration은 Dagster asset `feature_place_khoa_beaches`
(`run_feature_place_khoa_beaches`)가 맡는다.

```python
from kortravelmap.providers.khoa import beaches_to_bundles

# OceanBeachInfo items → list[FeatureBundle] (place, category 01020300)
bundles = await beaches_to_bundles(
    items,
    fetched_at=fetched_at,
    reverse_geocoder=reverse_geocoder,
)
```

Dagster 측 적재(`packages/kor-travel-map-dagster/.../assets.py`):

```python
async def run_feature_place_khoa_beaches(context):
    records = await _record_list(context, "khoa_beaches")
    bundles = await beaches_to_bundles(
        records,
        fetched_at=await _fetched_at(context),
        reverse_geocoder=_reverse_geocoder(context),
    )
    return await _load(
        context,
        provider=KHOA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BEACHES,
        bundles=bundles,
    )
```

전국 시도 (`SIDO_NM` 17종)를 순회하며 각 시도별 page 끝까지. 페이지당
기본 `numOfRows` 1000.

## 8. MOIS 충돌 정책

MOIS 인허가에 같은 위치 / 명칭 해수욕장이 있는 경우:
- MOIS: 영업/시설 정보 우선
- KHOA: 공식 위치/특성/이미지 우선
- 두 feature를 `sibling_group_id`로 묶고 dedup_review_queue에 후보로.

자세한 dedup 패턴은 ADR-016 + `docs/data-model.md` §9.2.

## 9. Dagster

| 항목 | 값 |
|------|----|
| asset 이름 | `feature_place_khoa_beaches` |
| JOB_SPEC | `kortravelmap.providers.khoa.JOB_SPEC` (beach) |
| suggested cron | `0 2 10 * *` (매월 10일 02:00 — 해수욕장 신규/변경 드뭄) |
| group | `features_place` |
| ConcurrencyConfig | `khoa_api: max_concurrent=1` |

(`khoa_coastal_notices`는 별도 — `docs/notice-feature-etl.md`)

## 10. 검증

### 10.1 fixture (≥ 3)

- `oceans_beach_info_donghae.json` — 정상 (강원도 동해안 5건, 이미지 있음)
- `oceans_beach_info_no_image.json` — `beachImg` 빈 값
- `oceans_beach_info_no_phone.json` — `linkTel` 없음
- `oceans_beach_info_empty_sido.json` — 빈 시도 (페이지 0)
- `oceans_beach_info_relative_image_path.json` — 상대 경로 (skip 확인)

### 10.2 통합 테스트

- 17 시도 모두 page 1까지 수집 → seed 데이터로 적재.
- 이미지 PUT → MinIO testcontainer.
- 같은 station 적재 2회 → idempotent.

## 11. 후속

- 해수욕장별 marine 지수 (수온, 파고, 적조) — `weather-feature-normalization.md`의
  `beach_marine` weather_domain.
- 해수욕장 운영기간 (개장일/폐장일) → `feature_special_days`로 비개장일 표시.
- 해수욕장 안전 공지 → `docs/notice-feature-etl.md`의 `khoa_coastal_notices`.
