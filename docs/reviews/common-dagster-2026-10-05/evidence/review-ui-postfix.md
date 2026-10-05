<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Map·PinVi 소비자 FULL post-fix 독립 리뷰 — Reviewer B / James

실행 ID: J-MAP-PINVI-CONSUMER-POSTFIX-20261005-01
시작 UTC: 2026-10-05T09:05:49.453731+00:00
종료 UTC: 2026-10-05T09:16:29.345259+00:00

**판정: BLOCK.** 기존 J-CONSUMER-P2-02의 identity 불일치 경계가 OPEN이고 새 J-CONSUMER-P2-03이 OPEN이다. 이전 P1 두 건의 코드 문제와 P2-01 상세 연결은 수정됐다. 새 P0/P1/P3는 발견하지 않았다. 작업자가 이후 수정하겠다는 내용은 이 고정 후보의 closure에 합산하지 않는다.

## 고정 대상과 FULL 격리

Map 기준선 3b9b49d694c7dd544ec6ed86253f5935bde0f193 → 실제 후보 72242b1a0c964893778ee7e0ef25e698097e1dfa.
PinVi 기준선 07cfef222c56d7e648c81b017aa8ffe4ccd1c386 → 실제 후보 f93af3248de8243be3c38f7e440eb0e394e84f48.
Common Python 1f8e339c7c79f86f8952b0d4c326ab4dae56bee8 및 UI dev.6 산출물은 불변이다.

manifest /mnt/f/dev/kor-travel-weather/.playwright-mcp/map-pinvi-postfix-manifest.json을 복사하고 SHA256 b9cb279817421a1ac405bfb05e0cfcf77b27b7841c2db488b65c9072b0aa974c를 검증했다. 검토 정본은 /home/digitie/.cache/james-map-pinvi-postfix-20261005/manifest.json이다.

- Map own Git archive SHA256: 64853ab57620b9800f22bc74bbc5160d5c93557807a27e646fc2a0c9770ed7dd.
- PinVi own Git archive SHA256: 3aa2127af2b6300fe83954d15d4cc359d12543a38abcfc8cfcb5c54060a6bf3e.
- manifest의 Map57/PinVi13 파일70개 전부 고정 추출 bytes와 일치하며 종료 시 재확인했다.
- own archive/probes/build 출력은 /home/digitie/.cache/james-map-pinvi-postfix-20261005 아래다. /tmp tmpfs에 새 작업 트리를 만들지 않았다.
- 앱과 Common 고정 source를 PYTHONPATH/alias로 우선하고 기존 venv/node_modules는 읽기 재사용했다. source·foreign 설치·운영 DB/컨테이너를 변경하지 않았다. peer 원문·통합 판정은 열람하지 않았다. review 문서는 manifest bytes hash만 검사했다.
- 이전 BLOCK 원문 map-pinvi-final-review-ui.md SHA256 47fff5e3709d44b76af3a3e33b558bbb0c2e982daca720034bec2d3abba84cbe는 그대로 유지했다.

UI/auth·공개 summary API·Python HTTP·배포·Dagster 배치 및 운영 가이드의 전체 base→candidate delta를 대상으로 작성자와 별도로 **FULL**이라고 판단한다. 기존 전체 검토 맥락을 유지하면서 고정 이전 후보→이번 후보 전체 수정 delta를 별도로 비교했다. Map frontend Docker/vendor COPY, API Git 설치, 상세/실제 hook/cursor, repository validator와 테스트를 검토했다. PinVi Hatch metadata/lock·HTTP finally cleanup·테스트를 검토했다. 기준선부터의 GraphQL scope/활성 run 상한·last-good·runtime unknown·로그인/메뉴·executor/resource/batch·OpenAPI/M05·가이드 계약도 이어서 검토했다. PinVi UI와 Common UI가 이번 Python 변경으로 새 구현됐다고 집계하지 않는다. 후속 docs/evidence-only closure는 제품 FULL 변경과 구분해야 한다.

