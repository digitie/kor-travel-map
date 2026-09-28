# ADR-103: n150 prod에서 Map DB는 공용 PostgreSQL instance 안의 전용 DATABASE다 (ADR-045 개정)

- 상태: accepted (2026-09-28) · 개정 대상: ADR-045 결정 1의 "독립 PostGIS DB", AGENTS.md "공유 DB 아님"
- 관련: Manager ADR-52

### 결정
- prod에서 `kor_travel_map`·`kor_travel_map_dagster`와 Map role 가족(`ktm_*` 19개, Dagster metadata login)은
  Manager의 공용 instance에 있다. standalone compose와 M05는 자기 `postgres`를 그대로 쓴다.
- 경계는 그대로다: 외부 소비자는 OpenAPI로만 닿는다. 다른 프로젝트 role은 Map DB에 CONNECT할 수 없다
  (Manager가 PUBLIC CONNECT를 닫는다).
- bootstrap 스크립트는 바뀌지 않는다: fresh DB에서 한 번, instance superuser로 돈다.
- prod collation은 glibc `en_US.utf8`이다. 순서가 digest·lock·Python 비교에 들어가는 text 키는 `COLLATE "C"`로
  고정하고, CI는 공용 이미지 digest에서도 통합 테스트를 돈다.

### 받아들인 위험
PG 16.15→16.9·PostGIS 3.5.7→3.5.2·musl→glibc, 공용 instance 장애 결합, fresh 재구축으로 ops/audit 이력과
비-ops 잔여 행(`feature_state_transitions` 25, manual-feature 잔재 5×3) 소실, `curated_*`·`provider_sync` 설정 행은
loader가 다시 쓸 때까지 비어 있음. bootstrap 동안 instance admin 비밀번호가 호스트 프로세스 표에 보임(후속: `PGPASSFILE`).

### 이 저장소에서 바뀐 것 (MP)
- `COLLATE "C"`: evidence export·backup twin(`principal_id`), evidence restore(lease 재구축·잠금),
  curation collection advisory lock, cache target source head capture·member 조회.
  회귀 탐지기는 `tests/integration/test_collation_sensitive_orderings_glibc.py`다.
- CI `integration` job은 `lane: alpine`·`lane: glibc` 두 leg이고, 이미지 정본은
  `tests/integration/_postgis_image.py`(`KTM_TEST_POSTGIS_IMAGE`)다.
- `scripts/n150/adjudicate.sh`는 Map API 컨테이너 안에서 읽기 전용으로 세고,
  `scripts/n150/repin.sh`는 D2 fixture DSN을 그 컨테이너의 DSN에서 유도한다. 두 스크립트에는
  instance 이름·port·superuser가 없다(`tests/unit/test_n150_scripts_have_no_instance_literals.py`).
