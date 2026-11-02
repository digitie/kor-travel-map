# resume-2026-09b.md — resume.md 아카이브 (2026-09-08 ~ 2026-09-14)

> 2026-11-02 규약 §8에 따라 [현재 resume](../resume.md)가 220 KiB 경계에 닿아(여유 632 B) 가장 오래된 완전한 네 절을 분리했다. 네 절에 상대 링크가 없어 본문은 바꾸지 않았다. 읽기 전용 이력이다.

## 2026-09-14 — 분모가 없는 provider를 분모 없이 막았다 (krex TPS 5)

**다음 한 작업: `T-VN-QUEUE-QUOTA` 조문 6 — 분모가 **있는** provider에 일일 예산을
둘지 판단.** 조문 5(`krex`)는 닫혔다.

**`krex`는 일일 한도를 기다리지 않고 축을 바꿨다.** 포털 네 면 어디에도 일일 수치가
없고 남은 길은 문의뿐이었는데, **이 provider에서 실제로 조일 수 있는 것은 간격이다.**
`python-krex-api` `feat/http-tps-limit`이 `KrexHttp`에 token bucket을 넣어 **초당
5건**을 넘기지 않는다(`max_rps` 기본 `5.0`, `KrexClient`/`AsyncKrexClient`로 전달).

세 가지를 일부러 다르게 했고 각각이 그냥 두면 틀렸을 자리다:

- **버스트 없음(capacity=1)** — capacity가 `max_rps`면 가득 찬 버킷에서 5건이 즉시
  나가고 그 초에 지속분이 더해져 **첫 1초에 10건**이다. 상한이지 평균이 아니다.
- **재시도도 요청이다** — 버킷이 재시도 루프 **안**에 있다.
- **락이 `threading.Lock`이다** — `_run_sync`가 호출마다 새 루프를 만들고 러닝 루프가
  있으면 별도 스레드에서 돈다. `asyncio.Lock`은 스레드를 전혀 막지 못하면서 막는 것처럼
  읽히고, 경합하면 처음 본 루프에 묶여 다음 루프에서 `RuntimeError`를 낸다(3.14 재현).

검사기는 일곱 변이로 확인했다(상한 끄기 / capacity 되살리기 / 기본값 / acquire를 루프
밖으로 / client 미전달 / go 포털만 우회 / 우회하는 새 전송 자리) — 각각 다른 테스트가
잡는다. 마지막 것은 AST로 `session.get(...)` 자리가 하나임을 본다. **효과 검사는 지금
있는 경로만 보므로 새 경로는 아무 테스트도 건드리지 않고 상한을 비켜 간다.**

**그리고 Map 쪽에서 내가 틀렸다.** "큐 러너가 순차 처리하므로 합계 5 TPS"라고
적었는데, 적대 리뷰 둘이 **독립적으로** 뒤집었다 — 그 순차성은 run **하나 안에서**의
이야기다. 큐 센서는 틱당 RunRequest를 10개 내고(`RUNNING`, 15초 틱),
`docker/dagster.yaml`이 `tag_concurrency_limits`로 **4를 동시에** 돌린다. run마다
프로세스가 다르니 `KrexClient`도 버킷도 넷 → **최대 20 TPS.** krex를 직렬화하는 것은
아무것도 없다(scope advisory lock은 키가 다르고, Dagster pool은 asset에만 있는데 큐
경로가 asset을 우회하며, `provider_refresh_policies.max_concurrent`는 **읽히기만 하고
집행되지 않는다**).

**닫혔다고 적은 구멍이 현재 설정으로 열려 있었다.** 지금 보증되는 것은 "프로세스당
5 TPS"이고 합계가 아니다. 남은 작업을 `T-VN-KREX-TPS-FANOUT`으로 뺐다 — 고칠 자리는
`max_rps`가 아니라 **provider 단위 동시성 집행**이고, 스키마
(`ops.provider_refresh_policies.max_concurrent`)는 이미 있다.

**아직 Map에 반영되지 않았다** — `pyproject.toml`의 krex 핀이
`c6d8717ec2b712cc952bc566b351f07a7cd3824a`다. krex PR 머지 후 repin이 따라온다.

t43a 배포 완료(`e3fddce81`, 전 사이클 GREEN — D1 live Playwright 11 passed,
D2 phase=passed). prod 실측으로 OpiNet 예산 140/90과 큐 skip 6건이 살아 있는 것을
확인했다.

