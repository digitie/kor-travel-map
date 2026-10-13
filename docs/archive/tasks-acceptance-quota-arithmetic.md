# tasks-acceptance 아카이브 — `T-VN-QUOTA-ARITHMETIC` (완료)

> `T-VN-QUOTA-ARITHMETIC`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-13).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 4개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-QUOTA-ARITHMETIC

```markdown
- [ ] T-VN-QUOTA-ARITHMETIC — **쿼터에 대해 저장소가 하는 진술 대부분이 근거가 없다**
```

**왜 이 task가 있나.** 형제 저장소 `kor-travel-weather`가 2026-09-12에 정지 원인을
확정했다(커밋 `a0c4dbb`) — 번역하지 않고 인용한다:

> **It was arithmetic, not a hang.** Each external provider swept 1,428 locations with
> one request each, hourly, against free tiers it exceeded by up to **43x**. Throttled,
> a request took **12-17s instead of ~0.3s**, so a *successful* sweep ran **4-13
> hours** — work arriving every hour that takes six to finish can only end one way.

그 뒤 Map을 같은 기준으로 쟀다(3렌즈 감사: 요청량 · 쿼터 · 적합).

**Map의 활성 schedule 산술은 성립한다 — 방어 장치가 아니라 순회 모양 때문이다.**

weather는 **지점당 1요청**으로 훑었다. Map의 상시 고빈도 경로는 전부 집계/bulk
endpoint다 — krex 교통공지 R=2~5, 휴게소 기상 R=1(전국 snapshot), 유가 R≈1,
krforest 3종 R≈1~2. weather와 같은 모양은 KMA 격자 3종뿐이고 그것은 2026-09-09부터
`DISABLED_FEATURE_LOAD_SCHEDULES`로 제거돼 있다. 나머지 27개는 월간이고, 요청당
17초를 대입해도 최악 봉투가 전역 상한의 65%다.

**weather와 구조적으로 다른 것 둘.**

1. **실패 모양.** weather의 vendor는 throttle했다 — run이 *살아서 일하므로* 회수되지
   않고 쌓였다. data.go.kr은 느려지지 않는다: resultCode 22를
   `failure_kind="quota", retryable=False`로 즉시 올린다. Map의 쿼터 초과는 조용한
   큐 포화가 아니라 **시끄러운 즉시 실패**다.
2. **큐 포화가 구조적으로 막혀 있다.** 고빈도·disabled schedule 전부
   `coalesce_active_runs=True`라 한 job이 슬롯 1개를 넘길 수 없다. weather의 "ten runs
   sat STARTED"는 재현되지 않는다 — 재현 가능한 것은 그쪽의 *다른* 증상, **tick이
   생략되고 데이터가 갱신되지 않는 것**뿐이다.

**무엇이 참이면 닫히는가.**

1. [x] **분모가 기록돼 있다.** (2026-09-13) data.go.kr 활용신청 17개 서비스의
   오퍼레이션당 일일 트래픽이 `docs/etl/upstream-quota.md` §2 표에 나눗셈과 함께
   적혀 있다(그 표가 정본이다 — 여기에 수를 복제하지 않는다). 표에 **없는** 넷
   (`krheritage`·`opinet`·`krex`·`mois`)은 data.go.kr 활용신청이 아니라 각자
   포털에 있고 아직 보지 않았다. 그 넷은 분모가 없다.
