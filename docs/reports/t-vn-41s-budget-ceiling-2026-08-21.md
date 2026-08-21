# T-VN-41S — build 예산 vs item 상한: 측정과 결정 (2026-08-21)

`docs/reports/t-vn-41s-1m-soak-2026-08-21.md`가 열어 둔 결정을 닫는다.

## 결정

| 상수 | 이전 | 이후 |
|---|---|---|
| `_SNAPSHOT_BUILD_TIMEOUT_SECONDS` | `300.0` | **`300.0` (유지)** |
| `_SNAPSHOT_BUILD_STATEMENT_TIMEOUT` | `"5min"` | `"5min"` (유지, CI가 예산과 대조) |
| `_SNAPSHOT_ITEM_LIMIT` | `1_000_000` | **`500_000`** |
| `_SNAPSHOT_MATERIAL_BYTE_LIMIT` | `512 MiB` | **`60 MiB`** (아래 §byte 축) |

**예산은 올리지 않는다.** 이 값은 stream share barrier가 유지되는 시간이자 그 stream의
outbox writer가 막히는 최대 시간이다. 올리면 아래 §"도달 가능한 장애"가 커진다.

**상한은 예산에서 유도하지 않는다.** 매력적인 안이었고 네 판정 렌즈 중 셋이 그것을 골랐으나,
반증에서 결정적 결함이 나왔다 — `limit = budget × rate / safety`로 정의하면
`limit / rate × safety ≡ budget`이므로 불변식 단언이 **항등식**이 된다. 예산을 절반으로
내리는 한 줄 변경에서도 CI가 green이고, client가 보는 413 문턱이 조용히 반토막 난다.
그때 PinVi가 받는 413은 `Retry-After`가 없는 terminal 오류라 reconciliation이 영구 정지하는데,
서버 쪽에서는 build가 아예 안 돌아 barrier 지표까지 조용해져 **"조치가 효과 있었다"로 보인다.**
유도식은 drift를 없앤 것이 아니라 **drift 경보를 없앤다.**

그래서 둘을 독립 리터럴로 두고 관계만 CI가 지킨다
(`test_snapshot_item_limit_fits_the_shipped_build_budget`). 처리량도 유도값이 아니라 별도
실측 리터럴이라, 예산을 내리면 그 테스트가 반드시 red가 된다 — 상한 변경을 사람이 보게 만든다.

## 측정

n150(운영 하드웨어), 격리 DB, 대표성 fixture(아래 §fixture).

> **측정 조건 정정.** 아래 세 수치를 잰 시점의 soak은 측정 동안
> `_SNAPSHOT_BUILD_TIMEOUT_SECONDS`를 3,600초로 덮고 session `statement_timeout`도
> 3,600초로 올린 상태였다(적대 리뷰가 잡았다). 따라서 소요 시간 자체는 유효하지만
> **배포 deadline 아래에서 완주가 증명된 것은 아니다** — `_snapshot_build_deadline`이
> 한 번도 돌지 않았다. 그 우회를 제거했으므로 앞으로의 soak은 배포 예산 그대로 돌고,
> 넘으면 그 자체가 실패다.

| N | seed | build | item/s | 예산 300초 대비 | 게이트(≤150초) |
|---|---|---|---|---|---|
| 250,000 | 9.0s | **59.1s** | 4,227 | 20% | PASS |
| 500,000 | 17.8s | **118.3s** | 4,225 | 39% | PASS |
| 1,000,000 | 39.0s | **235.7s** | 4,242 | 79% | FAIL |

`bytes_per_item`(item 표 heap) 182.1~182.3 B, Python peak 2.09 MiB(1M).

### 원래 전제가 재현되지 않았다

앞선 soak 보고서는 1,000,000이 예산을 **68~248초 초과**한다고 적었다(368.4초 / 547.9초).
오늘 같은 코드·같은 호스트·더 넓은 키로 재면 **235.7초**이고, 처리량은 세 지점에서
4,225~4,242로 **선형**이다. 그 보고서 자신이 첫 실행(547.9초)을 "compaction 후보 조건을
좁히기 전 커밋 + 통시 통합테스트 동시 실행"이라며 비-정본으로 못박고 있었으므로, 남는 것은
정본이라던 368.4초 하나인데 그것도 재현되지 않는다.

**그래도 1,000,000을 유지하지 않는다.** 예산의 79%를 쓰는 값은 상한으로 삼을 수 없다.
정렬 키 표현식(`convert_to(normalize(target_key, NFC), 'UTF8')`)에 인덱스가 없어 비용이
Θ(N log N)이고 `work_mem` 절벽이 있으며, 운영에는 항상 다른 부하가 있다. 앞선 보고서의
부하 측정(1,824 item/s = 오늘의 43%)이 재현되는 조건이라면 1,000,000은 548초로 넘친다.
안전계수가 존재하는 이유가 정확히 이 폭이다.

