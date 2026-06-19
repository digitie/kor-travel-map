# external-apis.md — Provider API 키 발급/호출 정책

본 문서는 본 라이브러리가 의존하는 provider 라이브러리들이 호출하는 외부 API의
발급/호출 정책 reference다. 공공 provider 호출은 `python-*-api` provider
라이브러리에 위임한다(ADR-006). 예외적으로 `kor-travel-concierge-youtube`는 형제 앱
`kor-travel-concierge`의 REST export를 kor-travel-map Dagster가 직접 pull한다(ADR-053).

본 문서는 운영자/에이전트가 어떤 키를 어디서 발급받고 어디에 두는지 한 곳에서
확인할 수 있도록 한다.

## 1. 키 보관 원칙

- 모든 API 키는 `SecretStr`로 settings에 로드.
- `.env` 파일은 권한 600. systemd `EnvironmentFile` 또는 vault 권장.
- 평문 commit 금지. CI/CD에서는 GitHub Actions secret.
- 로그/Sentry에 절대 노출 안 함.
- 키 회전 시 ADR 추가 (회전 사유, 영향 범위).

## 2. 환경변수 카탈로그

| 변수 | 사용 provider | 발급처 | 비고 |
|------|--------------|--------|------|
| `KMA_API_KEY` | python-kma-api | 기상청 API허브 (apihub.kma.go.kr) | 무료, 호출 한도 있음 |
| `VISITKOREA_SERVICE_KEY` | python-visitkorea-api | data.go.kr (TourAPI) | URL-encoded |
| `KRHERITAGE_API_KEY` | python-krheritage-api | 국가유산청 OpenAPI | |
| `KRFOREST_API_KEY` | python-krforest-api | 산림청 / 산림청 산악기상 | |
| ~~`KNPS_SERVICE_KEY`~~ | ~~python-knps-api~~ | — | **사용 안 함**. ADR-028 amendment + knps-api PR#4 (keyless). §3.8.1 참조 |
| `KREX_API_KEY` | python-krex-api | 한국도로공사 API | |
| `KHOA_API_KEY` | python-khoa-api | 국립해양조사원 | 해수욕장/해양지수 |
| `AIRKOREA_API_KEY` | python-airkorea-api | 한국환경공단 AirKorea | 대기질 |
| `OPINET_API_KEY` | python-opinet-api | 한국석유공사 OpiNet | 주유소·유가 |
| `DATAGOKR_API_KEY` | python-datagokr-api, data.go.kr-standard | data.go.kr 표준데이터 | 최우선 |
| `DATA_GO_KR_SERVICE_KEY` | 동일 | 동일 | 폴백 1 |
| `PUBLIC_DATA_SERVICE_KEY` | 동일 | 동일 | 폴백 2 |
| `SERVICE_KEY` | 동일 | 동일 | 폴백 3 |
| `KAKAO_LOCAL_REST_API_KEY` | kakao-local-api | Kakao Developers | `Authorization: KakaoAK {KEY}` |
| `NAVER_SEARCH_CLIENT_ID` | naver-search-api | NAVER Developers | 헤더 `X-Naver-Client-Id` |
| `NAVER_SEARCH_CLIENT_SECRET` | 동일 | 동일 | 헤더 `X-Naver-Client-Secret` |
| `GOOGLE_PLACES_API_KEY` | google-places-api-new | Google Cloud Console (Places API New) | field mask 필수 |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL` | kor-travel-concierge-youtube | 형제 앱 kor-travel-concierge | base URL, 예: `http://127.0.0.1:12401` |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY` | kor-travel-concierge-youtube | kor-travel-concierge `API_KEYS` 중 하나 | `X-API-Key` 헤더로 전송 |
| `KOR_TRAVEL_GEO_*` | kor-travel-geo | (로컬 DB 위주, vworld 폴백 키는 kor-travel-geo가 관리) | 본 라이브러리는 kor-travel-geo client만 사용 |
| `KOR_TRAVEL_GEO_VWORLD_API_KEY` | kor-travel-geo (reverse geocoding), 디버그/admin UI frontend (MapLibre/VWorld), PinVi 사용자 UI (ADR-026) | VWorld (vworld.kr) | **공유 키**. 별도 발급 X. ADR-025 + ADR-026 |