분모 조회는 끝났다 —
`opinet` **300/일**(저장소가 1,500으로 알고 있었다), `krheritage`·`mois`는 **키가
없어 한도 자체가 없고**(mois는 data.go.kr 파일데이터가 기관 자체 다운로드 URL을
가리킨다 — 이관됐지만 파일 경로는 그대로다), `krex`만 **미공개**라 문의가 남았다.
2026-09-14에 넷을 다 봤고 결과가 갈렸다: **opinet 300/일**(저장소가 1,500으로 알고
예산 600을 세웠다 — 켜면 첫날에 막혔을 값, 140/300/90으로 고침), **krheritage는
인증키가 없어 한도 자체가 없다**(위험은 쿼터가 아니라 차단), **mois도 키가 없다**
(data.go.kr 파일데이터가 기관 자체 다운로드 URL을 가리킨다 — "사이트 무응답으로 확인
실패"라고 적었던 것은 같은 날 뒤집혔다: 죽은 것은 사람용 포털이고 파일 호스트는
살아 있었으며, 깨진 것은 Referer 없는 내 curl이었다), **krex는 일일 한도 미공개라
TPS 5로 막았다**(위 참고).

**급하지 않다.** 2026-09-14 prod 실측 feature asset materialization **0건**이고
feature cron schedule은 전부 꺼져 있다 — 쿼터가 압박받는 상황이 아니다. 큐 예산
장치는 분모를 보고 나서 필요한지 판단한다("측정 전에 상한 숫자를 바꾸지 않는다").
KMA·에어코리아는 평가 대상에서 제외(2026-09-14 지시).

