# C7 실제 child build·stale label 독립 진단

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **C7 build BLOCK / fail-closed gate 유지**. actual child journal과 installed trusted chain을 읽기만 했다. 운영 build/chain/ACL/D1D2는 본인이 실행하지 않았다.

installed /root/chain16.sh SHA256 7f6558eebfbf3acceb7771e8025e161c028bbe6f8ff1e8d3177f103181b1bce4는 local private trusted copy와 정확히 같다. 공개 보고서에 전체 private script/주소/환경을 복사하지 않았다.

actual codex-common-execbuild-20261005 journal: npm ci/verify 명령을 포함하는 Docker RUN이 exit254로 실패했고 service Main process exit1/FAILURE 및 Failed result exit-code가 기록됐다. build script는 --quiet여서 해당 journal만으로 npm ENOENT 상세·유일한 causal error를 관측했다고 주장하지 않는다.

실제 kor-travel-map-c7-playwright:local image는 sha256:d46faeff17610efac1910aa6d8a40b18e820707b9b48b9ebdb21d2ab2e1b5f89이고 repository_commit은13f87577acfc1b7f6eca81a4b7e4b38babd59f81이다. 실패한 build가 새 tag를 만들지 않아 옛 image 라벨이 남는 현상과 일치한다. trusted chain47–60의 C단계는 child 완료 후 image label을 expected MAP과 비교하며 불일치면 die한다. D repin은62행 이후이므로 보고된 C 실패 흐름에서 후속 ACL/D1D2가 실행되지 않는 것은 일관된다. 후속 단계가 성공했다고 주장하지 않는다.

고정 Map885 source에서 별도 결정적 결함을 확인했다: docker/c7-playwright.Dockerfile19의 npm ci 이전 vendor COPY가 없고24에 전체frontend를 복사한다. frontend dependency UI/tokens는 file:vendor tgz다. source missing-input은 J-C7-P1-01(P1 OPEN)로 FULL 원문에 보존했다. 필요한 최소 수정은 ci 이전 vendor COPY이며 actual C7 build와 고정 candidate gate로 검증해야 한다.

EXECUTED: 승인된 readonly SSH/host stdlib로 installed chain hash·bounded child journal·docker image inspect, fixed Git C7 Docker/build script/frontend manifest 읽기. 실제 journal의 단일원인 관측과 source defect 확정을 구분했다.
NOT_RUN: 새 build·stage·chain·컨테이너 변경·pin 회전·테스트·ACL/D1D2. 제품·공개 archive·기존 원본 수정 없음.

검토/보존 시각(UTC): 2026-10-05T18:15:11.072706+00:00
