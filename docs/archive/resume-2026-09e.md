# resume 아카이브 — 2026-09

[현행 기록](../resume.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다.

## 2026-09-28 (저녁) — transport 개명 완료, 공용 PG 재시작 원인, Map DB 공용 이전 착수

**다음 한 작업: Map DB를 공용 PostgreSQL(11000)로 옮긴다(소유자 결정 C).** 명세·런북을 확정했고, 구현 1차
(Manager M1 펜스·MT 공용 튜닝, Map MP)가 돌고 있다. 그 뒤 M2(이전)와 이전 창이다.

- **소유자 결정**:
  - C: 위험을 받아들이고 옮긴다.
  - superuser S1: 새 superuser 없이 기존 `shared_admin`을 Manager가 돌리는 Map 부트스트랩 one-shot에만 주입한다.
    superuser가 필요한 것은 새 DB 부트스트랩 한 번뿐이다(bootstrap 게이트, untrusted 확장 postgis·pg_prewarm,
    400의 확장 소유자 검사). 런타임은 비-superuser다.
  - Map 정책대로 새로 재구축한다. 감사 dump와 옛 PGDATA는 보존하고, 검증 잔여 DB 4개는 옮기지 않는다.
  - Map 전용 튜닝을 공용에도 적용한다(`shared_buffers` 1GB, work_mem 64MB, max_wal_size 2GB, pg_prewarm이 모든 DB,
    shm 1gb, stop_grace 180s). 공용을 한 번 재시작해야 한다.
  - `kor_travel_map` 연결 상한은 floor(0.4×사용 가능 슬롯) = 38이다.
- **공용 PostgreSQL 반복 재시작 원인(유력, 적대 검증 유지)**:
  - 09-25~28에 5번 "exit code 2" 뒤 전체 재시작이 있었다(각 1~7분).
  - 실제 백엔드 크래시가 아니다. `init`이 없어 postmaster가 PID 1이다. 호스트 정체 때 `CMD-SHELL pg_isready`가
    5초를 넘기면 Docker가 `sh`만 죽이고, 고아가 된 `pg_isready`(exit 2)를 postmaster가 입양한다. PG16은 모르는
    자식의 비정상 종료도 크래시로 보고 클러스터를 리셋한다.
  - 고침은 공용 서비스에 `init: true`와 exec 형식 `pg_isready -t 2`를 두는 것이다. 튜닝 재시작에 같이 넣는다.
- **transport 배포 식별자 개명 cutover 완료**(12:24~12:33Z, transport #49 R=`b75fca1c`, 중단 약 1분).
  - Manager #432(`e2d45d65`)로 target이 `transport`가 됐다.
  - transport 백업은 Manager #430 role(16:50·17:15 UTC)로 옮겼다. 첫 dump 둘을 검증했다.
  - 72시간 관찰 뒤 정리한다(그때까지 n150 prune 금지).
- Manager #431: 백업 API 테스트의 `cancelled` flake를 고쳤다(TestClient가 요청마다 loop를 닫는 문제, 테스트만).

## 2026-09-28 — M05 격리 e2e 통과(p9), PinVi app-dagster 수정, 안 쓰는 전용 PostgreSQL 퇴역

**다음 한 작업: transport 배포 식별자 개명 cutover(창 KST 21:30~23:00) → Manager transport 백업 역할 release →
Manager 개명 release → Map DB를 공용 11000으로 이전(계획·적대 검토 중).** 모두 소유자 지시("남은 것 모두 완주")다.

- **M05 p9 PASSED**: pinset `8c9f9ad1`(Map `a18d9274` + PinVi `c5be9eb4`), Manager `88599eb9`.
  - 리허설 p9r `rehearsed` 뒤 실제 실행. `status: passed`, `phase: completed`, cleanup 실패 없음, `stderr.log` 0바이트.
  - 약 11분(06:10Z 종료). 격리 컨테이너는 모두 정리됐다.
- **막던 것과 고친 것**:
  - PinVi #570(`c5be9eb4`): #558 뒤 PinVi app compose의 `app-dagster`에 `PINVI_DAGSTER_PG_URL`과
    `pinvi_dagster` DB가 없어 항상 unhealthy였다. bootstrap 스크립트와 one-shot `app-dagster-db-init`을 넣었다.
    p9에서 db-init exit 0, dagster는 약 1분 만에 healthy.
  - PinVi #569(`5459b023`): `deploy-node.sh`의 fresh-stack 증명을 compose에서 유도한 서비스로 고쳤다.
  - Manager #428(`e25f105a`): M05 포트를 고정 기준(`28629`)부터 찾아 두 실행이 같은 빌드 입력을 준다(캐시 적중).
  - Dagster healthcheck 폭주: Manager #426 + Map #1284 뒤 운영 Dagster 컨테이너 전부가 exec 형식 probe와
    `init`으로 healthy다. 좀비 565 → 16. transport 스택만 개명 cutover 때 함께 반영한다.
- **chain17 t63b GREEN**(같은 pair): ACL 40/40, D1 11 passed, D2 passed.
  - t63a는 D1 `admin-scenario-catalog.live.spec.ts:76`이 `GET /v1/ops/datasets`를 15초 안에 못 봐 실패했다.
    같은 Map이 t62b·t63b에서 통과해 부하 flake로 본다.
- **안 쓰는 전용 PostgreSQL 퇴역**: Manager #429(`88599eb9`)가 geo·concierge·pinvi 전용 인스턴스와 airport-db를
  compose·target·백업 목록에서 지웠다. n150에서는 접속 0이던 `pinvi-postgres`(12800)만 내렸다(데이터 디렉터리 보존).
  - 백업 gc는 다른 인스턴스의 dump를 지우지 않는다(`INSTANCE_MISMATCH`).
  - n150 Manager 백업 cron(비-git 사본)이 2026-09-20 무렵부터 매일 실패하고 있었다(`compose_binds 절이 없다`).
    cron 사본을 동기화하고 수동 실행으로 확인했다.
  - `CLAUDE.md`·`docs/integration-map.md`의 DB 포트 설명을 실측(공용 11000 + map 12700)으로 고쳤다.
- **공용 PostgreSQL 비정상 재시작(원인 미상)**: 2026-09-28 03:28:57Z에 `kor-travel-shared-postgres`의 백엔드 하나가
  exit code 2로 끝나 postmaster가 전체를 재초기화했다. 복구에 약 2분 걸렸다(디스크 대기 속 pre-fsync 82초).
  OOM은 아니다. transport `/health`가 그 사이 500이었다. Map을 공용으로 옮기면 이런 사건의 영향 범위에 Map도 든다.
- **이어서**:
  - transport: PR #44가 머지돼 개명 브랜치 `chore/rename-deploy-identity-transport`를 #46 위로 rebase했다
    (`d2b7832`, 문서 밖 diff 동일). 창에서 transport 저장소 runbook "운영 식별자 개명 cutover"를 따른다.
  - Manager `feat/transport-backup-roles`: 적대 검토 MED 1건(호스트 단계 순서)을 고치는 중이다.
  - Map DB 이전: 읽기 전용 조사·계획·적대 검토 워크플로가 돌고 있다. 검증 잔여 DB 4개는 옮기지 않는다.

## 2026-09-27 — rustfs-init의 minio/mc 대체, 새 pair 사이클 t62b GREEN, M05는 n150 과부하로 BLOCKED

**다음 한 작업: n150 Dagster healthcheck 폭주를 먼저 잡고 M05를 다시 돌린다(소유자 결정 필요).**
M05 p2~p4는 본문 진입 전 인프라 phase에서 멈췄다(scoped 차단 — 실행권은 소비되지 않았고 같은 identity로 재실행된다).

- **minio/mc 소멸**:
  - Docker Hub의 `minio/mc`·`minio/minio` 저장소가 사라졌다(Hub API 404). digest 핀도 받을 수 없다.
  - M05 port(#424) 뒤 첫 실제 실행 p1이 claim 뒤 Map `rustfs-init` pull 거부로 BLOCKED됐다.
  - Map #1282(`a18d9274`), PinVi #568(`fd07903f`), Manager #425(`cc89ad9f`)로 세 저장소의 `rustfs-init`을 고쳤다.
    - 자기 rustfs 서비스와 같은 이미지의 curl(`--aws-sigv4`)로 버킷을 만든다.
    - 000과 5xx만 재시도한다. RustFS는 health 200 뒤에도 잠시 `503 storage_quorum`을 준다.
    - 요청마다 connect 5초·전체 30초 상한을 둔다.
  - 격리 실행 안에서 Map과 PinVi init 모두 `Exited (0)`을 확인했다. prod Manager `rustfs-init`도 6개 버킷 exit 0이었다.
- **새 pair**: Map `a18d9274` + PinVi `fd07903f`, pinset `ce444e8e`.
  - 회전 preflight OK.
  - chain17 **t62b GREEN**: rebuild `deployed`(Map head 400, PinVi `20260917_0102`), ACL 40/40, D1 11 passed, D2 passed.
  - t62a는 pinvi-web 빌드가 오래 조용하길래 buildx bake를 끊어 실패시켰다. 나중에 보니 레이어 export(gzip) 중이었을 가능성이 크다.
- **M05 p2~p4 (BLOCKED, 모두 `runtime_command_failed`)**:
  - p2: PinVi web 이미지 export가 약 40분 걸려 `commit failed: context deadline exceeded`.
  - p3·p4: PinVi `app-dagster`가 이미지 HEALTHCHECK(시작 60s·10s×3)를 넘겨 unhealthy.
  - 공통 원인은 n150 과부하다(load 최고 137). 운영 Dagster 스택들의 healthcheck(`dagster-daemon liveness-check`,
    `dagster api grpc-health-check`)가 매번 dagster를 import하는 Python을 띄운다. 부하가 오르면 10초를 넘겨 겹치며
    스스로 불어난다(동시 47개).
  - 좀비는 565개였다. PID 1이 자식을 거두지 않는 Dagster 컨테이너들에 있다: geo code-server 261, geo daemon 85,
    weather 78, PinVi 25, Map 20.
- **소유자에게 물을 것**:
  1. Dagster healthcheck를 가볍게 바꾸고(HTTP/grpc 대신 프로세스·포트 확인, 긴 timeout) `init: true`로 좀비를 거둔다.
     운영 스택 전부(Map·PinVi·geo·weather·airport)가 대상이고, Manager compose 재설치와 rebuild가 따른다.
  2. 또는 n150이 한가할 때 M05만 다시 돌린다(재발 가능성 높음).
- **별건**:
  - PinVi `deploy-node.sh`의 `fresh_stack_dependency_image_proof`가 main에서 이미 깨져 있다.
    `api_image_provenance.py compose-image-reference`가 app-api/web/dagster만 받아 exit 2가 난다.
  - prod `.env`의 관리 UI 비밀번호 해시 세 개가 따옴표 없이 `$`를 담고 있다. Manager 경로에서 컨테이너 값은 온전하다(해시 비교).
    다만 호스트에서 `docker compose --env-file .env`를 직접 부르면 잘린다.
  - Map·PinVi dagster-daemon이 healthcheck 타임아웃으로 `unhealthy` 표시다. 기능은 동작한다.

## 2026-09-27 — Manager ADR-51 결정 5(C6c 보호 참조 파생 규칙) 완료

**다음 한 작업: M05 격리 하네스의 Map ADR-100/101 대응.** 핀된 Map은 fresh-init 서비스를 `db-application-schema-fresh`로
부르고, `docker-compose.local-dev.yml`을 지웠고, role을 단일 LOGIN(`ktm_feature_service`)으로 바꿨다. 포팅 전까지
M05는 claim 전에 `runtime_setup_map_config`로 멈추며 실행권은 쓰지 않는다.

- **Manager**:
  - P-1 #422(`eb477467`): 설치기가 git에서 쓴 `.ktdm-release-compose.yml`을 원본으로, 자리별 보호 참조 부분집합 규칙을
    세웠다. 옛 표 검사와 병행이다.
  - P-2/P-3 #423(`784875e2`): 리터럴 표를 지웠다 — 이름 스캔, 허용 경로, sole-consumer, secret 이름 스캔, resolved의
    `.env` 재대조가 사라졌다. 내용 스캔은 값만 본다. resolved 문서에는 값 백스톱을 둔다. 변수 이름은 compose처럼
    ASCII로 읽는다.
- **n150 인수**:
  - 매 단계 `pin verify` 0, M05 preflight 0, 수렴 `converged`, 컨테이너 42개 재생성 0이다.
  - 설치된 compose는 통과한다. 누출 후보 둘은 거부된다.
  - 병합 전에 운영 데이터로 미리 돌려 보다가 bind 내용 스캔의 거짓 양성(배포 전체 차단)을 잡았다.

## 2026-09-27 — Manager ADR-51 잃는 보장 G(실패 출력 스크럽) 완료

**다음 한 작업: Manager ADR-51 compose 파생 규칙(결정 5).** 그 뒤 **M05 격리 하네스의 Map ADR-100/101 대응**. 포팅
전까지 M05는 claim 전에 `runtime_setup_map_config`로 멈춘다. 핀된 Map의 fresh-init 서비스가 `db-application-schema-fresh`인데
driver는 `-300`을 찾기 때문이다. 실행권은 쓰지 않는다.

- **Manager**:
  - G-1 #419(`95c79254`): 스크러버 하나를 CLI·API 출력 경계에 둔다.
  - G-2 #420(`8ff53b59`): 재구축 봉인을 해체하고 명령 원문 tail을 싣는다. `--json`은 `{status, stage?}`이고, claim 해제
    경로는 없앴다.
  - G-3 #421(`03729712`): M05는 항상 캡처하고, 가린 `stderr.log` 한 채널로 낸다. 생성 비밀은 생성 시 등록하고, 닫힌
    어휘는 삭제했다.
  - n150 설치.
- **n150 인수**:
  - 매 단계 `pin verify` 0, M05 preflight 0, 같은 pair 수렴 `converged`, 컨테이너 42개 재생성 0이다.
  - scrub probe 셋 모두 누출 0(비밀 71개 검사)이다.
- **Map**: `scripts/n150/chain17.sh`가 회전 preflight 사유, 회전 실패 출력, 재구축 실패의 stage와 `stderr.log` 끝을 보인다.
  운영자는 `/root/chain17.sh`로 다시 복사한다.

## 2026-09-27 — Manager ADR-51 잃는 보장 E(소스 봉인 제거) 완료

**다음 한 작업: Manager ADR-51 잃는 보장 G(실패 출력 스크럽)** — 닫힌 어휘를 원문 스크럽으로(#399가 1단계).
그 뒤 compose 파생 규칙(결정 5), 그리고 **M05 격리 하네스의 Map ADR-100/101 대응**(아래).

- **Manager**: E-1 #416(`ab20659b`, Map 계약 reader가 git 대신 source 트리 파일을 읽는다) → E-2 #417(`4fd1581e`,
  M05 본문이 실행별 checkout `runtime/{map-src,pinvi-src}`에서 돈다 — PinVi attestation 때문에 archive가 아니다)
  → E-3 #418(`13173cd9`, 재구축 source = `<state_root>/pinned-runtime-sources/<role>-<revision>/{tree,source.json}`,
  없을 때만 depth-1 fetch + `git archive`, 있으면 git 0회, 손상되면 다시 만든다). n150 설치.
- **n150 인수**: 매 단계 `pin verify` 0·M05 preflight 0·같은 pair 수렴 `converged`·컨테이너 42개 재생성 0. E-3 첫 수렴에서
  archive source 둘이 생겼고(tree id = 핀 commit, g/o 쓰기 0, 디렉터리 0755, `.git` 없음) build context 경로가 바뀌었는데도
  재생성 0, 두 번째 수렴은 `source.json`을 건드리지 않았다(git 0회). 옛 `<state_root>/pinned-runtime-sources-v5/`(827M)는
  되돌림 하한용으로 남겼다(삭제 선택, Manager `prod-deployment.md` §8.1).
- **발견 — M05 전체 실행이 Map #1259 이후 불가능하다.** E-2 검증용 실제 M05(`/root/m05-once-e2run`)가
  `runtime_loopback_publish_config_invalid`로 claim 전 거부됐다(`preflight_rejected`, 실행권 소비 없음). 원인은 E-2가 아니라
  Map #1259(2026-09-23, ADR-100 단일 LOGIN role·ADR-101 baseline 400)가 `docker-compose.local-dev.yml`을 지웠는데 M05 driver가
  아직 그 파일과 옛 role(`ktm_feature_migrator`·`ktm_feature_api_runtime`)을 쓰기 때문이다. E-2의 checkout 자체(GitHub depth-1
  fetch)는 n150에서 동작했다. 대응은 별도 작업이다.

## 2026-09-27 — Manager ADR-51 잃는 보장 D(설치기 단순화) 완료

**다음 한 작업: Manager ADR-51 잃는 보장 E(소스 봉인 제거).** pinned runtime 소스의 워크트리 불변화·
symlink·submodule 금지·로컬 origin 확인을 실행마다 `fetch` + `git archive <sha>`로 바꾼다. 그 뒤 G(실패
출력 스크럽 — #399가 1단계), compose 파생 규칙(결정 5) 순서.

- **Manager**: I-1 #414(`f0149db2`, 설치 root symlink의 소비자 이전) → n150 레이아웃 1회 전환 →
  I-2 #415(`58d25ab0`, 설치기 1,887줄 → 196줄) 머지·n150 설치.
- **n150 설치 방식이 바뀌었다**: `/opt/kor-travel-docker-manager` → 상대 symlink `ktdm-release-<sha>`,
  release는 `/opt/ktdm-release-<sha>/`(직전 하나 보존). 설치는 **root 소유 clone**
  `/var/lib/kor-travel-docker-manager/src`에서 `bash ~/install-mgr.sh <sha>`(헬퍼가 clone·checkout·
  installer 실행) → `ktdctl pin rebind-execution` → `pin verify` 0. 설치기가 항상 backend를 재기동한다.
  롤백은 옛 sha 재설치(손으로 symlink 넘기기 금지). 옛 설치기는 symlink 레이아웃을 해 없이 거부한다.
- **n150 인수**: 설치·같은 sha 재설치(5초, 빌드 없음)·I-1 롤백 왕복 모두 `pin verify` 0·M05 preflight 0,
  같은 pair 수렴 `converged`에 Manager 관리 컨테이너 42개 재생성 0, bind에 release 경로 0. release 크기
  83MB(옛 설치본은 헬퍼의 프론트 빌드로 882MB).
- **n150 디스크**: Tier 3(다른 세션 작업 디렉터리) 정리로 여유 102G → 117G. 소유자 판단 대기 항목 해소.

## 2026-09-27 — 봉인·신뢰 릴리스 단순화(Manager ADR-51 / Map ADR-102) 완료

**다음 한 작업: 없음(이 프로그램은 끝났다).** 남은 것은 ADR-51이 "그 뒤 각자"로 둔 별개 항목 —
설치기 단순화(잃는 보장 D), 소스 봉인(E), 실패 출력 스크럽(G), compose 파생 규칙 — 과 선택 정리
(B3 PR-4 launcher claim 해제, D-4 안 읽히는 evidence, Map 자신의 compose에 남은 permit volume).

- **Manager**: B2 #404 → B3 #405~#407 → C #408~#410 → **D #411~#413** 머지·n150 설치(`a3a695fa`).
  D-1 M05·`pin verify`가 `deploy-status.json`을 본다(공개 세대 API 삭제), D-2 v6 쓰기 중단·코드 삭제,
  D-3 Dagster storage permit mount 제거. 문서: PinVi #567, Map #1276.
- **최종 인수(t61a, Map `b4fbde1e` / pinset `fc39eb5c`)**: 새 pair 전체 경로 배포 — 같은 DB(oid 그대로),
  v6 파일 안 씀, permit 없음 → ACL 40/40 → **D1 11 passed → D2 passed(v4)**, lane 깨끗.
- **기록된 손실**: 공개 세대 뷰, 실패한 배포 뒤 한 번 커밋될 때까지 M05 거부, pre-M1 Map pinset으로의
  되돌림 불가(roll-forward), Manager 되돌림 하한 D-1.
- **소유자 판단 대기(유지):** n150 다른 세션 작업 디렉터리 약 18.5GB.

## 2026-09-27 — Manager ADR-51 C(락 통합) 완료: 파일 락은 G 하나

**다음 한 작업: Manager ADR-51 D**(permit mount 제거, v6 manifest 쓰기 중단, M05 driver·`pin verify`·공개 세대
API를 `deploy-status.json`으로). 선택으로 B3 PR-4(launcher claim 해제·실패 분류 이름 정리).

- **C-1 #408** 한 획득 경로(CLI pin 변이의 락 없는 두 갈래 삭제, 실제 자식 프로세스 경합 검사) →
  **C-2 #409** rehearsal의 UI/API·compose·legacy retire·관리자 비밀번호 `.env` 쓰기가 G로(잡혀 있으면 즉시
  409 `MANAGER_MUTATION_ACTIVE`) → **C-3 #410** pinned lease P·env 파생 락·override 삭제.
- n150 설치(`4d324926`) 뒤: 같은 pair 수렴 재구축 중 `lslocks`에 **G 하나만**, G를 쥔 동안 rehearsal 경로 즉시 거절,
  `pin verify` 0. 남은 P 파일은 보유자 없음을 확인하고 지웠다.
- **대가(설계대로):** 재구축·M05·설치 동안 UI 조작과 관리자 비밀번호 변경은 409다. UI가 G를 몇 ms 쥔 순간에
  chain17 launcher가 시작되면 빠르게 실패하므로 다시 돌린다. **G를 손으로 잡을 때는 `flock(1)` 금지**(없는 G를
  0644로 만들어 모든 변경이 멈춘다) — `/opt` venv의 `manager_mutation_lock()`으로만.

## 2026-09-26 (자정 무렵) — Manager B3: v8 journal이 코드에서 사라졌다

**다음 한 작업: Manager ADR-51 C(락 통합)** → D(permit mount 제거, v6 쓰기 중단·M05 driver를
`deploy-status.json`으로). B3의 선택 PR-4(launcher claim 해제 정리·실패 분류 이름)는 C에 합쳐도 된다.

- **B3 PR-1 #405** carry-over·죽은 증거 생산자 삭제(−2.3k줄), **PR-2 #406** v8 journal 모델 삭제·공개 세대
  리더는 v6 manifest만(−4.3k줄, `drift` 없음), **PR-3 #407** journal 시절 관리자 비밀번호 guard·preflight
  상태 퇴역(backend+frontend). 셋 다 적대 리뷰 반영, n150 전체 pytest 초록.
- **n150 설치(`95a82c67`)** 뒤 확인: `pin verify` 0(binding match), 공개 세대 리더 `ok/match/committed`
  (옛 공개 v8 사본은 안 읽음), M05 rotation preflight 통과, 사라진 route 404, 같은 pair `converged` 45초.
- **알려진 후속(B3 밖):** preflight §1이 늘 `EXECUTION_VERIFICATION_REQUIRED`/`LEGACY_SOURCE_TERMINAL`을 더해
  `ok`가 나오지 않는다(잃는 보장 B의 후속). `deployment_readiness`가 더는 주입되지 않는 PinVi
  `PINVI_ROLE_CATALOG_RESET_*`를 요구해 거짓 blocker를 낼 수 있다.

## 2026-09-26 (늦은 밤) — 단순화된 체인으로 첫 새 pair가 D1·D2까지 섰다

**다음 한 작업: Manager B3(v8 journal·phase·evidence 클래스와 journal 전용 코드 삭제, 남은 리더를
`deploy-status.json`으로)** → C(락 통합) → D(permit mount 제거, v6 쓰기 중단). 순서는 Manager ADR-51 §순서.

- **M1 #1270**(storage one-shot 멱등) · **M2 #1272**(C7/D2 attestation 체인 제거 + `scripts/n150/`, `adjudicate.sh`
  포함) 머지. `/root` 호스트 스크립트를 머지 커밋 `031205ff`에서 설치(옛 사본 `/root/host-scripts-pre-m2-*`).
- **t59a(Map `031205ff`, pinset `be344a89`)**: pair 계약 preflight → 회전 → 전진 배포 `deployed`(DB oid 그대로,
  경고 없음) → ADR-069 PASS → repin → ACL 40/40 → **D1 11 passed → D2 passed(v4)**, lane 깨끗.
- **n150 디스크:** 백업·덤프 약 31GB도 정리(소유자 승인) → 여유 111G(76%). geo 백업은 geo janitor로.
- **남은 판단:** 다른 세션 작업 디렉터리 약 18.5GB(지우지 않음).
- **작은 결함 하나 고침(이 PR):** chain16 step E가 공유 체크아웃 `/tmp/ktm-lint`의 fetch 실패를 검사하지 않아
  t59a에서 옛 origin/main 사본의 M01 preflight가 돌았다 → 배포한 SHA에서 꺼내고 실패하면 멈춘다.

## 2026-09-26 (밤) — Manager B2(마이그레이션 전진) 설치, 같은 pair 수렴 확인

**다음 한 작업: Map M1(#1270, storage one-shot 멱등) CI → 머지, M2(C7/D2 attestation 체인 제거 +
`scripts/n150/`) 적대 리뷰 반영 → PR → 머지 → 호스트 스크립트 설치(H1).** 그 뒤 첫 새 pair를 새 체인으로
돌려 D1/D2를 확인한다. 그다음 Manager B3(v8·journal 클래스 삭제) → C → D.

- **Manager B2 #404(`13e744b`)** 머지·n150 설치·`pin rebind-execution` 완료. 적대 리뷰 3회(1차 major 2 +
  2차에서 1차 수정이 만든 major 2 + 3차 minor 2) 반영, 변이 18/18.
