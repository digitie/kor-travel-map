# SPRINT-3.md — KNPS/트래킹 + 국가유산 + 정합성 Phase 1

> **상태**: proposed (Sprint 2 종료 후 Sprint 3 진입 PR로 accepted 전환)
>
> **목적**: ADR-034 9단계의 ⑤~⑥ — 국립공원/트래킹 (`python-knps-api` +
> `python-krforest-api` trails) + 국가유산 (`python-krheritage-api`). area/
> route geometry 처리 + ADR-033 Phase 1 정합성 검증 (F1~F3) 도입.

## 1. 진입 조건 (Sprint 2 DoD)

- [ ] Sprint 2 모든 DoD 충족 (`SPRINT-2.md §7`)
- [ ] 4 provider (visitkorea/kma/opinet/krex) + 보조 (airkorea/krforest_weather
      /khoa_weather) 적재 안정
- [ ] 디버그 UI backend 라우터 + OpenAPI drift gate green
- [ ] Coverage bar 65% pass
- [ ] Record Linkage scoring 첫 검증 완료 (휴게소 sibling group)

## 2. 산출물

### 2.1 Provider ⑤ — 국립공원/트래킹

**`python-knps-api` 14 dataset 적재** (`docs/knps-feature-etl.md` 사양):
- API 3 (visitor_statistics / access_restrictions / fire_alerts):
  - `visitor_statistics` — timeseries (별도 처리, v2 1차 범위 시점에 따라 또는
    Sprint 5로 연기)
  - `access_restrictions` — kind=notice, `notice_type='access_restriction'`,
    `payload.domain='forest'` (ADR-027 generic)
  - `fire_alerts` — kind=notice, `notice_type='fire_alert'`,
    `payload.domain='forest'` (ADR-027 generic)
- File 11:
  - `knps_park_boundaries` — kind=area, MultiPolygon, `area_kind='national_park'`
  - `knps_trails` — kind=route, LineString
  - `knps_visitor_centers` — kind=place, `01060101` TOURISM_INFORMATION_CENTER_PUBLIC
  - `knps_hazard_zones` — kind=area, **`area_kind='hazard_zone'`** (ADR-027)
  - `knps_weather_stations` — kind=weather anchor
  - `knps_restrooms` — kind=place, `05060000` CONVENIENCE_TOILET
  - `knps_cultural_resources` — kind=place, RESOURCE_TYPE 분기 (사찰/유적/기타)
  - `knps_campgrounds` — kind=place
  - `knps_shelters` — kind=place, **`03080100` LODGING_MOUNTAIN_SHELTER_KNPS**
    (ADR-027 신규 PlaceCategory)
  - `knps_recommended_courses` — kind=route, difficulty 포함
  - `knps_park_photos` — feature 본문 X, `feature_files` + `source_links`

**`python-krforest-api` trails 추가**:
- `krforest_trails` — kind=route (산림청 숲길, knps_trails와 sibling 후보)

**module**:
- `src/krtour/map/providers/knps.py` — 14 dataset 전부
- `src/krtour/map/providers/krforest_trails.py` — krforest_trails 한정

**SHP/GeoJSON parser 위치 결정** (ADR-028 §B 후속):
- **본 라이브러리 내**: `src/krtour/map/providers/knps/_parser.py`. 의존
  `pyproj>=3.6`, `pyshp>=2.3` (또는 `pyogrio`). EPSG:5179/5186 → WGS84 변환
  + CP949 인코딩 처리 (kraddr-geo ADR-005 패턴).
- 또는 upstream knps-api `[geo]` extra에 PR로 추가 — Sprint 3 진입 PR
  설계 단계에서 cost/benefit 평가 후 결정.

### 2.2 Provider ⑥ — 국가유산 (`python-krheritage-api`)

- **datasets**:
  - `krheritage_heritage_features` (place, search_list)
  - `krheritage_gis_spca` (area, MultiPolygon, 사적/명승 boundary)
  - `krheritage_gis_3070426` (area, MultiPolygon, 천연기념물 boundary)
  - `krheritage_event_list` (event, kind=event)
- **Feature.kind**: `place` + `area` + `event`
- **category** (`01.07 TOURISM_HERITAGE` 하위):
  - `01070100` `TOURISM_HERITAGE_TEMPLE`
  - `01070200` `TOURISM_HERITAGE_PALACE_ROYAL_TOMB`
  - `01070300` `TOURISM_HERITAGE_HISTORIC_SITE`
  - `01070400` `TOURISM_HERITAGE_HANOK_FOLK_VILLAGE`
