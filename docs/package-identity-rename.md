# Package Identity Rename — `kor-travel-map` / `kortravel`

본 문서는 T-226 package identity clean cut의 정본이다. 결정은 ADR-054가 갖고,
실제 코드/패키지 이동은 T-226b/c에서 별도 PR로 수행한다.

## 1. 사용자 결정

검색성과 직관성을 위해 public 배포명과 Python import root를 다음처럼 바꾼다.

| 항목 | 값 |
|------|----|
| 배포명 | `kor-travel-map` |
| Python import root | `kortravel` |
| 권장 import | `import kortravel as kt` |

## 2. 현재값과 목표값

T-226a 머지 직후 코드는 아직 현재값을 사용한다. 아래 목표값은 T-226b/c에서 적용한다.

| 표면 | 현재 | 목표 |
|------|------|------|
| GitHub 저장소 이름 | `python-krtour-map` | 후속 결정. 코드/package clean cut과 분리 가능 |
| PyPI distribution(메인) | `python-krtour-map` | `kor-travel-map` |
| Python import(메인) | `from krtour.map import ...` | `import kortravel as kt` |
| Admin distribution | `krtour-map-admin` | `kor-travel-map-admin` |
| Admin import | `from krtour.map_admin import ...` | `from kortravel.admin import ...` |
| CLI | `krtour-map ...` | `kor-travel-map ...` |
| env prefix | `KRTOUR_MAP_*` | `KOR_TRAVEL_MAP_*` |
| admin env prefix | `KRTOUR_MAP_ADMIN_*` | `KOR_TRAVEL_MAP_ADMIN_*` |
| 개발/운영 DB 이름 | `krtour_map` | `kor_travel_map` |
| Dagster metadata DB 이름 | `krtour_map_dagster` | `kor_travel_map_dagster` |
| Docker/image/service 표시명 | `krtour-map*` | `kor-travel-map*` |

바꾸지 않는 값:

- Postgres schema: `feature`, `provider_sync`, `ops`
- PostGIS extension schema: `x_extension`
- OpenAPI versioned path prefix: `/v1`
- standalone 고정 포트: API `12301`, admin UI `12305`, Dagster `12302`
- TripMate 연동 방식: OpenAPI HTTP, DB/Python import 직접 의존 없음

## 3. 이행 원칙

- clean cut으로 진행한다. 구 `krtour.map`, `krtour.map_admin`, `KRTOUR_MAP_*`,
  `krtour-map` CLI 호환 shim은 만들지 않는다.
- 구현 PR은 한 번에 너무 커지면 T-226b를 코드/package layout, T-226c를 배포/소비자
  전파로 나눈다.
- migration guide에는 이전 이름과 새 이름의 대응표를 제공한다.
- 새 Python import root는 top-level `kortravel`이다. quickstart와 예시는
  `import kortravel as kt`를 우선한다.
- `src/krtour/__init__.py`를 만드는 방식의 과도기 shim은 금지한다. T-226b에서
  `src/kortravel/` layout으로 이동하고 import-linter 계약을 함께 갱신한다.

## 4. 남은 작업

- T-226b: 코드/package clean cut
  - `src/krtour/map` → `src/kortravel`
  - admin package import/layout 전환
  - pyproject package include/distribution/script 갱신
  - import-linter, mypy, tests, generated OpenAPI script 경로 갱신
  - `KRTOUR_MAP_*` → `KOR_TRAVEL_MAP_*` settings/env 전환
- T-226c: 배포/소비자 전파
  - PyPI metadata, Docker/image/service 표시명 갱신
  - README/AGENTS/SKILL/architecture/provider-contract/integration-map 식별자 표 전환
  - TripMate 문서와 generated client 참조 갱신
  - `import kortravel as kt` quickstart + migration guide 작성
