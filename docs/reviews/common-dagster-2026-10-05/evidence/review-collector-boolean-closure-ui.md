# collector attestation·boolean 경계 독립 closure

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **좁은 하니스 closure PASS**. 범위는 ignored map-pinvi-operating-test-collect.py SHA256 0726daf879230bd805bbe3b2269376b4887926d1dda1189ede85d0a5b2073dc0 한 파일이다. 이전 원문 및 제품 판정은 변경하지 않는다.

EXECUTED: local Python compile, 실제 AST replace chain으로 native/UI remote Python을 완전히 치환한 compile 두 건, 현재 source AST의 native/UI 검증 branch만 자체 in-memory Path fixture로 평가했다. 검증 branch 이전 collector main/SSH/subprocess 및 이후 결과 파일 쓰기는 실행하지 않았다.

독립 경계 결과:
- 정상 native/UI control 두 건 PASS.
- attestation status FAIL native/UI 두 건 모두 AssertionError로 거절.
- native autonomous flag 한 위치, raise/crash 각 두 flag 네 위치, stall 네 flag 위치와 UI 네 case×다섯 flag 위치, 총 29 위치에서 False, 문자열 false, 숫자 1, null, 문자열 true를 각각 대입했다. 145개 모두 거절.
- 합계 정상 controls 2 PASS / negative 147 REJECTED. 실제 운영 테스트 수치가 아닌 source 검증 branch의 로컬 fixture 결과이다.

42행 native 및 61행 UI의 status PASS 요구, 47/51/53/80행의 is True 검증은 요청한 반례를 차단한다. False·문자열·정수 true 유사값을 정상 boolean으로 수용하지 않는다. native retry1 name/evidence 경로와 UI identity/source/time/capture 검증은 유지된다. 추가 actionable finding 없음.

NOT_RUN: 실제 native/UI receipt 수집, SSH/docker/인증/DB/브라우저/캡처·시각·개인정보 검사. 부모가 보고한 실제 uid999/gid999 시작 상태는 본인 실행이나 native 성공으로 집계하지 않는다. 제품·운영·공개 archive·다른 작업자 파일 수정 없음.

실행/보존 시각(UTC): 2026-10-05T17:43:15.622332+00:00
