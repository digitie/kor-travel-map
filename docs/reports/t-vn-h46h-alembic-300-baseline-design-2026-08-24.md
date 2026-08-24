# T-VN-H46H — Alembic `300` baseline 및 `0236 → 300` 비파기 handoff 설계

작성일: 2026-08-24

## 결정

현재 Map application schema를 Alembic active graph의 유일한 root `300`으로
재정본화한다. `0200_schema_baseline`부터
`0236_tvn41s_compaction_drained`까지의 현재 active migration source는 실행 graph와
runtime image 밖의 byte-pinned retired archive로 보존한다. 과거 revision으로의
downgrade, snapshot restore, migration replay는 지원하지 않는다.

기존 n150 Map application DB는 DDL/data migration을 다시 실행하지 않는다. 정확히 한 번의
`0236_tvn41s_compaction_drained → 300` Alembic metadata handoff만 허용하며, 일반
`upgrade`, `stamp`, entrypoint 자동 migration, 수동 `public.alembic_version` 편집은
계속 fail-close한다.

## 범위와 비범위

이 작업은 Map application DB의 active Alembic lineage와 새 DB bootstrap을 바꾼다.
Map Dagster metadata DB와 PinVi DB의 Alembic revision을 변경하지 않는다. PinVi의 진행 중
Alembic WIP는 candidate source로 쓰지 않으며, deployment transaction에는 변경 없는
immutable PinVi revision만 결박한다.

`ktdctl pinvi-pair rebuild-pinned --confirm`는 이번 전환의 대안이 아니다. 이 명령은
Map application·Map Dagster·PinVi DB를 재생성하는 파기형 workflow다. raw production
Compose와 수동 version-table SQL도 후보 source/image/head와 transition 증거를 남기지
못하므로 사용하지 않는다.

## source baseline 생성 규칙

`scripts/build-baseline.sh`는 세 application schema의 non-empty table 전체를
`seed.sql`에 넣는다. 따라서 다음 DB는 source로 사용하면 안 된다.

- n150 production DB
- n150 backup clone
- live acceptance DB
- provider ingestion, UI fixture, acceptance cleanup 잔재가 남은 DB

source는 오직 disposable PostGIS에서 다음 순서로 만든 data-free isolated reference DB다.

1. #1063의 exact role-contract 변경을 포함한 old active graph를 fresh DB에서
   `0236_tvn41s_compaction_drained`까지 올린다.
2. M01/M04/M05 final role graph와 object ownership repair를 적용한다.
3. provider ingestion, live fixture, browser acceptance를 한 번도 실행하지 않았음을
   seed manifest·row count·canonical hash로 확인한다.
4. `0236` data semantic closure를 확인한다. compaction-drained 미표시 empty material,
   orphan 미표시 material, drained인데 item이 남은 material은 각각 0이어야 한다.
5. 이 reference DB에서만 `schema.sql`과 `seed.sql`을 생성한다. 같은 DB에서 두 번째
   dump가 byte-identical하지 않으면 warning으로 계속하지 않고 생성 자체를 실패시킨다.
6. final bootstrap을 선행한 별도 fresh DB에 `300`을 적용하고, reference `0236`와
   relation·column·constraint·index·routine·trigger·owner·ACL·extension·seed 및
   role/membership contract를 독립 비교한다.

## active graph와 archive

새 active graph는 아래 하나뿐이다.

```text
300_schema_baseline.py
  revision = "300"
  down_revision = None
```

`0200`~`0236`은 `alembic/retired_versions/0200-0236/`처럼 active
`alembic/versions/` 밖의 cohort에 둔다. `0104_tvn36_final_fence`는 이미 pre-squash
archive에도 존재하므로 retired cohort와 기존 109개 archive의 revision manifest를 합치거나
normal `version_locations`로 동시에 load하지 않는다. cohort별 source digest manifest를
독립적으로 유지한다.

최종 API image는 retired Python migration, transition-only Alembic config, old M01/M05
runtime helper를 포함하지 않는다. DB=`300`일 때만 normal startup을 허용하고,
DB=`0236`은 “controlled baseline handoff required”로 명확히 거부한다. 그 밖의
archive/unknown version은 unsupported lineage로 거부한다.

## final bootstrap contract

`300` baseline 적용 전에 bootstrap은 다음 21개 application role의 존재와 attribute를
정확히 확정한다. password material은 계약에 포함하지 않는다.

| 구분 | role |
|---|---|
| base NOLOGIN | `ktm_feature_schema_owner`, `ktm_feature_state_procedure_owner`, `ktm_feature_audit_writer`, `ktm_feature_runtime`, `ktm_curation_command_owner`, `ktm_curation_audit_writer`, `ktm_curation_admin_executor`, `ktm_curation_provider_executor` |
| LOGIN | `ktm_feature_migrator`, `ktm_feature_api_runtime`, `ktm_feature_dagster_runtime` |
| M01/M04 | `ktm_manual_feature_procedure_owner`, `ktm_manual_feature_admin_executor`, `ktm_feature_create_provider_executor`, `ktm_feature_request_procedure_owner`, `ktm_feature_request_service_executor`, `ktm_feature_request_admin_executor` |
| M05 | `ktm_manual_provider_dedup_procedure_owner`, `ktm_manual_provider_dedup_detector_executor`, `ktm_manual_provider_dedup_admin_executor`, `ktm_feature_reference_reconciliation_service_executor` |