`T-VN-QUOTA-ARITHMETIC`은 여섯 조문 전부 `[x]`로 닫혔다. 분모 실측(오퍼레이션마다
따로 걸린다) · 분자(`upstream_requests_min`, #1229) · 쿼터성 실패의 재시도 차단
(#1227) · 증폭기 선언 · UI 보증 제거 · KMA 재활성화 전제. prod 배포 t41a·t42a 두
사이클 GREEN.

**조사 중에 blocker 하나를 찾아 고쳤다.** `DISABLED_FEATURE_LOAD_SCHEDULES`
(2026-09-09 사용자 지시로 KMA·AirKorea 자동 적재 중지)는 **시계만** 껐다. prod는
cron이 아니라 feature update queue로 도는데(schedule 전부 STOPPED, 큐 센서만
RUNNING) 큐 runner에 꺼진 operation의 spec이 그대로 있었고 정책 게이트는 row가
없으면 fail-open이다 — 즉 **사용자가 끈 provider가 살아 있는 경로로 나가고 있었다.**
지금은 큐 경계가 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 읽어 건너뛴다.

## 2026-09-11 — T-VN-39 재키가 착지했다 (#1197, `e8c66c47`)

`feature.features.feature_id`가 uuid다. 서버가 적재 시점에 발급하는 UUIDv7이고 어떤
입력에서도 유도되지 않는다. 예전의 `f_*` 주소는 `feature.feature_aliases.alias`의
**주소 등록부**로 옮겨 갔고, 그 주소로 들어와도 같은 Feature가 나온다(ADR-098).
**바깥 이름은 하나도 바뀌지 않았다** — 바뀐 것은 값의 출처뿐이다.

같은 날 보안 PR #1198(maplibre-gl 6 · Next 16.3.4 · sharp 0.35.4)이 먼저 들어갔고,
재키 PR이 그 위에 얹혔다.

### 착지 시점 게이트

| 층 | 결과 |
|---|---|
| GitHub CI 9종 | 전량 초록 |
| n150 — provider **실제 설치** | dagster 575 · api 1,223 · lint+unit 2,832(환경 실패 14) |
| 제품 SQL 786문 head Parse | 초록 (587 → 786) |
| live — 필터 3갈래 | 200 / 200(빈 목록) / **422** |
| live — DB→API→실제 브라우저 | 통과 |

### 이 작업이 남긴 규칙 다섯

1. **검사가 초록인 것과 결함이 없는 것은 다른 사실이다.** 가르는 방법은 검사에
   결함을 일부러 넣어 보는 것뿐이다 — 그렇게 해서 FK 검사가 **항진명제**였음을
   찾았다(정본을 마이그레이션과 함께 움직이는 덤프에서 읽고 있었다).
2. **하한은 "판단 대상 수"가 아니라 "대상을 실제로 몇 개 보았는가"에 건다.**
   앞의 것은 결함이 고쳐지는 순간 0이 되어 빨개진다.
3. **개수 세기는 전칭 명제가 아니다.** 표면을 열거해야 "변환 안 된 자리"가 보인다 —
   uuid 필터 하나가 그래서 500인 채로 남아 있었다.
4. **쪼개서 빠르게 도는 하네스는 그 자체가 프록시다.** 통합을 9묶음으로 나눠 돌면
   세션 공유 DB에 쌓이는 상태가 보이지 않는다. 머지 전에 한 번은 CI와 같은 방식으로.
5. **결함을 만든 자리와 그것을 가린 자리는 따로 있을 수 있다.** API 패키지의
   autouse echo-resolve가 uuid 해석 축을 구조적으로 관측 불가로 만들고 있었다.

### 열린 후속 둘

- **API 패키지 conftest의 echo-resolve가 재키 이전 세계를 모사한다**
  (`feature_id=ref`). 그 patch가 깔린 채로는 "legacy 주소가 uuid로 바뀌는가"와
  "없는 참조가 422인가"를 관측할 수 없다. 지금은 그 축을 재는 테스트가 자기
  resolver를 설치해 우회한다. echo 자체를 재키 뒤 모양으로 바꾸는 것은 이 패키지
  테스트 47곳이 참조 문자열을 그대로 기대해 별도 작업이다.
- **datagokr/krheritage upstream의 페이지네이션 퇴화.** Map은 위임을 끊어 스스로를
  지켰지만(`total` 권위 페이지네이터), 근본 수정은 provider 쪽이다. 다른 소비자는
  여전히 노출돼 있다.

### 다음 한 작업

**prod Map 배포.** Map revision이 바뀌었으므로 D2 재핀 사이클 전체가 따라온다
(rotate → rebuild → 이미지 → repin → preflight → D1 → D2). `docs/` 안의 prod 배포
절차와 PinVi token pair 규약을 따른다.

그 뒤 **T-VN-34C paired fresh-live 레인**은 여전히 별도다 —
`consumer-rollout-v1.json`의 T-VN-40 paired consumer receipt가 `pending`이고, 그
blocking_reason 자체가 "Map Admin provenance가 opaque feature_id + required
feature_uuid로 바뀌었으니 full-admin artifact를 다시 vendoring하고 PinVi M05
attestation을 붙여 paired acceptance를 다시 돌려라"다.

## 2026-09-08 (3) — 원장이 밀려 있던 둘을 정리하고 계약 하나를 개정했다

두 PR이 머지됐다 — Map #1194(9개 체크 전부 통과), Manager #335.

| 항목 | 상태 |
|---|---|
| `T-VN-M05-VERIFY-RECEIPT` | **완료** — V1~V4 전부. 원장만 밀려 있었다 |
| `T-VN-M02` | 잔여 셋 중 **둘이 이미 해소**됐는데 문장이 안 따라갔다 |
| `T-VN-39` 소유자 판정 | **없어졌다** — 계약 개정으로 |
| 열린 항목 | 8 → **6**(보류 셋 포함) |

**`T-VN-M02`의 잔여는 하나뿐이다.** purge 정책은 306이 닫았고, backup/restore 축은
2026-09-07 판정으로 `T-VN-H49`가 가져갔으며, live acceptance **spec 회수도 끝났다**
(main에 있다). 남은 것은 **실행**이고 그것이 막힌 이유는 셋인데 그중 하나는 306이 절반
풀었다 — "지워지지 않는 write"는 hard-purge fence가 유일한 삭제 경로를 거부해서 생긴
것이었고 이제 감사되는 purge 명령이 있다. 남은 것은 prod UI의 actor 불일치와, 무엇보다
**격리 스택 재구축**이다(`~/ktm-live-301`은 정지가 아니라 사라졌고 302 head다).

**`notice_states` 계약 개정(소유자 승인).** removal manifest에서 (c)를 뺐다 — 대체를
정당화한 "문자열 시각 판정"이 `T-VN-35B`/`T-VN-37D`로 이미 없어졌고, 그 항목의
`fenced_by`(`T-VN-37B`)는 **원장에 존재한 적이 없는 유일한 entry**였다. 목표 상태 DDL은
"채택되지 않음" 표시만 달고 남긴다 — 지우면 같은 논의를 다시 해야 한다.

### 착수 가능 — 소유자 판정 없이

1. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 이제 판정 대기가 없다. 컬럼 37 · FK 34 ·
   인덱스 57의 rekey 공학이고, `feature.features`가 0행이라 데이터 이행 위험이 없다.
2. **`T-VN-M02` live acceptance** — `~/ktm-live-301` 재구축이 선행이다.
3. **`T-VN-H49` 잔여** — `geo` 예약 성공 누적과 문서 갱신.

### 소유자 판정 대기 — 둘

1. `T-VN-H49` **manual Feature hard purge**는 닫혔다. 남은 것은 off-box 목적지 —
   호스트·계정·**root가 쓸 수 있는** ssh 키. 코드는 이미 있다.
2. 없음(`notice_states`가 해소되어 하나로 줄었다).

### 미조치 리뷰 findings

적대 리뷰 23건 중 7건을 고쳤다. 남긴 P2 셋은 동작 결함이 아니라 설계 여백이다 —
second-level cascade가 복구점 밖, `count_rows_dynamic`의 `search_path` 폭, DELETE fence는
여전히 origin.

**오늘 배운 것.** 리뷰 셋이 각각 같은 맹점을 찔렀다 — 변이 축이 "코드를 **지우면**
빨개지나"만 묻고 "이 술어가 덮는 **범위**가 맞나"를 묻지 않았다. 그리고 공유 session DB의
**전역 집계 단언을 여섯 번** 고쳤다(전부 "무엇이 일어났나"가 아니라 "DB가 비어 있나"를
재고 있었다).

## 2026-09-08 (2) — purge를 열고, TRUNCATE fence와 소비 기록을 닫았다

| 항목 | 상태 |
|---|---|
| `T-VN-H49` hard purge 정책 | **완료** — migration 306, 소유자 승인 |
| `T-VN-M02-TRUNCATE-FENCE` | **완료** — migration 307, `ENABLE ALWAYS` |
| `T-VN-M05-ONESHOT-CONSUME` | **완료** — Manager #335 |
| `T-VN-M05-VERIFY-RECEIPT` | V1·V2·V4 완료, **V3만 남음**(소유자 판정 포함) |
| 열린 항목 | 8 → **5**(보류 셋 포함) |

**purge가 자기 복구점을 들고 다닌다.** 소유자가 건 "restore proof 먼저" 전제는 문자
그대로는 아직 안 맞는다(복원 메커니즘은 증명됐지만 복구점이 없다). 지우기 전에 cascade로
사라질 행을 전부 담게 해서 그 전제를 우회했고, 그 우회를 소유자가 승인했다.

**TRUNCATE fence는 `ENABLE ALWAYS`다.** origin이면 `replica` 한 줄로 사라지고, 그 한 줄은
이 표를 TRUNCATE할 수 있는 유일한 행위자가 언제든 쓴다 — 정직한 위협 모델은 적대자가
아니라 실수다.

### 적대 리뷰 둘이 내 변이 검증의 구멍을 잡았다

Manager 리뷰(14건 → 2 확정)의 P1이 결정적이었다 — 소비 검사의 phase 필터를 **약화**하는
변이가 초록이었다. **내 변이 축은 "지우기"만 재고 "약화"를 재지 않았다.** 그 부류를
전부 다시 봐야 한다. Map 306/307 리뷰는 이 글 쓰는 시점에 진행 중이다.

### 착수 가능 — 소유자 판정 없이

1. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 가장 큰 축이고 소유자 판정 대상이 아니다.
   대체 identity와 fence가 이미 prod에 있고 `feature.features`가 0행이라 데이터 이행
   위험이 없다. 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다.
2. **`T-VN-M02` live acceptance** — `~/ktm-live-301`을 **재구축**해야 한다(정지가 아니라
   사라졌고, 체크아웃은 302 head이며 spec 자체가 없다). purge가 열려 cleanup 이야기는
   풀렸다.
3. **`T-VN-H49` 잔여** — `geo` 예약 성공 2건 더 쌓이기를 기다리는 것과 문서 갱신.

### 소유자 판정 대기 — 셋

1. `T-VN-M05-VERIFY-RECEIPT` **V3** — receipt 인용이 승격 정의의 "출력을 이 절에
   기록한다"와 충돌한다. 그 문장의 개정이 함께 가야 한다.
2. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·**root가 쓸 수 있는** ssh 키.
3. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가.