2. [x] **분자가 있다.** (2026-09-13) upstream 진입점 대부분이 요청을 세고 그 수가
   `upstream_requests_min`으로 metadata에 실린다. **커버리지·면제·부분 계측의
   정본은 `docs/etl/upstream-quota.md` §4**이고 그 수는
   `tests/lint/test_every_fetcher_counts_or_declares_why_not.py`가 선언에 결박한다 —
   여기에 복제하지 않는다(같은 수를 여러 파일에 복제한 것이 적대 리뷰 3·4·5차
   재발의 공통 원인이었다).

   **배선이 없던 것이 이 조문이 오래 열려 있던 이유였다.** fetcher가 generator라
   "세는 자리"와 "내보내는 자리" 사이에 값을 흘릴 인자가 없었다.
   `kortravelmap.dagster.upstream_requests`가 `ContextVar`로 그것을 대신하고
   **실행 경계 넷**이 계수기를 연다 — provider fetcher의 시그니처는 하나도 바꾸지
   않는다. `settings.log_api_calls`는 **지웠다**(읽는 코드가 없었고, 그 표는
   provider 호출이 아니라 Map API로 들어오는 요청을 기록한다).

   **"세지 않았다"는 값을 내지 않는다.** 계수기가 열려 있어도 한 번도 기록되지
   않았으면 key 자체가 실리지 않는다 — 계측되지 않은 경로가 "0번 요청했다"로
   위장하지 못한다. 틀린 0은 읽는 사람을 멈추게 하지 못한다.

   **적대 리뷰 여섯 판이 이 조문을 만들었고 3·4·5차 blocker는 전부 직전 판의
   수정이 만든 것이었다.** 서사는 `docs/journal.md` 2026-09-13. 교훈은 검사기
   쪽이다 — 2차 blocker를 정적 검사가 통과시켰다("계수 호출 자리가 있는가"만
   보므로 루프 밖 1회도 초록). 그래서 층을 나눴다: 정적 검사는 "빠진 진입점이
   없는가"만, 효과는 **가짜 client로 N번 부르게 하고 계수가 N인지 재는** 런타임
   테스트가 본다.
3. [x] **쿼터성 실패가 재시도를 사지 않는다.** (2026-09-13)

   `kortravelmap.dagster.quota_exhaustion`이 예외 연쇄를 걸어
   `Failure(allow_retries=False)`로 바꾼다. 문자열을 파싱하지 않는다. asset 35개 중
   34개가 지나는 `run_tracked_feature_asset`와 multi-member인
   `feature_place_mcst_culture` 둘에 결박하고, 결박 단위는 함수 이름이 아니라
   **`except` 핸들러**다 — 한 함수 안의 두 실패 분기 중 하나만 지워도 초록이던
   첫 판을 적대 리뷰가 잡았다.

   **"4배"는 틀렸다(적대 리뷰 정정).** 쿼터가 소진된 뒤의 재시도는 순회를 다시
   도는 것이 아니라 **첫 격자에서 즉사한다** — 격자 루프는 항상 `grids[0]`부터
   시작하고(성공 cursor는 완주 뒤에만 전진) 그 첫 호출이 곧바로 code 22를 받는다.
   실제로 아끼는 것은 순회 3벌이 아니라 **요청 3건 + backoff 420초 + 큐 슬롯
   점유 3회 + 실패 attempt 기록 3건**이다. 요청이 4배가 되는 것은 순회 *도중*
   나는 **재시도 가능한** 실패(H45가 겨냥한 쪽)이고 이 변경은 그쪽을 건드리지
   않는다.

   **HTTP 429는 제외한다.** provider lib들이 429와 resultCode 22에 같은
   `failure_kind="rate_limit"`를 붙이는데(visitkorea·mcst·krforest 실측) 이
   저장소 schedule 다수가 월 1회라, 429 한 번에 재시도를 끄면 그 asset은 한 달
   갱신되지 않는다. 예외가 든 HTTP 상태로 가른다.

   **`failure_kind`를 붙이는 provider가 절반뿐이다.** airkorea·datagokr·krairport·
   krex·opinet·krheritage·mois·knps는 붙이지 않는다. 속성 하나에만 걸면
   **가장 좁은 분모에서 한 번도 발화하지 않는다** — 에어코리아가 오퍼레이션당
   500/일이다. `QUOTA_EXCEPTION_TYPES`가 `(모듈, 클래스)` 선언으로 그 구멍을
   메우고, contract 테스트가 그 이름이 실물 lib에 실재하는지 형제 소스로 확인한다.

   **여전히 덮이지 않는 것**: `krheritage`는 쿼터 소진을 알려 주지 않는다
   (`RateLimitError`가 클라이언트 측 limiter이고 lib 안에서 raise되지 않는다).
   아래 "krheritage run 하나가 4 × ~3,950 = 15,800요청"은 이 기제로 닫히지 않는다.
   `datagokr`(전국표준데이터, 1,000/일)도 쿼터 전용 예외가 없다. `FEATURE_LOAD_RETRY_POLICY`
   (`max_retries=3`)가 35개 asset 전부에 붙어 있고, asset 경계가 `failure_kind`를
   예외 **문자열에 녹여**(`f"KMA provider refresh failed: {exc}"`) step 층이 분류를
   보지 못한다. code 22는 자정까지 같은 코드를 주므로 재시도의 성공 확률은 0인데,
   쿼터 소진된 KMA run 하나가 **4 × 300 = 1,200요청**, krheritage run 하나가
   **4 × ~3,950 = 15,800요청**을 쓴다.
