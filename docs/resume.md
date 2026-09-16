# resume.md — 현재 진척도와 다음 한 작업

## 2026-09-16 (3) — M02 완주. 열린 항목이 H49 계열과 둘만 남았다

**다음 한 작업: `T-VN-H49-BACKUP-STALENESS` 조문 1** — F9는 판정하지만 **사람에게 닿는
경로가 없다**. Dagster 배치에 `backup_root` 볼륨이 없고 `ops.feature_consistency_reports`를
아무도 폴링하지 않는다. 425건이 조용히 실패한 이유가 검사 부재가 아니라 **보는 사람
부재**였으므로, 검사를 더하는 것으로는 닫히지 않는다.

**`T-VN-M02` 완료.** live301에서 `E2E_MANUAL_CREATE_WRITE=1`로 **2 passed (47.9s)**,
DB 실측으로 `manual_admin` / `e2e-admin` / `ktm_feature_api_runtime` /
`ktm_manual_feature_procedure_owner` / `admin-ui-bff.manual-feature-create.v1` 확인.
**이 spec은 한 번도 실행된 적이 없었다** — 첫 실행이 초록이다.

**원장 기록이 또 낡아 있었다.** "격리 스택이 없다"(2026-09-08)는 틀렸고 pg는 5일째 떠
있었다. 실제로 막던 것은 (1) 체크아웃 이동 시 사라지는 `scripts/*.sh` 실행권한,
(2) **Dagster 메타DB 통째 부재**(롤·DB 생성 + `dagster instance migrate` 필요)였다.
spec 자체는 Dagster를 안 쓰지만 `run-admin-stack.sh`에 건너뛰기 경로가 없다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-H49`/`-OFFBOX`, `T-VN-H49-BACKUP-STALENESS` 조문 1.


## 2026-09-16 (2) — seal ACL 닫힘, 그리고 prod는 배포마다 새로 태어난다

**다음 한 작업: `T-VN-M02`** — 소유자 판단이 먼저 필요하다. 격리 스택을 다시 세울
것인지, purge를 HTTP로 노출할 것인지. 후자는 원장 기준 **순서 역전**이다(복원 증명은
`T-VN-H49`가 소유한다).

**`T-VN-CURATION-SEAL-ACL` 완료.** 세 조문 전부 실측으로 닫았다 — prod run `0f70d0d5`
`SUCCESS`(`features 1047 · seal 영수증 1건`), 배포 재적용 뒤에도
`dagster_seal=true / api_seal=false`, 실 login으로 적재 경로를 태우는 회귀 추가(변이
빨강 확인). 같은 실행으로 `T-VN-DAGSTER-STORAGE` 조문 1도 현 세대에서 다시 섰다.

**알아 둘 것 — prod DB는 배포가 새로 만든다.** `kor_travel_map` 생성 시각 =
t44a 배포 시각. 그래서 "prod에서 …가 완주한다" 형태의 조문은 다음 배포에서 `[x]`만
남고 근거가 사라진다. 규약은 `docs/tasks-rule.md` §6. 전수 확인상 실제로 그 자리였던
것은 `T-VN-DAGSTER-STORAGE` 조문 1 하나다.

**n150 네 세션 게이트에 mypy가 없다.** `sample_ids=()` 한 줄이 게이트 전부를 초록으로
지나 CI lint에서만 빨개졌다. PR 전에 mypy 3종 + lint-imports를 따로 돌린다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-M02`, `T-VN-H49`/`-OFFBOX`, `T-VN-H49-BACKUP-STALENESS` 조문 1.


## 2026-09-16 — 일일 예산은 만들지 않는다 (분자를 재서 나온 결론)

**다음 한 작업: `T-VN-LEDGER-ARCHIVE` 조문 2·3** — 원장 분리가 fence parity를
검산하게 하고, 아카이브를 삭제 감시 대상에 넣는 일. 조문 1(220KB 아래)은 닫혔다.