## 3. provider별 발급 절차 (요약)

### 3.1 기상청 (KMA)

1. https://apihub.kma.go.kr 가입
2. "마이페이지" → "API 키 발급" → 본 프로젝트용 키 생성
3. `KMA_API_KEY` 환경변수에 저장
4. 사용 API: 단기예보(VilageFcstInfoService), 초단기실황, 중기예보, 특보

### 3.2 TourAPI (VisitKorea)

1. https://www.data.go.kr 가입
2. "TourAPI" 검색 → 활용 신청 → 자동 승인
3. 발급된 ServiceKey는 **URL-encoded** 형태와 **decoded** 형태 모두 받음.
   provider 라이브러리는 decoded를 권장.
4. `VISITKOREA_SERVICE_KEY` 환경변수에 decoded 형태 저장.

### 3.3 국가유산청 (krheritage)

1. https://www.khs.go.kr API 신청 (홈페이지에서 OpenAPI 항목 확인)
2. `KRHERITAGE_API_KEY` 환경변수

### 3.4 OpiNet

1. https://www.opinet.co.kr/api 가입 + 활용 신청
2. `OPINET_API_KEY` 환경변수
3. 호출 한도 — 분당 60회 정도 (provider 라이브러리에서 token bucket).

### 3.5 도로공사 (krex)

1. data.go.kr에서 "한국도로공사" 검색 → API 활용 신청
2. `KREX_API_KEY` 환경변수

### 3.6 국립해양조사원 (KHOA)

1. http://www.khoa.go.kr/api 활용 신청
2. `KHOA_API_KEY` 환경변수

### 3.7 AirKorea

1. data.go.kr "한국환경공단 에어코리아" 검색
2. `AIRKOREA_API_KEY` 환경변수

### 3.8 산림청 (krforest)

1. data.go.kr "산림청" 검색 — 여러 dataset (휴양림, 산악기상 등)
2. `KRFOREST_API_KEY` 환경변수

### 3.8.1 국립공원공단 (KNPS, `python-knps-api`) — **keyless (auth 불필요)**

ADR-028 amendment 2026-05-25 + knps-api PR#3/#4: 인증 ServiceKey 사용 안 함.
data.go.kr 직접 다운로드 URL (atchFileId + fileDetailSn + insertDataPrcus)로
모든 14건 file dataset 접근.

1. **활용 신청 불필요** — data.go.kr 파일데이터는 별도 인증 없이 다운로드 가능
   (`https://www.data.go.kr/cmm/cmm/fileDownload.do?...`). knps-api가 URL을
   카탈로그에 박아 둠.
