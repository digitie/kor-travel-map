# address-geocoding.md — 주소·좌표 보강

본 문서는 feature 주소/좌표를 본 라이브러리 `Address` DTO로 정리하고,
`kor-travel-geo`(구 `kor-travel-geo`) REST v2 기반 정/역지오코딩으로 통일하는
패턴이다.

**ADR-041 (2026-05-27)** — 주소 DTO + utility는 `python-kraddr-base`에서
본 라이브러리로 흡수. 외부 의존 1개 제거.

## 1. 의존 라이브러리

- 주소 DTO: **`kortravelmap.dto.Address`** (PR#37, ADR-041 — kraddr-base 흡수).
  보강 필드: bjd_code / admin_dong_code / sigungu_code / sido_code /
  road_name_code / road_address_management_no / zipcode / sido_name /
  sigungu_name.
- 좌표 DTO: **`kortravelmap.dto.Coordinate`** (`PlaceCoordinate` 명시적 제외).
- 주소 normalize / 행정코드 parse: **`kortravelmap.core.address`** (PR#37) —
  `normalize_bjd_code` / `parse_bjd_code` / `extract_sigungu_code` /
  `extract_sido_code` / `normalize_phone_number` / `normalize_korean_text`.
- geocoding 엔진: `kor-travel-geo`(현 REST/env 표기 `kor-travel-geo`) **REST API v2**
  (provider-neutral `POST /v2/reverse`,
  `POST /v2/geocode`). 별도 FastAPI 서비스로 기동하며 본 라이브러리는 **HTTP로만**
  호출한다 — python 패키지/DB 의존 없음 (ADR-006). v1 sqlite store 및 in-process
  `AsyncAddressClient`는 폐기. v2 응답은 `CandidateV2.address.legal_dong_code` 등
  **structured field를 직접 제공**하므로(vworld level 파싱 불필요), 본 모듈은 v2로
  전환됐다. health check는 주소 정/역지오코딩 API 계약과 분리된 운영 endpoint로만
  취급하고, 주소 기능 문서에서는 구 address API 경로를 사용하지 않는다.
- 연동 모듈: **`kortravelmap.geocoding`** — kor-travel-geo / httpx를 **런타임 import 하지
  않는다**(httpx는 TYPE_CHECKING 전용). REST 응답(`ReverseResponse`/`GeocodeResponse`/
  `AddressStructure`/`GeocodeExtension`) structural Protocol만 의존(ADR-006). 순수
  변환 함수 `reverse_response_to_address` / `geocode_response_to_coordinate` /
  `geocode_response_to_address` + `KorTravelGeoRestClient`(httpx.AsyncClient 주입) +
  콜러블 팩토리.
- 설정: `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` — REST 서비스 base URL. 로컬 개발의
  공식 `kor-travel-geo` FastAPI 포트는 `http://127.0.0.1:12501`
  (`kor-travel-geo/docs/ports.md`). `None`이면 정/역지오코딩 보강 비활성
  (좌표만으로 적재).
- VWorld 폴백 키: `kor-travel-geo` REST 서비스 내부 설정에서만. 본 라이브러리에서
  `python-vworld-api` 직접 import 금지.

## 1.1 주소 정본 정책 (ADR-046)

provider가 제공하는 주소 문자열, 행정구역명, provider 자체 행정코드는
**원천/provenance 입력**일 뿐 `features.address`와 행정코드 컬럼의 정본이 아니다.
저장 정본은 항상 `kor-travel-geo` REST v2 결과로 만든 `kortravelmap.dto.Address`다.

- 좌표가 있으면 `POST /v2/reverse`로 주소와 행정코드를 얻는다.
- 주소 문자열만 있고 좌표가 없으면 `POST /v2/geocode`의 structured
  `legal_dong_code`/`region.bjd_cd`로 법정동코드를 먼저 보강한다. 좌표 후보가 필요하거나
  주소-좌표 정합성 검사가 필요한 workflow에서는 그 좌표를 다시 `POST /v2/reverse`로
  정규화한다.
- 좌표와 주소가 함께 있으면 **좌표 기준 reverse 결과를 정본**으로 삼고, provider
  주소 문자열과 kor-travel-geo 주소를 비교해 `AddressMatchReport`를 만든다.
- provider 주소가 일부만 있거나 결측이면 남은 주소 문자열, 좌표, 시군구명 같은
  단서를 kor-travel-geo 요청 입력으로 사용한다.
- provider 자체 코드(예: VisitKorea `areaCode`, OpiNet `sigun_code`, MOIS
  관할기관 코드)는 `source_records.raw_data`와 detail payload에만 보존한다.
  법정동코드/시군구코드로 직접 저장하지 않는다.
- kor-travel-geo 호출 실패, 결과 없음, confidence 미달, provider 주소와 좌표 기준 주소의
  불일치, 행정코드 충돌은 `ops.data_integrity_violations` 또는 후속 주소 검토 큐에
  기록하고 admin UI에서 수동 처리한다.
- geocoder resource 미주입은 정상 degrade가 아니라 운영 설정 누락이다. admin/ops
  화면에서 provider별 `not_geocoded` 비율을 확인해야 한다.

## 2. 핵심 callable

```python
from typing import Awaitable, Callable

from kortravelmap.dto import Address, Coordinate

# 정지오코딩: 주소 문자열 + 코드 → 좌표
AddressGeocoder = Callable[[Address], Awaitable[Coordinate | None]]

# 주소 보강: 주소 문자열 → 법정동코드/시군구코드가 있는 Address
AddressResolver = Callable[[Address], Awaitable[Address | None]]

# 역지오코딩: 좌표 → 행정구역 코드가 있는 Address
ReverseGeocoder = Callable[[Coordinate], Awaitable[Address | None]]
```

**provider 변환 함수는 모두 async** (ADR-002). feature_id가 bjd_code에
의존하므로(ADR-009) 변환기는 feature_id 계산 **전에** kor-travel-geo를 호출해
`Address`를 채운다. 좌표가 있으면 `reverse_geocoder(coord)`, 좌표가 없고 주소
문자열이 있거나 reverse 결과에 `bjd_code`가 없으면 `address_resolver(address)`로
structured `legal_dong_code`/`region.bjd_cd`를 보강한다. 좌표 후보가 필요할 때만
`address_geocoder(address)`를 사용한다. 같은 batch의 중복 좌표/주소는
`geocoding.cached_reverse_geocoder`와 `cached_address_resolver`로 1회만 호출한다
(변환기가 내부에서 자동 래핑).

`reverse_geocoder`/`address_resolver`를 받는 변환 함수 (모두 async):
- `standard_data.cultural_festivals_to_bundles` (datagokr 축제)
- `opinet.stations_to_bundles` (주유소)
- `krex.rest_areas_to_bundles` (휴게소)
- `krheritage.heritage_items_to_bundles` / `heritage_events_to_bundles`
- `mois.license_records_to_bundles`
- `knps.knps_point_records_to_bundles` / `knps_geometry_records_to_bundles`
  + CsvPreview 브리지 (centroid 역지오코딩)

```python
@dataclass(frozen=True)
class GeocoderResources:
    address_geocoder: AddressGeocoder | None = None
    address_resolver: AddressResolver | None = None
    reverse_geocoder: ReverseGeocoder | None = None
```

## 3. kor-travel-geo REST 클라이언트 → 콜러블 (구현 완료, PR#90/#123)

호출자가 `httpx.AsyncClient`(base URL = REST 서비스 호스트)를 만들어
`KorTravelGeoRestClient`에 주입하고 팩토리에 넘기면 §2 콜러블이 만들어진다.
httpx/AsyncClient 수명(close)은 호출자 책임 (ADR-002 async-only). 본 라이브러리는
kor-travel-geo / httpx를 **런타임 import 하지 않는다** — httpx는 TYPE_CHECKING 전용,
client는 `KorTravelGeoRestClient`(REST 응답 structural Protocol)로만 의존.

```python
import httpx
from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    kor_travel_geo_address_resolver,
    kor_travel_geo_reverse_geocoder,
    kor_travel_geo_address_geocoder,
)

async with httpx.AsyncClient(base_url=settings.kor_travel_geo_base_url) as http:
    client = KorTravelGeoRestClient(http)              # POST /v2/reverse·geocode
    reverse = kor_travel_geo_reverse_geocoder(client, max_distance_m=50)
    resolve = kor_travel_geo_address_resolver(client, min_confidence=0.5)
    geocode = kor_travel_geo_address_geocoder(client, min_confidence=0.5)

    addr = await reverse(Coordinate(lon=Decimal("127.0"), lat=Decimal("37.5")))
    resolved = await resolve(Address(road="서울특별시 영등포구 여의공원로 120"))
    coord = await geocode(Address(road="서울특별시 영등포구 여의공원로 120"))
```

매핑은 §4. `status != "OK"`/결과 없음/(reverse) `max_distance_m` 초과/(geocode)
`min_confidence` 미달이면 `None`. 자릿수가 틀린 코드(bjd/sigungu/zipcode/admin_dong)는
`None`으로 떨어뜨려 `Address` validator 거부를 피한다.

### 3.1 v2 REST 응답 → `Address` 매핑 (reverse)

v2 `ReverseV2Response.candidates[]`는 structured field를 직접 제공한다 — vworld
level 파싱이 없다 (`kor-travel-geo` `dto.v2` 정본). `distance_m` 최소 candidate가
대표다. 후보 좌표는 ADR-062 이후 `point.lon`/`point.lat`(`PointV2`)가 정본이며,
구 `point.x`/`point.y`는 REST 파서 호환 fallback으로만 받는다.

| v2 필드 | `Address` 필드 |
|---------|----------------|
| `address.legal_dong_code` (10자리; 없으면 `region.bjd_cd`) | `bjd_code` → `sigungu_code`/`sido_code` 파생 |
| `address.admin_dong_code` (10자리만) | `admin_dong_code` |
| `address.road_name_code` | `road_name_code` |
| `address.road_address` (road candidate; 없으면 `address.full`) | `road` |
| `address.parcel_address` (parcel candidate) | `legal` |
| `region.admin_dong`/`region.legal_dong` | `admin` |
| `address.postal_code` (5자리만) | `zipcode` |
| `region.sido`/`region.sigungu` | `sido_name`/`sigungu_name` |

v1과 달리 reverse도 `road_name_code`를 제공한다(`address.road_name_code`).
`candidate.match_kind`(`road`/`parcel`)로 road/parcel을 구분한다(v1 `type` 대체).

## 4. 코드 변환 기준

| 원천 코드 | 본 라이브러리 저장 기준 |
|----------|----------------------|
| `legal_dong_code`, `admCd` (10자리) | 그대로 `features.legal_dong_code` |
| `roadAddrMgtNo` (25자리) | `features.road_address_management_no`. 법정동코드 파생 가능하면 함께 저장 |
| `sggCd` (5자리), 시군구 코드 | 시군구 레벨 법정동 표현 `1111000000` 형태. match_level=`sigungu_code_only` |
| VisitKorea `areaCode`/`sigunguCode` | provider 코드 — `raw_data`/`payload`에만 보존. 법정동코드로 저장 X. kor-travel-geo reverse/geocode로 확정 |
| OpiNet `sigun_code` | 동일 — `raw_data`/`payload`에만. kor-travel-geo reverse/geocode로 확정 |
| MOIS 관할기관 코드 | `payload`에만 |

**철칙**: provider 주소 문자열이나 provider 자체 코드만으로 `legal_dong_code`를
추정하지 않는다. kor-travel-geo 결과가 없으면 `null` + 검토 상태로 둔다.

## 5. AddressEnrichment + AddressMatchReport

```python
@dataclass(frozen=True)
class AddressEnrichment:
    address: Address                       # 보강된 최종 Address (caller가 사용)
    geocoded_address: Address | None       # reverse geocoder 결과 raw
    coordinate: Coordinate | None          # 정/역지오코딩으로 얻은 좌표
    report: AddressMatchReport             # 매칭 수준 + 사유
```

```python
@dataclass(frozen=True)
class AddressMatchReport:
    match_level: str
    source_legal_dong_code: str | None
    geocoded_legal_dong_code: str | None
    provider_address: str | None = None
    normalized_address: str | None = None
    distance_m: float | None = None
    notes: list[str] = field(default_factory=list)
```

## 6. `match_level` 카탈로그

| `match_level` | 의미 | 운영 검토 |
|--------------|------|----------|
| `legal_dong_exact` | 원천 법정동코드와 좌표 reverse geocoding 결과 일치 | 정상 |
| `coordinate_legal_dong` | 원천 코드 없고 좌표로 채움 | 정상 |
| `legal_dong_conflict` | 원천 코드와 좌표 결과 충돌 | **검토 대상** |
| `source_legal_dong` | 원천이 표준 법정동코드를 직접 제공했고 kor-travel-geo 결과와 충돌 없음 | 정상 |
| `provider_code_converted` | 도로명주소관리번호 등으로 파생 | 정상 |
| `sigungu_code_only` | 시군구 레벨만 있음 (10자리 모두 채움 못함) | **검토 대상** |
| `address_text_match` | 코드 없이 문자열 매칭 | 정상 |
| `address_text_review` | 문자열 매칭 검토 필요 (불완전 매칭) | **검토 대상** |
| `provider_address_mismatch` | 좌표 기준 kor-travel-geo 주소와 provider 주소가 다른 장소로 보임 | **검토 대상** |
| `provider_address_partial_match` | 동/시군구는 맞지만 상세 주소가 불완전하거나 다름 | **검토 대상** |
| `address_text_only` | 좌표/geocoder 없이 문자열만 있음 | **검토 대상** |
| `coordinate_only` | 주소 문자열 없이 좌표 결과만 | 정상 |
| `address_geocode_legal_dong` | 정지오코딩 결과에서 좌표/법정동 보강 | 정상 |
| `not_geocoded` | 좌표/주소 단서가 있지만 kor-travel-geo 결과 없음 또는 resource 없음 | **검토 대상** (운영 설정/데이터 문제) |
| `no_address` | 주소·좌표 모두 없음 | **검토 대상** |

운영 검토 대상은 `ops.data_integrity_violations`에 기록 옵션 +
admin `/admin/integrity` 페이지에 노출.

## 7. 사용 패턴

### 7.1 collect 단계 (provider 변환 시)

```python
# providers/visitkorea.py
async def festival_to_bundles(items, *, fetched_at, reverse_geocoder=None):
    for item in items:
        # 1. provider 응답은 raw/provenance. 저장 정본은 kor-travel-geo 결과.
        base_address = Address(
            display_address=f"{item.addr1} {item.addr2 or ''}".strip(),
            code_set=AddressCodeSet(legal_dong_code=None, ...),
        )
        coord = _coord_from_visitkorea(item)
        
        # 2. 좌표가 있으면 좌표 기준 reverse가 정본.
        if coord and reverse_geocoder:
            enrichment = await enrich_address_from_coordinate(
                coord=coord, base_address=base_address,
                reverse_geocoder=reverse_geocoder,
            )
            address = enrichment.address
            address_report = enrichment.report
        # 3. 좌표가 없고 주소가 있으면 geocode -> reverse로 정규화.
        elif base_address.display_address and address_geocoder and reverse_geocoder:
            coord = await address_geocoder(base_address)
            if coord:
                enrichment = await enrich_address_from_coordinate(
                    coord=coord, base_address=base_address,
                    reverse_geocoder=reverse_geocoder,
                )
                address = enrichment.address
                address_report = enrichment.report
            else:
                address = base_address
                address_report = AddressMatchReport(
                    match_level="not_geocoded",
                    source_legal_dong_code=None,
                    geocoded_legal_dong_code=None,
                    provider_address=base_address.display_address,
                    normalized_address=None,
                )
        else:
            address = base_address
            address_report = AddressMatchReport(
                match_level="not_geocoded" if coord or base_address.display_address else "no_address",
                source_legal_dong_code=None, geocoded_legal_dong_code=None,
                provider_address=base_address.display_address,
                normalized_address=None,
            )
        
        yield FeatureBundle(
            feature=Feature(
                feature_id=...,
                kind=FeatureKind.EVENT,
                name=item.title,
                coord=coord,
                address=address,
                ...
            ),
            ...
        )
```

### 7.2 load_feature_rows 단계 (DB 적재 시)

본 라이브러리의 공통 적재 함수는 resource를 받아 자동 보강:

```python
from kortravelmap import load_feature_rows

await load_feature_rows(
    async_session,
    feature_items=feature_bundles,
    source_record_items=...,
    geocoder_resource={
        "kor_travel_geo_base_url": settings.kor_travel_geo_base_url,   # REST 서비스 URL
    },
)
```

내부 처리:
1. resource에서 `reverse_geocoder` callable 생성
2. 각 `Feature`의 `coord`가 있고 `address.legal_dong_code` 없으면 reverse 호출
3. 결과를 `features.address`, `features.legal_dong_code` 등에 반영
4. `AddressMatchReport`는 `features.detail.address_enrichment`에 저장
5. **`feature_id`는 재계산하지 않는다** — provider normalize 단계에서 정해진
   값을 따른다 (ADR-009 결정성 보장)

## 8. provider별 reverse geocoder 사용 표

| provider | 좌표 출처 | reverse geocoder 권장 |
|----------|---------|---------------------|
| VisitKorea | mapx/mapy (WGS84) | 권장 — areaCode가 표준 코드 아님 |
| MOIS | EPSG:5174 → WGS84 변환 | **필수** — sigun_code가 관할기관 코드 |
| OpiNet | KATEC EPSG:5181 → WGS84 변환 | **필수** — sigun_code가 OpiNet 코드 |
| KHOA beach | lat/lon (WGS84) | 권장 — sidoNm/gugunNm 한글 |
| krheritage | longitude/latitude (WGS84, GIS에서) | 권장 |
| krforest | 위경도 (WGS84) | 권장 |
| krex | 위경도 (WGS84) | 권장 |
| standard_data | 위경도 (WGS84, 표준데이터별) | 권장 |
| KMA weather | 격자 (nx, ny) — 좌표 변환 별도 | 적용 X (관측소 좌표는 별도 reference) |
| 전화번호 보강 | (좌표 안 다룸) | 적용 X |

## 9. 운영시간 (Opening hours) — 본 도큐먼트 외

상세는 `docs/architecture/feature-opening-hours.md`. 본 도큐먼트에서는 주소/좌표만.

## 10. 운영 검토 워크플로

```sql
-- 일 1회 정합성 검토 (T-201 feature_consistency_reports 케이스 F1)
SELECT 
  f.feature_id, f.name, f.legal_dong_code,
  f.detail->'address_enrichment'->>'match_level' AS match_level,
  f.detail->'address_enrichment'->>'notes' AS notes
FROM feature.features f
WHERE f.detail->'address_enrichment'->>'match_level' IN (
  'legal_dong_conflict', 'sigungu_code_only', 'address_text_review',
  'not_geocoded'
)
ORDER BY f.updated_at DESC
LIMIT 100;
```

운영자는 `/admin/integrity` 페이지에서 위 결과 확인 → 필요 시
`ops.feature_overrides`로 보정 (`docs/architecture/data-model.md` §9.3).

## 11. enrich_address_from_coordinate 헬퍼

```python
async def enrich_address_from_coordinate(
    *,
    coord: Coordinate,
    base_address: Address,
    reverse_geocoder: ReverseGeocoder,
) -> AddressEnrichment:
    """좌표 + 기존 Address → 보강된 Address + AddressMatchReport."""
    geocoded = await reverse_geocoder(coord)
    if geocoded is None:
        return AddressEnrichment(
            address=base_address, geocoded_address=None, coordinate=coord,
            report=AddressMatchReport(
                match_level="coordinate_only" if not base_address.display_address
                            else "address_text_only",
                source_legal_dong_code=base_address.code_set.legal_dong_code,
                geocoded_legal_dong_code=None,
            ),
        )
    return _merge_addresses(base_address, geocoded, coord)
```

`_merge_addresses`가 match_level을 계산하면서 두 Address를 합친다 (구체
구현은 코드 작성 단계).

## 12. VWorld / juso / epost 경계

본 라이브러리는 vworld/juso/epost API를 직접 호출하지 않는다. 모두
`kor-travel-geo` REST 서비스 내부에서 처리:

```
[kor-travel-map]
  ↓ ReverseGeocoder callable 호출
[httpx.AsyncClient → kor-travel-geo REST]   POST /v2/reverse · POST /v2/geocode
  ├─ 1차: 로컬 PostGIS (도로명주소 전자지도)
  ├─ 2차: vworld API fallback (선택)
  ├─ 3차: juso API fallback (선택)
  └─ 4차: epost API fallback (선택)
```

API 키/한도/재시도는 `kor-travel-geo` REST 서비스 책임. 본 라이브러리는 REST 응답만 신뢰.

## 13. 테스트

- 단위: Fake reverse_geocoder로 `enrich_address_from_coordinate`의
  match_level branch 전수 검증 (`tests/unit/test_geocoding.py`).
  REST 클라이언트는 `httpx.MockTransport`로 서버 없이 GET 요청 params + JSON
  파싱 + 변환 검증 (PR#90 test_geocoding 21건).
- 통합: 실제 `kor-travel-geo` REST 서비스 인스턴스 (docker compose 등) → 좌표 →
  Address 보강 시나리오.
- fixture: provider별 fixture에 `address_enrichment` snapshot 포함.

## 14. 운영 체크리스트

- [ ] `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL` 환경변수 (REST 서비스 URL)
- [ ] `kor-travel-geo` REST 서비스 v2(`POST /v2/reverse`, `POST /v2/geocode`)가 운영 환경에서 reachable
- [ ] reverse geocoder가 MOIS/OpiNet ETL에 주입되어 있는가
- [ ] `legal_dong_conflict` / `sigungu_code_only` / `not_geocoded` 비율
      모니터링 (Grafana panel)
- [ ] VWorld API 키 회전 시 `kor-travel-geo` REST 서비스 재설정 (본 lib는 무관)
