# tasks.md — 활성 작업

이 문서는 완료되지 않은 작업만 의존 순서대로 한 줄씩 나열한다. lane, 병렬 담당자,
계층형 하위 작업은 사용하지 않는다. 완료 이력은
[`docs/tasks-done.md`](tasks-done.md), 현재 실행 증적과 다음 한 작업은
[`docs/resume.md`](resume.md)가 정본이다.

- [/] T-VN-M05-ROLE-CATALOG-RESET — `31fe73ad…`·`b22bfb8c…`·`c6c73cdf…` n150 candidate는 각각 `target_not_isolated`·`foreign_membership`·`foreign_membership` terminal로 보존하며 재시도하지 않는다.
- [/] T-VN-M05-MANAGER-PIN-ROTATION — `030b12fc…` committed generation과 `6269138f…` pre-journal 단회 시도는 재실행하지 않는다. PinVi draft PR [#500](https://github.com/digitie/pinvi/pull/500)의 `55687a4f…`·Map `9c64e862…`와 Manager draft PR [#243](https://github.com/digitie/kor-travel-docker-manager/pull/243)의 canonical pinset `53d4639f…`만 다음 n150 trusted candidate다. root-owned structured result launcher로 이 새 pinset을 정확히 한 번 실행한다.
- [x] T-VN-FINAL-REBUILD — `030b12fc…`의 공식 `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 seven-runtime과 v6/v8 committed 증적, Map application `300`·Map Dagster·PinVi `20260824_0101` schema head를 확인했다. historical `cbb`·`52`·`06045`·`68d99705`·`285618c0`·`37932169`·`31fe73ad`·`b22bfb8c`·`89330403`·`c6c73cdf` candidate는 재시도하지 않는다.
- [ ] T-VN-M05-ACTIVATION — committed `53d4639f…` candidate에서만 isolated n150 M04/M05 live mutating E2E와 activation attestation을 실행한다.
- [ ] T-VN-41F1D-D1 — 최종 격리 리허설과 provenance attestation을 기록한다.
- [ ] T-VN-41F1D-D2 — data-dependent Map/PinVi admin live E2E를 통과하고 receipt를 승격한다.
- [ ] T-VN-41C — relay, reconciliation, consumer enable의 paired acceptance를 완료한다.
- [ ] T-VN-41F1D-E — 이전 generation을 퇴역하고 v6/v8 attestation 전환을 완료한다.
- [ ] T-FE-MOCK-FLAKE — n150 live GET-only로 mocked checkpoint 잔여를 해소한다.
- [ ] T-VN-M01 — admin Feature 생성 API의 live clean-cutover를 완료한다.
- [ ] T-VN-M02 — Feature origin/provenance 보존·불변성의 live acceptance를 완료한다.
- [ ] T-VN-M03 — curated 동시 생성의 import 및 live acceptance를 완료한다.
- [/] T-VN-M04 — 범용 Feature 요청 큐의 paired consumer acceptance를 완료한다.
- [/] T-VN-M05 — provider 발행 Feature 중복 판정과 paired reconciliation을 완료한다.
- [ ] T-VN-H34 — 공식 curation 미연결 membership의 남은 acceptance criteria를 마무리한다.
- [ ] T-VN-H43 — production backup의 정기 dump, SHA-256, 보존, rollback 기준선을 확정한다.
- [ ] T-VN-H49 — 4분할 인스턴스 backup의 주기 실행, bounded retention, off-box 증거를 완료한다.
- [ ] T-VN-H49-GEO-DAGSTER — geo_dagster metadata DB의 standalone backup을 검증한다.
- [ ] T-VN-H49-CONCIERGE — Concierge의 standalone backup을 검증한다.
- [ ] T-VN-H49-PINVI — PinVi의 standalone backup을 검증한다.
- [ ] T-VN-H49-OFFBOX — off-box 복제 자동화를 결선하고 backup 문서를 현행화한다.
- [ ] T-VN-39 — KTM·PinVi write-fence cutover를 수행한다.
- [ ] T-101 — cluster rollup materialized view 도입 조건을 재검토한다.