2. **환경변수 없음** — `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 모두
   사용 안 함. `KnpsClient()` 생성 시 인증 인자 없음.
3. 사용 dataset: 공원경계(SHP)/탐방로/탐방안내소/위험지역/기상관측시설/화장실/
   문화자원/야영장/대피소/시설도로/특별보호구역 (공간 데이터 11건) +
   기초/탐방객 통계 (timeseries 2건, feature 본문 X) + 메타 카탈로그 1건.
   자세히는 `docs/etl/knps-feature-etl.md` (ADR-028 amendment §H).
4. 호출 한도 — `KnpsClient(max_rps=5.0)` 기본 (data.go.kr 정책 보수치).
   `KnpsClient(max_rps=10.0)` 등으로 조정 가능.
5. (이전) `knps_access_restrictions`/`knps_fire_alerts` notice API는 knps-api
   PR#3에서 source 삭제 — 산림청 (`python-krforest-api`) / 소방청 source로
   이전 (별도 후속 ADR).

### 3.9 Kakao Local

1. https://developers.kakao.com 앱 생성
2. REST API 키 발급
3. `KAKAO_LOCAL_REST_API_KEY` 환경변수
4. 호출: `Authorization: KakaoAK {KEY}` 헤더

### 3.10 NAVER Search

1. https://developers.naver.com/apps 앱 등록
2. "검색" API 활성화
3. Client ID, Client Secret 발급
4. `NAVER_SEARCH_CLIENT_ID`, `NAVER_SEARCH_CLIENT_SECRET`

### 3.11 Google Places API (New)

1. Google Cloud Console → 프로젝트 생성 → "Places API (New)" 활성화
2. API 키 생성 (제한 권장: HTTP referrer 또는 IP)
3. `GOOGLE_PLACES_API_KEY` 환경변수
4. 호출 시 **Field Mask 필수** (`X-Goog-FieldMask`) — 전화번호만 받으려면
   `places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber`
5. 비용 발생 가능 — 호출 빈도 관리

### 3.12 data.go.kr 표준데이터

표준데이터 5종은 별도 provider 라이브러리 없이 `kortravelmap.standard_data`의
내부 bounded asyncio client에서 처리한다. (코드 작성 단계에서 v1과 동일 패턴
재구현)

API 키 우선순위:

1. `DATAGOKR_API_KEY`
2. `DATA_GO_KR_SERVICE_KEY`
3. `PUBLIC_DATA_SERVICE_KEY`
4. `SERVICE_KEY`

### 3.13 kor-travel-concierge YouTube 후보 export

1. kor-travel-concierge가 `/api/v1/features/snapshot`과
   `/api/v1/features/changes`를 제공해야 한다(구 `kor-travel-concierge` 프로젝트명 변경,
   ADR-053).
2. kor-travel-map Dagster는 `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL`을 host root로 받고,
   path는 fetcher가 `/api/v1/features/{snapshot|changes}`로 붙인다.
3. `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY`는 kor-travel-concierge 운영 환경의 `API_KEYS` 중
   하나와 같아야 하며, `X-API-Key` 헤더로만 전송한다.
4. `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_SYNC_ENDPOINT=snapshot|changes`,
   `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_CURSOR`,
   `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_PAGE_SIZE`로 full/incremental pull을 조정한다.

### 3.14 문화체육관광부 (MCST, `python-mcst-api`)

1. 파일데이터 CSV 13 dataset은 **키 불요**(keyless) — `FileDataClient`가
   다운로드 페이지(culture.go.kr `filedatDtl.do` / data.go.kr `fileData.do`)를
   스크레이핑해 최신 CSV를 받는다(provider #6/#7/#11, T-220 재배선 #395 + T-223b).
   구 KCISA
   OpenAPI(`CultureOpenApiClient`)/ODCloud(`DataGoFileApiClient`) 경로는 폐기
   — KCISA OpenAPI는 공인 DNS 미해석 + KCISA 전용 발급키 필요(provider #6).
2. dataset당 1 run 상한은 `KOR_TRAVEL_MAP_MCST_MAX_ITEMS_PER_DATASET`(기본 50000
   — 실측 최대 24,537행의 약 2배 여유).
3. dataset 카탈로그(slug/다운로드 페이지)는 `python-mcst-api` `catalog.py`가
   정본 — krtour 측 메타표는 `kortravelmap.providers.mcst.MCST_FILE_DATASETS`
   (적재 13), 제외 3종 사유는 `MCST_EXCLUDED_FILE_DATASETS`.

## 4. 호출 정책 (provider 라이브러리가 책임)

공공 provider는 본 라이브러리가 직접 호출하지 않고 provider 라이브러리가 다음을
지켜야 한다(각 provider 저장소의 ADR로 박혀 있어야 함). `kor-travel-concierge-youtube`
REST export는 ADR-053 예외로, kor-travel-map Dagster fetcher가 같은 timeout/secret
마스킹 원칙을 따른다.

- `httpx.AsyncClient`로 호출 (`requests` 동기 금지).
- `tenacity` 재시도: 5xx/timeout만 3회 지수 backoff. 4xx 즉시 실패.
- 회로차단: 실패율 임계 초과 시 일정 시간 차단.
- 타임아웃: `httpx.Timeout(connect=2, read=8)` 권장.
- 인증: `SecretStr`로 settings에서 로드. 헤더에만 사용, URL/로그 금지.
- 호출 로그: structlog JSON 한 줄 — `{provider, endpoint, status, latency_ms,
  request_id}`.
- 쿼터: provider별 token bucket 또는 leaky bucket.

본 라이브러리는 provider client 호출 횟수만 `ops.api_call_log` 테이블에 기록
(옵션, `log_api_calls=True`).

## 5. 호출 빈도 제어

본 라이브러리에서 강제 가능한 추가 제어:

- `Dagster ConcurrencyConfig` (PinVi 측)으로 same API resource pool
  `max_concurrent=1` (SPEC V8 K-2).
- bulk 적재 시 page 단위 sleep (provider 라이브러리에서).
- `ProviderSyncState.next_run_after`로 다음 호출 시각 박음 — Dagster scheduler가
  이 값을 존중.

## 6. 키 회전 절차

1. 새 키 발급
2. `.env` (또는 vault)에서 새 키로 교체
3. 운영 노드에서 컨테이너 재시작
4. 기존 키 무효화 (provider 콘솔)
5. journal.md + ADR (회전 사유, 영향 범위)

## 7. provider 응답 변경 대응

provider API spec이 변경되면:
1. `python-*-api` 라이브러리에서 typed model 변경 + minor version
2. 본 라이브러리의 `providers/<name>.py` 변환 함수 조정 + fixture 추가
3. `SourceRecord.raw_payload_hash` 변경 → 새 row 생성 → schema drift 자동
   감지
4. `data_integrity_violations`에 `violation_type='schema_drift_detected'`
   기록 (옵션)
5. ADR (큰 변경이면)

## 8. 비용 관리

대부분의 한국 공공 API는 무료. 유료/한도 있는 것만:

- **Google Places API (New)**: 호출당 비용. Place phone enrichment는 candidate
  3개 미만으로 제한 (`PLACE_PHONE_MAX_CANDIDATES=3`).
- **VWorld API** (MapLibre GL + VWorld raster tile): 본 라이브러리
  디버그 UI frontend **및 PinVi 사용자 UI** (ADR-026)가 사용. 키는
  `kor-travel-geo` ADR-019의 `KOR_TRAVEL_GEO_VWORLD_API_KEY`를 **공유 사용**
  (ADR-025 사용자 보강 2026-05-25). 별도 발급 금지. frontend는 **Next.js**
  (ADR-025 2차 보강) 규약상 `NEXT_PUBLIC_VWORLD_API_KEY`로 노출 — 값은
  동일 출처. HTTP referrer 제한 권장 (backend 호스트 + PinVi frontend
  호스트).
- **Kakao Maps JS SDK**: **미사용** (ADR-026 — PinVi 사용자 UI도
  VWorld/MapLibre 계열로 통일, SPEC V8 v8_3 supersede). 본 항목은 reference로
  유지하되 비용/한도 모니터링 대상이 아니다.
- **OpiNet**: 분당 한도 — token bucket으로 보호.

## 9. 운영 모니터링

`ops.api_call_log`로 호출 추세 추적:

```sql
-- provider별 최근 1시간 호출 수와 평균 지연
SELECT provider,
       count(*) AS calls,
       avg(latency_ms) AS avg_ms,
       max(latency_ms) AS max_ms,
       sum(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS error_5xx
FROM ops.api_call_log
WHERE occurred_at >= now() - interval '1 hour'
GROUP BY provider
ORDER BY calls DESC;
```

Grafana 패널에 노출 (PinVi 측). 5xx 비율 임계 초과 시 알림.

## 10. 호출 안 함 (테스트 기본)

`tests/unit`, `tests/integration`, `tests/fixtures`는 **외부 API를 호출하지
않는다**. provider 응답은 fixture로 녹화 (`tests/fixtures/<provider>/*.json`)
하거나 VCR.py로 cassette.

라이브 호출이 필요한 시나리오:
- 디버그 UI에서 "라이브 호출" 옵션 (개발자 명시 트리거)
- nightly canary (kor-travel-map Dagster `provider_canary` asset)
- 운영 ETL

위 시나리오는 모두 provider 라이브러리에서 직접 호출하고, 본 라이브러리는
받은 결과만 변환한다.
