# `300` baseline 위에 child migration을 얹으려면 — 전수 조사 결과

> 조사일 2026-08-31. `T-VN-M03`의 `ops.curation_import_manual_feature_children`
> (`301_m03_import_children`)을 얹으려다 PostGIS 통합이 무너져 원인을 전수로 팠다.
> 에이전트 4대가 재현 DB(PG16 + `alembic/baseline/schema.sql` 적재)로 실증한 결과다.
> **이 문서는 다음에 head를 올릴 사람을 위한 레시피다.**

## 요약

`301`은 저장소 안 변경만으로는 완주할 수 없다. 막는 것이 **저장소 밖에 둘** 있다.

1. **baseline 재봉인이 `0236`/`300` 고정이다.** `scripts/build-baseline.sh`가
   `SOURCE_HEAD=0236_tvn41s_compaction_drained`(`:649`)와
   `fresh_revision = "300"`(`:966`)을 게이트로 박아, **정의상 destination이 `300`인
   baseline만** 만든다. head를 올리려면 "해시 재생성"이 아니라 baseline 기계 자체의
   설계 변경이 필요하다.
2. **형제 저장소가 exact-string으로 핀한다.**
   `kor-travel-docker-manager`의 `map_application_300.py:26` `APPLICATION_HEAD = "300"`,
   `map_application_300_candidate.py:30`의 `_require_exact_string(contract,
   "application_head", …)`. Map만 고치면 candidate가 거절된다. 짝으로
   `docker/api-entrypoint.sh:404`가 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=300`을 요구한다.

부수로 확인된 운영 위험: `build-baseline.sh`가 요구하는 핀 이미지
`sha256:dc17b064a946…`가 n150에서 **태그를 잃고 untagged로만** 남아 있다
(`postgis/postgis:16-3.5-alpine`는 이제 `69ee08977169`). `docker image prune` 한 번이면
영구 소실이고, 레지스트리에서 그 정확한 이미지를 다시 얻을 수 있는지는 **확인 불가**
(repo digest가 어디에도 핀돼 있지 않다).

## 이미 처리한 것 (PR #1124)

- **head를 리터럴 사본에서 파생 정본으로.** `application_schema_head()`가 migration
  graph에서 유도하고 단일 head/단일 root가 아니면 fail-close.
  `docker/` 네 executable + 테스트 fixture가 이것을 읽는다.
- **`env.py`의 잠복 파손 둘.** `:256` handoff가 graph head로 결박돼 있던 것, `:424`
  fresh 설치 facet 검증이 head가 움직이면 **조용히 꺼지던** 조건. 후자가 특히 중하다 —
  예외도 로그도 없이 검증이 사라진다.
- **인덱스 이름 과잉 고정.** `test_feature_curation_lookup_uses_membership_index`가
  1행·무통계 표의 tie-break를 이름으로 박고 있었다. 성질 단언으로 바꿨다.

## `301`을 얹을 때 해야 하는 것 — 정확한 목록

### A. 저장소 안 (기계적)

| # | 대상 | 내용 |
|---|---|---|
| 1 | `tests/integration/test_alembic_upgrade.py:677-679` | `_TVN40_RAW_SQL_CATALOG_SHA256`의 `("ops","curation_import_plan_claims")` digest 갱신. `uq_curation_import_plan_claims_plan_sha256`이 `pg_constraint` 1행 + `pg_index` 1행을 더하므로 반드시 바뀐다.<br>`1a1e40ea9f26…` → **`7136d74e3a8ef4e95b8d006ea353a4f0605c78bcf92fd95061766a9c5654ea06`** |
| 2 | 같은 파일 `_TVN40_RAW_SQL_TABLES` | 새 표를 **넣어야 한다**. 같은 성격(raw SQL 전용 command evidence)인데 exact-catalog 핀이 없으면 FK 6축·CHECK 3개가 *이름은 그대로 둔 채* 의미만 바뀌는 drift를 아무도 못 잡는다.<br>digest: **`50592b1ac8cd898e26f3fd1f5d82031161a9c0cc10cfc2f7c95d1f3f0a847893`** |
| 3 | `alembic/versions/301_…py` | `idx_curation_import_manual_feature_children_plan`을 **삭제**. `pg_indexes.indexdef` 대조 결과 PK 인덱스와 완전 중복(`USING btree (import_plan_id, plan_row_number)`)이다 — 순수 낭비. |
| 4 | 같은 파일 | `ALTER TABLE … OWNER TO ktm_feature_schema_owner` + 형제 receipt 표와 동일한 `GRANT` 추가. |
| 5 | `tests/integration/_application_300_bootstrap.py` | `upgrade` 대상을 파라미터로 받게 하되 **정적으로 해소 가능해야 한다** — `test_active_runnable_paths_never_target_legacy_revision`이 upgrade 대상을 해소해 retired revision이 아님을 증명한다. 파라미터는 그 증명을 무력화하므로, 리터럴 두 함수로 나누는 편이 맞다. |
| 6 | 카탈로그 계약 대조 테스트 | `upgrade`를 `BASELINE_ROOT_REVISION`까지만. 해당 해시는 **`300` 시점 카탈로그**를 고정하므로 head까지 올린 DB와 비교하면 당연히 어긋난다(계약이 틀린 것이 아니라 비교 대상이 틀린 것). |

3표(`_UNMAPPED_TABLE_COLUMNS`/`_CONSTRAINTS`/`_INDEXES`)에 적은 값은 **재현 DB 대조
결과 전부 정확**하다. `feature.curation_link_decisions`의 unique도 ORM 모델에 선언돼
있어 autogenerate drift가 없다.

### B. 설계 결정이 필요한 것

| 대상 | 문제 |
|---|---|
| `alembic/env.py:424` | facet 계약(`application-destination-alembic-version.sql:84`)이 `ARRAY['300']`을 못 박는다. 조건만 넓히면 **모든 fresh 설치가 전면 차단**된다. 올바른 수정은 조건이 아니라 **검증 시점을 `300` 도달 순간으로 옮기는 것**이고, 그러려면 `run_migrations()`를 `300`에서 한 번 끊어야 한다. |
| `docker/application-schema-fresh-300.py:888` | 같은 이유. `command.upgrade(config, "head")`의 계약 검증 체크포인트를 `300`으로 옮기지 않으면 확정 실패한다. |
| `alembic/baseline/schema.sql:15659` | `CHECK (destination_head = '300'::text)`. fresh installer가 파생 head로 INSERT하면 **DB CHECK 위반**이다. fixture로 못 고친다 — 재봉인 대상. |
| `scripts/run-admin-stack.sh:678` | `revisions != [("300",)]` — admin stack 자체가 `301` DB를 거절한다. |

### C. 잠복 파손 주의

`test_application_300_handoff_executable.py:93-101`이 `os.geteuid() != 0`일 때 stamp
경로를 test double로 갈아끼운다. **`env.py`의 handoff 결박이 CI에서 초록으로 통과한
이유가 이것이다** — 컨테이너 rehearsal과 프로덕션에서만 드러난다. 이 축을 바꾸면
반드시 컨테이너 경로로 확인할 것.

## 확인 불가로 남긴 것

- `dc17b064a946` 이미지를 레지스트리에서 다시 얻을 수 있는지
- 위 두 digest의 최종 정확성 — 재현 DB 기준이며 실제 통합 실행으로 재확정해야 한다
- PinVi 쪽 `"300"` 의존 여부 (검색하지 않았다)
