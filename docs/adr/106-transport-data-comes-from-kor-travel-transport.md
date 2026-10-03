# ADR-106: 주유소·유가·휴게소·고속도로 돌발·공항은 kor-travel-transport export에서 받는다

- 상태: accepted (2026-10-02, 소유자 결정)
- 관련: ADR-006(공개 provider client 직접 사용 — wrapper 금지), ADR-053(kor-travel-concierge pull),
  ADR-088(operation 카탈로그 정본), ADR-098(provider identity = `(dataset, kind, natural_key)`),
  ADR-102(migration 전진 배포), kor-travel-transport ADR-013(내부 서비스 export)

### 소유자 결정(원문 요지)

- "Map에서 transport로 얻을 수 있는 것은 transport API로 바꾼다. 필요하면 transport API를 고친다."
- OpiNet은 transport의 브라우저 수집본을 Map 원천으로 쓴다. transport의 유가 stale은 먼저 고친다.
- 공항도 transport로 옮기고 transport가 KPO·ICAO·소재지를 함께 낸다.
- 새 provider 정체성 `kor-travel-transport`(source_kind `internal`, 자연키 그대로)와 identity 재지정 보험.
- prod Map DB는 비어 있다(예상된 상태). shadow 기간 없이 바로 전환하고 rollback 경로에 투자하지 않는다.
- 옛 OpiNet/KREX 적재·의존·env·Manager 키는 같은 PR에서 지운다.

### 결정

1. **원천.** 아래 여섯 dataset은 provider 라이브러리(`python-opinet-api`·`python-krex-api`·
   `python-krairport-api`)가 아니라 transport `GET /v1/service/exports/*`에서 받는다.

   | dataset_key | kind | transport export | 자연키 |
   |---|---|---|---|
   | `transport_fuel_stations` | place | `fuel-stations` | 오피넷 uni_id |
   | `transport_fuel_prices` | price | `fuel-stations`(유종별 최신 가격) | 오피넷 uni_id |
   | `transport_rest_areas` | place | `rest-areas` | `name::route_name::direction` |
   | `transport_rest_area_fuel_prices` | price | `rest-area-fuel-prices` | 휴게소 코드 |
   | `transport_highway_incidents` | notice | `highway-incidents/active` | 사건 단서(기존 규칙) |
   | `transport_airports` | place | `airports` | IATA 코드 |

2. **provider 정체성**은 `kor-travel-transport`(`source_kind=internal`)다. migration `404`가 새 dataset·
   operation·scope를 넣고, 옛 dataset의 `provider_feature_identities`를 같은 `(kind, natural_key)`로 새
   dataset에 옮기고(보험 — prod는 0행), 옛 적재 operation을 끄고 옛 dataset을 비활성화한다. 옛 돌발
   dataset에 source entity가 있으면 중단한다 — 돌발 계보는 dataset 범위 활성 집합으로 닫히므로 identity만
   옮기면 옛 계보가 영구 active로 남는다. 계보 함수 `provider_sync.notice_lineage_key`의 돌발 분기도 새
   dataset으로 옮긴다(`feature_repo._notice_lineage_sql`과 글자 단위 동일).
3. **ADR-006과의 관계.** ADR-006은 *공개* provider client를 감싸는 wrapper를 금지한다. transport는 같은
   플랫폼의 내부 서비스이고, Map은 kor-travel-concierge(ADR-053)와 같은 방식으로 읽는다: HTTP는 Dagster
   fetcher(`provider_fetchers.fetch_transport_*`)가 하고, `providers/kor_travel_transport.py`는 받은 JSON을
   **엄격히** 검사해 변환 함수가 받는 입력 shape(dataclass)로 바꾸는 계약 모듈이다. 정규화 변환은 원천 데이터
   영역별 모듈(`providers/opinet.py`·`krex.py`·`krairport.py`)에 그대로 둔다 — 모듈 이름은 데이터 영역이고
   provider 정체성은 `kor-travel-transport`다.
