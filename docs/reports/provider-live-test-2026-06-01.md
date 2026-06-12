# Provider 다종 실데이터 라이브 적재 테스트 (2026-06-01)

사용자 지시 — geocoder v2 전환 후 kma/opinet/krforest 등 다른 provider DB 적재를
실데이터로 검증. 서비스키는 각 provider 라이브러리의 `.env`에서 확인.

## 1. 환경

- 실행: WSL ext4 `~/dev/kor-travel-map` venv, provider 라이브러리는 NTFS
  (`F:\dev\python-*-api`)에 `PYTHONPATH`로 주입. provider 라이브러리는 ADR-006상
  본 lib가 런타임 import하지 않으므로, 라이브 스크립트에서 provider model →
  본 lib Protocol **어댑터 dataclass**로 감싸 변환.
- 적재: testcontainers `postgis/postgis:16-3.5-alpine`, alembic 0001~0006.
- 서비스키(`.env`): opinet `OPINET_API_KEY` / kma·krheritage·datagokr
  `DATA_GO_KR_SERVICE_KEY` / krex `KEX_EX_API_KEY`+`DATA_GO_KR_SERVICE_KEY` /
  knps keyless.

## 2. 결과 요약

| provider | 데이터셋 | 라이브 | 변환 | 적재 | category | 비고 |
|----------|---------|--------|------|------|----------|------|
| **opinet** | 주유소(유가) | 54 | 54 | ✅ 54 | `06020000` | 서울시청 5km, 좌표 54/54, place |
| **krheritage** | 국가유산 | 12 | 12 | ✅ 12 | `01070100`/`01070000` | place, 좌표 12/12 |
| **datagokr** | 표준데이터 축제 | 20 | 20 | ✅ 20 | `01000000` | event, 좌표 14/20 |
| **kma** | 기상특보 | 7 | 7 | ✅ 7 | `99000000` | notice, getWthrWrnList |
| **krex** | 고속도로 휴게소 | 60 | 60 | ✅ 60 | `06040101` | upstream `entrpsNm` fix 후 재검증(§4) — 좌표 60/60, place |
| **krforest** | 휴양림/수목원 | — | — | — | — | 본 lib provider 모듈 **미구현**(ADR-034 Sprint 5) |

모든 적재 케이스에서 `coord_5179` STORED generated SRID=5179 검증(ADR-012).

## 3. 발견 — 본 lib 코드 개선 (실데이터로 발견, 본 PR에서 수정)

**notice alias map에 KMA 기상특보 종류 누락.** `weather_alerts_to_notice_bundles`가
KMA 특보 `풍랑`/`강풍`/`태풍`/`건조`/`한파`/`폭풍해일`/`황사` 및 base type `호우`/
`대설`(주의보·경보 suffix 없는 단독형)을 `NoticeDetail.notice_type`으로 넘길 때
`normalize_notice_type`이 alias를 못 찾아 `ValidationError`로 적재 실패했다.

- 수정: `src/kortravelmap/dto/notice.py` `_ALIAS_MAP`에 전용 canonical 보유
  종류(`호우`→heavy_rain / `대설`·`대설주의보`·`대설경보`→heavy_snow) + 전용 없는
  종류 7종(`강풍`/`풍랑`/`태풍`/`건조`/`한파`/`폭풍해일`/`황사`)→generic
  `weather_alert` 추가. 원문 특보명은 `Feature.name`/payload에 보존.
- 검증: 수정 후 KMA 특보 7건 실데이터 적재 성공(notice, `99000000`). unit test
  `test_normalize_notice_type_kma_weather_alerts` 추가.

## 4. 발견·해소 — provider 라이브러리 측 이슈 (본 lib 대상 아님, ADR-044)