- **첫 전진 배포(t58a):** carry-over 대신 기준선 없는 전체 경로(옛 계약 v8 journal 62개가 읽히지 않음) —
  리셋 없음, DB oid 그대로, ADR-069 PASS, D1 11 passed. **t58b: `converged` 45초.**
- **주의:** 새 pair는 아직 chain17로 돌리지 말 것 — B2가 v8 journal을 쓰지 않으므로 chain16의 repin
  (gen_attest)이 실패한다. M2 + H1 뒤다. 같은 pair 재실행은 launcher(`run-pinned-rebuild-once`)로 수렴한다.
- **소유자 판단 대기(유지):** n150 백업·덤프 약 31GB, 다른 세션 작업 디렉터리 약 18.5GB.

## 2026-09-26 (저녁) — ADR-069 배포 완료(t57d): D1·D2 GREEN

**다음 한 작업: ADR-102/Manager ADR-51 단계 PR을 이어 간다** — Manager B2(마이그레이션 전진 본체,
브랜치 `feat/migrate-forward-b2`) 적대 리뷰 → PR·CI·머지·설치 → 같은 pair 수렴 1회 → Map M1(storage
one-shot 멱등) → M2 + 호스트 스크립트(H1) → B3 …. 순서 근거는 아래 2026-09-26(오후) 항목과 ADR-102.

