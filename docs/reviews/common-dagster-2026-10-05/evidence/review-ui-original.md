<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Map·PinVi 소비자 FULL 독립 적대 리뷰 — Reviewer B / James

실행 ID: J-MAP-PINVI-CONSUMER-20261005-01
시작 UTC: 2026-10-05T08:36:20.843433+00:00
종료 UTC: 2026-10-05T08:50:36.910684+00:00
관점: UI·인증·API 소비 계약·접근성·장애 관측·메모리 경계

**판정: BLOCK.** P1 2건·P2 2건이 아래 고정 후보에서 OPEN이다. 새로운 P0/P3는 발견하지 않았다. 이후 작업자의 수정이나 CI 결과를 이 후보의 closure로 소급하지 않는다.

## 고정 대상·격리·FULL 판단

- Map 기준선: 3b9b49d694c7dd544ec6ed86253f5935bde0f193
- Map 실제 검토 객체: acde3726481b09f8710ab94c29fdcdb78713dcf7
- PinVi 기준선: 07cfef222c56d7e648c81b017aa8ffe4ccd1c386
- PinVi 실제 검토 객체: 640612af58248b1dfc8200b8dcb1a1512f9977d0
- Common HTTP 실제 코드: 1f8e339c7c79f86f8952b0d4c326ab4dae56bee8
- Common UI dev.6: e28559803c1ec1134ef7ba7736b9acf4cadb9a32의 동결 산출물, SHA256 e4945d01d9eb89ed505a95b551899fd0ecf41be66c9ee6b76246701350447e6d.
- manifest 검토 사본: /home/digitie/.cache/james-map-pinvi-20261005/manifest.json. SHA256 64c32eb2dfb9c4cb17d29e2708a9fee5be2f8eaabc36ea5168d0ff0ec7bbd10a.
- Map archive: /home/digitie/.cache/james-map-pinvi-20261005/map.tar. SHA256 f5b99d07625bdcbb96c8c67f76cf44f266cbe97703b1d8e48858b8bc549c3366.
- PinVi archive: /home/digitie/.cache/james-map-pinvi-20261005/pinvi.tar. SHA256 5205b725af36f1f2417cedfa1abecbda5318a0dd2a0cfd471c853a3308744cc4.

Linux Git가 각 후보 commit 객체를 해석한 뒤 own ext4 cache에 archive를 추출했다. manifest Map54·PinVi13개 파일의 모든 SHA가 일치했다. 소스·사람의 dirty worktree·foreign venv/node_modules·운영 DB·컨테이너를 변경하지 않았다. 설치 의존성은 읽기 재사용했고 공격 파일·cache·build 출력은 본인 cache에만 만들었다. pytest PYTHONPATH는 고정 archive의 앱 및 이전 본인 Common1f8 archive를 우선했다. 타 리뷰어 원문·통합 판정·docs/reviews 내용은 읽지 않았으며 manifest 대상 review 문서는 bytes hash만 검증했다. journal/resume의 verdict는 근거로 삼지 않았다.

Map·PinVi AGENTS/SKILL의 기준선 대비 변경이 없음을 확인했다. 이미 읽은 규칙의 Linux 실행·N150 Playwright·독립 HTTP/DB 소유권·비밀 비노출 경계를 유지했다. UI/auth·공개 summary API·Python 전송·배포·snapshot 배치와 runbook의 실제 제품 변경이므로 작성자와 별도로 **FULL 대상**이라고 판단한다. 증거만 추가하는 후속 문서는 제품 FULL 검토와 구분해야 한다.

Map은 기준선→후보의 관리자 UI/생성 타입·OpenAPI·전송 및 요청별 client·정책·Dagster 배치/resource/executor/recovery tags·계약 핀·ADR/가이드/추적 문서 delta를 검토했다. PinVi는 전송 helper/직접 의존성·uv.lock·Map OpenAPI/M05 pair 핀·가이드 delta를 검토했다. PinVi apps/web 제품은 기준선과 동일하며 새로운 로그인/메뉴 재구현이나 UI 산출물 변경이라고 집계하지 않는다.

## OPEN findings

### J-CONSUMER-P1-01 — PinVi direct Git 의존성이 Hatch metadata 빌드를 막음