## 이전 findings disposition

| ID | 원래 심각도 | 이 후보의 상태 | 근거 |
| --- | --- | --- | --- |
| J-CONSUMER-P1-01 | P1 | FIXED | allow-direct-references=true 추가, own clean wheel build 성공 |
| J-CONSUMER-P1-02 | P1 | FIXED — 코드 prerequisite | Map API builder Git 명시. 실제 fresh Docker gate는 본인 NOT_RUN |
| J-CONSUMER-P2-01 | P2 | FIXED | controlled 선택/기존 실제 detail hook/다음 event cursor, run 전환 reset 직접 RTL PASS |
| J-CONSUMER-P2-02 | P2 | OPEN — 부분 수정 | 원래 missing fields는 error, 정상 empty는 ok. foreign repository/location이 여전히 ok |

P1-02는 기존 공식 builder에 필요한 Git 누락을 코드에서 닫았다는 뜻이다. 본인이 production Docker를 실행하거나 최종 image/운영 provenance를 검증했다고 주장하지 않는다. 최종 배포 게이트는 별도다.

## J-CONSUMER-P2-02 — expected repository identity 불일치가 정상으로 수용됨

심각도 P2 유지. 위치: Map packages/kor-travel-map-api/src/kortravelmap/api/dagster_query_service.py:179-213,353-357 및 frontend/src/components/common-dagster-panel.tsx:50.

새 _valid_summary_repository는 name/location.name의 문자열 존재와 collection/행 기본 구조를 검사하지만 설정의 repository selector와 name/location을 비교하지 않는다. 원래 finding 권고의 “손상·불일치·누락 fail-closed” 중 불일치가 남아 있다.

직접 실제 get_summary/HTTPX MockTransport에 세 경우를 주입했다.

1. 원래 {__typename:Repository}만 있는 경우 → status=error. 원래 missing-fields 재현은 닫혔다.
2. 정확한 설정 name/location과 정상 빈 네 collection → status=ok. valid empty를 잘못 차단하지 않는다.
3. name=geo_repository, location.name=geo_location, pipelines=[{name:geo_job,isJob:true}]와 정상 빈 다른 collection → status=ok, job_count=1, errors=[].

세 번째의 실제 요청 설정 selector는 __repository__@kortravelmap.dagster.definitions였다. 다른 프로젝트 응답이 정상 스냅샷으로 표시되고 location 링크도 그 identity를 따른다. last-good 보존 조건은 status!=ok만 오류이므로 정상 Map snapshot을 대체할 수 있다. GraphQL selector를 올바르게 보내는 것과 응답 identity 검증은 별개의 경계다.

최소 수정/closure 조건: helper에 expected name/location을 넘겨 모두 일치하는지 검사한다. 정상 empty, foreign name, foreign location, malformed connection, 정상 metadata를 실제 application function과 last-good 소비에서 회귀 검증한다. 프로젝트가 다른 live 서비스에 실제 요청한 것은 아니다. 본인 fixture만 주입했다.

스크립트: probes/repository-postfix-probe.py
SHA256 a913260d8c9309630ac335c6359185ee41c637d66b30cab346686c07ed1d798a.
결과: repository-postfix-result.txt
SHA256 96e04d67bf287213c67efe48ec614be1d1dac9ee57e0d10538a92959f2b2c9dc.

## J-CONSUMER-P2-03 — 필터 뒤 다른 실행의 실패 상세를 구별할 identity가 없음

새 심각도 P2. 위치: Map frontend/src/components/common-dagster-panel.tsx:67의 custom renderRunDetail 및 src/app/ops/pipeline/events-panel.tsx:346-399.
Common renderer의 사용자 정의 슬롯은 기본 상세 jobName/runId/status/runtime 상한 표시를 통째로 대체한다. 현재 callback은 기존 DagsterRunDetail만 렌더하고 그 컴포넌트는 failure_reason/events/pagination만 표시한다.