**쿼터 축이 전부 닫혔다.** `T-VN-QUEUE-QUOTA`(6/6)와 `T-VN-KREX-TPS-FANOUT`(4/4)
둘 다 완료로 이관했다. 조문 3의 답은 **"집행하지 않는다"**였다 —
`ops.provider_refresh_policies`가 prod에서 **0행**이고(seed도 0) 행이 없으면
`_skip_reason()`이 fail-**open**한다. gate가 그 테이블을 읽게 만들면 읽을 값이 없어
통과시켜 **코드 상수보다 나빠진다.** **분모가 아니라 분자를 재서** 판단했다 —
전국표준데이터는 하루를 넘기려면 총건수 166,000이 필요한데 실측 최대가 **18,883**
(`parking`)이다. visitkorea 5%, 산림청 0.6~6%, `krairport` **0건**(번들 데이터).
가장 좁은 `opinet`(300/일)은 이미 run당 예산이 있다. (`special_street`가 prod 키로
403인 것은 관측했으나 **평가 대상에서 제외**한다 — 2026-09-16 지시.)

**장치 대신 구멍 셋을 닫았다:** khoa 페이지 절대 상한 + stall 지문(선언 총건수 하나가
틀리면 하루치를 넘길 수 있었다), `opinet_run_call_budget`의 `le` 300→150(2 run × 300
= 600이 **설정 가능**했다).

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-M02`, `T-VN-H49`/`-OFFBOX`, `T-VN-D2-RESIDUE`, `T-VN-CURATION-SEAL-ACL`.


## 2026-09-15 — t44a 배포 완료, async 이관이 prod에서 돈다

**다음 한 작업: `T-VN-QUEUE-QUOTA` 조문 6 — 분모가 *있는* provider에 일일 예산을
둘지 판단.** krex는 TPS로 닫혔고(`T-VN-KREX-TPS-FANOUT` 조문 1·2·4), 남은 것은
분모가 있는 쪽이다.

`#1235`(provider 13개 async-only) 머지 후 t44a 재핀 전 사이클 GREEN — D1 live
Playwright 11 passed, D2 `phase=passed`. **prod에서 직접 읽어** 새 라이브러리(동기
`close` 없음, 전부 coroutine)와 gate(`{'krex': 0.2}`, 4건 선언, 계수기보다 바깥)가
살아 있는 것을 확인했다. **버전 문자열로는 판별되지 않아**(13개 전부 `0.1.0`) 코드의
성질을 물었다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3(정책 테이블 `max_concurrent` 집행),
`T-VN-QUEUE-QUOTA` 조문 6, `T-VN-LEDGER-ARCHIVE` 조문 2·3, `T-VN-M02`,
`T-VN-H49`/`-OFFBOX`, `T-VN-D2-RESIDUE`, `T-VN-CURATION-SEAL-ACL`.


## 2026-09-15 — provider 13개 async-only 이관 (브랜치 `feat/provider-async-tps-migration`)

**다음 한 작업: n150 4세션 게이트 결과 확인 → PR → 머지.** 그 뒤 prod 재핀
(`/root/chain17.sh`)이 따라온다 — provider 핀이 13개 바뀌었으므로 이미지 재빌드가 필요하다.

형제 `python-*-api` **13개 전부**가 native async only + 공유 TPS 제어로 재작성됐다
(사용자 개편). Map을 그 표면에 맞췄다 — 핀 13개, fetcher 20개 async 전환, 경계 4곳,
manifest 재생성, 계약표 13행.

**어제의 krex TPS 브랜치(`python-krex-api` `feat/http-tps-limit`)는 흡수됐다.** 새
라이브러리가 그 기본값과 검증을 그대로 갖고 있다(실측 확인). 머지하지 않고 접는다.
**Map 쪽 `provider_rate_gate`는 살아남는다** — 새 `rate_limiter=` 주입은 한 이벤트
루프 안에서만 성립하고 Map의 fan-out은 프로세스를 가로지른다.

검증(기준선 비교):

| | 브랜치 | HEAD 기준선 |
|---|---:|---:|
| dagster 세션 | 680 passed / **10 failed** | 675 passed / **같은 10 failed** |
| 실패 집합 | — | **IDENTICAL(회귀 없음)** |

남은 10건은 dagster 버전 환경 문제(`test_storage_migration_command` 9 +
`test_definitions` 1). tests/lint 288 passed(conformance 38 포함), ruff 전 트리 clean.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3·4(정책 테이블 집행 여부, prod 실측),
`T-VN-QUEUE-QUOTA` 조문 6(분모가 있는 provider의 일일 예산),
`T-VN-LEDGER-ARCHIVE` 조문 2·3.


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


## 2026-09-08 — T-VN-M05 완주. 열린 항목은 여섯이고 소유자 판정은 셋이다

