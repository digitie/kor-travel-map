# tripmate-integration.md — TripMate와 kor-travel-map OpenAPI 연동

> **ADR-045 supersede 안내 (2026-06-01)**:
> 본 문서의 예전 본문에는 TripMate가 `kor-travel-map`을 직접 import하고 같은
> process에서 `AsyncKorTravelMapClient`를 호출하는 패턴이 남아 있다. 그 운영 모델은
> ADR-045로 supersede됐다. 현재 기준은 다음이다.
>
> - kor-travel-map은 Docker에서 실행되는 독립 프로그램이다.
> - kor-travel-map은 독립 PostgreSQL/PostGIS DB와 독립 Dagster를 가진다.
> - TripMate는 kor-travel-map DB에 직접 접근하지 않는다.
> - TripMate는 `kor-travel-map`을 운영 코드에서 직접 import하지 않는다.
> - TripMate는 kor-travel-map OpenAPI client로 feature 조회와 batch 조회를 호출한다.
>   Feature update request는 `/admin/feature-update-requests*` 운영 표면으로 이동했으며,
>   TripMate 사용자 제안 큐는 TripMate app DB가 소유한다.
> - OpenAPI는 우선 admin UI 기준으로 작성하고, TripMate 연동 시 필요한 공개 API를
>   보완·확장한다.
>
> 아래 "직접 import" 예시는 ADR-045 이전 legacy 참고 자료다. 새 구현은
> `docs/openapi-admin-contract.md`를 우선한다.

## 0. 현재 표준: OpenAPI 연동

TripMate 연동의 현재 표준 흐름:

```
TripMate API/Web
  → generated kor-travel-map OpenAPI client
  → kor-travel-map API (`/v1/features/in-bounds`, `/v1/features/{id}`, `/v1/features/batch`)
  → kor-travel-map 독립 DB/Dagster
```

초기 TripMate 후보 API:

| API | 목적 |
|-----|------|
| `GET /v1/features/in-bounds` | bbox 기반 지도 feature 조회 |
| `GET /v1/features/{feature_id}` | feature 상세 |
| `GET /v1/features/search` | 이름/bbox 기반 feature 검색 |
| `GET /v1/features/nearby/by-target` | 외부 POI/cache target key 기준 주변 feature 조회 |
| `POST /v1/features/batch` | 여러 feature_id batch 상세 조회 (service read, `ServiceToken`; 구 `/tripmate/features/batch` 폐지) |
| `/admin/feature-update-requests*` | 운영자 승인 후 특정 feature/좌표 반경/시군구/provider 업데이트 큐잉 |
| `GET /ops/import-jobs/{job_id}` | 실제 Dagster/import job progress |

후속 후보는 `docs/reports/tripmate-requirements-reconcile-2026-06-06.md`와
`docs/tasks.md` `T-213a~h`를 따른다. 특히 일반 좌표 기준 `/features/nearby`,
provider last-sync, public `/health`/`/version`, weather card, category catalog는
현재 user OpenAPI에 포함되어 있으며, 목표 안정 계약은
`docs/tripmate-rest-api.md`의 `/v1` 경로 정리를 따른다.

예: 특정 좌표 중심 반경 5km 안 feature 업데이트 요청.

```http
POST /admin/feature-update-requests
Content-Type: application/json

{
  "scope": {
    "type": "center_radius",
    "center": {"lon": 126.978, "lat": 37.5665},
    "radius_km": 5.0
  },
  "providers": [],
  "dataset_keys": [],
  "update_policy": {
    "mode": "refresh_existing",
    "force_provider_call": true,
    "dedup_after_load": true,
    "consistency_check_after_load": true
  },
  "run_mode": "queued",
  "dry_run": false,
  "operator": "tripmate-admin",
  "reason": "사용자 신고 지역 데이터 갱신"
}
```

예: TripMate POI를 cache target으로 등록. 좌표만으로 식별하지 않고
`target_key`를 함께 보낸다.

```http
PUT /admin/poi-cache-targets/tripmate/poi_123
Content-Type: application/json

{
  "coord": {"lon": 126.978, "lat": 37.5665},
  "coord_precision_digits": 6,
  "radius_km": 5.0,
  "scope_mode": "center_radius",
  "update_enabled": true,
  "refresh_policy": "provider_default",
  "on_conflict": "reject"
}
```

