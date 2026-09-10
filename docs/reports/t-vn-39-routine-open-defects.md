# 재키 루틴 2차본 — 남은 blocking 결함 (2026-09-09)

적대 검증 2회를 거친 뒤 남은 것. 마이그레이션 작성 시 반드시 반영한다.
SQL 2차본은 `alembic/versions/_309_*.sql` 23개다.


## 309 초안의 위치와 미완성 이유

DDL 상수는 전부 유도됐고(재타입 34 · shadow 13 · FK drop 40 · 재생성 34 · 개명 4)
뷰 재키판과 트리거 순서도 확정됐다. 그러나 **초안을 `alembic/versions/`에 두면 안 된다**
— alembic이 그 디렉터리의 모든 `.py`를 실제 revision으로 읽으므로, `upgrade()`가
미완성으로 raise하면 **DB를 쓰는 테스트가 전부 죽는다.**

초안 위치(저장소 밖):
`<scratchpad>/309_t39_feature_id_rekey.draft.py` (453줄)

`tests/lint/test_receipt_head_check_covers_the_graph_head.py`가 이 미완성을 정확히
잡았다 — receipt head CHECK가 309를 허용하는데 `_UPGRADE_STATEMENTS`가 그것을 실행하지
않는다는 신호였다. 게이트가 의도대로 작동했다.

착지 조건: 아래 blocking 12건 반영 + `_UPGRADE_STATEMENTS` 조립 + `db.py`/
`runtime_privileges.py`/`feature_subtype.py` 동반 수정.


## ★ 범위 누락 — 재작성 대상은 23개가 아니라 35개다 (2026-09-09 실측)

`db.py`의 시그니처 리터럴을 사이드카에서 유도해 대조하다 찾았다. text `feature_id`
인자를 든 루틴 **12개가 재작성 세트에 없었다**:

| 루틴 | 줄 | 비고 |
|---|---|---|
| `feature.author_feature_field_overrides` | 497 | |
| `feature.revoke_feature_field_overrides` | 452 | |
| `feature.patch_curation_item_command` | 203 | |
| `feature.transition_feature_state` | 86 | **계약이 `(uuid,text,text,text,bigint,jsonb)`로 못 박았다** |
| `feature.reactivate_admin_feature_state` | 85 | |
| `feature.author_lifecycle_override` | 71 | |
| `feature.transition_admin_feature_state` | 69 | |
| `feature.revoke_lifecycle_override` | 34 | |
| `feature.append_theme_feature_candidate_transition` | 29 | `p_from_feature_id`/`p_to_feature_id` |
| `feature.lock_current_provider_feature_source_evidence` | 25 | |
| `feature.feature_uuid_from_legacy` | 23 | head 참조 0건 — **DROP 대상** |
| `feature.has_active_feature_override` | 8 | |

**왜 놓쳤나**: 1차 조사가 "본문에 `feature_uuid` 22개 · text 시그니처 20개"로 셌는데,
재작성 그룹을 짤 때 **두 집합의 합집합이 아니라 앞쪽 위주로** 20개를 골랐다. 위 12개는
본문에 `feature_uuid`가 **0건**이라(순수 시그니처·지역변수 타입 문제) 그 눈금에서 빠졌다.

**어떻게 잡았나**: `db.py`의 시그니처 리터럴 61개를 사이드카가 정의하는 21개와
대조하니 12개가 남았다. 유도로 대조하지 않았으면 재키 후 첫 호출에서 42883으로
드러났을 것이다.

## 실행자 노트 — 아래 결함 일부는 **다른 DDL 접근**을 전제한다

에이전트들은 shadow 짝이 있는 표를 `DROP COLUMN feature_id` + `RENAME feature_uuid TO
feature_id`로 옮긴다고 가정했다. **확정된 접근은 그것이 아니다**:

```sql
ALTER TABLE <t> ALTER COLUMN feature_id TYPE uuid USING feature_uuid;   -- 값 승계
ALTER TABLE <t> DROP COLUMN feature_uuid;                                -- shadow 제거
```

