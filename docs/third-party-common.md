## 2026-11-12 — integration-8-review 채택

부모 단일pack의 common670a753bc17f956f71bdc28385d6241a6e4ee017과
동일 upstream9a7a348b02d61969b394c681b024d5851eef836b를 채택한다.
정확 버전·파일·SHA512는 frontend common-artifacts.json이 정본이다.
UI0.2.0/tokens0.1.1/core1.0.1/web1.0.3에 더해 Lightning CSS1.33.0+nativecss.fix.4를
직접 개발 의존성으로 사용한다. CSS원천748651cbd845971e65c411166ddee101745dab21,
serde-content18e53fcf6f8ace093a292891b34fa3411192617d의 source/NOTICE/MIT 고지 동봉파일을 보존한다.
이전 후보 정보는 아래 이력이다.

# Common 의존성 출처

현재 frontend 산출물은 **integration-6-review 통합 검증 후보**이며 정식 릴리스가 아니다.
공통 원천은 `a14301c01a87d7d56e8da5bcf24c0a7f145d05a1`,
지도 원천은 `9a7a348b02d61969b394c681b024d5851eef836b`다.
부모의 최종 metadata/native CSS 검토 뒤 단일 pack과 release freeze를 확정한다.

`kor-travel-common`은 GPL-3.0-or-later이며 기존 Map의 GPL 경계를 유지한다.
shadcn Radix 원천 MIT 고지를 보존한다. 지도 web/core는 GPL-3.0-only이며
부모가 제공한 LICENSE 본문·NOTICE·src 동봉 산출물을 그대로 사용한다.

| 산출물 | 버전 | SHA512 무결성 |
| --- | --- | --- |
| `@kor-travel/ui` | `0.2.0` | `sha512-VznXMJCxgixE5Ym3Ipnf8i3KCM+65rXcUoEwvigHavMeJv1TPmZocuL1as74x+ZP0d/5dR12gvN0jhV9fvktcQ==` |
| `@kor-travel/tokens` | `0.1.1` | `sha512-GqHyu2fwh6OKhZARTMI5aJSOom71jQhoe2Bb895sX4cG7YZ7CFzqAL1xYDv8AXlM+pBYr2A+Xy9kJAzOnnWofw==` |
| `vworld-map-core` | `1.0.1` | `sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw==` |
| `vworld-map-web` | `1.0.3` | `sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w==` |

정본 원장은 frontend의 [common-artifacts.json](../packages/kor-travel-map-admin/frontend/common-artifacts.json)이다.
웹에서 사용하는 네 tgz만 frontend/vendor에 복사하며 RN 패키지는 설치하지 않는다.
명시적 file 재설치로 package-lock integrity를 갱신하고 AST/정책·원장·lock·vendor·중앙 원장을 검사한다.
이전 UI 0.1.0-dev.9/tokens 0.1.0 및 core 1.0.0 vendor와 활성 의존성 참조는 제거했다.

Python API/Dagster 공통 의존성은 이번 변경 범위 밖이며 기존
`aa232ad5f255233184de80eceaab2e9b6ccb00c9` Git 핀과 각 pyproject.toml을 유지한다.