실제 일상 시나리오를 직접 RTL로 재현했다.

1. job_alpha/alpha와 job_beta/beta 실패 두 개를 표시한다. 두 실패 원인은 흔한 동일 Worker unexpectedly exited다.
2. alpha를 선택해 실패 상세를 연다.
3. 실행 검색을 job_beta로 바꾼다.
4. 표에는 beta만 남지만 alpha 상세는 선택 유지 정책대로 남는다.
5. 상세 region에는 generic 원인/이벤트만 있고 job_alpha나 alpha run ID가 없다.

다른 실행의 실패 원인을 현재 보이는 beta의 실패로 오인할 수 있다. 기존 인라인 상세는 자신의 행 안에 있었지만 새 별도 상세 영역은 선택 대상의 시각 identity를 필요로 한다. 선택 자체를 유지하는 정책은 문제로 보지 않는다. 코드가 runId key로 cursor를 초기화하는 것도 올바르다.

own 테스트는 alpha 행 숨김·beta 행 단독·기존 상세 잔존을 먼저 확인한 뒤, 상세 안의 job_alpha identity assertion에서 정확히 FAIL했다. selector 변경이나 network 오류 때문에 실패한 것이 아니다.

최소 수정/closure 조건: custom 상세 wrapper에 선택 job 이름·전체 run ID·현재 status를 명시한다. default 상세를 대체하므로 알려진 runtime 상한/unknown 상태도 함께 유지하면 운영 해석에 도움이 된다. 검색/상태 필터로 선택 행이 사라져도 상세 identity를 확인하는 회귀를 추가한다.

스크립트: probes/detail-identity.attack.test.tsx
SHA256 e366365b2e8135ddfa7f34aa5e248622c7dabcd35556e9bdf2d6518760e9c057.
결과: ui-detail-identity-postfix-result.txt
SHA256 4f76b964fc44174a5c2ded0f5c691eb138f35a8784fa539d71baaf22e07949b8.
직접 결과 1FAIL, exit1,42.70초.

## 직접 EXECUTED

- immutable Git archive·manifest70개 SHA 검증, 종료 시 같은 고정 bytes 재확인.
- 두 UI dev.6 tarball SHA256 e4945d01d9eb89ed505a95b551899fd0ecf41be66c9ee6b76246701350447e6d, package-lock integrity와 실제 읽기 재사용 설치 @kor-travel/ui24파일 bytes가 전부 일치.
- Map 현재 OpenAPI/PinVi admin vendor byte-exact. 공개 user/service 소비 계약 bytes 변경을 추가하지 않은 admin delta다.
- PinVi own clean uv build --wheel --offline PASS. wheel SHA256 59c37d98837d8ca258a3fbfa3c6e82798923b827bb58155900f423d4f824a212. wheel METADATA의 Common1f8[http] direct dependency와 wheel 안의 M05 contract_data 원천 bytes를 직접 대조했다.
- Map test_dagster_bounded_summary.py + test_application_http_adapters.py + test_snapshot_batching.py: 합계24PASS/1.68초. 실제 PostgreSQL 봉인/rollback 실행은 아니다.
- PinVi test_admin_etl_dagster_probe.py + test_kor_travel_map_admin_contract.py: 합계39PASS/1.22초. 새 정상/timeout/error/caller cancel × slow close50ms unit도 포함한다.
- 추가 own PinVi OSError cleanup 실패 주입4건: 정상 body→ok, body ConnectError→down, timeout→down, 외부 취소→원CancelledError 유지. client.is_closed=true를 확인했고 log는 정적 경고만 남겨 synthetic private body/close 원문이 노출되지 않았다. 실제 foreign 서비스나 실제 TCP pool 장애를 만들지 않았다.
- 실제 기존 detail hook을 사용한 own RTL2PASS/42.02초: 클릭 전에 detail GET0건, 선택 후 실제 /v1/ops/pipeline/dagster-runs 경로, 다음 cursor, 다른 run의 cursor 초기화, degraded200 summary 뒤 선택/상세 유지, 같은 행 다시 클릭 시 상세 닫힘, summary unmount AbortSignal.aborted=true.
- repository 3경계 직접 공격: missing/error, valid empty/ok, foreign/ok 잔여 finding 재현.
- 필터 뒤 identity 추가 공격1FAIL: 새 P2-03을 직접 재현.

