# journal 아카이브 — 2026-09-16 ~ 2026-09-19

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-09-19 (4) — 등산로가 한 번도 성공한 적 없는 이유는 봉인의 크기 천장이었다

`feature_route_krforest_mountain_trails_job`이 **4시간18분** 지오코딩을 마치고
적재/봉인에서 죽었다. `ProgramLimitExceededError: total size of jsonb array
elements exceeds the maximum of 268435455 bytes`.

적재와 봉인이 같은 트랜잭션이고 봉인이 마지막이라 57,060행이 통째로 롤백된다.
`mountain_trail_segment`가 0행인 이유가 이것이다 — **한 번도 성공한 적이 없다.**
재시도는 같은 자리에서 죽으며 매번 4시간을 다시 쓴다. 2차 시도를 종료시켰다.

**진단을 두 번 했고 첫 번째가 틀렸다.** 처음에 나는 이 job의 정체를 "geo가 느려서
timeout"으로 읽고 재시도·동시성을 설계하려 했다. 적대 리뷰가 전제를 의심했고 다시
재니 geo는 p50 86ms로 답하고 있었고 5시간 동안 포화 신호를 한 건도 내지 않았다.
죽인 것은 호스트의 I/O 포화(`/proc/pressure/io` full 25%)였고, 그 원인의 일부는
내가 job 7개를 동시에 띄운 것이었다. 그것과 별개로, **끝까지 간 run은 봉인에서
죽었다** — 두 결함이 겹쳐 있었다.

**geometry가 route payload의 98.5%다.** 43 kB 중 나머지가 633 B다. 그래서 소유자
지시(별도 PostGIS 보조테이블)는 정확히 옳은 방향이다. 그런데 같은 함수가 place에도
돈다 — 323 B × MOIS 980,970행 = **302 MB로 geometry 없이도 초과**다. 즉 geometry를
어디로 옮기든 **fold 자체가** 다음 큰 dataset에서 같은 벽에 닿는다.

그래서 순서를 뒤집었다. **봉인 먼저(311), geometry 분리 다음(312).**

311은 배열 **원소의 정의를 한 글자도 바꾸지 않고** 접는 방식만 바꾼다. `jsonb_agg`
하나로 전 행을 모으는 대신 행마다 32바이트 digest를 만들어 정렬 집계한다.
`canonical_input` CTE를 손으로 옮기지 않고 **정본에서 추출해 조립한 뒤 41줄이
바이트 단위로 동일함을 프로그램으로 대조**했다 — head-schema diff에 CTE가 아예
나타나지 않는 것이 그 독립 증거다. 탐지 범위가 1비트도 줄지 않는다.

**해시 값은 달라지므로 세대를 남긴다.** 두 비교 지점은 같은 run의 receipt만
재대조하므로 게이팅은 안전하고, 투입 시점에 진행 중 curation root가 0건임을
실측했다. 그러나 이미 저장된 receipt는 이후 영원히 재계산되지 않는다 — 세대가
없으면 **"공식이 바뀌었다"와 "값이 변조됐다"가 같은 관측으로 보인다.**

**검사는 효과에 걸었다.** 256 MB 데이터를 만들 수 없으니 천장이 *생기는 원인*을
잰다 — 행수는 같고 payload만 1,000배 다른 입력에서 중간 집계 길이가 같은가
(`행수 × 32 B` 고정). 옛 fold가 실제로 100배 넘게 자라는 것을 같은 자리에서
대조군으로 증명해 항진명제가 아님을 보인다.

**게이트 구멍도 하나 닫았다.** 이날 나는 n150에서 `tests/unit tests/lint`만 돌리고
`packages/kor-travel-map-dagster/tests`를 빼먹었다 — Map CI는 그것을 별도 세션으로
돌린다. 그 구멍으로 세 검사가 CI에서 처음 빨개졌고, 메모리에는 그 다섯 세션이
이미 적혀 있었다. 규약이 있어도 따르지 않으면 없는 것과 같다.

## 2026-09-19 (3) — 0행의 이유를 끝까지 따라가니 결함이 둘이었다

`feature.feature_notices`가 저장소 전체에 0행인 것의 원인을 prod에서 따라갔다.
가설은 맞았고, 그 뒤에 **더 나쁜 것**이 있었다.

