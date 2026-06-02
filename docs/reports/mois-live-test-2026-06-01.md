# MOIS 실데이터 라이브 테스트 리포트 (2026-06-01)

Sprint 4a MOIS Step A 파이프라인(변환 → 적재 → snapshot prune)을 **행정안전부
LOCALDATA 실데이터**로 end-to-end 검증한 결과.

## 1. 환경

| 항목 | 값 |
|------|----|
| provider 라이브러리 | `python-mois-api` (`import mois`), 체크아웃 `~/dev/python-krmois-api` |
| 데이터 소스 | `file.localdata.go.kr` 파일 다운로드 (`LocalDataFileClient`) — **서비스키 불필요** |
| 서비스키 위치 | `F:\dev\python-krmois-api\.env` → `DATA_GO_KR_SERVICE_KEY` (OpenAPI `MoisClient`용; 파일 다운로드 경로는 미사용) |
| 실행 | WSL ext4 `~/dev/python-krtour-map`, `PYTHONPATH=~/dev/python-krmois-api/src` |
| 적재 | testcontainers `postgis/postgis:16-3.5-alpine`, alembic 0001~0006 |

## 2. 변환 검증 (다운로드 → PlaceRecord → krtour bundles)

흐름: `LocalDataFileClient.download_bytes(slug)` → `iter_records_from_binary` →
`PlaceRecord.from_local_data_record` → `krtour.map.providers.mois.license_records_to_bundles`.

| slug | 다운로드 | 영업중 | 변환 bundles | category (기대) | place_kind (기대) | 좌표 보유 | 결과 |
|------|---------|--------|-------------|------------------|--------------------|-----------|------|
| `bakeries` | 68,800 (22.4MB) | 19,913 | 2,000 | `02011000` ✓ | `bakery` ✓ | 1965/2000 | OK |
| `traditional_temples` | — | 500+ | 500 | `01070100` ✓ | `temple_traditional` ✓ | 415/500 | OK |
| `public_baths` | — | 500+ | 500 | `04020100` ✓ | `public_bath` ✓ | 497/500 | OK |
| `museums_and_art_galleries` | — | 500+ | 500 | `01040000` ✓ | `museum_art_gallery` ✓ | 466/500 | OK |
| `pet_grooming` (EXCLUDED) | — | 200 | **0** (skip) | — | — | — | OK skip |

- 4개 PROMOTED 슬러그의 category/place_kind 매핑이 실데이터에서 docs §6.1과 100% 일치.
- EXCLUDED 슬러그(`pet_grooming`)는 영업중 200건 입력에도 변환 0건 — skip 정상.
- 좌표는 mois가 EPSG:5174 → WGS84 변환한 `lon`/`lat`을 그대로 사용 (예: 종로구
  '원더쿠키' = 126.985, 37.579). `Coordinate` 한국 경계 검증 통과.

## 3. 적재 검증 (실데이터 → PostGIS)

`sync_mois_license_features_bulk`로 `public_baths` 영업중 300건을 testcontainers
PostGIS에 streaming 적재(batch_size=100) → 재조회.

- 적재: `bundles_total=300`, `features_inserted=300`, `deactivated=0`.
- 재조회: `feature.features` 300행(좌표 보유 298), `provider_sync.source_records`
  300행(`provider='python-mois-api'`).
- 샘플 '대호대중사우나' → category `04020100`, 좌표 (126.973, 37.573),
  **`coord_5179` STORED generated column SRID = 5179** (ADR-012 ST_Transform 정상).
- alembic 0001~0006 전부 적용 (`ops.import_jobs` 포함).

## 4. 발견 — 데이터 정합성 (버그 아님, 소스 특성)

**파일 다운로드 경로(`file.localdata.go.kr`)의 CSV에는 법정동코드 컬럼이 없다.**

