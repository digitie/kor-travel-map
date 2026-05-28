# ETL Live 통합 검증 리포트 (2026-05-28)

> 작성: Claude (claude worktree). 범위: Sprint 2 종료 직후 사용자 지시
> "etl 로직 live test → 데이터 유입·정합성·DB 적재·debug UI 검증 + 상세 리포트".
> **본 문서에는 API 키 값을 절대 기재하지 않는다** (키 이름·마스킹만).

## 1. 개요

- **대상**: 디버그 UI ETL preview `?source=live` 11개 dataset
  (`packages/krtour-map-debug-ui/etl_live.py`의 `LIVE_LOADER_REGISTRY`).
- **방법**: 각 provider 공공 API를 실 키로 호출 → 본 lib `providers/*` 변환 함수
  통과 → DTO(FeatureBundle/WeatherValue/PriceValue) 정합성 점검.
- **환경**: WSL(ext4, `/mnt/f`) + provider 키는 `packages/krtour-map-debug-ui/
  .env`(gitignore, 커밋 금지)에 매핑. 실행은 debug-ui 패키지 디렉터리 cwd
  (pydantic-settings `.env` 상대 경로).
- **키 출처**: 사용자 제공(apihub/krex EX/datagokr) + provider repo `.env`
  (opinet/kma). ADR-005/035 — 코드 외부 보관.

## 2. ETL live 검증 결과 (11 / 11)

