# tasks.md — 활성 작업

이 문서는 완료되지 않은 작업만 의존 순서대로 한 줄씩 나열한다. lane, 병렬 담당자,
계층형 하위 작업은 사용하지 않는다. 완료 이력은
[`docs/tasks-done.md`](tasks-done.md), 현재 실행 증적과 다음 한 작업은
[`docs/resume.md`](resume.md)가 정본이다. **각 항목의 해제 조건(acceptance
criteria)은 [`docs/tasks-acceptance.md`](tasks-acceptance.md)가 소유한다** —
2026-08-27 평면화(`6d671ef1`)가 열린 항목의 판정 근거까지 지웠고, 그 직후
`T-VN-FINAL-REBUILD`가 조건이 사라진 상태로 완료 처리된 사고가 있었다.

- [~] T-VN-FINAL-REBUILD — **배리어는 열리지 않았다.** `030b12fc…`의 공식 `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 seven-runtime과 v6/v8 committed 증적, Map application `300`·Map Dagster·PinVi `20260824_0101` schema head를 확인한 것은 사실이나, 이 task의 해제 조건 B1~B4는 삭제 직전 **전부 미체크**였고(`git show 6d671ef1^:docs/tasks.md` 739~752행) 평면화가 그 체크박스를 지운 다음 날 `b3bbd3a3`이 `[ ]`→`[x]`로 바꿨다 — 조건이 충족된 것이 아니라 사라진 것이다. generation `8eedf171…` 이후 `3d8d63e1`·`7035b0b1`·`82850711`·`5592a1d4`·`9b6eab1e` 등 최소 5개 pinset에서 새 image·새 Manager source로 rebuild가 다시 실행됐으므로 B3/B4는 반복적으로 false다. 해제 조건 원문은 [`docs/tasks-acceptance.md`](tasks-acceptance.md) 참조. historical `cbb`·`52`·`06045`·`68d99705`·`285618c0`·`37932169`·`31fe73ad`·`b22bfb8c`·`89330403`·`c6c73cdf` candidate는 재시도하지 않는다.
- [ ] T-VN-M05-ACTIVATION — `a3f6a8f3…`·`22563762…`·`c700bd2e…`·`fa28a6e7…`·`5512ce12…`·`41be91fe…`·`b46743ea…`·`5ad3b08c…`·`5592a1d4…`에 이어 Map `35a43317…`·PinVi `fed16a5c…`·Manager `eed1920…`·pinset `82850711…`도 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, registry/public generation `match` gate 뒤 n150 isolated M04/M05 launcher를 정확히 한 번 실행해 terminal로 차단됐다. 공개 registry의 고정 phase는 `runtime_setup`이며 HTTP·컨테이너·환경·output leaf 원문은 열지 않는다. 모든 terminal pinset과 각 source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는 isolated runtime setup의 ordinary exception을 raw detail 없이 더 좁은 allowlist phase로 수렴시켜 다음 immutable candidate의 보정 범위만 좁힌다. 이후 pinning·pair 결박·one-shot 계약은 Docker Manager trusted `ktdctl`과 `runtime-pins`·`pinned-runtime/generation` 공개 API만 사용한다. PinVi isolated Compose는 Manager가 transaction·pinset·세 source revision에 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만 허용하며, legacy 환경변수 marker·수동 Compose는 권한이 아니다. 재개 시에만 새 Map revision·새 PinVi provenance·새 Manager source를 atomic `pin rotate-pair`로 함께 결박한다. 회전 뒤에는 trusted `run-pinned-rebuild-once`가 current public generation을 만든 후 새 root-owned leaf에서 한 번만 실행하며, 최신 CI·전문 적대 리뷰 두 건·terminal 아님을 모두 만족해야 M04/M05 live acceptance attestation을 승격한다.
- [ ] T-VN-41F1D-D1 — 최종 격리 리허설과 provenance attestation을 기록한다.
- [ ] T-VN-41F1D-D2 — data-dependent Map/PinVi admin live E2E를 통과하고 receipt를 승격한다.
- [ ] T-VN-41C — relay, reconciliation, consumer enable의 paired acceptance를 완료한다.
- [ ] T-VN-41F1D-E — 이전 generation을 퇴역하고 v6/v8 attestation 전환을 완료한다.
- [ ] T-FE-MOCK-FLAKE — n150 live GET-only로 mocked checkpoint 잔여를 해소한다.
- [ ] T-VN-M01 — admin Feature 생성 API의 live clean-cutover를 완료한다.
- [ ] T-VN-M02 — Feature origin/provenance 보존·불변성의 live acceptance를 완료한다.
- [ ] T-VN-M03 — curated 동시 생성의 import 및 live acceptance를 완료한다.
- [~] T-VN-M04 — 범용 Feature 요청 큐의 paired consumer acceptance를 완료한다.
- [~] T-VN-M05 — provider 발행 Feature 중복 판정과 paired reconciliation을 완료한다.
- [ ] T-VN-H34 — 공식 curation 미연결 membership의 남은 acceptance criteria를 마무리한다.
- [ ] T-VN-H43 — production backup의 정기 dump, SHA-256, 보존, rollback 기준선을 확정한다.
- [ ] T-VN-H49 — 4분할 인스턴스 backup의 주기 실행, bounded retention, off-box 증거를 완료한다.
- [ ] T-VN-H49-GEO-DAGSTER — geo_dagster metadata DB의 standalone backup을 검증한다.
- [ ] T-VN-H49-CONCIERGE — Concierge의 standalone backup을 검증한다.
- [ ] T-VN-H49-PINVI — PinVi의 standalone backup을 검증한다.
- [ ] T-VN-H49-OFFBOX — off-box 복제 자동화를 결선하고 backup 문서를 현행화한다.
- [ ] T-VN-39 — KTM·PinVi write-fence cutover를 수행한다.
- [ ] T-101 — cluster rollup materialized view 도입 조건을 재검토한다.
