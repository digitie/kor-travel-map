# resume 아카이브 — 2026-09

[현행 기록](../resume.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다.

## 2026-09-29 — 공유 Dagster plane Map 준비(stage 0 + 3.1): 브랜치 `feat/dagster-shared-stage0`

**다음 한 작업: 브랜치를 CI 전량으로 확인하고 적대 리뷰 뒤 머지 → 다음 Map+PinVi pinned pair(chain17)로 배포.**

배포 체크리스트:

- [ ] **배포 전제(pool 이름 변경)**: pool을 쓰는 job의 QUEUED·STARTING·STARTED run이 0건이다. 확인은
  `docs/runbooks/docker-app.md` "pool 이름 변경 배포의 전제"의 읽기 전용 검사(exit 0)로 한다. 0건을 못 만들면 writer
  drain 아래에서 배포한다.
- [ ] 배포 뒤: 세 컨테이너의 `site-packages`에서 constraints에 나열한 패키지가 그 버전인지 본다(나열한 것만 고정).
- [ ] 배포 뒤: admin 운영 홈·pipeline 화면(runs 패널·run 상세)이 그대로인지 본다.

- 이미지·CI: `docker/constraints-dagster.txt`(나열한 패키지의 정확한 버전)를 API·Dagster Dockerfile과 CI 설치가
  `-c`로 읽는다. 올릴 때는 공유 host 이미지 먼저, 이 파일 나중.
- API/UI/C7/게이트의 Dagster 조회는 Map code location으로 좁혀졌다(journal 참조). pool은 `kor_travel_map.` 접두사.
- D4: Map은 DB에만 켜진 instigator가 없다(읽기 전용 확인). 남은 판단: run-status sensor의 `monitor_all_code_locations`.

## 2026-09-29 — Map DB 공용 PostgreSQL 이전 완료

**다음 한 작업: 72시간 관찰(~2026-10-02 11:30Z) 뒤 소유자 수락을 받아 12700 컨테이너 은퇴(§4.6, 수동, PGDATA 보존).**
관찰은 n150 `sudo MOVE_DIR=/root/map-db-move-20260929 bash /root/map-db-move-20260929/bin/40-monitor.sh <SINCE>`
(30분마다, ALARM은 기록용). 되돌리기는 같은 디렉터리의 `30-rollback.sh move`.

- Map `kor_travel_map`·`kor_travel_map_dagster`가 이제 `kor-travel-shared-postgres`(11000) 안에 있다(ADR-103, Manager ADR-53).
- Manager: #438 MT(공용 튜닝: shared_buffers 1GB·work_mem 64MB·max_wal_size 2GB·pg_prewarm 모든 DB·shm 1gb),
  #439 M2(이전: S1 — 새 superuser 없이 `shared_admin`을 부트스트랩 one-shot에만 secret 파일로, 백업 role 공용으로, D10).
  설치본 `3b282a7a`. 그 전 #434(stop grace·--no-deps), #435 M1(펜스·격리·연결 상한 38).
- 창(2026-09-29, `F:\dev\handoff\window\` 스크립트): Part A 10:25Z 공용 재생성(A7 20분 게이트 통과, 크래시 0·DSM 0) →
  Part B fence 10:55Z(감사 dump 12700에서) → M2 설치·env(DSN→11000) → rebuild(adopt, 3분, deployed) →
  verify V1~V7 0 FAIL → chain16 V8(ACL 40/40, D1 11, D2 passed) → backup V9(공용에서 dump, sha256 OK). 11:33Z 완료.
- 이전 직후 감시: 0 ALARM(연결 26/97, Map run 32 SUCCESS, prewarm leader 1, 백업 정상).
- Map 데이터는 정책대로 새로 재구축했다(features 0행이었다). 옛 ops·Dagster 이력은 감사 dump와 보존된 12700 PGDATA에 있다.

## 2026-09-28 — MP(Map DB 공용 이전의 Map 쪽 준비): 브랜치 `fix/shared-instance-readiness`

**다음 한 작업: MP를 CI 두 leg(alpine·glibc) 초록 + 적대 리뷰로 머지 → n150 호스트 스크립트를 MP SHA에서
0700 root로 재설치 → `/root/chain17.sh <MP_SHA> …`로 새 pair(MP + PinVi `c5be9eb4`)를 전용 12700 위에서
회전·D1/D2 초록.** 그 뒤 Manager 창(MT·M2)에서 이동한다(ADR-103, Manager ADR-53).

- `COLLATE "C"`: evidence export/backup twin, evidence restore, curation collection lock, cache target capture.
  감사 뒤 그대로 둔 곳과 이유는 커밋 메시지(`fix: glibc-safe text orderings …`)에 있다.
- CI `integration` 두 leg, 이미지 정본 `tests/integration/_postgis_image.py`.
- `scripts/n150/adjudicate.sh`·`repin.sh`는 Map API 컨테이너에서 DB 접근을 유도한다. `/root` 사본은 MP 머지 뒤
  재설치해야 한다(`scripts/n150/README.md` §설치, 0700 root, sha256 대조).
- MP는 OpenAPI 스냅숏을 바꾸지 않는다 — PinVi pair 계약 preflight가 그대로 통과한다.
- 적대 리뷰 반영(journal 참조): adjudicate 양성 대조, n150 스크립트의 API 컨테이너 조회를 D2 러너의 compose
  project로, repin의 source 값 대조, 효과 기반 인스턴스 탐지기, 두 lane의 수동 workflow·로컬 게이트.
  수동 `postgis-only.yml` 두 lane 초록(run 36421797357).
  - PR을 열 때 본문에 CI `integration` 두 leg의 URL을 적는다(required check가 없다).
  - 적대 리뷰 2차(09-29, journal 참조): n150 compose 조회의 stderr 차단(비밀 조각 누출), 탐지기 좁히기·유도
    결박, 판정 도구 읽기 전용 검사, 다섯째 잔여물 줄(fixture dataset), D2 러너의 fixture 대상 대조.
  - 남은 것(Map 밖, 소유자): `/opt/.env`의 `*_UI_ADMIN_PASSWORD_HASH` 넷을 작은따옴표로 감싸거나 `$$`로
    바꾸고, Map UI 관리자 비밀번호를 교체한다(hash 조각이 리뷰 transcript에 찍혔다).
  - 남은 것(Map 밖): 이동 창 사전 점검(스펙 §4.1 A0/A5)에 실행 중인 공용 컨테이너 `.Image`와
    `tests/integration/_postgis_image.py`의 `SHARED_GLIBC_POSTGIS_IMAGE` 대조 한 줄. API 이미지의
    `python -I -c 'import asyncpg'` smoke는 `docker-images.yml`이 OCI만 내보내 따로 load가 필요해 미뤘다.
- Manager ADR 번호: 이 이동은 **ADR-53**이다. ADR-52는 #433(공용 instance의 `init`·exec probe `-t 3`/`timeout 10s`·
  grace 300s·shm 512mb)이고 n150에 설치됐다(Manager `0fe0d97`, 공용 재생성 09-28 13:10:57Z). 아래 (저녁) 절의
  `stop_grace 180s`·`pg_isready -t 2`는 그 전 계획값이다.

## 2026-09-26 (오후) — t57a는 디스크 포화에 걸렸다 → 타임아웃 수정 후 재시도, 배포 모델은 마이그레이션 전진으로

**다음 한 작업: Manager #401 설치 → 이 커밋(새 pinset)으로 chain17 → code location 로드 확인 →
D1/D2.** 그다음 ADR-102/Manager ADR-51의 단계별 PR(A → M1 → M2+H1 → B1 → B2 …).

- **t57a(#399 설치본):** 후보 static inspection `ktm-application-schema head`가 60초 타임아웃으로
  죽었다(journal 전, claim 반환). 명령은 정상이다 — n150 SATA SSD가 92% 차 IO 압력 `full`이 상시
  50~60%이고, `docker run --rm /bin/true` 하나가 112초, head가 74초 걸렸다. #399가 봉인된 stage 한
  단어 대신 비밀을 가린 원인 원문을 stderr에 남겨서 재현 없이 바로 짚었다.
- **수정(Manager #401):** static inspection 60→600초, compose `--wait-timeout` 300→900초(ADR-069 뒤 Map은
  code-server → webserver → daemon 직렬 기동).
- **배포 모델 결정(소유자):** 봉인·신뢰 릴리스 단순화의 잃는 보장 A~H 전부 승인, **DB는 배포를
  넘어 보존(마이그레이션 전진)**, 리셋은 명시적 `--restart`만, 쌍 계약 preflight는 게이트 유지,
  M05 유지, n150은 rebuildable 유지, `--restart` 전 백업 강제 안 함, 급하면 구 모델 리셋 1회 허용,
  PinVi에도 forward-only ADR. → [ADR-102](../adr/102-migrate-forward-deploys-and-seal-removal.md),
  Manager ADR-51(#400), PinVi ADR-071(pinvi#566).
- **열린 것:** n150 디스크 92%·IO 포화 자체. 타임아웃은 증상 완화다.

[현행 기록으로](../resume.md)
