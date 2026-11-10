# resume — 2026-09-19

[현행 resume](../resume.md)에서 크기 상한에 따라 분리했다.

## 2026-09-19 (3) — 산사태 0행의 이유를 확정했다. 다음은 대량 역지오코딩이다

**다음 한 작업: 대량 역지오코딩이 일시적 실패 한 번에 전체를 버리는 것을 고칠 것.**

`src/kortravelmap/providers/mcst.py`의 `file_rows_to_bundles`는 **행마다 순차로**
`await _resolve_address(...)`를 부르고, 그 예외를 잡는 자리가 provider·dagster
어디에도 없다(저장소 전체에 `except GeoRequestError` 0건). prod 실측:

```
feature_place_mcst_culture_job        4회 시도 / 2h54m / FAILURE
  RetryRequestedFromPolicy: Exceeded max_retries of 3
    <- GeoRequestError: kor-travel-geo transport 실패: ReadTimeout
  마지막 시도는 upstream_requests_min=13 — 13개 dataset을 다 받아 놓고 죽었다
feature_route_krforest_mountain_trails_job
  04:04:24 STEP_START 이후 3시간 dagster 이벤트 0건
호스트: 4코어, load average 17
```

**실측한 분모.** geo reverse를 job과 같은 컨테이너·같은 설정으로 쟀다.

| 방식 | 20건 벽시계 | p50 | p95 |
|---|---:|---:|---:|
| 순차 | 2.6s | 86ms | 515ms |
| 동시 4 | 0.8s (3.3배) | 160ms | 212ms |
| 동시 8 | 0.4s (6.5배) | 134ms | 326ms |

동시성을 올려도 **건당 지연이 나빠지지 않는다** — geo가 병목이 아니라 왕복 직렬화가
병목이다. 그리고 p95가 0.5초인데 timeout은 10초다. ReadTimeout은 20배 이상치이므로
**timeout이 빡빡한 것이 아니라 이상치 한 번에 대한 내성이 0인 것**이 문제다.

**그런데 범인은 geo가 아니었다 — 원인을 다시 쟀다.**

처음에 나는 이 실패를 "geo가 느려서 timeout"으로 읽었다. 적대 리뷰가 그 전제를
의심했고(4코어에 load 17인데 geo는 CPU 0.15%로 유휴), 읽기 전용으로 다시 재니
전제가 틀렸다.

```
/proc/pressure/io   full avg300 = 25.5%   ← 전체 시간의 1/4 동안 모든 태스크가 디스크에 막힘
/proc/pressure/cpu  full avg300 =  0.0%   ← CPU는 병목이 아니다
geo 503 / E0500 (5시간)          0건      ← geo는 포화 신호를 낸 적이 없다
D 상태 프로세스                  postgres
04:05:00 최대 동시 run             8건
```

**04:03~04:05에 내가 feature job 7개를 동시에 띄웠고** weather 상시 run까지 8개가
4코어·단일 회전 디스크에서 겹쳤다. `docker/dagster.yaml`의 주석이 이미 그 사실을
적어 두었다 — *"provider job은 IO-bound이고 n150은 단일 회전 디스크를
weather/concierge/geo/airport와 공유한다. 올려도 수집이 빨라지지 않는다."*
그런데 geo를 대량 소비하는 asset에는 **pool이 붙어 있지 않다.** `concurrency.pools`
(`default_limit: 1, granularity: run`)와 `OPINET_API_POOL`·`KREX_NOTICE_SNAPSHOT_POOL`
이라는 선례가 이미 있는데 쓰이지 않았다.

**그래서 순서가 바뀐다.** 동시성을 *올리는* 것(배치 지오코딩)은 이 호스트에서
악화일 수 있다. 먼저 할 것은 ① geo 중량 asset에 pool을 붙여 **동시 실행을 묶고**,
② reverse/region 왕복을 **따로 세는** 계측을 넣어(오늘 그 수가 이 저장소에도 geo
저장소에도 없다) 분모를 만든 뒤, ③ 그 다음에 벽시계 deadline과 typed 분류를
넣는 것이다. 재시도·동시성 수치는 ②의 실측 없이 고르면 안 된다.

한계도 적어 둔다: pool은 `@asset` 데코레이터에 걸리는데 큐 경로는 그 래퍼를
**우회한다**(`feature_update_runner.py:432-433`). 즉 pool은 예약 경로만 묶는다.

**규모(조사로 정정됨).** MCST는 33,000이 아니라 13 slug 합계 **102,121행**이고,
행 수 1위는 **MOIS 980,970행**인데 그쪽은 단일 트랜잭션이라 90만 번째 행의 timeout이
앞서 적재한 전부를 rollback시킨다. dagster resource가 `region_fallback_radius_km=0.1`을
켜 두어 bjd가 안 나오는 좌표는 **행당 왕복 2회**다.

**OpiNet은 "마지막"이 아니라 "차단"이다.** `providers/opinet.py`도 주유소마다
`await reverse_geocoder(coord)`를 부른다 — 지금 쏘면 일일 쿼터를 태우고 같은
timeout으로 죽는다. 이 수정이 배포된 뒤에 쏜다.

**안전하다고 확인한 것.** MCST는 `retire_absent_from_snapshot`을 넘기지 않고 slug
단위로 커밋하므로 재실행이 안전하다(13개 중 2개 = 33,422행 이미 적재). 등산로는
`mountain_trail_segment`가 **0행**이라 은퇴시킬 것이 없어 지금 도는 run을 끝나게
두어도 파괴적이지 않다.

**runtime 상한이 34개 job 중 21개에 없다** — MOIS·MCST·등산로가 전부 거기 속하고
전역 6시간에만 매달린다. 다만 상한을 일괄로 붙이면 안 된다: MOIS는 순차 130ms ×
98만 = 35시간이라 7,200초를 붙이면 정상 run이 죽는다. 배치화 뒤에 측정해서 정할 것.

---

**이번에 닫은 것 (#1253).** `feature.feature_notices` 0행의 원인이 둘이었다.

1. 변환이 상류의 유일한 위치 단서를 버렸다. `ocrnFrcstIssuInsttNm`을 10,562건
   전수로 재 보니 **98.5%가 행정구역**(97%가 `충청남도 당진시` 꼴)인데
   `landslide_forecast_issues_to_bundles`가 빈 `Address()`를 박았다.
2. **데이터셋이 통째로 사라져도 job은 SUCCESS였다.** 10,467건을 받아 전부 버리고
   notice 0건으로 끝났는데 결과는 초록이었다. 적재율 하한을 두 적재 경로 모두에
   걸었다 — 버린 것이 남긴 것보다 많으면 적재하지 않고 죽는다.

**아직 열린 것.** D2 lane BLOCKED(`admin feature live acceptance: direct fixture
seed failed` — acceptance 하네스, prod 아님), 활용신청 4건(ansan / gyeonggi-muslim /
jeju / special-streets — 소유자 조치).

