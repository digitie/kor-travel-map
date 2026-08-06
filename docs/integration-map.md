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

> **2026-07-27 전환 완료**: 2026-07-18에 발견한 legacy admin ops 삭제와 PinVi caller
> 불일치는 `T-ADM-C6c`에서 해소했다. PinVi는 canonical datasets/pipeline과 제한된
> `ops:read`/`ops:cancel` principal을 사용하고, Docker Manager는 T-VN-41F1J의 별도
> `ops:fixture` principal으로 Map-owned cancel-probe 수명주기만 호출한다. 현재 n150은 서비스 전
> rehearsal 환경이며, v5 pinned-runtime generation 뒤 final-schema source/ETL 재적재와 F1D-D
> data-dependent live 인수는 아직 완료되지 않았다. 삭제된 ops 경로와 URL query Map API key는 호환
> 경로로 부활시키지 않는다.

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
                                                       ops: canonical datasets/pipeline)

[kor-travel-docker-manager] ═══ 인프라 계층(별도 데이터 흐름 없음): PostGIS(5432)·RustFS(12101) 구동/관리
[kor-travel-docker-manager Prometheus :12401] ┄┄(목표: Authorization Bearer metrics token으로
       12701 scrape — ADR-066 T-VN-02. 현재 docker-manager prometheus.yml에
       12701 job 없음, 배포 시 인증과 함께 신규 추가)┄▶ [kor-travel-map :12701/metrics]
