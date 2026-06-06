# T-RV-04b provider live fetcher 적합성 감사 — 2026-06-07

## 배경

T-RV-04b는 Dagster feature-load asset의 provider record resource를 guard(materialize 시
raise)에서 **실제 live fetcher**로 교체하는 작업이다. live fetcher는 provider public
client(`F:\dev\python-*-api` 로컬 체크아웃, ADR-044)에서 record를 읽어, 각 asset의
transform `*_to_bundles(records, ...)`가 요구하는 `@runtime_checkable` Protocol을 만족하는
record iterable을 resource value로 노출해야 한다.

provider #1 **datagokr_cultural_festivals**는 깨끗이 wiring 완료(#261): `PublicCulturalFestival`
이 `CulturalFestivalItem` Protocol을 그대로 만족하고 `DataGoKrClient.festival.iter_all()`이
clean bulk 페이지네이션을 제공했다.

본 감사는 나머지 6개 provider record resource에 대해 (A) Protocol ↔ 실제 provider model
필드 일치, (B) clean bulk fetch 가능 여부를 확인했다. **결론: datagokr 외 전부 설계 결정이
선행되어야 wiring 가능하다.**

## 적합성 매트릭스

| resource_key | Protocol↔model | fetch | 차단 사유 |
|---|---|---|---|
| `datagokr_cultural_festivals` | ✅ 일치 | ✅ clean bulk(`iter_all`) | **완료(#261)** |
| `krex_rest_areas` | ❌ 8필드 중 2 일치 | 메서드는 있음(`restarea.list_all` Page) | `RestArea`에 `uni_id`·`address` 없음, `tel→phone_number`/`highway_name→route_name`/`lon/lat` rename. **Protocol 재조정(ADR-044)** |
| `krex_traffic_notices` | ❌ 모델 빈약 | `traffic.get_incidents` 페이지 | `Incident`에 notice_id·좌표·severity·valid_from/until 없음. **Protocol 재조정** |
| `krheritage_items` | ⚠️ 미확인(@property 기반) | search 페이지 + **GIS 보강 루프 필요** | `geom_wkt`는 별도 GIS 호출. **fetch 정책(dual-phase)** |
| `krheritage_events` | ❌→✅ **재조정 완료** | `event.iter_months()` rolling window | **검증 결과 mismatch**(HeritageEvent=starts_on/place/address, `raw` 부재). ADR-044 재조정 완료: upstream `python-krheritage-api#4`(raw 주입) + krtour Protocol/transform 재정렬. **wiring 완료 2026-06-07.** |
| `mois_license_records` | ✅ 일치(`PlaceRecord`) | ❌ live API 아님 | MOIS 원천이 SpatiaLite **DB 파일**. LOCALDATA ZIP 다운로드+CSV 파싱+적재 또는 DB 스냅샷 동기. **정책 결정** |
| `knps_point_records` / `knps_geometry_records` | ❌ 사전 파싱 record 없음 | ❌ keyless 파일셋 | provider는 SHP/CSV 원본 + `GeoFeatureCollection`만 제공. **SHP/CSV→Protocol 어댑터 + 파일 다운로드 정책** |

## 결정 필요 항목 (우선순위)

1. ~~**krheritage_events**~~ — **완료(2026-06-07).** 실검증 결과 mismatch였고, ADR-044
   재조정(upstream `python-krheritage-api#4` raw 주입 + krtour Protocol/transform 재정렬)으로
   해결 후 wiring. **교훈: "ASSUMED CLEAN"은 신뢰 불가 — 모든 provider는 wiring 전
   model↔Protocol 실검증 필수.** datagokr 외 전부 mismatch로 드러날 가능성 높음.
2. **krex_rest_areas / krex_traffic_notices** (ADR-044 Protocol 재조정) — 택1:
   (a) `python-krex-api`에 누락 필드(uni_id/address/좌표 등) 추가 upstream PR, 또는
   (b) krtour `KrexRestAreaItem`/traffic Protocol + transform을 실제 model에 맞춰 재정렬
   (+ `uni_id` 대체 자연키 결정 — dedup/idempotency 영향, ADR-009/016). **데이터 모델 결정.**
3. **opinet_stations** (fetch 정책) — bulk 엔드포인트 없음. 전국 커버리지 전략:
   grid `search_stations_around` 순회 + uni_id dedup + `get_station_detail` N+1. **커버리지/비용
   정책 + rate-limit 결정.**
4. **mois_license_records** (정책) — LOCALDATA 파일 다운로드+파싱 워크플로 vs DB 스냅샷 동기.
5. **knps_point/geometry** (정책+어댑터) — 파일셋 enumerate→download→SHP/CSV 파싱→record 어댑터.

## 권고

- datagokr는 완료. **krheritage_events**를 다음 wiring 후보로(모델 실검증 후).
- krex(2)·opinet·mois·knps는 각각 **설계 결정**(Protocol 재조정/fetch 정책)이 선행 — 결정
  전 wiring은 런타임 `AttributeError`(krex류) 또는 불완전 커버리지(opinet)를 낳으므로 금지.
- 재조정은 ADR-044 원칙(provider 라이브러리 기준 정렬, 필요 시 upstream PR)에 따른다.
