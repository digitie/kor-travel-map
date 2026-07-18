# integration-map — PinVi 생태계 연동 정본 (T-217d, D-08)

4개 시스템(kor-travel-map · PinVi · kor-travel-concierge · kor-travel-docker-manager)의
포트·연동 방향·인증·envelope·계약 정본 위치를 **한 장**으로 고정한다.
"한쪽 갱신이 타 repo 전제에 전파되지 않는" 구조적 사고(2026-06-10 검토의 DEC-01류)
재발 방지가 목적이다. 분기별 상호 검증 절차는
[`runbooks/cross-repo-audit-checklist.md`](runbooks/cross-repo-audit-checklist.md).

> 본 문서는 **포인터 지도**다 — 계약 세부는 각 정본을 따른다(§4). 충돌 시 기계
> 정본(OpenAPI) > prose 정본 > 본 문서 순.

> **ADR-054 적용 완료**: public 배포명은 `kor-travel-map`, Python import root는
> `kortravelmap`이다. 구 import root용 호환 shim은 없다.

> **2026-07-18 계약 차단(PR #730 재검증에서 확정)**: KTM PR #724가 legacy admin ops API를
> 삭제했지만 PinVi
> `origin/main@48085afb`의 admin server는 삭제된 경로를 계속 호출한다. KTM 최신 main과 같은
> 버전으로 배포하면 provider-sync proxy는 upstream 404를 반환하고 ETL summary는 degraded/down으로
> 축약된다. 새 canonical ops는 frontend BFF gate라 경로만 교체해도 403이다. `T-ADM-C6c`에서
> PinVi caller·contract test와 명시적 service/operator principal을 먼저 복구하기 전
> `T-ADM-C7` 배포를 진행하지 않는다.

## 1. 시스템·포트

| 시스템 | 역할 | 로컬 고정 포트 | 근거 |
|---|---|---|---|
| **kor-travel-map** | feature 정본 owner — 공공 API+후보 정규화·dedup·PostGIS 조회 (독립 Docker, ADR-045) | API **12701** · admin UI 12705 · Dagster 12702 · (postgres 5432 · rustfs 12101/12105) | ADR-047 |
| **PinVi** | 사용자 여행 계획/협업/공유 서비스 — feature **consumer** | api **9021** · web 9022 | PinVi README |
| **kor-travel-concierge** | YouTube 콘텐츠 → 장소 후보 추출/검수 — feature 후보 **provider**. 현 코드/provider 이름은 `kor-travel-concierge` 계열 | API **12601** · MCP 12602 · web 12605 | kor-travel-concierge `.env.example` / `docs/feature-export-api.md` |
| **kor-travel-docker-manager** | 공용 인프라 일괄 관리(docker-compose+Web UI) — 단일 PostGIS·RustFS·관측 스택 소유 | PostGIS **5432**(`kor-travel-geo-postgres`) · RustFS S3 **12101**/console 12105 · Grafana 12205 · cAdvisor 12301 · Prometheus 12401 | kor-travel-docker-manager README, ADR-052 amendment |
| (보조) kor-travel-geo | geocoding REST v2 정본. 현 API/env 표기는 kor-travel-geo 계열 | **12501** | ADR-046/047 |

## 2. 연동 방향 (데이터 흐름)

```
[공공 API provider 라이브러리들]──────────────┐
                                              ▼ (krtour Dagster live fetch)
[kor-travel-concierge :12601] ──(REST export pull)──▶ [kor-travel-map :12701]
   GET /api/v1/features/{snapshot|changes}        feature_id 생성·dedup·정합성
   (krtour Dagster가 주기 pull, ADR-053)                │
                                                        │ OpenAPI /v1 (HTTP)
                                                        ▼
                          [PinVi api :9021] ◀──(read: in-bounds/search/nearby/
                            trip·POI·공유·협업          {id}/weather/batch/categories
                                  ▲                     /providers + curated-features
                                  │                     + /weather/* forecast/history)
                                  │                  ◀──(admin: /v1/admin/features*
                          [PinVi web :9022]          — 사용자 제안 승인 반영, ADR-051;
                                                       ops caller는 T-ADM-C6c 전환 대기)

[kor-travel-docker-manager] ═══ 인프라 계층(별도 데이터 흐름 없음): PostGIS(5432)·RustFS(12101) 구동/관리
[kor-travel-docker-manager Prometheus :12401] ──(pull scrape)──▶ [kor-travel-map :12701/metrics]
```

- PinVi ↔ kor-travel-map: **HTTP만**(라이브러리 import·공유 DB 없음, ADR-045/PinVi ADR-026).
- PinVi admin ops: 목표 계약은 `/v1/ops/datasets`·`/v1/ops/pipeline`이다. 삭제된
  `/v1/ops/dagster/summary`·`/v1/ops/providers*`·`/v1/ops/import-jobs*`는 alias로 부활시키지
  않고 PinVi caller를 전환한다. KTM frontend 전용 BFF secret·trusted CIDR을 PinVi에 공유하거나
  넓히지 않으며 server-to-server용 최소 service/operator principal을 별도로 둔다.
- service principal은 `X-Kor-Travel-Map-Ops-Token`과 권한 설명용
  `X-Kor-Travel-Map-Ops-Scope`를 함께 보낸다. read secret은 canonical datasets/pipeline의
  `GET` + `ops:read`, cancel secret은
  `POST /v1/ops/pipeline/executions/import_job/{id}/cancel` + `ops:cancel`에만 결박한다. scope
  문자열 자체는 권한 근거가 아니며 secret·method·exact route가 모두 맞아야 한다. cancel
  결박은 canonical hyphenated(8-4-4-4-12) UUID 표기만 exact 매칭한다 — 비정규 UUID 표기는
  `403` fail-closed다. API를 ASGI `root_path`(prefix) 아래에 mount하면 exact path 매칭이
  전부 실패해 cancel binding이 전면 fail-closed된다(현 배포는 root mount 전제). schedule,
  policy, preview, claim, update-request 등 나머지 mutation은 service principal에 항상 `403`이고
  trusted frontend BFF만 실행한다. token 누락은 `401`, token 또는 결박 불일치는 `403`, token이
  있는데 scope가 없거나 알 수 없는 값이면 `422` RFC7807이다. 감사 actor는 설정값이 아닌
  코드 상수 `service:pinvi`이며 요청 `X-Kor-Travel-Map-Actor`를 신뢰하지 않는다. 제거된
  `KOR_TRAVEL_MAP_API_OPS_ACTOR`가 존재하면 API 시작을 거부한다.
- 이 principal은 canonical datasets/pipeline router에만 적용한다. 기존 trusted frontend BFF는
  그대로 통과하고 `/v1/admin/*`, legacy unguarded ops, frontend BFF 인증 권한은 얻지 않는다.
- map API는 `KOR_TRAVEL_MAP_API_OPS_READ_TOKEN`과
  `KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN`, production 필수 게이트
  `KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED`, PinVi API는
  `PINVI_KOR_TRAVEL_MAP_OPS_READ_TOKEN`과
  `PINVI_KOR_TRAVEL_MAP_OPS_CANCEL_TOKEN`을 사용한다. 양쪽 token은 각각 모든 공백을 금지한
  32자 이상이며 read/cancel끼리뿐 아니라 admin BFF secret·public service token과도 달라야
  한다. map local은 required=`false`일 때 두 token이 모두 없거나 모두 명시적 빈 문자열인
  경우만 principal을 끌 수 있다. missing+empty, 한쪽 empty/non-empty, partial pair는 direct
  uvicorn과 launcher에서 모두 거부한다. n150 production은 required=`true`와 non-empty pair를
  함께 주입한다. map token/required는 API package env에만 두고 root `.env`, frontend,
  Dagster webserver/daemon에는 주입하지 않는다. Dagster image entrypoint도
  `KOR_TRAVEL_MAP_API_OPS_*`가 하나라도 존재하면 값이 비어 있어도 시작을 거부한다.
- n150 실제 주입은 `kor-travel-docker-manager` 배포 lane에서 map API의 required=`true`와
  두 token, PinVi API의 대응 token을 각 컨테이너에만
  추가한다. 배포는 secret 선주입 → map API → signed read/cancel smoke → PinVi API 순서다.
  rollback은 map만 먼저 내리지 않고 검증된 map/PinVi image pair를 함께 복원한다. 한쪽 token이
  없거나 짧거나 공백을 포함하거나 두 token이 같으면 C6c를 활성화하지 않는다.

| PinVi 현재 용도 | 삭제된 KTM 호출 | canonical 전환 대상 | 필수 의미 변환 |
|---|---|---|---|
| ETL/Dagster summary | `GET /v1/ops/dagster/summary` | `GET /v1/ops/pipeline/overview` | 새 overview DTO로 PinVi summary 재조립; `/v1/ops/metrics`는 잔여 무게이트를 닫기 전 별도 취급 |
| provider/dataset 상태 | `GET /v1/ops/providers*` | `GET /v1/ops/datasets`, `GET /v1/ops/datasets/detail` | provider-only 행을 provider×dataset×exact-scope projection으로 교체 |
| import job 목록 | `GET /v1/ops/import-jobs` | `GET /v1/ops/pipeline/executions?kind=import_job` | legacy job envelope를 root execution timeline·cursor 계약으로 교체 |
| import job 취소 | `POST /v1/ops/import-jobs/{id}/cancel` | `POST /v1/ops/pipeline/executions/import_job/{id}/cancel` | body operator 제거, 인증 principal actor + reason만 전달 |

- PinVi curated plan import: kor-travel-map `curated_features`를 REST로 읽어 PinVi
  `app.curated_trip_plans` / `app.curated_plan_pois`에 복사한다. `notice_plans`는
  PinVi 호환 API alias일 뿐 신규 정본명이 아니다.
- kor-travel-concierge → kor-travel-map: **pull 모델** — concierge는 export API만 제공, krtour Dagster가
  가져가 `FeatureBundle`로 소유(ADR-053). `operation=upsert` 적재 /
  `reject`·`tombstone` → 대응 feature `status='inactive'` 전환(ADR-050 #4, T-217b).
- PinVi ↛ kor-travel-concierge: 직접 연동 없음 — YouTube 후보는 kor-travel-map feature를 통해서만
  PinVi에 도달한다. PinVi `curated_trip_plans` 생성에도 kor-travel-concierge는 관여하지 않는다.

## 3. 인증·envelope — 표면별 의도적 차이 (D-08)

통일하지 않는다 — 표면 성격이 다르다. 아래 표가 "왜 다르지" 재논의를 막는 고정값이다.

| 표면 | 현재 인증 경계 | 성공 envelope | 에러 |
|---|---|---|---|
| kor-travel-map 공용 read (`/v1/features*` GET 등) | `public_api_key_required=true`일 때 public key. 현재 기본은 opt-out이며 일부 curated read는 dependency가 다르다 | `{data, meta}` — `meta.page.next_cursor` | RFC7807 `problem+json`(top-level `code`) |
| kor-travel-map service read (`POST /v1/features/batch`) | 설정 시 `X-Kor-Travel-Map-Service-Token`; 미설정은 현재 하위호환 통과(목표는 production fail-closed) | 〃 (`data={found{},missing[]}`) | 〃 |
| kor-travel-map admin + canonical ops (`/v1/admin/*`·`/v1/ops/{datasets,pipeline}*`) | same-origin Next.js BFF의 proxy secret + actor + trusted peer CIDR. Docker는 secret 필수·frontend 단일 `/32` | 〃 | 〃 |
| kor-travel-map ops live WebSocket | BFF가 발급한 짧은 수명 HMAC subprotocol ticket + DB nonce 단일 소비 + bounded lease | WebSocket event frame | 인증/만료는 data frame 없이 close 4401/4408 |
| kor-travel-map 관측/debug 잔여 (`/v1/ops/{metrics,system-logs,api-call-logs,consistency/*}`, `/v1/debug/mois-license/*`, `/metrics`) | 현재 app dependency 없음 — **해결 전 노출 금지인 알려진 gap** | 표면별 기존 envelope/Prometheus | 표면별 기존 계약 |
| kor-travel-concierge export (`/api/v1/features/*`) | DB `read` scope `X-API-Key` | **무-envelope** `{items, next_cursor, has_more}` (내부 export 단순 계약) | HTTP status |
| PinVi 자체 API (`:9021`) | 쿠키 세션/OAuth | PinVi 자체 `Envelope` | PinVi 자체 |

좌표는 전 구간 WGS84 평면 `lon`/`lat`(lon-first), bbox는 분리 4-float
`min_lon/min_lat/max_lon/max_lat`(ADR-048 #10 — cross-repo 정본).

### 3.1 vNext PinVi 조건부 cutover

ADR-073 목표 REST는 문서에 채택됐지만 아직 현재 OpenAPI/운영 계약이 아니다. PinVi 변경은 다음
compatible pair가 모두 준비된 뒤에만 활성화한다.

| 변경 | PinVi 선행 조건 | KTM 전환 조건 |
|---|---|---|
| ops datasets/pipeline | `T-ADM-C6c` canonical caller, 최소 service/operator principal, 삭제 경로 0건 | 양 저장소 commit pair 인증·응답 smoke 뒤 C7 |
| feature batch | 5-state typed DTO, transport 503 stale 유지, opaque UUID 보존 | state classifier와 revision, pinned service OpenAPI |
| Feature UUID | legacy alias-map DB 이관과 모든 FK/consumer 참조 shadow 검증 | UUID read/write 전환, alias lookup 보존, checksum 일치 |
| weather | set-based batch와 `target_at`/`known_at` typed consumer | bitemporal fact/current projection과 parent 404 |
| cache target/refresh | generation·ETag·Idempotency-Key·outbox consumer | service resource와 replay/outbox 활성화 |
| public/operator 분리 | 공개 DTO의 raw lineage 의존 0건, operator principal 사용 | route matrix·read-only DB role·표면별 OpenAPI SHA |

Cutover는 consumer 배포 → contract/OpenAPI SHA 확인 → production clone 복구·shadow 검증 → KTM
write fence → KTM API/DB 전환 → PinVi 활성화 → 양방향 smoke → soak 순서다. rollback window에는
write fence를 유지하거나 검증된 forward journal/PITR로 fence 이후 delta를 되살릴 수 있어야 한다.
단순 old snapshot 복원과 upstream 재수집은 rollback이 아니다. 어느 gate든 실패하면 consumer와 KTM을
이전 pinned compatible pair로 유지하고 새 writer를 열지 않는다(ADR-075).

현재 공개 read·weather·batch 경로를 목표 계약으로 바꾸는 호환 alias는 두지 않는다. 변경 시점은
각 T-VN task와 PinVi mirror task가 소유하며, 이 문서는 조건만 고정한다.

## 4. 계약 정본 위치

| 계약 | 정본(공급자 repo) | 소비측 view |
|---|---|---|
| kor-travel-map 전 표면 REST | `docs/architecture/rest-api.md` + 기계 정본 `packages/kor-travel-map-api/openapi{,.user}.json` | PinVi `docs/integrations/kor-travel-map-rest-api.md` |
| PinVi admin ops 전환 | 본 repo `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-11/F-17 + `docs/tasks.md` `T-ADM-C6c` | PinVi admin client·provider-sync proxy·contract test에 같은 task를 mirror |
| PinVi T-130 공개 해수욕장/축제 뷰 | 본 repo `docs/architecture/public-views-api.md` + `openapi.user.json`(T-222b 구현) | PinVi `docs/api/public.md` / `docs/kor-travel-map-requirements.md` §6 |
| curated features → PinVi curated trip plans | 본 repo [`docs/curated-features.md`](curated-features.md) + `openapi.user.json`(T-223c-1 read 구현) | PinVi `docs/kor-travel-map-requirements.md`의 curated trip plan import 절 / PinVi `docs/api/notice-plans.md`의 호환 alias 설명 |
| kor-travel-concierge feature export | kor-travel-concierge `docs/feature-export-api.md`(로컬 경로는 `F:\dev\kor-travel-concierge`, 프로젝트명은 `kor-travel-concierge`) | 본 repo: `docs/etl/concierge-feature-etl.md` + `providers/kor_travel_concierge.py` docstring |
| PinVi 사용자 제안 연동(합의 5건) | 본 repo `docs/architecture/rest-api.md` (구 ADR-051) | PinVi `docs/integrations/kor-travel-map-rest-api.md` §7 |
| YouTube 후보 detail 소비(TM-08) | 본 repo `docs/architecture/rest-api.md` (T-217f) | PinVi UX 기획 |
| geocoding | kor-travel-geo REST v2 (`POST /v2/{reverse,geocode}`) | ADR-046 |
| 인프라(PostGIS·RustFS) 구동/포트 | **kor-travel-docker-manager** `docker-compose.yml`+README (ADR-052 amendment) | 각 repo는 사용자 — 포트 값은 ADR-047과 정합 |

**원칙**: 계약 정본은 공급자 repo가 갖고(ADR-044), 소비자 repo 문서는 머리말에
"정본 링크 + view" 선언을 둔다. 형제 repo 실측은 반드시 `git fetch` 후
**origin/main** 기준(stale 본 체크아웃 함정 — 2026-06-10 검토에서 2건 사고).
