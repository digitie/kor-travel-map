# T-VN-41C — cache-target snapshot GC 실측 (n150 격리 DB)

- 날짜: 2026-08-20 · 상태: **PASS — 6개 축 전부 실측**
- 대상 AC(`docs/tasks.md` T-VN-41C): "n150 격리 DB에서 migration → 수동 GC → schedule ON →
  다음 tick 순서로 검증하고, GC 처리량이 유입률을 상회하며 remaining backlog가 0인지 증명한다.
  referenced snapshot 증가율과 보존 임계치 alert도 함께 확인한다."
- 재실행: `scripts/verify-tvn41c-cache-target-gc.sh` (n150에서
  `KTM_GC_VERIFY_DOCKER="sudo -n docker" KTM_GC_VERIFY_PYTHON=~/h35/venv/bin/python`).
  최종 실행 2026-08-20 08:13~08:16 UTC, 소스 `12e14cd3`(수치는 이 실행 기준).

## 1. 무엇을 어디서 돌렸나

격리 database **두 개**를 쓴다. 애플리케이션 DB(`ktm_gcverify`)와 Dagster storage
DB(`ktm_gcverify_dagster`)를 분리한 것은 취향이 아니라 필수다 — Dagster storage는
자기 alembic 계보를 `public.alembic_version`에 stamp하므로 같은 database에 얹으면
우리 head(`0225_tvn40c_physical_removal`)를 못 찾고 `Can't locate revision`으로 죽는다.
운영도 `kor_travel_map` / `kor_travel_map_dagster`로 같게 분리돼 있다(실행 중 확인).

prod DB는 건드리지 않았다. 게이트 스크립트는 `kor_travel_map` 등 운영 이름이 들어오면
`DROP DATABASE` 전에 거부한다.

## 2. 결과

| # | 축 | 결과 |
|---|---|---|
| ① | migration | fresh DB → role bootstrap → `alembic upgrade head` → `reconcile_runtime_privileges` 모두 OK. head `0225_tvn40c_physical_removal` |
| ② | 시딩 | 적격 backlog 56 header / 2,800 item + 보존 대조군 2종(참조됨 12, 미만료 12) |
| ③ | 수동 GC | 적격 **56/2,800 전부 삭제**, 대조군 24 **불변**, `remaining_*` 0, 4 batch, 35,422 items/s |
| ④ | 처리량 > 유입률 | 유입 **12,951 items/s** vs GC **65,214 items/s** (약 5.0배), 18 batch, remaining 0 |
| ⑤ | schedule ON → tick | cron override 반영 확인 후 STOPPED→start, **t+21초에 run 생성 · t+26초 SUCCESS**, backlog 42/2,100 → **0/0**, tick 1건 |
| ⑥ | referenced alert | 보존 ceiling·증가율이 **각각 독립 발화**, 기본 임계치에서는 **침묵** |

### ⑤ tick을 "우연"과 구별한 방법

GC schedule의 코드 기본 cron은 `15 * * * *`다. 이대로면 tick 관측에 최대 1시간이
걸리고, 관측됐다 해도 정시를 우연히 맞은 것과 구별되지 않는다. 그래서
`ops.dagster_schedule_overrides`에 `* * * * *`를 저장하고 **새 프로세스가 그 값을
집는지 먼저 단언**한 뒤 daemon을 띄웠다. override가 죽어 있으면 이 단계에서 멈춘다.

code location은 `maintenance.py`의 실제 job/schedule 객체를 import한다. 정의를 복제하면
`cron_for_schedule`의 import-time 해석과 `default_status=STOPPED`라는 **검증 대상 자체**가
사본이 되어 의미가 없다. 다만 운영 definitions 전체(38 schedule)를 띄우면 분당
schedule들이 격리 DB에 같이 tick을 쏘므로 code location은 GC job/schedule로만 좁혔다.

### ⑥ alert를 "항상 꺼짐"과 구별한 방법

alert는 **양방향**으로 봤다. 조인 임계치(header/item ceiling 10)에서는 켜지고, 기본
임계치에서는 같은 데이터로 꺼져야 한다. 한쪽만 보면 상수를 반환하는 alert와 구별되지
않는다. 증가율은 개수 ceiling을 기본값으로 둔 채 따로 터뜨려 발화 사유가 증가율이라는
것까지 분리했다.

```
[조인 임계치] alert=true  reasons=[item_ceiling, header_ceiling, item_growth, header_growth]
[기본 임계치] alert=false reasons=[]
[증가율만  ] alert=true  reasons=[item_growth, header_growth]   headers_growth_per_hour=8,530
```

## 3. 실측 중 확인한 동작 (결함 아님)

**growth baseline에는 1초 debounce가 있다.** `growth_baseline_eligible`은
`elapsed >= growth_min_interval_seconds`를 요구하고 그 하한이 1초다(테이블 CHECK).
GC 실행이 1초 안에 끝나면 직전 관측이 baseline 자격을 잃어 다음 판정이 "증가율 관측 불가"로
빠진다. backlog가 0인 상태에서 job을 연속 실행하면 각 run이 0.1초 이하라 실제로 이 경로에
들어간다 — 처음에 증가율 alert가 안 켜진 원인이 이것이었다. 게이트는 실행 사이에 2초를
둬서 피한다.

**fresh DB에서는 vacuum 관측이 비어 있다.** 매 run이
`snapshot_storage_observation_issue_reasons=['snapshot_vacuum_not_observed']` 경고를 낸다.
`pg_stat_user_tables`에 autovacuum 이력이 아직 없기 때문이고, 이것은 alert가 아니라 관측
품질 경고다(`snapshot_storage_alert`는 false). 운영에서 이 경고가 계속 보인다면 그때는
autovacuum이 실제로 안 돌고 있다는 신호이므로 의미가 다르다.

부수적으로, `referenced_growth_unobserved_reason`은 baseline 자격 실패도
`minimum_interval_not_reached`로 표기한다. 이번 사례에서는 실제 원인이 최소 간격이 맞아
오해를 낳지 않았지만, 사유 문자열이 조건보다 좁다는 점은 기록해 둔다.

## 4. 남은 것

이 축(GC)은 닫혔다. T-VN-41C에 남은 것은 GC와 독립인 두 항목이다 —
PinVi exact-pair receipt 전환과 최종 prod gate·production consumer enable.
