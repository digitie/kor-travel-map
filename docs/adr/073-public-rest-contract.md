# ADR-073: Typed public/service/operator REST 계약

- **상태**: accepted
- **날짜**: 2026-07-18
- **결정자**: 사용자 + Codex
- **출처**: `docs/reports/system-structure-api-schema-review-2026-07-16.md` D-9

## 컨텍스트

공개·service·operator 기능이 경로와 DTO에서 섞이고 공개 detail에 raw lineage가 노출된다.
`include_geometry`가 serialization이 아니라 결과집합을 바꾸며, total과 cursor도 실제 query
shape를 완전하게 표현하지 않는다.

## 결정

1. public-keyed 표면은 typed kind-discriminated feature detail/search/nearby/in-bounds,
   categories, collections만 제공한다. raw payload·hash·source record identity는 반환하지 않는다.
2. service 표면은 5-state feature batch, bitemporal weather batch, generation-aware cache target,
   idempotent refresh-request resource를 제공한다. service batch의 기본 projection은
   `trip_card`로 고정한다 — 서버 정의 enum이며 raw projection은 선택할 수 없다(D-9-1).
3. operator 표면은 source/observation lineage, change request, canonical datasets/pipeline,
   provider dataset 관리를 제공하며 ADR-066 principal을 사용한다.
4. `include_geometry`는 동일 candidate set의 serialization만 제어한다. in-bounds는
   `mode`, `truncated`, `coverage`, `cluster_key`를 명시하고 exact spatial predicate를 사용한다.
5. `include_total=false`는 COUNT를 실행하지 않는다. cursor에는 version과 정규화 query
   fingerprint를 넣고 API process 전용 server-only key로 HMAC-SHA256 서명한다. production은
   충분한 길이의 전용 key가 없거나 다른 인증 secret과 재사용되면 fail-closed한다. malformed,
   unknown version, 변조, 다른 query 재사용은 각각 typed RFC7807 422로 DB 접근 전에 거부한다.
   최초 도입은 단일 key clean cut이며 rotation 주기·진행 cursor 무효화율·다중 key grace window는
   운영 측정 뒤 별도 결정한다.
6. ETag는 `row_revision`/catalog revision에서 만들고 `If-None-Match` 304를 지원한다. 미구현
   옵션과 no-op beach 옵션은 OpenAPI에서 제거한다.
7. OpenAPI는 public/service/operator profile을 route policy에서 생성한다. 수기 allowlist는
   두지 않는다. RFC7807과 `Retry-After` 계약은 유지한다.

## 근거

표면별 권한과 payload를 타입으로 분리하면 공개 데이터 최소화와 소비자 계약 검증을 동시에
달성한다. 옵션은 이름 그대로 결과 의미를 보존해야 한다.

## 결과

- **긍정**: 공개 payload, 지도 completeness, pagination/cache 의미가 직관적으로 고정된다.
- **부정**: PinVi DTO와 OpenAPI profile을 계획된 cutover에서 함께 바꿔야 한다.
- **전환/rollback**: OpenAPI SHA와 consumer contract test를 먼저 배포한다. KTM 전환 실패 시
  PinVi를 이전 pinned spec으로 유지하고 write fence를 해제하지 않는다. 호환 alias는 만들지 않는다.

## 기존 결정과의 관계

ADR-048의 `/v1`, RFC7807, envelope, keyset 원칙을 유지하면서 목표 표면과 typed payload로
개정한다. ADR-066·067·072·074가 인증·상태·weather·쓰기 의미의 정본이다.
