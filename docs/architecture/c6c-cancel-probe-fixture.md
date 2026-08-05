# C6c cancel-probe fixture 수명주기 (T-VN-41F1J)

## 목적

T-VN-41의 C6c/F1D cutover는 PinVi가 Map canonical pipeline 취소를 실제로 호출하고,
Map이 **실행 중이지만 Dagster run이 없는** member를 안전하게 거절하는지 확인한다. 이
상태는 일반 수집 작업에 기대면 사라지거나 worker가 변경해 재현성이 없다. 따라서 probe
상태와 정리는 테스트 오케스트레이터나 정적 환경변수가 아니라 Map의 durable domain
state로 만든다.

성공 판정은 `409 PIPELINE_CANCELLATION_UNSAFE` 하나다. `404`, `502`, `503`, timeout,
다른 `409`, transport error는 모두 실패다. 이 fixture는 정상적인 provider 수집이나
admin UI의 pipeline 목록을 검증하는 기능이 아니다.

## 소유 경계

| 책임 | 소유자 | 금지하는 우회 |
|---|---|---|
| fixture job 생성·조회·consume·finalize, durable state | kor-travel-map | Manager의 DB 접속, Docker exec, 정적 job UUID |
| candidate Map ready 뒤 lifecycle 호출 및 F1D receipt | kor-travel-docker-manager | 넓은 HTTP 성공 수용, 자체 fixture 생성 |
| canonical cancel relay와 typed 오류 보존 | PinVi | fixture write credential 또는 lifecycle 호출 |
| normal cancel semantics | Map pipeline cancellation service | fixture 전용 취소 경로나 marker/history 삭제 |

Map만 `ops.import_jobs`와 `ops.pipeline_cancellations`를 함께 잠글 수 있으므로, fixture
수명주기 API는 Map service OpenAPI에 둔다. runtime full `openapi.json`은 route audit을 위해
이 3개 route를 포함하지만, user profile은 제외하고 admin BFF에는 이 route를 통과할 권한이 없다.

## 영속 모델

새 migration은 다음 상태를 둔다. `job_id` 및 `cancellation_id`의 UNIQUE 제약은 FK index를
겸하며, transaction ID PK 외 인덱스는 필요하지 않다.

```sql
CREATE TABLE ops.c6c_cancel_probe_fixtures (
  transaction_id UUID PRIMARY KEY,
  job_id UUID NOT NULL UNIQUE
      REFERENCES ops.import_jobs(job_id) ON DELETE RESTRICT,
  state TEXT NOT NULL CHECK (state IN ('armed', 'consumed', 'finalized')),
  cancellation_id UUID UNIQUE
      REFERENCES ops.pipeline_cancellations(cancellation_id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  consumed_at TIMESTAMPTZ,
  finalized_at TIMESTAMPTZ,
  CHECK (
    (state = 'armed' AND cancellation_id IS NULL
      AND consumed_at IS NULL AND finalized_at IS NULL)
    OR
    (state = 'consumed' AND cancellation_id IS NOT NULL
      AND consumed_at IS NOT NULL AND finalized_at IS NULL)
    OR
    (state = 'finalized' AND cancellation_id IS NOT NULL
      AND consumed_at IS NOT NULL AND finalized_at IS NOT NULL
      AND finalized_at >= consumed_at)
  )
);
```

`PUT`은 `transaction_id`를 멱등 키로 한다. 처음 요청은 Map이 새 job UUID를 생성하여
`kind='c6c_cancel_probe'`, `status='running'`, `dagster_run_id=NULL`로 만든 뒤 `armed`
row와 함께 commit한다. 같은 transaction ID의 재요청은 **동일 job ID와 현재 state**를
반환하고 새 job을 만들지 않는다. 다른 용도의 transaction ID 재사용은 허용하지 않는다.

`c6c_cancel_probe`는 reserved internal kind다. generic dispatch, worker claim, stale
recovery, normal lifecycle mutation, canonical pipeline execution list/detail 및 `ops:read`
projection이 이 kind를 선택하면 실패하도록 명시적으로 제외한다. fixture 전용 repository
외에 generic `start`/`finish` helper를 export하지 않는다. event write의 두 정본 경계
(`record_import_job_event`와 그 SQL)는 이 kind를 먼저 거부하며, 새 DB trigger는 direct SQL
`INSERT`를, 기존 event identity trigger는 job ID 변경을 거부한다. 따라서 fixture event가
존재할 수 없고 event audit은 import-job join이라는 정렬 경로 훼손 우회 없이 기존 partial time
index만 사용한다.

## 상태 전이와 crash 규칙

```text
PUT ensure                 PinVi normal cancel             POST finalize
없음 ───────────────► armed ───────────────────────► consumed ───────────► finalized
                            (cancellation history 보존)        (job failed terminal)
```

