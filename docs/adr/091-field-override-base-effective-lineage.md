# ADR-091: Field override의 base/effective lineage 완결

- **상태**: accepted
- **날짜**: 2026-08-10
- **결정자**: 사용자 + Codex
- **관련**: ADR-071, ADR-074, ADR-075, ADR-090, T-VN-36

## 컨텍스트

T-VN-34C 뒤의 `feature.features`와 subtype은 현재 effective 값이지만,
`data_origin='user_request'`와 `data_version > 0`의 whole-row fence가 provider의 모든
필드 갱신을 막는다. `ops.feature_overrides`는 lifecycle 전이의 재활성화 방지에는 쓰이나,
provider base 값·field별 provenance·일관된 effective materialization의 정본은 아니다.

`feature_versions`의 provider version `0`과 user receipt는 이 전환 전 bridge다. 이들을
계속 확장하면 한 row snapshot이 field별 의도와 source freshness를 다시 섞는다.

## 결정

1. 하나의 Feature 값은 **provider base → active field override → typed effective storage**의
   세 층으로만 표현한다. base ledger와 active override는 정본이고, `feature.features`와
   subtype의 값은 같은 transaction에서 materialize한 effective projection이다. 이것은
   compatibility dual-write가 아니라 한 정본의 base/effective 관계다.
2. `ops.feature_override_field_paths`는 모든 허용 field path의 typed registry다. registry는
   path, target scope/core·subtype, value kind, null 허용, source 요구와 admin/provider 쓰기
   허용을 고정한다. identity, kind, UUID/alias, row revision, 시간, source link와
   publication·quality 축은 registry 밖이다. lifecycle은 ADR-090의 typed state procedure와
   `lifecycle_state` override만 계속 사용한다.
3. provider base는 feature·field마다 현재 canonical source observation, source record hash,
   dataset/entity/record identity와 typed scalar 또는 geometry 값을 보존한다. geometry는 JSON으로
   다운캐스트하지 않고 typed PostGIS 값으로 저장한다. active override는 override value, author,
   reason, command/request receipt, base revision과 revoke tombstone을 보존한다. active uniqueness는
   `(feature, field_path)` 하나이며, revoke/replace는 security-definer command만 수행한다.
4. runtime은 base/override/effective column의 직접 DML 권한을 받지 않는다. provider patch,
   admin/user author·revoke, user-created Feature와 replay는 source evidence → Feature → subtype의
   고정 잠금 순서와 strong revision을 쓰는 typed security-definer procedure만 통과한다. procedure는
   allow-listed path를 typed assignment로 materialize하며 registry 문자열을 SQL로 실행하지 않는다.
5. whole-row freeze는 먼저 immutable request/history와 canonical source observation으로
   field override로 materialize하고, base/effective checksum이 일치한 경우에만 제거한다. mapping할
   수 없는 request, source 또는 typed field는 자동 추정하지 않고 migration preflight에서
   fail-closed한다. `data_origin`, `data_version`, `feature_versions`, whole-row request receipt와
   그 의존 trigger/index는 T-VN-36D의 한 forward-only final migration에서만 물리 삭제한다.
6. post-36/pre-T39 actual schema는 현행 text `feature_id`와 UUID shadow를 함께 보존한다. final
   target의 UUID `feature_id`는 T-VN-39 소유이므로, T-VN-36 contract와 post-T39 target contract를
   서로 대체 근거로 사용하지 않는다.

## 근거

provider source의 최신성, 운영자 보정, typed read 성능을 한 table snapshot으로 해결하려 하면
whole-row fence와 다중 `CASE`가 다시 생긴다. field별 base ledger는 source evidence를 보존하고,
materialized typed storage는 공개·공간·admin read의 기존 인덱스 경로를 유지한다.

## 결과

- **긍정**: 보정하지 않은 provider field는 계속 최신화되고, revoke는 최신 base를 즉시
  effective 값으로 복원한다. source/base/override/command의 책임도 분리된다.
- **부정**: registry·typed materializer·backfill checksum·runtime ACL을 한 cutover에서 함께
  검증해야 한다.
- **전환**: A–D는 하나의 PR과 하나의 release head로만 병합한다. intermediate Alembic revision은
  개발·fresh integration용 논리 phase일 뿐, intermediate binary를 실행하거나 rollback shadow를
  유지하지 않는다.

## 기존 결정과의 관계

ADR-071의 field-level 단일화 결정을 실행 가능한 base/effective lineage와 command 경계로
구체화한다. ADR-090의 state-axis audit·typed lifecycle override와 ADR-074의 command receipt는
유지하며, ADR-075의 legacy 제거 검증을 T-VN-36D에 적용한다.
