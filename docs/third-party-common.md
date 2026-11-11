# Common 의존성 출처

현재 정본은 integration-11-review 단일pack 검증 후보다. 별도 재pack은 하지 않는다.
공통 producer a35481349d6747b4f13b958ae64d9c0bbd0b5413,
지도 source 9a7a348b02d61969b394c681b024d5851eef836b,
Lightning CSS source 748651cbd845971e65c411166ddee101745dab21,
serde-content source 18e53fcf6f8ace093a292891b34fa3411192617d,
Radix source 1752a539c8d5ae57961a0fa2702d2573d48fefe7다.

C10→C11 UI/tokens는 내장 policy JSON 두 파일만 바뀌며 나머지117파일은 동일하다.
c9의 stock Scope와 달리 fix2는 실제 runtime 변경이므로 새 production build와 modal browser가 필요하다.
Scope1/C10 checkpoint와 과거 검증 로그는 통합 validation에 보존한다.

| 산출물 | 정확 버전 | SHA512 무결성 |
| --- | --- | --- |
| @kor-travel/tokens | 0.1.1 | sha512-85mqNJXqhTlA4RbtKUhmzx6rH6mOOeNmsXTJtCetQ5y8njLy+5XLZbdT6j1tf3ME9XQA6X63Ah4kmuLdqEZHbA== |
| @kor-travel/ui | 0.2.0 | sha512-BsRRdnJUp6FQ2KWkXtINb7IkrxxwnWFlLP/oVlNN4UXBKren7uTlnYT4iJsdaO98iA4Tn2EMPX06eT2uB5jEDA== |
| lightningcss | 1.33.0+nativecss.fix.4 | sha512-zDQ03VJE37OlyBrLsRcsEdIVu0T4BXJKDH5y9//To6GlGN2UrKQGERFVAFblkPQ5ZEbhuOp5wpXxGARZNdbQLA== |
| vworld-map-core | 1.0.1 | sha512-Djm14Arr7U0r7Sabj6P0V57CdzWIGaJmecklmY1hwrq1QUZJjMUFgkZfGRFalUo6AFzHEwwzOEzbJPMifGhINw== |
| vworld-map-rn | 1.0.1 | sha512-lgDBasKIEG2ElQ9jnHDB9pA+x04Xge9yzBb1NPPw1auyvlkQvxsq4NfRPIrw1VWiutcGiIefySLiVaZDUkO69Q== |
| vworld-map-web | 1.0.3 | sha512-HPXZcz/wP6tFsCZqlAbansWNICcZPubC+/V7rDWXYTQVlOBLl9cZQ1HSMJd25c2CZoMNreVFTQA0vzkVglkS1w== |
| @radix-ui/react-focus-scope | 1.3.1+kortravel.fix.2 | sha512-v3XweXrUSZ/QfrMVvYmsAkVNDnvcN21QKbSrViXYf0OQf5Ue9xSgqQIukgGjsYMEBQ5qxQW8fnOC9t1Y0ENPXw== |

정본은 frontend [common-artifacts.json](../packages/kor-travel-map-admin/frontend/common-artifacts.json)이다.
vendor7개를 보존하고 웹 사용6개만 설치한다. vworld-map-rn은 웹 의존성에 추가하지 않는다.
UI/tokens119파일 및 Scope15파일을 포함한 모든 설치 package 원문·도달 lock copy SRI를 실제 대조한다.
공통 실행 코드 pin은55a921b55d248106cbe320e7f5305f3d3cdb60fe,
정책은 최신 common frontend-dependencies.json, canonical은 명시 C11 원장을 사용한다.

kor-travel-common은 GPL-3.0-or-later이며 shadcn Radix의 MIT 원천 고지를 보존한다.
지도 web/core의 GPL-3.0-only LICENSE 본문·NOTICE·src 동봉 파일을 그대로 사용한다.
Lightning CSS의 MPL-2.0 source archive·NOTICE와 포함 upstream 고지, Radix의 MIT 고지를 보존한다.
Lightning CSS는 root/frontend 직접 dev 의존성과 $lightningcss override를 사용한다.
Scope는 root/frontend 직접 runtime file 의존성과 $@radix-ui/react-focus-scope override를 사용한다.
전역 CSS compiler alias나 private source 경로는 추가하지 않았다.

Python API/Dagster 공통 의존성은 이번 범위 밖이며 기존
aa232ad5f255233184de80eceaab2e9b6ccb00c9 Git 핀과 각 pyproject.toml을 유지한다.