4. **계약 관계 — pin 없음.** Map은 transport export의 소비자일 뿐이다. transport export는 Map을 위해 있으므로
   Map에 필드·모양이 필요하면 transport API를 직접 바꾼다(같은 PR 쌍, 버전·호환 층 없음, 옛 모양 shim 없음).
   Map은 transport OpenAPI를 vendoring하거나 revision/SHA로 핀하지 않는다(2026-10-03 소유자 결정 — repin
   절차는 과하다). 대신 `providers/kor_travel_transport.py`가 응답을 엄격히 검사해(필수 필드·타입·페이지·
   `collection` 상태) 어긋나면 `failure_kind`(`transport_contract` 등)와 함께 run을 실패시킨다. 파서·변환
   테스트는 Map 소유 대표 응답 `tests/unit/golden/kor-travel-transport/*.json`을 쓴다. transport 쪽 drift 방지는
   transport CI의 `export_openapi.py --check`다.
5. **인증.** `X-Kor-Travel-Transport-Service-Token`(Map `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_SERVICE_TOKEN` =
   transport `TRANSPORT_SERVICE_EXPORT_TOKEN`). transport는 토큰과 **접속 주소**(peer, 기본 loopback —
   `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`)가 모두 맞아야 응답하고 아니면 404다. Map code-server는 host
   network에서 `http://127.0.0.1:14001`로 부른다. 404는 설정 누락(`ProviderCredentialMissing`, 요청 전)과
   가른다 — `TransportExportHidden`(`failure_kind=transport_hidden`: token·접속 주소·버전 중 하나).
