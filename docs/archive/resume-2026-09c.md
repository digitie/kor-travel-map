# resume — 2026-09-15 ~ 2026-09-16

[현행 resume](../resume.md)에서 크기 상한에 따라 분리했다.

## 2026-09-16 (4) — 백업 알림은 보류, 대신 진행 중이던 사고를 고쳤다

**다음 한 작업: `T-VN-H49` 또는 `T-VN-H49-OFFBOX`** — `T-VN-H49-BACKUP-STALENESS`
조문 1(알림 경로)은 **소유자 지시로 보류**한다.

**보류 전에 얻은 것.** `geo_dagster`·`concierge`·`pinvi` 백업이 09-12부터 5일째
`Permission denied`로 실패 중이던 것을 찾아 고쳤다(git이 `scripts/*.sh` 실행 비트를
벗겼고 crontab은 경로를 직접 실행한다). 조문이 열려 있는 동안 같은 형태가 세 DB에서
재발한 것이다.

**원장 정정.** 조문 1의 "(a) api 컨테이너만 마운트한다"는 틀렸다 — api·dagster 둘 다
`backup_root`가 없고, Dagster op config schema엔 키 자체가 없으며, 자동 기록되는 F9
행은 예외 없이 `observed=false`다. 그리고 **없는 디렉터리가 진짜 중단과 같은 신호**가
되는 F9 결함은 알림과 독립이라 따로 고칠 수 있다.

**재개할 때 첫 일은 채널 실배달 육안 확인이다.** 설계는 확정돼 있다(소유권 →
`kor-travel-docker-manager`, 채널 → ntfy). 기대치 모델 초안이 그 저장소에 미커밋으로
있다: `config/backup-policy.yml` · `services/backup_policy.py` ·
`services/backup_watchdog.py`. 소비자가 없어 커밋하지 않았다.

**열린 항목(활성 셋):** `T-VN-H49-BACKUP-STALENESS` 조문 1(**보류**) ·
`T-VN-H49` · `T-VN-H49-OFFBOX`. 보류 셋: `T-VN-41C` · `T-VN-H43` · `T-101`.


## 2026-09-16 (3) — M02·LEDGER-ARCHIVE 완주. 활성 항목이 H49 계열 셋만 남았다

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

**`T-VN-LEDGER-ARCHIVE`도 함께 닫았다.** 조문 2·3은 #1239가 이미 넣은 것이었는데 표기만
열려 있었다. 오늘 원장이 다시 220 KiB를 넘어 그 도구를 **실전에서 썼고**, 닫힌 절 둘을
검산 통과 후 옮기고 넷을 이유와 함께 거절했으며, 삭제 게이트가 아카이브 미커밋 상태를
잡아냈다 — 코드가 있다는 것보다 강한 근거다.

**열린 항목(활성 셋, 전부 H49 계열):** `T-VN-H49-BACKUP-STALENESS` 조문 1 ·
`T-VN-H49` · `T-VN-H49-OFFBOX`.
**보류 셋**(잔여로 세지 않음): `T-VN-41C` · `T-VN-H43` · `T-101`.

**오늘 네 번 낡은 기록에 막혔다** — `T-VN-D2-RESIDUE`(나흘), `T-VN-DAGSTER-STORAGE`
조문 1(배포가 증거를 지움), `T-VN-M02`(여드레), `T-VN-LEDGER-ARCHIVE`(사흘). 넷 다
**일이 남아서가 아니라 기록이 따라가지 않아서** 열려 있었다. `docs/tasks-rule.md` §6이
이 형태를 다루지만 규약만으로는 부족하다 — 조문을 닫는 PR이 그 조문을 실제로 닫는지
보는 장치가 없다.


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


