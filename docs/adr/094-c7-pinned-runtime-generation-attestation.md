# ADR-094: C7 신뢰 경계를 compatible-pair manifest v4에서 pinned runtime generation v5 + rebuild journal v7로 옮긴다

- 상태: accepted
- 날짜: 2026-08-20
- 결정자: human, AI agent
- 관계: [ADR-076](076-c6c-manifest-v4-map-runtime-provenance.md)을 대체한다.
  [ADR-079](079-openapi-digest-not-pinned-in-compatible-pair.md)의 **판단은 유지**하되 그 대상
  artifact가 C7 경계에서 퇴역하므로 함께 대체한다.

## 컨텍스트

ADR-076은 C6c compatible-pair manifest v4에 Map 네 runtime image의 provenance를 결박했다.
ADR-079는 거기에 OpenAPI digest를 더하자는 v5 승격 제안을 기각하고 v4를 유지했다.

그 뒤 docker-manager가 파괴적 재구축 transaction을 도입하면서 **다른 계보의 문서**가 생겼다 —
`PinnedRuntimeManifest` v5와 `PinnedRuntimeRebuildJournal` v7이다. 이 둘은 compatible-pair
manifest에 필드를 더한 것이 아니라, 재구축 transaction이 소유하는 별도 artifact다.

T-VN-41F1D 계열 acceptance를 준비하면서 v4가 실제로 무엇을 보고 있었는지 다시 실측했다.

- **v4 pair는 다섯 image만 담는다** — Map API·UI·Dagster web·Dagster daemon과 PinVi API.
  PinVi web과 PinVi dagster는 세대 밖이라, 그 둘이 어떤 image로 떠 있든 attestation이 통과했다.
- v4에는 schema head가 없다. 배포된 코드와 DB head의 불일치는
  `docs/reports/incident-2026-07-27-*.md`가 지목한 실패 모드인데 pair는 그것을 담지 않는다.
- v4 manifest만으로는 "어떤 세대가 active인가"는 알아도 **"그 세대가 파괴적 rebuild를 끝까지
  통과했는가"** 를 알 수 없다. 그 사실은 journal만 안다.
- v4의 `rollback` slot은 DB preimage가 없는 세대를 가리켰다. v5는 그 slot을 아예 없앴다 —
  되돌릴 수 없는 것을 되돌릴 수 있는 것처럼 기록하지 않는다.

## 결정

C7 production live runner와 admin feature live acceptance runner의 **attested input을
v5 pinned runtime manifest + v7 rebuild journal 두 문서로 바꾼다.** v4 compatible-pair
manifest는 이 경계에서 퇴역한다.

1. env는 `E2E_C7_COMPATIBLE_PAIR_MANIFEST` 하나에서
   `E2E_C7_PINNED_RUNTIME_MANIFEST` + `E2E_C7_REBUILD_JOURNAL` 둘로 나눈다.
2. runtime role을 **다섯에서 일곱으로** 늘리고 compose service env 두 개
   (`E2E_C7_PINVI_WEB_SERVICE`, `E2E_C7_PINVI_DAGSTER_SERVICE`)를 신설한다. 일곱 image를
   전부 `docker inspect`로 실측 대조한다.
3. host attestation document를 version 3에서 **4**로 올린다.
   `compatible_pair_manifest_sha256`·`c6c_contract_generation`을 빼고
   `pinned_runtime_manifest_sha256`·`rebuild_journal_sha256`·`rebuild_transaction_id`·
   `pinned_runtime_pinset_sha256`·`schema_heads`를 넣는다.
4. journal은 phase `committed`, candidate가 manifest `active_generation`과 **전체 동등**,
   cancel probe `finalized`를 요구한다. 부분 비교는 두 문서가 같은 transaction의 앞뒤라는 것을
   증명하지 못한다.
5. Map application schema head는 runner가 이미 측정하는 **실제 Alembic head**와도 대조한다.
   문서끼리만 비교하면 image 일곱은 실측하면서 head만 서류상 일치인 비대칭이 남는다.
6. **v4를 억지로 넣어 통과하는 compatibility 경로는 만들지 않는다.** v4 manifest는
   `manifest shape`로 fail-close된다.
7. evidence manifest version을 1에서 2로 올린다. attested document 구성이 바뀌었기 때문이다.
   audit은 v1 archive를 legacy로 인정하되 **그 시절 계약으로 그대로 검사한다** — 과거 증거를
   지우게 만들지 않으면서 "옛것은 무조건 통과"도 아니게 한다.

## 근거

- **정확성이 첫째다.** 일곱 runtime을 한 세대로 고정하는 것은 다섯만 고정하는 것보다 엄격히
  강하다. schema head와 pinset 결박도 마찬가지로 순증이다.
- **단일 정본.** v4와 v5를 함께 받으면 "어느 쪽이 정본인가"가 실행 시점 env에 따라 갈린다.
  호환 경로를 두지 않는 이유다.
- **ADR-079와 충돌하지 않는다.** ADR-079가 기각한 것은 *compatible-pair manifest에 OpenAPI
  digest를 더하는 것*이었고, 그 판단(OpenAPI 결박은 receipt/contract 계층이 소유한다)은 지금도
  유효하다. 이 ADR은 그 필드를 되살리지 않는다 — manifest 계보 자체를 교체한다.

## 결과

- 저장소측 계약(runner·검증 모듈·state/audit helper·unit test·runbook)은 2026-08-20 완료.
- n150 data-dependent 실행은 v5/v7 문서가 존재해야 가능하고, 그 문서는 파괴적 rebuild
  transaction이 처음 만든다. 실행 시점·선행조건은 백로그 `T-VN-FINAL-REBUILD`가 소유한다.
- v5/v7은 `require_rebuildable_mode` 아래에서만 생성된다(ktdm `rehearsal`/`rebuildable`).
  ktdm state root는 Manager owner 소유 `0700`이고 runner는 root 소유 `0600`을 요구하므로,
  운영자가 내용을 바꾸지 않은 root 소유 사본을 만들어 넘긴다.
- 이전 v4 후보 archive(`contracts/vnext/t-vn-41-candidate-*.json`)는 **detached 이력으로
  불변**이다. 현행 계약이 바뀌었다고 과거 증거의 모양을 고쳐 쓰면 이력이 아니라 위조다.
