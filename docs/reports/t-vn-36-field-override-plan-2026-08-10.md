# T-VN-36 — field override 단일화 A–D 통합 설계

- **상태**: draft
- **날짜**: 2026-08-10
- **base**: T-VN-34C 완료 head `b03d5a4f`
- **범위**: T-VN-36A–D를 하나의 forward-only PR/release로 수행한다.

## 1. 완료 기준과 비목표

목표는 provider base, field override, typed effective projection의 정본을 하나로 만들고
`data_origin`/`data_version` whole-row fence 및 `feature_versions` bridge를 제거하는 것이다.
public 응답 shape와 ADR-090의 lifecycle/publication/quality state audit은 이 작업의 정본이
아니다. state axis 가운데 lifecycle의 provider reactivation fence는 기존 typed command를
유지하고, 일반 field override로 우회하지 않는다.

기존 값·새 값을 함께 쓰는 compatibility dual-write, legacy view/shadow column, old binary
rollback은 만들지 않는다. base ledger와 typed effective storage는 같은 procedure가 만드는
한 정본의 두 층이므로 이 금지와 충돌하지 않는다.

## 2. 정본 모델

| 층 | relation/소유 | 값 | 쓰기 규칙 |
|---|---|---|---|
| registry | `ops.feature_override_field_paths` | canonical path, physical scope, value kind, null/source/admin/provider policy | migration만 seed·변경 |
| provider base | `feature.feature_base_field_values` | field별 typed value, dataset/entity/record/hash, base revision·관측시각 | source evidence를 검증한 provider procedure만 |
| operator intent | `ops.feature_overrides` | active override value, author/reason, command or request receipt, source/base revision, revoke tombstone | author/revoke procedure만 |
| effective | `feature.features` + five typed subtype | base 또는 active override가 선택된 typed value | materializer procedure만 |

`feature_base_field_values`와 `feature_overrides`는 scalar/JSONB 값과 PostGIS geometry 값을
별도 typed column으로 가진다. JSONB의 `null`은 provider가 명시한 null 값이고, base 행의
부재는 그 field가 source에서 아직 관측되지 않았음을 뜻한다. registry의 composite key와
CHECK/trigger가 value kind·target subtype·null 규칙을 검증한다. geometry는 SRID와 subtype
geometry type까지 검사한다.

registry의 field path는 `core.name`, `place.address`, `route.geom`처럼 scope를 포함한다.
identity, kind, `feature_uuid`, alias, `row_revision`, 생성/갱신 시각, source link, public-ready
cache, lifecycle/publication/quality는 등록하지 않는다. registry가 허용하는 물리 column 목록은
36A freeze artifact가 모델/DDL에서 생성해 diff로 검증한다. runtime JSON의 임의 path나 dynamic
SQL은 허용하지 않는다.

## 3. A–D 단일 PR의 논리 phase

### 36A — registry·base ledger·whole-row freeze materialization

1. executable registry/DDL contract, target DDL, post-36/pre-T39 invariant parser와 fixture를
   freeze한다. actual schema는 text `feature_id`와 UUID shadow를 함께 두고, final target의 UUID
   FK와 혼동하지 않는다.
2. `feature_base_field_values`와 immutable/revocable override provenance를 만든다. active unique,
   registry composite FK, type validator, direct DML/DDL/trigger-disable ACL fence를 DB에서 만든다.
3. fresh provider rebuild로 canonical base를 적재하고 immutable request/history를 path whitelist로
   replay해 whole-row user change를 override로 materialize한다. update는 request payload가 지정한
   field만 override한다. user-created Feature는 provider base 없이 required effective fields의
   explicit override로 만든다.
4. payload/path/source를 재구성할 수 없는 행은 count와 identity를 preflight manifest로 내고
   fail-closed한다. current effective row와 materialized effective row는 kind별·field별
   `EXCEPT ALL`과 source/override digest로 대조한다.

### 36B — provider/admin/user writer를 typed command로 전환

1. `apply_provider_feature_field_patch`는 current dataset/entity/head/record와 Feature를
   source evidence → Feature → subtype 순으로 잠그고, coverage에 포함한 base field만 upsert한다.
   active override가 없는 field만 effective typed storage로 갱신하고 Feature revision은 bundle당
   한 번만 증가시킨다.
2. `author_feature_field_overrides`와 `revoke_feature_field_overrides`는 expected revision,
   authenticated principal, reason code, ADR-074 domain command receipt를 요구한다. replace는
   기존 active row를 procedure 안에서 tombstone으로 만들고 새 row를 author한다.
