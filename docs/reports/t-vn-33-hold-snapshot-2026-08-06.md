# T-VN-33 중단 시점 스냅샷 — 2026-08-06

## 상태

사용자 지시에 따라 T-VN-33의 구현·검증·적대 리뷰·rebase·커밋·push를 이 시점에서
중단한다. 이 문서는 완료 보고가 아니다. 작업트리의 T-VN-33/F1D 관련 변경은 **미스테이징,
미커밋** 상태로 보존하며, 원격·n150·컨테이너·DB에는 새 변경을 적용하지 않았다.

현재 branch는 `feat/tvn33-provider-datasets`, draft PR은 #966이다. 이미 원격에 있는
checkpoint 다섯 개보다 뒤의 변경은 모두 WIP이며, merge 가능 상태로 간주하면 안 된다.

## 확정된 설계

실행 membership identity는 예외 없이 다음 triple이다.

```text
provider_dataset_id + sync_scope + operation_key
```

`import_job_datasets`처럼 dataset member를 저장하는 행에는 세 값 모두 non-null이어야 한다.
operation이 없는 generic job은 dataset member 행을 만들지 않는다. 같은 ID/scope에서 다른
operation을 union·rank·대표 선택하거나 nullable/wildcard `operation_key`로 읽는 경로는
금지한다. 상세 결정은 ADR-088 §결정 2가 정본이다.

## 재개 전 반드시 해소할 P0

1. migration/model/guard: `import_job_datasets`, `provider_sync_state`, Dagster operation child
   snapshot의 PK/FK/unique/upsert/concurrency guard를 triple로 물리 전환한다. 기존 nullable
   operation key 및 wildcard guard는 삭제한다.
2. core read/write: feature-update request/job consistency·active plan·executor·pipeline projection의
   JSON/SQL/filter/partition을 triple로 바꾸고, pair/scope `ROW_NUMBER` representative selection을
   제거한다.
3. API/UI: `/ops/datasets`, `/ops/pipeline`, catalog, deep link, cache key, preview/mutation,
   event/history filter가 operation key를 요구·표시한다. refresh scope union/default effective
   selection과 자연키 normal route/body/query를 제거한다.
4. runtime: sync-state public natural-key route 및 Dagster scheduled/asset natural-key membership
   reconstruction을 exact DB membership injection으로 바꾸거나 route를 물리 삭제한다.
5. final schema: `0090`은 legacy source column을 삭제한 뒤에도 남아 있는
   `issue_curation_source_rule_decision()`을 catalog join으로 교체해야 한다. 모든 stale fixture를
   final schema seed → source entity → source record/head 순서로 바꾼다.

## 이 시점의 유효한 부분 검증

- core exact membership/sync-state focused unit: 104 passed.
- frontend type regeneration/type-check/selected ESLint/Vitest: 34 passed.
- T-VN-41 F1D-E Map-side attestation/runner/state/admin focused Python: 139 passed;
  helper ownership Playwright: 4 passed.
- API OpenAPI export 및 `--check`은, triple API 재설계 전의 numeric-ID checkpoint에서 통과했다.

## 검증으로 간주하지 않는 것

- Dagster focused suite는 145건 **수집만** 확인했다. NTFS WSL process가 D-state로 멈춰 실행/mypy를
  완료하지 못했으므로 pass가 아니다.
- local mocked Playwright는 WSL Chromium 부재로 실행 전 중단됐다.
- fresh final-schema PostGIS/API/Dagster/OpenAPI/UI 통합 검증, T-VN-33 최종 적대 리뷰 2인,
  PR rebase/CI, n150 live E2E는 수행하지 않았다.

## T-VN-41에 미치는 영향

F1D-E의 Map-side v5/v7 attestation·v4 cleanup evidence 보완은 WIP로 존재하지만 T-VN-41은
완료가 아니다. F1D-D는 T-VN-33 merge → final Map provenance pin → destructive rebuild-pinned
→ final-schema source/ETL 재적재 → n150 data-dependent UI/PinVi E2E 순서를 모두 통과한 뒤에만
재개한다. Docker Manager shared mutation lease/TOCTOU 보완은 Manager 구현을 변경하지 않고
Map runbook 요구 interface로만 기록되어 있다.

## 재개 순서

1. 이 스냅샷을 읽고 작업트리와 draft PR #966의 범위를 대조한다.
2. P0 1~5를 schema/core/API/frontend/Dagster lane으로 다시 분할하되, triple physical schema를
   먼저 안정화한다.
3. clean final-schema DB에서 migration/fixture/API/Dagster/frontend 통합 gate를 실행한다.
4. 독립 적대 리뷰 2인이 P0=0을 확인한 뒤에만 rebase·보안 감사·CI·merge를 진행한다.
5. 그 다음에만 T-VN-41 F1D-D의 final rebuild/ETL/n150 acceptance를 실행한다.
