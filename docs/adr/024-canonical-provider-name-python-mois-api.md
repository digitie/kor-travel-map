# ADR-024: canonical provider name 정정 — `python-krmois-api` → `python-mois-api`

- **상태**: accepted (ADR-022의 식별자 표 및 provider-contract.md의 canonical name
  세부 정정. ADR-006/ADR-022의 큰 결정은 그대로 유지)
- **날짜**: 2026-05-24
- **결정자**: Claude (사용자 위임)
- **컨텍스트**: v1 산출물을 바탕으로 v2 docs를 작성하면서 행정안전부(MOIS)
  지방행정 인허가 OpenAPI 라이브러리를 `python-krmois-api` (`import krmois`)로
  표기했다. 실제 라이브러리 확인 결과:
  - PyPI distribution 이름: `python-mois-api`
  - Python import 이름: `mois`
  - GitHub: `digitie/python-mois-api`
  - pyproject.toml `project.name`: `python-mois-api`
  - README 명시: "설치 패키지 이름은 `python-mois-api`, import 패키지 이름은
    `mois`입니다"
  
  `krmois`는 본 라이브러리(v1) 내부에서만 쓰던 alias였고 실제 라이브러리에는
  존재하지 않음.

- **결정**:
  - canonical provider name: **`python-mois-api`** (변경)
  - Python import: `from mois import MoisClient` (변경)
  - `CANONICAL_PROVIDER_NAMES`에 `python-mois-api` 등록
  - `LEGACY_PROVIDER_ALIASES`에 다음 추가 (호환):
    - `"krmois"` → `"python-mois-api"`
    - `"mois"` → `"python-mois-api"`
    - `"pykrmois"` → `"python-mois-api"`
    - `"python-krmois-api"` → `"python-mois-api"` (이미 작성된 docs 호환)
  - 본 라이브러리에서 import path: `kortravelmap.providers.mois` (ADR-022 namespace)
  - loader 모듈: `kortravelmap.mois`
  - dataset_key prefix: `mois_*` (예: `mois_license_features`,
    `mois_license_features_bulk`, `mois_license_features_history`)
  - source_entity_type: `license_place` (변경 없음)

- **근거**:
  - 외부 라이브러리의 실제 이름과 일치 → 사용자/에이전트 혼동 방지
  - PyPI distribution 이름을 canonical로 사용하는 v2 표준(ADR-022)과 정합
  - `LEGACY_PROVIDER_ALIASES`로 v1 호환 유지 — 갑작스러운 BREAKING 회피

- **결과 (긍정)**:
  - import path와 PyPI 이름이 일치
  - 신규 에이전트가 `python-mois-api` GitHub repo를 바로 찾을 수 있음
  - alias로 점진 마이그레이션 가능

- **결과 (부정)**:
  - 기존 v2 docs (`docs/krmois-license-feature-etl.md`, `docs/architecture/provider-contract.md`,
    이전 ADR text 등)에 `python-krmois-api` 표기 남아 있음 → 본 ADR PR에서 일괄
    rename.
  - `docs/krmois-license-feature-etl.md` 파일명도 `docs/etl/mois-license-feature-etl.md`로
    변경 또는 alias 유지 결정 필요 (본 ADR에서는 **파일명도 변경** — git mv).

- **후속**:
  - `docs/architecture/provider-contract.md` §2 (canonical names) + §3 (dataset_key) + §4
    (카탈로그) 갱신
  - `docs/krmois-license-feature-etl.md` → `docs/etl/mois-license-feature-etl.md`
    (git mv) + 내용 정정
  - 새 `docs/etl/mois-feature-etl.md`로 full lifecycle 통합 또는 license 전용 +
    full lifecycle 두 docs 유지 — 본 PR에서 후자 채택 (`mois-license-feature-etl.md`
    유지 + `mois-feature-etl.md` 신규 = 상위 개요 + 4단계 lifecycle).
  - 모든 신규/기존 docs의 `krmois.*` import 예시 → `mois.*`로 정정
  - PR description에 변경 요약