4. [x] **선언 없는 증폭기가 없다.** (2026-09-13)

   krex `lookback_hours` 48 → 6(호출 한 번의 요청 상한이 `lookback+1`이다),
   krforest 4곳과 visitkorea를 저장소 공통 헬퍼로 옮기고 `absolute_max_pages`를
   줬다. **OpiNet은 무제한이 아니었다** — 라이브러리가 격자 셀 20,000을 넘으면
   호출 전에 거부하고, 총량을 실제로 묶는 것은 하루 한 번 coalescing이다.

   이 과정에서 **저장소 헬퍼 자체의 결함**이 드러났다: `max_pages`는 천장이 아니라
   바닥이었다(`absorb`가 선언 건수에 맞춰 올린다). upstream이 `total_count`를
   거짓으로 크게 말하면 요청 수가 그 숫자를 따라간다. `absolute_max_pages`를
   더해 닫았다.

   **krforest 정당화가 거꾸로였다(적대 리뷰 정정).** 라이브러리는 유도가 실패할 때
   10,000페이지로 폭주하는 것이 아니라 **1페이지로 조용히 잘린다** — 응답에
   `totalCount`가 없으면 `_http.py`가 `total_count = len(items)`로 채워 추정치가
   1이 된다. 그리고 **저장소 헬퍼로 옮겨도 그 절단은 그대로다**(2026-09-13 실측:
   2,500행 dataset에서 1,000행에서 멈춘다). 종료 규칙을 바꾸면 범위 밖 page에
   예외를 던지는 provider에서 새 실패가 생기므로 고치지 않고 **경고로 들리게** 했다.
   실제 위험은 쿼터 폭주가 아니라 **행 누락이 성공으로 보이는 것**이다.

   **krex의 "시끄럽게 실패"도 없었다(적대 리뷰).** 빈 Page는 예외가 아니라 정상
   반환이고, 적재 경로에 빈 가드가 없어 0행이 `record_sync_success`까지 가서
   `consecutive_failures`를 0으로 되돌렸다. `KrexRestAreaWeatherUnavailable`을
   더했다 — 그 fetcher에는 테스트가 하나도 없었다.

   **visitkorea 라이브러리에서 잃은 '전진하지 않는 페이지네이션' 가드**도
   `ProviderPage.fingerprint` + `ProviderPaginationStalled`로 헬퍼에 복원했다. 세 곳이 Map 코드에서 1줄로 보이는데 provider
   안에서 팬아웃한다 — 휴게소 기상 `latest_weather()`가 최대 **49요청**
   (`lookback_hours=48`), krforest 3종이 `max_pages` 미지정으로 lib 상한 **10,000
   page**, OpiNet bbox/poi_cache_target 모드가 예산 미전달로 무제한.
5. [x] **UI가 근거 없는 보증을 하지 않는다.** (2026-09-13 — `_schedule_note`가
   비율 대신 실측 표를 가리킨다. `tests/lint/test_quota_claims_have_a_denominator.py`가
   비율 주장이 돌아오면 빨개진다.) admin의 schedule note가 두 갈래 모두
   "rate limit의 약 90% 이하를 목표로 한"을 돌려주는데, 그 90%의 분모는 31개
   schedule에 대해 존재하지 않는다. **그 화면이 운영자가 cron을 올리는 화면이다.**
