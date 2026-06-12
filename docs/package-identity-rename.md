# Package Identity Rename — `kor-travel-map` / `kortravelmap`

본 문서는 T-226 package identity clean cut의 정본이다. 결정은 ADR-054가 갖고,
실제 코드/패키지 이동은 T-226c 이후 별도 PR로 수행한다. T-226b는 대규모 rename을
바로 시작하기 전 실행 단위와 검증 게이트를 확정했다.

2026-06-13 사용자 재결정으로 Python import root와 권장 import 예시는
`kortravelmap` / `import kortravelmap as ktm`으로 조정됐다.
같은 날 추가 결정으로 CLI 목표명은 `ktmctl`로 맞춘다. PostgreSQL/RustFS 네이밍은
`kor-travel-geo` 패턴을 따른다: DB 이름은 underscore(`kor_travel_map`), RustFS
bucket/prefix는 hyphen(`kor-travel-map`)을 사용한다.
관련 형제 프로젝트의 GitHub repo/project 표시명도 함께 정렬한다:
`kor-travel-geo`는 `kor-travel-geo`, 기존 `kor-travel-concierge`/`kor-travel-concierge` 계열
프로젝트 표시는 `kor-travel-concierge`를 쓴다. 현재 코드/provider/env canonical
전환은 별도 clean cut PR에서 수행한다.

## 1. 사용자 결정

검색성과 직관성을 위해 public 배포명과 Python import root를 다음처럼 바꾼다.

| 항목 | 값 |
|------|----|
| 배포명 | `kor-travel-map` |
| Python import root | `kortravelmap` |
| 권장 import | `import kortravelmap as ktm` |

## 2. 현재값과 목표값

T-226a/T-226b 머지 직후 코드는 아직 현재값을 사용한다. 아래 목표값은 T-226c 이후
적용한다.

| 표면 | 현재 | 목표 |
|------|------|------|
| GitHub 저장소 이름 | `kor-travel-map` | 후속 결정. 코드/package clean cut과 분리 가능 |
| PyPI distribution(메인) | `kor-travel-map` | `kor-travel-map` |
| Python import(메인) | `from kortravelmap import ...` | `import kortravelmap as ktm` |
| Admin distribution | `kor-travel-map-admin` | `kor-travel-map-admin` |
| Admin import | `from kortravelmap.admin import ...` | `from kortravelmap.admin import ...` |
| Dagster distribution | `kor-travel-map-dagster` | `kor-travel-map-dagster` |
| Dagster import | `from kortravelmap.dagster import ...` | `from kortravelmap.dagster import ...` |
| CLI | `kor-travel-map ...` | `ktmctl ...` |
| env prefix | `KOR_TRAVEL_MAP_*` | `KOR_TRAVEL_MAP_*` |
| admin env prefix | `KOR_TRAVEL_MAP_ADMIN_*` | `KOR_TRAVEL_MAP_ADMIN_*` |
| 개발/운영 DB 이름 | `kor_travel_map` | `kor_travel_map` |
| Dagster metadata DB 이름 | `kor_travel_map_dagster` | `kor_travel_map_dagster` |
| RustFS bucket/prefix 표시명 | `kor-travel-map`, `krtour-uploads` | `kor-travel-map`, `kor-travel-map-uploads` |
| Docker/image/service 표시명 | `kor-travel-map*` | `kor-travel-map*` |
| 주소 서비스 프로젝트/레포명 | `kor-travel-geo` | `kor-travel-geo` |
| AI 후보/concierge 프로젝트/레포명 | `kor-travel-concierge`, `kor-travel-concierge` | `kor-travel-concierge` |

바꾸지 않는 값:

- Postgres schema: `feature`, `provider_sync`, `ops`
- PostGIS extension schema: `x_extension`
- OpenAPI versioned path prefix: `/v1`
- standalone 고정 포트: API `12301`, admin UI `12305`, Dagster `12302`
- TripMate 연동 방식: OpenAPI HTTP, DB/Python import 직접 의존 없음

## 3. 이행 원칙

- clean cut으로 진행한다. 구 `kortravelmap`, `kortravelmap.admin`, `KOR_TRAVEL_MAP_*`,
  `kor-travel-map` CLI 호환 shim은 만들지 않는다.
- 구현 PR은 T-226b 실행계획에 따라 T-226c Python import/package layout, T-226d
  runtime/deployment identity, T-226e 소비자 문서/client 전파로 나눈다.
- migration guide에는 이전 이름과 새 이름의 대응표를 제공한다.
- 새 Python import root는 top-level `kortravelmap`이다. quickstart와 예시는
  `import kortravelmap as ktm`를 우선한다.
- `src/krtour/__init__.py`를 만드는 방식의 과도기 shim은 금지한다. T-226c에서
  `src/kortravelmap/` layout으로 이동하고 import-linter 계약을 함께 갱신한다.

## 4. 남은 작업

- T-226b: 코드/package clean cut 실행계획
  - 완료 기준: `docs/reports/t-226b-package-clean-cut-plan-2026-06-12.md`
  - 코드 이동 전 분할 단위와 grep/테스트/OpenAPI gate 확정
- T-226c: Python import/package layout clean cut
  - `src/kortravelmap` → `src/kortravelmap`
  - `packages/kor-travel-map-admin/src/kortravelmap/admin` →
    `packages/kor-travel-map-admin/src/kortravelmap/admin`
  - `packages/kor-travel-map-dagster/src/kortravelmap_dagster` →
    `packages/kor-travel-map-dagster/src/kortravelmap/dagster`
  - pyproject package include/distribution/script 갱신
  - import-linter, mypy, tests, generated OpenAPI script 경로 갱신
- T-226d: runtime/deployment identity 전파
  - `KOR_TRAVEL_MAP_*` → `KOR_TRAVEL_MAP_*` settings/env 전환
  - DB 기본값, RustFS bucket/prefix 이름, Docker/image/service 표시명 갱신
- T-226e: 소비자 문서/client/migration guide
  - README/AGENTS/SKILL/architecture/provider-contract/integration-map 식별자 표 전환
  - TripMate 문서와 generated client 참조 갱신
  - `import kortravelmap as ktm` quickstart + migration guide 작성
