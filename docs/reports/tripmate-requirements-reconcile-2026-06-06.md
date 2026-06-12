# TripMate kor-travel-map 요구사항 대조 — 2026-06-06

TripMate `docs/kor-travel-map-requirements.md`를 현재 kor-travel-map `origin/main`
(`ae67a88`, PR#232 머지 이후)과 대조한 결과다. TripMate 문서의 kor-travel-map 기준선은
`b775c74`라서 ADR-045 독립 프로그램화, `kor-travel-map-admin` rename, user OpenAPI 분리,
feature update request 큐 구현 이전 상태가 상당 부분 남아 있다.

따라서 이 리포트는 TripMate 문서의 K-1~K-14를 그대로 백로그로 복사하지 않고, 현재
코드와 문서 정본(`docs/tripmate-rest-api.md`, `packages/kor-travel-map-admin/openapi.user.json`)
기준으로 **이미 충족된 항목**, **부분 충족 항목**, **새 task로 남길 항목**을 나눈다.

## 현재 user OpenAPI 표면

`packages/kor-travel-map-admin/openapi.user.json`의 현재 path:

| Path | 상태 |
|------|------|
| `GET /features/in-bounds` | 구현 |
| `GET /features/{feature_id}` | 구현 |
| `GET /features/search` | 구현 |
| `GET /features/nearby/by-target` | 구현 |
| `POST /tripmate/features/batch` | 구현 |
| `POST /tripmate/feature-update-requests` | 구현 |
| `GET /tripmate/feature-update-requests/{request_id}` | 구현 |

구현 표면은 OpenAPI HTTP 모델이다. TripMate 운영 코드가 `kor-travel-map`을 직접
import하거나 kor-travel-map DB/Dagster DB에 직접 접속하는 구 모델은 ADR-045/046 기준으로
다시 만들지 않는다.

## 요구사항 대조표

| TripMate 항목 | 현재 판단 | 후속 task |
|---------------|-----------|-----------|
| K-1 bbox 조회 `features_in_bounds` | repo/client/HTTP/user spec 구현됨. 다만 `zoom`/`cluster_unit`은 계약만 있고 서버 집계는 미구현이다. | `T-213c` |
| K-2 단건 상세 `get_feature` | client/HTTP 구현됨. 공개 응답은 D-7 정제 필드 기준. | 없음 |
| K-3 일반 좌표 반경 조회 `features_nearby` | 외부 POI/cache target 기준 `/features/nearby/by-target`만 구현됨. 사용자 현재 위치처럼 raw `lon/lat/radius_m`을 받는 endpoint/repo/client는 없다. | `T-213b` |
| K-4 feature batch 조회 | HTTP `POST /tripmate/features/batch`와 repo `get_feature_rows_by_ids`는 구현됨. 내부 `AsyncKorTravelMapClient.get_features` 공개 메서드는 아직 없다. | `T-213d` |
| K-5 텍스트 검색 | HTTP `GET /features/search`와 repo `search_features`는 구현됨. 내부 `AsyncKorTravelMapClient.search_features` 공개 메서드는 아직 없다. | `T-213d` |
| K-6 날씨 카드 | `core.weather` 순수 helper와 KMA weather value 변환은 있으나 feature 상세용 DB 조회/API 카드 조립은 아직 없다. | `T-213e` |
| K-7 category catalog export | `kortravelmap.category` 정적 카탈로그 144건은 구현됨. HTTP `GET /categories`, runtime feature count, Python/TS marker drift gate는 남아 있다. | `T-213f` |
| K-8 feature update request | `ops.feature_update_requests`, repo/client, admin REST, TripMate/user REST(`/tripmate/feature-update-requests*`), Dagster sensor/job 연결이 구현됨. | 없음 |
| K-9 dedup merge/정합성 | `merge_dedup_review`, `/admin/dedup-review`, `/ops/consistency/*`가 있다. `/admin/issues` write/action과 admin 응답 envelope 통일은 이미 T-212/T-DA 후속으로 잡혀 있다. | `T-212b/c`, `T-DA-15/16` |
| K-10 `knps`/`krheritage` provider re-export | provider 모듈은 있으나 `kortravelmap.providers.__init__` package-level export는 없다. | `T-213g` |
| K-11 sync state write helper | `infra.sync_state_repo`에는 read/write helper가 있으나 `AsyncKorTravelMapClient`와 user/admin last-sync API 표면이 없다. | `T-213g` |
| K-12 healthz public | `/debug/health`, `/debug/version`만 있다. TripMate liveness용 `/health`, `/version`, deep health는 user spec에 없다. | `T-213h` |
| K-13 feature_id 포맷 | ADR-009와 `core.ids.make_feature_id`가 `f_{bjd_code}_{kind[0]}_{sha1[:16]}` 포맷을 확정한다. TripMate 쪽 UUID 가정은 TripMate 수정 대상이다. | `T-210b` |
| K-14 운영급 HTTP 서비스 | ADR-045 이후 Docker 독립 프로그램 + API `12301` + admin UI `12305` + Dagster `12302` 모델로 구현 중이다. 생산 운영 hardening은 T-209/T-RV/T-212 범위다. | `T-209b-a`, `T-212` |

## 우선순위

완성도·안정성·확장성·성능을 기준으로 다음 순서를 권장한다.

1. `T-209b-a`: Dagster schedule/run/event storage를 PostgreSQL로 고정해 운영 기반을 먼저
   안정화한다.
2. `T-213b`: raw 좌표 기준 `/features/nearby`를 `coord_5179` + `ST_DWithin` +
   EXPLAIN 회귀 테스트로 구현한다. 사용자 현재 위치/추천 흐름의 핵심 read path다.
3. `T-213d`: HTTP/repo에 이미 있는 batch/search를 `AsyncKorTravelMapClient` read parity로
   맞춘다. API/Dagster 내부 구현이 같은 경로를 재사용할 수 있어 테스트와 유지보수가
   안정된다.
4. `T-213g`/`T-213h`: provider export, sync state, health/version을 운영 관측 표면으로
   정리한다.
5. `T-213c`/`T-213e`/`T-213f`: clustering, weather card, category runtime catalog는
   사용자 경험과 운영 UI 품질을 올리는 후속 확장으로 진행한다.

## 반영 위치

- `docs/tasks.md`: `T-213a`~`T-213h` 백로그 추가.
- `docs/tripmate-rest-api.md`: user spec에 없는 last-sync/health/weather 후속 범위를 task
  ID와 함께 명시.
- `docs/tripmate-integration.md`: 초기 후보 API 표를 현재 path와 후속 path로 정리.