500,000은 118.3초로 예산의 39%, 게이트(예산/2 = 150초)에 21% 여유를 남긴다.
게이트를 만족하는 최대치는 150 × 4,225 ≈ **633,750**이며 500,000은 그 아래 라운드 값이다.

### 운영 규모 대비

prod의 external_system별 cache target 수는 가장 큰 stream(`c7-e2e`)이 **179건**이고 나머지는
전부 1건이다(2026-08-21 실측, 전부 e2e/테스트 stream — 실 PinVi stream은 아직 없다).
500,000은 관측 최대의 **2,793배**다. 즉 이 상한 인하는 실사용을 전혀 좁히지 않는다.
`feature.features` 1,008,852행은 cache target이 아니므로 이 축과 무관하다.

## byte 축 — item 수만으로는 build 시간을 묶지 못한다

`_SNAPSHOT_MATERIAL_BYTE_LIMIT`은 `material_bytes`(= `_leaf_material` 인코딩 길이 합,
`10 + 4 + |system| + 4 + |key| + 1 + 8 + 32`)와 비교한다. heap 크기가 아니다.

| 키 모양 | B/item | 500,000 재료 | byte 상한 발화 지점 |
|---|---|---|---|
| soak fixture 37자 ASCII | 104 | 49.6 MiB | 5,162,220 |
| prod 실측 35자 ASCII | 103 | 49.1 MiB | 5,212,338 |
| 계약 최대 512자 ASCII | 683 | 325.7 MiB | 786,048 |
| 512자 한글 NFC | 1,611 | 768.2 MiB | 333,253 |

`target_key`는 계약상 **512자**까지 허용된다(`validate_cache_target_key`). 그래서 같은
item 수에서도 재료량이 **16배** 흔들리고, build는 그 키로 인덱스 없는 표현식 정렬을 두 번
한다. item 상한만으로는 그 폭 축을 전혀 묶지 못한다.

예전 512 MiB는 실측 재료 처리량 **439,600 B/s**(500,000 × 104 B / 118.3초) 기준
**1,221초 = 예산의 4.1배**라 시간 방어선이 될 수 없었다. 게다가 item 상한을 500,000으로
낮춘 뒤로는 계약 최대 폭에서도 500,000 × 683 B = 325.7 MiB < 512 MiB라 **ASCII stream에서
아예 발화하지 않는 죽은 코드**가 됐다.

**60 MiB**로 조인다. 439,600 B/s에서 143초로 예산 절반(150초) 안이다. 정상 폭 stream은
영향이 없다 — 103 B/item이면 610,820 item에 해당해 item 상한(500,000)이 먼저 걸린다.
즉 이 상한은 **비정상적으로 넓은 키**만 잡는다. 두 축 모두
`tests/unit/test_cache_target_snapshot_repo.py`가 예산 절반 성질을 지킨다.

## 안전계수 2가 넉넉한가

넉넉하지 않다. 이 저장소가 가진 유일한 동시 부하 관측은 앞선 보고서의 1M 547.9초 대
오늘의 235.7초 = **2.32배**다. 상한에 적용하면 118.3 × 2.32 = 274.5초로 예산의 91.5%다.
즉 2배 여유는 그 한 점의 부하 배수에 거의 정확히 소진되며, 폭 축(위 §byte)에는 남는 것이
없다. 그래서 byte 축을 별도로 조였다. 부하 아래 재측정은 남은 숙제다.

## fixture — 예전 측정이 왜 낙관적이었나

예전 fixture는 `'soak-' || lpad(value::text, 8, '0')`로 **13자 ASCII를 삽입 순서대로** 심었다.
build의 정렬 키는 `convert_to(normalize(target_key, NFC), 'UTF8')`이고 **그 표현식에 대한
인덱스가 없다**(models.py·alembic 전수 확인). 따라서 build 한 번에 전체 정렬이 두 번 일어나고,
그 비용은 키 폭과 입력 correlation에 좌우된다. 삽입 순서와 정렬 순서가 일치하는 13자 키는
그 정렬의 **최선 조건**이다 — 즉 그 fixture가 잰 처리량은 하한이 아니라 상한이었다.

prod 실측 `target_key`는 24~36자(평균 35.1, 전부 ASCII)다. 새 fixture는
`'s-' || md5(value::text) || '-' || lpad(value % 100, 2, '0')`로 37자를 만들고, md5가 삽입
순서와 정렬 순서의 상관도 함께 끊는다. `source_payload_fingerprint`도 상수를 버렸다 —
상수 fingerprint는 sha256 입력 지역성과 페이지 압축률을 비현실적으로 좋게 만든다.
`state`는 `deleted`로 둔다: `active` head는 `target_id`가 가리키는 실제
`ops.poi_cache_targets` 행(좌표 계열 CHECK 포함)을 요구해 fixture 비용이 측정 대상을
압도하고, state는 leaf 1바이트라 이 축의 대표성을 해치지 않는다.

