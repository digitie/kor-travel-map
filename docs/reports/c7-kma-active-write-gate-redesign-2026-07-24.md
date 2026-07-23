# C7 `ops-c7-kma-active-write` 게이트 재설계 제안 (2026-07-24)

- **상태**: Proposed (팀 결정 대기)
- **관련 태스크**: T-ADM-C7RUN
- **관련 PR/커밋**: #829 (running-race tolerate + detail-perf recency), 배포 스택 `map=9492ab2d / pinvi=e60d1711`
- **선행 하드닝 브랜치**: `fix/c7-late-scenario-hardening` (2-reviewer clean, v6 검증 — 아래 §4)

---

## 1. 요약 (TL;DR)

C7 실질 **제품 코드 blocker는 모두 fix·merged**(#829: running-race tolerate, detail 쿼리 perf).
남은 것은 **제품 결함이 아니라, `ops-c7-kma-active-write` 게이트 자체의 구조적 취약성**이다:

- **~50 step 단일 zero-retry flow** 하나에 **성격이 다른 3개 관심사**가 뭉쳐 있고,
- 그 중 하나(**cursor-overflow, 51 requests**)가 매 실행마다 **prune 불가능한 append-only 누적**을
  만들어 **자기가 검증하는 ops 쿼리를 스스로 열화**시키며,
- 후반 active 시나리오에 **서로 독립적인 flake source가 최소 5개** 남아있다(§3).

zero-retry 게이트에서 5개 독립 flake × self-degrading 누적은 **whack-a-mole로 수렴하지 않는다**.
따라서 개별 fix를 더 쌓기보다 **게이트 구조를 재설계**한다.

---

## 2. 근본 분석 — 왜 하나씩 못 잡나

### 2.1 하나의 monolith에 뭉친 3개 관심사

| # | 관심사 | 검증 목적 | 성격 |
|---|--------|-----------|------|
| 1 | **canonical identity + run-now** (create/reuse/rediscover/terminal) | "KMA active-write 파이프라인이 실제로 도는가" — **핵심 가치** | API 계약, 대체로 결정적 |
| 2 | **dataset detail UI 렌더** | admin UI가 파이프라인 상태를 보여주는가 | UI 타이밍 민감 |
| 3 | **cursor pagination overflow** (51 requests) | run-history 페이지 경계 이후 cursor가 도는가 | **느림 + 누적 생성 + 실시간 base 결합** |

세 관심사는 **실패 모드도, 필요한 견고화 기법도 다르다**. 하나로 묶여 있으니
어느 한 축의 flake가 전체 zero-retry 게이트를 떨어뜨린다.

### 2.2 self-inflicted 누적 (가장 해로운 구조)

관심사 #3은 매 실행마다 **51개의 실 KMA refresh 요청을 prod-live 스택에 영구 생성**한다.
`feature_update_request_idempotency`는 **append-only + RESTRICT FK**라 prune 불가.
그런데 detail/run-history ops 쿼리는 `roots_with_identity`를 **(target OR all) root 전체에 대해
bound 전에 계산**한다 → **누적이 커질수록 detail 쿼리가 느려진다**.

즉 **게이트가 스스로 검증 대상(ops 쿼리)을 열화**시키는 되먹임 구조다.
#829의 recency time-window+fallback로 한 번 완화했으나(§3-①), 이번 세션의 실행 누적만으로
7일 window조차 수천 root가 되어 다시 server timeout(504)에 도달했다.

### 2.3 실시간 KMA 타이밍 결합

base-rollover(§3-④), fast-completion(§3-③), freshness window 등 **실 KMA 시각에 강결합**되어
있어, 51-req 루프가 KST :40 base 경계를 넘기면 결정적으로 깨진다. 이는 **타이밍 내재적**이라
테스트 코드로 완전히 제거하기 어렵다.

---

## 3. 남은 flake source 5개 (정확한 위치)

| # | 위치 | 원인 | 성격 | 재설계 대응 |
|---|------|------|------|-------------|
| ① | backend `load_dataset_detail` → `list_pipeline_executions` | #829 recency-fallback가 fresh per-run scope(runs 적음)에서 발동 → **fully-unbounded O(roots²)** 재조회 → server timeout(504) | 백엔드 scalability | **C** (per-dataset bound) |
| ② | spec:381 `assertRunningRequestIdentityFromUi` | execution-detail 패널이 **response-gate 안 됨** (datasets fix와 동일 class) | 테스트 UI 타이밍 | **D** |
| ③ | spec:894 `rediscoverExactActiveRequest` | create 직후 `active_execution!==null` 단정 — fast-completion race | 테스트 타이밍 | **A**(identity spec tolerant) |
| ④ | spec:1005-1040 overflow 루프 | 51-req 실행이 KST :40 base rollover를 straddle → `base_datetime` 불일치 hard-fail | **타이밍 내재적** | **B**(overflow 분리) + **E**(bounded retry) |
| ⑤ | cleanup(`cleanupResources`) | cooperative cancel이 480s 내 terminalize 못 하는 tail | 잔여 | **B** + 완화 |

> ①·②·③은 §4의 선행 하드닝/리뷰에서 이미 진단·부분구현됨.
> ④는 관심사 #3을 prod-live에서 떼면 소멸. ⑤는 #3 규모 축소로 크게 완화.

---

## 4. 이미 완료된 것 (재설계의 입력)

- **제품 코드 fix (merged #829, 스택 9492ab2d)**:
  - running-race **tolerate** (fast-completion 시 running 관측 강요 제거).
  - detail 쿼리 **recency+fallback** perf (O(roots²) → windowed).
- **선행 하드닝 브랜치 `fix/c7-late-scenario-hardening`** (미머지, 2-reviewer clean):
  - `gotoExactDatasetUiSettled` — dataset UI 3개 goto 사이트를 detail GET response로 settle.
  - `withC7Cleanup` terminalTimeout 90s→480s (본문 grant와 일치).
  - run-now-while-running leg 제거 (mock 커버 `ops-pipeline.spec.ts:2379`, flake surface 축소).
  - **v6 검증**: UI-render 어서션을 **통과**(142s까지 진행) — settle fix 유효 확인.
    이후 ①의 504로 진행 실패 → 본 재설계의 트리거.
  - 2명 adversarial 리뷰: 하드닝 3fix **correctness/robustness clean**, 추가로 ②③④⑤ 식별.

---

## 5. 제안 — 재설계

### A. Monolith 분할 (관심사별 spec)

`ops-c7-kma-active-write` 하나를 세 개로 분리:

1. **`ops-c7-kma-identity`** — create/reuse/rediscover/terminal + fingerprint.
   **핵심 zero-retry 게이트**. #829 tolerant + ③ fast-completion tolerant 반영 → 결정적.
2. **`ops-c7-kma-detail-ui`** — dataset detail UI 렌더. **전부 response-gated**(D).
3. **`ops-c7-kma-cursor-overflow`** — pagination 경계. **prod-live 게이트에서 분리**(B).

효과: 각 spec의 flake surface가 좁아지고, 실패 시 **어느 관심사가 깨졌는지 즉시 국소화**.
zero-retry는 #1(핵심)에만 엄격 적용하고 #2/#3은 정책을 달리할 수 있음(E).

### B. cursor-overflow를 실 KMA prod 부하에서 분리 **(핵심 한 방)**

pagination-past-page-boundary는 **51개 실 KMA refresh를 prod에 영구 생성할 필요가 없다**.
다음 중 하나로 대체:

- (B1) **seeded fixture / 훨씬 작은 N** 으로 cursor 경계만 검증, 또는
- (B2) **전용 integration test**(비-누적 경로, DB seed)로 이관, 또는
- (B3) prod-live에서는 **저빈도**로만 실행.

이 한 수로 **④(base-rollover straddle) + ②-누적유발 + ⑤-tail 규모**를 **동시에 제거/완화**한다.
게이트가 자기 검증 대상을 열화시키는 되먹임(§2.2)이 끊긴다.

### C. ops detail 쿼리 per-dataset bound **(durable 백엔드 fix)**

#829의 **all-root 대상 time-window+fallback**를 **(provider, dataset_key) 범위 내
recency/count bound**로 교체:

- **snapshot**(`list_dataset_pipeline_execution_snapshots_scoped`)은 이미 scoped `EXISTS`라
  target-dataset root만 처리 → 여기에 **created_at recency/count bound** 추가는 clean.
- **run_history**(`list_pipeline_executions`)는 shared all-root CTE를 쓰므로 **scoped variant**가
  필요(dataset 필터를 `roots_with_identity` **앞**으로).
- 이렇게 하면 **누적과 무관하게 빠름**(target-dataset root만, 그마저 bound). all-root-overall
  bound의 **crowding-out**(고빈도 타 dataset이 저빈도 scope를 밀어냄) 문제도 회피.
- **주의(trade-off)**: bound는 idle scope의 아주 오래된 run을 첫 페이지에서 제외할 수 있음.
  단 latest_execution은 scoped snapshot이 보존, 더 오래된 것은 "load more"(unbounded 페이징)로
  커버. C7 대상 dataset의 idle scope는 과거 테스트 잔재라 제외가 오히려 정합.

> ①은 B만으로도 크게 완화되지만(누적 원천 제거), **C는 prod detail의 근본 scalability 보증**이므로
> B와 독립적으로 가치가 있다.

### D. UI 어서션 전면 response-gate

- dataset UI: `gotoExactDatasetUiSettled` (선행 하드닝, §4) 유지.
- **②** execution-detail 패널(spec:381)도 **동일 패턴**으로 execution-detail GET에 gate.

### E. zero-retry 정책 재고

- **핵심 identity 게이트(#1)**: zero-retry 유지(결정적이어야 함).
- **타이밍 내재적 잔여(④ 등)**를 포함하는 spec(#3)은 **spec-level bounded retry**(게이트 전체가
  아니라 개별 spec에 retries=1~2) 허용 검토. base-rollover straddle 같은 물리적 타이밍은
  코드로 0%가 불가능 — 소수 재시도가 현실적.

---

## 6. 권고 우선순위

1. **B (overflow 분리)** — 누적 되먹임 근절. 단일 최대 효과. ④ 소멸.
2. **C (per-dataset bound)** — prod detail scalability 근본 보증(누적 방어).
3. **A + D** — 선행 하드닝(§4) 머지 + spec 분할 + ②③ 반영. 대부분 이미 구현.
4. **E** — 잔여 타이밍에 bounded retry 정책.

B+C가 **구조적 원인(누적·scalability)**을, A+D+E가 **잔여 타이밍**을 덮는다.
B를 먼저 하면 이후 v6 반복이 **base-rollover 창에 종속되지 않아** 검증 사이클이 크게 빨라진다.

---

## 7. 하지 않은 대안 (기록)

- **누적 prune**: `feature_update_request_idempotency` append-only + RESTRICT FK로 **불가**.
  (retention 정책 도입은 별도 큰 아키텍처 변경 — 범위 밖.)
- **all-root-overall count bound**: 구현은 간단하나 고빈도 dataset이 저빈도 scope를
  crowding-out → idle scope run_history 첫 페이지 공백. C의 per-dataset bound로 회피.
- **whack-a-mole 계속**: 5개 독립 flake + self-degrading 누적에서 수렴 안 함(본 문서의 전제).