**가설이 실측이 됐다.** 산사태 feed의 유일한 위치 단서 `ocrnFrcstIssuInsttNm`을
10,562건 전수로 재 보니 97%가 `충청남도 당진시`처럼 시도+시군구, 0.6%가 시도만,
0.1%가 `경기도 산림환경연구소`, 1.5%가 빈 값이었다. **98.5%가 행정구역을 말한다.**
그런데 변환이 모든 notice에 `coord=None`과 빈 `Address()`를 박아 그것을 버렸다.
`_provider_address`가 `None`이 되니 적재기가 "단서 없음"으로 전량을 떨궜다.

값은 자르지 않고 그대로 `Address.admin`에 넣는다. 좌표 없는 row의 주소 단서를
`admin`에 남기는 것은 이 저장소의 기존 관례이고(`providers/mcst.py`), 검증층의
`_provider_address`가 바로 그것을 읽으려고 `road`→`legal`→`admin`을 본다.

**더 나쁜 것: 데이터셋이 통째로 사라져도 job은 SUCCESS였다.** 상류 10,467건을
받아 10,467건을 전부 버리고 notice feature 0건으로 끝났는데 결과는 초록이었다.
`strict_address`가 prod에서 `drop`이고, 그 모드는 "대부분 멀쩡한데 몇 개가 나쁘다"를
전제로 하는데 **전제가 깨진 것을 아무도 세지 않았다.** error 심각도 위반 10,467건이
`ops.data_integrity_violations`에 `open`으로 쌓여 있었고 그것을 읽는 admin 화면도
있었다. **기록은 읽히지 않으면 없는 것과 같다.**

그래서 적재율 하한을 뒀다 — 버린 것이 남긴 것보다 많으면 적재하지 않고 죽는다.
0.5는 측정값이 아니라 의미의 경계이고, 그 사실을 코드에 적었다. 다만 측정과의
거리도 적었다: 같은 날 landslide를 뺀 모든 dataset의 error 탈락률은 0%, landslide도
주소를 살리면 1.5%다. 하한은 정상값의 33배 위에 있다.

이 하한이 막는 것은 소실만이 아니다. drop은 탈락 bundle을
`retire_absent_from_snapshot=True` 적재 **앞에서** 제거하므로, 일시적 장애로 떨어진
행의 **기존 feature가 은퇴**한다. 은퇴는 다음 run의 멱등 upsert로 돌아오지 않는다.

**두 경로에 걸었다.** 적재 경로가 materialize와 chunked stream 둘인데, 이 저장소가
반복해 다친 모양이 "선언을 바꿨는데 그 선언을 얼려 둔 자리를 같이 못 봤다"이다.
chunked 쪽은 batch를 다 흘린 뒤, 그러나 loader가 commit하기 **전에** 던진다.

**죽기 전에 증거를 남기는 계약이 strict 경로에만 있었다.** 그 블록을
`_fail_before_load`로 빼서 하한도 같은 경로를 쓰게 했다. 따로 뒀으면 나중에 생긴
쪽이 기록을 빠뜨린 채 던지기 쉽고, 그 결과는 이유를 모르는 빨간 run이다.

**변이 다섯 가지로 검사가 실제로 빨개지는 것을 확인했다.** 그중 처음 만든 하나는
빨개지지 않았는데, 검사가 항진명제여서가 아니라 변이가 엉뚱한 호출부(strict 경로)를
건드렸기 때문이었다 — 변이를 못 믿으면 "빨갛게 만들어 봤다"도 못 믿는다.

## 2026-09-19 (2) — 적대 리뷰가 내 수정 안에서 같은 모양을 셋 더 찾았다

전문 리뷰어 2인이 다각도로 보고, 발견마다 반증 검증을 붙였다(에이전트 24, 반증
성공 2건). **확정된 것 15건 중 셋이 이 PR이 스스로 막겠다고 선언한 모양이었다.**

**키가 경로에 있으면 예외 메시지가 그것을 나른다.** 서울 열린데이터광장은 인증키를
URL 경로에 받는다. 나는 본문을 예외에 싣지 않도록 신경 썼는데, 그 사이에 낀
`response.raise_for_status()` 한 줄이 URL 전체를 담은 `httpx.HTTPStatusError`를
던진다. 그 메시지는 Dagster step-failure 이벤트와 compute log에 영속 기록되고,
큐 경로는 `from exc`로 체인까지 보존한다. **형제 라이브러리는 이미 그것을 막고
있었다** — `python-datagokr-api`가 `copy_remove_param("serviceKey") + from None`을
쓴다. 이론적 지적이 아니라 확립된 규범에서의 회귀였다.

