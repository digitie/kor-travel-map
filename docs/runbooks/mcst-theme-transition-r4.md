# runbook — ADR-121 R4 MCST 테마 전환(운영 창)

정본 설계는 [`docs/architecture/place-theme-attributes.md`](../architecture/place-theme-attributes.md) §8,
결정은 [ADR-121](../adr/121-mcst-theme-lists-as-place-attributes.md)이다. 이 문서는 운영 창의 순서와
되돌림만 적는다.

## 0. 무엇이 되돌릴 수 없나

- `ktmctl mcst-theme-transition --execute`: MCST Feature를 master로 병합(attach·collapse)하거나
  퇴역(retire, 반려 업종)시킨다. 퇴역한 `feature_id`는 재사용하지 않고 lifecycle override가 provider
  재활성화를 막는다. PinVi M05 사건이 batch마다 남고, 사건 표는 append-only다.
- `KOR_TRAVEL_MAP_MCST_THEME_ATTACH_MODE=apply`: 이후 MCST 적재가 붙임 경로로 돈다. 전환 뒤 `off`로
  되돌리는 것은 롤백이 **아니다**(옛 목록 앵커가 퇴역 Feature를 다시 claim한다).

그 밖의 단계(계획·리허설·perf EXPLAIN)는 읽기 전용이거나 transaction을 되감는다.

## 1. 전제

- Map에 alembic 448(`448_mcst_theme_transition`)까지 배포. 붙임 모드는 아직 `off`.
- PinVi 재vendor 불필요 — 448은 OpenAPI·사건 payload 모양을 바꾸지 않는다(사건 표에 열·FK만 더한다).
- 국가유산 367쌍 큐 적용과 **겹치지 않는다**(같은 병합 경로·protocol EX를 쓴다).
- **이미지 롤백 = DB 복원.** 448 뒤에는 사건 표에 `origin_kind`·생성 열·FK가 바뀌어 448 이전 이미지가
  manual M05 사건을 쓰지 못할 수 있다. 448 이전 이미지로 되돌리려면 §3 전체 되돌림(백업 복원)과 함께 한다.
- PinVi M05 소비자는 **꺼져 있고** 살아 있는 lease가 없어야 한다(`ops.feature_reference_reconciliation_leases`에
  만료 전 lease 0). 실행 중 소비자가 사건을 ACK하면 §3 전체 되돌림이 PinVi까지 번진다.

## 2. 순서

| # | 누가 | 무엇 | 되돌림 |
|---|---|---|---|
| 1 | deploy | Map 448 포함 SHA로 회전(attach mode `off`) | 회전 규칙대로 |
| 2 | deploy | **동결**: 모든 feature 적재 operation·queue(`DISABLED_FEATURE_LOAD_SCHEDULES`)와 `consistency_dedup_refresh_daily_schedule` 정지, STARTED run 0 확인. 관리자 쓰기(M05 manual dedup 결정·feature PATCH·병합 큐 적용)도 창 동안 멈춘다. 국가유산 367쌍 큐가 돌고 있지 않음을 확인 | 해제 |
| 3 | deploy | map DB 백업(pg_dump) — 되돌림 기준점 | — |
| 4 | R4 | 새 계획 `ktmctl mcst-theme-plan --samples 50 [--exclude <dataset>:<action> …] --ids-out … --plan-out plan.json`(읽기 전용) → 목록별 action 수·정밀도 표본·제외 행 수·PinVi 참조 수 보고. 제외는 §2.1 | 없음(읽기) |
| 5 | coordinator | 표본 승인, 제외 목록·`plan_sha256` 확정 | — |
| 6 | R4 | 표본 리허설 `ktmctl mcst-theme-transition plan.json [--exclude …] --sample-per-action 200`(되감음) → stale·error 0 확인 | 없음(되감음) |
| 7 | R4 | **실행** `ktmctl mcst-theme-transition plan.json [--exclude …] --execute --confirm-plan-sha256 <sha> --batch-size 200` | §3 |
| 8 | deploy | `KOR_TRAVEL_MAP_MCST_THEME_ATTACH_MODE=apply`(Map Dagster code-server·worker env) 회전 | `off`는 롤백 아님 |
| 9 | deploy | 동결 해제, MCST 적재 1회(`feature_place_mcst_culture_job`) | — |
| 10 | R4 | 적재 metadata `theme_attach` 상태 수 확인(owner·sticky·redirected·matched·created), 속성 필터 운영 EXPLAIN | — |
| 11 | admin | 촬영지 rule `c09e1efd…`의 `place_kind`를 비우는 `PATCH /v1/admin/curated-source-rules/{rule_id}`(If-Match) | 다시 PATCH |