예: 여러 POI key를 기준으로 주변 캐시 갱신을 큐잉. 반경이 겹치는 feature/provider
scope는 kor-travel-map이 dedup해 한 번만 업데이트한다.

```http
POST /admin/feature-update-requests
Content-Type: application/json

{
  "scope": {
    "type": "cache_target_keys",
    "external_system": "tripmate",
    "target_keys": ["poi_123", "poi_456"],
    "radius_km": 5.0,
    "scope_mode": "center_radius"
  },
  "run_mode": "queued",
  "dry_run": false,
  "operator": "tripmate",
  "reason": "저장 POI 주변 캐시 갱신"
}
```

예: POI key 기준 주변 feature summary 조회. 목록 응답에는 detail JSON/raw payload가
포함되지 않고 `last_updated_at`은 항상 포함된다.

```http
GET /features/nearby/by-target?external_system=tripmate&target_key=poi_123&radius_km=5
```

예: 특정 좌표 중심 반경 10km와 교차하는 시군구의 feature 업데이트 dry-run.

```http
POST /admin/feature-update-requests
Content-Type: application/json

{
  "scope": {
    "type": "sigungu_by_radius",
    "center": {"lon": 126.978, "lat": 37.5665},
    "radius_km": 10.0,
    "match": "intersects"
  },
  "run_mode": "queued",
  "dry_run": true,
  "operator": "tripmate-admin",
  "reason": "대상 시군구 산정"
}
```


## 1. TripMate 책임 경계

TripMate는 kor-travel-map을 Python package로 import하지 않는다. 운영 연동은 생성된
OpenAPI client를 통해 HTTP로만 수행한다. TripMate가 보유하는 것은 사용자/여행계획/POI
도메인과, 저장 POI를 kor-travel-map cache target으로 등록·삭제·조회하는 호출 코드다.

TripMate가 직접 소유하는 항목:

- 사용자 인증/인가, 여행계획, 저장 POI, 사용자 UI.
- kor-travel-map OpenAPI client 생성물과 타입 검증 계층.
- POI 생성·수정·삭제 시 cache target write 경로 호출. 현재 구현은
  `PUT/DELETE /admin/poi-cache-targets/{external_system}/{target_key}`이며, TripMate
  직접 write를 허용할지는 `docs/tripmate-rest-api.md`의 `T-214f` 결정에 따른다.
- 저장 POI 기준 주변 feature 조회 시 `GET /features/nearby/by-target` 호출.
- 사용자 흐름에서 필요한 feature 상세 조회 시 `GET /features/{feature_id}` 호출.

kor-travel-map이 직접 소유하는 항목:

- feature 정규화, provider 호출, dedup, consistency, 주소 정본화.
- 독립 PostgreSQL/PostGIS DB, RustFS/object store, Dagster 자산/스케줄/큐.
- provider별 rate limit, refresh interval, cache target과 provider scope의 교집합 dedup.
- admin/operator UI와 OpenAPI schema export.

## 2. TripMate 호출 규약

TripMate는 좌표만으로 POI를 식별하지 않는다. 같은 위치라도 좌표 정밀도 차이와 POI 생명주기
차이가 있으므로 항상 `external_system` + `target_key`를 함께 보낸다. kor-travel-map은 이 값을
cache target의 영속 키로 사용하고, 동일 좌표·동일 유효 자리수에서는 좌표와 키가 1:1로
매핑되도록 검증한다.

POI 삭제 시 TripMate는 cache target도 삭제해야 한다. 삭제된 key는 더 이상 provider update
scope 산정에 참여하지 않으며, 기존 feature 자체는 provider 데이터와 retention 정책에 따라
유지·비활성화·삭제된다.

## 3. 금지

- TripMate 운영 코드에서 `from kortravelmap import ...` 직접 import 금지.
- TripMate가 kor-travel-map DB 또는 Dagster DB에 직접 접속 금지.
- TripMate `apps/etl`에서 kor-travel-map provider 적재 asset을 소유 금지.
- legacy package/path/env 이름을 위한 호환 shim 추가 금지.
- 목록 API에서 feature 상세 JSON/raw payload를 반환 금지. 상세 JSON은
  `GET /features/{feature_id}` 계열에서만 반환한다.