최초 detail harness는 pathWithQuery를 mock에서 빠뜨려1FAIL/1PASS였다. 그 출력은 ui-detail-postfix-harness-missing-export-result.txt로 따로 보존하고 fixture의 mock만 actual module을 보존하는 방식으로 정정했다. 제품 source는 바꾸지 않았다. 정정 후2PASS가 상세 closure 근거이며 최초 harness 오류를 제품 결함으로 집계하지 않았다.

본인 probes와 명령 정본은 /home/digitie/.cache/james-map-pinvi-postfix-20261005/probes 아래다. Linux Node22.22.2/Vitest4.1.10/jsdom 실행이다.

```bash
/usr/local/bin/node /mnt/f/dev/kor-travel-map-codex-dagster/node_modules/vitest/vitest.mjs run --root /home/digitie/.cache/james-map-pinvi-postfix-20261005/probes --config /home/digitie/.cache/james-map-pinvi-postfix-20261005/probes/vitest.config.mts --no-cache
```

위 명령은 현재 own 두 test 파일을 함께 실행하므로2PASS/1FAIL이 기대된다. repository/PinVi probe는 원문 후보 때와 같은 고정 PYTHONPATH 구성에서 본인 Python 파일을 실행한다. 상세 원문 결과·script hash는 고정 cache에 남겼다.

## 유지된 계약과 NOT_RUN

Map의 여섯 사전 P2는 앞선 FULL 보고서에서 닫은 기존 재현 상태를 유지한다. 공통 로그인/메뉴/redirect/error clear·실패 logout 처리, separate active query·1000 상한·HTTP200 degraded last-good, invalid/없는 runtime cap=null, tick의 상태/시각만 전달, repo@location 단일 URL segment, 기존 canonical execution/command recovery 경계를 이번 전체 delta에서도 유지했다. HTTP finally 변경은 client 재사용을 만들지 않으며 정상/오류/cancel을 다른 HTTP 요청이나 쓰기 job 재실행으로 전파하지 않는다.

snapshot batching은 배치100·기존 단일 transaction/봉인 API를 소비하고, executor step1/DB pool1/overflow0·SQL/lock 제한과 RecoveryPolicy write retry0를 유지한다. 운영 shared Manager daemon의 run monitoring·queue·실제 timeout terminal 복구는 이 소스만으로 완료라고 판단하지 않는다. 메모리 구조 개선을 실제 전체 RSS 감소 수치로 바꾸지 않는다.

검토자 직접 전체390 UI/type/lint/build/Doctor·strict96/247·전체 backend·최종 GitHub CI·fresh production Docker/image provenance·실제 Dagster daemon/worker중단·실제 PG rollback·paired M05 activation/attestation·운영 재구축/RSS·N150 브라우저 로그인/JWT/RBAC/cookie/CSRF·desktop/mobile 폭/overflow/키보드 Arrow/스크린리더·live outage recovery·PR merge는 NOT_RUN이다. parent의 별도 PASS 수치와 진행 상황은 본인 수행에 합산하지 않는다. jsdom으로 실제 모바일 CSS나 browser keyboard gate를 통과했다고 주장하지 않는다.

두 OPEN P2에 대해 새 고정 후보의 반례 closure가 필요하다. 현재 BLOCK 원문 및 이전 BLOCK 원문은 변하지 않는다. 이 검토는 코드 수정·stage·commit·push를 수행하지 않았다.
