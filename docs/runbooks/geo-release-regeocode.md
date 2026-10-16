# geo 릴리스 재지오코딩 운영 runbook

kor-travel-geo가 새 주소 데이터셋(새 `data_token`)을 서빙하면 Map은 geo 유도 값(법정동·행정동·시군구 코드 등)을
가진 dataset을 다시 적재해 낡은 해석을 고친다. 결정과 근거는 [ADR-109](../adr/109-geo-release-regeocode.md), 코딩용 상세(표·
판정 규칙·run_key)는 [`etl/address-geocoding.md`](../etl/address-geocoding.md)가 정본이다. 이 문서는 **운영 절차**만 갖는다.

## 1. 흐름 한 장

```
geo 활성화(새 data_token)
  └─ kor_travel_geo_release_sensor (300초, 기본 STOPPED) 또는 admin UI "지금 감지"
       └─ plan_geo_release(같은 함수) ── 첫 토큰 → 기준선 행(계획 0)
            │                         ├─ 같은 토큰의 활성 계획 → 그대로(멱등)
            │                         └─ 새 토큰 → 계획(plan_seq) + 항목(= Dagster run 1개씩)
            └─ tick마다: 진행 중 run 1개 정산 → 다음 대기 항목 1개 RunRequest(태그 geo_release_plan_id)
                 └─ 전용 feature-load job이 적재 경로로 다시 변환·지오코딩 → 스탬프(geo_data_token) 전진
                      └─ 항목이 전부 끝나면 완료 판정: 잔여 있으면 sweep 1회 → residual_stale 기록
                           → 활성 cache target의 same_sigungu 링크 재동기화 → done
```

- 항목 1행 = run 1개다(MCST는 dataset 13개가 run 1개, KNPS는 dataset마다 run_config가 달라 항목 5개).
- 쿼터 민감 9개 operation(datagokr 축제·standard_data 4종·fileData 4종)은 `source_mode=replay` — provider를 다시 부르지
  않고 저장된 원본으로 다시 변환한다. 자동 적재를 끈 넷은 계획에서 `skipped(disabled)`다.
- **MOIS는 센서가 내지 않는다**(아래 §4). 항목 사유가 `replay_not_launchable_before_t_gr_08`로 보이지만(OpenAPI enum 불변을
  위해 재사용한 값) 화면은 "수동 실행 후 skip 필요"로 보인다.
- 화면: admin UI `/admin/ops/geo-releases`(현재 토큰·계획·커버리지·항목·건너뛰기·다시 계획·지금 감지). API는
  `/v1/ops/geo-releases`(admin 프로필).

## 2. 배포 순서

geo `data_token` backfill(geo ADR-069) → PinVi admin 스냅샷 재vendor(Map admin OpenAPI가 바뀐 PR이면 Map API 배포 **전**) →
Map pair 배포(migration 407·408·409, 센서는 STOPPED로 들어간다) → Manager `dagster.yaml` concierge lane(concierge ADR-49
refresh job용 — Map 변경 아님) → concierge. Map 배포는 coordinator가 chain17로 한다.

## 3. 센서를 켜기 전에 확인할 것

1. **geo가 토큰을 낸다** — `/admin/ops/geo-releases` 현재 상태가 "정상"이고 `data_token`이 `dd1-…`다. "data_token 없음"(빨강)이면
   켜도 계획 없이 Skip만 한다(§6).
2. **기준선이 있다** — 계획 목록 맨 위가 지금 토큰의 `기준선` 행이다. 없으면 "지금 감지"를 한 번 눌러 기준선을 기록한다
   (첫 토큰은 계획을 만들지 않는다 — §5 FAQ).
3. **odroid geo 부하** — 소유자 지시: odroid geo의 mv_refresh 실측이 끝난 뒤에 켠다(센서 기본 STOPPED의 이유).
4. **큐 worker가 놀고 있다** — `feature_update_request_worker` run이 돌면 센서는 그 tick을 Skip한다. 대량 큐 작업 중에는
   켜도 진행이 없다.
