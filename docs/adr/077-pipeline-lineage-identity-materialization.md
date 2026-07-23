# ADR-077: pipeline root 멤버십을 stamp하고 read-time 재귀 lineage를 제거

- **상태**: accepted
- **날짜**: 2026-07-24
- **결정자**: 사용자 + Claude
- **출처**: C7 detail 504 근본원인 분석 · PR #832 2-reviewer 리뷰(잔여 = 무한 성장 lineage 재귀) · 현재 스키마(0050~0062) 정밀 조사

## 컨텍스트

`ops` pipeline 조회(run-history·detail·snapshot·overview·executions)는 모두
`src/kortravelmap/infra/pipeline_lineage.py`의 **재귀 lineage CTE**를 공유한다:
`job_ancestry`(전 job의 부모 체인을 재귀로 순회) → `cycle_roots`/`terminal_roots`
→ `job_component_roots`(component root 파생) → `job_owners`(소유 request 파생).
매 read마다 전 히스토리 그래프를 재구성하므로 누적에 비례해 악화하고 detail이
server timeout(504)을 냈다. #829(recency)·#832(dataset-scoped)는 재귀가 도는
**seed 집합만** 좁혔을 뿐 재귀 자체는 남겨, hot dataset에서 상수만 줄이고
성장률은 그대로다(무한 증가 — robustness 리뷰 잔여 지적).

정밀 조사 결과 **재귀는 데이터 형태상 불필요하다**:

- `import_jobs`는 이미 identity를 first-class로 저장한다(0051: `provider`/
  `dataset_key`, 0053: `sync_scope`, 불변 트리거 0052). 저장 안 된 유일한 것은
  **root/component 멤버십**(`root_id`/`component_root_id` 컬럼 없음).
- 세 job 계열 모두 **CHECK 제약으로 강제된 ≤2단계 트리**이고 **root는 insert
  시점에 알려져 있다**: provider-feature(root=`provider_feature_load_run`,
  자식은 같은 `dagster_run_id`+`parent_job_id=root`), batch(root=`load_batch_id`
  보유 + `parent_job_id IS NULL`, 자식은 같은 `load_batch_id`+`parent`),
  update-request(단일 노드 = 자기 root). `ck_import_jobs_feature_operation_parent`
  등이 3단계·cycle을 금지한다. 즉 재귀의 임의 depth·cycle 처리는 **제약이
  금지하는 형태에 대한 방어적 일반화**다.
- 코드베이스는 **이미 이 패턴을 쓴다**: `ops.pipeline_cancellations`는 root
  (`root_kind`+`root_id`)를 취소 시점에 materialize한다(0050). run-history/detail
  경로에만 적용되지 않았을 뿐이다.

본 저장소는 **아직 서비스 전(개발 단계)**이라 호환성·문서계약·prod 데이터 보존
제약이 없다 — shadow-read/backfill soak/단계별 rollback 같은 이관 ceremony는
불필요하다. 설계 우수성·안정성·속도를 최우선으로 근본 재설계한다(사용자 지시).

## 결정

**write 시점에 이미 아는 root 멤버십을 stamp하고, read-time 파생을 삭제한다.**
(materialize 범위는 **`root_id` 컬럼만** — 별도 projection 테이블 없이, root당
≤2개 member를 조회 시 rollup. 유지보수 표면적 최소, 2단계 형태라 충분히 빠름.)

1. `ops.import_jobs`에 **`root_id uuid NOT NULL`** + **`root_kind text`**(root의
   실행 종류) 추가. insert 시 stamp — root는 자기 자신(`root_id = job_id`), 자식은
   **부모의 `root_id` 승계**. 모든 writer가 이 값을 이미 안다.
2. `root_id`/`root_kind`를 **불변 identity**에 편입(`trg_import_jobs_identity_
   immutable`). 그리고 **2단계 불변식 전역 lock 트리거** 추가: 자식의
   `root_id`는 부모의 `root_id`와 같고 그 부모는 root(`parent_job_id IS NULL`)여야
   한다 — root_id를 1-hop stamp 가능하게 만드는 보증을 미래 job 종류가 깨지 못하게.
