# ADR-022: `krtour` implicit namespace + Python import path `kortravelmap`

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 초기 v2 설계에서 Python import 이름을 `kor_travel_map`(flat)으로
  잡았다. 사용자가 `kortravelmap`(namespace)로 변경을 지시. 근거:
  - `kor-travel-geo`의 ADR-015가 `kraddr` implicit namespace(PEP 420)를
    채택. 동일 도메인의 다른 라이브러리(`kraddr-base`, `kor-travel-geo`,
    `kraddr-...`)가 같은 namespace를 공유 → `kraddr.base`, `kraddr.geo`.
  - `krtour` namespace를 동일 패턴으로 채택하면 향후 `krtour.weather`,
    `krtour.poi` 같은 자매 라이브러리 추가 시 일관된 import 경로 확보.
- **결정**:
  - PyPI distribution 이름은 `kor-travel-map` (그대로 유지).
  - **Python import 이름**은 `kortravelmap` (PEP 420 implicit namespace).
  - 디렉토리 layout: `src/kortravelmap/__init__.py` (있음), `src/krtour/__init__.py`
    (**없음** — implicit namespace).
  - `pyproject.toml` `[tool.setuptools.packages.find]`에 `namespaces = true`,
    `include = ["kortravelmap*"]`.
  - import-linter 계약의 모든 module 경로를 `kor_travel_map.*` → `kortravelmap.*`로
    교체.
  - 환경변수 prefix는 `KOR_TRAVEL_MAP_*` 유지 (이름 일관성 — env는 underscore 표준).
  - CLI 명령 이름은 `kor-travel-map` 유지.
  - 별도 패키지 `kor-travel-map-api`(ADR-055)의 Python import는
    `kortravelmap.api` (sibling under `kortravelmap` namespace, 별도 distribution이
    같은 namespace를 공유). 디렉토리 layout: `packages/kor-travel-map-api/src/
    kortravelmap/api/__init__.py`.
- **근거**:
  - kraddr 라이브러리 군과 패턴 정합.
  - 향후 자매 패키지 확장 자유.
  - PEP 420은 표준이며 setuptools/poetry/uv 모두 지원.
- **결과 (긍정)**:
  - 도메인 패키지 군이 통일된 namespace 사용.
  - 별도 distribution이 같은 namespace를 공유해도 충돌 없음.
- **결과 (부정)**:
  - 일부 IDE/타입체커가 implicit namespace에 약함 → mypy/pyright 명시적 path
    설정 필요할 수 있음.
  - `src/krtour/__init__.py`를 실수로 만들면 namespace가 깨짐 → CI에서 차단
    체크 (`tests/unit/test_no_namespace_init.py`).
- **후속**:
  - 모든 docs/code 예시 import path 갱신.
  - `pyproject.toml` `package-dir` / `packages.find` / `package_data` 갱신.
  - import-linter 계약 갱신.
  - 디렉토리 layout 가이드 (`docs/architecture/architecture.md`, `docs/dev-environment.md`).
  - 별도 패키지 `kor-travel-map-admin`의 pyproject + README도 동일 패턴 적용.