차이가 크다 — `ALTER COLUMN TYPE`은 **그 컬럼의 인덱스·CHECK·PK를 자동 재구축**하지만
`DROP COLUMN`은 **자동 삭제**한다. 그래서 "PK와 composite FK가 collateral로 사라진다"는
결함(#2 계열)은 DROP+RENAME 경로에서만 성립하고, 확정 접근에서는 부모측
`uq_features_id_kind` 개명만 챙기면 된다.

**단, 부모(`feature.features`)를 참조하는 FK 40개는 어느 접근이든 사전 DROP이 필요하다**
— 크로스 표 타입 불일치 때문이다. 그것은 이미 DDL 순서 D단계에 있다.

반대로 `DROP COLUMN feature_uuid`(shadow 제거)는 확정 접근에서도 그대로 일어나므로,
**shadow 컬럼에 걸린** 인덱스·CHECK는 여전히 사전 열거 대상이다(실측 2건:
`ck_feature_reference_reconciliation_events_replacement`,
`idx_manual_provider_dedup_cases_decision_fence`).

## ★ 3차가 잡은 진짜 파손 지점

1·2차가 `feature_subtype.py:238`(무해한 주석)을 지목하고 **325행을 놓쳤다**:

```python
all_columns = ("feature_id", "feature_uuid", "kind", *columns)
# → f-string으로 INSERT INTO feature.{table} ({", ".join(all_columns)})
```

이것이 오늘 subtype의 `feature_uuid`를 채우는 **유일한 애플리케이션 경로**이고 재키 후
42703이다. 동적 조립이라 파서가 못 본다 — 검증 체크 #5가 정확히 이 부류를 노렸는데
두 라운드가 지나쳤다.


## triggers

### 1. `feature.fence_features_identity_update`

재생성한 트리거의 **실행 위치**가 지정되지 않아, 이 수정이 스스로를 무효화한다. 2차본 SQL은 `DROP TRIGGER IF EXISTS ... ; CREATE TRIGGER trg_features_identity_fence BEFORE UPDATE OF feature_id ...`를 함수 정의 바로 뒤 한 덩어리로 내고 주석은 '같은 트랜잭션에서'라고만 적었다. 그런데 이 CREATE가 재키 DDL **앞**에서 돌면 새 트리거는 아직 text인 `feature_id` 컬럼에 DEPENDENCY_AUTO를 걸고, 그 직후 재키가 그 컬럼을 DROP하면서 오류도 경고도 없이 다시 함께 삭제된다 — A1이 고치려던 바로 그 침묵 소멸이 재현된다. 비교점: 같은 그룹의 fill 루틴은 '이 DROP은 재키 DDL 앞에 놓아야 한다'를 명시했는데 fence만 위치 pin이 없다.

**수정**: CREATE TRIGGER를 재키 DDL(features의 text feature_id DROP + feature_uuid RENAME) **뒤**로 명시 이동. 순서를 ①DROP TRIGGER → ②컬럼 재키 → ③CREATE TRIGGER(UPDATE OF feature_id)로 caller_impact와 SQL 주석 양쪽에 박을 것. 트리거 목록 전수 확인 결과(head 21781/21795/21832/21839 등 `UPDATE OF` 13건 중 identity 컬럼을 쥔 것은 21795 하나)는 정확하므로 그 근거는 유지.

### 2. `feature.derive_subtype_public_ready`

caller_impact가 '이 두 자식 표는 조용한 불일치 위험이 없다 — fk_feature_{areas,routes}_feature_kind가 (feature_id, kind)로 부모를 참조하므로 값이 어긋나면 23503으로 즉시 잡힌다'고 단언하는데, **그 FK는 재키 순간 자동 소멸한다.** 2차본이 채택한 값 보존 경로는 `feature_id character varying` DROP인데, PostgreSQL의 DROP COLUMN은 그 컬럼이 관여한 인덱스·제약을 자동 삭제한다. 실측 대상: `pk_feature_areas PRIMARY KEY (feature_id)`(head 18788), `pk_feature_routes`(head 18836), `fk_feature_areas_feature_kind`(head 23236), `fk_feature_routes_feature_kind`(head 23356) 전부가 collateral이다. 2차본은 identity_pair FK(23244/23364)만 DROP 대상으로 적고 feature_kind FK·PK는 '살아남아 축을 흡수한다'는 전제로 서술했다. 재생성 지시가 없으면 재키 후 subtype 표에 PK도 부모 FK도 없는 상태가 남고, 주장한 23503 보호막은 정확히 그 순간 사라진다.

**수정**: caller_impact를 '필수 동반 DDL'로 승격: ①fk_*_identity_pair DROP(재생성 없음) ②컬럼 DROP+RENAME ③`pk_feature_areas`/`pk_feature_routes`를 새 uuid feature_id로 재생성 ④`fk_feature_areas_feature_kind`/`fk_feature_routes_feature_kind`를 재생성. ④는 부모측 `uq_features_identity_kind`(head 19008-19012)의 `uq_features_id_kind` 개명·재생성이 선행돼야 참조 대상이 존재한다(features 표 소유 그룹과 순서 조정 필요) — 이 선행 의존도 함께 기재할 것.

### 3. `feature.derive_subtype_public_ready`

caller_impact가 지목한 `src/kortravelmap/infra/feature_subtype.py:238`은 **재키 후에도 깨지지 않는다.** 238은 `_SUBTYPE_DRIFT_SQL`(241-269)의 설명 주석이고 그 SQL 전문을 읽은 결과 feature_uuid 참조가 0건이다(feature_id/kind만 본다). 반면 같은 파일의 진짜 파손 지점을 통째로 놓쳤다: **325행 `all_columns = ("feature_id", "feature_uuid", "kind", *columns)`** 가 f-string으로 `INSERT INTO feature.{table} ({", ".join(all_columns)})`를 조립하는 subtype writer다 — 이것이 오늘 feature_routes/feature_areas.feature_uuid를 채우는 유일한 애플리케이션 경로이고, 재키 후 42703이다. 부속 바인드도 함께 죽는다: 151(`feature_uuid: str` 파라미터) / 173(`"feature_uuid": feature_uuid` common dict) / 436 / 458. 검증 지시의 체크 #5('동적 SQL·format() 안의 컬럼 이름 — 파서가 안 본다')에 정확히 해당하는 유일한 사례를 이 그룹이 지나쳤고, 실행자가 238을 열어 보면 아무 문제도 없어 그대로 넘어가게 된다.

**수정**: caller_impact의 feature_subtype.py 항목을 238 → **151·173·325·436·458**로 교체하고 '동적 조립이라 파서·mypy 어느 쪽도 잡지 않는다'를 명시. 238(`_SUBTYPE_DRIFT_SQL`)은 반대로 '수정 불필요(shadow 미참조)'로 기재해 잘못된 점검 지시를 제거할 것.

### 4. `feature.ensure_features_legacy_alias`

`feature.feature_aliases` 표의 **재키 방향이 명시되지 않았다** — 이 그룹이 그 표의 동반 DDL(CHECK·index)을 직접 열거해 놓고 정작 컬럼 처분만 비워 뒀다. boundary_kept는 '그 컬럼(feature_uuid)은 재키 후 소멸한다'고만 적었는데, 문자 그대로 실행하면 [결함 1]과 같은 함정이다: 오늘 head 15606-15609는 `alias text` + `feature_id text` + `feature_uuid uuid`이고 target §4(contracts/vnext/target-schema-v1.sql:928-943)는 `alias text` + `feature_id uuid`다. feature_uuid를 DROP하고 text feature_id를 uuid로 retype하면 alias→uuid 매핑의 유일한 소재지를 지우는 것이고, legacy `f_*` 텍스트에서 v7을 역산할 방법은 없다(ADR-083). alias 표는 값 보존이 세 표보다 더 결정적이다 — alias 행 자체가 legacy id ↔ uuid 사전이기 때문이다.

**수정**: boundary_kept/caller_impact에 다른 세 표와 같은 문장을 명시: `feature.feature_aliases`는 **text `feature_id` DROP + `feature_uuid` → `feature_id` RENAME**(alias 컬럼은 text 그대로 유지). 작업 규칙의 요약 표현('feature_uuid 삭제')이 반대 방향을 유도하므로, 그 축약이 아니라 값 보존 경로임을 문장으로 못 박을 것.

### 5. `feature.ensure_features_legacy_alias`

caller_impact의 인덱스 판정이 **정반대다.** '`idx_feature_aliases_feature_uuid`(head 20413-20416)는 사라질 컬럼의 인덱스다. 컬럼 DROP과 함께 소멸하며 재생성 대상이 아니다(target §4는 idx_feature_aliases_feature만 둔다)'라고 적었는데, 값 보존 재키(B4의 DROP+RENAME)에서는 feature_uuid가 RENAME되므로 이 인덱스는 **살아남고**, 대신 text feature_id 위에 있던 `idx_feature_aliases_feature`(head 20409)가 컬럼과 함께 **사라진다.** 그대로 두면 target §4가 요구하는 `idx_feature_aliases_feature`는 존재하지 않고, 이름만 낡은 `idx_feature_aliases_feature_uuid`가 uuid 컬럼 위에 남는다 — 유도형 스키마 검사기에 drift로 잡힌다.

**수정**: '컬럼 RENAME 뒤 `ALTER INDEX feature.idx_feature_aliases_feature_uuid RENAME TO idx_feature_aliases_feature`(또는 DROP 후 재생성). text feature_id에 걸린 기존 idx_feature_aliases_feature는 컬럼 DROP과 함께 소멸하며 재생성 대상이 아니다'로 두 인덱스의 역할을 맞바꿔 기재.

### 6. `feature.write_feature_state_transition`

caller_impact의 '`idx_feature_state_transitions_feature_occurred`는 `ALTER`가 자동 재구축한다(설계보고서 §5-2)'가 **이제 거짓이다.** 이 문장은 폐기된 `ALTER COLUMN TYPE` 계획의 잔존물이다 — 2차본 자신이 [결함 1] 정정으로 경로를 'text feature_id DROP + feature_uuid RENAME'으로 바꿨고, DROP COLUMN은 인덱스를 재구축하는 게 아니라 **함께 삭제한다.** 실측: head 20472 `CREATE INDEX idx_feature_state_transitions_feature_occurred ON feature.feature_state_transitions USING btree (feature_id, occurred_at, transition_id)` — 이 feature_id는 text 쪽이다. 재생성 지시가 없으면 재키 후 감사 타임라인 인덱스가 통째로 없어지고, `_ADMIN_FEATURE_STATE_TRANSITIONS_SQL`(WHERE feature_id + ORDER BY transition_id DESC keyset)이 seq scan으로 떨어진다 — 결과는 맞고 인덱스만 죽는 1차본 함정과 같은 종류의 손실이다.

**수정**: 해당 문장을 '이 인덱스는 text feature_id에 걸려 있어 컬럼 DROP과 함께 소멸한다 — RENAME 뒤 uuid `feature_id`로 **명시 재생성**해야 한다'로 교체. 같은 기준을 방어 검사 문단과 나란히 필수 항목으로 승격할 것(FK가 없어 값 불일치도, 인덱스 소멸도 둘 다 침묵한다는 점이 이 표의 고유 위험이다).

### 7. `feature.ensure_features_legacy_alias`

alias 생산자를 없애면서 **착지 순서 게이트가 없다.** alias 행은 DB 내부 값이 아니라 API 경계가 소비하는 값이다 — 실측: `src/kortravelmap/infra/feature_identity.py:301`의 해석 규칙 2단계와 383행 `_RESOLVE_BY_ALIAS_SQL`이 `feature.feature_aliases`로 legacy `f_*` 참조를 해석하고, 그 결과가 packages/.../routers/admin_features.py:1666 `resolve_feature_ref_or_error` → `identity.feature_id` 경로로 흐른다. 2차본은 disposition에서 '(a)안 삭제 유지'를 확정 문장으로 쓰고, 대체 생산자(명시 INSERT)의 주인은 unknowns의 '소유 그룹 불명'으로만 남겼다. 이 상태로 DROP만 먼저 머지되면 신규 Feature에 legacy alias가 만들어지지 않아 legacy id 조회가 조용히 404가 된다 — 경계를 넘는 값이 지워지는, ★규칙이 막으려는 바로 그 결과다.

**수정**: 삭제 판단 자체는 옳다(재키 후 NEW에 legacy 텍스트가 없어 트리거가 alias를 만들 방법이 물리적으로 없다는 근거는 유효). 다만 disposition에 순서 게이트를 명시할 것: '이 DROP은 대체 INSERT 경로(create wrapper 또는 Python writer)가 착지한 **뒤**에만 적용한다.' 계약 756의 페이로드 화이트리스트(feature_id/kind/name/category_code)에 legacy alias를 실을 자리가 없다는 점까지 이미 unknowns에 정확히 적혀 있으므로, 그 항목을 unknowns에서 blocking 선행조건으로 승격만 하면 된다.

**경계 규칙 확인**: ■ 결론: 이 그룹에는 경계 규칙의 '유지' 가지가 적용될 자리가 **원문에 0개**다. 따라서 "1차본이 22개 전부에서 지웠다"는 체계적 결함은 이 6개 루틴에서는 재현되지 않는다 — 지운 것이 모두 '삭제' 처분 칸에 해당한다. 전수 근거는 아래.

■ 자리별 전수 (head-schema.sql 원문 직접 열람)
· jsonb payload의 'feature_uuid' 키 → **0건**. 6개 모두 RETURNS trigger이고, 유일한 jsonb 산출은 write_feature_state_transition의 `v_context -> 'provider_evidence'` 통과값(identity 키 없음)이다.
· RETURNS TABLE(... feature_uuid ...) → **0건**(6개 전부 RETURNS trigger).
· API 응답 필드 → **0건**. 실측: feature_state_transitions를 읽는 유일한 API 경로 `_ADMIN_FEATURE_STATE_TRANSITIONS_SQL`(src/kortravelmap/infra/admin_feature_repo.py:1845-1871)은 transition_id·상태 6축·kind·reason·principal·causation·provenance·occurred_at·row_revision만 select하고 feature_id/feature_uuid 둘 다 select하지 않는다. 응답 모델 `AdminFeatureStateTransitionAuditRecord`(packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_features.py:809-830, `extra="forbid"`)에도 두 필드가 없다. 2차본의 boundary_

## dedup

### 8. `feature.record_manual_provider_dedup_candidate / resolve_manual_provider_dedup_case / resolve_manual_provider_dedup_case_v2 / list_manual_provider_dedup_detector_manuals / list_manual_provider_dedup_cases / read_manual_provider_dedup_case (6개 전부)`

`SET ROLE` 누락. 6개 루틴 전부 소유자가 `ktm_manual_provider_dedup_procedure_owner`이고(head-schema.sql:5320, 5367, 8156, 8660, 9608, 9646 / 304:132), 마이그레이션 주변 role은 `ktm_feature_schema_owner`다(305:163, 171). 이 저장소의 명시 규약은 alembic/versions/302_m03_import_child_issuance.py:310-311 — "procedure 소유자는 …다 — **REPLACE/DROP/CREATE와 ACL은 소유자 role로 수행한다**(schema owner가 멤버십 보유)" — 이고, 305_m05_relitigation_fence.py:158-163이 같은 프로시저에 대해 `SET ROLE ktm_manual_provider_dedup_procedure_owner` → 사이드카 → `SET ROLE ktm_feature_schema_owner`를 실제로 두고 있다. 2차본은 OWNER·ACL은 정확히 복원했으면서 그 문장들을 합법으로 만드는 role 전환을 6블록 어디에도 두지 않았다. `DROP PROCEDURE/FUNCTION`과 `CREATE OR REPLACE FUNCTION`은 소유자만 할 수 있으므로 3개 DROP+CREATE와 2개 CREATE OR REPLACE 전부 42501(must be owner of ...)로 죽는다. 1차본의 OWNER/ACL 유실을 고치면서 그 옆의 같은 부류 결함이 남았다.

**수정**: 각 블록을 `SET ROLE ktm_manual_provider_dedup_procedure_owner;`로 열고 `SET ROLE ktm_feature_schema_owner;`로 닫는다. 단 DROP+CREATE 3개는 304의 실측 패턴을 따르는 것이 안전하다 — 304는 새 함수 CREATE와 ALTER OWNER/REVOKE/GRANT를 **schema owner로** 수행한다(_UPGRADE_STATEMENTS에 SET ROLE이 없다). 즉 `SET ROLE <proc owner>` → DROP → `SET ROLE ktm_feature_schema_owner` → CREATE → ALTER OWNER → REVOKE/GRANT 순. `ktm_manual_provider_dedup_procedure_owner`가 schema `feature`에 CREATE 권한을 갖는지 확인되지 않았으므로(302:319-329가 ops 스키마에서 정확히 그 문제를 만났다) CREATE를 소유자 role로 옮기지 말 것.

### 9. `feature.resolve_manual_provider_dedup_case_v2 / record_manual_provider_dedup_candidate / list_manual_provider_dedup_detector_manuals`

`tests/integration/`의 호출자가 caller_impact에서 **통째로 빠졌다.** 2차본은 db.py·runtime_privileges.py의 "파서가 안 보는 문자열 리터럴"을 스스로 발견해 놓고 같은 부류를 테스트 트리에는 적용하지 않았다. 실측 자리: (1) tests/integration/conftest.py:404-409 — `CALL feature.resolve_manual_provider_dedup_case_v2(..., NULL::text /*survivor*/, ..., NULL::text /*4번째 OUT*/, NULL::bigint)` → 재키 후 42883이고, 그 sqlstate가 :414에서 `gate_sqlstate`로 기록돼 tests/integration/test_tvn_m05_manual_provider_dedup.py:429 `assert ... == "P0002"`를 깬다(활성화 게이트 fixture 자체가 무의미해진다). (2) test_evidence_restore.py:92-99 — `CAST(:survivor_feature_id AS text)` + `NULL::text` → 42883. (3) test_tvn_m05_manual_provider_dedup.py:292-296 및 :605-608 — `CAST(:manual_feature_id AS text), CAST(:provider_feature_id AS text)` record CALL → 42883. (4) 같은 파일 :636-637 — `'feature.record_manual_provider_dedup_candidate(text,text,jsonb,jsonb)'::regprocedure` → 42883(파스 시점). (5) 같은 파일 :480-481 — v1 시그니처 리터럴 `(uuid,text,text,bigint,bigint,text,text,text,bigint)`. (6) 같은 파일 :781-782, :820-821 — `event.old_feature_uuid` / `event.replacement_feature_uuid` **테이블 컬럼**을 SELECT/assert → shadow 삭제 후 42703. (7) test_tvn_m05_provider_bundle_dedup_scenario.py:94-99 `_RECORD_CANDIDATE_SQL`의 `AS text` 2자리. (8) test_tvn_m05_detector_manual_listing.py:40 `_LISTING = "...(text,integer)"` + :65-66 `CAST(:after AS text)` + :160/:194/:200/:206 `'{_LISTING}'::regprocedure` 4자리 → 42883(소유자·ACL 단언이 실패가 아니라 에러가 된다).

**수정**: 위 8곳을 uuid로 옮긴다: survivor/OUT `NULL::text`→`NULL::uuid`, `CAST(... AS text)`→`AS uuid`, 시그니처 리터럴 `(text,text,jsonb,jsonb)`→`(uuid,uuid,jsonb,jsonb)`·`(text,integer)`→`(uuid,integer)`·v1/v2 6번째 인자 `text`→`uuid`, `event.old_feature_uuid`/`replacement_feature_uuid` 단언은 `old_feature_id`/`replacement_feature_id`로 재지정. 부수 확인 2건: (a) test_tvn_m05_provider_bundle_dedup_scenario.py:502/515/620/733의 `data[...]["feature_uuid"]` 단언들은 **경계 복원 덕분에 무수정으로 통과한다** — 경계 규칙이 옳았다는 실측 증거이므로 boundary_kept에 근거로 올릴 것. (b) 같은 파일 :734 `assert provider_feature_uuid != scenario.provider_feature_id`는 재키 후 두 값이 같아지면 거짓이 된다 — unknowns의 'feature_id와 feature_uuid가 같은 값이 된다'가 만드는 최초의 구체적 회귀이므로 unknowns가 아니라 caller_impact로 승격할 것.

**경계 규칙 확인**: 원문에서 `feature_uuid`가 등장하는 자리를 6개 루틴 범위(head-schema.sql 5256-5318 / 5326-5365 / 8057-8152 / 8380-8658 / 9371-9606 / 9614-9644)에서 기계적으로 전수 열거해 33자리를 얻었고, 한 자리씩 2차본과 대조했다. 누락·무단 삭제 0건.

[A] 경계를 넘는 jsonb `'feature_uuid'` 키 — 원문 총 8자리, 2차본에서 **8/8 전부 살아 있고 8/8 전부 `CAST(... AS text)`다.**
 1. list_manual_provider_dedup_cases :5283 `candidate.manual_feature_uuid` → `CAST(candidate.manual_feature_id AS text)` ✅
 2. 같은 함수 :5289 provider → `CAST(candidate.provider_feature_id AS text)` ✅
 3. read_manual_provider_dedup_case :8082 → `CAST(candidate.manual_feature_id AS text)` ✅
 4. 같은 함수 :8090 provider → ✅
 5. record_manual_provider_dedup_candidate :8525(v_manual_snapshot) → `CAST(v_manual.feature_id AS text)` ✅
 6. 같은 프로시저 :8535(v_provider_snapshot) → ✅
 7. resolve_manual_provider_dedup_case :9572(payload old_feature) → `CAST(v_manual.feature_id AS text)` ✅
 8. 같은 프로시저 :9577(payload replacement_featu

## create

### 10. `feature.create_feature_with_initial_state`

`parent_feature_id`를 `nullif(p_feature ->> 'parent_feature_id', '')::uuid`로 바꾼 줄이 조건부로만 옳고, 그 전제 조건의 절반이 caller_impact에 없다. 컬럼 재타입 쪽은 안전에 가깝다 — head-schema.sql:23372의 `fk_features_parent_feature_id_features FOREIGN KEY (parent_feature_id) REFERENCES feature.features(feature_id)`가 강제하고, docs/reports/t-vn-39-rekey-design-2026-09-09.md:59의 '재타입 34(shadow 유도 13 · **alias 조회 21**)'가 legacy `f_*`를 담은 컬럼군을 따로 세고 있어 이 컬럼이 그 21에 들어갈 개연성이 높다. 문제는 **payload 값** 쪽이다: 이 자리에 들어오는 값의 생산자는 `src/kortravelmap/dto/feature.py:143 parent_feature_id: str | None = None`(포맷 제약 없음 — 바로 아래 `sibling_group_id`가 'dedup sibling group UUID (string 표현)'이라 명시된 것과 대조된다)이고, 실제로 채우는 곳은 `src/kortravelmap/providers/opinet.py:553`·`:712`의 `parent_feature_id=station_feature.feature_id`와 `src/kortravelmap/providers/krex.py:892-903`이다. 즉 DTO의 `feature_id`가 anchor 교체와 함께 uuid로 넘어가지 않으면 이 줄은 opinet 가격 Feature와 krex 자식 Feature 매 건마다 **가드 없는 22P02**를 낸다. 산출물의 unknowns는 이 위험을 '컬럼이 21에 안 들어가면 42804'로만 적어 값 쪽 절반을 빠뜨렸고, 같은 뿌리인 `feature_repo.py:2220` blocker와 연결하지도 않았다.

**수정**: 둘 중 하나. (a) 원문 줄 `p_feature ->> 'parent_feature_id',`를 글자 그대로 되돌리고 이 컬럼의 처분을 DDL 그룹에 넘긴다(브리핑의 '바꿀 필요 없는 줄은 글자 그대로' 원칙에 맞고, 재타입이 되면 그때 42804로 즉시 드러난다). (b) 캐스트를 유지하되 caller_impact에 `dto/feature.py:143` · `providers/opinet.py:553`·`:712` · `providers/krex.py:892-903`을 `feature_repo.py:2218-2220`과 **같은 blocker 묶음**으로 올리고, 302~308 사슬에서 `parent_feature_id`가 alias 조회 21에 포함됐음을 재키 DDL 원문으로 확정한다.

**경계 규칙 확인**: **결론: 경계 규칙은 지켜졌다.** 네 루틴 전부를 `alembic/head-schema.sql` 원문에서 잘라내 `diff -u`로 대조했고, `feature_uuid` 등장 자리를 하나씩 셌다(grep -o 기준 실제 개수).

**routine 1 `create_feature_with_initial_state` (원문 3679-3785)** — 실제 12곳(산출물은 "11곳"이라 적었다). 분류: 시그니처 OUT 1 · DECLARE 1 · 입력 allowlist 1 · `IF p_feature ? 'feature_uuid'` 블록 2 · INSERT 컬럼/값 2 · RETURNING…INTO 2 · fallback SELECT…INTO 2 · (ALTER PROCEDURE 1은 본문 밖). **경계 자리 0** — jsonb payload 키·`RETURNS TABLE` 컬럼·API 응답 필드가 하나도 없다(이 루틴은 `RETURNS TABLE`을 만들지 않고, jsonb를 조립하는 유일한 자리는 `jsonb_build_object`가 아니라 입력 검증이다). 12곳 전부 삭제 = **정답**.

**routine 2 `create_admin_manual_feature_with_initial_state` (원문 2851-3009)** — 실제 21곳(산출물 "17곳"). 시그니처 OUT 2 · DECLARE 3 · allowlist 1 · `jsonb_typeof` 1 · 지역변수 사용 14. **경계 자리 0.** OUT 개명이 HTTP를 안 건드린다는 주장을 실측 확인: `packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_features.py:1838`의 wire 키는 이미 `"existing_feature_i

## curation

### 11. `feature.create_curation_rule_reconcile_receipt`

caller_impact가 소비자 목록의 완결성을 주장하는데("in-DB 호출자 5곳 전부 무영향", "Python 호출자 없음", "읽는 쪽은 src/kortravelmap/infra/models.py:2903-2941 ORM 매핑뿐") **데이터 계약 소비자 하나가 빠졌다**. `feature.materialize_theme_candidate_generation`(alembic/head-schema.sql:5498)이 이 함수가 쓴 scope-member 집합을 DB에서 **재도출해 EXCEPT로 대조**한다. 재도출 3곳이 전부 캐스트 없는 `SELECT 'feature'::text, link.feature_id`다 — head-schema.sql:5710(v_expected_scope_member_count 계산), 5729·5744(EXCEPT 양방향). 재키로 source_links.feature_id가 uuid가 되면(contracts/vnext/target-schema-v1.sql:1434) 이 셋은 첫 branch `entity.source_entity_key`(text)와 `UNION types text and uuid cannot be matched`(42804)로 죽고, 설령 통과해도 `ops.curation_rule_reconcile_scope_members.member_key`(text, head:16713)와의 EXCEPT가 성립하지 않는다. 즉 2차본이 루틴2에서 `link.feature_id::text`로 만든 member_key 철자는 **이 검증자와 공유하는 계약**인데, 그 결박이 산출물에 한 줄도 적혀 있지 않다. 이 함수 자체가 호출자가 아니라서 '호출자 5곳' 목록에 안 걸린 것이 누락의 원인이다.

**수정**: 루틴2의 caller_impact에 항목 추가: "`feature.materialize_theme_candidate_generation`(head:5498)의 scope 재도출 3곳 — head-schema.sql:5710 / 5729 / 5744 — 도 **같은 커밋에서** `SELECT 'feature'::text, link.feature_id::text`로 동일하게 고쳐야 한다. 안 고치면 non-provider reconcile 경로 전량이 첫 호출에 42804로 죽고, 타입이 맞더라도 `ck_theme_candidate_reconcile_scope_set`이 상시 발화한다. 이 루틴이 다른 그룹 소관이면 그룹 간 결박(cross-group blocker)으로 올릴 것." 동시에 "읽는 쪽은 ORM 매핑뿐"이라는 완결성 문장을 "ORM 매핑 + in-DB 재도출 검증자 1개"로 정정. (부수적으로 unknowns #3의 "SQL/dagster 쪽 세대 간 비교 여부는 미확인"은 실측으로 좁힐 수 있다 — head:5679-5697의 aggregate 해시 재계산은 저장된 scope_members 행을 그대로 읽으므로 `core.feature_uuid::text` 배열 접기의 영향을 받지 않는다. 즉 배열 접기는 안전하고, 위험한 것은 member_key 철자뿐이다.)

**경계 규칙 확인**: 【결론: 이 그룹에는 "되살릴 경계"가 원문부터 0개다. 1차본의 체계적 결함(22개 전부에서 feature_uuid 삭제)은 curation 그룹에는 존재하지 않았고, 2차본이 그것을 정확히 진단했다.】

■ 원문 feature_uuid 토큰 전수(세 루틴 범위 awk 스캔, 총 6건 — 이게 전부다)
  - feature.apply_curation_import_items_command (257~670): **0건**. 2차본의 "grep 0건" 주장 실측 확인.
  - feature.create_curation_rule_reconcile_receipt (3561~3670): **2건** — 3589·3657 `core.feature_uuid::text` (둘 다 jsonb_build_array의 **키 없는 위치 원소**).
  - ops.record_curation_import_manual_feature_child (12499~12591): **4건** — 12499 `IN p_feature_uuid uuid`(시그니처), 12566 `feature_row.feature_uuid = p_feature_uuid`(술어), 12583 INSERT 컬럼명, 12587 VALUES 인자.

■ ★규칙 자리별 개수 (하나씩 셈)
  1) jsonb payload의 `'feature_uuid'` **키** — 원문 **0개**. 따옴표 붙은 `'feature_uuid'` 리터럴이 세 범위에 한 건도 없다. → 유지할 대상 없음. (반대로 유지해야 할 인접 키 `'requested_feature_id'`(원문 601)는 2차본에 **그대로 살아 있다** — diff에 나타나지 않음. 값 출처 `identity.feature_id`도 원문 그대로이고 재키 후 uuid → jsonb_build_

## misc

### 12. `feature.purge_manual_feature`

**FK 삭제 액션 보존이 선결조건인데 어디에도 없다.** 지금 `fk_feature_aliases_feature`(head-schema.sql:23220)는 `ON DELETE CASCADE`라 confdeltype='c'이고, 그래서 legacy alias 행은 블로커가 아니라 캡처 대상이다. 그런데 (a) T-VN-39 설계 문서(docs/reports/t-vn-39-rekey-design-2026-09-09.md §4)는 `features`를 참조하는 FK 40개를 **전부 DROP하고 34개를 재생성**한다고 못 박았고, (b) 재생성의 목표형인 contracts/vnext/target-schema-v1.sql:936-937은 이 FK를 **`ON DELETE` 절 없이** 쓰고 바로 위 주석에 `-- ON DELETE 의미(feature 물리 삭제 시 alias 처분): 미정`이라고 적어 두었다. NO ACTION('a')으로 재생성되면 이 프로시저의 블로커 probe `confdeltype IN ('r','a')`가 **모든 Feature의 legacy alias 1행을 블로커로 센다** → 모든 purge가 `ck_manual_feature_purge_evidence_bound`로 실패한다(부분 회귀가 아니라 100% 불능). 덤으로 캡처 루프(`'c','n'`)에서도 빠져 복구점이 alias를 잃고, `trg_feature_aliases_delete_fence`(21683)가 cascade 없는 DELETE를 거부하게 된다. 2차본은 `legacy_feature_id` NOT NULL 완화는 '계약 선결조건'으로 승격했으면서 이것은 unknowns에도 없다.

**수정**: caller_impact에 하드 선결조건으로 추가: `alembic/head-schema.sql:23220 fk_feature_aliases_feature`는 재생성 시 **`ON DELETE CASCADE`를 반드시 보존**해야 하며, 일반화하면 `feature.features`를 참조하는 34개 재생성 FK 전부가 원래 `confdeltype`을 유지해야 한다(이 프로시저의 블로커/캡처 분류가 pg_constraint.confdeltype에 전적으로 의존한다). contracts/vnext/target-schema-v1.sql:936-937이 현행 head-schema와 어긋난다는 사실을 명시하고 어느 쪽이 정본인지 T-VN-39 DDL 그룹에 귀속시켜라. 본문 주석에도 한 줄(‘alias FK가 CASCADE가 아니면 이 probe가 모든 purge를 막는다’)을 남기는 편이 낫다.

**경계 규칙 확인**: 원문에서 저자가 만든 경계 자리(jsonb 키 / RETURNS TABLE 컬럼 / API 노출 필드)를 하나씩 세었다. 총 2개이고 2개 모두 2차본에 살아 있으며 값이 CAST(feature_id AS text)다.

[1] feature.current_theme_candidate_snapshot — 2개(전부 유지)
  · alembic/head-schema.sql:4295 `'feature_uuid', feature.feature_uuid::text,`
    → 2차본 `'feature_uuid', feature.feature_id::text,` (candidate_input → candidate_input_hash 입력)
  · alembic/head-schema.sql:4356 `'feature_uuid', input.feature_uuid::text,`
    → 2차본 `'feature_uuid', input.feature_id::text,` (RETURNS TABLE match_evidence)
  1차본이 (a) 앞엣것을 삭제하고 (b) 뒤엣것을 'feature_id'로 개명한 것을 둘 다 되돌렸다. 두 jsonb의 키 집합이 원문과 글자 단위로 동일함을 기계 diff로 확인했다(변경 5줄뿐: 시그니처 1 + 투영 삭제 2 + 값 출처 2). 소비 경계 실측: packages/kor-travel-map-api/src/kortravelmap/api/routers/curations.py:118 `extra="forbid"`, :129-130 `feature_id: str` + `feature_uuid: UUID`, :149 `match_evidence: dict[str, Any]` — 확인됨.

[2] feature.purge_manual_feature — 0개
  원

---

## n150 실행이 잡은 것 (2026-09-09)

설계 리뷰가 아니라 **실행**이 잡은 결함들이다. 순서가 그대로 진단의 순서다 — 앞의
것이 막고 있어서 뒤의 것이 안 보인다.

### 1. `permission denied for schema ops`

`ALTER PROCEDURE ops.record_curation_import_manual_feature_child(...) OWNER TO
ktm_curation_command_owner`. 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을
요구한다. 302가 같은 함정을 만나 "이전 동안만 GRANT하고 즉시 REVOKE"로 풀었는데, 그
형태는 **이미 CREATE를 가진 롤에서 권한을 빼앗는다.** 29건 전부를 자기 상태를 보고
되돌리는 `DO` 블록으로 감쌌다.

실측으로 범위가 확정됐다: `feature` 스키마는 소유자 롤 전부가 `ALL`을 갖고
(`alembic/head-schema.sql:24731-24737`), `ops`만 `ktm_curation_audit_writer` 하나를
빼고 USAGE뿐이다(`:24745-24752`). 그래서 이 문제는 사실 `ops` 한 건짜리였다.

### 2. 사이드카 배선 구멍 11건

2차 스코프에서 찾은 11개 루틴의 사이드카를 다 써 놓고 `_ROUTINE_STATEMENTS`에 넣지
않았다. **아무것도 빨개지지 않는다** — 마이그레이션은 통과하고, 시그니처 린트는
사이드카 파일을 원천으로 읽으므로 그것도 초록이다. 첫 실패는 한참 뒤 런타임이다.

`tests/lint/test_migration_sidecars_are_wired_into_their_migration.py`가 막는다.
배선을 정규식으로 찾으면 검사 자신이 같은 함정에 빠지므로(306은 이름을 f-string으로
조립해서 읽는다) `pathlib.Path.read_text`를 계측한 채 모듈을 import해서 실제로 열린
파일을 센다.

### 3. `must be owner of function derive_subtype_public_ready`

파일 하나의 결함이 아니라 **배치**의 결함이다. 루틴 사이드카를 소유자 롤별로 바깥에서
묶었는데, 그 그룹 안에 자기 `SET ROLE ...; ...; SET ROLE ktm_feature_schema_owner;`
쌍을 이미 들고 있는 파일이 섞여 있었다(pg_dump가 그렇게 뱉는다). 그 파일이 끝나는
순간 롤이 스키마 소유자로 돌아가고, 뒤따르는 파일이 엉뚱한 롤로 실행된다.

각 파일도 옳고 목록도 옳은데 합성이 틀린다. 그리고 목록에서 파일 하나를 옮기는
것만으로 다른 파일이 깨진다 — 계약이 아니라 함정이다.

바깥 그룹을 없애고 18개 사이드카가 각자 창을 열고 닫게 했다. 이제
`_ROUTINE_STATEMENTS`의 순서에는 의미가 없다.
`tests/lint/test_routine_ddl_runs_under_its_owner_role.py`가 문장열을 그대로 흉내 내
롤 상태를 따라가며 지킨다.

`ops.record_curation_import_manual_feature_child`는 예외가 될 뻔했으나 — `ops`에서
소유자 롤이 CREATE를 못 가진다 — 창을 셋으로 쪼개(소유자 롤로 DROP → 스키마 소유자로
CREATE+이전 → 소유자 롤로 GRANT) 예외를 없앴다.

### 4. 통과, 그리고 테스트 추종

여기서 `alembic upgrade head`가 통과했다(13 passed / 2 failed). 남은 둘은 마이그레이션이
아니라 테스트다: `_UNMAPPED_TABLE_COLUMNS`의 `feature_id text` 핀 4개와 uuid 컬럼에
들어가는 문자열 리터럴. 다섯 번째 핀
`ops.tvn36_legacy_freeze_preflight_manifest.feature_id`는 legacy `f_*`를 보존하는
freeze manifest라 **text 그대로 둔다.**

## 되짚어 본 것 — 이미 옳았던 것

- **FK 참조 액션 34개 전부 보존됨.** §12이 하드 선결조건으로 올린
  `fk_feature_aliases_feature`의 `ON DELETE CASCADE`를 포함해 `ON DELETE`/`ON UPDATE`/
  `MATCH`/`DEFERRABLE`이 head와 글자 단위로 일치한다. 조용히 깨지는 부류라
  `tests/lint/test_dropped_and_recreated_fks_keep_their_actions.py`로 못 박았다.
- **target-schema 계약은 이미 `feature_id uuid`다.** `contracts/vnext/target-schema-v1.sql`에
  `feature_id text`가 0건이다 — 309는 계약을 벗어나는 게 아니라 계약을 향해 간다.
  계약이 `feature_uuid`를 말하는 두 자리는 산문 주석이고, 둘 다 "current head는 아직
  shadow를 들고 있다"는 **경과 서술**이다.
- **ADR-098 write 경로 완결.** 18개 provider 전부가 `provider_natural_key`를 싣고,
  `tests/lint/test_provider_features_carry_their_natural_key.py`가 그것을 지킨다.

## 남은 것

- `packages/kor-travel-map-api/.../identity_projection.py`는 재키 후 **항등 치환**이 된다.
  `feature_id`가 이미 UUID라 `row["feature_uuid"]`로 갈아끼울 것이 없다. 8개 라우터
  ~30개 호출부가 걸려 있어 T-VN-39 범위에서 걷어내지 않는다 — 재키가 초록이 된 뒤의
  독립 정리 항목이다. 지금은 무해하게 계속 통한다(repo가 여전히
  `CAST(feature_id AS text) AS feature_uuid`를 투영한다).

---

## 잔여 text 루틴 전수 판정 (2026-09-09)

head 오라클을 직접 훑어 "사이드카가 없는데 `feature_id`를 만지면서 명시적 text가
섞인" 루틴 7개를 뽑고, 각각을 두 에이전트가 독립 판정했다(하나는 판정, 하나는 반박).
**"text가 보인다"는 곧 결함이 아니다** — 실제로 타입이 충돌하는 식만 결함이다.

### 깨진다 — 사이드카 필요 (2)

**`feature.archive_curated_source_command`** (head:1451·1483)
```sql
COALESCE(array_agg(scope.feature_id ORDER BY scope.feature_id), ARRAY[]::text[])
```
`scope`의 UNION 두 갈래가 `theme_feature_candidates.feature_id`와
`source_links.feature_id`인데 309가 둘 다 uuid로 옮긴다 →
`42846: COALESCE could not convert type text[] to uuid[]`.

배열 타입은 둘 다 typcategory 'A'라 42804 카테고리 검사를 통과하고, 그 다음
`can_coerce_type(uuid[] → text[], IMPLICIT)`가 실패한다 — uuid는 pg_cast에 항목이
하나도 없고 I/O fallback은 ASSIGNMENT 이상을 요구하기 때문이다. 그래서 공통타입이
첫 인자 uuid[]로 굳고 두 번째 인자 변환에서 죽는다.

재키 **전**에는 UNION이 text ∪ varchar였고 varchar가 text로 binary-coercible이라
공통타입이 text였다. 즉 `ARRAY[]::text[]`는 실수가 아니라 재키가 무효화하는 계약이다.

`INTO STRICT v_prelock_features`의 I/O 캐스트가 살려주지 않는다 — COALESCE는 SELECT
문 **안**의 식이라 그 문장의 parse 단계에서 죽고, plpgsql 대입 캐스트는 그 뒤다.

**`feature.materialize_theme_candidate_generation`** (head:5710·5729·5743)
`SELECT 'feature'::text, link.feature_id`의 UNION이
`42804: UNION types text and uuid cannot be matched`. 바깥 `EXCEPT`가
`ops.curation_rule_reconcile_scope_members.member_key`(text, 이종 멤버 키를 담아
309가 옮기지 않는다)와 비교하므로, 올바른 이전은 member_key를 uuid로 만드는 것이
아니라 `link.feature_id::text`로 text 축을 유지하는 것이다. 바깥 EXCEPT의 불일치는
독립 결함이 아니라 안쪽 UNION 공통타입 해석의 결과다.

### 안 깨진다 — 근거 (5)

- **`feature.archive_curated_theme_command`** · **`feature.patch_curated_theme_command`** —
  UNION 두 갈래(`theme_feature_candidates` ∪ `source_links`)가 **함께** 재타입되므로
  재키 전 text ∪ text가 재키 후 uuid ∪ uuid가 된다. 조인·필터에 feature_id 비교가
  없고, `v_feature_id text`는 advisory lock 키로만 쓰인다.
- **`feature.promote_theme_feature_candidate`** — 비교가 전부 uuid ↔ uuid.
- **`feature.validate_feature_override_value`** — `ops.feature_overrides.feature_id`가
  재키 후 uuid로 도착한다(`_309_author_feature_field_overrides.sql:16`이 `p_feature_id uuid`).
- **`ops.is_valid_feature_update_scope_0052`** — `ARRAY[]::text[]`가 feature 식별자와
  무관하다.

### 통하는 형태 — 이것을 결함으로 세지 마라

- `text[]` 변수에 `uuid[]` 대입, `FOR v_x IN SELECT <uuid 컬럼>`에서 `v_x`가 text —
  plpgsql 대입은 I/O 캐스트를 한다.
- `'literal' || <uuid 값>` — `text || anynonarray` 연산자가 있고, 결과가 uuid의
  canonical 소문자 표기라 uuid 변수를 쓸 때와 **같은 문자열**이다. advisory lock 키
  `'feature-write:' || ...` 15자리가 갈라지지 않는다는 뜻이고, 실측으로 확인했다
  (사이드카 4곳 전부 같은 철자, `_309_patch_curation_item_command.sql:72`는 uuid 컬럼을
  직접 이어 붙인다).

---

## 근본원인 — 왜 이 태스크가 오래 멈춰 있었나

### 하나: 마이그레이션이 끝까지 돌지 못해 아래를 아무것도 재지 못했다

T-VN-39의 결함은 대부분 **`alembic upgrade head`가 통과한 뒤에야** 보인다. 그
전까지는 통합 스위트 전량이 setup error라, 어떤 테스트가 왜 깨지는지 물어볼 수조차
없다. 그리고 마이그레이션 자체의 결함이 **순서대로 서로를 가렸다**:

1. `ops` 스키마 권한 → 이걸 넘어야 2가 보인다
2. 사이드카 배선 구멍 11건 → 넘어야 3
3. 롤 창 순서 결박 → 넘어야 4
4. 주석 속 `:feature_id` 바인드 표기 → 넘어야 비로소 테스트가 돈다

한 번에 하나씩만 보이므로, "고치고 돌리고"를 네 번 반복해야 첫 신호가 나온다. 그
사이 아래층은 전부 미측정이었고, 미측정 구간에서 한 판단은 전부 추측이었다.

### 둘: 범위를 오라클이 아니라 프록시에서 유도했다

옮겨야 할 루틴의 목록을 **네 번** 다시 셌고 네 번 다 놓친 것이 나왔다.

| 회차 | 프록시 | 놓친 것 |
|---|---|---|
| 1 | 본문에 `feature_uuid`가 나오는 루틴 | 시그니처만 text인 12개 |
| 2 | `db.py`/`runtime_privileges.py`의 선언 리터럴 | 둘 다 아닌 2개 |
| 3 | 표 별칭으로 한정된 `*.feature_uuid` 읽기 | `COALESCE`·`UNION`·`ILIKE` 부류 |
| 4 | `feature_id text` 인자를 받는 루틴 | 본문에서만 깨지는 2개 |

프록시는 언제나 진짜 집합보다 작다. 진짜 집합은 head 오라클
(`alembic/head-schema.sql`)이 갖고 있고, 그것을 세운 뒤에야 범위가 계산 가능해졌다.

### 셋: 탐지기의 시야가 곧 결함의 은신처였다

이번에 붙인 검사 여섯 개는 **전부 붙이자마자 같은 부류를 더 찾아냈다.**

- 사이드카 배선 검사 → 11건
- 식별자 인자 타입 검사 → 2건
- 자리표시자 수 검사 → 사람이 찾은 2건 외에 **2건**, 그리고 `tests`를 범위에
  넣자 **6건 더**
- 바인드 표기 검사 → 마이그레이션을 죽이던 주석 1건

특히 자리표시자 검사는 처음에 `_SEARCH_ROOTS`에서 `tests`를 뺐고, 검사가 안 보는
곳에 같은 결함이 그대로 살아 있었다. **범위를 좁게 잡는 것 자체가 은신처를 만든다.**

### 비용의 분포 — 큰 결함이 아니라 조용한 한 줄이었다

통합 실패 집계에서 최대 단일 원인은 SQL 한 줄이었다:

    COALESCE(CAST(:feature_id AS uuid), job.payload ->> 'feature_id')

일괄 캐스트 전환이 첫 갈래만 바꿨고 `->>`가 내는 text가 남았다. `INSERT`가 파스
단계에서 죽어 job 이벤트 기록이 통째로 멈췄고, **475건 / 84개 테스트**를 끌고
내려갔다. 그 앞에는 마이그레이션을 통째로 죽이던 주석 한 줄(700여 건)이 있었다.

즉 이 태스크를 멈춰 세운 것은 설계 난제가 아니라 **탐지되지 않는 작은 불일치**였고,
그것들은 하나같이 DDL 단계에서 조용하고 호출 시점에 죽는 형태였다.

### 개선 — 무엇을 바꿨나

1. **head 오라클을 세웠다.** 범위·시그니처·소유자·FK 액션의 단일 정본이 생겼고,
   "rev-300 baseline을 계약 오라클로 쓰던" 거짓 초록 부류가 닫혔다.
2. **결함마다 탐지기를 남겼다.** 고친 것으로 끝내지 않고, 같은 부류가 다시 들어올 수
   없게 검사를 붙였다(6종). 검사는 **규칙을 발명하지 않고 엔진/오라클에서 읽는다** —
   바인드 검사는 SQLAlchemy 자신의 정규식을, 소유자 검사는 head의 `OWNER TO`를 쓴다.
3. **순서 결박을 끊었다.** 롤 창을 사이드카 안으로 옮겨 `_ROUTINE_STATEMENTS`의
   순서에 의미가 없게 만들었다. 목록에서 파일 하나를 옮기는 것만으로 다른 파일이
   깨지는 배치는 계약이 아니라 함정이다.
4. **측정 하네스를 고쳤다.** pytest-timeout이 없어 데드락 하나가 전체 런을 무한정
   붙들던 것을, 파일 묶음 + 묶음별 `timeout`으로 바꿨다. 9묶음 20분이면 전체 표면을
   한 번 잰다.

## 결정적 개선 — 이 부류는 **실행이 필요 없었다** (2026-09-10)

### 관찰

위 "근본원인 하나"는 이렇게 적혀 있다: *"T-VN-39의 결함은 대부분 `alembic upgrade
head`가 통과한 뒤에야 보인다."* 절반만 맞았다. 마이그레이션이 통과해야 보이는 것은
맞지만, 그 뒤에 필요한 것이 **통합 스위트 한 바퀴**라는 전제가 틀렸다.

남아 있던 실패의 지배적 부류를 SQLSTATE로 보면 전부 한 곳을 가리킨다:

| 코드 | 뜻 | 언제 나는가 |
|---|---|---|
| 42883 | `operator does not exist: uuid = text` | **Parse** |
| 42P08 | `inconsistent types deduced for parameter $1` | **Parse** |
| 42P18 | `could not determine data type of parameter $1` | **Parse** |
| 42703 | `column "x" does not exist` | **Parse** |
| 42804 | `column "x" is of type uuid but expression is of type text` | **Parse** |
| 42P01 | `relation "x" does not exist` | **Parse** |

전부 PostgreSQL이 **Parse 단계**에서 낸다. 행이 하나도 없어도, 픽스처를 하나도
세우지 않아도 난다. 즉 이 부류를 찾는 데 **테스트 실행이 필요 없다.**

### 무엇을 만들었나

`tests/integration/test_product_sql_parses_against_head.py` — 제품 SQL 587개를
모아 head 스키마에 물린 뒤 `prepare()`만 시킨다. 실행하지 않는다.

수집은 **모듈을 import해서** `_..._SQL` 상수를 읽는다. AST로 문자열 리터럴을 긁으면
f-string 합성과 `+` 연결을 놓치고 그것이 또 하나의 프록시가 된다 — 이 저장소가 네 번
당한 실패 모드다. 조각(CTE 본문·INSERT 접두)은 이름 규약이 아니라 **포함 관계**로
가린다: 다른 수집 문장 안에 통째로 들어가면 조각이고, 판정은 품는 쪽에서 이미
이뤄진다. 품는 문장이 사라지면 조각이 자동으로 다시 검사 대상이 된다.

### 결과

첫 실행 **33초**, 20건. 그중 여덟이 진짜 결함이었다:

- 42P08 둘 — `curation_candidate_repo`의 nullable 필터. 맨 바인드와 캐스트된 바인드가
  한 문장에 섞였다.
- 42883 하나 — `feature_reference_reconciliation_repo`. `CALL`의 **OUT 자리 타입**이
  시그니처와 달라 그 CALL이 어떤 프로시저와도 맞지 않았다.
- 42883 둘 — `manual_provider_dedup_repo`의 사라진 시그니처 호출, `feature_repo`의
  `CAST(:hidden_before AS text[])`.
- 나머지는 드라이버가 주는 `uuid.UUID`가 문자열 계약으로 새는 자리와 scope 검증.

같은 여덟 건을 통합 스위트로 찾으면 9묶음 × 최대 20분이고, 그나마 실패 하나가 DB
픽스처를 죽이면 그 뒤가 통째로 가려진다. 실제로 두 번 그렇게 가려졌다.

### 이 오라클이 고쳐 준 두 번째 것 — 검사 자신의 틀린 전제

`test_procedure_calls_match_their_signature.py`는 docstring에 이렇게 적어 두고
개수만 셌다: *"인자의 타입은 보지 않는다. PostgreSQL은 OUT 자리의 타입을 해석에 쓰지
않는다."* 그 전제가 틀렸다는 것을 head 오라클이 증명했다 — SQL에서 부르는 `CALL`은
OUT 자리도 함수 해석에 넣는다. 검사를 넓히자 테스트 SQL에서 같은 부류 셋이 더 나왔다.

**검사가 스스로 적어 둔 근거도 프록시일 수 있다.** 오라클에 물어야 한다.

### 남은 사각과 그 이유

- **테스트 SQL** — 이 오라클이 닿지 않는다. 대부분 함수 안에서 조립되고 픽스처
  상태에 얽혀 있다. 그래서 `test_procedure_calls_match_their_signature.py`를 남기고
  타입까지 보게 넓혔다.
- **h35 고정 세대**(ADR-075) — `curation_repo`의 `_FROZEN_H35_*`/`_PRE_UUID_*`는
  0063~0079 세대를 겨냥한다. 그 세대의 오라클은 head가 아니다. 재키 뒤 그 경로는
  세대 분기가 없는 공용 표면 셋 때문에 이미 반쪽이고, **되살릴지 은퇴시킬지는 열린
  결정**이다(`_pre_uuid_feature_id_recordset`의 docstring이 목록을 들고 있다).
- **`feature.feature_files`** — 선택적 관계다. 호출부가 `to_regclass`로 먼저 묻고
  없으면 그 SQL을 실행하지 않는다. head에 없는 것이 정상이다.

## 조정기는 head 전용이 아니다 (2026-09-10)

`src/kortravelmap/infra/runtime_privileges.py`는 **revision 300에서도 돈다.**
`0236 → 300` handoff 실행자가 stamp 직후 그것을 호출하고, 그 시점의 catalog를
image에 봉인된 immutable reference와 sha256으로 대조한다. 그 catalog에는 **컬럼
단위 ACL**이 들어 있다.

그래서 "head에서 사라진 컬럼을 목록에서 뺀다"는 자명해 보이는 편집이 **300에서**
계약을 깬다. 309가 shadow `feature_uuid`를 지우며 `_ROUTE_AREA_RUNTIME_INSERT_COLUMNS`
에서 그 이름을 뺐고, 컬럼이 아직 살아 있는 300에서 ACL 두 줄이 사라졌다.

reference는 release 절차(`scripts/build-baseline.sh`, 살아 있는 0236 컨테이너와
source certificate 필요)만 다시 만들 수 있다. **바꿀 수 없는 쪽이 reference이고
맞춰야 하는 쪽이 조정기다.** 따라서 이 인벤토리에 이름을 더하거나 빼는 편집은
"head에서 맞는가"가 아니라 **"300과 head 양쪽에서 맞는가"**를 물어야 한다. 답이
갈리면 조건부로 만든다 — 표는 `to_regclass`, 컬럼은 `pg_attribute`.

### 진단 레시피 — sha256은 어느 줄인지 말하지 않는다

이 부류의 실패 메시지는 언제나 "catalog does not match"다. 어긋난 줄을 보려면
같은 절차를 재현해 **행을 그대로** 떨어뜨리고 두 판을 diff한다:

1. `tests/integration/_application_300_bootstrap.py`의
   `upgrade_baseline_root_with_application_300_bootstrap`으로 fresh 300 DB를 만든다.
2. `ktm_feature_migrator`로 붙는다(조정기가 그 로그인을 요구한다).
3. `reconcile_runtime_privileges_in_transaction` → `_set_canonical_contract_gucs`
   → `alembic/baseline/application-catalog.sql` 실행 → scalars를 줄로 적는다.
4. 의심되는 편집을 되돌린 판으로 같은 것을 한 번 더 하고 `diff`한다.

2026-09-10 실측에서 26,536줄 중 어긋난 것은 **둘**이었고, 그 둘이 handoff 전체를
멈춰 세웠다.

## live e2e — 격리 스택에서 실제로 돌렸다 (2026-09-10)

머지 전에 "정말 도는가"를 재려면 실행이 필요하다. n150의 disposable 격리 스택
(`~/ktm-live-301`, PG 127.0.0.1:15451 · API 13711 · admin web 13712)을 이 브랜치로
세우고 다음을 실측했다. prod compose project·DB·volume·image에는 접근하지 않았다.

| 단계 | 결과 |
|---|---|
| 빈 DB(`template0`) → `alembic upgrade head` | `HEAD=309_t39_feature_id_rekey`, `feature.features.feature_id` = **uuid** |
| `reconcile_runtime_privileges` | OK |
| API 기동(`ktm_feature_api_runtime` 로그인) | `/health` 200 — 기동 시 ADR-090 권한 preflight 통과 |
| **provider 적재**(dagster runtime 로그인, `load_feature_bundles`) | `features_inserted=1` |
| ↳ 정본 키 | `01a08a42-22ee-72bc-86d5-8c6d67deba82` (서버 발급 UUIDv7) |
| ↳ claim | `(place, <자연키>) → 그 uuid` 1행 |
| ↳ alias | `f_1156010100_p_17064ab452996653` 1행 — **주소 등록부** |
| `GET /v1/features?min_lon=…` | 200 · `feature_id` = `feature_uuid` = 정본 uuid |
| `GET /v1/features/search?q=…` | 200 · 1건 |
| `GET /v1/features/<uuid>` | 200 |
| `GET /v1/features/<legacy f_*>` | 200 · **같은 정본 키로 해석** |
| admin UI 로그인(실제 브라우저) | OK |
| admin `/features/<uuid>` | 이름 + 정본 uuid 렌더 |
| admin `/features/<legacy f_*>` | **같은 Feature** 렌더 |

핵심은 마지막 두 줄이다. ADR-098 결정 6("alias는 주소 등록부")이 DB·API·브라우저
세 층에서 같은 답을 낸다 — legacy 주소로 들어가도 정본 uuid의 Feature가 나온다.

`/features` **목록**은 이 스크립트에서 비어 보였다. 그 화면이 "현재 지도 범위의
feature"를 거르는 bbox 화면이고 기본 뷰포트가 심은 좌표를 담지 않기 때문이다 —
같은 질의를 API 층(`/v1/features?min_lon=…`)에서 하면 그 Feature가 나온다. 재키와
무관하다.

**재현 순서**(전부 `/tmp`의 disposable 스크립트, 리포지토리 밖):
빈 DB 생성 → `tests/integration/_application_300_bootstrap.upgrade_head_with_application_300_bootstrap`
→ 롤 비밀번호를 `.env`에 맞춤 → `reconcile_runtime_privileges` → uvicorn →
provider 번들 적재 → `npx next build && npx next start` → Playwright 드라이브.

## 적대 리뷰 — 12 에이전트 6축, 그리고 그것이 고친 것 (2026-09-10)

live e2e가 초록이 된 뒤 머지 전에 적대 리뷰를 돌렸다(opus5/xhigh, 6축 × 2명:
축 정합 · 경계 계약 · 마이그레이션/카탈로그 · 탐지기 품질 · 런타임 권한 ·
트랜잭션 경계). blocker 2건과 major 8건이 나왔고 전부 닫았다.

### blocker (커밋 `cb35cbcf`)

| 자리 | 무엇이었나 |
|---|---|
| 값이 새는 자리 | DB가 준 `uuid.UUID`가 text 계약 DTO로 그대로 나갔다 |
| 경계가 깨지는 자리 | 실행 트랜잭션이 조용히 deassociate된 채로 다음 단계가 이어졌다 |

### major — 축 부류 (커밋 `c1b4f3a3`)

1. `_FIND_PLACE_NO_PHONE_SQL` · `_PENDING_DEDUP_SQL` — 두 자리 모두 uuid를 밖으로
   내보내고 있었다. 첫 열을 `CAST(... AS text)`로 고정했다.
2. `ops.dedup_review_queue.feature_id_a/b`는 uuid인데 후보를 만든 `core.dedup`은
   provider 변환기가 준 legacy 주소만 안다. weather/price 값 경로와 **같은 부류**라
   같은 처방(`resolve_canonical_feature_ids`)을 썼다. 순서 정규화와 self-pair
   판정을 해석 **후**로 옮긴 것이 덤이다 — 서로 다른 두 참조가 같은 Feature를
   가리킬 수 있다.
3. `feature_request_repo` — SQL이 text로 내보낸 값과 프로시저가 준 `uuid.UUID`를
   맞대고 있었다. `str != UUID`가 **항상 참**이라 exact_conflict 분기가 언제나
   실패했다. 축은 같고 표기만 달랐던 자리다.
4. `legacy_id_for_filter`가 두 자리를 겸했다 — 자유 검색어(`q`, text 바인드)와
   feature 필터(uuid 바인드). `q`에는 원문을 돌려주는 것이 옳지만 uuid 자리에는
   그것이 곧 22P02(500)다. 표면을 둘로 갈랐고
   (`canonical_feature_id_for_filter`), 새 표면은 legacy `f_*`도 받아 정본 uuid로
   푼다 — 그 주소가 **여기서 처음으로 실제 필터가 된다**. 경계는
   `tests/lint/test_feature_ref_filters_bind_on_the_right_type.py`가 고정한다.

### major — 탐지기 부류 (커밋 `03cafa2a`)

네 건 다 "결함을 못 보는데 초록"이라 같은 부류다. 이 브랜치가 여러 번 잘못된
안심을 얻은 경로가 바로 여기다.

| 탐지기 | 왜 못 봤나 | 무엇으로 바꿨나 |
|---|---|---|
| FK 액션 보존 | "이전"을 head-schema에서 읽었는데 그것이 마이그레이션과 **함께 움직이는** 덤프였다 — 항진명제 | 308 시점 FK 222개를 얼려 정본으로(`contracts/vnext/foreign-key-referential-actions-v1.json`, sha 핀). 실측: 309가 되살린 34개 전부 drift 0 |
| head Parse 오라클 | 조립기 45개 중 **6개만** 불렀고 그 사실이 어디에도 없었다 | 인자 표 + `X \| None` 전조합 + 대역 호출 + "조용히 빠지는 길"을 없애는 fence. 43/45 호출, 수집 587 → **780** |
| 축 비교 검사 | `_SAME_AXIS`의 `feature_id` 갈래가 `legacy_feature_id`(text)까지 삼켰다 | 양쪽 축을 다 본다. "text가 아님"은 uuid라는 뜻이 아니므로 **적극적 uuid 신호**가 있을 때만 어긋난 것으로 판정 |
| 전화번호 보강 테스트 | `str(c.feature_id)`가 계약 위반을 덮었다 | 표기를 맞추지 않고 **표기를 잰다** + 후보를 지시대로 다음 단계에 그대로 흘린다 |

FK 검사는 확인을 위해 `fk_feature_aliases_feature`의 CASCADE를 떼고 head-schema까지
함께 고쳐(옛 판이 정확히 눈감던 조합) 돌려 봤다 — 새 축은 빨강, 옛 축은 초록이었다.

### 이 리뷰가 남긴 규칙

**검사가 초록인 것과 결함이 없는 것은 다른 사실이다.** 그 둘을 가르는 유일한 방법은
검사에 결함을 **일부러 넣어 보는 것**이고, 이번에 그렇게 해서 항진명제 하나를
찾았다. 그리고 하한(floor)은 "판단 대상 수"가 아니라 **"대상을 실제로 몇 개
보았는가"**에 걸어야 한다 — 앞의 것은 결함이 고쳐지는 순간 0이 되어 빨개지고,
뒤의 것만 "검사가 비었다"를 말한다.

## 머지 직전 — 쪼갠 하네스가 가린 것 (2026-09-10)

적대 리뷰 지적을 전부 닫고 9묶음 통합이 초록이 된 뒤 PR을 열었다. CI의 **한 세션
전량 런**이 곧바로 4건을 빨갛게 만들었다.

    tests/integration/test_feature_identity_boundary.py
      test_provider_create_writes_uuid_and_alias_atomically
      test_admin_manual_create_issues_no_alias
      test_feature_request_approval_issues_no_alias
      test_manual_curation_create_issues_no_alias
    → assert (0, 21, 0, 0) == (0, 0, 0, 0)

### 왜 묶음 런은 못 봤나

묶음 런은 파일 묶음마다 **새 세션·새 컨테이너**다. 그래서 세션 공유 DB에 누적되는
상태가 묶음 경계에서 사라진다. CI는 `pytest tests/integration -q` 한 줄로 전부를
한 세션에 돌리므로 누적이 그대로 보인다.

쪼갠 이유는 좋았다 — pytest-timeout이 없어 advisory lock 데드락 하나가 런 전체를
무한정 붙들고, 파일마다 `timeout`을 걸면 그 파일만 잃는다. 실제로 19분짜리 정지 두
번을 그 방식이 막았다. **그러나 빠른 하네스는 그 자체가 프록시다.** 이 작업이 오래
걸린 근본 원인이 "범위를 프록시에서 유도했다"인데, 마지막에 같은 실수를 측정 방식에서
한 번 더 했다.

### 숫자만 돌려주는 단언은 절반만 일한다

첫 실패는 `21`이라는 숫자 하나만 들고 있었다. 어느 claim인지 말하지 않았다 — 이
저장소가 sha256 카탈로그 대조에서 이미 겪은 부류다.

그래서 고치기 **전에** 진단을 붙였다(`_claims_missing_their_address`, 최대 12건을
실패 메시지에 싣는다). 다시 돌리자 답이 한 번에 나왔다:

    natural_key: 'DAGSTER-OPINET-001' / 'DAGSTER-KNPS-POINT-001' /
                 '11-DAGSTER001-37' / '2026.07.13::10:00:00::0010::서울방향::양재::1' …
    bound_by_operation: 'provider_sync'

전부 dagster asset 테스트가 commit한 claim이었다.

### 원인은 FK가 없다는 사실 하나

`provider_sync.provider_feature_identities`에는 `feature.features`로 가는 FK가 없다
(dataset FK 하나뿐). 그래서 정리 도우미가 도는

    TRUNCATE feature.features, provider_sync.source_entities, ... CASCADE

가 claim을 데려가지 않는다. commit하는 테스트가 지나간 자리마다 부모 없는 claim이
남고, identity 불변식의 둘째 축이 그것을 "주소 없는 claim"으로 세므로 **다른 파일이
대신 죽는다**.

`test_notice_lifecycle.py`는 이 함정을 이미 밟고 자기 자리에 명시 DELETE를 넣어
뒀는데(그 주석이 "claim은 CASCADE로 따라오지 않는다"고 정확히 적고 있다), 그 교훈이
정리 목록을 각자 들고 있는 **열여섯 파일**로 퍼지지 않았다.

### 처방 — 목록을 늘리지 않는다

호출부마다 이름을 더 적게 하면 잊는 것이 기본값이 된다. 대신 도우미가 호출부
TRUNCATE **뒤에** 부모 없는 claim만 거둔다:

```sql
DELETE FROM provider_sync.provider_feature_identities AS claim
WHERE NOT EXISTS (
    SELECT 1 FROM feature.features AS f WHERE f.feature_id = claim.feature_id
)
```

feature가 살아 있는 claim은 건드리지 않으므로 어떤 테스트의 의미 있는 상태도 잃지
않고, "feature는 있는데 주소가 없다"는 **진짜 결함**은 불변식이 계속 잡는다. 두 갈래를
`test_db_cleanup.py`의 한 테스트가 함께 본다 — 거두는 것만 보면 "전부 지운다"와
구분되지 않기 때문이다.

### 남는 규칙

쪼갠 하네스로 초록을 얻었으면 머지 전에 **한 번은 CI와 같은 방식으로** 돌린다.
다르게 재면 다른 것을 재는 것이다.
