# native retry3 timeout 판별 실패 독립 진단

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **하니스 결함 확정**. J-NATIVE-EVENT-P2-01(P2), map-native-runtime-probe-retry3.py:125–128. 제품 FULL111 판정은 변경하지 않으며 native 전체 성공을 주장하지 않는다. 진단 ID J-NATIVE3-TIMEOUT-DIAG-20261006.

직접 읽기 전용으로 확인한 실제 설치 환경:
- 운영 Map Dagster 컨테이너의 installed distribution 버전은 1.13.24다.
- installed run_monitoring.py SHA256: 1b7d7a4bf8d56b76e5c4f3ae7c900bdbf73dfbe96b1b89d6a95f7bea5ec9e7a3.
- _core/events/__init__.py:156에서 RUN_FAILURE = "PIPELINE_FAILURE"이고 167에서 PIPELINE_FAILURE는 같은 enum alias다.
- event_methods.py:435–441 report_run_failed는 PIPELINE_FAILURE.value로 event를 생성·저장한다.
- run_monitoring.py:253–254 daemon logger는 float max_time(20.0)을 출력하지만 263–265 report_run_failed 메시지는 int(max_time), 즉 Exceeded maximum runtime of 20 seconds.를 사용한다.

결정적 실패 원인: probe126의 event_type_value == 'RUN_FAILURE'는 실제 serialized value PIPELINE_FAILURE를 거절한다. 따라서 정상 timeout event가 이미 저장되어도 timeout_events는 빈 목록이 된다. 메시지20→20.0 변경 또는 대기만 추가하는 조치는 이 결함을 해결하지 못한다.

최소 수정 권고: DagsterEventType.RUN_FAILURE enum 자체 또는 DagsterEventType.RUN_FAILURE.value와 비교하고 정확한 timeout 메시지/상한 검증을 유지한다. daemon logger 존재나 단순 terminal FAILURE만으로 통과시키지 않는다.

저장 순서·race 판단: 실제 event_methods.py:230–231은 event storage에 먼저 저장하고 255–256에서 run storage 상태를 갱신한다. 동일 timeout failure event의 상태 저장이 event 저장보다 먼저라는 근거는 없다. 다만 run_monitoring.py:262에서 worker terminate가 먼저 실행되고 263에서 daemon timeout failure를 별도로 보고하므로 worker가 다른 failure를 먼저 기록하면 terminal poll과 후속 timeout event 사이의 간격은 가능하다. enum 결함 수정 후 동일한 RUN_FAILURE timeout event를 bounded wait하는 방어는 정당하다. 당시 SQLite 이벤트 snapshot을 직접 조회한 것은 아니므로 race를 실제 관측 원인으로 단정하지 않는다.

읽은 실제 retry3 증거:
- failure receipt SHA256 4b8565c7ac8040f8f3d26619bf7e5b300ee77623fa3b0156d03390cd21c0ccea: status FAIL, AssertionError, raise/crash 두 completed cases에서 실제 STEP_START·원인 검증·동일 job manual retry SUCCESS가 기록되어 있다.
- daemon private log SHA256 c650090e1c8e871c20452f359edca463dbf95c2dbdea460b142c6446d19ee7bd: max20.0 seconds timeout termination 한 건을 확인했다. 공개 보고서에 전체 로그·private endpoint·자격증명은 복사하지 않았다.
- probe source6d7 SHA와 즉시 terminal poll 후 all_logs predicate는 로컬 고정 하니스에서 읽었다.

EXECUTED: 승인된 실제 운영 컨테이너에서 readonly docker exec 두 건, python -I stdlib importlib.metadata/pathlib로 설치 버전·source만 읽기; readonly 호스트 stdlib로 소유 retry3 failure receipt/log digest 및 제한된 안전한 내용 읽기. Dagster/product 패키지를 실행 import하거나 run/daemon/DB를 새로 생성하지 않았다.

NOT_RUN: 새 job/운영 테스트/DB 조회·변경/재시도4·collector PASS/UI tests. 실제 stall receipt 성공은 없으며 raise/crash 부분 결과를 native 전체 PASS로 합산하지 않는다. 소스·제품·외부 서비스·공개 archive 수정 없음. 이전 원문 불변.

검토/보존 시각(UTC): 2026-10-05T17:58:29.476160+00:00
