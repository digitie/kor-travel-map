# tasks.md — 활성 작업

이 문서는 완료되지 않은 작업만 의존 순서대로 한 줄씩 나열한다. lane, 병렬 담당자,
계층형 하위 작업은 사용하지 않는다. 완료 이력은
[`docs/tasks-done.md`](tasks-done.md), 현재 실행 증적과 다음 한 작업은
[`docs/resume.md`](resume.md)가 정본이다. **각 항목의 해제 조건(acceptance
criteria)은 [`docs/tasks-acceptance.md`](tasks-acceptance.md)가 소유한다** —
2026-08-27 평면화(`6d671ef1`)가 열린 항목의 판정 근거까지 지웠고, 그 직후
`T-VN-FINAL-REBUILD`가 조건이 사라진 상태로 완료 처리된 사고가 있었다.

**entry는 [`docs/tasks-rule.md`](tasks-rule.md) §5 형식을 지킨다 — 제목 한 줄 +
1~3문장.** 실측 서사·정정 이력·해제 조건 본문은 여기 적지 않는다(그것들의 자리는
acceptance·journal이다). 2026-09-07 정리 직전 6개 항목이 최대 703자까지 부풀어
acceptance 본문을 중복하고 있었고, 그 중복본 안에 **낡은 식별자**가 살아 있었다
(`T-VN-M05-ACTIVATION`이 두 pinset 전의 값을 현재형으로 적고 있었다).
`tests/lint/test_task_ledger_conventions.py`가 길이를 강제한다.

**외부 저장소 항목**은 규약 §6에 따라 여기 세지 않고 "외부 추적"으로만 둔다.
현재 하나다 — `GM-17`(Manager production compose required-set 완화). 소유자 지시로
**열린 항목 중 가장 마지막**이고, 착수 전 오너와 범위 재확인이 조건이다. 정본은
`kor-travel-docker-manager` 저장소의 `docs/general-mgmt-audit.md`와 `docs/tasks.md`다.

**보류 항목**은 규약 §6에 따라 잔여로 계산하지 않는다. 현재 셋이다 —
`T-VN-41C`·`T-VN-H43`·`T-101`. 각각 사유와 재개 조건을 아래 줄에 적는다.

- [~] T-VN-M05-ACTIVATION — **M04/M05 live acceptance attestation 승격**

  격리 본문이 현 pinset `b229446a`(Manager `0406b14d`)에서 통과했고 m04·m05
  attestation이 그 실행의 산출물로 남아 있다. 승격은 문서 행위가 아니라 PinVi의
  서명 activation receipt 발급·배포이며, 그 실행 여부가 소유자 판정이다.

- [ ] T-VN-41C — **cache-target consumer enable** — **보류**(소유자 지시 2026-09-07)

  relay·reconciliation 구현은 끝나 있고 남은 것은 런타임 결선과 enable인데, 현
  lifecycle에서 enable과 pinned rebuild가 **상호배타**다. 실 production 전환
  시점까지 미룬다.

- [~] T-FE-MOCK-FLAKE — **admin UI logs acceptance의 live 절반**

  mocked checkpoint는 PR #1045·#1059·#1077로 해소됐다(HEAD에서 재계산 확인: 284
  tests, manifest sha 일치). live 절반은 `logs.live.spec.ts` 2건이 배포 스택에서
  4회 통과했으나, 해제 조건이 요구하는 "승인된 읽기 전용 자격증명" 해석이 소유자
  판정으로 남아 있다.

- [ ] T-VN-M02 — **Feature origin/provenance 보존·불변성 live acceptance**

  spec이 **미병합 브랜치**(`feat/m01-m02-live-acceptance`, main 대비 64 behind /
  2 ahead)에만 있어 유실 위험이 있다 — 회수가 먼저다. purge 정책과
  backup/restore 소유권 두 조건은 소유자 판정이다.

- [~] T-VN-M04 — **범용 Feature 요청 큐**

  구현은 병합됐다(#1029, PinVi #458·#465). 남은 paired request→approval receipt를
  `T-VN-41C`에 위임한다고 적혀 있었으나 **받는 절이 그 범위를 수락한 적이 없다**
  (dangling pointer) — 위임을 걷고 자기 해제 조건을 갖는 것이 선행이다.

- [~] T-VN-M05 — **provider 발행 Feature 중복 판정 계약(ADR-097)**

  판정 계약과 그 결과의 paired 전파가 대상이다. acceptance 절에 판정 가능한 해제
  조건 문단이 없어 ADR-097 §후속 4항목을 옮기는 것이 선행이다.

- [ ] T-VN-H34 — **공식 curation 미연결 membership**

  코드·엔드포인트는 배포 완료다. 남은 두 조건(전수 후보 조사, prod import)이 현
  prod에 없는 데이터를 전제하는데 **pinned rebuild가 매번 DB를 새로 만든다** —
  범위를 저장소 CSV 수준으로 재정의할지가 소유자 판정이다.

- [ ] T-VN-H43 — **Map DB 백업 주기화·외부 사본** — **보류**(소유자 지시 2026-08-06)

  기준선 dump·sha256·rollback은 완료됐다. 남은 정기화·2차 외부 사본은 현 환경에서
  수행하지 않는다(n150은 실 production이 아니며 손상 시 재적재가 정책).
  off-box 자동화의 현 소유자는 `T-VN-H49-OFFBOX`다.

- [ ] T-VN-H49 — **Geo application DB backup/retention 운영 증거**

  `scheduled_backup`·retention janitor가 최근 성공과 bounded retention으로
  수렴하는지 보인다. 고착된 queued `load_jobs` 행 해소에 prod DB 쓰기 또는 geo
  admin API 호출이 필요해 소유자 승인이 선행한다.

- [ ] T-VN-H49-GEO-DAGSTER — **geo_dagster metadata DB standalone backup 검증**

  잔여는 복원 리허설 1회와 그 기록이다. `ktdctl db-backup rehearse-restore
  geo_dagster`로 즉시 착수 가능하다.

- [ ] T-VN-H49-CONCIERGE — **Concierge standalone backup 검증**

  잔여는 복원 리허설 1회와 그 기록이다. 즉시 착수 가능하다.

- [ ] T-VN-H49-PINVI — **PinVi standalone backup 검증**

  잔여는 복원 리허설 1회와 그 기록이다. 즉시 착수 가능하다.

- [ ] T-VN-H49-OFFBOX — **off-box 복제 자동화 결선과 backup 문서 현행화**

  코드가 아니라 운영 결선이 남았다 — 목적지 호스트·계정·ssh 키가 소유자/운영자
  몫이고, 그 뒤 env와 crontab 한 줄이다. `/opt`의 `.env`에 `KTDM_BACKUP_ROOT`가
  없어 logrotate가 설치되지 않은 것도 이 축에서 함께 닫는다.

- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  legacy TEXT `feature_id` PK 물리 제거가 본체이고 이 백로그에서 가장 큰 축이다.
  removal manifest (c)의 대체물 `provider_sync.notice_states`가 **미구현이고 소유
  항목이 없다** — 그것을 어디가 소유할지가 소유자 판정이다.

- [ ] T-101 — **cluster rollup materialized view 도입 검토** — **보류/제외**(소유자 지시 2026-09-07)

  하지 않는다. 재개하려면 목표 SLO 정의와, exact-viewport(ADR-073 accepted 계약)
  vs region-total 의미 택일이 선행한다 — 후자는 ADR 개정과 PinVi 소비자 계약
  변경을 함께 부른다.
