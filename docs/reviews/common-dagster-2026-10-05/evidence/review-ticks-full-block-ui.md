# Map885/Common/PinVi FULL 연속 독립 리뷰

<!-- SPDX-License-Identifier: MIT -->
<!-- SPDX-FileCopyrightText: 2026 kor-travel contributors -->

판정: **FULL BLOCK**. J-C7-P1-01 OPEN. 이전 builtin FULL 원문 SHA b4e2629d16ed41197f8a5d5ebd9d4797d6eae61a4c9ea9bbe7e6c28ddeb7a9d3는 불변이며, 새 실제 build 경계에서 발견한 결함으로 현재 rollout gate를 갱신한다.

고정 manifest SHA256 9d53eed9d50fdc1c6f5044005efa0c9686303d91e9e14f08c28aad140f177d28.
- Common base7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52 → a960bdb114d99a2ac1b9608a77b240635806e551, 35파일.
- Map basea46d7b92c0e727805348e20d60fe188592e16477 → 885d6205a8ce8d9e79c38b9198eb05f51bcc9192, 62파일.
- PinVi base07cfef222c56d7e648c81b017aa8ffe4ccd1c386 → 0058369c778f8c3357ee393e12e3447d7975cc1f, 15파일.

독립 Git object 검증: 112개 전부 candidate blob SHA가 manifest와 일치하고 각 base→candidate changed file 목록이 manifest와 정확히 일치했다. peer evidence는 hash 계산만 하고 원문 의미를 읽지 않았다. 기존111 manifest와 비교 시 새 handoff1파일 및 resume/query2파일만 달라졌고 이전 path 삭제는 없다. 이전 검증의 HTTP/recovery/UI/auth/API/DTO/OpenAPI/vendor/M05 evidence를 byte동일성 범위에서 재사용한다. 전체 설치 경로가 실행 검증됐다는 뜻은 아니다.

새 query 검토: dagster_query_service.py56/73의 schedule/sensor ticks는 limit3를 유지하며 STARTED,SKIPPED,SUCCESS,FAILURE 네 상태를 모두 명시한다. 실행중·skip·정상·실패 상태를 숨기지 않고 기존 timestamp/error 등 출력 field와 owned repository selector·오류 처리를 유지한다. query delta는 literal2개/comment2줄뿐이다. 신규 root API29PASS 및 실제 query2.077초 관측은 작성자 근거이며 본인 실행으로 합산하지 않는다.

문서 delta: handoff/resume는 최신 transport c6105233/#69 redaction과 standalone #1304·디스크 경계 정보를 보존한다. historical prod13f/PinVi80c 기록은 당시 handoff 문맥이며 후보885 실제 rollout PASS로 바꾸지 않았다.

## J-C7-P1-01 — npm ci 전에 frozen Common vendor가 없음

P1 OPEN. docker/c7-playwright.Dockerfile:7–19 및 frontend/package.json:46–47.
C7 image는 frontend manifest와 root lock을 복사한 뒤19행 npm ci를 실행하지만 vendor가 포함된 전체frontend는24행에야 복사한다. UI/tokens dependencies는 file:vendor/*.tgz이다. 따라서 정확한 git archive에서 설치 layer에 필요한 두 tarball이 없고 C7 build가 실패한다. 정상 developer node_modules/CI API Docker 성공은 이 경계를 검증하지 않는다.

독립 source 증거: C7 Docker SHA fdccc6f96b302334cb80e78672397a151dea8884203a500ccdbc863d54842401, vendor COPY0개, ci19 < frontend COPY24. 후보 archive에는 vendor UI SHA e4945d01d9eb89ed505a95b551899fd0ecf41be66c9ee6b76246701350447e6d / tokens554ae3f6a18cbf453130b29f8a2d737ddb880101b55e14535cf8d63174b47505가 있으나 그 layer에는 없다.

실제 readonly child journal에서도 npm ci 포함 RUN이 exit254, unit exit1/FAILURE이며 executor local image 라벨은 옛13f87577이다. quiet build가 ENOENT 상세를 출력하지 않아 해당 exit의 단일 원인까지 관측했다고 주장하지 않는다. source missing-input defect 자체는 결정적이다.

재현 경계: 현재 exact candidate archive로 C7 executor build script를 실행하면 file:vendor 설치 입력이 npm ci layer에서 빠진다. 본인은 새 build를 실행하지 않았다. 최소 수정은 vendor 디렉터리를 npm ci 이전 정확한 workspace 경로로 COPY하는 것이다. 이후 fixed frozen source·manifest 재검토 및 실제 C7 build gate가 필요하다.

EXECUTED: fixed Git blob/hash/range 검증, 이전 manifest byte상속 비교, query/docs/C7/build-script/package source 읽기, 승인된 actual readonly journal/image/chain 점검.
NOT_RUN: 제품 tests/빌드/CI/E2E/885 rollout, N150 mutation, ACL/D1/D2 실행. 원본과 public archive/제품 수정 없음. Common 변경은 공개 Python·UI/runbook 경계의 기존 FULL 판정을 이어받으며 새 문서만의 closure 예외를 runtime 변경과 혼동하지 않는다.

검토/보존 시각(UTC): 2026-10-05T18:15:11.072706+00:00
