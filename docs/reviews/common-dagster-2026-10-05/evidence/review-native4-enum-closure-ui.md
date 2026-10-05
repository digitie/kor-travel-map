# native retry4 timeout enum 독립 closure

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **좁은 하니스 closure PASS**. J-NATIVE-EVENT-P2-01의 심각도 P2를 유지하고 FIXED로 판단한다. 제품 FULL111 및 실제 native/UI 판정과 별도다. 진단 원문 map-native3-timeout-diagnosis-ui.md SHA256 dcae3824c8f13ff8168eb99f46ea9ec2e6830d9219e236e0b191834442ad5655는 변경하지 않았다.

검토 bytes SHA256:
- native retry4 source: 7d9821abd4e590eadc1b476dcc0b7b5b12d4a9b0d854ef27c4d239d82c8181bf
- native retry4 launch: 2c6c5edfbcd1c4a8d9c9e483559df6141c7fe2290fe086408e4c559f27aac424
- native retry4 upload: 239613366bbca9227bae5d03367a6101202102a573587e204c8746581c8b213c

retry3 source와 직접 diff한 변경은 DagsterEventType import 및 timeout event predicate의 enum 비교·bounded wait뿐이다. event_type == DagsterEventType.RUN_FAILURE는 실제 설치1.13.24의 serialized PIPELINE_FAILURE alias를 올바르게 판별한다. Exceeded maximum runtime of 20 seconds 메시지 요구는 그대로이고 20.0 logger 문자열로 완화하지 않았다. terminal FAILURE/start/step/상한 tag/활성·overlap/healthy/retry assertions는 유지된다.

timeout event guard는 monotonic 5초 budget과0.1초 poll로 기다린 뒤 event가 없으면 여전히 실패한다. 이는 기다리는 poll budget이며 all_logs IO 자체의 hard timeout을 주장하지 않는다. 자체 fakeclock fixture는 float/poll 간격 때문에5.1초에서 종료했다.

EXECUTED: local Python 세 파일 및 placeholder 완전 치환 remote Python 네 개(launch1/upload3) compile, launch/upload retry4name/path/sourcehash 역치환 bytes SHA 비교. 각각 이전81ccdc9deea32630f20461557e91e32a6f14773d93a65a0dd243d811acb1fd77 / c144383885337f115868f6ee547386c5310a26a6e6d61a07b1ec73c8f8a4c115와 정확히 일치했다.

현재 source AST의 timeout deadline/while/assert 세 statement만 own in-memory fixture로 평가했다. 실제 serialized enum값 PIPELINE_FAILURE를 가진 RUN_FAILURE의 즉시·지연 timeout control2 PASS. no event,20.0 메시지, ENGINE_EVENT timeout문자열, ordinary RUN_FAILURE 네 negative 모두 거절했다. 지연 control은0.2초/3조회, negative는 fakeclock5.1초 이내 종료했다. 하니스 main 및 실제 Dagster instance를 실행하지 않았다.

NOT_RUN: SSH/Docker/upload/native jobs/DB/UI/collector 실제 수집. 원래 잘못 준비한20.0 후보는 부모가 NOT_RUN으로 명시했으며 이번7d 후보의 성공 실행으로 소급하지 않는다. root가 예정한 collector3→4 name/path/hash 변경은 아직 이 보고서에서 검토하지 않았다. 소스·제품·운영·공개 archive 수정 없음. 추가 actionable finding 없음. 실제 재시도 receipt 검증은 별도다.

검토/보존 시각(UTC): 2026-10-05T18:00:17.094065+00:00
