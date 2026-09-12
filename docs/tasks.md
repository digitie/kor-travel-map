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


- [ ] T-VN-41C — **cache-target consumer enable** — **보류**(소유자 지시 2026-09-07)

  relay·reconciliation 구현은 끝나 있고 남은 것은 런타임 결선과 enable인데, 현
  lifecycle에서 enable과 pinned rebuild가 **상호배타**다. 실 production 전환
  시점까지 미룬다.


- [ ] T-VN-M02 — **Feature origin/provenance live acceptance 실행**

  구현 축은 전부 충족이고(2026-09-07 4축 실측) purge 정책은 소유자 판정으로
  `T-VN-H49` 계열로 이관했다. 남은 것은 회수한 `admin-manual-feature-create.live.spec.ts`를
  격리 스택(n150 `~/ktm-live-301`)에서 완주시키는 것 하나다 — prod에서는 돌리지 않는다.


- [ ] T-VN-H43 — **Map DB 백업 주기화·외부 사본** — **보류**(소유자 지시 2026-08-06)

  기준선 dump·sha256·rollback은 완료됐다. 남은 정기화·2차 외부 사본은 현 환경에서
  수행하지 않는다(n150은 실 production이 아니며 손상 시 재적재가 정책).
  off-box 자동화의 현 소유자는 `T-VN-H49-OFFBOX`다.

- [ ] T-VN-H49 — **Geo application DB backup/retention 운영 증거 + hard purge 정책**

  `scheduled_backup`·retention janitor의 수렴을 보인다. 수납했던 manual Feature hard
  purge 정책은 2026-09-08 소유자 판정으로 열려 migration 306이 구현했다. **geo 예약
  성공 누적은 2026-09-11 실측으로 닫혔다**(09-07~09-10 연속 4건, 08-24·08-25는 GC가
  실제로 지웠다). 남은 것은 off-box 사본 결선(`T-VN-H49-OFFBOX`)뿐이다.


- [ ] T-VN-H49-OFFBOX — **off-box 복제 자동화 결선과 backup 문서 현행화**

  코드가 아니라 운영 결선이 남았다 — 목적지 호스트·계정·ssh 키가 소유자/운영자
  몫이고, 그 뒤 env와 crontab 한 줄이다. `/opt`의 `.env`에 `KTDM_BACKUP_ROOT`가
  없어 logrotate가 설치되지 않은 것도 이 축에서 함께 닫는다.

- [~] T-VN-DAGSTER-STORAGE — **prod Dagster run의 성공/실패 신호를 믿을 수 없다**

  로컬 쓰기가 봉인된 `DAGSTER_HOME`으로 가 run이 FAILURE로 표시되고 compute log가
  남지 않는다. 적재 자체는 막지 않는다. 설정은 #1216이 고쳤고, 남은 것은 배포 뒤
  run 하나가 SUCCESS로 끝나는 실측이다. 해제 조건은 acceptance §T-VN-DAGSTER-STORAGE.

- [ ] T-VN-D2-RESIDUE — **D2가 run마다 은퇴 Feature 1행을 prod에 남긴다**

  D2는 소유 Feature를 은퇴까지만 끌고 가고 삭제는 `purge`가 하는데, 그 action이
  D2 lane의 `run_helper` 선택지에 없다. 해제 조건은 acceptance §T-VN-D2-RESIDUE.

- [ ] T-VN-CURATION-SEAL-ACL — **적재 seal 함수를 적재 role이 실행할 수 없다**

  prod 적재가 `permission denied for function current_provider_curation_input_set`로
  멈춘다. snapshot이 아닌 모든 provider 적재가 그 함수를 부른다. 해제 조건은
  acceptance §T-VN-CURATION-SEAL-ACL.

- [ ] T-101 — **cluster rollup materialized view 도입 검토** — **보류/제외**(소유자 지시 2026-09-07)

  하지 않는다. 재개하려면 목표 SLO 정의와, exact-viewport(ADR-073 accepted 계약)
  vs region-total 의미 택일이 선행한다 — 후자는 ADR 개정과 PinVi 소비자 계약
  변경을 함께 부른다.
