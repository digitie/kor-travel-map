# Common 의존성 출처

현재 산출물은 integration-9-review 검증 후보다. 부모가 제공한 동일 bytes와 원장을 사용한다.
공통 원천2c1182e765bb2bc53e01e0962cf2a73683891e1d,
지도 원천9a7a348b02d61969b394c681b024d5851eef836b,
Lightning CSS 원천748651cbd845971e65c411166ddee101745dab21,
serde-content 원천18e53fcf6f8ace093a292891b34fa3411192617d다.

c8 대비 UI/tokens의 변경 member는 각각 check-dependencies.mjs뿐이며 runtime/CSS는 동일하다.
core/web/Lightning CSS fix.4 bytes는 동일하다. 별도 CSS fix.5는 사용하지 않는다.
후속 native CI 메타데이터 변경은 위 배포 package의 Rust/JS bytes 변경이 아니다.

| 산출물 | 정확 버전 | SHA512 무결성 |
| --- | --- | --- |
| @kor-travel/ui | 0.2.0 | sha512-buhlDym3/Id355Cse+lwBsFk3G1nz3dY2XviAA+X82TZPXmcujYGxItRZafsY0t4xsWkiQ3jAxtCYjFZ7JsbEQ== |
| @kor-travel/tokens | 0.1.1 | sha512-+JglXOZhP11afRr/upKHWz7cjsj4IPIKYkoVh8lq9IcJTKU8zIHA8pirC1IOS1++gqOmMCnPkj1oi8EzJsTUyQ== |
| vworld-map-core | 1.0.1 | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-web | 1.0.3 | sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w== |
| lightningcss | 1.33.0+nativecss.fix.4 | sha512-zDQ03VJE37OlyBrLsRcsEdIVu0T4BXJKDH5y9//To6GlGN2UrKQGERFVAFblkPQ5ZEbhuOp5wpXxGARZNdbQLA== |

정본은 frontend [common-artifacts.json](../packages/kor-travel-map-admin/frontend/common-artifacts.json)이다.
사용5개 tgz만 frontend/vendor에 두며 RN은 설치하지 않는다. 동일 파일명의 재설치도
lock/vendor/중앙 원장을 대조하고 설치된 UI/tokens 검사기 bytes까지 확인했다.
기존 core1.0.0과 이전 후보의 불필요한 vendor는 제거했다.

kor-travel-common은 GPL-3.0-or-later이며 shadcn Radix의 MIT 원천 고지를 보존한다.
지도 web/core의 GPL-3.0-only LICENSE 본문·NOTICE·src 동봉 파일을 그대로 사용한다.
Lightning CSS의 MPL-2.0 및 대응 source archive·NOTICE와 포함 upstream 고지를 보존한다.
직접 개발 의존성은 root/frontend에 같은 fix.4를 두고 root override는 $lightningcss를 참조한다.
전역 CSS compiler alias나 private source 경로를 추가하지 않았다.

Python API/Dagster 공통 의존성은 이번 범위 밖이며 기존
aa232ad5f255233184de80eceaab2e9b6ccb00c9 Git 핀과 각 pyproject.toml을 유지한다.