- **module**: `src/krtour/map/providers/krheritage.py`
- **사찰/한옥은 MOIS sibling 후보** — Sprint 3 시점엔 MOIS 미적재라
  dedup_review_queue 영향 0. Sprint 5에서 MOIS sibling으로 재검증.

### 2.3 ADR-033 Phase 1 — `feature_consistency_reports` (T-201a)

- `ops.feature_consistency_reports` 테이블 alembic migration:
  ```sql
  CREATE TABLE ops.feature_consistency_reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    severity_max TEXT NOT NULL CHECK (severity_max IN ('OK','WARN','ERROR')),
    cases JSONB NOT NULL,
    summary JSONB NOT NULL
  );
  CREATE INDEX idx_reports_batch ON ops.feature_consistency_reports (batch_id);
  CREATE INDEX idx_reports_started ON ops.feature_consistency_reports (started_at DESC);
  ```
- F1 (orphan source): `SourceRecord` 있는데 `Feature` 없음 — severity=ERROR
- F2 (detail 누락): `Feature.kind='place'`인데 `PlaceDetail` 없음 (다른 kind
  도 동일) — severity=ERROR
- F3 (CRS drift): `Feature.coord_5179 ≠ ST_Transform(Feature.coord, 5179)` —
  severity=ERROR
- **Dagster 게이트 미적용** — 검증만, mv_refresh swap은 차단 안 함 (Phase 1
  은 "관측" 목적).
- 디버그 UI `/integrity` 라우터 추가 (`features.py` 다음으로).

### 2.4 ADR-032 Coverage Sprint 3 상향

- 전체 75% / core 85% / providers 65% / infra/client/api 70%
- `dto/` 100% branch 유지

### 2.5 dedup_review_queue 첫 입주

- knps `cultural_resources`(사찰) + krheritage `temple` 간 dedup 후보 생성.
- queue size 작아 (수십~수백 건) 운영 디버깅 용이.
- Sprint 4 MOIS 진입 전에 룰 안정.

## 3. Sprint 3 ADR/T 항목 진척

| 항목 | 상태 (진입 시) | DoD (Sprint 3 종료) |
|------|---------------|---------------------|
| ADR-027 (forest 카테고리 확장) | accepted (Sprint 1 적용) | knps_shelters → `03080100` + hazard_zones → `area_kind='hazard_zone'` 동작 |
| ADR-028 (python-knps-api 등록) | accepted (Sprint 1) | 14 dataset 적재 + Dagster asset 11종 |
| ADR-033 (정합성 단계 도입) | accepted (Sprint 1) | Phase 1 (F1~F3) 코드 + 통합 테스트, 게이트 미적용 |
| upstream knps-api PR | merged | shelter/barrier maki + `verified` 승격된 dataset 확인 |

## 4. 비목표 (Sprint 3)

- MOIS provider (Sprint 4)
- 휴양림/수목원 (Sprint 5)
- 박물관/미술관 (Sprint 5)
- Phase 2 정합성 F4~F8 + Dagster 게이트 (Sprint 5)
- KNPS `visitor_statistics` timeseries 본격 처리 (Sprint 5 또는 별도)

## 5. 위험 / 차단 사유

- **SHP/GeoJSON 파싱 위치 결정**: Sprint 3 진입 PR 설계 단계에서 본 라이브러리
  vs upstream knps-api `[geo]` extra 선택. 본 라이브러리 권고 (ADR-006 정신).
- **사찰/한옥 dedup**: knps_cultural_resources(사찰) + krheritage_heritage_features
  (temple)이 sibling 가능. 좌표 + 명칭 비교만으로 정확 sibling group 생성
  검증 필요.
- **dataset verification_status `planned`**: knps-api에 일부 dataset이
  `planned` 상태로 남아 있을 수 있음 — Sprint 3 진입 전 upstream live
  test로 `verified` 승격 권고.

## 6. 종료 조건 (Sprint 3 → Sprint 4)

- [ ] Provider ⑤⑥ 모듈 + fixture + 통합 테스트 모두 merge
- [ ] ADR-033 Phase 1 (F1~F3) 코드 + 통합 테스트 green
- [ ] `feature_consistency_reports` 테이블 + 일 1회 Dagster asset 동작
- [ ] dedup_review_queue 첫 운영 시작 (룰 안정 확인)
- [ ] Coverage bar 75% pass
- [ ] `docs/journal.md` Sprint 3 종료 회고 entry
- [ ] `docs/sprints/SPRINT-4.md` 진입 PR 준비 (특히 SPRINT-4 분할 여부
      4a/4b 결정)