6. [x] **KMA 격자 재활성화의 전제조건이 적혀 있다.** (2026-09-14)
   전제조건과 그 수는 `docs/etl/upstream-quota.md` §3이 정본이다 — 여기 복제하지
   않는다. 조문이 요구한 것은 전부 들어왔다: 오퍼레이션별 분모(§2), 세 오퍼레이션이
   쿼터를 공유하지 않는다는 사실, **G = 59**(2026-09-13 prod 실측), 증폭기 선언
   (조문 4), 쿼터성 실패가 재시도를 사지 않는다는 것(조문 3 — 조문 6이 스스로 적은
   전제다), 그리고 켠 뒤 비율을 확인할 분자(조문 2).

   **조문 본문이 이미 끝난 측정을 "남은 것"으로 적고 있었다** — "남은 것은 G 실측"은
   같은 절의 표가 같은 날 G=59로 답했고, 헤드라인 72%/72%/24%는 반증된 G=300 열이다.
   낡은 조문 하나로 task가 열려 있었다.

   **2026-09-14 지시로 KMA·에어코리아는 쿼터 평가 대상에서 빠졌다**(§3 참고) —
   재활성화는 그 지시를 되돌리는 일이지 이 조문이 판단할 것이 아니다.

   (원래 조문) "24×300×2 + 8×300 = 16,800요청/일 → 1.68배"는 **분모를 잘못 잡은
   것**이었다(오퍼레이션마다 따로 걸린다). "초과분은 다음 run으로"도 거짓이었다 —
   코드는 `KmaWeatherGridLimitExceeded`로 전면 실패한다.

**바꾸기 전에 측정해야 하는 것.** 이 task의 절반은 코드가 아니라 숫자였다.

| 무엇 | 어떻게 | 상태 |
|---|---|---|
| 각 활용신청의 일일 한도 | data.go.kr 마이페이지 → 활용신청 상세 | **2026-09-13 실측** |
| `VilageFcstInfoService_2.0`의 3 operation이 한 통을 공유하는가 | 같은 화면 | **공유하지 않는다** |
| G = 실제 KMA 격자 수 | `ops.poi_cache_targets`의 활성 target을 `kma.grid.to_grid`로 dedupe | **G = 59** (2026-09-13 prod) |
| dataset별 선언 건수 | 각 endpoint에 `pageNo=1&numOfRows=1` 1요청 | 미측정 |
| Map이 throttle 구간에 들어간 적이 있는가 | Dagster run 지속시간 분포 + asset metadata | 미측정 |

### 2026-09-13 실측 — 분모를 얻었고, 그것이 조문 6의 전제를 뒤집었다

**일일 트래픽은 서비스가 아니라 오퍼레이션마다 따로 걸린다.** 활용신청 상세의
"상세기능" 표에 오퍼레이션마다 "일일 트래픽" 열이 있다. `기상청_단기예보
조회서비스`는 `getUltraSrtNcst` / `getUltraSrtFcst` / `getVilageFcst` /
`getFcstVersion` **넷이 각각 10,000/일**이다. 전체 표는
`docs/etl/upstream-quota.md`.

그래서 조문 6의 "한 활용신청에 16,800요청/일 → 1.68배"는 **분모를 잘못 잡은
것**이었다. 오퍼레이션별로 다시 세면:

| schedule | 오퍼레이션 | G=300(상한)일 때 | G=59(오늘 실측)일 때 | 한도 |
|---|---|---:|---:|---:|
| `..._ultra_short_nowcast_hourly` (`45 * * * *`) | `getUltraSrtNcst` | 7,200 (72%) | **1,416 (14%)** | 10,000 |
| `..._ultra_short_forecast_hourly` (`50 * * * *`) | `getUltraSrtFcst` | 7,200 (72%) | **1,416 (14%)** | 10,000 |
| `..._short_forecast_hourly` (`20 * * * *`, cursor skip) | `getVilageFcst` | 2,400 (24%) | **472 (5%)** | 10,000 |

**세 schedule은 서로의 쿼터를 먹지 않는다.** 합산해서 터지는 그림이 아니다.

