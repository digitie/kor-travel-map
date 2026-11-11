# Common 의존성 출처

현재 frontend 산출물은 **integration-5-review 통합 검증 후보**이며 정식 릴리스가 아니다.
공통 원천 commit은 `789e6d2`이며, 최종 리뷰 뒤 부모가 immutable 원천 SHA와 단일 pack을 확정한다.
지도 원천은 `digitie/maplibre-vworld-react` main `9c46c57181d433c91f7e8837c4e4396204e9b583`에
부모가 재현한 web ES2022 컴파일 수정을 포함한 후보다. 최종 upstream 수정 commit은 부모 확정이 필요하다.

`kor-travel-common`은 GPL-3.0-or-later이며 기존 Map의 GPL 경계를 유지한다.
shadcn Radix 원천의 MIT 고지와 지도/하위 의존성 고지를 tgz 안에 보존한다.

| 산출물 | 버전 | SHA512 무결성 |
| --- | --- | --- |
| `@kor-travel/ui` | `0.2.0` | `sha512-m81yqLBWVdTwA1bwRB/HVOdhi2KFQV5ijMh2QfkxYIV5YUI7o7q7YK8qFCejqqUsz2FAXDPgHm8rcFjibbqfZQ==` |
| `vworld-map-core` | `1.0.0` | `sha512-tP++7XNg9UYXeeUc+aX8q+RD6/dkVzZuBSXPHUKEqHIRobLjUo1HcPEJruOU0bUzHGxnJL/8reIM7xI+vXYaUw==` |
| `@kor-travel/tokens` | `0.1.1` | `sha512-95d/E3rHhORo8etrQear9Phtj9PYgoek5yRueAEGFZkXxMGbfrywyH7hjYKVnDRgJak4rotJ653MOWTyKTY+sQ==` |
| `vworld-map-web` | `1.0.3` | `sha512-9S0TUlgu4ky9ztjkanf0lhoijydhcX5ehHtyQB1jla+rGnuPLK4POiH4wIb2v5ATKuO5hOnHEG534gfyuEH+5g==` |

정본 원장은 frontend의 [common-artifacts.json](../packages/kor-travel-map-admin/frontend/common-artifacts.json)이다.
동일 파일을 frontend/vendor에 복사하고 명시적 file 의존성 재설치로 package-lock integrity를 갱신한다.
CI `check:dependencies`는 원장·lock·manifest·직접 소스에 대한 AST 검사를 모두 실행한다.
이전 UI 0.1.0-dev.9/tokens 0.1.0 vendor는 제거했다.

Python API/Dagster 공통 의존성은 이번 변경 범위 밖이며 기존
`aa232ad5f255233184de80eceaab2e9b6ccb00c9` Git 핀과 각 pyproject.toml을 유지한다.