3. provider/user/admin/merge/address/quality writer는 raw table DML과 `data_origin` CASE를
   제거하고 위 procedures만 호출한다. lifecycle retire/reactivate는 ADR-090 procedure를 그대로
   사용하고, non-lifecycle commands가 state audit을 우회하지 못하게 한다.
4. provider patch와 override author/revoke, source-head advance와 provider patch, field별 동시
   command, stale revision/retry의 two-session regression을 추가한다.

### 36C — effective read·API/UI·consumer cutover

1. repository의 `data_origin`/`data_version` 조건과 field별 `CASE`를 effective typed core/subtype
   projection으로 바꾼다. public은 기존 `public_features`, admin은 effective values와 override
   provenance/timeline을 명시적으로 읽는다. base 값은 public DTO에 노출하지 않는다.
2. admin override author/revoke API는 If-Match·Idempotency-Key·reason code와 field registry의
   typed value schema를 가진다. generated OpenAPI, frontend axes/override UX, fixtures와 E2E를
   함께 갱신한다.
3. PinVi admin-detail consumer는 exact Map head에서 재-vendor한다. user/service schema가 실제로
   변하지 않으면 snapshot 변경 없음도 bytes와 compile/no-legacy gate로 증명한다.

### 36D — destructive fence·legacy 제거·final live

1. final migration은 post-36/pre-T39 contract를 실행한 뒤 `data_origin`, `data_version`,
   `feature_versions`, whole-row request receipt/trigger, provider baseline version `0`, dependent
   index·ACL·runtime preflight requirement을 물리 삭제한다. `ops.feature_change_requests`는
   whole-row add/update/delete workflow라면 domain command receipt와 override history로 이관한 뒤
   함께 삭제한다. target/actual의 relation 존재 여부는 contract가 각각 명시한다.
2. static normal-path 및 catalog gate는 legacy column, `data_origin='user_request'`,
   `feature_versions`, whole-row `CASE`, runtime grant와 old procedure symbol이 0임을 확인한다.
3. n150 fresh PostGIS→provider ETL→field override author/provider refresh/revoke→admin/public/PinVi
   browser main/recovery를 실행하고 cleanup과 destructive catalog zero를 기록한다.

## 4. command·동시성·ACL contract

모든 command는 domain command claim → request/override receipt → source evidence → Feature → subtype의
전역 순서를 지킨다. provider에게 request receipt는 없으므로 source evidence → Feature → subtype이다.
source head/link과 override를 plain read로 검사하지 않으며 필요한 row를 같은 transaction에서 잠근다.

runtime API/Dagster login은 source relation의 정상 ETL DML과 named procedure `EXECUTE`만 갖는다.
base ledger, overrides, effective protected column, command result 및 audit relation의 raw INSERT/UPDATE/
DELETE/TRUNCATE는 거부한다. state/audit/override/materializer owner는 서로 다른 NOLOGIN role과 fixed
`search_path`를 사용하고, startup preflight와 actual LOGIN integration이 table/column/function privilege를
catalog로 증명한다.

## 5. 검증 matrix

| 영역 | 필수 증거 |
|---|---|
| DDL/contract | registry field/type/subtype exhaustive diff, invalid scalar/geometry/path rejection, active unique, tombstone immutability, post-36/pre-T39 parser/SHA |
| migration | provider/user-created/user-updated/legacy lifecycle rows, unmappable fail-closed manifest, base/effective bidirectional `EXCEPT ALL`, source·override digest |
| writer | provider change가 unoverridden field만 갱신, active override 보존, revoke 후 latest base 복원, row revision 1회, stale/retry/409/412/428 |
| concurrency | provider source-head advance × provider patch, provider patch × author/revoke, same command retry, two field command, lock-order/deadlock regression |
| read/API | public unchanged, admin effective/provenance typed schema, OpenAPI export/check, frontend typecheck/E2E, PinVi exact pair compile/no-legacy |
| final fence | raw runtime DML 42501, legacy catalog/static zero, fresh `upgrade head`, 0097→36D upgrade, n150 destructive main/recovery and cleanup |

## 6. PR·병합 규율

`feat/tvn36-abcd-field-overrides`는 `feat/tvn34-state-model`의 `b03d5a4f`만을 base로 둔다.
A–D는 하나의 Draft PR에서 review하며, phase checkpoint는 원격에 push할 수 있으나 intermediate
Alembic head를 서비스에 배포하지 않는다. 두 독립 적대 리뷰가 DDL/ACL·writer/consumer를 검토하고,
n150 evidence와 CI가 모두 green일 때만 forward-only로 병합한다.