- **배포:** pair Map `6511441f` / PinVi `b227e77b`(pinset `e4909e26`), Manager `e891ec7`(#401).
  chain17 t57d: rebuild success → repin verifier PASS → M01 ACL 40/40 → D1 11 passed → D2 passed.
- **ADR-069 확인:** Map·PinVi code-server/webserver/daemon healthy, companion = owner 이미지, code location
  LOADED(Map 48 jobs / PinVi 9 jobs), gRPC 12703/12803 loopback 전용(`[::ffff:127.0.0.1]`, 비-loopback 29개 거부).
- **t57b·t57c:** 호스트 포화(BuildKit session healthcheck 실패 / 내가 journal 전 중단). 데이터 변경 없음.
- **n150 디스크:** 캐시·재생성 가능 항목만 정리해 42G → 84G(82%), IO `full` 50~60% → 약 3%.
  **소유자 판단 대기:** 백업·덤프 약 31GB, 다른 세션 작업 디렉터리 약 18.5GB.
- **열린 것:** geo code-server `-h 0.0.0.0`(아래 2026-09-26 항목) 그대로.

## 2026-09-26 — ADR-069 재구축이 code-server를 한 번도 띄운 적이 없었다 → Manager 수정 후 재시도

**다음 한 작업: Manager #399 설치 → 이 커밋(새 pinset)으로
chain17 → Map Dagster GraphQL로 code location 로드 확인 → D1/D2.** 그다음 봉인·신뢰 릴리스
단순화(설계 완료, 잃는 보장 목록은 소유자 승인 대기).

### 원인 (자세히는 journal.md 2026-09-26)

- **t56g·t56h:** 비상 복구 때 `/opt` compose에 손으로 넣은 패치(webserver/daemon `-m`)를
  되돌리지 않은 채 돌렸다. 새 이미지의 봉인 entrypoint가 `-m`을 거부해 compose up에서 죽었다.
  신뢰 릴리스 사본으로 원복·diff 확인 완료. pinset `a7cc0414`는 journal이 패치본 compose sha를
  동결해 재개 불가 — 버린다(이 커밋이 새 pinset이다).
- **더 근본:** pinned rebuild가 `up --no-deps`에 고정 서비스 목록을 줬고, compose는 호출에 이름이
  없는 서비스로의 `depends_on` 간선을 지운다. 그래서 Map code-server는 **어느 재구축에서도 기동된
  적이 없고**, webserver healthcheck는 빈 `RepositoryConnection`도 통과시켜 `--wait`가 초록이었다.
  D1도 code location을 보지 않는다 — 그대로 두면 저장소 0개인 Dagster가 GREEN으로 커밋될 뻔했다.
  PinVi code-server·daemon도 관리 밖이라 DB 리셋을 건너 옛 이미지로 떠 있었다.
- **PinVi:** SQLAlchemy 2.1.0이 bare `postgresql://`의 기본 driver를 psycopg(v3)로 바꿔
  pinvi-dagster가 `ModuleNotFoundError: psycopg`로 죽었다 → pinvi#565(`<2.1`).

### 끝난 것

- Manager #399(generation companion: resolved compose에서 slot 이미지를 공유하는 비-slot 서비스를
  파생해 stop/up/readiness/image 대조에 태움, 영속 포맷 변경 없음) + 실패 원문을 `.env` 비밀을
  가려 stderr로(봉인 단순화 1단계) + PinVi code-server `-h 127.0.0.1`(인증 없는 gRPC LAN 노출 제거).
  적대 리뷰가 "companion 호출처 10곳 중 8곳은 지워도 테스트가 안 깨진다"를 검증해, commit·committed
  재개까지 도는 테스트를 더했다 — 변이 검사로 10곳 + one-shot 제외 + 프로세스 환경 리댁션 12/12가
  각각 빨개지는 것을 확인했다.

