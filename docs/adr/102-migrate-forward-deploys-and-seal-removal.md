# ADR-102 — 배포는 마이그레이션 전진이다: DB를 보존하고, 배포 봉인과 attestation 체인을 걷어낸다

- 상태: Accepted (2026-09-26)
- 결정자: human(소유자), AI agent
- 관계: [ADR-094](094-c7-pinned-runtime-generation-attestation.md)를 대체한다.
  [ADR-101](101-single-baseline-revision-400.md)의 전제("운영 중 아님·데이터 보존 없음")와
  "다시 접을 때" 절차를 대체한다 — baseline `400` 자체는 유지한다.
  건너편은 kor-travel-docker-manager ADR-51이다.

## 결정

1. **운영 DB는 배포를 넘어 보존된다.** 배포는 Map 애플리케이션 DB에
   `alembic upgrade head` + `kortravelmap.infra.runtime_privileges` 재조정(schema one-shot)을,
   Dagster metadata DB에 storage one-shot을 **매번** 실행한다. 둘 다 이미 head면 무연산이다.
   DB를 지우는 길은 Manager의 명시적 `rebuild-pinned --restart --reason`뿐이다.
2. **migration은 forward-only다.** `alembic/env.py`는 이미 downgrade를 거부한다. `400` 위에
   `401`부터 쌓고, 실데이터 위에서 도는 것을 전제로 쓴다(잠금 시간, backfill).
   **재스쿼시는 stamp bridge 없이 금지다** — 이미 head `H`에 있는 운영 DB가 새 root로
   stamp될 수 있어야만 접는다. ADR-101 "다시 접을 때"의 "빈 DB를 올려 덤프하고 `500`으로
   접는다"는 그 조건을 더해서만 유효하다.
3. **Dagster storage one-shot(`docker/dagster-storage-migrate.py`)은 멱등 관측만 남긴다.**
   - 남김: 설치된 Dagster head, 없으면 `create_all` + stamp, `instance migrate` + `reindex`,
     session advisory lock, 관측 기반 "애플리케이션 DB가 아님" 가드, env에 app DSN이 있으면 거부.
   - 삭제: permit 읽기, intent/receipt outbox(`ktm_dagster_storage_operation_{intents,receipts}`와
     불변 trigger는 `DROP ... IF EXISTS`로 치운다), "final head인데 이번 operation intent 없음"
     거부, 정확 catalog 대조(부분집합 검사로 바꾼다).
4. **런타임은 자기 신원을 증명하지 않는다.** Dagster 런타임 기동 시 `verify-identity`를 없앤다.
   entrypoint의 argv·PATH·env 봉인도 걷어내고 **한 줄만** 남긴다 — `dagster api grpc`의 `-h`는
   `127.0.0.1`이어야 한다(인증 없는 gRPC + host network = LAN 코드 실행).
5. **런타임 head 확인(ADR-090)을 Dagster code-server·daemon에도 기본으로 켠다.** 지금 production은
   API에만 `KOR_TRAVEL_MAP_RUNTIME_DB_PREFLIGHT_REQUIRED`를 켜서 Dagster 런타임은 애플리케이션
   head를 보지 않는다.
6. **C7 attestation 체인을 걷어낸다(ADR-094 대체).** orchestrator 스냅샷, `/etc/kor-travel-map/*attestation*`,
   `gen_attest.py`, Manager의 manifest/journal 재파싱(`E2E_C7_PINNED_RUNTIME_MANIFEST`,
   `E2E_C7_REBUILD_JOURNAL`, `rebuild_journal_sha256`)을 없앤다. D1/D2는 **핀된 SHA의 평범한
   체크아웃**에서 돌고, 그 기능 단언이 게이트다. n150 러너 스크립트는 저장소(`scripts/n150/`)로
   옮겨 버전 관리한다.

## 왜

### 배포가 데이터를 지울 이유가 없다

ADR-101은 "운영 중이 아니고 데이터 보존도 요구하지 않는다"에서 출발했다. 그 전제 아래서
배포마다 DB를 지우고 다시 만드는 것은 비용이 없어 보였다. 실제로는 비용이 있다 — 리셋 뒤
적재는 전부 다시 받아야 하고 data.go.kr의 일일 한도는 오퍼레이션마다 걸린다. 큐레이션·수동
Feature처럼 provider에서 다시 받을 수 없는 행은 리셋이 그대로 없앤다. 소유자는 리셋을
기본값이 아니라 명시적 선택으로 두기로 했다.

