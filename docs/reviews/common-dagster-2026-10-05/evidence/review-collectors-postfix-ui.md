# 운영 수집 하니스 독립 후속 리뷰

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **하니스 정적 검토 PASS**. 제품 builtin FULL PASS는 변경하지 않는다. 실제 fourth rebuild/runtime/native/browser/운영 테스트 PASS를 주장하지 않는다.

실행 ID: J-COLLECTORS-POSTFIX-20261006. 검토/보존 시각: 2026-10-05T17:11:47.459905+00:00. 범위는 Weather ignored 하니스 다섯 파일만이다. 소스·운영·공개 archive를 수정하거나 다른 리뷰어 원문을 읽지 않았다.

## 고정 검토 bytes

- map-builtin-success-receipt-collect.py: 9eb7745e0f31de1465a93fb24a56b26d37b548398781070205b2ab3d08f1b226
- map-operating-screenshots-collect.py: 1087bcafd40bca6fc3a65ce245f8154302ce965d06b9f5eb02770a2bddaa7070
- map-pinvi-operating-ui.mjs: 7e4b9d49ac8739787f267fad16b53b02cca87930289823a8550f12c4aa554f78
- map-pinvi-operating-ui-launch.py: 56f361c7085ce01adcd36fb818b95c91dc1461f2e34485076afe82216dd19fee
- map-pinvi-operating-test-collect.py: b133388b0676c5b3ffe0ef3ae55f658979e74e5d04f90b3467a5cef45140e54c

## 이전 finding disposition

1. 초기 P2 성공 receipt 연결 부족: **FIXED**. success collector 7–12에서 동일 bytes로 attestation source를 검증하고 36–39에서 transaction_id/deploy_run_id, pinset, schema heads를 연결하며 46에서 같은 bytes를 hash한다. 19–26의 성공/정수 returncode/committed/deployed/resumedFalse와 정확한 열 필드 검증이 fail-closed한다. warnings 원문 대신 warning_count만 내보낸다. 설치 Manager 호출부의 열 필드 계약은 부모 검증 근거이며 본인이 실제 설치 호스트에서 재검증한 것은 아니다.
2. 초기 P2 캡처 provenance 부족: **FIXED**. 새 UUID·attestation/source/container/image identity, 컨테이너 실행 시간 안의 result 시간, 네 app/browser 조합의 인증·쿠키 정리·last-good/recovery 및 정확히 여덟 capture digest를 연결한다. UI는 기존 선택 상세·모바일 폭·조건부 키보드 assertions를 유지한다. launch는 이전 result/PNG가 있으면 덮어쓰기 전에 거절한다.
3. 초기 P2 전송 실패 후 재시도 불가: **FIXED**. screenshots collector 32–57은 소유 TemporaryDirectory 안에 전송 결과를 보관하고 여덟 파일의 크기/SHA 검증 뒤 payload를 최종 경로로 rename한다. 전송 timeout/검증 예외가 최종 디렉터리를 만들지 않으며 context manager가 임시 디렉터리를 정리한다. 이미 완성된 immutable 최종 결과의 덮어쓰기는 계속 거절한다.
4. 후속 발견 J-COLLECTOR-P1-01, 치환 토큰 충돌: **FIXED**. 중간 collector SHA 752de1bf022b7c6f9f1cbbb739efd06bcbc8090161a84e2f704075d4983bfdc3의 NAME 우선 치환이 FILENAME을 FILE'container'로 깨뜨렸다. 구형 최소 문자열을 독립 compile하여 SyntaxError를 확인했다. 최종 b133은 겹치지 않는 __CONTAINER_VALUE__/__RESULT_FILE_VALUE__를 사용한다. 실제 AST replace chain을 fixture 값으로 치환한 native/UI remote Python 두 개를 각각 compile하고 name/filename 값 및 미치환 토큰 부재를 확인했다. 기존 심각도 P1을 유지한 closure이다.

## 직접 수행 / NOT_RUN

EXECUTED: 다섯 파일 전체 읽기·SHA256, Python 하니스 네 개 compile, success/launch remote Python fixture compile, 최종 collector native/UI 완전 치환 remote Python compile, 구형 충돌 negative compile, MJS node --check. 모두 소스 파싱/컴파일이며 하니스 main 또는 SSH/운영 명령을 실행하지 않았다.

NOT_RUN: 실제 SSH·Docker·브라우저·인증·다운로드·장애 주입·운영 DB·PNG 시각 검사, 실제 전송 실패 후 재시도 실행. staging 실패 정리는 source control flow 검토이며 실행 검증 수치로 합산하지 않는다.

추가 actionable finding 없음. 고정 remote 경로와 설치 계약을 운영자가 관리하는 하니스 범위의 판정이다. 실제 환경 결과 및 게시 전 여덟 PNG의 시각/개인정보 검사는 별도 gate다. source digest와 결과 identity가 일치해도 PNG signature/hash 자체가 시각적 잘림·개인정보 검사를 대신하지 않는다.

초기 원문 map-two-collector-review-block.md SHA256 a53f44a8b5ae9f55d83ca9b83c45ef8119de104af682fd41ed4edd98a26658ea 및 original source hashes sidecar를 불변 보존했다. 운영 테스트 미실행 상태를 소급하여 PASS로 바꾸지 않았다.