그리고 그것을 막는다고 이름 붙인 검사가 **그 가지를 한 번도 지나지 않았다.**
테스트 대역의 `raise_for_status`가 무조건 `None`을 돌려줬기 때문이다. 이 저장소가
반복해 다친 "탐지기가 항진명제" 그대로다 — 좌표 축 검사와 INFO-200 종료 검사도
같은 부류였다(전자는 `_validated_lonlat`의 bbox 자동 스왑이 되돌려 주고, 후자는
첫 페이지에서 이미 끝나 두 번째 응답을 소비하지 않는다).

**`if secret is None`은 배포 형상에서 한 번도 발화하지 않는다.** compose가
자격증명을 `${X:-}`로 배선하므로 변수는 **항상 정의되고 값이 빈 문자열**이다.
pydantic은 그것을 `SecretStr("")`로 받고, 모든 provider fetcher의 None 가드가
지나간다. 키 없는 스택이 빠른 실패 대신 무인증 상류 호출을 낸다 — OpiNet처럼
run당 예산이 있는 provider에서는 그 예산만큼 헛돈다. `env_ignore_empty=True`.

**하루 300회 보장이 재시도를 세지 않았다.** Dagster의 step 재시도는 asset을
처음부터 다시 실행하고, 그 실행이 run 예산을 **전부 다시 쓴다**. 공통 정책
(`max_retries=3`)이면 한 job이 최악 네 번 돌아 560회다. 기본 모드를 켠 것이
이 잠복을 실효로 만들었다. OpiNet asset 전용 `max_retries=0`을 두고, 검사는
배수를 리터럴이 아니라 **실제 정책에서 유도**한다 — 누군가 재시도를 되살리면
예산 검사가 함께 빨개진다.

**두 번은 리뷰어가 틀렸다.** (1) "자연키가 바뀌어 기존 서울 책방 feature가 전량
고아가 된다"는 2인이 high/critical로 올렸지만, prod에서 이 dataset의
`source_entities`가 **0건**이다(직접 조회). 적재된 적이 없어 충돌 대상이 없다.
(2) "경고 기준을 `min(ceiling, absolute_ceiling)`으로"는 그렇게 하면 항진명제가
된다 — `ceiling`이 바로 위에서 `needed × 2 + 1`로 유도된 값이다. 반증 검증이
(1)을 잡았고 (2)는 내가 구현하다 잡았다.

