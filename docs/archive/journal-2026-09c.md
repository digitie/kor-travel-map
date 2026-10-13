# journal 아카이브 — 2026-09-14 ~ 2026-09-15

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-09-15 — t44a 배포: async 이관이 prod에서 도는 것을 읽었다

`#1235`(provider 13개 async-only)를 `e9b877b39`로 핀했다. 전 사이클 GREEN — 회전
(pinset `bbb330689e38`) · rebuild `phase=committed` · executor 이미지 · repin
**VERIFIER PASS** · M01 ACL **55/55** · **D1 live Playwright 11 passed** · lane 정리 ·
D2 `phase=passed`(`recovery_attempt=0`).

D2의 `host_attestation_sha256`이 repin 단계의 값(`c564e786…`)과 **같다** — 검증된 그
이미지가 그대로 돌았다는 뜻이다.

**배포가 초록인 것과 고친 것이 그 안에 있는 것은 다른 사실이다.** 그래서 이번에도
prod 컨테이너에서 직접 읽었다. **버전 문자열로는 판별되지 않았다** — provider 13개가
전부 `0.1.0`이라 핀이 바뀌었는지 알 수 없다. 그래서 **코드의 성질**을 물었다:

| 무엇 | prod 실측 |
|---|---|
| `krex.DEFAULT_MAX_RPS` / 버킷 capacity | **5.0 / 1.0**(버스트 없음) |
| `KrexClient.close` 존재 | **False** — 동기 표면이 사라졌다 |
| `restarea.list_all`·`aclose`·`mois.sync_localdata_source_db`·`kma forecast.now`·`airkorea.stations` | **전부 coroutine** |
| fetcher 32개 | **async generator 31** + `fetch_mois_license_records` 1(로컬 SQLite라 동기가 맞다) |
| `PROVIDER_RATE_GATES` | `{'krex': 0.2}` — 교대 간격 1/5초 |
| gate 선언 operation | **4건**(krex place·price·weather·notice) |
| gate가 `__call__`에 있나 / 계수기보다 바깥인가 | **True / True** |
| 큐가 건너뛰는 operation | **6**(종전 값 유지) |
| opinet 예산 | **140 / 90**(종전 값 유지) |

`T-VN-KREX-TPS-FANOUT` 조문 4가 이것으로 닫힌다 — **gate가 prod 실행 경계에 실제로
있다.** 조문 3(`provider_refresh_policies.max_concurrent` 집행)은 그대로 열려 있다.


## 2026-09-15 — provider 13개가 async-only가 됐고, 낡은 대역이 세 번 계약 파손을 가렸다

형제 `python-*-api` **13개 전부**가 native async only + 공유 TPS 제어로 재작성됐다.
동기 HTTP bridge·`Async*` 별칭·`aio()`가 사라졌고 모든 네트워크 메서드가 코루틴,
정리는 `aclose()`다. 핀을 올리고 Map을 맞췄다.

**어제 만든 krex TPS 브랜치는 upstream에 흡수됐다.** 새 라이브러리가 그 기본값
(`max_rps=5.0`, `capacity=1` — 버스트 없음)과 검증(`NaN`/`inf`/`bool` 거절)을 그대로
갖고 있다. 실측 확인: 8건 동시 최소 간격 0.2004초, 최악 1초 창 5건. 루프 결박 문제는
**async-only로 가면서 원인 자체가 사라졌다**(`_run_sync`가 없어졌다). 머지하지 않고
접는다 — 남길 것은 코드가 아니라 그 판에서 배운 것이다.

**반대로 Map 쪽 `provider_rate_gate`는 살아남는다.** 새 `rate_limiter=` 주입은 한
이벤트 루프 안에서만 성립하고, Map의 fan-out은 프로세스를 가로지른다.

### 내가 틀린 곳 하나

`kma_weather.py`를 "로컬 헬퍼만 쓰니 무변경"이라고 단정했다 — **grep 결과 앞부분만
보고** 그랬다. 실제로는 결함이 셋이었다:

1. `forecast.now/short/vilage`를 `await` 없이 호출.
2. 코루틴 함수를 `retry_upstream_async`에 넘김 — 그 함수는 `return call()`이라 코루틴
   **객체**를 돌려주고 **그 안의 예외를 재시도가 한 번도 보지 못한다.** 재시도가 사라진
   줄도 모르게 사라진다.