contract는 role 존재만 보지 않는다. LOGIN/INHERIT/SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS/
REPLICATION attribute, PostgreSQL 16 membership의 `admin_option`/`inherit_option`/
`set_option`, DB와 `feature`/`provider_sync`/`ops`/`x_extension` owner, required extension의
namespace와 required `USAGE`를 모두 exact하게 확인한다. `ktm_feature_%`,
`ktm_curation_%`, `ktm_manual_%` 범위에 여분 membership edge가 있으면 거부한다.

routine ACL digest의 grantee axis는 과거 5-role 목록으로 고정하지 않는다. clean `0236`
reference의 effective direct grantee set을 정본으로 하고, `PUBLIC`, final owner/executor,
direct `EXECUTE`를 받는 runtime LOGIN role을 빠짐없이 측정한다. 새 direct grantee가
발견되면 digest가 이를 조용히 생략하지 않고 baseline 생성/적용을 거부해야 한다.

## one-shot `0236 → 300` handoff

old revision source가 active graph 밖에 있으면 일반 `stamp --purge 300`은 current `0236`을
새 `ScriptDirectory`에서 해석하려다 실패한다. 따라서 `alembic/env.py`에는 generic bypass가
아닌 exact one-shot branch만 남긴다.

허용 전제는 모두 참이어야 한다.

1. online migration function이 `do_stamp`다.
2. `purge=True`, target revision이 정확히 `("300",)`이며 SQL 출력 mode가 아니다.
3. raw `public.alembic_version`은 정확히 한 행이고 값은
   `0236_tvn41s_compaction_drained`다.
4. explicit handoff discriminator/tag가 있다. normal API entrypoint는 이 값을 설정하지
   않는다.
5. installed graph의 root/head가 유일하게 `300`이다.
6. writer fence, final role/extension/ACL contract, expected catalog fingerprint 및
   `0236` data semantic closure가 통과했다.

이 branch는 old `0236`을 `ScriptDirectory._stamp_revs()`에 전달하지 않는다. 같은 DB
connection의 outer transaction 안에서 preflight → Alembic `context.run_migrations()` →
postflight 순서로 실행한다. postflight failure까지 rollback되어 version row가 `0236`으로
보존돼야 한다.

postflight는 unique `300`, unique active `heads/current`, 동일한 application catalog,
role/membership, extension/ACL, index validity, constraint validation, trigger enablement,
data semantic closure를 재확인한다. 변경이 허용된 것은 Alembic metadata row 하나뿐이다.

다음은 모두 무변경 거부 대상이다.

- tag 없는 `stamp --purge 300`
- `--purge` 없는 stamp
- target `head`, `base`, old revision, range 또는 multi-target
- `0200`, `0104`, `0235`, unknown revision, empty/multi-row version table
- normal `upgrade head`가 `0236` DB를 자동 handoff하려는 시도
- 모든 downgrade 및 old archive replay

## n150 candidate deployment

Map PR을 merge하기 전 n150에서는 Docker Manager의 별도 Map in-place transition transaction을
사용한다. 기존 v7 destructive rebuild journal을 재사용하거나 in-place 결과를 rebuild로 기록하지
않는다. 새 typed journal은 최소한 다음을 redacted form으로 남긴다.

- `transition_kind = in_place_alembic_baseline_stamp`
- exact Map draft commit과 변경 없는 PinVi commit
- seven runtime immutable image ID 및 candidate head
- Map application pre/post head, Map Dagster/PinVi head
- writer-fence receipt
- expected/pre/post catalog and role/ACL fingerprint
- candidate execution identity, phase progression, committed terminal state

순서는 host-global lock → immutable source/image/head attestation → writer quiesce →
exact `0236`/catalog preflight → controlled stamp → `300`/post-catalog attestation →
candidate runtime start다. stamp 성공 뒤에는 old image 재기동이나 `0236` stamp-back을
하지 않는다. 실패 수정은 `300` 위의 forward fix만 허용한다.

candidate runtime health 뒤에는 Map UI login POST가 `200 + Set-Cookie`, invalid credential이
`401`인지 확인한다. 이어 exact candidate snapshot의 isolated fixture helper와 browser
main/recovery를 실행해 live UI E2E의 passed/recovered, cleanup/FK/container residue `0`,
`BLOCKED.json`/`ACTIVE.json` 부재를 확인한다. source SHA, transition-journal hash, head,
redacted result와 residue count만 evidence로 남기며 URL, credential, cookie, trace/video,
screenshot, fixture identifier, container identifier는 즉시 폐기한다.

## 완료 전 검증

- active root/head는 `300` 하나이고 generated application graph도 동일하다.
- retired source/archive manifest는 byte-pinned이고 normal runtime image에 없다.
- clean `0236`와 fresh `300`의 full catalog, final role graph, effective routine ACL,
  extension namespace 및 seed contract가 동등하다.
- exact handoff positive case와 모든 rejection/rollback case가 integration test로
  `0236` preservation을 증명한다.
- Docker image/entrypoint, role bootstrap, Compose wiring, current 운영 문서가
  `300`/no-old-restore 정책과 일치한다.
- Map baseline 누적 delta와 Docker Manager transition delta를 각각 두 전문 적대 리뷰가
  독립적으로 재검토해 P0=0을 확인한다.
- candidate deployment와 live UI E2E가 완료되기 전 Map baseline PR은 병합하지 않는다.
