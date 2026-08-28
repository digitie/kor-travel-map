# tasks.md — 활성 작업

이 문서는 완료되지 않은 작업만 의존 순서대로 한 줄씩 나열한다. lane, 병렬 담당자,
계층형 하위 작업은 사용하지 않는다. 완료 이력은
[`docs/tasks-done.md`](tasks-done.md), 현재 실행 증적과 다음 한 작업은
[`docs/resume.md`](resume.md)가 정본이다.

- [/] T-VN-M05-ROLE-CATALOG-RESET — `31fe73ad…`·`b22bfb8c…`·`c6c73cdf…` n150 candidate는 각각 `target_not_isolated`·`foreign_membership`·`foreign_membership` terminal로 보존하며 재시도하지 않는다.
- [x] T-VN-M05-MANAGER-PIN-ROTATION — `030b12fc…` committed generation과 `6269138f…`·`53d4639f…` 단회 시도는 재실행하지 않는다. `53d4639f…`은 installed launcher execute bit 미보존으로 admission 이전에 종료했고 durable output·ledger·raw stderr가 없다. PinVi `41a36ee6…`·Map `9c64e862…`와 Manager canonical pinset `c1ad5a3e…`은 root-owned structured result launcher로 정확히 한 번 실행돼 `committed` 됐다(generation `8eedf171…`, Map application `300`, Map Dagster `29b539ebc72a`, PinVi `20260824_0101`).
- [x] T-VN-FINAL-REBUILD — `030b12fc…`의 공식 `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 seven-runtime과 v6/v8 committed 증적, Map application `300`·Map Dagster·PinVi `20260824_0101` schema head를 확인했다. historical `cbb`·`52`·`06045`·`68d99705`·`285618c0`·`37932169`·`31fe73ad`·`b22bfb8c`·`89330403`·`c6c73cdf` candidate는 재시도하지 않는다.
- [/] T-VN-M05-ADMISSION-TERMINAL — `7035b0b1…`은 Map `3916ebfd…`·PinVi `73870e52…`·Manager `291bd161…`를 clean trusted release, atomic `ktdctl pin rotate-pair`, 단발 pinned rebuild, public generation `match`로 결박한 뒤 n150 isolated M04/M05 launcher를 새 root-owned leaf에서 정확히 한 번 실행해 unconditional terminal로 차단한 결과다. 공개 fixed phase는 `runtime_setup_admission`이며 HTTP·container·환경·output leaf·private receipt 원문은 열지 않는다. `3d8d63e1…`은 Map `0cb126fc…`·PinVi `9372137e…`·Manager `712ae8c…`의 rebuild가 공개 generation `match`까지 도달했지만 외부 `pin block`이 lock 보유 중 기록한 제어면 terminal 때문에 M04/M05 launcher를 실행하지 않는 별도 terminal이다. Manager `03a3300…`은 외부 root block뿐 아니라 모든 runtime pin mutation을 active global mutation에서 거절하고 trusted launcher의 inherited-lock fallback만 허용한다. 이 pinset·source pair·Manager source·leaf는 재실행하지 않는다. Map `86d38d46…`·PinVi runtime source `3b9d6026…`·해당 Manager source가 동결된 fresh candidate이며, 문서 전용 병합은 이를 재결박하지 않는다. CI와 exact-head 전문 적대 리뷰 두 건이 모두 GO일 때만 fresh pair를 만든다.
- [ ] T-VN-M05-ACTIVATION — `a3f6a8f3…`·`22563762…`·`c700bd2e…`·`fa28a6e7…`·`5512ce12…`·`41be91fe…`·`b46743ea…`·`5ad3b08c…`·`5592a1d4…`에 이어 Map `35a43317…`·PinVi `fed16a5c…`·Manager `eed1920…`·pinset `82850711…`도 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, registry/public generation `match` gate 뒤 n150 isolated M04/M05 launcher를 정확히 한 번 실행해 terminal로 차단됐다. 공개 registry의 고정 phase는 `runtime_setup`이며 HTTP·컨테이너·환경·output leaf 원문은 열지 않는다. 모든 terminal pinset과 각 source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는 isolated runtime setup의 ordinary exception을 raw detail 없이 더 좁은 allowlist phase로 수렴시켜 다음 immutable candidate의 보정 범위만 좁힌다. 이후 pinning·pair 결박·one-shot 계약은 Docker Manager trusted `ktdctl`과 `runtime-pins`·`pinned-runtime/generation` 공개 API만 사용한다. PinVi isolated Compose는 Manager가 transaction·pinset·세 source revision에 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만 허용하며, legacy 환경변수 marker·수동 Compose는 권한이 아니다. 재개 시에만 새 Map revision·새 PinVi provenance·새 Manager source를 atomic `pin rotate-pair`로 함께 결박한다. 회전 뒤에는 trusted `run-pinned-rebuild-once`가 current public generation을 만든 후 새 root-owned leaf에서 한 번만 실행하며, 최신 CI·전문 적대 리뷰 두 건·terminal 아님을 모두 만족해야 M04/M05 live acceptance attestation을 승격한다.
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