### 열린 것

- **geo code-server가 host network에서 `-h 0.0.0.0`**(인증 없는 gRPC가 LAN에 열림). geo 이미지의
  workspace.yaml이 어느 host로 붙는지 확인한 뒤 닫는다. Manager 테스트에 알려진 예외로 등록해
  두었고, 해소되면 그 예외부터 지우라고 빨개진다.

## 2026-09-25 — ADR-069 code-server: PinVi 활성화 완료, Map은 merge+재설치 끝·재구축 진행 중

**다음 한 작업: 이 커밋(새 pinset)으로 n150 chain17.sh 재시도, D1(live e2e UI)까지 확인.**
자세한 경위는 `journal.md` 2026-09-25. 요약: Map #1264 + Manager #397/#398(등록
누락 두 건) 전부 머지·배포 끝, 재구축이 (pinset, Manager revision) 단위 v6
execution terminal에 두 번 막혀 새 커밋으로 pinset을 갈아야만 재시도 가능했다.

### 끝난 것

- PinVi dagster-code-server + webserver(`-w`) + daemon 첫 기동, schedule/sensor
  0개 자동 기동 확인.
- Map도 같은 code-server 분리(Map #1264, Manager #397) — mypy 깨던 SQLAlchemy
  2.1.0 무상한 고정(#1265), C7 attestation 카운트 6→7, Manager
  `compose_service.py`의 별도 protected-scalar 레지스트리 등록 누락(#398).
- n150 Manager `6452a4c…`로 재설치 + 프론트엔드 재빌드 완료.

### 아직

- 이 커밋의 새 pinset으로 chain17.sh(rotate→rebuild→executor image→repin→
  ACL preflight→D1 live e2e→lane 정리→D2) 재시도.
- D1(live Playwright, admin UI)로 code-server 토폴로지가 실제로 code
  location을 서빙하는지, 기존 schedule/sensor/job이 그대로 보이는지 시각
  확인.

## 2026-09-24 — prod 전 사이클 GREEN. ADR-100/101 + PinVi 단일 role, 실사용으로 처음 섰다

**다음 한 작업: 소유자 판단 — D1/D2 spec 재검증을 지금 돌릴지, 아니면 여기서 접을지.**
prod 자체는 안정 상태이므로 급하지 않다(아래 "끝난 상태" 참고). 돌린다면
`docs/integration-map.md`의 D1(live Playwright)·D2(admin acceptance) 절차를
그대로 따른다 — 지금 pinset(`fa6f624e5b06…`)이 첫 실사용 기준선이라 두 레인
모두 **이 번호로는 한 번도 실행된 적이 없다.**

### 끝난 것 — Manager+PinVi 연쇄 네 자리 (자세한 근거는 journal.md 2026-09-24)

어제 남겼던 "빌드 영수증 축 빠짐"은 Manager PR #391/#392/#393으로 닫혔다. 그
뒤 재구축이 Map을 다 통과하고 PinVi 쪽에서 네 번 더 막혔다 — pinvi DB owner
drift(직접 SQL로 수정) · Map `ktm_*` role 19개 정본 이탈(직접 SQL로 수정) ·
PinVi 0101이 요구하는 catalog-lock fence 함수 부재(Manager #394) · PinVi
0101 자신이 자기 migrator 권한을 트랜잭션 안에서 거둬감(pinvi #564). 넷 다
**ADR-46(PinVi M05 다중 role 폐기)이 인프라는 고쳤는데 그 인프라가 떠받치던
자리 일부를 안 고친 것**이 근본이었다.

### 끝난 상태 (2026-09-24 실측)

| | |
|---|---|
| pinset | `fa6f624e5b068713546517d19660e60701913e483565ea21ee11ef73d19a00cc` |
| map revision | `f5703bc676b175fb1b0f9ccbcdd202df02ad71d6` (schema head `400`) |
| pinvi revision | `b60cc8cd601d6236655902337e150bfbd0829719` (schema head `20260917_0102`) |
| Manager | `7fc1a8c94bea5eb5155246a71ddaa731d840a841`(#394), trusted install + execution rebind 완료 |
| 런타임 | 7개 서비스(map-api/ui/dagster/dagster-daemon, pinvi-api/web/dagster) 전부 healthy |
| `.env` | `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=400`(재구축 후 변경, 순서 지킴) |

## 2026-09-23 — ADR-100/101 머지됨, prod는 Manager의 **남은 ADR-101 구간**에 막혀 있다

**다음 한 작업: Manager에서 paired candidate build receipt 장치를 걷어낸다.**
그것 없이는 prod 재구축이 끝나지 않는다.

### 무엇이 막혔나

ADR-101은 Map에서 `scripts/build-application-300-{candidate,paired-candidate}.sh`와
`build-baseline.sh`를 지웠다(ADR 문서 17행이 그 셋을 명시한다). 그런데 Manager의
소비자는 그대로 남아 있다 — 앞선 ADR-101 Manager 작업(#389)이 영수증·fence·phase
기계를 접었지만 **빌드 영수증 축은 범위 밖이었다.**

같은 뿌리에서 두 자리가 어긋나 있다:

1. `compose_service.py:2830` `_run_map_application_300_paired_builder`가 지워진
   `scripts/build-application-300-paired-candidate.sh`를 요구한다.
   → 재구축이 `prejournal_failure` / stage `application_builder`로 죽는다 (실측).
2. `compose_service.py:6098` `DagsterStorageCandidate`가 아직
   `paired_candidate_build_receipt_sha256`을 싣는다. Map의
   `docker/dagster-storage-migrate.py`는 이제 `_CANDIDATE_FIELDS =
   {dagster_image_id, dagster_config_sha256}` **exact** 검사다.
   → 1번을 고쳐도 Dagster storage 단계에서 `dagster_storage_permit_candidate_invalid`
   로 막힌다(코드 대조로 확인, 아직 실측 전).

면적: `map_application_300_candidate.py` 773줄 + 호출부 + `Application300Contract` +
테스트 참조 약 75건.

### prod 현재 상태 (2026-09-23 09:5x 실측)

**더 나빠지지 않았다.** 두 실패 모두 저널 **전**이라 후보가 해제됐고, 새 pinset에는
journal이 없다 — 고착이 아니라 재시도 가능 상태다.

| | |
|---|---|
| pinset | `e8441d96983d…` → map `f5703bc6…`, pinvi `351b4ace…` |
| journal | 없음 (재시도 안전) |
| 컨테이너 | `kor-travel-map-postgres`, `pinvi-postgres`만 Up. 나머지는 여전히 down |
| rebuild t53a | `prejournal_failure` / `prebuild_snapshot` — `.env` 자격증명 부재 (**해결됨**) |
| rebuild t53b | `prejournal_failure` / `application_builder` — 위 1번 (**미해결**) |

### 이번 사이클에서 끝낸 것

- **Manager 설치본을 `e4d4fa55`로 갱신했다** (사용자 1회 허가로 trusted installer 실행).
  이전 설치본은 `2dc633dd`로 머지 여섯 개 뒤처져 있었다.
- **`.env`에 ADR-100 단일 LOGIN 자격증명 쌍을 넣었다** —
  `KOR_TRAVEL_MAP_SERVICE_PASSWORD`, `KOR_TRAVEL_MAP_PG_DSN`. Manager는 M05 폐기와
  함께 이 값을 더는 쓰지 않으므로 운영자 책임이다. 선행 조건을 Manager
  `docs/prod-deployment.md`에 적었다(kor-travel-docker-manager #390).
  백업: `.env.bak-pre-adr100-service-credential-20260923T095230Z`.
- **핀을 회전했다** — 직전 pinset의 journal 영구 고착 탈출구가 새 커밋이었고, 두
  머지가 그것을 만들었다. 회전은 **다시 하면 안 된다**(`rotate-pinned-pair`가 같은
  쌍에 대해 no-op을 거부한다). 재시도는 rebuild 단계부터다.

### 재시도 방법 (Manager 고친 뒤)

```bash
# 회전은 이미 끝났다 — chain17을 통째로 다시 돌리면 B단계에서 죽는다.
sudo systemd-run --no-block --unit=ktdm-rebuild-<새태그> --collect \
  --property=Type=oneshot --property=TimeoutStartSec=7200 \
  /opt/kor-travel-docker-manager/scripts/run-pinned-rebuild-once \
  <설치된 Manager 40-hex> /root/rebuild-ktdm-rebuild-<새태그>
# 성공하면 후반부
sudo /root/chain16.sh <MAP 40-hex> <PINVI 40-hex> <execbuild unit> <d2 unit> <태그>
```

그다음에 `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를 `400`으로 바꾼다
(지금 `312_route_geometry_sidecar`). **재구축 뒤에** 바꾼다 — 먼저 바꾸면 API가
기동을 거부한다.

## 2026-09-20 (2) — PR #1257 머지 완료, prod 배포가 pinned-rebuild journal에 고착 (outage 진행 중)

**다음 한 작업: PinVi에 실제 커밋 하나를 올려 새 pinset을 만들고 `chain17`을 다시
돌린다.** PR #1257(ADR-099 2단계)은 머지됐고(`b3c217f0`), 회전 → rebuild까지는
진행했으나 **prod의 Map/PinVi 앱 컨테이너가 전부 내려간 채로 멈춰 있다**
(postgres 둘은 healthy, Map DB는 이미 `312_route_geometry_sidecar`로 정확히 재생성됨
— 데이터 손실 없음, 순수 가용성 중단).

**막힌 지점 (n150, Manager `d6c503a0` 기준 실측):**

1. pinset `3705983b`(map `b3c217f0` + pinvi `ed5eb020`)의 rebuild가 compose-up
   단계에서 반복 실패. 원인: **다른 세션이 geo 공용-postgres 온보딩 작업으로
   `.env`에 `KOR_TRAVEL_GEO_SHARED_APP_PASSWORD`를 추가**해 파일 전체 해시가 바뀜
   (`.env.bak-t308-20260920042101`로 확인, 완전히 무해한 동시 작업).
2. 그런데 `_assert_pinvi_role_credential_rebind_admission`(Manager
   `compose_service.py`)이 `journal.phase == "map_runtime_ready"`일 때만 재결박을
   허용한다 — 이 journal은 이미 그보다 진행된 `cancel_probe_finalized`라 **원인이
   무해해도 이 pinset은 설계상 영구 재개 불가**다(`rotate-pinned-pair`도 같은
   map+pinvi 쌍이면 no-op을 거부해 새 pinset을 못 만든다).
3. 알려진 v6 candidate 이미지로 직접 서비스만 복구를 시도했으나 두 관문에 추가로
   걸렸다 — `.env`의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=300`(수 주 전 값,
   **고쳤다** → `312_route_geometry_sidecar`, `.env.bak-pre-migration-head-fix-*`)와
   `application final permit`(`/run/kor-travel-map-application-final-permit/`,
   호스트 마운트가 8월 25일자 무관한 rehearsal 트리를 가리키며 비어 있음 — 이건
   **파이프라인이 끝까지 성공해야만 발급**되는 증빙이라 손으로 만들 수 없다).

**해제 조건:** PinVi에 사소한 실제 커밋(예: 문서 동기화) → `rotate-pinned-pair`로
진짜 새 pinset 생성(고착된 journal 우회) → `chain17.sh` 재실행 → compose up이
끝까지 성공 → final permit 발급 → 서비스 기동 확인.

소유자 결정(2026-09-20): 지금은 보류하고 weather → concierge → geo → pinvi → map
순서의 Dagster 실행구조 개선·DB 인스턴스 통합을 먼저 진행한다. 이 outage 정리는
그 작업과 별도로 재개한다.

## 2026-09-20 — ADR-099 2단계: route geometry가 전용 PostGIS relation으로 갔다

**다음 한 작업(완료, 위 항목 참조):** ~~네 세션 게이트를 초록으로 만들고 머지 →
핀 회전 · DB 재구축 · 전 provider 재적재.~~ 소유자 지시: *"마이그레이션 하지말고
db재설계후 다시데이터 로드해. 지금데이터는 무의미함."*

`312_route_geometry_sidecar`가 `feature.feature_routes.geom`을
`feature.feature_route_geometries`로 옮긴다. **데이터를 이어 나르지 않는다** —
`feature_routes`가 비어 있기를 요구하고, 행이 남아 있으면 마이그레이션이 멎는다.
설계 근거는 ADR-099 §4·§5.

### 이 단계에서 반복해서 터진 결함은 하나의 모양이었다

**"선언을 바꿨는데 그 선언을 얼려 둔 자리를 같이 못 봤다."** geometry 컬럼 하나가
이사했을 뿐인데 그것을 가리키던 자리가 **열여섯 곳**에서 옛 자리에 남아 있었다:
뷰 의존(DROP 실패), plpgsql 프로시저 셋(첫 적재에서 42703), `public_ready` 트리거
누락(route가 오류 없이 공개 bbox에서 0건), NOINHERIT 소유자 검사, 권한 조정기의
fail-close fence, ORM 메타데이터, GiST 인덱스 이름에 결박된 검사 여덟,
`ktm_feature_state_procedure_owner`의 geometry 권한, `ktm_curation_command_owner`의
SELECT, `current_theme_candidate_snapshot`의 `to_jsonb(route)`, override field-path
레지스트리, 무결성 관측 두 축, 역할 창 lint의 309 결박, 롤 유지 lint의 AST 한계,
그리고 head 오라클 자체.

그래서 이 브랜치는 **이름을 옮기는 대신 모델에서 유도하게** 바꿨다 —
`GEOMETRY_RELATIONS`/`EXTERNAL_GEOMETRY_KINDS`가 단일 정본이고, 검사·관측·권한이
거기서 나온다. 다음 이사(area)는 dict 값 하나를 바꾸는 일이어야 한다.

### 적대 리뷰 (opus5 · xhigh 2인 + 반증 패널)

10건 중 8건 생존, 1건 반증, 1건은 API 오류로 미완. 생존분은 전부 닫았다.
반증된 것은 "312가 봉인 member 정의를 바꾸는데 `input_set_formula` 세대를 안
올렸다" — 312가 비어 있기를 **요구**하므로 세대 2로 발급된 구 route arm receipt가
312 DB에 남을 수 없다. 판단 근거는 ADR-099 결과 절에 적었다.

내 자신의 돌연변이 실험도 검사 결함 하나를 더 찾았다 — 롤 유지 lint가 **주석 붙은
`SET ROLE`을 못 봤다**. 사이드카의 여는 창은 거의 언제나 설명 블록 뒤에 오므로,
검사는 닫는 쪽만 보고 있었다.

---

## 2026-09-19 (4) — 등산로가 한 번도 성공한 적 없는 이유를 찾았다. 봉인에 크기 천장이 있다

**다음 한 작업: ADR-099 2단계 — route geometry를 PostGIS 보조 relation으로 분리.**
1단계(`311_seal_member_digest`, fold를 행별 digest로)는 이 PR에서 닫았다.

`feature_route_krforest_mountain_trails_job`이 **4시간18분** 지오코딩을 마치고
적재/봉인에서 죽었다.

```
asyncpg.ProgramLimitExceededError:
  total size of jsonb array elements exceeds the maximum of 268435455 bytes
```

`feature.current_provider_curation_input_set`이 causal seal을 만들 때 **데이터셋
전 행의 feature detail을 하나의 `jsonb_agg` 배열로 모아** 그 text를 sha256한다.
route는 `to_jsonb(route)`라서 geometry가 통째로 들어간다.

**적재는 같은 트랜잭션 안에서 봉인보다 먼저** 일어난다. 그래서 57,060행을 넣고 →
봉인에서 죽고 → **통째로 롤백**한다. `provider_sync.source_entities`의
`mountain_trail_segment`가 0행인 이유가 이것이다 — 이 job은 **한 번도 성공한 적이
없다.** 재시도는 같은 자리에서 죽으며 매번 4시간을 다시 쓴다. 2차 시도는 종료시켰다.

**실측 — geometry가 payload의 98.5%다** (기존 둘레길 26행 기준).

| | route당 | 57,060건 환산 |
|---|---:|---:|
| 현재(geom 포함) | 43 kB | **2.45 GB** ❌ |
| geom 제외 | 633 B | 36 MB ✅ |

현재 천장은 대략 **43 kB 기준 6,200 route**다. 둘레길 26건은 안전하다.

**그런데 geometry만의 문제가 아니다.** `feature.feature_places`는 평균 **323 B**인데
(prod 34,422행 실측) MOIS 980,970행이면 **302 MB**로 geometry 없이도 한계를 넘는다.
즉 geometry를 어디로 옮기든 **fold 자체가 O(행수 × 행당 payload)인 것**이 근본이다.

**소유자 지시**: *"등산로는 postgis 형태로 별도의 보조테이블에 저장"*,
*"등산로와 같은 건 route 에 저장"*. 즉 route 정체성은 유지하고 geometry 저장소만
분리한다. 설계는 ADR-099로 진행 중이다(다음 ADR 후보 번호 확인함).

**설계에 확정된 제약(실측).**

- 보조 테이블 PK는 `feature_id` **1:1**이다 — `forest_trails_to_bundles`가 item
  하나당 bundle 하나를 만들어 57,060 세그먼트 = 57,060 route feature다. 1:N은
  `ktm_feature_runtime`에 **의도적으로 없는** subtype DELETE 권한을 새로 요구한다.
- **area도 같은 구조**다(`MULTIPOLYGON NOT NULL` + 동일한 부분 GiST). 지금 0행이고
  생산자(KNPS 국립공원 경계)는 비활성 목록에도 없이 그냥 실행된 적이 없다 —
  적재되는 순간 같은 사고가 난다.
- 봉인은 기록이 아니라 **게이트**다. 불일치 시 child는 23514, root는 `stale_input`.
  그리고 한 사이클에 **최소 세 번** 호출되며 그중 `finalize_provider_curation_root`는
  **적재와 다른 트랜잭션**이다 — 적재 쪽만 고치면 finalize에서 같은 자리에서 죽는다.
- ADR-086/`0087_route_area_subtypes`가 geometry를 subtype에 넣은 이유는 성능이 아니라
  **불변식**이다: "geometry가 필수인 kind와 없어야 하는 kind가 술어가 아니라 테이블
  구조로 갈린다". 보조 테이블은 그 불변식을 다시 연다 — 대체 fence가 설계의 중심이다.
  (admin 주석의 "0086"은 ADR 번호이고 revision은 `0087`이다.)
- 보조 테이블은 `feature_routes`가 아니라 **`feature.features`에 직접 FK**를 걸어야
  한다. purge 증거 포획이 `confrelid='feature.features'` 한 단계만 훑으므로, 2단
  CASCADE로 지워지면 복구점에 안 남는다.
- provider 경로의 geometry 변경은 geometry를 빼도 계속 감지된다 —
  `krforest.py`가 `geometry_wkt`를 `raw_payload_hash`에 넣고 그 해시가 봉인 배열에
  이미 있다. 다만 **직접 `SET geom` 경로가 셋 실재**한다
  (`_309_{apply_provider_feature_field_patch,author_feature_field_overrides,revoke_feature_field_overrides}.sql`).
- API/OpenAPI는 걸리지 않는다 — route geometry는 GeoJSON(`include_geometry`)으로만
  나가고 저장 표현은 노출되지 않는다.
- **배포 창이 지금 깨끗하다**: snapshot receipt 5건, 진행 중 curation root **0건**.
  봉인 해시 정의를 바꿔도 `stale_input`으로 빠질 in-flight root가 없다.

## 2026-09-19 (2) — 재배포·재실행 완료. 그리고 상한 수정이 가린 것을 드러냈다

**다음 한 작업: 산사태 notice의 위치 해석.** prod에 `feature.feature_notices`가
**0행**이다 — 이 dataset은 한 번도 적재된 적이 없다.

**왜 이제 보이는가.** 종전에는 `ProviderPaginationOverrun`으로 job이 수집 단계에서
죽어 검증까지 가지 못했다. 상한을 40장으로 올리자 처음으로 전량이 도착했고, 그
다음 단계가 **전량을 떨궜다.** 2026-09-19 04:09 실측 materialization:

```
upstream_requests_min              11      ← 상한 수정은 동작했다
address_validation_total        10467
address_validation_error_count  10467
address_validation_dropped_count 10467     ← 받은 것 전부 탈락
```

**원인 가설(미확정).** 이 feed에는 좌표도 도로명주소도 없고 위치 단서가
`ocrnFrcstIssuInsttNm`(예: `충청남도 당진시`) 하나다 — **주소가 아니라 기관명**이다.
주소 파서는 그것을 주소로 읽지 못한다. 고치려면 기관명 → 시군구 코드 경로를
따로 두어야 한다. **먼저 `address_validation_issues`의 실제 사유를 읽어 가설을
확인할 것** — 위 숫자는 "전량 탈락"을 말할 뿐 이유를 말하지 않는다.

**이것은 회귀가 아니다.** 상한 수정이 만든 것이 아니라, 상한 수정이 **처음으로
그 지점까지 도달시켜서** 보이게 된 것이다.

**재배포·재실행으로 확인된 것.** prod `697a1d87a`, migration head `310_seoul_source_move`.

| dataset | 이전 | 지금 |
|---|---:|---:|
| `datagokr_seoul_bookstores` | 0 (odcloud 404) | **606** |
| `krforest_arboretums` | 0 | **212** |
| `krforest_recreation_forests` | 0 | **182** |
| `krforest_dulle_trails` | — | **26** |
| `krforest_landslide_forecast_issues` | job 실패 | 10,467 수신 / 0 적재 |

**아직 열린 것.** MCST 문화·krforest 산악등산로 재실행 결과, OpiNet place/price
재실행(하루 예산 280/300), 그리고 D2 lane BLOCKED
(`admin feature live acceptance: direct fixture seed failed`) — prod 서비스가 아니라
acceptance 하네스 쪽이고 별건이다.

## 2026-09-19 — 원천을 고쳤다. 다음은 재배포와 재실행이다

**다음 한 작업: prod 재배포 후 실패했던 job 재실행.** prod 이미지는 아직 `e9b877b3`라
이번 묶음(provider 핀 · OpiNet 기본 모드 · 서울 책방 원천)이 하나도 실려 있지 않다.
**핀을 올리지 않으면 머지한 provider 수정이 적용되지 않는다** — 재배포 전까지 산림
표준데이터 3종과 MCST 아동서점은 여전히 0건이다.

**닫은 것.**
- provider 핀 상향 — `python-krforest-api@70814c9`(표준데이터 gateway가 response
  래퍼를 벗은 것), `python-mcst-api@0f5a8fe`(아동서점 fileDataNo 282→484).
- OpiNet 기본 모드 `low_top_area`(운영 결정). compose가 안 넘기던 호출량 노브 둘도
  배선. `.env.example`에 남아 있던 180/600(한도를 1,500으로 잘못 알던 시절 값)도
  90/140으로 정정 — 그 파일이 compose 기본값을 덮는다.
- 서울 책방 원천 → 서울 열린데이터광장 OA-21062(`TbSlibBookstoreInfo`), 라이브 606건.
  schedule을 `DISABLED_FEATURE_LOAD_SCHEDULES`에서 뺐다.
- MCST asset이 **시도하지 않은 dataset까지** 적재하던 것(worker 경로에서 12종이 빈
  authoritative 적재 + sync-success를 받았다).
- 페이지 상한 사전 경고 — 여유가 절반 아래로 내려오면 prod가 먼저 말한다.

**오너 작업으로 남은 것(코드로 못 닫는다).** data.go.kr 활용신청 4건 — 안산
세계맛집 · 경기 무슬림 친화 음식점 · 제주 향토음식점 · 지역특화거리 표준데이터.
활용신청은 키가 아니라 **데이터셋 단위**다. 신청이 끝나면
`DISABLED_FEATURE_LOAD_SCHEDULES`에서 그 이름을 빼는 것으로 되살아난다.

**별건으로 남긴 것 (1).** MCST 부분 실패 run에서 **적재에 성공한 dataset의
membership이 완료 처리되지 않는다.** `raise Failure`가 완료 콜백보다 앞에 있고,
콜백 계약(`received_memberships != memberships` → RuntimeError)과 wrapper의
`len(result.results) != len(completed_memberships)` 단언이 부분 완료를 거부한다.
증거 원장과 DB 상태가 어긋나지만 (a) 큐 경로에는 도달하지 않고(scope당 slug 1개
— multi-member run은 수동 launch나 schedule일 때만 생긴다), (b) 이번 변경의
회귀가 아니다(종전에는 실패 하나가 13개를 전멸시켰다). 고치려면 두 결박을 함께
풀어야 한다 — 2026-09-19 적대 리뷰가 확정했다.

**별건으로 남긴 것 (2).** 산사태 예보발령 증분 수집. 이 asset은
`load_authoritative_notice_snapshot`으로 `active_lineage_keys` 전체를 대조하므로,
부분 수집으로 바꾸면 화해 계약부터 다시 설계해야 한다. 지금은 상한 40장(실측 10,562행
대비 약 4배)과 사전 경고로 버틴다.

[현행 기록으로](../resume.md)