**문서도 같은 자리에서 낡아 있었다.** `opinet-place-price-etl.md`는 이 모드의
운영 정본인데 1,500/600/180을 그대로 들고 있었고, `feature.curated_sources`의
서울 책방 행은 죽은 URL과 **뜻이 뒤집힌** freshness_note("서울 열린데이터광장
원천 서비스 종료 안내 노출" — 옮겨 간 바로 그 포털이다)를 들고 있었다. admin
UI와 공개 curation API가 읽는 값이라 마이그레이션 310으로 고쳤다.

**남긴 것 하나.** MCST 부분 실패 run에서 **적재에 성공한 dataset의 membership이
완료 처리되지 않는다** — `raise Failure`가 완료 콜백보다 앞에 있고, 콜백 계약이
exact full snapshot을 요구한다. 증거 원장과 DB 상태가 어긋나지만 큐 경로에는
도달하지 않고(scope당 slug 1개), 이번 변경의 회귀도 아니다(종전에는 13개가
전멸했다). 부분 완료를 표현하려면 두 결박을 함께 풀어야 해 별건으로 둔다.

## 2026-09-19 — 핀을 올리지 않으면 고친 적이 없는 것과 같다

prod에서 32개 provider job을 한 번에 돌려 실패를 전수로 확정한 뒤, 그 원인들을 각각
닫는 작업이다. 이번 묶음이 고친 것은 **네 가지 모두 "선언은 바꿨는데 그 선언을 얼려
둔 자리를 같이 못 봤다"**는 한 가지 모양이다.

**provider 핀.** `python-krforest-api`(표준데이터 gateway가 `{header, body}` 래퍼를
벗어 산림 표준데이터 3종이 파싱에서 전멸)와 `python-mcst-api`(아동서점 CSV 원천이
fileDataNo 282 → 484로 이동) 양쪽 수정을 머지했는데, **이 저장소의 핀을 올리지 않으면
적재는 여전히 0건이다.** 표면 manifest도 함께 재생성했다 — 생성물이라 손으로 고치지
않는다.

**OpiNet은 선택자를 넘기는 것으로 끝나지 않았다.** 기본값이 `disabled`면 배포가
끝나도 적재가 시작되지 않아 운영자가 호스트 `.env`를 손으로 고쳐야 한다. 그 손 편집이
prod와 문서를 어긋나게 만든 자리다. 기본 모드를 `low_top_area`로 두고, compose가 아예
넘기지 않던 호출량 노브 둘도 함께 배선했다. 그리고 **`.env.example`에는 한도를 300으로
정정하기 전의 180/600이 그대로 남아 있었다** — 그 파일을 복사해 쓰면 고친 기본값을
덮고 첫날에 한도를 넘긴다. 검사는 리터럴이 아니라 "최악의 날(매월 1일, price+place)
호출이 무료키 하루를 넘지 않는다"에 결박했다.

**서울 책방은 활용신청으로 되살릴 수 있는 종류가 아니었다.** odcloud가 404
`등록되지 않은 서비스 입니다`를 주는데, 날조한 데이터셋 번호와 **같은 응답**이고
swagger 네임스페이스도 404다. 원천을 서울 열린데이터광장 OA-21062
(`TbSlibBookstoreInfo`)로 옮기고 라이브로 606건을 확인했다. dataset_key와 provider
이름은 **레지스트리 신원**이라 바꾸지 않았다 — provider_dataset row, operation key,
봉인된 300 카탈로그가 전부 그 이름을 쥐고 있다. 바뀐 것은 원천뿐이고 분기는
`_FILE_DATA_SOURCE_OVERRIDES` 한 줄이다. 분기를 fetcher 안에 둔 이유는 호출자가
둘(Dagster resource + feature-update worker)이라 한쪽에만 넣으면 큐로 도는 prod만 죽은
원천을 계속 부르기 때문이다.

이 포털의 함정을 검사로 못박았다. **오류도 HTTP 200으로 주고**, json을 요청해도
인증 실패는 XML로 오며, 범위를 넘기면 서비스 봉투 없이 `RESULT.CODE=INFO-200`만 온다.
그리고 **`XCNTS`가 위도, `YDNTS`가 경도다** — X를 경도로 읽는 통념대로 일반 키 목록에
넣으면 조용히 뒤집힌다.

**MCST asset은 시도하지 않은 dataset까지 적재하고 있었다.** feature-update worker는
fetcher를 slug 하나로 좁혀 부르는데(`_mcst_resources`) asset은 13개를 다 돌았다 —
나머지 12개가 **시도한 적도 없이** 빈 authoritative 적재와 sync-success를 받았다.
처음 적었던 근거("빈 스냅샷이 기존 feature를 전부 은퇴시킨다")는 **틀렸다**: 이
provider는 `retire_absent_from_snapshot`을 넘기지 않는다. 실제 해악은 은퇴가 아니라
**위장**이다 — sync cursor가 전진해 수집 실패가 신선한 성공으로 보이고, curation seal이
관측한 적 없는 집합을 권위로 봉인한다.

**산사태는 상한을 올리는 것으로 닫지 않았다.** 10,562건으로 자라 상한 10장을 먹은
사고에서 상한은 제 일을 했지만(조용한 절단 대신 시끄러운 실패) 그 신호는 job이 죽은
뒤의 신호였다. 발령마다 행이 쌓이는 append-only 피드라 다음 dataset도 같은 길을 간다.
그래서 **여유가 절반 아래로 내려오는 순간 prod가 먼저 말하게** 했다 — 그 지점은 CI
검사가 요구하는 여유(2배)와 같은 자리다. 경고 문구는 "상한을 올려라"가 아니라
"증분 수집으로 바꿀 때인지 보라"다. 증분 전환 자체는 별건이다 — 이 asset은
`load_authoritative_notice_snapshot`으로 `active_lineage_keys` 전체를 대조하므로,
부분 수집으로 바꾸면 화해 계약부터 다시 설계해야 한다.

## 2026-09-16 (3) — 조문이 열려 있는 동안 같은 사고가 세 DB에서 재발했다

`T-VN-H49-BACKUP-STALENESS` 조문 1을 설계하려고 실측하다 **진행 중인 두 번째 사고**를
찾았다. `geo_dagster`·`concierge`·`pinvi` standalone 백업이 **09-12부터 5일째**
`Permission denied`로 실패 중이었다:

```
[2026-09-11T03:15:05Z] [standalone-backup:geo_dagster] done      ← 마지막 성공
/bin/sh: 1: .../run-standalone-backup.sh: Permission denied      ← 이후 전부
```

crontab은 경로를 직접 실행하는데 그 파일이 실행 불가였다(전부
`-rw-rw-r--`). 실행 비트를 세우고 미등록 role
탐침으로 확인했다(`EXIT=2` — 덤프도 GC도 일으키지 않는 경로). 다음 cron부터 실제
백업이 나온다.

**조문 하나가 "아직 아니다"로 열려 있는 동안 같은 형태가 세 DB에서 조용히 재발했다.**
이보다 그 조문의 값을 잘 보여주는 것은 없다.

**근본 원인은 "경보가 없다"보다 앞이었다.** Manager 저장소 어디에도 백업 주기를
선언한 것이 없다 — 기대치가 오직 crontab에만 있고 저장소의 어떤 코드도 crontab을 읽지
않는다. 선언되지 않은 것의 부재는 원리적으로 탐지할 수 없다. 그래서 감시자보다
기대치 모델이 먼저다.

원장의 틀린 문장도 고쳤다: 조문 1의 "(a) api 컨테이너만 마운트한다"는 사실이 아니다 —
**api·dagster 둘 다** `backup_root`가 마운트도 env도 없고, Dagster op의 config schema엔
그 키 자체가 없다. 자동으로 기록되는 F9 행은 **예외 없이 `observed=false`**다.

알림 경로 자체는 소유자 지시로 보류했다. 설계(조사 4 + 안 3 + 채점)는 소유권을
Manager로 이관하고 채널은 ntfy로 확정했으며, 기대치 모델 초안이 그 저장소에 미커밋으로
있다. 재개 시 첫 일은 **채널 실배달 1건의 육안 확인**이다.

## 2026-09-16 (2) — 한 번도 돌지 않았던 spec을 돌렸다

`T-VN-M02`의 마지막 조문은 "live acceptance spec이 격리 스택에서 완주한다" 하나였다.
live301(api `13711` · web `13712` · dagster `13714`)에서 `E2E_MANUAL_CREATE_WRITE=1`로
**2 passed (47.9s)**. 그리고 검사가 초록인 것과 DB가 그렇게 된 것은 다른 사실이라 따로
셌다 — `feature.features` 1 → 2, origin에 `manual_admin` · `e2e-admin` ·
`ktm_feature_api_runtime` · `ktm_manual_feature_procedure_owner` ·
`admin-ui-bff.manual-feature-create.v1`. 로그인한 주체가 BFF를 지나 SECURITY DEFINER
경계 너머 provenance까지 실려 온다는 것이 이 절이 요구한 계약이다.

**이 spec은 한 번도 실행된 적이 없었다.** 오늘 아침 actor 리터럴 결함을 찾은 것도
실행이 아니라 체인을 읽어서였다 — 즉 통과한다는 것이 알려져 있지 않았다. 그래서 이
조문의 값은 "M02를 닫았다"가 아니라 **"이제 그 spec이 실제 게이트가 됐다"**에 있다.

**원장이 또 낡아 있었다.** 2026-09-08 기록은 "컨테이너도 볼륨도 없다, 재구축이
선행이다"였는데 `ktm-live-301-pg`는 5일째 떠 있었고 체크아웃에 spec도 있었으며 앱 DB
head는 `309`로 저장소와 같았다. 실제로 막던 것은 둘이다: 체크아웃을 옮기면 사라지는
`scripts/*.sh` 실행권한, 그리고 **Dagster 메타DB 통째 부재**(`kor_travel_map_dagster`
롤·DB를 만들고 `dagster instance migrate`까지 해야 런처 사전검증을 지난다 — spec은
Dagster를 쓰지 않지만 `run-admin-stack.sh`에 건너뛰기 경로가 없다).

**그리고 같은 것을 한 번 더 찾았다.** `T-VN-LEDGER-ARCHIVE` 조문 2·3도 #1239가 이미
넣은 것이었는데 표기만 열려 있었다. 오늘 원장이 다시 220 KiB를 넘어 그 도구를 실전에서
썼고 — 닫힌 절 둘을 다중집합 보존 검산 뒤에만 옮기고, 넷을 이유와 함께 거절하고,
삭제 게이트가 아카이브 미커밋 상태를 `T-VN-39-DEPLOY#1~#4`로 잡아냈다 — 코드가 있다는
것보다 강한 근거가 생긴 김에 닫았다.

**오늘 하루에 네 번이다.** `T-VN-D2-RESIDUE`(나흘) · `T-VN-DAGSTER-STORAGE` 조문 1
(배포가 증거를 지움) · `T-VN-M02`(여드레) · `T-VN-LEDGER-ARCHIVE`(사흘). 넷 다 **일이
남아서가 아니라 기록이 따라가지 않아서** 열려 있었고, 그동안 "막혀 있다"로 읽혔다.
`docs/tasks-rule.md` §6이 이 형태를 다루지만 규약만으로는 부족하다 — 조문을 닫는 PR이
그 조문을 실제로 닫는지 보는 장치가 없다. 다음에 만들 것이 있다면 그것이다.

## 2026-09-16 — seal ACL을 닫았고, prod가 배포마다 새로 태어난다는 것을 알았다

`T-VN-CURATION-SEAL-ACL` 세 조문을 닫았다(#1239 머지 후 별도 PR). 조문 2는 코드를
읽어 이미 들어가 있었고 조문 1은 2026-09-12 기록이 있었는데, **그 기록의 근거를 다시
재려다 prod DB가 배포 때 새로 만들어진다는 것을 알았다** — `kor_travel_map` 생성
시각이 t44a 배포 시각(2026-09-15 12:29:55Z)이고, 조회 시점 `feature.features` 0행 ·
`source_entities` 0행 · seal 영수증 0건 · Dagster run 897건은 전부 분 단위 날씨
스케줄(배포 후 15시간치)이었다. **`[x]`는 붙어 있는데 그것을 뒷받침하는 관측은 없는
상태였다.**

그래서 현 세대에 `feature_place_standard_museums_job`을 정식 경로로 다시 제출했다.
run `0f70d0d5` `SUCCESS`, `features 1047 · source_entities 1047 · **seal 영수증 1건**`.
영수증은 적재가 seal 함수에서 해시를 받아온 뒤에만 쓰이므로 — 그리고
`finish_provider_feature_membership_command`가 영수증 유무와
`authoritative_snapshot_complete`가 어긋나면 거절하므로 — "EXECUTE가 목록에 있다"가
아니라 **"적재가 그 함수를 실제로 실행했다"**의 증거다. 같은 실행으로
`T-VN-DAGSTER-STORAGE` 조문 1도 현 세대에서 다시 섰다.

조문 3에는 **실 login으로 적재 경로를 태우는** 회귀를 추가했다. 있던 검사 둘 다 조문이
거부하는 모양이었다 — 하나는 migrator가 카탈로그 술어를 묻고, 다른 하나는 실 login으로
접속하지만 그 목록에 seal 함수가 없다. 변이로 차이를 보였다: EXECUTE는 두고 호출부가
함께 거는 표 SELECT만 걷으면 **옛 검사는 초록이고 새 검사만 빨갛다.**

배포가 DB를 새로 만든다는 사실은 특정 task가 아니라 **조문을 쓰는 방식**의 문제라
`docs/tasks-rule.md` §6에 적었다. 전수 확인 결과 실제로 근거를 잃은 조문은
`T-VN-DAGSTER-STORAGE` 조문 1 **하나**였다(prod 실측 근거 4건 중).

그리고 **CI가 잡고 n150 네 세션 게이트가 못 잡은 것**이 하나 있었다 —
`consistency.py`의 `sample_ids=()`(선언은 `list[str]`). 게이트는 전부 pytest이고
mypy가 없다. dataclass는 런타임에 타입을 강제하지 않아 F9 검사 39건이 전부 초록인 채로
통과했다.
