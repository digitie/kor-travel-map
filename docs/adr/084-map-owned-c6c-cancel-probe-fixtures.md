# ADR-084 — Map-owned C6c cancel-probe fixture

- 상태: accepted
- 날짜: 2026-08-06
- 결정자: 사용자 · Codex

## 컨텍스트

C6c/F1D production cutover의 cancel probe는 PinVi가 Map의 canonical import-job cancellation을
호출하고 `running`이지만 `dagster_run_id`가 없는 member를 `409
PIPELINE_CANCELLATION_UNSAFE`로 안전하게 거절하는지 확인한다. 첫 trusted attempt는 login,
ETL summary, provider sync까지 성공했지만 cancel이 `404`였다. 정적
`KTDM_C6C_CANCEL_PROBE_JOB_ID`에 Map import job이 존재하지 않았기 때문이다.

Manager가 DB/docker를 조작하거나 PinVi가 fixture를 생성하면 두 시스템이 Map canonical
cancellation 상태와 별도 진실을 갖고 crash/retry에서 중복 POST, false green, history 유실을
만든다. broad 409/502/503 수용도 endpoint/fixture 부재를 성공으로 오판한다.

## 결정

1. Map은 `ops.c6c_cancel_probe_fixtures`에 transaction ID, job, canonical cancellation,
   `armed|consumed|finalized` 상태를 영속한다. job/cancellation FK와 상태 CHECK로 전이의
   정합성을 DB에서 보장한다.
2. Map service OpenAPI에 fixture 전용 ensure/read/finalize route를 둔다. Manager는 transaction
   ID만 전달하고 Map이 생성한 job UUID를 사용한다. 정적 job ID와 직접 DB/docker 우회는
   제거한다.
3. `ops:fixture` principal은 Map↔Docker Manager만 가진다. PinVi는 기존 exact
   `ops:cancel`로 정상 cancellation만 호출하며 fixture 권한을 얻지 않는다.
4. fixture kind는 generic worker, stale recovery, normal mutation, `ops:read` execution
   projection에서 제외한다. finalize는 canonical cancellation history를 보존한 채 terminal
   job 상태만 fixture 전용 transaction으로 닫는다.
5. F1D success는 exact `409 PIPELINE_CANCELLATION_UNSAFE`이며, response의 fixture capability
   generation과 service OpenAPI artifact를 compatible pair에 re-pin한다. route/capability 없는
   old image는 fallback 없이 fail-closed한다.

## 근거

Map만 import job marker, cancellation attempt/member/run, system log를 같은 transaction에서
다룬다. fixture lifecycle을 그 소유 경계로 옮기면 execution retry와 crash recovery가 durable
state를 단일 정본으로 읽고, Manager는 orchestration/recept 기록에만 집중한다. 자격증명도
PinVi cancel scope와 fixture write scope를 분리해 최소 권한을 유지한다.

## 결과

### 긍정

- F1D는 실제 missing-run unsafe branch를 결정적으로 검증하며 404/5xx를 성공으로 오인하지 않는다.
- static environment drift와 중복 cancel POST가 제거되고, crash 재개가 durable state로 정해진다.
- fixture는 normal provider workload와 admin pipeline UI에서 격리된다.

### 부정

- Map migration, service OpenAPI, 세 번째 ops credential, compatible-pair capability pin이
  필요하다.
- Map/Manager/PinVi release 순서가 endpoint/capability preflight를 포함해 더 엄격해진다.

## 후속

- T-VN-41F1J-A: Map schema/repository/API/auth/tests.
- T-VN-41F1J-B: Docker Manager dynamic orchestration/receipt.
- T-VN-41F1J-C: Map/PinVi service artifact와 generation re-pin.
- T-VN-41F1J-D: n150 isolated rehearsal과 prod live UI E2E.