3. **재귀 lineage 전면 삭제**: `pipeline_lineage.py`의 `job_ancestry`/`cycle_roots`/
   `terminal_roots`/`job_component_roots`/`job_owners`, 그리고 #832의 `scoped_jobs`
   재확장까지. `pipeline_repo.py`의 `roots_with_identity`/`canonical_provider_
   datasets` 상관 서브쿼리도 제거. run-history/detail/snapshot/overview는
   **`WHERE root_id = …` / `GROUP BY root_id` 인덱스 조회**로 재작성.
4. 인덱스 `(root_kind, root_id)` + 기존 `(provider, dataset_key, sync_scope,
   created_at DESC)` 유지. member rollup은 root당 `root_id` 인덱스 조회(≤2행).
5. 기존 불변식(append-only, quarantine, shape CHECK, `feature_update_requests`
   generation guard)은 **그대로 보존**한다 — read 모델이 이들에 의존한다
   (`quarantined_at IS NULL` 필터 등).
6. 쿼리는 ADR-004대로 raw SQL `text()` 유지.

## 근거

root/ownership는 **immutable append-only 엣지의 순수 함수**이고, CHECK 제약이
≤2단계를 보증하므로 root는 write 시점 1-hop에 확정된다. 따라서 read-time 재귀는
순수 오버헤드다. projection 테이블 대신 컬럼만 택한 이유: 2단계 형태에서 root당
member rollup은 `root_id` 인덱스로 저렴하고, projection 유지(member 상태 변화 시
rollup 일관성)라는 표면적을 추가하지 않는 것이 이 규모에서 설계상 더 단순·안정.

## 구현 단계 (dev-stage — 이관 ceremony 없음)

- **P1** migration: `root_id`/`root_kind` 컬럼 + 인덱스 + 불변/2단계 lock 트리거
  추가, 기존 행 backfill(부모 승계 1-pass; 테스트 DB는 재생성). 빈 PostGIS
  `alembic upgrade head && alembic check`·단일 head.
- **P2** write-path: insert 경로(`jobs_repo`·`feature_operation_repo`·`batch_dag`·
  `feature_update_repo`)에서 root_id stamp.
- **P3** read 재작성: `pipeline_lineage.py` 재귀 삭제, `pipeline_repo.py` 쿼리를
  root_id 기반 인덱스 조회로. #829/#832 변형 제거.
- **P4** 테스트: 재귀 특화 테스트 → root_id 불변식/2단계 lock/조회 동치·성능
  (EXPLAIN 인덱스 확인) 테스트로 교체. n150 CI-parity 게이트.

## 결과

- **긍정**: 모든 ops read가 누적과 무관하게 O(log n) 인덱스 조회. 재귀 CTE·
  O(roots²) 상관 서브쿼리 전면 제거. #829/#832 interim 패치 불필요(제거).
  hot dataset 성장률 문제 근절.
- **부정**: 4개 write-path에 stamp 추가, migration, read 쿼리 재작성 필요.
  `root_id`가 틀리면 조회가 오답 → 2단계 lock 트리거 + 불변식 테스트가 게이트.
- **전환/rollback**: dev-stage라 단순 — 컬럼/트리거 drop으로 되돌림. prod 데이터
  보존 대상 없음.

## 기존 결정과의 관계

- 0050(pipeline_cancellations의 root materialize)의 **검증된 패턴을 run-history/
  detail 경로로 확장**한다.
- 0051/0053(identity 컬럼)·0052(불변 트리거) 위에 root 멤버십을 마저 저장한다.
- #829(recency)·#832(dataset-scoped)는 **interim query 패치**였고 P3에서 제거된다.
  재설계 제안 #831 §C의 근본(정식) 형태.
- ADR-004(raw SQL) 유지. 호환성·문서계약은 개발 단계라 제약 아님(ADR-075의
  이관 ceremony 비적용); 단 DDL 위생(단일 head, `alembic upgrade+check`)은 지킨다.
