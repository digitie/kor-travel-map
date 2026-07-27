# ADR-078: 가격 current와 history를 full series identity로 조회

- **상태**: accepted
- **날짜**: 2026-07-27
- **결정자**: 사용자 + Codex
- **출처**: T-VN-44 React key 감사 · Claude Code PR #841~#853 적대적 후속 감사

## 컨텍스트

`feature.feature_price_values`의 자연키는 이미 `(feature_id, provider,
price_domain, product_key, observed_at)`다. 그러나 price card와 지도/admin summary는
`product_key`만으로 `DISTINCT ON`해 같은 제품을 제공하는 서로 다른 provider/domain
series 중 하나를 버렸다. 반면 frontend history chart는 provider/domain/product를
series로 분리해야 React key와 선이 충돌하지 않는다. 저장 identity와 조회 cardinality가
달라 API·지도·chart가 서로 다른 사실을 표시하는 상태였다.

기존 `(feature_id, price_domain, product_key, observed_at DESC)` index도 provider를
누락해 full identity current와 맞지 않는다. current용 중복 index를 하나 더 만들면
고빈도 관측 insert마다 B-tree를 추가 갱신해 write amplification이 커진다.

n150의 PinVi와 concierge source를 감사한 결과 price endpoint/`price_summary` runtime 소비는 0건이고,
PinVi에는 user OpenAPI 계약 snapshot만 있다. 따라서 소비자 선행 cutover 대상은 없으며 이 PR에서
user/admin OpenAPI와 admin UI를 함께 생성·검증하는 clean cut이 가능하다.

## 결정

1. 가격 series 식별자를 `(feature_id, provider, price_domain, product_key)`로 고정한다.
   observation identity는 여기에 `observed_at`을 더한 기존 자연키를 유지한다.
2. public/admin price card의 `current`와 지도/admin `price_summary`는 각 series에서
   `observed_at` 최신 1건을 반환한다. 동일 `product_key`라도 provider/domain이 다르면
   별도 current 값이다. `history`는 모든 series를 합쳐 최신 관측순으로 제한한다.
3. 지도 marker는 동일 product가 둘 이상일 때만 provider/domain을 함께 표시한다.
   history chart는 full series별로 선·점·legend 색을 구분한다.
4. current 쿼리는 기존 unique B-tree `uq_price_value_identity`를 all-DESC 순서로
   역방향 스캔한다. 별도 current index를 만들지 않는다.
5. history는 `(feature_id, observed_at DESC, provider, price_domain, product_key)`
   index 하나를 사용한다. product-only index는 migration 0064에서 제거한다.
6. 운영 DDL은 ADR-075에 따라 `DROP/CREATE INDEX CONCURRENTLY`와 Alembic
   `autocommit_block()`을 사용한다. 실패 후 남은 동일 이름 INVALID index를 먼저
   제거해 upgrade/downgrade 재실행을 self-heal한다.

## 근거

저장 자연키와 read model의 series cardinality를 같게 두면 provider가 추가돼도 값이
조용히 유실되지 않는다. unique index의 정렬축을 모두 뒤집은 backward scan은 current
`DISTINCT ON`의 요구 순서를 만족하므로 중복 index 없이 조회할 수 있다. history는
`observed_at`이 두 번째인 별도 access path가 필요하므로 index 하나만 유지하는 것이
read 성능과 write 비용의 균형이 가장 단순하다.

## 결과

- **긍정**: 동일 제품의 다중 공급원을 public/admin/map/chart 전 표면에서 보존한다.
  새 provider/domain을 추가해도 query cardinality를 다시 바꿀 필요가 없다.
- **긍정**: current용 중복 B-tree를 피하고 history hot path만 전용 index로 지원한다.
  EXPLAIN gate가 두 index access path를 고정한다.
- **부정**: `current`와 `price_summary` 배열이 제품당 1건이 아니라 series당 1건으로
  늘어날 수 있다. 사용자 지시의 서비스 전·호환성 비제약과 위 소비자 감사에 따라 호환 shim 없이
  user/admin OpenAPI와 UI를 함께 바꾼다.
- **부정**: 같은 제품의 여러 series를 표시할 때 marker label과 chart legend가
  길어진다. marker는 중복 제품일 때만 identity를 노출해 단일 series 가독성을 유지한다.

## 후속

- migration 0064 fresh upgrade/downgrade와 single-head를 통합 테스트한다.
- price card current/history와 public/admin bbox 두 경로의 다중 series 결과를 검증한다.
- OpenAPI를 재생성하고 admin frontend type drift gate를 통과시킨다.
- R1 격리 실데이터 DB/API/UI에서 migration과 다중 series 표시를 Live E2E로 검증한다.
