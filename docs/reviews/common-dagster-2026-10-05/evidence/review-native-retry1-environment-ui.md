# native retry1 권한 하니스 독립 리뷰

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **좁은 정적 리뷰 PASS**. 제품 FULL PASS 및 실제 six-service 결과와 별도이며 native probe 성공을 주장하지 않는다.

실행 ID: J-NATIVE-RETRY1-ENV-20261006. 읽기 범위는 ignored map-native-runtime-probe-launch.py / map-pinvi-operating-test-collect.py 두 파일뿐이다. 이전 원문·실패 컨테이너·제품·운영·공개 archive 변경 없음.

검토 SHA256:
- launcher: d404481ede05a87f6a8710a6ad5bc5b493dd416c89d434bd1ac8e5d2ac65930f
- collector: e978bc33ea6a698d9b438726d4b32a0628c17a9318234ff506b304b6895507dc

권한/격리 경계: launcher 10–18행은 attested 운영 image 일치, Config.User appuser, python -I stdlib로 읽은 실제 euid/egid가 정수이며 모두 양수인 것을 확인한다. 새 native-evidence-retry1 경로는 부재·비symlink 및 소유 root 부모를 확인하고 0700 mkdir 후 실제 uid/gid로 chown한다. 21행 /work tmpfs mode1777은 비루트 appuser의 native-runtime-instance 생성 권한을 제공한다. 기존 실패 컨테이너와 다른 retry1 이름 및 전용 evidence 경로를 사용한다.

24행 image 기본 비루트 사용자를 유지하며 --user 0 override가 없다. native source648 hash guard, exact readonly probe file mount, 전용 evidence write mount, network none/memory3g/cpu2를 유지한다. 전체 private root/runtime.env 또는 환경 비밀 파일을 mount하지 않는다.

collector 6/15–16행의 retry1 name/path는 launcher와 일치한다. native name 및 경로 분기 세 줄을 이전 형태로 역변경한 bytes SHA가 b133388b0676c5b3ffe0ef3ae55f658979e74e5d04f90b3467a5cef45140e54c와 정확히 일치했다. UI 수집 검증 로직은 이전 독립 검토 bytes 그대로다.

EXECUTED: 로컬 파일 전체 읽기/SHA256, local Python 두 개 compile, EXPECTED_IMAGE 치환한 launch remote Python compile, 실제 AST replace chain으로 native/UI collector remote를 완전 치환한 뒤 compile·name/filename fixture 검증, collector 역치환 bytes SHA 비교. 추가 actionable finding 없음.

NOT_RUN: 하니스 main, SSH/docker exec/run, 실제 euid 조회·chown·mount·native jobs·수집·DB·브라우저·운영 변경. 첫 native launch의 PermissionError와 zero jobs/result 상태는 부모 실행 근거이며 본인 실행으로 집계하지 않는다. source상 권한 경계가 해결되지만 실제 재시도 결과는 운영 실행으로 확인해야 한다. 실패한 launch의 경로/컨테이너가 남으면 같은 이름 재실행을 거절하는 안전 gate는 유지되므로 그 경우 원본을 보존하고 운영자가 별도 retry identity를 결정한다.

보존 시각(UTC): 2026-10-05T17:31:55.012901+00:00