**그리고 300은 상한이지 대상 수가 아니었다.** prod 실측: `ops.poi_cache_targets`가
**0행**이고(파괴적 rebuild 직후, PinVi 미등록) `KMA_WEATHER_EXTRA_POINTS`의 60점이
DFS 격자로 dedupe되어 **G = 59**다. 오늘 KMA를 다시 켜는 것은 쿼터 관점에서
넉넉하다 — 4배 배수를 전부 얹어도 57%다.

**그런데 72%는 여유가 아니다.** 조문 3의 4배 배수가 여기에 곱해지면 한 번의
재시도 순환이 그 run을 300 → 1,200으로 만들고, 하루 세 번이면 9,900으로 한도에
닿는다. 즉 재시도는 쿼터 초과의 *결과*가 아니라 *원인*이 될 수 있는 구간에 이미
들어와 있었다. **조문 3을 닫는 것이 조문 6의 전제조건이다.**

가장 좁은 자리는 KMA가 아니다 — 에어코리아 **500/op/일**, 전국\*표준데이터와
visitkorea 전부 **1,000/op/일**이다.

`krheritage`(국가유산청) · `opinet` · `krex`(도로공사) · `mois`/`localdata`는
data.go.kr 활용신청이 **아니라서** 이 화면에 없다. 그쪽 분모는 여전히 미측정이고,
"krheritage run 하나가 15,800요청"의 분모도 그래서 아직 없다.

**측정 전에 상한 숫자를 바꾸지 않는다**는 원칙은 유효했다. 분모를 몰라도 정당한
것 — 폭주 상한, 재시도 배수 제거, 분자 만들기, 오도하는 문구 지우기 — 만 먼저
했고, 그 사이에 분모가 들어왔다.

### 2026-09-13 prod 배포 (t41a) — 전 사이클 GREEN

`chain17.sh`로 sanctioned 재핀 사이클을 돌렸다(`0b60a850` = #1227 머지 커밋).

```
A. 회전 preflight     OK (OpenAPI 표면 3종 digest 동일)
B. 회전               49번째 · pinset bae61363a6fdd7ff
C. rebuild            success · phase=committed
                      heads 3종 불변 → 마이그레이션 없음이 실측으로 확인됨
0. 핀 원장 대조        map=0b60a850 ✓ pinvi=f62e7ef1 ✓
C. executor 이미지     success · 라벨=0b60a850…
D. repin              repository_commit=0b60a850… · VERIFIER PASS
                      attestation_sha256=10fd0f1f…
E. M01 ACL preflight   failed 0 / total 55
F. D1 (live Playwright) 11 passed (26.0s)
G. lane 정리           BLOCKED 없음
H. D2                 phase=passed · status=complete · recovery_attempt=0 · 잔여물 0
```

배포 뒤 **새 세대에서 run 완주 게이트(#1226)가 15/15 통과**했다 — 탐침 run이 실제로
SUCCESS로 완주했고 필수 daemon 4종이 전부 fresh, 멈춘 run 0건이다.

**UI에서 실제로 바뀐 것**: prod API 컨테이너가 돌려주는 schedule note가
"provider rate limit의 약 90% 이하를 목표로 한 …"에서
"이 저장소가 고른 …기본값입니다. upstream 일일 한도 대비 소비량은 schedule마다
다릅니다 — 실측 한도는 docs/etl/upstream-quota.md에 있습니다."로 바뀌었다.
32개 schedule에 똑같이 붙던 근거 없는 비율이 화면에서 사라졌다.

**배포 경로에서 배운 것 둘.** (1) host-direct `docker compose build`는 이제 쓸 수
없다 — 대상 서비스만 빌드해도 compose 파일 **전체**를 보간하는데 prod `.env`에
다른 서비스(concierge)의 키가 없다. sanctioned 경로(`run-pinned-rebuild-once`)는
Manager가 env를 통째로 구성해 넘긴다. (2) prod postgres는 소켓 기본 경로가 아니라
`127.0.0.1:12700`이고 백업 대상은 `$POSTGRES_DB`(=postgres, 7MB)가 아니라
애플리케이션 DB `kor_travel_map`(44MB)이다.