실행기(7)는 n150에서 Map API 컨테이너의 DSN(`ktm_feature_service`)으로 돈다 — 사건 writer가 그 로그인과
admin executor membership을 요구한다(실행기가 시작할 때 `session_user`를 확인하고 다르면 아무것도 하지
않는다). batch 하나가 transaction 하나이고 protocol EX를 쥔다 — batch 200이면 쓰기 정지가 batch마다 짧다.
batch 안에서 Feature 하나라도 `error`면 그 batch를 **통째로 되감고 멈춘다**(앞 batch는 남는다). 원인을
고친 뒤 같은 명령을 다시 돌린다 — commit된 batch는 건너뛰고(`(plan_sha256, batch_size, batch_index)`),
크기를 바꿔 돌려도 이미 전환된 Feature는 건너뛴다(`feature_id` UNIQUE → `already_done`).

전환되는 Feature를 가리키는 열린(`pending`) `ops.dedup_review_queue` 행은 `ignored`로 닫힌다(사유에 ADR-121).
병합 대상(master·생존자)은 active·published·valid여야 한다 — 아니면 `stale_target`으로 건너뛴다.

계획과 실행 사이에 Feature가 바뀌면 그 Feature는 `stale_revision`·`stale_target`으로, 병합 전제가 깨지면
(다른 kind 등) `conflict`로 건너뛴다(아무것도 쓰지 않고 batch는 commit된다). 동결 중에는 0이어야 하고, 0이
아니면 실행기가 종료 코드 1로 끝난다. 건너뛴 Feature는 같은 `(plan_sha256, batch_size)`로는 다시 시도되지
않는다 — 원인을 본 뒤 **새 계획**을 뽑아 다시 승인받는다(이미 전환된 Feature는 새 계획에서 빠진다).

리허설도 사건 sequence 번호를 소비한다(`nextval`은 되감기지 않는다). 사건 번호에 빈 칸이 생기는 것은
정상이다 — PinVi 커서는 존재하는 사건만 따른다.

### 2.1 정밀도 게이트 미달 쌍 제외(`--exclude`)

표본 판정(5)에서 어떤 목록의 어떤 action이 정밀도 게이트(설계 §5.4, 0.97)를 못 넘으면 그 쌍만 빼고
나머지를 전환한다. **계획 파일을 손으로 고치지 않는다** — `mcst-theme-plan --exclude <dataset>:<action>`
(반복 가능)으로 계획을 다시 뽑는다.

- `<dataset>`은 dataset_key(`mcst_barrier_free_places_csv`) 또는 slug(`barrier_free_places_csv`,
  `_csv` 생략 가능 — `barrier_free_places`). 계획에는 언제나 dataset_key로 기록된다. `<action>`은
  `attach`·`collapse`·`retire`(전환 action)만. 모르는 dataset·action·같은 쌍의 반복은 종료 코드 2로 거부.
- 제외된 행은 **기록된 비전환**이다. 계획 JSON의 `excluded_items`에 원래 action·대상·`row_revision` 그대로
  남고(`items`에서 빠진다), `exclusions`에 쌍이 남는다. 둘 다 `plan_sha256`에 든다 — 승인한 sha가 "무엇을
  하지 않는지"까지 고정한다. 효과는 `keep`과 같다(Feature·앵커·`feature_id` 불변, 사건 없음, 장부 행 없음,
  apply 모드 적재에서는 자기 목록의 owner로 남는다). 그래도 `keep`으로 다시 쓰지 않는 것은 판정과 결정을
  섞지 않기 위해서다 — 보고서 `by_dataset`·`samples`는 판정 그대로(제외 전후 같은 숫자)이고, 제외는
  보고서 `exclusions`(쌍마다 `feature_count`)와 계획 `excluded_items`로 따로 보인다. 나중에 그 쌍을 다시
  전환하려면 제외 없이 새 계획을 뽑으면 된다.
- 제외는 그 **행의 dataset** 기준이다. 다른 목록의 `collapse`가 제외된 목록의 생존자로 접히는 것은 그
  목록의 판정으로 남는다(생존자는 `keep`이라 제외와 무관하다). 남는 전환이 제외된 Feature를 대상으로
  하면 계획 생성이 거부한다(계획기 규칙상 생기지 않는다 — collapse 대상은 `keep` 생존자, attach 대상은
  비MCST master).
- `--ids-out`과 보고서 `retiring_feature_count`는 제외를 뺀 **실제 퇴역 예정**이다 — PinVi 참조 수는 이
  목록으로 다시 센다.
- 실행기(6·7)에는 **같은 `--exclude`를 다시 준다**. 계획에 기록된 제외와 정확히 같지 않으면(빠뜨림·더함
  포함, 순서와 표기는 무관) 리허설·실행 모두 DB에 닿기 전에 종료 코드 2로 거부한다 — sha만 붙여 넣다가
  다른 범위의 계획을 실행하는 일을 막는다. 제외 없는 계획은 `--exclude` 없이 돈다. 실행 요약에
  `exclusions`·`excluded_items`(수)가 찍힌다.
