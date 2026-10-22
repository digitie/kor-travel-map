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
현재 둘이다 — Manager compose의 `KOR_TRAVEL_MAP_KMA_*` env 제거(ADR-104/105 뒤 Map이 읽지
않는 키다. 2026-10-13 Manager 저장소에서 진행 중이며 정본은 그 저장소의 PR이다)와
`GM-17`(Manager production compose required-set 완화). 소유자 지시로
**열린 항목 중 가장 마지막**이고, 착수 전 오너와 범위 재확인이 조건이다. 정본은
`kor-travel-docker-manager` 저장소의 `docs/general-mgmt-audit.md`와 `docs/tasks.md`다.

**보류 항목**은 규약 §6에 따라 잔여로 계산하지 않는다. 현재 셋이다 —
`T-VN-41C`·`T-VN-H43`·`T-101`. 각각 사유와 재개 조건을 아래 줄에 적는다.

**reconcile sensor 재시도(ADR-111 후속)** — `T-RECONCILE-RETRY`는 ADR-112(accepted) 결정 0-1(#1345)과 1~7 구현으로
2026-10-21 `tasks-done.md`로 이관했다.

**geo 릴리스 재지오코딩 묶음(ADR-109 accepted, 2026-10-16 구현)** — 전부 닫혔다(`T-GR-00`·`T-GR-00-LEDGER`는 2026-10-15, `T-GR-01`~`08`은 2026-10-16~17
`tasks-done.md`로 이관). 접두사 `T-GR-`는 그대로 쓴다(ADR-109 열린 결정 7 결론 — `tasks-rule.md` §3 묶음 prefix). 운영은 runbook `geo-release-regeocode.md`.
설계 정본은 ADR-109 + `docs/etl/address-geocoding.md`, PR 묶음은 acceptance §T-GR-00.

**geo·transport 호스트 odroid 이전 묶음(ADR-110 proposed, 2026-10-13, Track 2)** — 2026-10-19 T-MAP-02 현재 설치 수용은 tasks-done으로 이관했다. 아래 계획은 이력이다. `T-MAP-02`(`T-MAP-01`은 2026-10-15 이관) — 목록 위치일 뿐
의존이 아니다. 접두사 `T-MAP-`는 **임시**다(ADR-110 열린 결정 5). 호스트 플립 자체는
외부 저장소(Manager ADR-58·geo ADR-070·transport ADR-014 — 셋 다 proposed로 머지)의 일이라 여기 세지 않는다 — 실제 이전은
2026-10-14~15 일어났다(ADR-110 사실 갱신 절). 의존:
T-MAP-02는 설계 §13의 MGR → (TRN/WEA/GEO) → MAP 사슬과 달리 코드
의존이 없다고 보고 병렬 착수를 **제안**한다(ADR-110 열린 결정 6, 소유자 확인) — 선행은 **T-GR-00-LEDGER**(journal
분리 — 2026-10-15 이관), `geocoding.py`를 T-GR-01과 공유하므로 늦은 PR이 리베이스, 배포는 원래 **transport 플립(설계
§11.2 4a) 전**이었으나 플립이 먼저 일어나 이제 **가능한 한 빨리**다(acceptance §T-MAP-02 2026-10-15 소유자 결정 — 머지 뒤 첫 prod 배포).


- [ ] **prod Map/PinVi outage — pinned-rebuild journal이 pinset `3705983b`에서 영구 고착** — **보류**(소유자 지시 2026-09-20, weather/concierge/geo/pinvi/map DB 통합을 먼저 진행)

  회전·rebuild는 돌았으나 compose-up 단계 반복 실패로 prod의 map-api/ui/dagster·
  pinvi-api/web/dagster가 전부 내려가 있다(DB는 안전, `312_route_geometry_sidecar`로
  정확히 재생성됨). 원인·해제 조건은 `docs/resume.md` 2026-09-20 (2) 항목 참조 —
  요약: PinVi에 실제 커밋 하나 → 새 pinset → `chain17.sh` 재실행.

- [ ] T-VN-41C — **cache-target consumer enable** — **보류**(소유자 지시 2026-09-07)

  relay·reconciliation 구현은 끝나 있고 남은 것은 런타임 결선과 enable인데, 현
  lifecycle에서 enable과 pinned rebuild가 **상호배타**다. 실 production 전환
  시점까지 미룬다.


- [ ] T-VN-H43 — **Map DB 백업 주기화·외부 사본** — **보류**(소유자 지시 2026-08-06)

  기준선 dump·sha256·rollback은 완료됐다. 남은 정기화·2차 외부 사본은 현 환경에서
  수행하지 않는다(n150은 실 production이 아니며 손상 시 재적재가 정책).
  off-box 자동화의 현 소유자는 `T-VN-H49-OFFBOX`다.

- [ ] T-VN-SEED-RECEIPT-HEADAWARE — **seed 영수증이 마이그레이션의 registry 정정을 막는다**

  `ops.feature_override_field_paths`가 rev 300 seed 영수증으로 봉인돼 있어
  312가 `route.geom`의 `target_relation`을 새 relation으로 못 옮긴다(옮기면 fresh
  300 배포가 영수증 불일치로 멎는다). catalog 쪽은 `_sealed_destination_catalog`가
  이미 head-aware로 풀었고 seed 쪽에는 그 처리가 없다.

- [ ] T-VN-H49-BACKUP-STALENESS — **백업이 멈춰도 아무도 몰랐다**

  `scheduled_backup`이 425건 연속 실패하는 동안 5일간 경보가 없었다(2026-09-16 발견,
  webserver 재기동으로 복구). 진짜 결함은 멈춘 것이 아니라 **멈춘 줄 몰랐다**는
  것이다. 해제 조건은 acceptance §T-VN-H49-BACKUP-STALENESS.

- [ ] T-VN-H49 — **Geo application DB backup/retention 운영 증거 + hard purge 정책**

  `scheduled_backup`·retention janitor의 수렴을 보인다. 수납했던 manual Feature hard
  purge 정책은 2026-09-08 소유자 판정으로 열려 migration 306이 구현했다. **geo 예약
  성공 누적은 2026-09-11 실측으로 닫혔다**(09-07~09-10 연속 4건, 08-24·08-25는 GC가
  실제로 지웠다). 남은 것은 off-box 사본 결선(`T-VN-H49-OFFBOX`)뿐이다.


- [ ] T-VN-H49-OFFBOX — **off-box 복제 자동화 결선과 backup 문서 현행화**

  코드가 아니라 운영 결선이 남았다 — 목적지 호스트·계정·ssh 키가 소유자/운영자
  몫이고, 그 뒤 env와 crontab 한 줄이다. `/opt`의 `.env`에 `KTDM_BACKUP_ROOT`가
  없어 logrotate가 설치되지 않은 것도 이 축에서 함께 닫는다.

- [ ] T-101 — **cluster rollup materialized view 도입 검토** — **보류/제외**(소유자 지시 2026-09-07)

  하지 않는다. 재개하려면 목표 SLO 정의와, exact-viewport(ADR-073 accepted 계약)
  vs region-total 의미 택일이 선행한다 — 후자는 ADR 개정과 PinVi 소비자 계약
  변경을 함께 부른다.

- [ ] T-WX-SOURCEROLE — **`SourceRole.WEATHER_CONTEXT` 퇴역 migration(선택)**

  ADR-105 뒤 생산자가 없다. enum 값과 `source_links` CHECK를 함께 좁히는 migration이
  필요하다. 남은 행이 0인지 먼저 확인한다.

- [ ] T-WX-DTO — **`WeatherValue` DTO·weather enum 삭제 여부 결정**

  ADR-105가 정의 유지로 남겼고 API 재도입 방지 검사가 그 정의에 기댄다. 지우려면 그
  검사를 kind/provider 정체성만으로 다시 써야 한다.

- [ ] T-LOAD-LOCK-WAIT — **동시 provider 적재가 `feature-curation-write`를 30초만 기다리고 55P03으로 죽는다**

  2026-10-22 n150에서 다섯 dataset이 3회 재시도 끝에 실패했다. 소유자 결정은 "1안 지금(적재 쪽 대기 상한만 늘림),
  2안 나중(쓰기 단계의 잠금 보유 축소)"이다. 해제 조건은 acceptance §T-LOAD-LOCK-WAIT.
