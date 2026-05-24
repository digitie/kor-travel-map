# external-apis.md — Provider API 키 발급/호출 정책

본 문서는 본 라이브러리가 의존하는 provider 라이브러리들이 호출하는 외부 API의
발급/호출 정책 reference다. **본 라이브러리 자체는 외부 API를 직접 호출하지
않는다** — 호출은 `python-*-api` provider 라이브러리에 위임한다 (ADR-006).

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
| `KRADDR_GEO_*` | python-kraddr-geo | (로컬 DB 위주, vworld 폴백 키는 kraddr-geo가 관리) | 본 라이브러리는 kraddr-geo client만 사용 |

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

표준데이터 5종은 별도 provider 라이브러리 없이 `krtour.map.standard_data`의
내부 bounded asyncio client에서 처리한다. (코드 작성 단계에서 v1과 동일 패턴
재구현)

API 키 우선순위:
1. `DATAGOKR_API_KEY`
2. `DATA_GO_KR_SERVICE_KEY`
3. `PUBLIC_DATA_SERVICE_KEY`
4. `SERVICE_KEY`

## 4. 호출 정책 (provider 라이브러리가 책임)

본 라이브러리는 외부 API를 직접 호출하지 않지만, provider 라이브러리가 다음을
지켜야 한다 (각 provider 저장소의 ADR로 박혀 있어야 함):

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

- `Dagster ConcurrencyConfig` (TripMate 측)으로 same API resource pool
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
- **Kakao Maps JS SDK** (frontend, TripMate 사용자 UI 측): 일 호출 한도. 모니터링
  필요. *(본 라이브러리의 디버그 UI는 Kakao 미사용 — `maplibre-vworld-js` +
  VWorld 사용, ADR-025)*
- **VWorld API** (`maplibre-vworld-js` 의 raster/vector tile): 본 라이브러리
  디버그 UI frontend가 사용. 키는 `python-kraddr-geo`의
  `KRADDR_GEO_VWORLD_API_KEY` 공유 또는 디버그 UI 전용 `VITE_VWORLD_API_KEY`
  별도 발급. HTTP referrer 제한 권장.
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

Grafana 패널에 노출 (TripMate 측). 5xx 비율 임계 초과 시 알림.

## 10. 호출 안 함 (테스트 기본)

`tests/unit`, `tests/integration`, `tests/fixtures`는 **외부 API를 호출하지
않는다**. provider 응답은 fixture로 녹화 (`tests/fixtures/<provider>/*.json`)
하거나 VCR.py로 cassette.

라이브 호출이 필요한 시나리오:
- 디버그 UI에서 "라이브 호출" 옵션 (개발자 명시 트리거)
- nightly canary (TripMate Dagster `provider_canary` asset)
- 운영 ETL

위 시나리오는 모두 provider 라이브러리에서 직접 호출하고, 본 라이브러리는
받은 결과만 변환한다.
