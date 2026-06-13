# T-226b package clean cut 실행계획

작성일: 2026-06-12
작성자: Codex
관련 결정: ADR-054, `docs/package-identity-rename.md`

## 1. 결론

T-226b는 `kor-travel-map` / `kortravelmap` clean cut을 실제 코드 PR로 들어가기 전
분할 단위와 게이트를 확정하는 작업으로 닫는다. 코드 이동 자체는 다음 PR부터
수행한다.

이유는 단순 문서 표기 변경이 아니라 Python package layout, admin package, Dagster
code location, settings/env prefix, CLI, Docker/CI, generated OpenAPI/client, TripMate
소비 문서가 동시에 흔들리는 변경이기 때문이다. 한 PR에서 전부 바꾸면 리뷰와 롤백
단위가 지나치게 커진다.

따라서 후속 작업은 다음처럼 나눈다.

| 작업 | 범위 | PR 성격 |
|------|------|---------|
| T-226c | Python import/package layout clean cut | 코드 이동 + import/lint/test |
| T-226d | runtime/deployment identity 전파 | env/DB/Docker/CI/service name |
| T-226e | 소비자 문서/client/migration guide | README/docs/generated client/TripMate 문서 |

## 2. 현재 표면 계량

2026-06-12 `origin/main` 기준으로 다음 표면이 확인됐다.

| 항목 | 수치/경로 |
|------|-----------|
| Python/설정/문서 후보 파일 | 908개 |
| `kortravelmap` 참조 파일 | 368개 |
| `KOR_TRAVEL_MAP` 참조 파일 | 86개 |
| 메인 package | `src/kortravelmap` |
| API package | `packages/kor-travel-map-api/src/kortravelmap/api` |
| Dagster package | `packages/kor-travel-map-dagster/src/kortravelmap_dagster` |
| import-linter root | `kortravelmap` |
| main console script | `kor-travel-map = "kortravelmap.cli.main:main"` |
| API console script | 없음 |
| Dagster module | `kortravelmap.dagster.definitions` |

대표 settings 파일(`src/kortravelmap/settings.py`,
`packages/kor-travel-map-api/src/kortravelmap/api/settings.py`)은 codegraph impact가
파일 단위 1개로만 잡혔지만, 실제 위험은 문자열 기반 env prefix, 테스트 fixture,
Docker/CI 설정, 문서 예시가 함께 바뀌는 데 있다.

## 3. 확정 layout

T-226c 이후 Python import layout은 다음을 목표로 한다.

| 표면 | 목표 |
|------|------|
| 메인 import root | `kortravelmap` |
| 권장 사용 | `import kortravelmap as ktm` |
| DTO/core/infra/provider import | `kortravelmap.dto`, `kortravelmap.core`, `kortravelmap.infra`, `kortravelmap.providers` |
| 메인 package path | `src/kortravelmap` |
| API import | `kortravelmap.api` |
| API package path | `packages/kor-travel-map-api/src/kortravelmap/api` |
| Dagster import | `kortravelmap.dagster` |
| Dagster package path | `packages/kor-travel-map-dagster/src/kortravelmap/dagster` |
| main distribution | `kor-travel-map` |
| API distribution | `kor-travel-map-api` |
| dagster distribution | `kor-travel-map-dagster` |
| main CLI | `ktmctl` |
| API CLI | 없음 |

구 `kortravelmap`, `kortravelmap.api`, `kortravelmap.dagster`, `KOR_TRAVEL_MAP_*`,
`kor-travel-map*` 호환 shim은 만들지 않는다. `src/krtour/__init__.py`를 만들지 않는다는
기존 금지 규칙도 계속 유효하며, T-226c 완료 뒤에는 `src/krtour/` 자체가 없어져야 한다.

## 4. T-226c 실행 절차

T-226c는 코드 import와 package metadata만 다룬다.

1. 최신 `main`에서 새 branch를 만들고 `codegraph sync`를 실행한다.
2. 파일 이동을 먼저 수행한다.
   - `src/kortravelmap` → `src/kortravelmap`
   - `packages/kor-travel-map-api/src/kortravelmap/api` →
     `packages/kor-travel-map-api/src/kortravelmap/api`
   - `packages/kor-travel-map-dagster/src/kortravelmap_dagster` →
     `packages/kor-travel-map-dagster/src/kortravelmap/dagster`