```

- PinVi ↔ kor-travel-map: **HTTP만**(라이브러리 import·공유 DB 없음, ADR-045/PinVi ADR-026).
- PinVi admin ops의 현재 계약은 `/v1/ops/datasets`·`/v1/ops/pipeline`이다. 삭제된
  `/v1/ops/dagster/summary`·`/v1/ops/providers*`·`/v1/ops/import-jobs*`는 alias로 부활시키지
  않는다. KTM frontend 전용 BFF secret·trusted CIDR을 PinVi에 공유하거나 넓히지 않으며
  server-to-server용 최소 service/operator principal을 별도로 둔다.
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
  `KOR_TRAVEL_MAP_API_OPS_ACTOR`가 존재하면 API 시작을 거부한다. T-VN-41F1J의 fixture
  secret은 `PUT|GET /v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}`와
  `POST .../{transaction_id}/finalize` + `ops:fixture`에만 결박하고, actor는 코드 상수
  `service:docker-manager`다. fixture token은 read/cancel token이나 PinVi 권한을 넓히지 않는다.
- 이 principal은 canonical datasets/pipeline router에만 적용한다. 기존 trusted frontend BFF는
  그대로 통과하고 `/v1/admin/*`, legacy unguarded ops, frontend BFF 인증 권한은 얻지 않는다.
- map API는 `KOR_TRAVEL_MAP_API_OPS_READ_TOKEN`,
  `KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN`, `KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN`, production 필수 게이트
  `KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED`, PinVi API는
  `PINVI_KOR_TRAVEL_MAP_OPS_READ_TOKEN`과
  `PINVI_KOR_TRAVEL_MAP_OPS_CANCEL_TOKEN`을 사용한다. 양쪽 token은 각각 모든 공백을 금지한
  32자 이상이며 세 token은 서로와 admin BFF secret·public service token과 모두 달라야
  한다. fixture token은 Docker Manager에만 주입한다. map local은 required=`false`일 때 세 token이
  모두 없거나 모두 명시적 빈 문자열인 경우만 principal을 끌 수 있다. missing+empty, 한쪽 empty/non-empty, partial set은 direct
  uvicorn과 launcher에서 모두 거부한다. n150 production은 required=`true`와 non-empty 세 token을
  함께 주입한다. map token/required는 API package env에만 두고 root `.env`, frontend,
  Dagster webserver/daemon에는 주입하지 않는다. Dagster image entrypoint도
  `KOR_TRAVEL_MAP_API_OPS_*`가 하나라도 존재하면 값이 비어 있어도 시작을 거부한다.
- n150에서는 `kor-travel-docker-manager` 배포 lane이 map API의 required=`true`와 세 token,
  PinVi API의 read/cancel 대응 token, Manager의 fixture 대응 token을 각 컨테이너에만 주입한다.
  fixture token은 PinVi container에 절대 주입하지 않는다. 2026-07-27 canonical
  read/cancel principal smoke와 C7을 통과해 활성화했다. 이후 배포도 secret 선주입 → map API →
  signed read/cancel smoke → PinVi API 순서를 유지하고, rollback은 검증된 Map/PinVi image
  pair를 함께 복원한다. 한 token이라도 없거나 짧거나 공백을 포함하거나 세 token 중 둘이 같으면
  새 pair를 활성화하지 않는다.
- `/v1/features/search` cursor 서명에는 API 전용
  `KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET`을 사용한다. 이 값은 public API key나
  admin/service/ops/metrics credential과 공유하지 않고 map API container에만 주입한다.
  production features surface는 공백 없는 32자 이상 값이 없으면 기동을 거부한다. n150
  cutover에서는 API 재생성 전에 secret을 먼저 주입하고, 첫 page cursor로 같은 query의 다음
  page 성공과 query 변경·변조 cursor의 typed 422를 확인한다. 값 rotation은 발급 당시 key로
  만든 기존 cursor를 즉시 무효화하므로 배포 창의 허용 동작으로 기록하며, local-dev의
  process-local fallback은 재시작·multi-worker 간 cursor 연속성을 보장하지 않는다.

| PinVi 용도 | 폐기된 KTM 호출 | 현재 canonical 호출 | 적용된 의미 변환 |
|---|---|---|---|
| ETL/Dagster summary | `GET /v1/ops/dagster/summary` | `GET /v1/ops/pipeline/overview` | 새 overview DTO로 PinVi summary 재조립; 관측 metrics는 별도 `ops:read` 인증 표면 |
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
| kor-travel-map 공용 read (`RoutePolicy.PUBLIC_KEYED`) | production에서 `X-Kor-Travel-Map-Api-Key` 또는 `X-Kor-Travel-Map-Service-Token`. URL `key` query는 폐기했고 full/user OpenAPI는 route policy에서 같은 OR 계약을 생성한다 | `{data, meta}` — `meta.page.next_cursor` | RFC7807 `problem+json`(top-level `code`) |
| kor-travel-map service resource (`/v1/features/{batch,weather/batch}`, `/v1/service/cache-target*`, `/v1/service/refresh-requests*`, `/v1/service/feature-alias-maps*`) | production 필수 `X-Kor-Travel-Map-Service-Token`; cache-target은 command=`{command}`, consumer=`{read,claim,ack,nack,snapshot}`, restore=`{restore-fence}`, recovery=`{recovery,recovery-replay}` exact 역할 principal과 canonical consumer/system binding을 추가 결박 | 〃 | 〃 |
| kor-travel-map admin + canonical ops (`/v1/admin/*`·`/v1/ops/{datasets,pipeline}*`) | same-origin Next.js BFF의 proxy secret + actor + trusted peer CIDR. Docker는 secret 필수·frontend 단일 `/32` | 〃 | 〃 |
| kor-travel-map ops live WebSocket | BFF가 발급한 짧은 수명 HMAC subprotocol ticket + DB nonce 단일 소비 + bounded lease | WebSocket event frame | 인증/만료는 data frame 없이 close 4401/4408 |
| kor-travel-map Prometheus `/metrics` | production 필수 `KOR_TRAVEL_MAP_API_METRICS_TOKEN`의 `Authorization: Bearer` scrape identity(ADR-066 결정 4, T-VN-02) | Prometheus exposition | 비-Bearer/불일치 401 |
| kor-travel-map 관측 ops (`/v1/ops/{metrics,system-logs,api-call-logs,consistency/*,health-deep}`) | AdminBFF 또는 `X-Kor-Travel-Map-Ops-Token` + `X-Kor-Travel-Map-Ops-Scope: ops:read` | 표면별 기존 envelope | RFC7807 `problem+json` |
| kor-travel-map C6c contract fixture (`/v1/ops/contract-fixtures/c6c-cancel-probe/*`) | Docker Manager만 `X-Kor-Travel-Map-Ops-Token` + `X-Kor-Travel-Map-Ops-Scope: ops:fixture`; AdminBFF·PinVi·read/cancel token은 불허 | `{data, meta}` durable fixture receipt | RFC7807 `problem+json` |
| kor-travel-map raw debug (`/v1/debug/mois-license/*`) | production에서는 route 자체를 mount하지 않는다. local-dev에서만 mount하며 AdminBFF 인증을 요구한다 | 표면별 기존 envelope | RFC7807 `problem+json` |
| kor-travel-concierge export (`/api/v1/features/*`) | DB `read` scope `X-API-Key` | **무-envelope** `{items, next_cursor, has_more}` (내부 export 단순 계약) | HTTP status |
| PinVi 자체 API (`:9021`) | 쿠키 세션/OAuth | PinVi 자체 `Envelope` | PinVi 자체 |

좌표는 전 구간 WGS84 평면 `lon`/`lat`(lon-first), bbox는 분리 4-float
`min_lon/min_lat/max_lon/max_lat`(ADR-048 #10 — cross-repo 정본).

### 3.1 vNext PinVi 단계적 cutover

ADR-073의 공개 조회·검색, canonical ops principal, 5-state feature batch는 현재 OpenAPI와
v5 pinned-runtime generation에 반영됐다. sparse weather batch처럼 생산자만 먼저 반영되거나
cache target처럼 미완인 항목은 각 T-VN task와 PinVi consumer가 함께 준비된 generation에서만
활성화한다. 현재 계약은 배포 source에 결박된 OpenAPI snapshot으로 판정한다.

Docker Manager의 runtime 정본은 version 5 `active_generation` 하나다. Map API·UI·Dagster
web·daemon과 PinVi API·web·Dagster의 일곱 immutable image, 양쪽 source revision, Map application·
Dagster 및 PinVi head, pinset hash를 exact field로 가진다. version 7 rebuild journal의 committed
candidate는 generation과 같아야 하며 finalized cancel-probe receipt를 포함한다. Map C7 attestation
v5는 일곱 role의 compose service/container binding과 UI/API/Dagster endpoint role을 함께 서명하고,
caller env가 이를 바꾸면 fail-close한다. final-schema source/ETL reload receipt가 같은 manifest/journal,
세 head와 canonical dataset availability에 결박되기 전에는 data-dependent C7/Admin live E2E를 시작할 수 없다.
F1D-D의 재적재 및 data-dependent live 인수는 아직 미완료다.

| 변경 | PinVi 선행 조건 | KTM 전환 조건 |
|---|---|---|
| ops datasets/pipeline | **완료** — canonical caller, 최소 service/operator principal, 삭제 경로 0건 | **완료** — commit pair 인증·응답 smoke와 C7 |
| ops 관측 read | **완료** — consistency/log caller `ops:read` 전환과 direct caller inventory | **완료** — operator gate·route exception 0건, production principal smoke |
| feature batch | 5-state typed DTO, transport 503 stale 유지, opaque UUID 보존 | state classifier와 revision, pinned service OpenAPI |
| Feature UUID | legacy alias-map DB 이관과 모든 FK/consumer 참조 shadow 검증 | UUID read/write 전환, alias lookup 보존, checksum 일치 |
| weather | sparse 다중 `targets[]`/`known_at`, item `card_key`·target-local `cards[]` typed consumer | 단일 snapshot bitemporal projection, 공유 card 정규화, metric budget, parent 404 |
| cache target/refresh | **paired PR 전 미완** — generation·conditional ETag·Idempotency-Key·strict pull consumer | **producer foundation 진행** — service resource, restore fence, same-tx outbox, pull lease/replay/snapshot |
| public/operator 분리 | 공개 DTO의 raw lineage 의존 0건, operator principal 사용 | route matrix·read-only DB role·표면별 OpenAPI SHA |

Cutover는 consumer 배포 → contract/OpenAPI SHA 확인 → shadow 검증 → KTM write fence → KTM API/DB
전환 → PinVi 활성화 → 양방향 smoke → soak 순서다. 실패 시 write fence를 유지하고 immutable image를
전 세대로 되돌린 뒤 forward-fix 또는 최종 schema source/ETL 재적재를 새 receipt로 증명한다. 중간 DB
preimage·PITR·old snapshot을 복원 근거로 사용하지 않는다. 어느 gate든 실패하면 consumer와 KTM을
이전 세대의 immutable generation으로 되돌려 writer를 열지 않는다. 현재 개발 단계에서 data 보전보다
최종 schema source/ETL 재적재가 정본이며, stale receipt·중간 DB snapshot은 복원 근거가 아니다.

`/v1/features/search` 전환에는 `include_total=false`의 COUNT 0회, `true`의 COUNT 1회,
동일 정규화 query에서만 이어지는 signed cursor, 알 수 없는 version·변조·query mismatch의
typed 422를 포함한다. production API의 cursor signing secret은 다른 runtime과 frontend로
전파하지 않으며 실제 값은 배포 전용 env에만 둔다.

현재 pinned generation에 포함된 공개 read·feature batch는 활성 계약이다. sparse weather
batch와 후속 service resource는 각 T-VN task와 PinVi mirror task가 활성화 시점을 소유한다.
어느 경우에도 구 계약용 호환 alias는 두지 않는다.

#### cache target paired stream (ADR-081)

cache target 전파는 Map→PinVi callback push가 아니라 PinVi가 Map service stream을 pull하고
contiguous prefix를 ACK하는 at-least-once 계약이다. 양쪽 공통 event discriminator는
`event_type`이고 exact 값은 다음 네 개뿐이다.

- `cache_target.state_applied`
- `cache_target.links_reconciled`
- `refresh_request.status_changed`
- `cache_target.reconciled`

Map은 `restore_epoch`, PinVi는 target `source_generation`, Map result writer는
`target_sequence`를 소유한다. target 의미 순서는 이 tuple이고 global sequence가 배정한
`relay_order` cursor는 external system별 delivery prefix에만 쓴다. event inbox commit과 ACK는 순서가 다르다. PinVi는 inbox dedupe,
target tuple CAS, DB cache generation, consumer checkpoint를 한 transaction에 먼저 commit하고
그 뒤 ACK한다. ACK 유실은 동일 event 재전달이며 side effect를 추가하지 않는다.
`external_system`과 `target_key`는 양쪽 모두 trim된 Unicode NFC canonical form으로 전송한다.
`target_key` 상한은 source와 refresh scope 모두 512자다. Map API/repository/DB가 비정규 identity를
거부하므로 NFC-equivalent identity를 별도 target/request로 생성해 snapshot Merkle이나 refresh를
오염시킬 수 없다.

Map의 모든 outbox writer transaction은 system stream을 head/target/link보다 먼저 잠근다. DB trigger는
그 stream lock 뒤에만 global sequence에서 `relay_order`를 배정하므로 각 external system cursor는 같은
stream에서 늦게 commit되는 더 낮은 event를 추월하지 않는 commit-safe prefix다. global sequence는 번호의
전역 uniqueness만 제공하고 서로 다른 stream의 commit 순서를 보장하지 않는다. snapshot reuse cursor는 생성 당시의 안전한 lower-bound로
유지될 수 있으므로 PinVi는 그 뒤 event를 재조회하고 immutable inbox receipt로 중복을 제거한다.

restore/cutover는 stream GET의 raw ETag를 기준으로 restore-fence command를 호출해 Map epoch를
N+1로 올린 뒤 writer를 연다. 이 transaction은 더 낮은 epoch의 모든 non-delivered delivery를
terminal `superseded`로 종결하므로 구 pending/retry/lease/dead가 새 epoch claim이나 dead gate에
섞이지 않는다. exact fence replay는 같은 receipt를 반환하고 delivery version을 바꾸지 않는다.
이때 Map은 active `preparing|running` reconciliation도 terminal `superseded`로 종결하고 fence 응답에
대체한 request UUID와 count를 포함한다. PinVi는 이 UUID가 자기 active request라면 구
snapshot/seal/completion을 중단하고 새 epoch stream ETag로 begin부터 다시 시작한다. exact fence
replay의 claim/delivery/reconciliation count와 request UUID는 최초 응답과 같아야 한다.
restored payload의 epoch를 신뢰하지 않는다. fixed snapshot은
active+tombstone Merkle v1과 pinned service OpenAPI를 함께 검증한다. credential, principal scope,
contract SHA, epoch, snapshot checksum 중 하나라도 맞지 않으면 PinVi consumer는 fail-closed한다.
source PUT/DELETE와 refresh create는 exact `cache-target:command` principal만 사용한다. 기존
`cache-target:consumer` umbrella는 registry와 인증 fallback에서 clean cut 제거한다. 한 canonical
`(consumer_id, sorted external_systems)` binding은 command=`{command}`,
consumer=`{read,claim,ack,nack,snapshot}`, restore=`{restore-fence}`,
recovery=`{recovery,recovery-replay}` 네 역할을 각각 정확히 하나 가져야 한다. complete하고 서로 겹치지
않는 binding 여러 개는 서로 다른 consumer에만 허용한다. 한 `consumer_id`는 정확히 한 canonical system
tuple을 소유하며 여러 system은 한 sorted union binding으로 표현한다. 이 규칙이 external-system 없는
ACK의 cross-binding claim 제거를 막는다. external system의 binding 소유권, token digest,
`principal_id`는 전역 unique이며 public VWorld/API key와 역할 token digest 재사용도 기동을 막는다. 각
17개 operation은 OpenAPI `x-required-service-scope`로 요구 scope를 노출하고 runtime도 같은 inventory를
사용한다. request-bound reconciliation은 scope를 metadata 조회 전에 검사한다. command
writer가 PUT/DELETE 후 source GET으로 CAS를 이어가거나 refresh `Location`을 polling하는 GET에서는
consumer credential로 명시적으로 전환한다. command principal은 consumer·snapshot·restore·recovery를
호출하지 못한다. 이 권한 분리부터 Map service OpenAPI SHA를 다시 pin하고 compatible pair를 contract
generation 7로 올린다. generation 6 조합은 command 표면 활성화에 사용할 수 없다.
성공한 `cache_target.reconciled` payload는 exact
`{request_id, snapshot_id, actual_merkle_root, expected_merkle_root, status, version}`이며,
envelope의 `source_payload_fingerprint`는 expected root와 같다. PinVi는 이 request/snapshot identity를
inbox receipt와 함께 원자적으로 보존한다.

Map producer foundation PR만 merge된 상태는 `T-VN-41C` 완료나 production enable이 아니다.
PinVi paired PR → contract pin → isolated restore clone/backfill → Merkle 일치 → duplicate/gap/epoch
live → soak를 모두 통과한 compatible pair에서만 enable한다.

### 3.2 feature batch 5-state 계약 (T-VN-11, 적용 완료)

`POST /v1/features/batch`는 요청 순서를 보존하는
`found|retired|suppressed|missing|unchanged` discriminated union이다. `found`는 최신 공개
`trip_card`, `unchanged`는 소비자 `known_row_revision`과 같은 공개 feature,
`retired`는 lifecycle tombstone, `suppressed`는 존재하지만 공개 projection에서 제외된
feature, `missing`은 저장소에 없는 identity다. 따라서 비공개와 미존재를 같은 상태로
축약하지 않으며 PinVi는 같은 typed state를 Web·Map·Mobile 표시 resolver에서 사용한다.

**echo 계약 (T-VN-32C 값 전환에서 명문화)**: batch item·found/missing 키의
`feature_id`**와 found item의 `trip_card.feature_id`(item echo와 동일 값)**,
weather batch(`POST /v1/features/weather/batch`)의 target `feature_id` echo는
**요청 표기를 그대로 보존**한다 — Map이 응답 read 표면의 `feature_id` 값을
UUID 정본으로 전환(T-VN-32C PR-2)한 뒤에도, batch 계열 echo는 canonicalize하지
않는다. 소비자(PinVi `kor_travel_map.py`의 echo 등식 검증)는 legacy `f_*`로
보내면 legacy를, UUID로 보내면 UUID를 그대로 돌려받는다. 조회 자체는 Map
경계에서 legacy/UUID 양형식을 해석한다(ADR-068 결정 3). **형식 위반 참조**
(공백 패딩/256자 초과)는 경계 해석 대상에서 제외되어 종전과 동일하게 해당
item만 missing/no_data가 된다 — batch의 per-item 상태 기계 격리는 값 전환
후에도 유지된다(리뷰 M1로 422 격상안 철회). 코드 정본은
`kortravelmap.api.identity_projection` 모듈 docstring이다.

### 3.3 body actor 제거 (T-VN-20, ADR-066 D-2) — PinVi 전송 중단 필요

T-VN-20이 모든 admin write의 감사 actor를 인증 principal(admin BFF의
`X-Kor-Travel-Map-Actor`)에서만 파생하도록 완결했다. request body의
`operator`/`actor`/`created_by`/`reviewed_by`는 더 이상 감사 actor 원천이 아니다.

PinVi `origin/main`의 `apps/api/app/clients/kor_travel_map_admin.py`가 아직 body로
보내는 필드는 **수용하되 무시**(accept-and-ignore)한다 — 아래 endpoint는 body에
해당 필드가 있어도 `422`가 아니고, 값은 무시되며 저장 actor는 principal이다:

| KTM endpoint | PinVi가 보내는 body 필드 | 처리 |
|---|---|---|
| `POST/PATCH/DELETE /v1/admin/features*`, `.../change-requests/{id}/approve\|reject` | `operator`(고정 `"pinvi-admin"`) | 수용·무시, actor=principal |
| `PATCH /v1/admin/issues/{id}` | `operator` | 수용·무시, actor=principal |
| `PATCH /v1/admin/dedup-reviews/{id}` | `reviewed_by` | 수용·무시, actor=principal |

**PinVi follow-up (별도 PR)**: 위 3개 client 메서드에서 `operator`/`reviewed_by`
body 전송을 제거한다(감사 actor는 KTM이 BFF principal로 기록하므로 불필요). 제거 전까지
KTM은 deprecated 필드로 수용하며, 두 필드 모두 OpenAPI에 `deprecated: true`로 표기된다.

반면 PinVi가 **호출하지 않는** admin frontend 전용 write(auth-event `actor`, curated
select/unselect `actor`, enrichment review `reviewed_by`, offline upload
`created_by`·validate `operator`)는 body 필드를 **schema에서 제거**했다 — 옛 caller가
보내면 `422`다(admin frontend는 이미 전송 중단, BFF actor header만 사용).

### 3.4 cache-target Map writer-drain (T-VN-41D, ADR-082)

cache-target diagnostic/cutover의 Map Dagster producer quiescence는 공개 HTTP 계약이
아니다. Docker Manager가 frozen Compose로 candidate Map API image의 private typed runner를
실행하고, Map은 own application DB의 durable lease로 schedule/sensor의 기존 상태와 owned
Dagster run의 terminal-cancel 결과를 보관한다. Manager journal에는 opaque lease UUID와
secret-free receipt SHA-256만 남긴다.

이 runner는 `begin|attest|restore`만 허용하며, cache-target command/consumer/restore/recovery
4-role token, 일반 admin/ops schedule·cancel endpoint, 외부 GraphQL을 재사용하지 않는다.
`restore`는 Map Dagster daemon을 재기동하기 전에 원래 running instigation만 복원·attest한다.
정본 상태/입출력/schema/recovery와 isolated rehearsal은
[`architecture/cache-target-writer-drain.md`](architecture/cache-target-writer-drain.md), 결정은
ADR-082다.

### 3.5 C6c cancel-probe Map fixture (T-VN-41F1J, ADR-084)

Docker Manager는 candidate Map이 ready인 뒤 F1D transaction ID로 fixture ensure/read/finalize
service API만 호출한다. Map은 해당 ID의 running/no-Dagster-run job과 canonical cancellation
연결을 durable하게 소유하고, PinVi는 기존 `ops:cancel`로 보통 cancel request 한 번만 보낸다.
Manager는 exact `409 PIPELINE_CANCELLATION_UNSAFE`와 cancellation ID를 확인한 뒤 finalize한다.
`404`, `502`, `503`, timeout, 다른 409는 모두 실패이고, transaction state가 `consumed`이면
cancel을 다시 보내지 않는다. 세부 상태 전이와 API는
[`architecture/c6c-cancel-probe-fixture.md`](architecture/c6c-cancel-probe-fixture.md) 및
ADR-084가 정본이다.

## 4. 계약 정본 위치

| 계약 | 정본(공급자 repo) | 소비측 view |
|---|---|---|
| kor-travel-map 전 표면 REST | `docs/architecture/rest-api.md` + 기계 정본 `packages/kor-travel-map-api/openapi{,.user,.service}.json` | PinVi `docs/integrations/kor-travel-map-rest-api.md` |
| PinVi canonical ops | 본 repo `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-11/F-17 + 본 문서 §2 principal 계약 | PinVi admin client·provider-sync proxy·contract test와 `docs/integrations/kor-travel-map-rest-api.md` |
| PinVi T-130 공개 해수욕장/축제 뷰 | 본 repo `docs/architecture/public-views-api.md` + `openapi.user.json`(T-222b 구현) | PinVi `docs/api/public.md` / `docs/kor-travel-map-requirements.md` §6 |
| canonical curation item → PinVi curated trip plans | 본 repo ADR-092 + service `openapi.service.json`의 `/v1/service/curation-items/{curation_item_id}/detail-snapshot`; 전용 `pinvi:curation-snapshot:read` ServiceToken만 허용하고 AdminBFF secret/CIDR은 공유하지 않음 | PinVi `docs/kor-travel-map-requirements.md`의 canonical curation item import 절과 vendored service contract |
| kor-travel-concierge feature export | kor-travel-concierge `docs/feature-export-api.md`(로컬 경로는 `F:\dev\kor-travel-concierge`, 프로젝트명은 `kor-travel-concierge`) | 본 repo: `docs/etl/concierge-feature-etl.md` + `providers/kor_travel_concierge.py` docstring |
| PinVi 사용자 제안 연동(합의 5건) | 본 repo `docs/architecture/rest-api.md` (구 ADR-051) | PinVi `docs/integrations/kor-travel-map-rest-api.md` §7 |
| YouTube 후보 detail 소비(TM-08) | 본 repo `docs/architecture/rest-api.md` (T-217f) | PinVi UX 기획 |
| cache-target Map writer-drain | `docs/architecture/cache-target-writer-drain.md` + Map API image private typed runner (public OpenAPI 미노출) | Docker Manager T-049F frozen Compose receipt parser |
| **C6c cancel-probe fixture** | `docs/architecture/c6c-cancel-probe-fixture.md` + `openapi.service.json`의 `ops:fixture` 3 route + ADR-084 | Docker Manager F1D orchestrator; PinVi는 기존 cancel relay만 소비 |
| **curation collection 표면** | 본 repo `packages/kor-travel-map-api/src/kortravelmap/api/routers/curations.py` + `openapi{,.user}.json`. CSV 정본은 `resources/curations/*.csv` + `manifest.json` | runtime identity lookup 소비자는 없음. PinVi pinned OpenAPI snapshot의 schema field hit는 호출 소비가 아님(2026-07-30) |
| **feature alias-map 이관 (T-VN-32C)** | 본 repo `contracts/feature-alias-map-v1-golden.json`(`feature-alias-map-v1` — Map/PinVi 독립 재계산 golden) + `GET /v1/service/feature-alias-maps{,/checksum}`(`openapi.service.json`). 이관·복구 경계 전용 bulk read(ADR-068 결정 3) — 런타임 alias lookup 표면이 아니다 | PinVi vendored `apps/api/tests/contract/feature-alias-map-v1-golden.json` + 독립 구현 `app/core/feature_alias_contract.py` + 이관 실행기 `pinvi-feature-uuid-cutover` |
| geocoding | kor-travel-geo REST v2 (`POST /v2/{reverse,geocode}`) + public API key header 인증 | ADR-046 + geo ADR-064 |
| 인프라(PostGIS·RustFS) 구동/포트 | **kor-travel-docker-manager** `docker-compose.yml`+README (ADR-052 amendment) | 각 repo는 사용자 — 포트 값은 ADR-047과 정합 |

> **`collection_key`는 안정 식별자가 아니다 (2026-07-30).** 공개/admin 응답에 실리지만
> 마이그레이션 `0045` → `0065`에서 형식이 **두 번** 바뀌었다(`0065`가 legacy collection 52개를
> `legacy:<theme_uuid>:<source_uuid>:<md5(title)>`로 재작성한다). admin collection 생성의 필수
> 입력·저장 필드이고 목록 검색 대상이며, CSV import도 `ON CONFLICT (collection_key)`로
> upsert한다. 반면 runtime path에서 collection을 식별하는 값은 `collection_id` UUID다.
> 따라서 `collection_key`는 운영·import용 mutable business key로만 쓰고, 외부의 장기 참조나
> path identity에는 **`collection_id`를 사용한다**. CSV 정본의
> `korean-tourism-100:*` 같은 key는 이번 legacy 재작성 대상이 아니지만, 그 사실을 전체
> `collection_key` 안정성 계약으로 확대하지 않는다.

**원칙**: 계약 정본은 공급자 repo가 갖고(ADR-044), 소비자 repo 문서는 머리말에
"정본 링크 + view" 선언을 둔다. 형제 repo 실측은 반드시 `git fetch` 후
**origin/main** 기준(stale 본 체크아웃 함정 — 2026-06-10 검토에서 2건 사고).

kor-travel-map backend의 geo 호출은 public API key를 URL query로 보내지 않고
`X-KTG-API-Key` header로만 보낸다. Map은 geo public endpoint만 호출하며
`X-KTG-Actor`/`X-KTG-Roles`/`X-KTG-Admin-Proxy-Secret`을 보내거나 admin 권한을
위임받지 않는다. Map 설정 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`에는 geo public key를
넣으며 Map admin BFF/service/ops token과 공유하지 않는다.