3. 정리가 `close`를 찾는데 실물엔 `aclose`뿐 — 가드가 조용히 통과해 세션이 샜다.

같은 3번 모양이 `feature_update_runner._close_method`에도 있었다. 같은 client의
schedule 경로는 고쳐졌는데 direct/admin 경로만 남아 있었다.

### 낡은 대역이 계약 파손을 가린 세 자리

소스만 바꾸면 40곳이 `TypeError`로 죽는다. 그건 시끄러워서 낫다. **문제는 조용히
통과하는 자리다.**

| 자리 | 무엇이 가려졌나 |
|---|---|
| krheritage | `await`를 빼도 초록 — 250건이 코루틴 객체로 나가는데 단언이 **개수만** 봤다 |
| opinet | fake의 `**_kwargs`가 kwarg 이름 변경을 삼켰다. 실물은 `TypeError` 뒤 조용히 기본 반경 5000m로 떨어질 자리 |
| mcst | 상한이 1이라 row 수 == slug 수 — "slug당 1건"과 "row당 1건"이 같은 수였다 |

**필수 인자만으로는 부족하다** — 기본값이 있는 인자일수록 구멍이 넓다. 셋 다 변이로
빨강을 확인하고 닫았다.

### drift 하나를 더 닫았다

gate의 교대 간격(`1/5`초)과 라이브러리의 `DEFAULT_MAX_RPS`(5)가 서로를 모른 채 각자
`5`를 들고 있었다. Map은 `max_rps`를 넘기지 않으므로 **라이브러리 기본값에 의존한다** —
그쪽이 바뀌면 gate가 조용히 틀린 값이 된다. 형제 소스를 AST로 읽어 둘을 결박했고,
**양쪽 변이**(gate만 바꾸기 / 라이브러리만 바꾸기)로 잡히는 것을 확인했다.

### 판정은 격리가 아니라 기준선으로

dagster 세션 **680 passed / 10 failed**. 같은 하네스로 HEAD를 돌리니 **675 passed /
같은 10 failed** — 실패 집합이 바이트 단위로 동일하고 통과만 5건 늘었다. 남은 10건은
dagster 버전 환경 문제다.


## 2026-09-14 — 분모가 없는 provider를 분모 없이 막았다 (krex TPS 5)

`krex`의 일일 한도는 포털 네 면 어디에도 없었고 남은 길은 문의였다. **기다리는 대신
축을 바꿨다** — 이 provider에서 실제로 조일 수 있는 것은 하루 총량이 아니라 간격이다.
`python-krex-api` `feat/http-tps-limit`이 `KrexHttp`에 token bucket을 넣어 **초당
5건**을 넘기지 않는다(`max_rps` 기본 `5.0`).

**세 번, 그냥 두면 틀렸을 자리가 있었다.**

1. **처음 만든 것은 5 TPS가 아니라 10 TPS였다.** capacity를 `max_rps`로 두면 가득 찬
   버킷에서 5건이 즉시 나가고 그 초에 지속분 5건이 더해진다. 테스트가 창의 **시작점**만
   보고 있어서 초록이었다 — 어느 1초 창이든 보게 고치니 빨개졌다. capacity=1로 낮췄다.
2. **락이 아무것도 막지 않고 있었다.** `asyncio.Lock`을 썼는데 `_run_sync`는 호출마다
   새 이벤트 루프를 만들고 러닝 루프가 있으면 **별도 스레드**에서 돈다. asyncio 락은
   스레드를 전혀 막지 못하면서 막는 것처럼 읽히고, 경합하면 처음 본 루프에 묶여 다음
   루프에서 `RuntimeError`를 낸다(3.14에서 재현 확인). 임계구역 안에서 await하지
   않으므로 `threading.Lock`으로 바꿨다. **동시 호출에서 상한이 지켜지던 것은 락 덕이
   아니라 GIL 덕이었다** — 재는 것과 지켜지는 것이 달랐다.
3. **`KrexClient`가 `max_rps`를 넘기지 않았다.** 버킷이 transport에만 있어서, client만
   쓰는 호출자는 더 낮춰야 할 때 낮출 방법이 없었다. 두 facade 모두에 넣었다.