**krex(`python-krex-api`) 휴게소 list 파싱 실패 → upstream fix 후 해소.** 최초
`client.restarea.list_all` 호출 시 `KrexParseError: restAreaNm/serviceAreaName is
required`. raw 응답 직접 확인 결과 data.go.kr `tn_pubr_public_rest_area_api`의
휴게소명 필드가 **`entrpsNm`**("강릉(강릉)")인데, krex 라이브러리는
`restAreaNm`/`serviceAreaName`을 요구해 **upstream API 필드명 변경에 미추종**이었다.

- 책임: data 정합성 1차 책임은 provider 라이브러리(ADR-044) → `python-krex-api`가
  `entrpsNm` alias 추가로 해소. **upstream PR#6 (`fix/restarea-entrpsNm-field`,
  커밋 `ea4c08d`) 머지 확인** — `client.py` `name=str(_required(row, "entrpsNm",
  "restAreaNm", "serviceAreaName"))`. 본 lib `rest_areas_to_bundles` 변환 자체는
  최초부터 정상(데이터만 받으면 동작).
- **재검증(2026-06-01, upstream fix 후)**: 휴게소 60건 fetch(좌표 60/60) → 60
  bundle 변환 → PostGIS 60 적재, `coord_5179` SRID=5179 60/60, category
  `06040101` 60/60 — **PASS**.
- 본 lib `KrexRestAreaItem` Protocol엔 `uni_id`가 필요하나 `RestArea` 모델엔 없어
  자연키 합성(`휴게소명::노선::방향::lon::lat`) — `::` 구분자(ADR-009, `|` 금지).
  이 데이터셋은 `route_name`/`direction`이 비어(None) 휴게소명+좌표가 사실상 키.

## 5. 어댑터 매핑 노트 (재현용)

- **opinet** `Station`(WGS84 `lon`/`lat`) → `station_name←name`, `brand_code←brand.value`,
  `address←address_road or address_jibun`, `longitude/latitude←Decimal(lon/lat)`.
- **krheritage** `HeritageDetail` → key 필드는 **nested `.key.ccba_*`**, `name←name_ko`,
  `heritage_type←category`(enum 아님), `designated_date←parse("YYYYMMDD")`, WGS84 직접.
- **datagokr** `PublicCulturalFestival` → `management_no` 없음 → `fstvl_nm::주소` 합성,
  float 좌표 → Decimal, `organizer_name←mnnst_nm`, `provider_org_name←instt_nm`.
- **kma** `getWthrWrnList`는 untyped `.raw`(`stnId`/`title`/`tmFc`/`tmSeq`)만 제공 →
  `title` 파싱으로 특보종류/level 추출, `tmFc`→issued_at, region 구조 없어 stnId를
  synthetic region으로. 자연키 `alert_id::region_code`.
- 자연키 구분자는 모두 `::`(make_feature_id가 `|` 금지, ADR-009).

## 6. 미검증 / 후속

- ~~**krex**: `python-krex-api`의 `entrpsNm` 필드 미추종 해소 후 재검증.~~ **완료
  (2026-06-01)** — upstream PR#6 fix 후 휴게소 60건 적재 PASS(§4).
- **krforest**: 본 lib provider 변환 모듈 미구현(ADR-034 Sprint 5). 구현 후 적재 검증.
- **knps**(국립공원): keyless file dataset — 본 리포트 범위 외(별도 CsvPreview 경로).
- geocoder 보강(reverse) 주입 시 좌표 보유 record의 bjd_code 100% 보강은
  `mois-live-test-2026-06-01.md` §5에서 확인됨(동일 geocoder 적용 가능).

## 7. 결론

opinet/krheritage/datagokr/kma/**krex** 5종 provider의 변환·적재 경로가 **실데이터로
정상 동작**함을 확인(좌표 변환·5179 generated·place/event/notice 분기 모두 검증).
실데이터 검증으로 notice alias map 갭 1건을 발견·수정했고, krex는 upstream 라이브러리
`entrpsNm` 미추종을 provider 책임(ADR-044)으로 분계 → upstream PR#6 fix 후 재검증
PASS. krforest는 본 lib 미구현(ADR-034 Sprint 5)으로 제외.