심각도 P1. 위치: PinVi apps/api/pyproject.toml:9 및 build-system/metadata 설정.
시나리오: 새 Common Git dependency를 포함한 API 패키지를 clean 환경이나 공식 Docker의 pip install -e . 경로로 설치한다.
직접 재현: 본인 archive에서 아래 명령은 exit2로 실패했다.

```bash
/home/digitie/.local/bin/uv build --wheel --offline --out-dir /home/digitie/.cache/james-map-pinvi-20261005/pinvi-dist /home/digitie/.cache/james-map-pinvi-20261005/pinvi/apps/api
```

실제 Hatch 오류는 project.dependencies의 direct reference를 tool.hatch.metadata.allow-direct-references=true 없이 허용하지 않는다는 내용이다. API Dockerfile:42의 설치도 같은 metadata backend를 사용한다. 기존 준비된 venv에서 27 probe unit이 PASS하는 것과 clean 패키지 빌드 성공은 다르다.
영향: API 설치/이미지 생성과 배포가 막힌다.
최소 수정 및 closure 조건: 의도한 고정 direct reference를 Hatch에서 허용하고 lock을 유지한다. 고정 수정 후보의 clean wheel/editable metadata 및 실제 production Docker build를 검증한다.
직접 실행 원문: pinvi-wheel-result.txt, SHA256 eda9209c80e27c9ccbb1e4598c1abdc0880debf7f70e426da5c067d24b1771ae.

### J-CONSUMER-P1-02 — Map API builder에 신규 Git 의존성 설치 도구가 없음

심각도 P1. 위치: Map docker/api.Dockerfile:12,27-30 및 packages/kor-travel-map-api/pyproject.toml:31.
시나리오: 캐시 없이 공식 API 이미지를 만든다. 새 dependency는 git+https이며 API builder는 build-essential/curl만 설치한다. 같은 repo Dagster builder는 Git를 명시적으로 설치한다.
독립 코드 확인으로 배포 prerequisite 누락을 식별했다. 실제 Docker 재현은 검토자 직접 실행이 아니다. 작업자가 제공한 CI37284719348 원문 /tmp/map-docker-ci-failed.log를 읽기 전용으로 확인했으며 git version 실행의 Errno2 및 Cannot find command 'git' 오류가 있었다. 본인 보존 excerpt는 parent-map-docker-git-excerpt.txt다.
영향: Map API fresh production 이미지 생성이 실패한다.
최소 수정 및 closure 조건: builder에 Git를 설치하고 runtime 권한/패키지 경계를 유지한다. 고정 수정 후보의 캐시 없는 production image 생성과 source provenance를 확인한다. 이후 작업자가 말한 다른 후보의 진행 중 CI는 이 원문 후보의 PASS로 합산하지 않는다.

### J-CONSUMER-P2-01 — Common 교체로 기존 실패 상세·이벤트 pagination을 잃음

심각도 P2. 위치: Map packages/kor-travel-map-admin/frontend/src/app/ops/pipeline/pipeline-client.tsx:593 및 src/components/common-dagster-panel.tsx:34-36,55-61.
시나리오: 순수 Dagster 실패 run을 목록에서 열고 실패 원인·다음 이벤트 페이지를 확인한다.
기준선 DagsterRunsPanel은 events-panel.tsx:317의 DagsterRunDetail을 선택 시 렌더해 failure_reason/events/event_cursor를 소비했다. 새 CommonDagsterPanel은 모든 errorMessage를 null로 만들고 showRunDetails/selectedRunId/onSelectRun/renderRunDetail을 전달하지 않는다. Common 기본 showRunDetails=false이므로 실패 run을 선택하는 인앱 버튼과 이벤트 연결 자체가 없다.
직접 RTL 공격에서 failed_map_job은 보였지만 실행 상세 버튼을 찾는 실제 assertion은 FAIL했다. DOM은 “실패 원인을 불러오지 못했습니다.”와 외부 Dagster 링크만 표시했다. 단순 selector 이름 변경이 아니라 source에서 상세 hook 호출과 pagination 경로가 제거됐다.
영향: 기존 실패 원인·이벤트 paging으로 조사/복구하던 관리자 흐름이 퇴행한다.
최소 수정 및 closure 조건: Common의 controlled selection/renderRunDetail에 기존 상세 query/UI를 연결하고 선택한 run만 로드한다. run 변경 시 cursor를 초기화하며, stale summary·상세 오류·페이지 이동·키보드 선택을 회귀 검증한다.
직접 공격: probes/consumer.attack.test.tsx의 첫 테스트. 결과 ui-attack-result.txt는 1FAIL/4PASS, exit1이다.

