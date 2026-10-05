# 공통·Map·PinVi 규범 가이드 독립 좁은 리뷰
실행 ID: J-NORMATIVE-GUIDE-20261006-B.
판정: **PASS**. 아래 P3 설명 개선은 비차단 권고다. 이 보고서는 문서 정확성·도입 절차·링크 검토이며 새 제품 FULL 리뷰나 운영 성공 판정이 아니다.

## 고정 bytes와 범위
- Common docs/runbooks/dagster-adoption.md: ed75f864e2719d1130e94013c58cda8b15d14fb87904bda50ea3c5758cee7c6d
- Map docs/runbooks/common-dagster.md: 5d199456a2ee01e600f8359c444f487a215dbd2846cd9eaaed1d9acfed9fd525
- PinVi docs/runbooks/common-dagster.md: b17feb6412cde0651f7df822e5da9a6ea822b527fbe884b3467e1291a407f19d

고정 제품 Common a960bdb114d99a2ac1b9608a77b240635806e551 / Map 1a3c4673790f51daa1a2f5ccf803d4e31673bad6 / PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f의 필요한 계약만 Git 객체로 비교했다. 전체 회귀를 재실행하지 않았다. peer 원문은 읽지 않았고 증거 링크는 존재만 확인했다.

## 확인 결과
- 의존성 분리가 정확하다. Map API/Dagster는 a960, PinVi API HTTP는 1f8e339c, ETL 복구는 73e3ff8b이며 UI dev.6는 별도 frozen artifact다. guide가 앱 인증·RBAC·URL·DB 게시 정합성과 shared daemon의 소유자를 혼동하지 않는다.
- HTTP plain 4MiB/전체 10초/별도 cleanup 50ms, 압축 거부·실패 client 폐기·uncertain write 결과·last-good snapshot 경계가 기존 공용/소비자 계약과 맞는다. HTTP200 degraded/잘못된 응답을 정상 0건으로 만들지 않고 별도 old active 조회를 유지하도록 설명한다.
- UI nullable job/cap, controlled selection 및 null detail, public CSS/tokens/data-slot, 모바일 기본 옵션/내부 표 스크롤, 소비자 auth/Link 주입을 설명한다. 공통 표시 컴포넌트를 인증·쓰기 권한의 소유자로 오인하지 않는다.
- 경량 health CLI는 설치된 protobuf를 쓰고 proxy와 자식 reply를 모두 확인하며 standard module/file/package profile만 허용한다. custom/stateful/알려지지 않은 metadata를 정상으로 추측하지 않고, health 판정과 restart/worker 회수를 구분한다.
- 새 bounded tick 절차는 두 앱 고정 코드와 일치한다. Map summary query의 두 literal 및 PinVi admin_etl의 두 literal 모두 limit 3와 STARTED/SKIPPED/SUCCESS/FAILURE를 지정한다. schema/resolver 버전 의존성, upgrade 재검증, legacy NULL/tie 경계, HTTP 상한 유지가 명시돼 있다. Map의 다른 상세 endpoint query도 전부 변경됐다고 주장하지 않는다.
- 모든 상대 링크 대상은 존재하며 공용 UI heading anchor도 일치한다. 외부 GitHub 링크의 source 경로는 로컬 고정 Git 객체로 확인했다. 네트워크 접근성 검사는 하지 않았다.

## 비차단 권고
J-GUIDE-P3-01 / P3 OPEN — PinVi docs/runbooks/common-dagster.md:49~57.
최초 T-370의 “운영 재구축은 이 PR 범위 아님/fixture DB만 사용” 설명과 67~73행의 현재 paired 운영 후속이 같은 문서에 있다. 소비자가 검증 절을 현재 PR 전체 범위로 읽으면 혼동할 수 있다. 해당 앞 구간을 “최초 T-370 채택의 검증 범위”로 명시하고 후속 운영은 67행 이후/별도 검증 기록을 따른다고 한 문장 연결하는 것을 권한다. 후속 절이 이미 별도로 존재하므로 필수 계약 위반 또는 BLOCK 사유로 보지 않는다.

## EXECUTED / NOT_RUN
EXECUTED: 지정 세 파일 SHA256, 문서 전체 읽기, 상대 링크 존재 및 heading, 고정 pyproject Git pin과 tick query 네 literal 비교.
NOT_RUN: 제품 테스트·설치·운영 접속·배포/회전/build/native/UI/D1/D2. 문서의 실제 query 2.077초·기존 테스트 결과는 작성자/증거 주장으로 읽었으며 본인의 재실행 결과로 합산하지 않았다. 현재 frozen pair의 actual rebuild/live는 별도 운영 영수증으로 판정해야 한다.

제품·문서·기존 원문을 수정하지 않았으며 새 ignored 보고서만 작성했다.

검토/보존 시각(UTC): 2026-10-05T19:00:01.390561+00:00