6. **신선도 계약 — 두 겹, 모든 dataset.** transport는 근거 수집의 이력이 없거나 실패했거나 stale이면 503을
   낸다(transport ADR-013: 주유소 24시간, 휴게소 3일, 휴게소 유가 12시간, 돌발 30분). Map은 그것만 믿지 않는다:
   - 매 페이지 `collection`(`last_success_at`·`failed`·`stale`)을 엄격히 읽고 하나라도 어긋나면
     `TransportExportNotCurrent`(`transport_not_current`)로 실패한다. 503도 같은 예외다.
   - 완전 snapshot export(주유소·휴게소·휴게소 유가)가 끝까지 0건이면 `TransportExportEmpty`
     (`transport_empty`)로 실패한다 — 0건을 전량 삭제로 읽지 않는다. 휴게소 수집이 꺼진 transport
     (`REST_AREA_COLLECTION_ENABLED=false`)는 이력이 없어 503이므로 삭제로 번지지 않는다.
   - 돌발 집합은 Map도 `collected_at` 나이(30분, 시계 역행 30분)를 잰다(`require_fresh_incident_set`).
     빈 목록은 그 검사를 통과한 뒤에만 "지금 돌발 없음"이다.
   - fetcher는 전부 모은 뒤 적재하므로(`_record_list`) 뒤 페이지의 실패도 적재·reconcile 전에 run을 멈춘다.
     실패한 run은 아무것도 적재·삭제·종료하지 않는다. Map 쪽 reconcile(#632)·watermark·DB lock은 그대로다.
   - 전송 오류·502/504만 유한 재시도(경계당 2회)하고, 페이지 수 상한과 이미 본 cursor
     집합으로 cursor 순환을 잡는다. 재시도 예산은 **run 하나에 하나**다(2026-10-04 정정 — 처음 구현은
     fetcher 호출마다 새 예산이었다): asset step과 큐 run이 `upstream_retry.sharing_run_retry_budget`을 연다.
   - 분류(2026-10-04): 503·`collection` 어긋남은 `retryable=True`인 step 실패다(HTTP 층에서는 바로 다시
     부르지 않고 `RetryPolicy`가 step을 다시 돈다). 공항 0건은 `transport_empty`, JSON이 아닌 본문은
     `transport_malformed_upstream`이다. 나머지(`transport_hidden`·`transport_empty`·`transport_contract`·
     `transport_malformed_upstream`)는 `retryable=False`이고 asset 경계가 `Failure(allow_retries=False)`로 바꿔
     step 재시도를 끈다(`quota_exhaustion.raise_terminal_if_transport_unrecoverable`). 큐 경로는 원인과 무관하게
     실패한 request로 끝난다 — 503도 다시 큐에 넣지 않는다(결정, 다음 schedule/request가 다시 돈다).
   - 가격 feature 주소(2026-10-04): transport export에는 지역 코드가 없고 가격 job은 역지오코딩하지 않으므로,
     주유소·휴게소 가격 feature는 place locator(`list_primary_place_locator`)가 실어 오는 place의
     bjd·행정동·시도·시군구 코드를 이어받는다(옛 OpiNet 경로가 주유소 주소를 그대로 쓰던 것과 같다).
6a. **유가 관측 시각.** transport 주유소 가격 행에는 셋이 있다: `provider_updated_at`(오피넷 `*_DT` — 그 유종
   가격을 **바꾼** 시각), `observed_at`(transport 원본 행 키 — `provider_updated_at`이 있으면 그것, 없으면 그 행의
   수집 시각), `collected_at`(transport가 이 값을 현재가로 **마지막으로 확인한** 수집 시각). Map
   `PriceValue.observed_at`은 `collected_at`이다. Map의 현재가 지평선(`KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS`,
   기본 4일)은 "이 값이 아직 현재가라는 근거가 있는가"를 묻는데, 가격을 유지 중인 주유소의 `*_DT`는 며칠~몇 주
   묵으므로 그것을 쓰면 멀쩡한 현재가가 지평선 밖으로 사라진다. 오피넷 갱신시각은 PriceValue payload
   `provider_updated_at`으로 보존한다(normalization `opinet-v1.1`). 휴게소 유가도 같은 뜻(transport 수집 시각)이다.
   관리 UI의 "과거 날짜" 표식은 provider가 아니라 가격 도메인 `opinet_gas_station`으로 고른다 — 이제 휴게소
   유가도 같은 provider에서 온다.
6b. **역지오코딩은 place job만.** 주유소 유가 job(일 1회)은 주유소 place를 다시 만들지 않는다. 가격 feature의
   부모는 이미 적재된 place의 locator(`list_primary_place_locator`)로 찾고 좌표는 transport가 넘긴 WGS84를 쓴다.
   place가 없는 새 주유소는 부모 없이 적재되고 다음 실행에 붙는다. 역지오코딩하는 place job(주 1회)은
   geo-heavy pool 아래서 돈다.
7. **지운 것.** OpiNet 호출 예산·scope 모드·KST 일일 coalescing·POI cache target scope, krex 돌발 이중 snapshot
   안정성 검사(transport가 수집 단위로 일관성을 진다), krex rate gate(장치는 남기고 선언 0), krex·opinet 쿼터
   예외 선언, 세 provider 핀과 env(`KOR_TRAVEL_MAP_OPINET_*`, `KOR_TRAVEL_MAP_KREX_*`).

### 결과

- (+) 같은 상류(OpiNet·data.go.kr·EX)를 한 번만 부른다. Map 주유소가 시군 회전 일부에서 전국(약 1.2만 곳)으로
  넓어진다. OpiNet 무료키 300회/일 관리가 Map에서 사라진다.
- (−) Map의 이 여섯 dataset이 transport 가용성에 묶인다. transport가 멈추면 적재가 실패한다(오래된 값을 새
  값처럼 적재하지 않는다).
- (−) OpiNet 원천이 브라우저 수집(`opinet.experimental`)이라 공식 API보다 원천 변화에 약하다(소유자 수용).
- (−) C7 운영 게이트가 쓰던 "upstream 0" 안전 operation(공항)이 이제 transport 내부 export를 한 번 부른다.
  외부 provider 호출은 여전히 0이다 — 게이트 계약을 그 뜻으로 고쳐 적었다. 기준 5가 GREEN이려면 transport가
  떠 있고 token이 맞아야 한다(`docs/runbooks/c7-prod-live-e2e.md`).
- (−) migration 404는 옛 dataset의 operation을 종류 불문(`refresh`·`feature_load`·`preview`)으로 끈다(402와 같다).

### 배포 순서

transport(0022 → 0023, `TRANSPORT_SERVICE_EXPORT_TOKEN`·`REST_AREA_COLLECTION_ENABLED=true`, 휴게소 수집 1회 성공
확인) → Map 머지 → Map pinned pair(migration 404)와 Manager compose(token, 옛
OpiNet/KREX 키 제거)를 **같은 rotation**에서 → C7. Manager만 먼저 반영하면 옛 Map job이 키 없이 실패하고, Map만
먼저 올리면 token 없이 실패한다(어느 쪽도 데이터를 지우지 않는다).
