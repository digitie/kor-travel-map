# native retry4 실제 receipt 독립 읽기 전용 검토

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **ACTUAL RECEIPT PASS**. 범위는 기존 Map1ba exact image 안의 격리 SQLite/native gRPC·multiprocess·daemon 테스트다. 새 Map885 rollout/UI/공용 운영 장애·provider/DB 시험의 PASS로 확장하지 않는다. 본인은 새 테스트를 실행하지 않고 기존 결과와 실제 stopped container를 읽기 전용으로 검증했다.

receipt SHA256 bd31491f4bee7d2962089445d50852185e3935f625d8d5961b3f925f27ef6bf6.
runtime attestation SHA256 de4be912a7327e155c65242ee48b1bac108c03c8818431855fc33bc442701312.
container bbd4456083fa53bdcee7cf3c06527b1ceb0a838a5689ac88e614dd152ed84429.
image sha256:5ded0abe5dc4deddfc1e7ccc5353cffa8ecab001449abeb3f606267d0348ad9f.

독립 검증: receipt/attestation PASS·committed, attested Map source1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e, image/installed Common SHA 일치. 실제 readonly docker inspect에서 같은 containerID/image, appuser, exited/ExitCode0/RunningFalse/OOMKilledFalse와 exact readonly native-probe-retry4 mount를 확인했다. 실제 mount source SHA가 검토7d9821abd4e590eadc1b476dcc0b7b5b12d4a9b0d854ef27c4d239d82c8181bf와 일치했다.

Common installed commit은 a960bdb114d99a2ac1b9608a77b240635806e551이다. receipt의 common_reference_contract1f8은 역사적 계약 기준이며 실제 설치 pin으로 오인하지 않았다. actual_common_dagster_sha256 ee1bce427711246b700f8d413d00500418d789dc30624607b3fdac800bdfd4d2는 fixed Commona960 Git source blob과 정확히 일치한다. Dagster1.13.24 및 autonomous daemon flag True를 확인했다.

raise/crash/stall 순서 세 case 모두 terminal FAILURE와 동일job manual retry SUCCESS다. raise/crash는 STEP_START·원인검증 True, stall은 STEP_START/native timeout event/overlap/active-coalescing release 모두 True, concurrent healthy job SUCCESS, runtime tag20이다. source7d의 enum+정확한20 seconds timeout assertion과 별도 source provenance guard를 재사용하며 이전 실패/20.0 잘못 준비한 후보를 성공으로 소급하지 않는다.

EXECUTED: 로컬 receipt/attestation/source/Git common SHA 검증 및 assertion, 실제 readonly docker inspect·mount source hash 조회.
NOT_RUN: 본인 native job/daemon/DB/재시도·운영 변동·UI·새885 결과 실행. 작성자 실행 결과를 본인 실행 테스트 수로 집계하지 않는다. 원본·제품·공개 archive 변경 없음.

검토/보존 시각(UTC): 2026-10-05T18:15:11.072706+00:00