5. **MOIS 이어 달리기 센서**(`feature_place_mois_licenses_continuation_sensor`) 상태를 안다 — §4의 MOIS 수동 실행이 예산을
   넘기면 이 센서가 잇는다. 릴리스 run(태그 `geo_release_plan_id`)은 이 센서가 건너뛴다(이중 체인 방지).
6. n150 변경 전 `~/preflight.sh` PASS(운영 규칙).

켜기: Dagster UI → Automation → `kor_travel_geo_release_sensor` → Start. 끄면 진행 중 run은 끝까지 돌고 다음 항목만 멈춘다.

## 4. MOIS: 수동 실행 후 skip

MOIS는 replay가 없다(원본 `raw_data`가 record 1:1이 아니다 — ADR-109 결정 7 결과). fetch를 센서가 자동으로 내면 릴리스
시점에 전국 Phase A sync와 50만 행 변환·snapshot 은퇴가 예정 없이 돈다. 그래서:

1. 계획에 MOIS 항목(`feature_place_mois_licenses_job`)이 "수동 실행 후 skip 필요"로 남는다. 그동안 계획은 `running`이다.
2. 운영자가 정한 시각에 MOIS job을 run_config 없이 수동 실행한다(Map API "지금 실행" 또는 Dagster launch). 예산을 넘기면
   이어 달리기 센서가 잇는다(§3-5). 스탬프 없는 payload-bjd 행은 이 run이 reverse 없이 `not_called`로 찍는다.
3. **쿼터 주의**: MOIS fetch는 소스 DB가 TTL(`KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS`) 안이면 data.go.kr을 부르지 않지만
   TTL이 지나면 증분 Phase A sync가 `apis.data.go.kr`를 부른다 — TTL ≥168h 권고([`mois-license-feature-etl.md`](../etl/mois-license-feature-etl.md) §13.3).
4. 마지막 run이 `complete`면 화면에서 MOIS 항목을 **건너뛰기**한다 — 그래야 계획이 완료 판정으로 간다. 건너뛴 dataset은
   커버리지 분모에서 빠지고 `skip 제외`로 보인다(MOIS 스탬프 자체는 수동 run이 이미 찍었다).

## 5. FAQ — 첫 토큰은 왜 계획 0건인가

소유자 결정(2026-10-15): geo `data_token`이 '없음'에서 첫 토큰으로 바뀌는 것(지문 backfill·dump 복원)은 **기준선**이지
재계획 사유가 아니다. 그 토큰을 `기준선` 행으로 기록할 뿐 계획을 만들지 않는다. 스탬프 없는 행은 평소 적재가 채운다
(스탬프 부재 = stale은 적재 경로 규칙). 계획은 기준선 이후 토큰이 **바뀔 때**만 생긴다.

## 6. 증상별 대응

| 증상 | 의미 | 할 일 |
|---|---|---|
| 현재 상태 "data_token 없음"(빨강), 센서 Skip "geo data_token 없음 — 지문 backfill/복구 필요" | geo가 지문을 내지 않는다 | geo 쪽 backfill/복구(geo ADR-069). Map은 기다린다 — 계획을 만들지 않는 것이 정상 |
| "응답 없음" | geo 장애·미설정·활성 릴리스 없음 | geo 상태 확인. 센서는 커서를 바꾸지 않고 Skip |
| 항목 `실패 · run 미기동`(`run_not_launched`) | RunRequest 뒤 900초(3 tick) 동안 run이 없었다 | Dagster run 큐·동시성 확인 뒤 **다시 계획**(최종 상태라 자동 재시도 없음) |
| `실패 · 진척 없음`(`no_progress`) | MOIS 이어 달리기에서 변환 0건(정지 규칙) | MOIS run 로그 확인. 원인 해소 뒤 수동 실행(§4) |
| `실패 · run 실패`(`run_failed`) | 비-MOIS run이 1회 자동 재요청 뒤에도 실패 | run 로그. `ReplayIncomplete`/`ReplayPayloadDrift`면 §7 |
| `실패 · run 취소`(`canceled`) | 운영자가 run을 취소했다(재요청 안 함) | 의도였으면 건너뛰기, 아니면 다시 계획 |
| `실패 · 대체된 계획`(`superseded`) | 새 계획이 이 계획을 닫았다 | 할 일 없음 — 새 계획을 본다 |
| 계획이 오래 `running` | 대개 MOIS 항목이 수동 대기 중 | §4 |
| 센서 Skip "feature update 큐 worker run … 진행 중" | 큐 run과 겹침 회피(전역 잠금 대기로 pool을 쥐지 않게) | 큐가 끝나면 저절로 진행 |
| `/admin/issues`에 stale 주소 finding이 replay 뒤에도 남음 | replay는 sync 성공·stale-close를 하지 않는다 | 정상 — 다음 fetch run이 닫는다 |

