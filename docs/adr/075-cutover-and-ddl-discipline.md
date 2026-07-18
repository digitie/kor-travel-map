# ADR-075: 보존 우선 cutover와 DDL 규율

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-11·D-12

## 컨텍스트

vNext는 identity, lineage, 상태, weather schema와 PinVi 계약을 함께 바꾼다. snapshot 이후 쓰기를
허용한 채 old snapshot으로 rollback하면 사이 write가 유실되고, upstream 재수집은 닫힌 feed·quota·
3년 weather 보존 때문에 복구책이 될 수 없다. DDL도 유형별 lock·validation 비용이 다르다.

## 결정

1. 구현 전 target DDL, ADR, OpenAPI, typed contract test를 freeze한다. 데이터는 정본·감사·파생으로
   보존 등급을 분류하고 restore/PITR 또는 forward journal replay를 실제로 검증한다.
2. 대형 변경은 shadow schema/backfill/양쪽 checksum과 의미 검증으로 준비한다. consumer를 먼저
   배포한 뒤 KTM과 PinVi를 순차 전환하며 그동안 write fence 또는 검증된 delta capture를 유지한다.
3. rollback window에는 write fence를 유지하거나 forward journal을 새 schema와 old schema 양쪽에
   replay할 수 있어야 한다. 어느 쪽도 없으면 rollback 가능하다고 선언하지 않는다.
4. soak와 reconciliation이 끝나기 전 legacy column/table/alias를 제거하지 않는다. 정본 데이터는
   DB-to-DB로 이관하고 검증된 파생 데이터만 재계산한다.
5. FK/CHECK는 가능한 경우 `NOT VALID`로 추가하고 별도 `VALIDATE CONSTRAINT`한다. UNIQUE는
   `CREATE UNIQUE INDEX CONCURRENTLY` 후 writer conflict target과 같은 cutover에서 연결한다.
6. 소형 ops 수술형 DDL은 lock acquisition timeout, 예상 보유 시간, drain 조건을 분리해 clone에서
   실측한다. 대형 rewrite는 shadow/backfill/swap을 사용한다. 실패한 concurrent index는 탐지·제거한다.
7. 모든 migration PR은 빈 PostGIS DB `alembic upgrade head && alembic check`, 단일 head, rollback/
   forward-recovery 절차를 통과한다. 공간/시간 index는 실제 query와 write 비용 실측으로 채택한다.

## 근거

호환성 유지가 아니라 데이터 보존과 검증 가능한 복구가 cutover 안전성의 기준이다. DDL을 lock
특성별로 나누면 과도한 무중단 추상화와 예측하지 못한 장기 중단을 모두 피할 수 있다.

## 결과

- **긍정**: schema/API 전환과 rollback이 데이터 유실 없이 검증 가능한 절차가 된다.
- **부정**: shadow 저장 공간, consumer 선배포, write fence와 운영 측정이 필요하다.
- **전환/rollback**: 각 migration step에 독립 rollback 또는 forward-only 복구를 명시한다.
  snapshot restore는 fence 이후 write가 없을 때만 허용하며, 그 외에는 forward journal/PITR로
  복구한다. legacy 제거 PR은 별도 최종 단계다.

## 기존 결정과의 관계

ADR-040/045의 backup·restore 경계를 강화한다. ADR-046의 무호환 원칙은 유지하되 live PinVi는
consumer-first cutover라는 유일한 운영 예외를 따른다.
