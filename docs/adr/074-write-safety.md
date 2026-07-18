# ADR-074: Domain-owned replay, revision, outbox 쓰기 안전성

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-10

## 컨텍스트

일부 pipeline·schedule command에는 append-only replay ledger와 CAS가 있지만 다른 write에는
같은 의미가 없다. transport retry, stale admin 수정, cache-target 세대 역전이 서로 다른
오류를 만들며 하나의 범용 ledger로 합치면 lifecycle이 더 불명확해진다.

## 결정

1. 재시도가 필요한 각 command domain은 `(principal namespace, Idempotency-Key)`와 정규화 body
   fingerprint, 최초 결과를 저장하는 append-only ledger를 소유한다. 같은 key/같은 body는 결과를
   replay하고 다른 body는 409다.
2. mutable resource는 단조 `row_revision`과 `If-Match`를 사용하며 stale write는 412다.
   기존 policy revision은 resource-specific 선례로 유지한다.
3. cache target은 `(external_system, target_key)` identity, 단일 canonical coordinate,
   `source_generation`과 restore epoch을 가진다. 낮은 generation은 적용하지 않는다.
4. DB commit 뒤 외부 전파는 transactional outbox와 멱등 relay가 담당한다. critical write path에서
   원격 consumer 성공을 기다리지 않는다.
5. pipeline exact-scope active operation UNIQUE와 Idempotency-Key replay는 각각 업무 single-flight와
   HTTP 재시도 책임으로 직교한다.

## 근거

resource lifecycle에 맞는 안전장치를 각 domain이 소유해야 replay 결과와 동시성 의미가 분명하다.
revision과 outbox는 lost update와 dual-write를 별도로 해결한다.

## 결과

- **긍정**: 재시도, 경쟁 수정, 순서 역전, 외부 전파 실패를 구분하고 복구할 수 있다.
- **부정**: command별 ledger와 outbox 운영·purge가 필요하다.
- **전환/rollback**: domain별로 독립 도입한다. relay는 backfill/reconciliation 뒤 enable하고 실패 시
  소비를 중단해 outbox를 보존한다. revision을 이해하지 못하는 consumer는 해당 resource cutover
  전에 선배포한다.

## 기존 결정과의 관계

ADR-065의 POI target ETag·generation 의미를 확장하고, canonical pipeline/schedule의 기존
append-only audit와 exact-scope 제약을 회귀 기준선으로 유지한다.
