# tasks.md — 활성 작업

이 문서는 완료되지 않은 작업만 의존 순서대로 한 줄씩 나열한다. lane, 병렬 담당자,
계층형 하위 작업은 사용하지 않는다. 완료 이력은
[`docs/tasks-done.md`](tasks-done.md), 현재 실행 증적과 다음 한 작업은
[`docs/resume.md`](resume.md)가 정본이다. **각 항목의 해제 조건(acceptance
criteria)은 [`docs/tasks-acceptance.md`](tasks-acceptance.md)가 소유한다** —
2026-08-27 평면화(`6d671ef1`)가 열린 항목의 판정 근거까지 지웠고, 그 직후
`T-VN-FINAL-REBUILD`가 조건이 사라진 상태로 완료 처리된 사고가 있었다.

- [~] T-VN-M05-ACTIVATION — 새 pinset 한 번의 실행으로 M04/M05 live acceptance attestation을 승격한다. **2026-09-04 실측**: `e2e025`가 pinset `e6b52db4`·Manager `b3217edc`에서 `status: passed`로 닫혔고(m04 `f08620a9…`, m05 `37320bb5…`, provenance `25a80946…`, `m04_server_side_chain_verified: true`), 실행 후에도 봉인 트리가 `_validate_immutable_tree` ACCEPT라 **같은 pinset 재실행이 가능하다** — 이전 두 번은 그렇지 않았다. 승격 판정은 소유자 몫이다. 착수 전 [`docs/tasks-acceptance.md`](tasks-acceptance.md)의 A1~A4와 terminal 재실행 금지 목록을 확인한다.
- [ ] T-VN-41C — **보류**(사용자 지시 2026-09-07). relay·reconciliation은 **구현이 끝나 있다** — lease·retry·dead-letter·replay 4/4가 `cache_target_outbox_repo.py`에, 5-status 상태기계와 DB 대조(두 번 server-cursor scan + Merkle root)가 `cache_target_reconciliation_repo.py`에 있고 라우터가 끝까지 부른다(2026-09-06 재조사가 종전 "구현이 남았다" 서술을 정정했다). 남은 것은 **런타임 결선과 consumer enable**인데, 현 lifecycle(rehearsal/rebuildable)에서 **enable과 pinned rebuild가 상호배타**다 — 켜면 `environment_sha256`이 바뀌어 rebuild가 필요한데 Manager `require_rebuildable_mode`는 cache-target 값이 inert 기본값일 때만 rebuild를 허용한다. 소유자가 셋 중 (c)를 택했다: **실 production 전환 시점까지 enable을 미룬다.** 그때 재개하며 그 전까지 규약 §보류에 따라 잔여로 세지 않는다. 재개 시 착수 순서와 남은 다섯 조각은 [`docs/tasks-acceptance.md`](tasks-acceptance.md) §T-VN-41C가 갖는다.
- [ ] T-FE-MOCK-FLAKE — n150 live GET-only로 mocked checkpoint 잔여를 해소한다.
- [ ] T-VN-M02 — Feature origin/provenance 보존·불변성의 live acceptance를 완료한다.
- [~] T-VN-M04 — 범용 Feature 요청 큐. 구현은 병합됐고(#1029, PinVi #458·#465), **남은 paired request→approval receipt와 isolated acceptance는 `T-VN-41C`가 소유한다** — 해제 조건이 그렇게 위임하고 있어 이 줄은 그 범위를 다시 세지 않는다(2026-09-04 중복 정리). 2026-09-04 `e2e025`가 submit→pending receipt→PinVi approval 사슬을 닫았다 — `m04_server_side_chain_verified: true`는 **M05** attestation payload에 있고 M04 payload에는 없다(2026-09-04 실측으로 정정).
- [~] T-VN-M05 — provider 발행 Feature의 **중복 판정 계약**(ADR-097)과 그 판정 결과의 paired 전파를 완료한다. `T-VN-41C`의 reconciliation은 relay/DB 대조라 **다른 것**이고, live acceptance를 실제로 태우는 실행 수단은 `T-VN-M05-ACTIVATION`이다(2026-09-04 중복 정리 — 삼중 계상은 낱말 충돌이었고 범위는 셋 다 다르다).
- [ ] T-VN-H34 — 공식 curation 미연결 membership의 남은 acceptance criteria를 마무리한다.
- [ ] T-VN-H43 — **보류**(사용자 지시 2026-08-06). 기준선 dump·sha256·rollback 기준선은 완료됐고 남은 정기화·2차 외부 사본 자동화는 **현 환경에서 수행하지 않는다**(n150은 실 production이 아니며 손상 시 재적재가 정책). 실 prod 전환 시 manager #148로 재개한다. off-box 자동화의 현 소유자는 `T-VN-H49-OFFBOX`다 — 규약 §보류에 따라 잔여로 세지 않는다(2026-09-04 중복 정리).
- [ ] T-VN-H49 — **Geo application DB**의 `scheduled_backup`·retention janitor가 최근 성공과 bounded retention으로 수렴하는지 운영 증거를 남긴다. 나머지 세 인스턴스와 off-box는 아래 `-GEO-DAGSTER`/`-CONCIERGE`/`-PINVI`/`-OFFBOX`가 소유한다 — 해제 조건이 그것들을 자기 체크리스트로 열거하므로 이 줄은 자식 범위를 다시 세지 않는다(2026-09-04 중복 정리).
- [ ] T-VN-H49-GEO-DAGSTER — geo_dagster metadata DB의 standalone backup을 검증한다.
- [ ] T-VN-H49-CONCIERGE — Concierge의 standalone backup을 검증한다.
- [ ] T-VN-H49-PINVI — PinVi의 standalone backup을 검증한다.
- [ ] T-VN-H49-OFFBOX — off-box 복제 자동화를 결선하고 backup 문서를 현행화한다.
- [ ] T-VN-39 — KTM·PinVi write-fence cutover를 수행한다.
- [ ] T-101 — cluster rollup materialized view 도입 조건을 재검토한다.
