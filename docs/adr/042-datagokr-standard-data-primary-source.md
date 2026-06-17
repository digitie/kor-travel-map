# ADR-042: 전국관광지정보표준데이터 / 전국문화축제표준데이터 — `python-datagokr-api` 경유로 본 라이브러리에서 적재

- **상태**: accepted (PR#33, 2026-05-27)
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-034 9단계 1단계가 "축제(`python-visitkorea-api`)"였다. 그러나 사용자가
data.go.kr 표준데이터 2종을 1차 source로 사용하라고 지시:

- **전국관광지정보표준데이터** — 전국 관광지 점 정보 (place kind).
- **전국문화축제표준데이터** — 전국 축제/문화행사 (event kind).

두 표준데이터는 안정성/갱신주기/품질이 visitkorea TourAPI보다 좋다. provider
경계는 `python-datagokr-api` 라이브러리에서 client + typed model을 두고, 본
라이브러리는 그 model을 `Feature` bundle로 변환.

### 결정

- **축제 1차 source 변경**: visitkorea festival → `data.go.kr-standard`
  전국문화축제표준데이터. visitkorea는 enrichment(image / 상세 description /
  contentId 매핑)로 활용 (`source_role='enrichment'`).
- **관광지 표준데이터** — Sprint 5 박물관/미술관 라인에 추가. `data.go.kr-
  standard.tourism_points` (place kind, 카테고리는 `01 TOURISM` 아래 세분류로
  매핑 — kraddr-base category catalog의 8자리 코드).
- **provider 라이브러리 책임**: `python-datagokr-api`에서 client + typed
  model + iter_pages를 안정화. 본 라이브러리는 import + 변환 함수만.
- **dataset_key 명명**:
  - `datagokr_tourism_points` (관광지)
  - `datagokr_cultural_festivals` (축제)
- **Sprint 2 1단계 PR scope 갱신**: visitkorea festival → datagokr_cultural_
  festivals로 변경. visitkorea는 Sprint 2 끝물에 enrichment PR 별도.

### 근거

- 표준데이터는 행정안전부 / 공공데이터포털이 안정 운영 — 갱신 주기가 명시되어
  있고 schema 변경이 announce.
- visitkorea TourAPI는 contentId 매핑은 좋으나 좌표 nullable이 많고 축제
  데이터 정합성이 들쭉날쭉.
- "여러 source가 같은 entity를 채운다"는 본 라이브러리의 1차 use case →
  표준데이터 primary + visitkorea enrichment 패턴이 정석.

### 결과 (긍정)

- 축제 데이터 baseline 품질 향상.
- `python-datagokr-api`를 본격 활용 → standard data 5종(관광지/축제/주차장/
  도로/박물관)이 동일 client로 들어옴.

### 결과 (부정)

- visitkorea를 1차에서 enrichment로 강등하면 Sprint 2 1단계 fixture/test가
  바뀜.
- 완화: ADR-034 9단계 1단계 description을 본 ADR에서 amendment — "축제 (data.
  go.kr-standard 1차 + visitkorea enrichment)"로 변경.

### 후속

- `docs/sprints/SPRINT-2.md` §2.1 갱신 — provider 1단계가 `data.go.kr-
  standard` + `python-datagokr-api`로.
- `docs/etl/event-feature-etl.md` 1차 source를 datagokr 표준데이터로 정정,
  visitkorea는 enrichment 절로 보강.
- `docs/adr/README.md` ADR-034 amendment — 9단계 1단계 표 행 수정.
- `python-datagokr-api` 측 client/model 검증 (별도 라이브러리 작업).
- `pyproject.toml` `[providers]` extra에 `python-datagokr-api` 핀 (Sprint 2
  진입 시).
- 본 라이브러리 신규 모듈 `src/kortravelmap/providers/standard_data.py` —
  `tourism_points_to_bundles` / `cultural_festivals_to_bundles`.