검사기는 **일곱 변이**로 확인했다 — 상한 끄기 / capacity 되살리기 / 기본값 바꾸기 /
acquire를 재시도 루프 밖으로 / client 미전달 / go 포털만 우회 / 우회하는 새 전송 자리
추가. 각각 다른 테스트가 잡는다. 마지막 것만 AST다: `session.get(...)` 자리가 하나임을
본다. **효과 검사는 지금 있는 경로만 본다 — 새 전송 경로는 아무 테스트도 건드리지 않고
상한을 비켜 간다.** 이 저장소가 분자에서 이미 겪은 형태다(#1229 → #1231).

ruff clean · mypy strict clean · pytest **91 passed**(live 5 deselected).

**그리고 네 번째로 틀린 것은 Map 쪽 결론이었다.** "큐 러너가 scope를 순차 처리하므로
합계 5 TPS"라고 적었는데, 전문 리뷰어 둘이 **독립적으로 같은 자리**를 짚었다. 그
순차성은 run **하나 안에서**의 이야기다:

| 자리 | 값 |
|---|---:|
| 큐 센서 틱당 RunRequest | **10** (`RUNNING`, 15초 틱) |
| `dagster.yaml` `max_concurrent_runs` | **10** |
| `tag_concurrency_limits[…request_id]` | **4** |

request마다 run_key가 다르니 worker run 넷이 동시에 뜨고, run마다 프로세스가 다르니
`KrexClient`도 버킷도 넷이다 → **최대 20 TPS.** 직렬화하는 것이 아무것도 없다:
실행 advisory lock은 request id와 scope key에 걸려 scope가 다르면 둘 다 진행하고,
Dagster pool `KREX_NOTICE_SNAPSHOT_POOL`은 **asset**에 선언됐는데 큐 경로는 asset
wrapper를 우회하며, `ops.provider_refresh_policies.max_concurrent`는 plan payload에
**실리기만 하고 아무도 그 값을 보고 멈추지 않는다.**

**닫혔다고 적은 구멍이 현재 설정으로 열려 있었다.** 배포가 초록인 것과 고친 것이 그
안에 있는 것이 다르듯, **라이브러리가 막는 것과 시스템이 막는 것도 다르다.** 지금
보증되는 것은 "프로세스당 5 TPS"다. 남은 작업은 `T-VN-KREX-TPS-FANOUT`.

**아직 Map에 들어오지 않았다** — krex 핀은 `c6d8717e…` 그대로다(`ddd69cd2`는 그 전
값이다 — 처음에 그것을 적었다). krex PR 머지 후 repin이 따라온다.

## 2026-09-14 — t43a 배포, 그리고 고친 것이 prod에서 살아 있는 것을 봤다

`#1231`·`#1232`·`#1233`을 `e3fddce81`로 핀했다. 전 사이클 GREEN — 회전
(pinset `6ff11b3b6520d05b`) · rebuild `phase=committed` · executor 이미지 ·
repin **VERIFIER PASS** · M01 ACL **55/55** · **D1 live Playwright 11 passed** ·
lane 정리 · D2 `phase=passed`.

**배포로 끝내지 않고 고친 값을 prod에서 읽었다:**

| 무엇 | 종전 | prod 실측 |
|---|---:|---:|
| `opinet_run_call_budget` | 600 | **140** |
| `opinet_low_top_max_calls` | 180 | **90** |
| 큐가 건너뛰는 operation | 0 | **6** |

배포가 초록인 것과 **고친 것이 그 안에 있는 것**은 다른 사실이다. 이 판에서 그
구분을 여러 번 배웠다 — 목록에 이름을 올린 것과 그 이름을 읽는 실행 경계가 있는
것이 달랐고(#1231), 분자를 세는 것과 그 수가 실릴 자리가 있는 것이 달랐다(#1229).

## 2026-09-14 — "이관됐다"가 "옮겨야 한다"는 뜻은 아니었다 (MOIS)

`mois`/localdata 분모를 보러 갔다가 네 번 생각을 바꿨다. 그 순서를 적는다 — 각
단계에서 내가 무엇을 근거로 틀렸는지가 내용이다.

**1. "사이트가 죽었다".** `www.localdata.go.kr`가 WebFetch 2회·브라우저 2회 내내
뜨지 않았다. 그래서 "확인 실패"로 적었다.

**2. "라이브러리가 깨졌다".** 사용자가 "웹사이트 디자인 변경 때문일 수 있으니 확인 후
이슈 있으면 라이브러리 수정"이라고 했다. 보니 라이브러리는 `www`가 아니라
`file.localdata.go.kr`를 쓴다 — **다른 호스트**다. curl로 쳤더니 302 → `/error.html`
→ **403**. "깨졌다"고 적었다.

**3. 그런데 깨진 것은 내 curl이었다.** Referer를 붙이니 200이었다. 그리고 라이브러리
소스를 보니 **이미 Referer를 보내고 있었다.** 실제로 라이브러리 경로를 그대로 실행하니
info 200 · validate 200이다. 내 재현이 라이브러리와 달랐던 것이지 라이브러리가 틀린
것이 아니었다. **호출을 흉내 내지 말고 그 호출을 시켜 봤어야 했다.**

**4. "data.go.kr로 이관됐다"(사용자).** 그러면 파일 호스트를 계속 긁는 것은 레거시에
매달리는 것처럼 보였다. 그래서 두 방식을 비교했고 — 오픈API는 slug마다 활용신청이
필요하고(prod 키로 403) `general_restaurants` 한 slug만 2,129,830행이라 페이지 수천
개였다.

**그리고 세 번째 것을 보고 답이 나왔다.** data.go.kr 파일데이터 상세의 제공형태가
"**기관자체에서 다운로드(제공데이터URL기재)**"이고, 그 URL 필드가
`https://file.localdata.go.kr/file/<slug>/info` — **지금 라이브러리가 쓰는 바로 그
주소**다. 두 데이터셋으로 확인했다(15045016 / 15044967).

**이관은 됐는데 파일 경로는 그대로였다.** data.go.kr이 메타데이터를 들고 실제 파일은
기관 호스트에서 받게 한다. 그래서 옮길 것이 없고, 그 경로는 활용신청이 필요 없으므로
**분모가 없는 것이 정상**이다(krheritage와 같은 이유).

### 남길 것

**깨졌을 때 볼 곳은 data.go.kr 파일데이터 페이지의 URL 필드다.** 그것이 정본이고
`file.localdata.go.kr`는 그 필드의 현재 값일 뿐이다. 지금 그 호스트는 Referer를
요구하고(핫링크 보호), 사람용 포털은 죽어 있다 — 조이는 중이라는 신호다.

그리고 요청 수가 확정됐다: slug당 3(info·validate·download) × 42 = **126요청**으로
전체 스냅샷. 오픈API로 같은 것을 받으면 수만 요청이다.

## 2026-09-14 — 포털을 한 번 보니 저장소가 5배 틀려 있었다 (OpiNet)

"지금 쿼터 이슈가 급한 이유가 뭐야? 공식 자료에서 확인하면 되는 거 아님?"이라는
물음이 맞았다. 두 가지가 동시에 드러났다.

### 급하지 않았다

prod 실측: feature asset materialization **0건**, feature cron schedule 전부 꺼짐.
KMA·에어코리아는 제외 + 큐 경계에서 강제. **지금 prod는 upstream을 거의 부르지
않는다.** 나는 큐 예산 강제 장치를 만들려 하고 있었는데, 이 저장소가 스스로 적은
원칙이 "**측정 전에 상한 숫자를 바꾸지 않는다**"였다. 내가 그것을 어기고 있었다.

### 그리고 보니 5배 틀려 있었다

오피넷 이용안내를 **한 번 열었더니** 일반 API 19종이 `300call/일`이고 1,500call/일은
**유료 프리미엄 3종**이었다. 이 저장소는 무료키 한도를 1,500으로 알고 그 위에 예산
전체를 세웠다:

| 자리 | 종전 | 실제 300 대비 |
|---|---:|---|
| `opinet_run_call_budget` 기본 | 600 | **하루 한도의 2배**(place job과 겹치면 4배) |
| 같은 필드 `le` 상한 | 700 | 설정 한 줄로 하루의 2.3배 |
| `opinet_low_top_max_calls` 기본 | 180 | `get_area_codes`와 합쳐 하루의 66% |

Map이 부르는 네 오퍼레이션은 전부 일반 API 목록에 있다. **켜져 있었다면 첫날에
막혔을 값이다** — prod가 `opinet_scope_mode=disabled`라 잠복해 있었을 뿐이다.

140/300/90으로 내렸고 산수를 테스트로 결박했다(종전 값으로 되돌리면 2건이 빨개지는
것을 확인했다). 대가는 커버리지다 — lowTop 시군 윈도가 60 → 30, 전국 1주기 ≈4일 →
≈8일. run당 cap으로는 "하루 2 run"을 표현할 수 없어서 생기는 손해다.

### 남은 셋도 봤다 — 그리고 "분모가 없다"가 셋 다 다른 뜻이었다

- **`krheritage`: 한도가 존재하지 않는다.** provider 소스가 `serviceKey`를
  `apis.data.go.kr` 호스트에만 주입하고 heritage는 `www.khs.go.kr/cha`다 — **인증키가
  없다.** 키가 없으면 per-key 일일 한도라는 개념이 없다. sweep당 ~3,950요청에 대해
  "몇 %"를 물을 대상이 애초에 없었던 것이다. 위험은 쿼터 소진이 아니라 **과도 호출로
  인한 차단**이고, 그것은 분모가 아니라 간격·동시성의 문제다.
- **`krex`: 한도를 공개하지 않는다.** 인증키는 즉시 발급되는데 OpenAPI 소개·인증키
  발급 어느 페이지에도 수치가 없다. **모르는 것이지 없는 것이 아니다.**
- **`mois`/localdata: 못 봤다.** `www.localdata.go.kr`가 응답하지 않았다. 재시도해야
  한다.

셋을 "분모 없음"으로 뭉쳐 적고 있었는데, 실제로는 **없다 / 모른다 / 안 봤다**로
전부 다르다. 필요한 조치도 다르다 — 첫째는 rate limit, 둘째는 문의, 셋째는 재시도다.

### 교훈

**분자를 만드는 데 하루를 썼는데, 분모 하나를 보는 데는 1분이 걸렸고 그쪽이 더 큰
것을 찾았다.** 계측은 "우리가 얼마나 쓰는가"를 답하지만 그 답이 쓸모 있으려면 분모가
맞아야 한다.

## 2026-09-14 — 사용자가 끈 provider가 살아 있는 경로로 나가고 있었다

`T-VN-QUOTA-ARITHMETIC` 조문 6(마지막)을 닫으러 갔다가 조문보다 큰 것을 찾았다.

### 조문 6은 이미 충족돼 있었다

본문이 "**남은 것은 G(실제 격자 수) 실측**"이라고 적는데, **같은 절의 표가 같은 날
G = 59로 답하고 있었다.** 헤드라인 비율 72%/72%/24%도 반증된 G=300 상한의 열이다.
낡은 조문 하나로 task가 열려 있었던 것이다. 조문이 요구한 것 — 오퍼레이션별 분모,
쿼터 비공유, G, 증폭기 선언, 조문 3, 켠 뒤 볼 분자 — 은 전부 들어와 있었다.

### 그런데 prod는 cron으로 돌지 않는다

instigator state가 11개뿐이고 전부 센서 + 분당 job 하나다. **feature load schedule은
하나도 켜져 있지 않다**(전부 `default_status=STOPPED`, 켜진 적 없음). 살아 있는 것은
`feature_update_request_queue_sensor`다. 즉 쿼터 산수 전체가 **cron 기준으로 쓰였는데
prod의 실제 적재 경로는 큐**다.

그래서 2차 적대 리뷰가 잡은 "큐 runner가 계수기를 열지 않는다"가 **운영상 가장 중요한
blocker**였다. 그때는 그것을 몰랐다.

### 그리고 "껐다"가 참이 아니었다

`DISABLED_FEATURE_LOAD_SCHEDULES`는 2026-09-09 사용자 지시로 KMA·AirKorea 자동 적재를
중지한 기록이다. 그런데 그 목록은 **`FEATURE_LOAD_SCHEDULES` 생성에서 이름을 빼는
것이 전부**였다 — 전 저장소에서 그 상수를 읽는 자리가 그 한 줄뿐이다.

큐 runner에는 꺼진 operation 6개의 spec이 그대로 있고, 실행 전 정책 게이트는
`provider_refresh_policies` row가 없으면 `allow_targeted`로 **fail-open**한다.
baseline seed에 그 row는 **0건**이다. PinVi cache target refresh 하나가 반경 안 KMA
weather feature를 잡으면 격자 순회가 그대로 나간다.

**사용자가 끈 것이 꺼져 있지 않았다.** 기록은 "껐다"고 말하는데 살아 있는 경로에서는
지켜지지 않았다.

이제 큐 경계가 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 읽어
`provider_auto_load_disabled`로 건너뛴다. 결박은 목록이 아니라 **효과**에 건다 —
enforcement를 `if False:`로 바꾸면 12건이 빨개지고 대조군 2건은 초록으로 남는 것을
확인했다. "끄는 것은 시계이지 능력이 아니다"는 원칙은 그대로다: 사람이 Dagster UI에서
job을 직접 돌리는 백필은 이 runner를 지나지 않는다.

### 남은 것은 끄지 않은 provider의 총량이다

큐에는 일일 예산이 없다. 상한은 센서 tick당 10 run(15초 간격)뿐이다.

그리고 같은 날 **KMA·에어코리아가 쿼터 평가 대상에서 빠졌다**(사용자 지시). 둘 다
꺼져 있고 이제 큐 경계가 그 결정을 강제하므로, 평가는 **끄지 않은 provider**만
본다. 그러자 그림이 더 나빠졌다 — 남는 provider 중 일일 가드가 있는 것은
**OpiNet 하나뿐**이다(KMA의 cursor skip이 빠지니 그렇다). `krheritage`는 sweep당
~3,950요청인데 분모조차 없고, 나머지 다수는 1,000/op/일이다.

빼고 나서 남은 것이 더 좁아지는 것 — 그것이 이 지시가 실제로 드러낸 것이다.
`T-VN-QUEUE-QUOTA`로 남겼다(`docs/etl/upstream-quota.md` §5).

## 2026-09-14 — 분자를 prod에 올렸고, 거기서는 아직 볼 수 없다는 것을 알았다

`#1229`(`2db70b478`)가 머지됐고 t42a 재핀 사이클이 전 사이클 GREEN이다 — 회전 #50,
rebuild `phase=committed`, repin VERIFIER PASS, M01 ACL 55/55, **D1 live Playwright
11 passed**, D2 `phase=passed`. 분자 모듈이 prod Dagster 이미지에 살아 있는 것도
확인했다(`upstream_requests_min`).

### 그런데 prod의 asset 경로에서는 분자를 관측할 수 없다

배포 뒤 돌아간 run이 `current_weather_summary_refresh`(분당) 하나뿐이다. feature
asset materialization이 **0건**이라 `upstream_requests_min`이 실린 자리가 없다.

이유는 설정이다 — feature load schedule은 전부 `default_status=STOPPED`이고
(`schedules.py`), prod의 instigator state 11개에 feature 스케줄이 하나도 없다.
**즉 오늘 prod는 feature upstream을 거의 부르지 않는다.** 분자를 붙였지만 그것이
0이 아닌 값을 내려면 누군가 스케줄을 켜야 한다.

**그리고 그것이 정확히 어디를 봐야 하는지를 바꾼다.** prod의 살아 있는 적재 경로는
cron이 아니라 **feature update queue**다(`feature_update_request_queue_sensor`만
RUNNING). 큐 경로의 분자는 asset output metadata가 아니라
`ProviderDatasetRefreshResult.metadata`에 실린다 — 2차 적대 리뷰가 잡은 "큐 runner가
계수기를 열지 않는다"가 운영상 가장 중요한 blocker였던 이유다.

이것은 결함이 아니라 **이 task의 다음 단계가 무엇인지를 말해 준다.** 조문 6(KMA
격자 재활성화)이 아직 `[~]`인 이유와 같은 자리다 — 분모·분자·증폭기 선언이 다
끝났으므로, 이제 켜는 판단에 필요한 것은 전부 있다. 켜는 순간 그 판단이 맞았는지를
`upstream_requests_min`이 처음으로 말해 줄 것이다.

**켜지 않고 분자를 검증하려면 쿼터를 쓴다.** 그래서 하지 않았다. 계측의 정확성은
런타임 테스트가(가짜 client로 N번 → 계수 N) 결박하고, prod가 더해 주는 것은
"실제 Dagster 문맥에서 배선이 살아남는가"뿐이다 — 그 축은 스케줄이 켜지는 날
공짜로 확인된다.