- 계획 파일 형식에 `exclusions`·`excluded_items`가 더해져 sha 정의가 바뀌었다. 이 기능 이전에 뽑은
  계획 파일은 실행기가 "옛 형식"으로 거부한다 — 운영 창에서 새로 뽑는다(어차피 창 안에서 다시 뽑는다).
- 계획은 그대로 읽기 전용이다(`SET TRANSACTION READ ONLY`) — 제외는 읽은 뒤 메모리에서만 적용한다.

2026-11-23 표본 판정(R4 준비 실행, `plan_sha256 3f93a4b7…`)에서 `barrier_free_places` collapse(0.94~0.96,
같은 복합 건물 주소의 다른 시설이 0 m로 접힘)와 `world_restaurants` collapse(0.81~0.92, 다른 주소의 체인
지점이 접힘)가 미달했다. 그 판정대로라면:

```
ktmctl mcst-theme-plan --samples 50 \
  --exclude barrier_free_places:collapse --exclude world_restaurants:collapse \
  --ids-out ids.tsv --plan-out plan.json
ktmctl mcst-theme-transition plan.json \
  --exclude barrier_free_places:collapse --exclude world_restaurants:collapse \
  --sample-per-action 200
ktmctl mcst-theme-transition plan.json \
  --exclude barrier_free_places:collapse --exclude world_restaurants:collapse \
  --execute --confirm-plan-sha256 <plan.json의 plan_sha256> --batch-size 200
```

## 3. 되돌림

- **전체**: 3의 백업으로 map DB를 복원한다(그 뒤의 쓰기는 잃는다 — 동결 중이므로 전환뿐이다). PinVi가
  그 사이 M05 사건을 ACK했다면 PinVi 참조도 함께 되돌려야 한다 — PinVi 소비자가 꺼져 있으면(기본) 없다.
- **부분**: `ops.mcst_theme_transition_items.before_state`에 퇴역 전 상태·link(역할 포함)·curation item
  행 전체·퇴역 전 active override, 병합 대상의 병합 전 link·curation item이, `evidence`에 옮긴/버린 link
  수·닫은 검토 행 id가 있다. 순서가 중요하다: ① link를 패자에게 되돌리고 역할을 `before_state.links`·
  `target_links`대로 복원 → ② 그 link를 근거로 관리자 재활성화(재활성화는 현재 원천 근거를 요구한다 —
  link가 없으면 실패한다) → ③ curation item을 되돌린다 → ④ 닫은 검토 행을 필요하면 `pending`으로. 개별 Feature를 되살리려면 관리자 재활성화(lifecycle override 해제 → active)와 link 재지정을 손으로
  한다. 사건은 지우지 않는다 — 되살린 Feature를 가리키는 새 사건이 필요하면 별도 결정이다.

## 4. PinVi

- 사건은 `ops.feature_reference_reconciliation_events`에 `origin_kind = 'mcst_theme_transition'`으로 쌓인다.
  payload 모양은 manual dedup 사건과 같고 `case_id`·`resolution_id`에 batch·item id가 들어간다.
- PinVi 운영 M05 소비자는 기본 꺼짐이다. 꺼져 있는 동안 퇴역 id를 참조하는 PinVi 행(R2 실측
  `trip_day_pois` 1,020행·161 Feature, 전부 attach/collapse)은 batch 응답 `retired`와 저장된 card
  snapshot으로 보인다. 소비자를 켜면 쌓인 사건을 순서대로 `rebind`·`detach`한다. 소비자는 sign-off 전까지
  꺼 둔다.
- 사건 writer는 장부 행을 원천과 대조한다 — batch의 domain command(actor·operation), 퇴역 전이 행(feature·
  revision·principal·kind), 병합 이력(loser·master). 실제로 일어난 퇴역에만 사건을 낸다(장부만 고쳐 아무
  Feature나 내리게 할 수는 없다). 다만 runtime 자격이 통째로 넘어가면 그 대조 원천도 runtime이 쓸 수 있다 —
  manual M05와 같은 신뢰 수준이다.
- 증거 export: 사건 표의 기존 evidence export(`evidence_export.py`·`docker-backup.sh` JSONL)는
  `ops.mcst_theme_transition_batches`·`_items`를 담지 않는다(후속 과제). 사건의 `case_id`·`resolution_id`
  (= batch·item id)는 §2-3 pg_dump 백업과 실행 뒤 두 표를 `COPY … TO STDOUT`으로 떠 둔 파일로 푼다.