- `armed → consumed`은 기존 canonical cancellation이 만든 marker/member/attempt를 확인한
  **같은 transaction**에서 `cancellation_id`를 기록한다. cancellation이 없거나 root/job이
  다르면 409로 거절한다.
- `finalize`는 consumed fixture만 받는다. 같은 transaction에 job을 terminal `failed`로
  닫고 final timestamp를 기록한다. unsafe cancellation의 marker, attempt, member, run,
  system log는 지우거나 바꾸지 않는다.
- `PUT`과 `finalize` 모두 재시도 안전하다. process crash 뒤 Manager는 `GET`으로 현재
  row와 `canonical_unsafe_outcome`을 읽고 다음에 필요한 요청만 보낸다. outcome은
  `consumed`/`finalized` row의 canonical cancellation FK와 SQL consume 조건에서만 만들어지는
  `{http_status:409, code:"PIPELINE_CANCELLATION_UNSAFE", root_job_id, cancellation_id}`
  immutable 증빙이다. state가 `consumed`인 경우 Manager는 이 증빙을 durable receipt에 쓴 뒤
  cancel POST를 다시 보내지 않고 finalize를 재개한다. `finalized` fixture는 재무장하지 않는다.
- 과거 candidate image가 fixture endpoint/capability를 제공하지 않으면 Manager pair
  preflight가 fail-closed한다. old image에서 정적 UUID로 fallback하지 않는다.

## service API와 인증

모든 endpoint는 `X-Kor-Travel-Map-Ops-Token`과
`X-Kor-Travel-Map-Ops-Scope: ops:fixture`를 요구한다. 요청 scope 문자열만으로는
권한이 되지 않으며, `KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN`, exact method/path, scope가
모두 일치해야 한다. 이 token은 read/cancel/admin/public/service/metrics credential과 모두
다르고 Map API와 Docker Manager에만 주입한다. PinVi에는 주입하지 않는다.

| method/path | 입력 | 성공 | 실패 의미 |
|---|---|---|---|
| `PUT /v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}` | hyphenated UUID path | 200, `{transaction_id, job_id, state, canonical_unsafe_outcome, capability_generation}` | malformed/다른 scope 403, 미인증 401, lifecycle 모순 409 |
| `GET /v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}` | hyphenated UUID path | 200, 같은 durable receipt와 outcome | 없음 404 (Manager는 ensure 직후에만 허용) |
| `POST /v1/ops/contract-fixtures/c6c-cancel-probe/{transaction_id}/finalize` | `cancellation_id` hyphenated UUID body | 200, final receipt와 immutable outcome | 아직 armed/불일치 cancellation 409 |

service OpenAPI artifact에는 이 3 route와 DTO, security requirement를 포함한다. runtime full
`openapi.json`도 조립된 route audit을 위해 포함하며, user artifact는 제외한다. response의
`capability_generation`은 compatible-pair pinset의 동일 값과 정확히 일치해야 한다.

## C6c 실행 순서

1. Manager가 candidate Map migration·readiness·fixture capability generation을 확인한다.
2. Manager가 F1D durable transaction ID로 `PUT ensure`를 호출하고 response job ID를 journal에
   secret 없이 기록한다.
3. PinVi가 기존 `ops:cancel` credential로 canonical import-job cancel을 한 번 호출한다.
4. Manager가 **정확한** `409 PIPELINE_CANCELLATION_UNSAFE`와 canonical cancellation ID를
   확인하고 `GET` outcome과 job/cancellation identity가 일치할 때만 receipt를 확정한다.
5. response loss 뒤에는 `GET`의 immutable outcome을 같은 receipt로 기록한 뒤, cancel POST 없이
   fixture credential로 `POST finalize`를 재개한다.

cancel 직전/직후 crash도 `GET` state + immutable outcome으로 재개한다.
Manager가 Map DB 또는 container 상태를 읽어 추론하지 않는다.

## 검증 범위

- Map unit/API/integration: auth exactness, PUT idempotency, state CHECK, generic worker/read
  exclusion, unsafe cancellation consume, finalize history preservation, duplicate/cross-ID
  rejection, old capability fail-close.
- compatible pair: service OpenAPI artifact·capability generation re-pin, PinVi relay가 typed
  409 code를 보존하는 contract test.
- n150: isolated rehearsal 뒤 prod F1D 한 회차와 admin UI live E2E. 중간 fixture 데이터는
  보존 대상이 아니며 final schema의 backup/restore만 별도로 검증한다.

## 비목표

이 문서는 normal pipeline cancel API의 대체, provider job scheduler, PinVi의 fixture
관리 화면, Manager의 Map DB 접근 권한, 정적 fixture ID 호환을 만들지 않는다.