### J-CONSUMER-P2-02 — 손상 Repository 응답이 정상 빈 snapshot으로 인정됨

심각도 P2. 위치: Map packages/kor-travel-map-api/src/kortravelmap/api/dagster_graphql.py:484-518, dagster_query_service.py:308-321 및 frontend/src/components/common-dagster-panel.tsx:47.
시나리오: repository 필드가 누락/손상된 JSON 응답을 받는다. 두 run connection 자체는 정상 빈 목록이다.

```json
{"data":{"repositoryOrError":{"__typename":"Repository"},"runsOrError":{"__typename":"Runs","results":[]},"activeRunsOrError":{"__typename":"Runs","results":[]}}}
```

직접 실제 get_summary + HTTPX MockTransport에 위 응답을 주입했다. 반환은 status=ok, repository_count=1, name=__repository__, location_name=unknown_location, jobs/schedules/assets/sensors=0, errors=[]이었다. repository 파서의 기존 관대한 fallback을 신규 summary route/Common UI가 그대로 소비한다. 프론트는 status=ok만 검사하여 마지막 정상 job/schedule snapshot을 이 가짜 정상 snapshot으로 덮는다.
영향: 장애·잘못된 repository metadata가 “정상, 작업/스케줄0건”으로 표시되고 정상 관측을 잃는다.
최소 수정 및 closure 조건: summary repository identity/location과 필수 collection/행 구조를 검증해 손상·불일치·누락을 error로 반환한다. empty valid collection은 허용하되 field 누락과 구분한다. 실제 DTO→UI의 last-good 유지 회귀도 검증한다.
재현 명령:

```bash
PYTHONPATH=/home/digitie/.cache/james-map-pinvi-20261005/map/packages/kor-travel-map-api/src:/home/digitie/.cache/james-map-pinvi-20261005/map/src:/home/digitie/.cache/james-map-pinvi-20261005/previous-common-http/james-common-map-http-postfix-1f8e339/packages/py/kor-travel-common/src /home/digitie/.cache/map-common-recovery-venv/bin/python /home/digitie/.cache/james-map-pinvi-20261005/probes/repository-shape-probe.py
```

script SHA256 6c5983c2c6af10b9f8e1749637a21e47f3878a1a574aec1fc499e25aeac84cea. 결과 repository-shape-result.txt SHA256 731d52171c35b489c316ee872c1eae5d8afca8971a63ee7f7e15a90ba999e1b0.

## 직접 EXECUTED

- immutable 객체·archive·manifest 모든 파일 해시 검증.
- Map/PinVi vendor dev.6 동일 SHA 확인, 두 package-lock UI integrity가 실제 tarball SHA512와 일치. 실제 읽기 재사용한 설치 @kor-travel/ui의 파일24개가 tarball bytes와 일치.
- Map OpenAPI와 PinVi admin vendor가 byte-exact이며 SHA256 ccec0fd05d2e5fea6ab46192e7ac1a3f08d9b0137cefcd92672be794f4f95294.
- Map test_dagster_bounded_summary.py: 10PASS/1.17초. 오래된 STARTED+최근30 success, 잘못된 run connection/status, 상한 초과, terminal 우선, 압축 응답 거부.
- Map test_application_http_adapters.py: 8PASS/1.23초. 요청별 client 재사용/종료·어댑터 경계.
- Map test_snapshot_batching.py: 2PASS/1.38초. 유한 배치 소비와 변환 실패의 sync 성공 미기록 fixture. 실제 PostgreSQL rollback/seal 실행으로 주장하지 않는다.
- PinVi test_admin_etl_dagster_probe.py: 27PASS/0.77초.
- PinVi test_kor_travel_map_admin_contract.py: 8PASS/0.28초.
- own RTL consumer 공격: 4PASS/1FAIL/36.99초. 실패 상세 누락 FAIL; degraded200 last-good run/링크 유지, cap 누락=null, 로그인 transport 오류 원문 숨김/비밀번호 제거/다시 제출 가능, encoded control redirect4개 차단 PASS.
- own RTL menu 공격: 2PASS/45.19초. longest-prefix 한 항목만 aria-current, collapse 뒤 accessible name 유지, 로그아웃403 뒤 오류 표시/메뉴 유지/재시도 가능.
- 손상 Repository 실제 application function 공격: 위 P2를 직접 재현.
- own clean PinVi wheel build: 위 P1을 직접 재현.