넓은 키로 바꾸고도 처리량이 **올랐다**(2,714 → 4,225). 그러므로 예전 수치와 오늘 수치의
차이는 키 폭이 아니라 호스트 상태·커밋 차이에서 온 것이며, 이것이 "한 번의 측정을 계약
상수의 하한으로 쓰지 않는다"는 규칙의 근거다.

## 도달 가능한 장애 — 상한과 무관하게 179건에서도 터진다

상한은 관측 최대의 2,793배라 **발화 자체가 불가능한 숫자**다. 같은 조사에서 실제로 도달
가능한 경로 둘이 나왔고 함께 고쳤다.

1. **writer 무한 대기.** `cache_target_stream_repo.py`의 `_LOCK_STREAM_SQL ... FOR UPDATE`
   경로에 `lock_timeout` 설정이 **0건**이었다 = PG 기본 `0`(무한). snapshot build가 같은
   stream을 예산 전 구간 `FOR SHARE`로 쥐는 동안 writer는 **connection을 문 채** 쌓이고,
   그 pool은 전 endpoint 공유다(`make_async_engine` 기본 `pool_size=5 + max_overflow=10`
   = 15). build 하나가 지도 조회까지 포함한 API 전체를 마르게 할 수 있었다.
   → `lock_timeout = 1s` + typed `stream_busy`(503, `Retry-After: 10`).

   여기서 두 가지를 더 잡았다(적대 리뷰). 첫째, `set_config(..., is_local => true)`는
   statement가 아니라 **transaction** 범위다. 상한을 걸어 놓고 되돌리지 않으면 같은 writer
   transaction의 이후 lock 대기가 전부 그것을 물려받는데 거기에는 handler가 없어
   처리되지 않은 `DBAPIError` → **500**이 된다. 고치려던 것보다 나쁘다. 그래서 상한은
   `lock_stream_row_or_conflict` helper가 **그 문장에만** 걸고 곧바로 `0`으로 되돌린다.
   둘째, `Retry-After`가 lock 대기보다 짧으면 duty cycle이 높아 무한 대기를 고친 효과가
   대부분 사라진다(대기 5초 · 재시도 1초 = 83%). 대기를 1초로 줄이고 재시도를 10초로
   벌려 9%로 만든다.

   그리고 **고친 경로가 하나뿐이면 의미가 없다.** `cache_target_event_repo`의
   `_LOCK_RESULT_STREAMS_SQL`(`FOR UPDATE OF stream`)도 같은 row를 잡는데 `lock_timeout`이
   0건이었고, 그쪽이 오히려 더 유력한 피해자다 — PinVi의 refresh-request 생성이 그 경로다.
   같은 helper를 적용했다.

2. **재시도 폭주.** `snapshot_build_timeout`의 `Retry-After: 1`은 예산을 통째로 태우고 실패한
   요청에 1초 뒤 재시도를 지시한다. 재시도가 즉시 advisory lock을 다시 잡고 같은 예산을 또
   태우므로 그 stream은 barrier를 놓지 않는 **100% duty cycle**로 물린다.
   → `Retry-After`를 예산값으로. 상수를 API에 다시 적지 않도록 infra가
   `snapshot_build_budget_seconds()`를 공개한다.

## 재현

```
# n150, 격리 DB. N을 인자로 준다. 인자 없으면 배포 상한을 그대로 잰다.
KOR_TRAVEL_MAP_PG_DSN=postgresql+asyncpg://.../<격리DB> \
  python scripts/tvn41s_material_soak.py "$PWD" 500000
```

soak은 이제 `build <= 예산 / 2`를 **본 판정**으로 단언한다. 예전의 "정책 결정 대기라 red가
정상" 장치(`known_open`)는 결정이 닫혔으므로 제거했다. `ADMITTED`가 상한과 다르면
`docs_stale`로 알린다 — 상한이 아닌 크기를 잰 결과는 상한을 보증하지 않는다.

## 다음에 이 값을 바꿔야 하는 조건

- 예산을 바꾼다 → `test_snapshot_item_limit_fits_the_shipped_build_budget`이 red가 된다.
  상한을 함께 정하고 **재측정**한다.
- 하드웨어를 바꾼다 / `target_key` 폭이 크게 달라진다 / PG major를 올린다 → 재측정한다.
  500,000 기준 build 118초 + seed 18초라 1,000,000(235초 + 39초) 대비 정기 실행이 현실적이다.
- 실 PinVi stream이 상한의 절반(250,000)에 접근한다 → 그때는 상한이 아니라 **chunked
  snapshot 경로**를 논해야 한다. 지금은 whole-snapshot뿐이라 413이 terminal이다.