### 리셋이 상태기계의 근원이었다

Manager의 재구축 journal은 phase 스물, receipt·intent 여럿, 재개 규칙 위에 서 있다. 그 대부분은
"DB를 지우는 도중에 죽으면 어디서 재개하는가"와 "이 DB가 이번 회차에 만든 그 DB인가"에
답하려고 존재한다. storage permit(DB oid·system identifier·후보 이미지·dagster.yaml sha 결박)과
outbox도 같은 질문의 Map 쪽 답이다. DB를 지우지 않으면 질문이 사라진다 — 남는 것은
"head까지 올렸는가"뿐이고, 그것은 one-shot이 끝난 뒤 Manager가 DB를 직접 읽어 잰다
(ADR-101이 영수증 대신 관측을 택한 것과 같은 이유다).

### attestation은 두 번째 증명이었다

Manager가 이미 모든 컨테이너의 이미지를 핀된 세대와 대조하고 이미지 라벨로 소스 리비전을
확인한다. Map 러너가 같은 사실을 root 소유 스냅샷과 서명 파일로 다시 증명한 것은 root가 root를
속이는 경우를 막는 장치였고, 이 호스트의 위협 모델(단일 소유자, root는 신뢰 경계 밖) 밖이다.
대가는 컸다 — Manager의 내부 파일 모양이 바뀔 때마다 Map 러너와 호스트 스크립트가 함께 깨졌다.

## 무엇을 잃는가

소유자가 2026-09-26 목록 전체를 보고 승인했다.

- **배포가 "빈 DB에서 전체 파이프라인이 동작한다"를 더는 증명하지 않는다.** role bootstrap,
  `400` baseline, Dagster `create_all` + stamp 경로는 `--restart`, M05 격리 하네스, CI에서만 돈다.
- **out-of-band drift가 배포를 넘어 살아남는다.** 손으로 고친 SQL·여분 객체를 리셋이 지워 주지
  않는다. 남는 탐지는 런타임 head 확인과 one-shot의 부분집합 검사뿐이다.
- **더 낮은 head로 되돌릴 수 없다.** forward-only이므로 탈출구는 roll-forward 또는 `--restart`다.
  같은 head로 돌아가도 새 코드가 쓴 데이터 모양을 옛 코드가 만날 수 있고, 이는 탐지되지 않는다.
- **Map 서비스 login의 `.env` 비밀번호 회전과 role graph 변경이 배포로 반영되지 않는다.**
  role bootstrap이 빈 DB 전용이기 때문이다. 멱등 reconcile 단계를 후속으로 더한다.
- **실패한 배포가 실데이터를 새 head로 올린 채 멈출 수 있다.** 옛 이미지는 head 확인으로 기동을
  거부하므로 복구는 fix-forward다.
- **Dagster storage를 이번 회차 DB·이미지에 결박하던 증명과 DB 안 append-only 기록이 사라진다.**
  "애플리케이션 DB가 아님"은 이름 상이 검사, app DSN 거부, 관측 가드, 최소권한 login으로 지킨다.
- **이미지가 임의 argv·PATH·자격 env를 거부하지 않는다.** compose와 `.env`를 고칠 수 있는 것은
  소유자뿐이다(Manager UI 사용자의 compose 편집은 Manager의 파생 규칙이 막는다 — ADR-51).
- **러너 파일이 root 스냅샷과 같다는 증명이 사라진다.** root 대 root이고 위협 모델 밖이다.
- **cancel-probe fixture가 영속 DB에 쌓인다.** kind 필터로 목록·가드에서 빠지므로 동작에는
  영향이 없는 잔재다.

## 건너편 — Manager(ADR-51)

리셋 경로는 명시적 `--restart` 하나로 줄고, pinset별 journal·phase·receipt·permit은 전역
`deploy-status.json`(absent / in_progress / committed) 하나로 바뀐다. 재개는 없고 처음부터 다시
돈다 — 모든 단계가 멱등이라 가능하다. 지금 운영 중인 세대는 추가 리셋 없이 새 코드가 채택한다.

## 순서

Manager가 먼저 storage 영수증 없이도 통과하도록 관대해진 뒤(PR-A), Map의 storage one-shot
멱등화(M1)와 attestation 체인 제거(M2, 호스트 스크립트 동시 변경)가 들어간다. 첫 마이그레이션
전진 배포는 M1이 들어간 Map 리비전이어야 한다 — 그 이전 이미지는 permit이 없으면 metadata DB를
건드리기 전에 실패한다(데이터 손실은 없다).