3. import를 기계적으로 바꾼다.
   - `kortravelmap.` → `kortravelmap.`
   - `kortravelmap.api` → `kortravelmap.api`
   - `kortravelmap.dagster` → `kortravelmap.dagster`
4. `pyproject.toml` 계열을 갱신한다.
   - `project.name`
   - `[project.scripts]`
   - `tool.setuptools.packages.find.include`
   - `tool.setuptools.package-data`
   - `tool.importlinter.root_package`
   - import-linter layer 목록
   - `tool.coverage.run.source`
   - `tool.mypy.mypy_path`
   - Dagster `module_name`
5. 테스트와 스크립트 import를 갱신한다.
6. OpenAPI export script import가 바뀌면 `openapi.json` / `openapi.user.json`을
   재생성한다.

T-226c PR의 grep gate:

```bash
grep -R "from krtour\.map\|import krtour\.map\|krtour\.map_admin\|krtour\.map_dagster" \
  src packages tests scripts alembic pyproject.toml
grep -R "src/krtour\|packages/kor-travel-map-admin\|packages/kor-travel-map-dagster" \
  .github scripts packages pyproject.toml
```

위 grep은 active code/config에서 결과가 없어야 한다. migration 문서와 archive 문서의
이전 이름 설명은 예외로 둔다.

T-226c 최소 검증:

```bash
python -m ruff check .
python -m mypy --strict src/kortravelmap
python -m mypy --strict packages/kor-travel-map-api/src
python -m mypy --strict packages/kor-travel-map-dagster/src
lint-imports
python -m pytest tests/unit -q
python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --check
```

## 5. T-226d 실행 절차

T-226d는 runtime identity를 바꾼다.

- `KOR_TRAVEL_MAP_*` → `KOR_TRAVEL_MAP_*`
- `KOR_TRAVEL_MAP_API_*` → `KOR_TRAVEL_MAP_API_*`
- 기본 DB 이름 `kor_travel_map` → `kor_travel_map`
- 기본 Dagster metadata DB 이름 `kor_travel_map_dagster` → `kor_travel_map_dagster`
- RustFS bucket/prefix 표시명 `kor-travel-map`, `krtour-uploads` →
  `kor-travel-map`, `kor-travel-map-uploads`
- Docker image/service/container 표시명 `kor-travel-map*` → `kor-travel-map*`
- advisory lock namespace, 로그/metric service label, compose profile 이름 중 사용자 가시
  identity를 새 이름으로 전환

T-226d에서도 env alias는 만들지 않는다. 로컬 `.env.example`, 문서, CI secret 예시,
Docker compose, systemd/standalone runbook을 같은 PR에서 맞춘다.

## 6. T-226e 실행 절차

T-226e는 소비자 전파와 안내 문서를 다룬다.

- README quickstart를 `import kortravelmap as ktm` 기준으로 재작성한다.
- `docs/package-identity-rename.md`를 migration guide로 승격한다.
- AGENTS/SKILL/CLAUDE/architecture/provider-contract/integration-map의 식별자 표를
  목표값으로 일괄 전환한다.
- generated client와 TripMate 문서가 distribution/service 이름을 직접 참조하는지
  확인한다.
- `kor-travel-map` / `kortravelmap` 표기는 migration guide, ADR history, archive 문서에만
  남긴다.

## 7. 병행 작업 주의

- T-212e는 다른 agent가 병행 중이다. T-226c/d/e 시작 전마다 `main`을 fetch/rebase하고,
  T-212e closure PR이 머지됐는지 확인한다.
- T-225는 T-212e 결과가 머지된 뒤 실행한다. T-226 계열이 먼저 PR로 올라가더라도,
  T-225의 live row 수/P99/offline upload 증거 확인을 대체하지 않는다.
- T-226c 이후 다른 agent가 기존 import path로 새 코드를 추가하면 conflict가 커진다.
  코드 rename PR은 가능한 한 짧게 열어 둔다.
