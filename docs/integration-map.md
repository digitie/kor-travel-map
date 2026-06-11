# integration-map — TripMate 생태계 연동 정본 (T-217d, D-08)

4개 시스템(python-krtour-map · TripMate · tripmate-agent · tripmate-manager)의
포트·연동 방향·인증·envelope·계약 정본 위치를 **한 장**으로 고정한다.
"한쪽 갱신이 타 repo 전제에 전파되지 않는" 구조적 사고(2026-06-10 검토의 DEC-01류)
재발 방지가 목적이다. 분기별 상호 검증 절차는
[`runbooks/cross-repo-audit-checklist.md`](runbooks/cross-repo-audit-checklist.md).

> 본 문서는 **포인터 지도**다 — 계약 세부는 각 정본을 따른다(§4). 충돌 시 기계
> 정본(OpenAPI) > prose 정본 > 본 문서 순.

## 1. 시스템·포트

| 시스템 | 역할 | 로컬 고정 포트 | 근거 |
|---|---|---|---|
| **python-krtour-map** | feature 정본 owner — 공공 API+후보 정규화·dedup·PostGIS 조회 (독립 Docker, ADR-045) | API **9011** · admin UI 9012 · Dagster 9013 · (standalone postgres 15433 · rustfs 9003/9004) | ADR-047 |
| **TripMate** | 사용자 여행 계획/협업/공유 서비스 — feature **consumer** | api **9021** · web 9022 | TripMate README |
| **tripmate-agent** | YouTube 콘텐츠 → 장소 후보 추출/검수 — feature 후보 **provider** | API **9041** · web 9042 | tripmate-agent ADR-23 |
| **tripmate-manager** | 공용 인프라 일괄 관리(docker-compose+Web UI) — 단일 PostGIS·RustFS 소유 | PostGIS **15434**(`kraddr-geo-postgres`) · RustFS S3 **9003**/console 9004 | tripmate-manager README, ADR-052 amendment |
| (보조) kraddr-geo | geocoding REST v2 정본 | **9001** | ADR-046 |

## 2. 연동 방향 (데이터 흐름)

```
[공공 API provider 라이브러리들]──────────────┐
                                              ▼ (krtour Dagster live fetch)
[tripmate-agent :9041] ──(REST export pull)──▶ [python-krtour-map :9011]
   GET /api/v1/features/{snapshot|changes}        feature_id 생성·dedup·정합성
   (krtour Dagster가 주기 pull, ADR-049/050)            │
                                                        │ OpenAPI /v1 (HTTP)
                                                        ▼
                          [TripMate api :9021] ◀──(read: in-bounds/search/nearby/
                            trip·POI·공유·협업          {id}/weather/batch/categories
                                  ▲                     /providers)
                                  │                  ◀──(admin: /v1/admin/features*
                          [TripMate web :9022]          — 사용자 제안 승인 반영, ADR-051)

[tripmate-manager] ═══ 인프라 계층(별도 데이터 흐름 없음): PostGIS(15434)·RustFS(9003) 구동/관리
```

- TripMate ↔ krtour-map: **HTTP만**(라이브러리 import·공유 DB 없음, ADR-045/TripMate ADR-026).
- tripmate-agent → krtour-map: **pull 모델** — agent는 export API만 제공, krtour Dagster가
  가져가 `FeatureBundle`로 소유(ADR-049). `operation=upsert` 적재 /
  `reject`·`tombstone` → 대응 feature `status='inactive'` 전환(ADR-050 #4, T-217b).
- TripMate ↛ tripmate-agent: 직접 연동 없음 — YouTube 후보는 krtour-map feature를 통해서만
  TripMate에 도달한다(tripmate-agent plan §2.2).

## 3. 인증·envelope — 표면별 의도적 차이 (D-08)

통일하지 않는다 — 표면 성격이 다르다. 아래 표가 "왜 다르지" 재논의를 막는 고정값이다.

| 표면 | 인증 | 성공 envelope | 에러 |
|---|---|---|---|
| krtour-map 공용 read (`/v1/features*` GET 등) | 비강제(운영은 인프라 SSO) | `{data, meta}` — `meta.page.next_cursor` | RFC7807 `problem+json`(top-level `code`) |
| krtour-map service read (`POST /v1/features/batch`) | `X-Krtour-Service-Token` | 〃 (`data={found{},missing[]}`) | 〃 |
| krtour-map admin/ops (`/v1/admin/*`·`/v1/ops/*`) | 인프라 SSO/IP allowlist + `admin_destructive_enabled` kill-switch | 〃 | 〃 |
| tripmate-agent export (`/api/v1/features/*`) | `X-API-Key` | **무-envelope** `{items, next_cursor, has_more}` (내부 export 단순 계약) | HTTP status |
| TripMate 자체 API (`:9021`) | 쿠키 세션/OAuth | TripMate 자체 `Envelope` | TripMate 자체 |

좌표는 전 구간 WGS84 평면 `lon`/`lat`(lon-first), bbox는 분리 4-float
`min_lon/min_lat/max_lon/max_lat`(ADR-048 #10 — cross-repo 정본).

## 4. 계약 정본 위치

| 계약 | 정본(공급자 repo) | 소비측 view |
|---|---|---|
| krtour-map 전 표면 REST | `docs/rest-api.md` + 기계 정본 `packages/krtour-map-admin/openapi{,.user}.json` | TripMate `docs/integrations/krtour-map-rest-api.md` / 본 repo `docs/tripmate-rest-api.md`(TripMate 소비 매핑) |
| TripMate T-130 공개 해수욕장/축제 뷰 | 본 repo `docs/public-views-api.md`(제안 사양, 아직 OpenAPI 미포함) | TripMate `docs/api/public.md` / `docs/krtour-map-requirements.md` §6 |
| tripmate-agent feature export | tripmate-agent `docs/youtube-feature-pipeline-plan.md` §7 (→ 독립 계약 문서로 분리 예정, D-04/TA-02) | 본 repo: ADR-049/050 + `providers/tripmate_agent.py` docstring |
| TripMate 사용자 제안 연동(합의 5건) | 본 repo `docs/tripmate-rest-api.md` §7 (ADR-051) | TripMate `docs/integrations/krtour-map-rest-api.md` §7 |
| YouTube 후보 detail 소비(TM-08) | 본 repo `docs/tripmate-rest-api.md` §8 (T-217f) | TripMate UX 기획 |
| geocoding | kraddr-geo REST v2 (`POST /v2/{reverse,geocode}`) | ADR-046 |
| 인프라(PostGIS·RustFS) 구동/포트 | **tripmate-manager** `docker-compose.yml`+README (ADR-052 amendment) | 각 repo는 사용자 — 포트 값은 ADR-047과 정합 |

**원칙**: 계약 정본은 공급자 repo가 갖고(ADR-044), 소비자 repo 문서는 머리말에
"정본 링크 + view" 선언을 둔다. 형제 repo 실측은 반드시 `git fetch` 후
**origin/main** 기준(stale 본 체크아웃 함정 — 2026-06-10 검토에서 2건 사고).
