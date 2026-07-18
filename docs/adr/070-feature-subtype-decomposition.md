# ADR-070: Feature core와 typed subtype 분해

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-6

## 컨텍스트

Feature base row와 detail JSONB/부분 detail table은 kind별 필수 필드와 geometry 규칙을 DB에서
완전히 보장하지 못한다. 새로운 subtype을 추가할 때 공통 row와 임의 payload가 함께 커진다.

## 결정

1. `feature.features`에는 UUID, 공통 표시 필드, 직교 상태, category FK, revision만 둔다.
2. point/place, event, notice, route, area 등 subtype은 1:1 typed table로 분리한다. 각 subtype은
   필요한 필드와 `geometry(Point|MultiLineString|MultiPolygon, 4326)`처럼 허용 geometry
   type/SRID를 DB 제약으로 가진다(D-6-2 — route는 `LineString`이 아니라 `MultiLineString`).
   geometry CHECK는 세 가지다: `ST_IsValid`, `NOT ST_IsEmpty`, core 좌표와 geometry의
   anchor 일치.
3. core kind와 subtype row의 일치, category 존재, 좌표/geometry 불변식은 deferred validation이
   가능한 DB 제약과 통합 테스트로 검증한다.
4. provider membership, source lineage, publication state, override는 subtype payload와 분리한다.
   원천 원문은 immutable source record에만 둔다.

## 근거

typed subtype은 종류별 무결성을 명시하면서 공통 core를 작게 유지한다. PostGIS type/SRID 제약과
공간 인덱스도 실제 쿼리 단위로 설계할 수 있다.

## 결과

- **긍정**: 잘못된 kind/geometry 조합과 필수 필드 누락을 DB에서 거부한다.
- **부정**: subtype별 join과 migration이 추가된다.
- **전환/rollback**: subtype마다 독립 shadow table을 backfill하고 projection을 하나씩 전환한다.
  실패한 subtype만 이전 detail projection으로 돌릴 수 있으며 다른 subtype 전환은 유지한다.

## 기존 결정과의 관계

ADR-018의 무제한 free-form detail 금지를 확장한다. ADR-071의 override 방식과 독립적으로 배포·
rollback할 수 있다.