| 항목 | 상태 |
|---|---|
| `T-VN-M05` | **완료** — 조문 M05-1~M05-7 전부 충족 |
| M05-2 | evidence export(A)·오프라인 검증(B)·리허설 소유권 증명(C)·**복원본 수리(D)** |
| M05-5 | 전용 admin 라우트 `src/app/admin/manual-provider-dedup/` |
| 실측 | n150 M05 통합 42건, 세 배치 순서 36건, 변이 14축 전부 RED |
| restore 정책 | **변함없이 닫혀 있다**(2026-08-26 소유자 결정) |

M05-2를 닫으면서 판정을 한 번 되돌렸다. "lease를 evidence root에 담지 않으니 fencing
token이 되살아날 자리가 없다"는 **번들에 대해서만** 참이었다 — `pg_dump`는 스키마 전체를
담으므로 복원본에는 lease 행이 dump 시점 `(worker_id, lease_epoch)`를 달고 살아 돌아오고,
복원본은 사본이라 그 토큰이 양쪽에서 동시에 유효하다.

### 착수 가능 — 소유자 판정 없이 지금 할 수 있는 것

1. **`T-VN-M05-VERIFY-RECEIPT`** — V1·V2·V3 미충족. `verify_leaf`는 정말 아무것도 쓰지
   않는다(`m05_isolated_e2e.py:2388-2405`). 다만 **V2가 요구하는 값은 전부 이미 지역변수로
   살아 있다**(pinset·Map/PinVi revision·binding의 Manager revision·claim). 두 갈래 함정:
   신뢰 경계 거부 경로(`:2445`/`:2448`)는 axis를 하나도 안 남기고 `return 1`하므로 "실패도
   남긴다"가 가장 필요한 곳이 비어 있고, V3는 조문 `:1386-1388`이 "출력을 이 절에
   기록한다"고 **명령**하고 있어 조문 정정이 함께 간다.
2. **`T-VN-M05-ONESHOT-CONSUME`** — 성공 분기가 아무것도 안 남긴다. **소비를 scoped
   `phase`로 기록하면 L8 호환이 공짜로 풀린다**(L8은 `entry.phase is None`만 본다).
   **`result.json`에 키를 추가하면 안 된다** — 런처가 정확한 키 집합을 강제해
   (`run-m05-isolated-e2e-once:505-519`) 불일치가 성공한 실행을 무조건 소각한다.
3. **`T-VN-M02-TRUNCATE-FENCE`** — 원장 서술 둘이 틀렸다(아래 §정정). 트리거를 더하는
   비용은 통합 테스트 **0곳**이다.
4. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 소유자 판정 대상이 아니다. 대체 identity
   (`feature_uuid` + unique 둘)와 fence 트리거가 이미 prod에 있고 `feature.features`는 0행이라
   데이터 이행 위험이 없다. 남은 것은 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다.
5. **`T-VN-H49` 잔여** — `geo` 예약 성공 2건 더 쌓이기를 기다리는 것과 문서 갱신뿐이다.

### 소유자 판정 대기 — 둘

~~`T-VN-H49` manual Feature hard purge 정책~~ — **2026-09-08 판정·구현 완료**(migration
306). 감사되는 운영 명령으로 열되 UI 버튼이 아니고, purge가 자기 복구점을 담아 H43
보류에 묶이지 않게 했다. claim의 두 역할을 갈라 tombstone을 관리 가능하게 했고 ADR-093에
개정 한 문장을 박았다. 상세는 `docs/tasks-acceptance.md` §T-VN-H49.

1. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·**root가 쓸 수 있는** ssh 키. 코드는 이미 있다
   (`offbox_backup_sync.py`, CLI, 상태 API). `/opt` `.env`에 `KTDM_OFFBOX*` 0개.
2. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가. 새 선행 항목을 세울
   것인가, 아니면 removal manifest에서 (c)를 뺄 것인가(frozen 계약 개정).

**보류/제외 셋**: `T-VN-41C`·`T-VN-H43`·`T-101` — 셋 다 재개 조건이 아직 발화하지 않았다
(41C·H43은 실 production 전환, T-101은 SLO 정의와 ADR-073 의미 택일).
**외부 추적**: `GM-17`(가장 마지막).

### 정정 — 이전 실측 둘이 틀렸다