전체 mock·fixture만 사용했다. RTL은 Linux jsdom이며 실제 브라우저 CSS 폭·탭 이동·스크린리더 실증이라고 주장하지 않는다. UI runner는 읽기 재사용 설치 Vitest4.1.10/Node22.22.2이며 고정 앱 코드는 own archive다. 실행 명령 정본은 probes/vitest.config.mts와 *.attack.test.tsx이며 아래처럼 원본 후보 공격을 다시 실행할 수 있다.

```bash
/usr/local/bin/node /mnt/f/dev/kor-travel-map-codex-dagster/node_modules/vitest/vitest.mjs run --root /home/digitie/.cache/james-map-pinvi-20261005/probes --config /home/digitie/.cache/james-map-pinvi-20261005/probes/vitest.config.mts --no-cache
```

## 본인 사전 finding disposition

| 기존 ID | 심각도 유지 | 이 후보의 disposition |
| --- | --- | --- |
| J-MAP-BASE-P2-01 | P2 | FIXED — Common redirect sanitizer, own encoded control4건 차단 |
| J-MAP-BASE-P2-02 | P2 | FIXED — separate active filter/1000 cap, 직접 old run 회귀 |
| J-MAP-BASE-P2-03 | P2 | FIXED — HTTP200 degraded 기존 재현은 snapshot 유지. 별개 손상 ok 응답은 새 P2-02 OPEN |
| J-MAP-BASE-P2-04 | P2 | FIXED — 본인 FULL PASS Common1f8 전송 상한과 실제 앱 압축/요청별 client 테스트 연결 |
| J-MAP-BASE-P2-05 | P2 | FIXED — 로그아웃 실패를 성공 이동으로 처리하지 않음, own403 오류·재시도 |
| J-MAP-BASE-P2-06 | P2 | FIXED — Common 오류 slot·비밀번호 제거·busy 해제, own transport 실패 공격 |

RecoveryPolicy 쓰기 retry0·job별 max runtime·multiprocess step1·pool1/overflow0·SQL/lock 상한·snapshot streaming이 Map canonical operation/봉인/curation 계약을 우회해 새 identity를 만드는 경로는 이번 코드 리뷰에서 발견하지 않았다. 한도가 프로세스 전체 RSS나 provider 원천을 모두 bounded로 만들었다고 판정하지 않는다. Domain execution timeline·수동 명령/claim recovery는 Common 패널과 분리된 기존 앱 경로다.

## NOT_RUN 및 남은 게이트

검토자 직접 전체389 UI/type/lint/build, 전체 Map/PinVi backend, strict mypy, native Dagster daemon/worker 중단·재시도·PG transactional rollback, paired M05 activation/attestation, 운영 source/image provenance, 실제 N150 로그인/JWT/RBAC/cookie/CSRF·desktop/mobile CSS·Tab/Arrow 이동·스크린리더·HTTP outage live, 운영 재구축/RSS·최종 CI·PR merge는 NOT_RUN이다. parent가 알린 별도 전체 검사 숫자·다른 후보 CI는 본인 실행에 합산하지 않는다. 운영 재구축/live는 아직 검토 완료로 선언하지 않는다.

Map API Docker 실패 증거는 parent 실제 CI 원문을 읽고 source 누락과 대조한 것이며 본인 Docker 실행이 아니다. 본인이 수행하지 않은 배포·운영 검증은 후속 고정 수정 manifest와 실제 N150 증거에서 별도로 판정해야 한다.

원문 후보의 네 finding을 수정하고 동일 실패 주입이 닫히는지 확인한 뒤 FULL closure가 필요하다. 이 보고서는 소스 수정·stage·commit·push 없이 보존한다.
