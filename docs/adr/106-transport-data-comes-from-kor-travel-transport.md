# ADR-106: 주유소·유가·휴게소·고속도로 돌발·공항은 kor-travel-transport export에서 받는다

- 상태: accepted (2026-10-02, 소유자 결정)
- 관련: ADR-006(공개 provider client 직접 사용 — wrapper 금지), ADR-053(kor-travel-concierge pull),
  ADR-088(operation 카탈로그 정본), ADR-098(provider identity = `(dataset, kind, natural_key)`),
  ADR-102(migration 전진 배포), kor-travel-transport ADR-012(내부 서비스 export)

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
4. **계약 고정.** transport `docs/openapi.json`(transport CI `--check`)을
   `contracts/kor-travel-transport/openapi.json`으로 vendoring하고 `PIN.json`에 transport revision과
   SHA-256을 적는다. golden fixture(`contracts/kor-travel-transport/golden/*.json`)가 실 파서를 지나고, vendored
   schema의 required 필드를 모두 가진다(`tests/unit/test_providers_kor_travel_transport.py`).
5. **인증.** `X-Kor-Travel-Transport-Service-Token`(Map `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_SERVICE_TOKEN` =
   transport `TRANSPORT_SERVICE_EXPORT_TOKEN`). transport는 토큰과 loopback Host가 모두 맞아야 응답하고 아니면
   404다. Map dagster는 같은 호스트의 `http://127.0.0.1:14001`로 부른다. 404는 "토큰 또는 Host 불일치"로
   번역해 실패한다.
6. **돌발 종료 의미 보존.** transport 활성 집합은 마지막 성공 수집이 본 사건 전체다. 수집이 실패했거나 30분 넘게
   성공하지 못했으면 transport가 503을 내고 Map fetcher가 실패한다 — 오래된 집합으로 사건을 닫지 않는다.
   Map 쪽 reconcile(#632)·watermark·DB lock은 그대로다.
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
  외부 provider 호출은 여전히 0이다 — 게이트 계약을 그 뜻으로 고쳐 적었다.