- **"n150에 예약 백업이 아예 없다"는 틀렸다.** `digitie` crontab에 `geo_dagster`·
  `concierge`·`pinvi` 셋이 매일 돌고 2026-08-21부터 **18일 연속 성공**했다. root로 실행한
  조회가 `/root/backups`를 봤고 cron은 `KTDM_BACKUP_ROOT=/home/digitie/backups`를 쓴다 —
  **다른 디렉터리를 보고 "없다"고 적었다.** `map_application`이 어느 cron에도 없는 것은
  `T-VN-H43`의 의도된 보류다.
- **"TRUNCATE CASCADE가 hard-purge fence를 통째로 우회한다"도 틀렸다.** CASCADE 폐포 30개
  중 10개에 BEFORE TRUNCATE 가드가 켜져 있어 실제로는 중단된다. fence가 그 거부에 기여하지
  않고 진단이 엉뚱한 이유를 대는 것이 진짜 결함이다. "통합 테스트 24곳"도 **14곳**이고,
  `_db_cleanup.py:49`가 이미 `session_replication_role = replica`로 돌아 트리거를 더해도
  **0곳이 깨진다**. 원장이 놓친 더 큰 구멍은 `ops.feature_requests`로, TRUNCATE 가드도
  append-only 가드도 없다.
- **`~/ktm-live-301`은 "정지"가 아니라 사라졌다** — 컨테이너도 볼륨도 없고, 그 체크아웃은
  302 head이며 해당 spec 자체가 없다. `T-VN-M02` live acceptance는 재기동이 아니라 재구축이
  선행이다.


## 2026-09-06 — D2 lane이 api-audit까지 완주했다

| 항목 | 상태 |
|---|---|
| pinset | Map `631f1abc` + PinVi `b9637375` |
| `T-VN-D2-API-AUDIT` | **완료** — `ktdm-d2-008` `phase: passed`, runner exit 0 |
| lifecycle | 56 = 7 operation × 8 phase (`helper-api-audit` 8개) |
| evidence | `phase: evidence-validated`, 파일 집합 exact, FK 제약 18, 리포트 2 |
| api-audit | counts 3·1·7·3, FK 18/8, `feature_ids`·`feature_uuids` 각 1건 |
| 선행 축 | ACL preflight 55/55, D1 11 passed |

`feature_id` 규칙은 서로 다른 실행이 만든 Feature **셋**으로 배포 DB에서 확인했다 —
새 규칙(uuid 재현) 3/3 일치, 구 규칙(run_id 재계산) 3/3 불일치.

### 다음 한 작업

**2026-09-07 소유자 판정 4건이 들어왔다.** 열린 항목은 15 → **11**이 됐다(보류/제외 3 포함).

| 판정 | 결과 |
|---|---|
| 승격 정의 변경 | `T-VN-M05-ACTIVATION` — 문서 행위가 아니라 **재계산 가능한 대조**로 정의. Manager `--verify-leaf`가 해시 사슬과 살아 있는 pin registry를 대조한다. 서명은 근거에서 뺐다(키가 실행마다 새로 생겨 사후 검증 불가) |
| 과대 계상 삭제 | `T-VN-M02`에서 backup/restore 축 제거 — 소유는 `T-VN-H49` 계열 |
| H34는 CSV만 | `T-VN-H34` **완료**. 범위 밖 넷은 지우지 않고 acceptance에 남겼다 |
| D1이 자격증명을 갚음 | `T-FE-MOCK-FLAKE` **완료** |

**착수 가능 — 순서대로.**

1. `T-VN-M02` **spec 회수** — 미병합 브랜치 유실 위험. 판정과 무관하게 먼저.
2. `T-VN-H49` 자식 셋 복원 리허설 — Manager `rehearse-restore` 결함을 고쳐 배포한 뒤
   실행한다(`geo_dagster`·`concierge`는 백업 0건이라 `create` 선행).
3. `T-VN-M04` — 조문을 세웠고 reject 통합 테스트를 더했다. CI green이면 닫힌다.

**소유자 판정 대기 — 여섯.**

1. `T-VN-M05-ACTIVATION` A2 — "실행은 단 한 번"의 기준(기계는 execution identity당 1회를
   강제한다. 한 pinset 아래 leaf가 셋 생겼다).