**다시 계획(replan)**: 계획 상세의 "다시 계획"(또는 `POST /v1/ops/geo-releases/{plan_id}/replan`) — 같은 토큰으로 `plan_seq + 1`
새 계획을 만들고 지금 활성 계획은 `superseded`. **최신 관측 토큰의, 기준선이 아닌 계획만** 된다(그 외 409). 누를 때마다
계획이 하나 더 생기고 그만큼 run·쿼터를 쓴다.

## 7. replay 실패 대처

- **`ReplayIncomplete`** — 읽은 원본 수가 그 dataset의 active entity 수와 다르거나(빈 읽기 포함), 변환 결과가 읽은 레코드를
  다 덮지 않았다. 흔한 원인은 **건수를 센 transaction과 페이지 읽기 사이에 같은 dataset이 바뀐 경쟁**(같은 dataset의 fetch·
  큐 run과 겹침)이고 재시도로 풀린다(센서가 1회 자동 재요청). 계속되면 head·record 누락이다 — `/ops/consistency`에서
  orphan source entity를 확인하고, 그 dataset을 fetch 모드로 한 번 수동 적재한 뒤 항목을 건너뛴다.
- **`ReplayPayloadDrift`** — 되살린 record의 payload hash가 저장값과 다르다(원본 → record 복원이 1:1이 아니다). 적재 전에
  멈췄으므로 데이터는 그대로다. 그 dataset을 fetch로 수동 적재하고 항목을 건너뛴 뒤, 코드에서 replay 목록
  (`REPLAY_RECORDS_RESOURCES`)에서 빼는 이슈를 연다.
- replay run은 sync state·curation seal을 쓰지 않는다 — dataset의 "마지막 성공"은 replay로 바뀌지 않는다.

## 8. 검증 지표

- 계획 상세 커버리지: **계획 토큰 스탬프**(`stamped_current / total_provider_with_coord`)가 오르고 `다른 토큰`·`스탬프 없음`이
  0으로 간다. `geo 미호출`(`not_called`, provider 코드만 쓴 행)·`skip 제외`·`provider 밖`은 표시만 한다.
- 완료 뒤 `residual_stale`이 남았으면 sweep 1회로도 못 고친 행이다 — 다시 계획은 운영자 판단.
- 값이 바뀐 행만 `row_revision`이 전진한다(값 동일은 스탬프만) — ETag·cache target 무효화가 그만큼만 일어난다.

## 9. 롤백 A → B → A

geo가 B를 활성화했다가 A로 되돌리면: 감지가 A를 다시 본다. 계획 표의 최신 행은 B이므로 "A는 이미 끝났다" 규칙에 걸리지
않는다. A 기준 잔여(`stamped_other + unstamped`)가 있으면 **새 `plan_seq`**로 A 계획을 만들고(B가 다시 찍은 행을 되돌린다),
없으면 계획 없이 B의 활성 계획만 `superseded`로 닫는다. 어느 쪽이든 B 계획이 활성으로 남지 않는다. run_key에 `plan_seq`가
들어 있어 두 번째 A의 run은 첫 번째 A의 run과 겹치지 않는다(Dagster run_key 영구 dedupe와 충돌 없음).
