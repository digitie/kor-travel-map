# address-geocoding.md — 주소·좌표 보강

본 문서는 feature 주소/좌표를 본 라이브러리 `Address` DTO로 정리하고, 필요 시
`python-kraddr-geo` 기반 정/역지오코딩으로 보강하는 패턴이다.

**ADR-041 (2026-05-27)** — 주소 DTO + utility는 `python-kraddr-base`에서
본 라이브러리로 흡수. 외부 의존 1개 제거.

## 1. 의존 라이브러리

- 주소 DTO: **`krtour.map.dto.Address`** (PR#37, ADR-041 — kraddr-base 흡수).
  보강 필드: bjd_code / admin_dong_code / sigungu_code / sido_code /
  road_name_code / road_address_management_no / zipcode / sido_name /
  sigungu_name.
- 좌표 DTO: **`krtour.map.dto.Coordinate`** (`PlaceCoordinate` 명시적 제외).
- 주소 normalize / 행정코드 parse: **`krtour.map.core.address`** (PR#37) —
  `normalize_bjd_code` / `parse_bjd_code` / `extract_sigungu_code` /
  `extract_sido_code` / `normalize_phone_number` / `normalize_korean_text`.
- geocoding 엔진: `python-kraddr-geo` (`kraddr.geo.AsyncAddressClient`) — 별도
  라이브러리 (흡수 대상 아님).
- VWorld 폴백 키: `python-kraddr-geo` 내부 store 설정에서만. 본 라이브러리에서
  `python-vworld-api` 직접 import 금지.

## 2. 핵심 callable

```python
from typing import Awaitable, Callable

from krtour.map.dto import Address, Coordinate

# 정지오코딩: 주소 문자열 + 코드 → 좌표
AddressGeocoder = Callable[[Address], Awaitable[Coordinate | None]]

# 역지오코딩: 좌표 → 행정구역 코드가 있는 Address
ReverseGeocoder = Callable[[Coordinate], Awaitable[Address | None]]
```

provider 변환 모듈은 이 위에 동기 `Protocol` 변종을 따로 두기도 한다 — 예:
`krtour.map.providers.standard_data.ReverseGeocoder` (PR#34).

async-only (ADR-002). resource dataclass:

```python
@dataclass(frozen=True)
class GeocoderResources:
    address_geocoder: AddressGeocoder | None = None
    reverse_geocoder: ReverseGeocoder | None = None
```

## 3. resource 자동 생성

resource dict에 `kraddr_geo_store` 또는 `kraddr_geo_database_path`가 있으면 본
라이브러리가 callable을 자동 생성한다.

```python
from krtour.map.geocoding import (
    kraddr_geo_reverse_geocoder,
    kraddr_geo_address_geocoder,
)

reverse = kraddr_geo_reverse_geocoder(
    database_path="data/juso/kraddr_geo.sqlite",
    store_kwargs={
        "vworld_api_key": "...",
        "vworld_domain": "...",
    },
)
```

helper는 내부적으로 `AsyncAddressClient`를 lazy 생성. caller는 dispose 책임.

## 4. 코드 변환 기준

| 원천 코드 | 본 라이브러리 저장 기준 |
|----------|----------------------|
| `legal_dong_code`, `admCd` (10자리) | 그대로 `features.legal_dong_code` |
| `roadAddrMgtNo` (25자리) | `features.road_address_management_no`. 법정동코드 파생 가능하면 함께 저장 |
| `sggCd` (5자리), 시군구 코드 | 시군구 레벨 법정동 표현 `1111000000` 형태. match_level=`sigungu_code_only` |
| VisitKorea `areaCode`/`sigunguCode` | provider 코드 — `raw_data`/`payload`에만 보존. 법정동코드로 저장 X. 좌표 reverse geocoding으로 확정 |
| OpiNet `sigun_code` | 동일 — `raw_data`/`payload`에만. 좌표 reverse geocoding으로 확정 |
| MOIS 관할기관 코드 | `payload`에만 |

**철칙**: 주소 문자열만으로 `legal_dong_code` 추정 금지. reverse geocoder 없이는
`null`로 둔다.

## 5. AddressEnrichment + AddressMatchReport

```python
@dataclass(frozen=True)
class AddressEnrichment:
    address: Address                       # 보강된 최종 Address (caller가 사용)
    geocoded_address: Address | None       # reverse geocoder 결과 raw
    coordinate: PlaceCoordinate | None     # 정/역지오코딩으로 얻은 좌표
    report: AddressMatchReport             # 매칭 수준 + 사유
```

```python
@dataclass(frozen=True)
class AddressMatchReport:
    match_level: str
    source_legal_dong_code: str | None
    geocoded_legal_dong_code: str | None
    notes: list[str] = field(default_factory=list)
```

## 6. `match_level` 카탈로그

| `match_level` | 의미 | 운영 검토 |
|--------------|------|----------|
| `legal_dong_exact` | 원천 법정동코드와 좌표 reverse geocoding 결과 일치 | 정상 |
| `coordinate_legal_dong` | 원천 코드 없고 좌표로 채움 | 정상 |
| `legal_dong_conflict` | 원천 코드와 좌표 결과 충돌 | **검토 대상** |
| `source_legal_dong` | 원천 법정동코드를 그대로 사용 (reverse geocoder 미사용) | 정상 |
| `provider_code_converted` | 도로명주소관리번호 등으로 파생 | 정상 |
| `sigungu_code_only` | 시군구 레벨만 있음 (10자리 모두 채움 못함) | **검토 대상** |
| `address_text_match` | 코드 없이 문자열 매칭 | 정상 |
| `address_text_review` | 문자열 매칭 검토 필요 (불완전 매칭) | **검토 대상** |
| `address_text_only` | 좌표/geocoder 없이 문자열만 있음 | 정상 (제한적) |
| `coordinate_only` | 주소 문자열 없이 좌표 결과만 | 정상 |
| `address_geocode_legal_dong` | 정지오코딩 결과에서 좌표/법정동 보강 | 정상 |
| `not_geocoded` | 좌표 있지만 reverse geocoder resource 없음 | **검토 대상** (운영자 누락) |
| `no_address` | 주소·좌표 모두 없음 | 정상 (제한적) |

운영 검토 대상은 `ops.data_integrity_violations`에 기록 옵션 +
admin `/admin/integrity` 페이지에 노출.

## 7. 사용 패턴

### 7.1 collect 단계 (provider 변환 시)

```python
# providers/visitkorea.py
async def festival_to_bundles(items, *, fetched_at, reverse_geocoder=None):
    for item in items:
        # 1. provider 응답으로 기본 Address 구성
        base_address = Address(
            display_address=f"{item.addr1} {item.addr2 or ''}".strip(),
            code_set=AddressCodeSet(legal_dong_code=None, ...),
        )
        coord = _coord_from_visitkorea(item)
        
        # 2. 좌표 있고 reverse geocoder 있으면 보강
        if coord and reverse_geocoder:
            enrichment = await enrich_address_from_coordinate(
                coord=coord, base_address=base_address,
                reverse_geocoder=reverse_geocoder,
            )
            address = enrichment.address
            address_report = enrichment.report
        else:
            address = base_address
            address_report = AddressMatchReport(
                match_level="not_geocoded" if coord else "address_text_only",
                source_legal_dong_code=None, geocoded_legal_dong_code=None,
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
from krtour.map import load_feature_rows

await load_feature_rows(
    async_session,
    feature_items=feature_bundles,
    source_record_items=...,
    geocoder_resource={
        "kraddr_geo_database_path": settings.kraddr_geo_database_path,
        "kraddr_geo_store_kwargs": settings.kraddr_geo_store_kwargs,
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

상세는 `docs/feature-opening-hours.md`. 본 도큐먼트에서는 주소/좌표만.

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
`ops.feature_overrides`로 보정 (`docs/data-model.md` §9.3).

## 11. enrich_address_from_coordinate 헬퍼

```python
async def enrich_address_from_coordinate(
    *,
    coord: PlaceCoordinate,
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
`python-kraddr-geo` 내부에서 처리:

```
[python-krtour-map]
  ↓ ReverseGeocoder callable 호출
[python-kraddr-geo] AsyncAddressClient
  ├─ 1차: 로컬 PostGIS (도로명주소 전자지도)
  ├─ 2차: vworld API fallback (선택)
  ├─ 3차: juso API fallback (선택)
  └─ 4차: epost API fallback (선택)
```

API 키/한도/재시도는 `python-kraddr-geo` 책임.

## 13. 테스트

- 단위: Fake reverse_geocoder로 `enrich_address_from_coordinate`의
  match_level branch 전수 검증 (`tests/unit/test_geocoding.py`).
- 통합: 실제 `AsyncAddressClient` + 소량 SQLite store → 좌표 → Address
  보강 시나리오.
- fixture: provider별 fixture에 `address_enrichment` snapshot 포함.

## 14. 운영 체크리스트

- [ ] `python-kraddr-geo` git sha 핀
- [ ] `KRTOUR_MAP_KRADDR_GEO_PG_DSN` 또는 SQLite path 환경변수
- [ ] reverse geocoder가 MOIS/OpiNet ETL에 주입되어 있는가
- [ ] `legal_dong_conflict` / `sigungu_code_only` / `not_geocoded` 비율
      모니터링 (Grafana panel)
- [ ] VWorld API 키 회전 시 `python-kraddr-geo` store 재설정