| # | dataset | 결과 | 정합성 메모 |
|---|---------|------|-------------|
| 1 | kma_short_forecast | ✅ 1000건 | observed/valid KST(+09:00) 100%, metrics PCP/POP/PTY/REH/SKY/SNO |
| 2 | kma_ultra_short_nowcast | ✅ 8건 | KST 100%, T1H/REH/RN1/PTY/UUU/VEC |
| 3 | kma_ultra_short_forecast | ✅ 60건 | KST 100%, LGT 포함. 첫 호출 HTTP 429(rate limit)→재시도 정상 |
| 4 | datagokr_cultural_festivals | ✅ 정상 | dataset 15013104, 실 축제 데이터. `api.data.go.kr` DNS 간헐 불안정(재시도 후 200) |
| 5 | kma_weather_alerts | ✅ 19건 | data.go.kr `getWthrWrnList` fallback(notice), 호우→heavy_rain_warning 등 |
| 6 | krex_rest_areas | ✅ 98건 | place Feature. null-name placeholder 행 skip(PR#62) 후 |
| 7 | krex_rest_area_weather | ✅ endpoint 정상 | restWeatherList 200 (해당 시간대 0건 — 데이터 시점 의존) |
| 8 | krex_rest_area_prices | ⚠️ 0건(crash 제거) | `curStateStation`이 주유가격 미제공(필드 불일치) — EX endpoint 이슈 |
| 9 | krex_traffic_notices | ❌ HTTP 404 | `incident` endpoint deprecated — 유효 키로도 404 |
| 10 | opinet_fuel_station_details | ✅ 1건 | place Feature, KATEC→WGS84 좌표 in-range. auto-discovery(PR#64) |
| 11 | opinet_gas_station_prices | ✅ 2건 | PriceValue, unit=KRW/L, opinet_gas_station |

**요약**: 9/11 정상 유입 + 정합성 OK. krex 2종(prices/notices)은 EX OpenAPI
endpoint 변경/deprecated 이슈(키 무관, 아래 §4).

### 정합성 점검 항목 (통과)
- 좌표: WGS84 lon∈[124,132]/lat∈[33,39] 범위 검사 — 위반 0.
- 시각: WeatherValue observed_at/valid_at가 KST aware(+09:00).
- FeatureBundle: feature_id ↔ source_link.feature_id, source_record_key ↔
  source_link.source_record_key 일치. notice/place kind 정상.
- notice_type/category/marker: NOTICE_TYPES·PlaceCategory 유효값.

## 3. 발견·수정 (이번 세션 PR)

| PR | 내용 |
|----|------|
| #57·#58 | datagokr·weather_alerts live → 11/11 dataset live 등록 |
| #59 | Sprint 2 종료 (coverage 50→65) |
| #60 | weather_alerts **apihub primary + data.go.kr fallback** + **키 이름 drift 정정** + **starlette<1.0 CI 회귀 hotfix** |
| #62 | krex robustness — null-name 휴게소 skip(Feature ValidationError 수정) + 가격 Decimal guard + food 404 best-effort |
| #64 | opinet **auto-discovery**(lowTop10/aroundAll) — UNI_ID 없이 live 동작 |

### 주요 버그 (실데이터로만 드러남)
1. **starlette 1.0 CI 회귀**: 신규 starlette(1.2.0)가 TestClient에 `httpx2`를
   hard-require → debug-ui 테스트 전면 collection 실패. `starlette>=0.40,<1.0` +
   `httpx>=0.27,<1.0` 핀으로 해소(PR#60). **다른 모든 debug-ui PR도 차단했던 이슈**.
2. **krex rest_areas ValidationError**: EX `serviceAreaRoute`가 모든 표시필드
   null인 placeholder 행 반환 → `Feature(name="")` 검증 실패. `rest_areas_to_bundles`
   가 빈 name/uni_id 행을 skip하도록 수정(PR#62).
3. **가격 Decimal crash**: 비숫자 가격 문자열 → `InvalidOperation`. guard 추가(PR#62).

## 4. 사람이 조치할 항목 (Action Items)

### 4.1 KMA apihub 활용신청 (특보 구조화 region)
- 키 `gagX…`(apihub.kma.go.kr authKey)는 **인증은 되나 활용신청된 API 0건** —
  `wrn_now_data`/`wrn_now_data_new`/`kma_sfctm2` 전부 HTTP 403
  "활용신청이 필요한 API 입니다".
- **조치**: apihub.kma.go.kr 로그인 → 예특보>기상특보>특보현황(`wrn_now_data`)
  **활용신청** → 승인 후 같은 키로 자동으로 apihub primary(구조화 특보구역
  REG_ID) 경로 동작. **현재는 data.go.kr `getWthrWrnList` fallback으로 정상
  유입 중**(관서 단위 coarse region)이라 긴급도 낮음.

### 4.2 krex EX OpenAPI endpoint 정정 (→ python-krex-api upstream)
- EX 키(`2668138864`/`1371545112`)는 **유효**. serviceAreaRoute(221)/
  curStateStation(226)/restWeatherList(200) 정상.
- **deprecated/오류 endpoint (유효 키로도 404 또는 필드 불일치)**:
  - `/openapi/trafficapi/incident`(돌발) → 404.
  - `/openapi/restinfo/restMenuList`(식음료 가격) → 404. (`restBrandList`는 200이나
    브랜드 목록이라 가격 아님.)
  - `/openapi/business/curStateStation`은 주유가격이 아닌 휴게소 목록 반환(필드 불일치).
- **조치**: data.ex.co.kr `introduce02`(JS 렌더라 자동 추출 불가, 브라우저 확인)에서
  현재 유효한 돌발/식음료가격/주유가격 endpoint를 확인 → **python-krex-api 카탈로그
  + client 정정** → 본 lib `providers/krex.py` 매핑 + debug-ui loader 반영.
  rest_areas/weather endpoint는 정상.
- 참고: 사용자 `.env`의 krex 키 이름은 `KEX_GO_API_KEY`이나, EX 호출에는
  `KEX_EX_API_KEY`(=EX 전용 키)가 필요. 본 검증은 사용자 직접 제공 EX 키 사용.

### 4.3 키 이름 drift (settings 문서 정정 완료, PR#60)
- provider repo `.env` 실제 키 이름이 debug-ui 가정과 달랐음 → settings docstring +
  `.env.example`에 source 명시:
  - 공통 `DATA_GO_KR_SERVICE_KEY` → kma 동네예보 / datagokr / (krex의 data.go.kr) / visitkorea
  - `OPINET_API_KEY`(certkey) → opinet
  - `KEX_GO_API_KEY`/`KEX_EX_API_KEY` → krex(data.ex.co.kr `key`)
  - `KMA_APIHUB_AUTH_KEY` → kma apihub(`authKey`, data.go.kr serviceKey와 별개)

## 5. DB 적재 검증 (진행 예정 — task #116)

`infra/models.py` ORM(FeatureRow/SourceRecordRow/SourceLinkRow) + Alembic
upgrade로 testcontainer PostGIS에 FeatureBundle 적재 → 재조회·정합(coord_5179
STORED generated = ST_Transform, JSONB detail round-trip, FK) 검증하는 통합
테스트 작성 예정. (docker는 WSL 가용 확인.)

## 6. Debug UI E2E (진행 예정 — task #117)

WSL에 node 설치 → uvicorn(backend, 8087) + next dev(frontend, 8610) 기동 →
Windows Playwright로 ETL preview 페이지 + REST(/debug/etl/*) e2e 검증 예정.

## 7. 결론

- **ETL provider→DTO 변환 파이프라인은 11/11 dataset에서 live 동작 확인**(9 정상,
  2 krex는 EX endpoint upstream 이슈로 부분). 정합성(좌표/시각/키/타입) 통과.
- 실데이터 검증이 fixture만으로는 못 잡는 3개 실버그(starlette CI, null-name
  Feature, Decimal crash)를 드러냄 → 전부 수정.
- 잔여: apihub 활용신청 + krex EX endpoint 정정(사람) / DB 적재·Playwright(후속 PR).