2. `T-VN-M02` purge 정책 — evidence cascade/orphan·권한·409 계약.
3. `T-VN-H49` 자식 셋의 리허설 **기록 위치**.
4. `T-VN-H49` 부모 — 고착 `load_jobs` 해소를 위한 prod 쓰기 승인.
5. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·ssh 키. **그리고 n150에 예약 백업이 아예 없다**
   (root crontab 없음·timer 없음·logrotate 미설치, geo·geo_dagster·concierge 백업 0건).
6. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가. 가장 큰 축이다.

**보류/제외 셋**: `T-VN-41C`·`T-VN-H43`·`T-101`. **외부 추적**: `GM-17`(가장 마지막).

## 2026-09-06 — D2 통과, receipt 승격

| 항목 | 상태 |
|---|---|
| `T-VN-M01` 활성화 | **완료** — ACL 55/55(rebuild 앞뒤 두 번) · 거부 축 4/4 403 · witness 8관계 zero-write · 성공 축 201 |
| kill-switch | `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true` (2026-09-05T20:27:59Z) |
| D2 스펙 | **in-lane 통과** — main·recovery 각 `{"counts":{"passed":2},"result":"passed"}` |
| `T-VN-41F1D-D2` | **통과** — `phase: passed` / `status: complete` (2026-09-06T01:47:03Z, runner exit 0, 1분 43초) |
| D2 증거 | `phase: evidence-validated` — 파일 집합 exact(10), lifecycle 48, FK 제약 18, 리포트 2 |
| D2 잔여물 | 독립 측정으로 0 — acceptance 소유 row 0, 라벨 컨테이너 0, BLOCKED/ACTIVE/RESULT 없음 |
| 선행 축 | 같은 pinset에서 ACL preflight 55/55 · D1 11 passed(29.9초) |
| 게이트 | 결함마다 `tests/lint/` 탐지기, 전부 변이로 red 확인 |
| pinset | Map `ab3640f8` + PinVi #535 — rebuild `48166bd2…`, generation `56d331a7…` |

### 다음 한 작업

**`T-VN-41C`의 구조적 순환에 대한 소유자 판정.** 선행 배리어는 전부 닫혔다 — D1·D2·
`T-VN-41F1D-E`·`T-VN-M01` 완료. 41C의 relay·reconciliation은 **구현이 끝나 있다**(2026-09-06
재조사가 종전 서술을 정정했다). 남은 셋 중 앞의 둘은 셋째가 풀리기 전에는 착수할 수 없다:

1. **런타임 결선** — 배포 Map 컨테이너에 `..._CACHE_TARGET_SERVICE_PRINCIPALS`가 없어 service
   표면이 401이고 relay 관계 19개가 전부 0행이다.
2. **enable 경계 구현** — PinVi가 production에서 sync enable을 거부하며, 그 조문이 기다리는
   "root-owned final C7 enable boundary"가 Manager에 없다.
3. **구조적 순환** — 켜면 `environment_sha256`이 바뀌어 rebuild가 필요한데, Manager
   `require_rebuildable_mode`는 cache-target 값이 inert여야 rebuild를 허용한다. **현
   lifecycle(rehearsal/rebuildable)에서 enable과 pinned rebuild는 상호배타다.**

셋 중 하나를 골라야 한다 — (a) lifecycle을 옮긴다, (b) Manager가 cache-target 축을
`environment_sha256` 결박에서 분리한다, (c) enable을 실 production 전환 시점까지 미룬다.
(a)는 rebuild 능력을 잃고, (b)는 Manager 계약 변경이며, (c)는 41C를 그때까지 여는 것이다.
`docs/tasks.md`의 41C 줄과 `tasks-acceptance.md` §T-VN-41C가 정본이다.

`GM-17`은 소유자 지시로 **가장 마지막**이다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정 — 이 줄이 순서를 뒤집어
적고 있었다). `GM-17`은 소유자 지시로 **가장 마지막**이다.
`T-VN-D2-API-AUDIT`(helper의 `api-audit`/`purge` 경로가 한 번도 실행된 적 없음)은 D2 완주와
분리했다 — 고치려면 clone lane의 content digest 계약까지 함께 판단해야 한다.

### 이번에 확인된 운영 사실

