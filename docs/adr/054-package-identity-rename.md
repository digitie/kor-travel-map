# ADR-054: 배포명은 `kor-travel-map`, Python import root는 `kortravelmap`로 clean cut한다

### 상태

Accepted (2026-06-12) — T-226의 package identity rename 정본이다. 본 ADR은 목표
identity와 이행 범위를 확정한다. 실제 코드/패키지 이동은 T-226c 이후 별도 PR로 수행한다.
2026-06-13 사용자 재결정으로 Python import root와 권장 import 예시를
`kortravelmap` / `import kortravelmap as ktm`으로 조정했다.
같은 날 추가 결정으로 CLI 목표명은 `ktmctl`로 맞춘다. PostgreSQL/RustFS 네이밍은
`kor-travel-geo` 패턴을 따른다: DB 이름은 underscore(`kor_travel_map`), RustFS
bucket/prefix는 hyphen(`kor-travel-map`)을 사용한다.
현재 코드/provider/env canonical 전환은 별도 clean cut PR에서 수행한다.

### 배경

현재 public identity는 GitHub/PyPI distribution `kor-travel-map`, Python import
`kortravelmap`, CLI `kor-travel-map`, env prefix `KOR_TRAVEL_MAP_*`다(ADR-022/045/047).
하지만 "krtour" 축약어는 검색성과 직관성이 낮고, 사용자가 새 public 배포명과 import
관례를 다음처럼 확정했다.

- 배포명: `kor-travel-map`
- Python import root: `kortravelmap`
- 권장 import 예시: `import kortravelmap as ktm`

### 결정

T-226 clean cut의 목표 identity는 다음과 같다.

| 표면 | 현재 | 목표 |
|------|------|------|
| PyPI distribution(메인) | `kor-travel-map` | `kor-travel-map` |
| Python import root(메인) | `kortravelmap` | `kortravelmap` |
| 권장 import | `from kortravelmap import ...` | `import kortravelmap as ktm` |
| API distribution | `kor-travel-map-api` | `kor-travel-map-api` |
| API import | `kortravelmap.api` | `kortravelmap.api` |
| Admin frontend package | `kor-travel-map-admin` | `kor-travel-map-admin` |
| Dagster distribution | `kor-travel-map-dagster` | `kor-travel-map-dagster` |
| Dagster import | `kortravelmap.dagster` | `kortravelmap.dagster` |
| CLI | `kor-travel-map` | `ktmctl` |
| env prefix | `KOR_TRAVEL_MAP_*` | `KOR_TRAVEL_MAP_*` |
| API env prefix | `KOR_TRAVEL_MAP_API_*` | `KOR_TRAVEL_MAP_API_*` |
| 개발/운영 DB 이름 | `kor_travel_map` | `kor_travel_map` |
| Dagster metadata DB 이름 | `kor_travel_map_dagster` | `kor_travel_map_dagster` |
| RustFS bucket/prefix 표시명 | `kor-travel-map`, `krtour-uploads` | `kor-travel-map`, `kor-travel-map-uploads` |
| Docker/image/service 표시명 | `kor-travel-map*` | `kor-travel-map*` |
| 주소 서비스(의존) 프로젝트/레포명 | `kor-travel-geo` | `kor-travel-geo` |

Postgres schema 이름(`feature`, `provider_sync`, `ops`, `x_extension`)과 고정 포트
(API `12701`, admin UI `12705`, Dagster `12702`)는 바꾸지 않는다. 외부 경계인 OpenAPI
`/v1` 계약은 서비스 identity가 바뀌어도 유지한다.

### 이행 원칙

- clean cut으로 진행한다. 구 `kortravelmap` / `kortravelmap.api` / `KOR_TRAVEL_MAP_*`
  호환 shim은 만들지 않는다(ADR-046과 동일한 이유).
- 단, migration guide에는 "이전 이름 → 새 이름" 표를 제공한다.
- 코드 이동은 T-226b 실행계획을 거쳐 T-226c에서 수행한다:
  `src/kortravelmap` → `src/kortravelmap`,
  `packages/kor-travel-map-api/src/kortravelmap/api` →
  `packages/kor-travel-map-api/src/kortravelmap/api`,
  `packages/kor-travel-map-dagster/src/kortravelmap_dagster` →
  `packages/kor-travel-map-dagster/src/kortravelmap/dagster` layout을 적용하고,
  import-linter/contracts/test/OpenAPI export 경로를 함께 바꾼다.
- runtime/deployment identity는 T-226d에서 수행한다: env prefix, 기본 DB 이름,
  Dagster metadata DB 이름, RustFS bucket/prefix 이름, Docker/image/service name,
  advisory lock/log/metric label을 새 이름으로 전환한다.
- 외부 경계 문서 전파는 T-226e에서 수행한다: generated client/OpenAPI 문서, README
  quickstart, examples/snippets, migration guide를 갱신한다.
- 이 ADR이 머지된 시점의 코드/문서 식별자 표는 아직 "현재 상태"를 말한다. 목표 identity는
  `docs/package-identity-rename.md`를 정본으로 본다.

### 결과

- T-226a는 ADR-054와 `docs/package-identity-rename.md`를 정본으로 완료한다.
- T-226b는 `docs/reports/t-226b-package-clean-cut-plan-2026-06-12.md`로 분할 단위와
  검증 게이트를 확정한다.
- T-226c/d/e가 끝나기 전까지 `kor-travel-map` / `kortravelmap` 표기는 코드와 현재 운영값을
  가리키는 사실로 남는다.
- T-226c/d/e 완료 후 README/AGENTS/SKILL/architecture/provider-contract/integration-map의
  식별자 표를 목표 identity로 일괄 전환한다.