- `bakeries` raw record의 행정코드 관련 컬럼 = `OPN_ATMY_GRP_CD`(개방자치단체코드)
  뿐. `LEGAL_DONG_CD`/`BJD_CD`/`ADM_CD`는 부재 → `PlaceRecord.legal_dong_code`가
  전부 `None`.
- 결과: reverse_geocoder 미주입 시 모든 feature가 `make_feature_id`의 `'global'`
  bucket(`f_global_p_*`)에 들어간다 (bjd_code 0/2000).
- **본 lib는 이미 이를 대비** — `legal_dong_code` 부재 시 좌표 reverse geocoding으로
  bjd_code를 보강(ADR-009). 좌표 보유율이 높으므로(96~99%) geocoder만 주입하면
  대부분 실제 법정동 bucket으로 들어간다.
- **운영 권고**: MOIS Step A bulk 적재는 `reverse_geocoder`(kraddr-geo REST) **주입
  필수**. OpenAPI(`MoisClient`, `DATA_GO_KR_SERVICE_KEY`) 경로가 법정동코드를
  제공하는지는 별도 확인 대상(파일 경로와 컬럼셋이 다를 수 있음).
- `opn_authority_code`는 법정동코드가 아니므로 bjd로 쓰지 않음(payload 보존) — 코드
  동작 확인됨.

## 5. geocoder 보강 라이브 재검증 (2026-06-01 후속, ✅ 완료)

§4의 "법정동코드 부재 → geocoder 보강 필수"를 **kraddr-geo REST 실연동**으로 검증.
kraddr-geo FastAPI(`127.0.0.1:9001`, `GET /v1/address/reverse`, `structure.level4LC`
= 법정동코드 10자리) + 자체 PostGIS 주소 마스터 기동 상태.

흐름: `bakeries` 영업중 + 좌표O + `legal_dong_code=None` 200건 →
`KraddrGeoRestClient`(httpx 주입) → `kraddr_geo_reverse_geocoder` →
`cached_reverse_geocoder` → `license_records_to_bundles(reverse_geocoder=...)`.

| 조건 | bjd_code 보유 | `f_global_*` |
|------|--------------|-------------|
| geocoder 미주입 | 0/200 | 200 |
| **geocoder 주입** | **200/200 (100%)** | **0** |

- 샘플: '원더쿠키' → bjd `1111014700`(재동), sigungu `11110`(종로구), sido `11`,
  admin `가회동`, feature_id `f_1111014700_p_*` (실제 법정동 bucket).
- 결론: §4의 설계상 예측(geocoder 주입 시 대부분 보강)이 실데이터로 **100% 확인**.
  좌표 보유 record는 geocoder 주입만으로 `'global'` bucket을 완전히 벗어남.
- 주의: `KraddrGeoRestClient(base_path='/v1')`가 prefix를 붙이므로 httpx
  ``base_url``은 ``http://host:9001``(``/v1`` 미포함)로 줘야 한다(중복 방지).

## 6. 미검증 (후속)

- **OpenAPI 경로**(`MoisClient` + `DATA_GO_KR_SERVICE_KEY`): 법정동코드 제공 여부 +
  rate limit 확인.
- **전체 슬러그 bulk**: 42 PROMOTED 슬러그 × 시군구 = 수십만~수백만 row 적재 시간/
  메모리 (off-peak, advisory lock 단일 워커).
- **좌표 미보유 record**(1~4%): 좌표가 없으면 reverse geocoding도 불가 →
  `'global'` bucket 잔존. 주소 문자열 기반 forward geocoding
  (`kraddr_geo_address_geocoder`) 병행 검토.

## 7. 결론

Sprint 4a MOIS Step A 파이프라인(변환·적재·5179 generated·snapshot·**geocoder
보강**)이 **실데이터로 정상 동작**함을 확인. category/place_kind 매핑·EXCLUDED
skip·좌표 변환·PostGIS 적재·법정동 보강 모두 검증됨. 파일 다운로드 경로의
법정동코드 부재는 kraddr-geo geocoder 주입으로 실연동 100% 해소됨.