- **증거 계약 위반은 스펙이 통과한 뒤에야 드러난다.** `_validate_evidence`가 정확한
  파일명 집합과 action별 키를 요구하는데 그 검증이 스펙 통과 뒤에 돌기 때문이다. 그래서
  결함이 병렬로 안 보이고 배포 스택 실행 한 번에 하나씩 직렬로 나온다 — 열두 번을 그렇게
  썼다. 게이트를 로컬에서 유도해 미리 깨뜨리는 것이 그 비용의 유일한 대안이다.
- **executor 이미지를 같은 `:local` 태그로 다시 빌드하면 핀이 가리키던 이미지가 사라진다.**
  live attestation이 image ID를 exact로 들고 있어 재빌드 순서를 지켜야 한다.
- **`rolinherit=false`라 privilege 확인에 `::regclass`를 쓸 수 없다.** Map 역할 전부가
  NOINHERIT이므로 preflight는 catalog join으로만 판정한다.


## 2026-09-05 — 새 pinset에서 D1 통과, D2는 helper 결함 셋을 고치고 재실행 대기

`af6d7061`(Map `c72456f6` + PinVi `f4401659`)로 rebuild를 마쳤고, attestation을 재발행해
verifier가 PASS했다. D1은 통과했다. D2는 seed에서 죽었고 원인 셋을 전부 고쳐 실 DB에
대고 seed → cleanup → audit을 통과시켰다.

| 항목 | 상태 |
|---|---|
| pinset | **`af6d7061`** = Map `c72456f6` + PinVi `f4401659` |
| rebuild | 성공 (`2acd8e97…`, generation `31622c79…`) |
| host attestation v4 | 재발행 `10ad0f0f…` — **verifier PASS** |
| C7 executor image | `sha256:f760bf6c…` (라벨 `c72456f6`) |
| `T-VN-41F1D-D1` | **통과** — 데이터 비의존 live UI 11/11, 33.2초, 핀 자신의 스펙 바이트로 실행 |
| `T-VN-41F1D-D2` | helper 결함 셋 수정 완료, 실 DB 사이클 통과. **재실행 대기** |
| D2 lane 상태 | `BLOCKED` 해제 — 잔여물 0 실측 후 `clear-blocked`, 증거는 `adjudicated-…`에 보존 |

### 다음 한 작업

**helper 수정을 머지한 뒤 pinset을 한 번 더 돌린다.** 설치 스냅샷 디렉터리 이름이
`E2E_C7_EXPECTED_GIT_COMMIT`에 결박돼 있고 그것이 attestation의 `repository_commit`·
generation의 `map_source_revision`과 exact여야 하므로, Map revision이 바뀌면
rotate-pair → rebuild → attestation 재발행 → 스냅샷 재설치 → executor 이미지 재빌드 →
D1 → D2가 따라온다. 전 과정이 이번에 스크립트로 남았다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정). `GM-17`(Manager production compose
required-set 완화)은 소유자 지시로 **가장 마지막**이다.

### 이번에 확인된 운영 사실

- **out-of-band DB 패치는 다음 rebuild에 증발한다.** 어제 배포 DB에 손으로 준
  `GRANT SELECT ON public.alembic_version TO ktm_feature_migrator`가 rebuild로 사라졌고,
  그래서 helper의 진짜 결함이 드러났다. DB가 선언된 계약으로 수렴하는 건 좋은 성질이지만
  그런 패치에 기댄 green은 근거가 되지 못한다.
- **rebuild가 `BLOCKED` lane을 가로지르면 `recover`가 구조적으로 불가능하다.**
  `begin-recovery`가 BLOCKED의 execution identity와 현재 identity의 일치를 요구하는데
  rebuild가 여섯 필드를 전부 바꾼다. 이때의 정본 경로는 잔여물을 직접 측정해 0임을 확인한
  뒤 `clear-blocked`로 정리하고 증거를 남기는 것이다.

### 남아 있는 소유자 판정

- `docker/*.py` 여섯 파일이 `mypy --strict` clean인데도 검사 밖이다(n150 실측). 프로덕션
  기동을 막는 `application-schema-final-permit.py`가 그중 하나다. 편입 비용은 0이지만
  `application-schema-fresh-finalize.py`(5건)·`dagster-storage-migrate.py`(4건)는
  정리가 필요해 경계를 어디에 둘지가 판단이다.
- CI의 mypy는 핀이 없다(`mypy>=1.10`). 새 mypy 릴리스가 검사를 조이면 무관한 PR에서
  `lint` job이 붉어질 수 있다 — 기존 세 스텝도 같은 노출을 갖는다.
