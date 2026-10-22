# journal 아카이브 — 2026-09-26 ~ 2026-09-27

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-09-27 — Dagster healthcheck 폭주: 셸 래퍼가 남긴 고아들

M05가 n150 과부하로 연달아 멈춘 원인을 좁혀 보니, 운영 Dagster 스택 넷(Map·PinVi·geo·weather)의 healthcheck였다.
- 적대 리뷰가 메커니즘을 바로잡았다. docker는 컨테이너마다 probe를 하나씩만 돌린다. 문제는 `CMD-SHELL`이다.
  timeout 때 `sh`만 죽고, 그 아래 dagster-import Python은 고아로 계속 돈다. PID 1인 dagster는 고아를 거두지 않는다.
  exec 형식 probe 컨테이너는 좀비가 0이었다.
- CLI `dagster api grpc-health-check`는 deadline이 없다. weather code-server가 멈추자 probe가 끝없이 쌓였다.
  weather 수집이 하루 반 동안 사실상 멈춰 있었다.

Manager #426(`7bda04db`)의 내용:
- 모든 Dagster probe를 exec 형식 `python -I`로 바꿨다.
- code-server는 같은 gRPC health 호출을 `grpc_health`로 직접 한다(0.5초, deadline 8초).
- daemon은 120초 주기에 timeout 60초, retries 2다.
- 12개 서비스 모두 `init: true`다.

반영: Map·PinVi는 같은 pair 수렴으로, geo·weather는 `-p`/`--project-directory`를 명시한 호스트 직접 재생성으로 했다.
결과: 좀비 565 → 40, 동시 probe 47 → 1, weather code-server 복구.

이 PR은 Map 자체 compose(local dev와 n150 격리 스택)에 같은 계약을 넣고, `test_docker_dagster_runtime.py`가 exec 형식과
`init`을 command에서 유도한 서비스마다 요구한다.

## 2026-09-27 — minio/mc가 사라진 날: 세 저장소의 rustfs-init과 M05가 부딪힌 n150의 한계

M05 port(Manager #424) 뒤 첫 실제 격리 실행 p1은 claim과 Map fresh-init 사슬까지 통과했다. 그다음
`rustfs rustfs-init api frontend` 기동에서 `pull access denied for minio/mc`로 멈췄다. Docker Hub의 `minio/mc`와
`minio/minio` 저장소가 통째로 사라진 것이다. Map·PinVi·Manager 세 compose가 모두 이 이미지로 버킷을 만들고 있었다.
- PinVi는 digest로 핀했지만 저장소가 없으면 digest도 받을 수 없다.
- Manager는 rustfs 재생성 뒤 `run --rm rustfs-init`을 돌리고, 실패하면 mutation을 롤백한다. 즉 rustfs 재생성 자체가 막혀 있었다.

**고친 방법**: 새 클라이언트 이미지를 들이지 않았다. 각 저장소의 rustfs 서비스 이미지에 curl(8.19/8.21)이 이미 있어서,
`curl --aws-sigv4 aws:amz:us-east-1:s3 -X PUT <ep>/<bucket>`으로 버킷을 만든다.
- 이미 있는 버킷은 200(RustFS 실측) 또는 409 `BucketAlreadyOwnedByYou`로 성공이다. 4xx는 코드와 S3 본문을 남기고 즉시 실패한다.
- 적대 리뷰가 하나를 더 잡았다. RustFS는 `/health/live`가 200이 된 뒤에도 약 1.7초 동안 PUT에 `503 waiting for storage_quorum`을 준다.
  옛 mc는 minio-go가 이것을 안에서 재시도했다. 그래서 000·5xx 재시도와 요청 상한(connect 5s, max 30s)을 넣었다.
- Map의 `docker-compose.host.yml`은 스크립트 사본 대신 endpoint env 한 줄만 바꾼다.

**사이클**: 새 pair(Map `a18d9274` + PinVi `fd07903f`)로 회전해 chain17을 돌렸다. t62b는 rebuild `deployed`,
ACL 40/40, D1 11, D2 passed로 초록이었다. t62a에서는 pinvi-web 빌드가 37분 동안 `Build Steps 0/0`, I/O 0으로 보여
buildx bake를 끊었다. 나중에 docker.sock의 `/debug/pprof/goroutine?debug=2`로 보니, 같은 상태의 빌드는
`exportLayers → computeBlobChain → overlay.WriteUpperdir → gzip`에 있었다. node_modules 레이어를 파일 단위로 압축하는 중이었다.
**조용함은 정지의 증거가 아니었다.**

**M05는 n150 한계에 부딪혔다.** p2~p4는 모두 본문 진입 전 인프라 phase에서 멈췄다(scoped 차단, 실행권 미소비).
Map과 PinVi `rustfs-init`은 셋 다 `Exited (0)`이었다.
- p2: PinVi web export 약 40분 → `commit failed: context deadline exceeded`.
- p3·p4: PinVi `app-dagster`가 HEALTHCHECK 한도(약 150초)를 넘겨 unhealthy.

원인을 좁히니 운영 Dagster 스택들의 healthcheck였다. `dagster-daemon liveness-check`와 `dagster api grpc-health-check`는
주기마다 dagster를 import하는 Python을 띄운다(각 수 초, CPU 95%). 부하가 오르면 10초 타임아웃을 넘겨 다음 주기와 겹친다.
p4 도중 이런 프로세스가 47개 동시에 돌았고 load는 137까지 갔다. PID 1이 자식을 거두지 않는 Dagster 컨테이너들에는 좀비가
565개 쌓여 있었다. M05 빌드 부하가 이 되먹임에 불을 붙였다. 운영 서비스라 내리지 않았다. healthcheck 경량화와 `init: true`를
소유자 결정으로 올린다.

## 2026-09-27 — C6c 보호 참조를 표에서 규칙으로: 운영 데이터로 미리 돌려 본 것이 배포를 살렸다

Manager ADR-51 결정 5를 두 PR로 끝냈다. 대상은 UI·API 사용자가 compose env를 고칠 때 비밀이 엉뚱한 서비스로 새지
않게 하는 C6c 보호 참조다. 먼저 규칙을 옛 표 검사와 **나란히** 세웠고(P-1), 그다음 표를 지웠다(P-2).

- **규칙**: 설치기가 git에서 쓴 읽기 전용 사본 `.ktdm-release-compose.yml`이 원본이다. 후보가 어떤 자리(서비스 env key,
  다른 필드, 최상위 항목)에서 참조하는 보호 변수는 원본이 같은 자리에서 참조하는 것의 부분집합이어야 한다. 보호
  변수는 이름이 민감하거나, 값이 `.env` 비밀을 담는 변수다.
- **P-1에서 드러난 것**: 옛 표는 공유 PostgreSQL 비밀과 geo·concierge·weather·transport 비밀을 하나도 몰랐다.
  `grafana`에 `${KOR_TRAVEL_SHARED_POSTGRES_PASSWORD}`를 얹어도 통과했다.

값진 순간은 두 번 다 "운영 데이터로 미리 돌려 보기"에서 나왔다.
- **P-2의 거짓 양성**: 표 대신 파생 이름으로 bind 파일 내용을 스캔하게 바꾸자, n150의 실제 `rustfs-init` 스크립트가
  거부됐다. 스크립트가 자기가 쓰는 env 이름을 적었을 뿐이다. 이대로 머지했다면 모든 배포가 막혔을 것이다. 내용
  스캔은 이제 비밀 **값**만 찾는다. 옛 Map role bootstrap 면제 주석이 이미 그 원칙을 말하고 있었다.
- **적대 리뷰의 우회로**: 변수 이름 파서가 `str.isalnum()`을 써서 `$..._PG_DSNé`를 모르는 이름으로 읽었다.
  compose는 DSN을 치환한다. resolved 스캔을 지운 뒤라 막는 것이 없었다. 이름을 ASCII로 좁혔다. resolved 문서에는
  "비밀 값은 원본의 보호 참조 자리에만" 백스톱을 다시 세웠다.

n150 검증:
- 매 단계 `pin verify` 0, M05 preflight 0, 같은 pair 수렴 `converged`, 컨테이너 42개 재생성 0이다.
- 설치된 compose는 통과한다. 공유 비밀을 grafana로 옮긴 후보와 Map API 토큰을 map-ui로 옮긴 후보는 거부된다.
- 사본은 git과 바이트가 같다.

## 2026-09-27 — 실패 출력을 봉인에서 원문으로: 스크러버 하나, 채널 하나

Manager ADR-51 잃는 보장 G를 세 PR로 끝냈다. 순서는 "가리는 쪽 먼저"였다. G-1에서 스크러버 하나(`secret_scrub.py`)를
CLI·API 출력 경계에 먼저 세웠다. 그다음 G-2가 재구축 경로의 봉인을 풀어 원문 tail을 싣고, G-3이 M05의 opt-in forensic
증거 파일들을 "항상 캡처, 가린 `stderr.log` 하나"로 바꿨다. 순서를 거꾸로 하면 원문이 가림보다 먼저 나간다.

리뷰가 잡은 것은 이번에도 "출력 자리"였다. G-2에서 `compose config`의 stderr tail이 `ComposeCandidateContractError`를
타게 되자, 그것이 `ValueError`라서 `ktdctl action`·`ensure`의 `print(str(exc))`가 가리지 않은 채 냈다. 그래서 CLI의
예외 출력 20곳을 helper 하나로 모았다. 테스트는 원문 출력 자리가 없다는 사실을 본다. 스크러버의 원천도 고쳤다.
`.env`와 프로세스 환경을 합치면 한쪽 값이 사라진다 — compose는 프로세스 환경을, 스크러버는 `.env`를 앞세웠다.
이제 합치지 않은 key·값 쌍을 모은다.

G-3의 가장 값진 발견은 우연한 검사였다. M05의 fresh-init 진단 override는 서비스에 entrypoint만 얹었다. 서비스가
없으면 compose가 그 override를 거부했고, 그것이 claim 전에 났다. override를 걷으면 이 검사도 조용히 사라지고,
핀된 Map(서비스 이름이 `db-application-schema-fresh`로 바뀜)에서 M05가 실행권을 쓴 뒤에야 죽는다. 이제 claim 전에
명시적으로 본다. 생성 비밀은 목록 대신 생성·기록 시점에 스스로 등록된다. 옛 목록은 열한 개를 놓쳤다. 새 테스트는
driver가 **실제로 쓴** env 파일을 자식이 통째로 에코하게 하고, 민감 값이 하나도 새지 않는지 본다.

n150 검증:
- 재구축 probe(일부러 거부시킨 실행): JSON은 `{"status":"failed","stage":"environment_admission"}`이다. traceback
  마지막 줄에 진짜 원인이 있고, 비밀 71개 중 누출은 0이다.
- M05 negative probe 둘: 원인 문구가 나오고 누출은 0이다.
- 같은 pair 수렴: 두 번 다 `converged`, 컨테이너 42개 재생성 0이다.
- 맞춰서 `scripts/n150/chain17.sh`도 원인을 숨기지 않게 했다. 회전 preflight 사유와 회전 실패 출력 전체를 보이고,
  재구축이 실패하면 stage와 `stderr.log` 끝 80줄을 보인다. 회전 종료값을 보게 되면서 재실행 경로가 생겼다. C에서 실패한 뒤 다시 돌리면 같은 pair 회전을 registry가 거부하므로, 원장이 이미 그 Map이면 B를 건너뛴다(리뷰가 잡았다).

## 2026-09-27 — 소스 봉인을 걷어냈다: SHA가 곧 증명, 이름 붙은 디렉터리가 곧 캐시

Manager ADR-51 잃는 보장 E를 세 PR로 끝냈다. 순서는 이번에도 "읽는 쪽 먼저"였다. E-1에서 재구축의 Map 계약
reader를 git이 아니라 파일 읽기로 옮겨 두지 않았다면, E-3에서 source가 `.git` 없는 archive가 되는 순간 모든
재구축이 `candidate_contract`에서 죽었을 것이다 — 그런데 그 reader를 부르는 유일한 테스트는 함수를 통째로
대역으로 바꾸고 있어서 CI는 초록이었을 것이다([낡은 테스트 대역이 계약 파손을 가린다]).

E-2에서 M05는 archive가 아니라 실행별 checkout을 쓴다. PinVi attestation이 진짜 clean checkout과 Map의 service
릴리스 blob을 요구하기 때문이다. 적대 리뷰가 잡은 가장 중요한 것은 테스트의 맹점이었다 — full-path harness의
checkout 대역이 preflight 트리를 그대로 복사해서, body가 Map compose나 `--map-source-root`를 옛 트리로 되돌려도
모든 테스트가 통과했다. 이제 두 checkout이 생긴 뒤 preflight 트리를 치워 버린다(변이 3종이 red).

E-3의 해석 하나: "실행마다 fetch"를 "없을 때만 fetch, 같은 revision은 재사용"으로 읽었다. 디렉터리 이름이 SHA이니
재사용이 곧 증명이고, 같은 pair 수렴이 네트워크 없이 끝난다. 대신 재사용이 git 없이 이뤄지므로 두 가지를 더했다 —
이름을 붙이기 전에 `os.sync()`, 기록이 손상되면 거부하지 않고 다시 만들기(거부하면 수동 삭제 전까지 모든 재구축이
막힌다). 또 `tarfile`의 `data` 필터가 디렉터리 mode를 적용하지 않아 M05의 umask 077을 따르면 이미지 안에 0700
디렉터리가 구워질 뻔했다 — 디렉터리를 0755로 고정하고 변이로 확인했다.

E-2 검증 삼아 실제 M05를 한 번 돌렸는데 claim 전 단계에서 거부됐다. E-2 탓이 아니라 Map #1259가 지운
`docker-compose.local-dev.yml`과 옛 role을 M05 driver가 아직 쓴다 — 9월 23일 이후 M05 전체 실행은 가능하지 않았다.
정기 게이트가 preflight까지만 보기 때문에 아무도 몰랐다.

## 2026-09-27 — 설치기를 1,887줄에서 196줄로: 레이아웃을 먼저 옮기고 나서 설치기를 바꿨다

Manager ADR-51의 잃는 보장 D(설치기)를 끝냈다. D-1/D-2와 같은 순서를 따랐다 — **설치 root가 symlink여도
모든 소비자가 도는 코드(I-1)를 옛 설치기로 먼저 깔고**, 손으로 한 번 레이아웃을 옮긴 뒤, 새 설치기(I-2)를
그 위에 설치했다. 거꾸로 하면 새 설치기가 만든 symlink를 옛 코드(재구축 root·M05·rebind·관리자 비밀번호)가
`lstat`으로 거부해 모든 mutation이 멈춘다.

핵심 규칙은 하나였다: **compose 프로젝트 루트는 resolve하지 않는다.** 풀린 release 경로가
`--project-directory`에 들어가면 상대 bind source가 `/opt/ktdm-release-<sha>`로 굳어 설치마다 컨테이너가
재생성되고, 그 release가 GC되면 재시작에서 깨진다. n150에서 compose v5.2와 venv가 symlink 경로를
그대로 쓰는지 먼저 봤고, 인수에서는 같은 pair 수렴 뒤 컨테이너 42개의 bind 문자열과 생성 시각이 그대로인지를
봤다. 반대로 비교하는 쪽은 양쪽을 다 풀어야 했다 — operator bind의 backend 소스 가드는 한쪽만 풀고 있어서
symlink root에서 조용히 통과하고 있었다(I-1에서 고침).

적대 리뷰가 I-1에서 한 건(revision을 읽는 두 곳이 root 소유·쓰기 금지 검사까지 지웠다), I-2에서 일곱 건을
확정했다. I-2의 가장 쓸모 있던 지적은 재기동 한도였다 — 깨진 release가 `StartLimitBurst`를 넘기면 그
직후의 롤백 설치가 `systemctl start`에서 거절되어 backend가 내려간 채 남는다. `reset-failed`를 먼저 부른다.
반박된 보안 지적 몇 개(운영자 소유 clone에서 root가 설치기를 실행한다, `python -m venv`가 cwd를 import한다)도
한두 줄이라 받아들였다 — 이제 설치기는 root 소유 clone만 받고 git도 root로 돈다.

부수 효과: 옛 헬퍼가 설치본 안에서 `npm ci && npm run build`를 돌려 release마다 790MB가 쌓였는데, 프론트
유닛은 운영자 홈의 사본에서 돈다 — 아무도 쓰지 않는 빌드였다. 새 release는 83MB다.

## 2026-09-27 — 봉인을 걷어낸 체인으로 한 바퀴: D 완료와 최종 인수

Manager ADR-51 D를 세 PR로 끝냈다. 순서가 핵심이었다 — **읽는 쪽을 먼저 옮기고(D-1), 그다음 쓰기를
멈추고(D-2), 마지막에 mount를 걷는다(D-3)**. 거꾸로 하면 v6 쓰기를 멈춘 첫 새 pair 배포 뒤 M05가
"pinset이 다르다"로 막힌다. D-1은 n150에서 v6 파일 둘을 잠시 치워도 `pin verify`와 M05 preflight가
그대로 0인 것으로 "아무도 읽지 않는다"를 확인했고, D-3은 네 컨테이너를 다시 만들며 permit 마운트와
env 이름이 사라진 것을 봤다.

적대 리뷰는 D-1에서 문구 하나(v6 동결 이유를 여전히 "M05가 읽어서"로 적음)만 잡았고, D-2·D-3에서는
발견이 없었다. 한 가지 운영 실수: PinVi 문서 PR의 머지가 CI 완료 전에 실패했는데 스크립트가 원격
브랜치를 지워 PR이 닫혔다 — 커밋을 다시 올려 reopen 뒤 머지했다(merge 결과를 확인한 뒤에만 브랜치를
지울 것).

최종 인수로 최신 Map main(`b4fbde1e`)을 새 pair로 chain17에 태웠다. 전진 배포는 같은 DB 위에서 전체
경로를 돌았고(oid 그대로), v6 파일은 D-2 이전 시각 그대로, permit 없이 storage one-shot이 끝났다.
ACL 40/40 → D1 11 passed → D2 passed. 봉인·신뢰 릴리스 단순화(ADR-102 / Manager ADR-51)는 여기서
닫는다.

## 2026-09-27 — 락을 먼저 합치고 나서 줄였다

Manager ADR-51 C를 세 PR로 끝냈다. 결정 6이 순서를 정해 두었다 — rehearsal에서 UI mutator가 다른 락 파일을
잡고 있었으므로, **먼저 모두를 G 하나로 모은 뒤에야** pinned lease와 env 파생 락을 지울 수 있었다. 거꾸로 하면
지우는 순간 한동안 "한 번에 한 mutator"가 깨진다.

C-1에서 드러난 것: CLI의 pin 변이 검사들은 **환경의 우연**으로 초록이었다. CI에는 `/run/lock/...`이 없어서,
n150 비root에서는 읽을 수 없어서 락 없이 진행하는 갈래로 빠졌다. 그 갈래를 지우자 전제가 사라졌고, conftest가
테스트마다 G를 자기 소유 tmp 디렉터리로 옮기게 했다([검사의 전제가 환경의 우연이면]). 그 픽스처의 정리 순서가
다른 테스트의 `os.open` 대역과 부딪혀 한 번 더 고쳤다.

적대 리뷰가 C-3에서 잡은 것 중 기억할 만한 것: 지운 락 경로 대조를 대신한다고 둔 `.env` 대조가 **같은 객체끼리
비교해 실패할 수 없었다**. 재구축의 진짜 보호는 본문 내내 쥔 G와 동결된 snapshot이다 — 없는 보호를 있다고
적느니 지우고 그렇게 적었다. 그 삭제를 정규식으로 하다 한 호출이 `with` 블록의 유일한 문장이라 모듈 전체가
SyntaxError가 된 것도 n150이 잡았다(커밋 전에 파싱 한 번이면 됐다).

n150: 같은 pair 수렴 재구축 중 `lslocks`에 `global-mutation.lock` 하나만 보였다.

## 2026-09-26 (자정 무렵) — Manager B3: 6,900줄을 지우는 동안 리뷰가 잡은 것은 검사와 문구였다

첫 새 pair가 단순화된 체인으로 D2까지 선 뒤, Manager의 v8 journal 시절 코드를 세 PR로 걷어냈다
(#405 carry-over·죽은 증거, #406 journal 모델, #407 journal 시절 관리자·preflight 화면). 지운 것은 약
6,900줄이다. 각 PR에 적대 리뷰를 돌렸고, 잡힌 것은 런타임 결함이 아니라 **검사와 문구**였다.

- PR-1의 "옛 v6/v8 파일을 넘겨받지 않는다" 검사는 `{}` 바이트를 심었는데, 옛 carry-over도 파싱 실패를
  삼켜 None이 되므로 carry-over가 되돌아와도 초록이었다. 옛 코드라면 넘겨받았을 커밋된 세대를 심자
  B2 시점 src에서 빨개졌다 — [검사기 하한은 '본 것'에 건다]의 또 한 예.
- PR-2는 pinset digest를 여전히 "Map과 공유하는 계약"이라 적어 같은 문서의 "Map이 그 코드를 지웠다"와
  모순됐다. 이제 이유는 디스크다(원장·보존 사본·차단 목록·실행 원장이 모두 그 digest로 묶인다).
- PR-3은 현재 세트에 옛 차단 기록이 있을 때 패널 머리가 서버의 `pin verify` 대신 "회전해야 합니다"를
  보였다 — 같은 패널 아래의 "재구축은 경고일 뿐"과 모순.

n150 설치 뒤 `pin verify`·공개 세대 리더·M05 preflight·같은 pair 수렴이 모두 그대로였다. 하나 배운 것:
설치본을 직접 호출해 검사할 때 `python -I`는 서비스의 `PYTHONPATH=backend/src`를 버려 `.env` 경로를
site-packages 기준으로 잘못 잡는다 — preflight가 `MODE_UNVERIFIABLE`로 보였지만 서비스 환경에서는
`rehearsal/rebuildable`이었다.

## 2026-09-26 (늦은 밤) — 봉인 없이 한 바퀴: 첫 새 pair가 D2까지 섰다

M1(#1270)과 M2(#1272)를 머지하고 `/root` 호스트 스크립트를 머지 커밋에서 설치한 뒤, 새 pair(Map
`031205ff`)를 단순화된 체인으로 처음 돌렸다. 회전 전 pair 계약 preflight(유지한 hard gate) → 전진 배포
`deployed` → repin(원장 대조와 이미지 라벨뿐) → ACL 40/40 → D1 11 → **D2 passed**. 전진 배포는 DB를 지우지
않았고(oid 그대로), M1의 storage one-shot이 처음으로 **이미 head인 영속 metadata DB 위에서** 돌았다.
D2는 root 소유 스냅샷이 아니라 D1과 같은 git archive 체크아웃에서 돌았고, BLOCKED/result는 v4였다.

M2에 붙인 `adjudicate.sh`(rebuild가 가로지른 BLOCKED 정리)는 호스트 사본을 옮기다 결함 셋을 드러냈다.
옛 사본은 M2 뒤 늘 실패했고(퇴역한 env 키와 스냅샷 경로), 옮긴 판에도 적대 리뷰가 major 하나를 잡았다 —
러너의 lock을 잡지 않고 ACTIVE·run 컨테이너를 보지 않아, timeout으로 죽은 D2의 BLOCKED(recover의 유일한
앵커)를 지울 수 있었다. 재검증은 lint가 가드 **삭제**만 잡고 `|| true` 같은 **약화**는 놓친다는 것을 보였다.

t59a 로그에는 작은 것이 하나 더 있었다. chain16 step E가 공유 체크아웃 `/tmp/ktm-lint`에서 `fetch` 뒤
M01 preflight를 꺼내는데 fetch 실패(`unresolved deltas`)를 보지 않아, 옛 origin/main 사본이 조용히 돌았다.
배포한 SHA에서 꺼내고 실패하면 멈추게 고쳤다.

## 2026-09-26 (밤) — 배포는 이제 DB를 지우지 않는다: Manager B2 설치, 같은 pair가 45초에 수렴했다

Manager ADR-51 B2(#404)를 머지·설치했다. 재구축 본체가 v8 journal 상태기계에서 **마이그레이션 전진**으로
바뀌었다 — 영속 상태는 `deploy-status.json` 하나, 재개 없음, 리셋은 `--restart`뿐.

**적대 리뷰가 내 수정을 두 번 잡았다.** 1차 리뷰 반영에서 "판정 전에는 PostgreSQL을 멈춰 있을 때만
띄운다"로 바꿨는데, 2차 리뷰(5개 관점이 독립으로 같은 결함에 도달)가 그 변경이 major 둘을 만든 것을
보였다: 떠 있는 DB 컨테이너의 이미지가 바뀌면 `--restart`까지 모든 실행이 같은 자리에서 영구히 막히고,
PGDATA가 바뀐 호스트에서는 **옛 컨테이너로 identity 기준선을 통과한 뒤 새 cluster를 만들어 커밋**했다 —
`--restart` 없는 리셋. 두 PostgreSQL을 판정보다 먼저 `up`하고 전체 경로는 다시 `up`하지 않는 것으로
고쳤다. 3차(2차 수정의 검증)는 다시 minor 둘을 잡았다 — 리셋 여부를 "기준선이 비었는가"로 추측하면
기준선 없이 시작한 `--restart`가 리셋 전에 죽어도 리셋으로 기록된다. 리셋이 끝나면 `step=reset`을
쓰는 것으로 바꿨다. 고친 것마다 결함을 되살려 테스트가 빨개지는 것을 확인했다(변이 18/18).

**n150.** 설치(`13e744b`) → `pin rebind-execution` → 같은 pair(`6511441f`/`b227e77b`)로 첫 전진 배포.
기대한 carry-over(지금 세대를 그대로 넘겨받기)는 일어나지 않았다 — state root에 **옛 계약의 v8 journal
62개가 더는 읽히지 않고**, 읽을 수 없는 journal이 하나라도 있으면 넘겨받지 않는다는 규칙이 걸렸다.
설계된 대안인 "기준선 없는 전체 경로 한 번"으로 갔고(150초, 리셋 없음), DB oid가 t57d가 만든 것과
정확히 같다(1186381 / 1191333 / 430243). ADR-069 토폴로지 PASS, D1 11 passed. **두 번째 실행은
`converged` 45초**, 런타임 컨테이너를 재시작하지 않았다.

## 2026-09-26 (저녁) — 42GB를 비우니 배포가 한 번에 섰다

#401을 설치하고 같은 pair(Map `6511441f` / PinVi `b227e77b`, pinset `e4909e26`)로 chain17을 두 번
더 돌렸다. **t57b**는 pinvi-dagster 빌드 중 BuildKit session healthcheck 실패로 죽었고, **t57c**는
journal 전에 내가 멈췄다 — 둘 다 코드가 아니라 호스트였다. SATA SSD가 91% 차 있었고 IO 압력 `full`이
여전히 50~60%였다. 타임아웃을 늘리는 것은 증상 완화라, 이번에는 원인을 줄였다.

디스크 조사는 후보마다 "지워도 되는가"를 따로 반박하게 했고, 결과를 세 층으로 나눴다. 캐시와 재생성
가능한 것(옛 pinset·리허설 이미지, 고아 볼륨, Manager의 옛 pinset 소스 78개, npm/uv/pip 캐시,
지난 e2e·C7·M05 스크래치)만 지웠다. 42G → 84G(91% → 82%), IO `full`은 약 3%로 떨어졌다. 백업·덤프
(약 31GB)와 다른 세션의 작업 디렉터리(약 18.5GB)는 되돌릴 수 없어 소유자 판단으로 남겼다. 지우는
명령도 추측이 아니라 명시 목록이었다 — `docker volume prune`은 현재 스택이 아닌 이름 붙은 볼륨까지
삼키고, 옛 작업 디렉터리 하나는 다른 worktree들의 git 디렉터리였다.

**t57d**는 같은 pair로 끝까지 섰다. rebuild success → executor 이미지 → repin(verifier PASS) → M01 ACL
preflight 40/40 → **D1 11 passed** → **D2 `phase: passed`**(lane에 BLOCKED/RESULT/ACTIVE 없음).
ADR-069 토폴로지도 확인했다: Map·PinVi 각각 code-server/webserver/daemon healthy, companion 이미지 =
owner 이미지, code location LOADED(Map 48 jobs, PinVi 9 jobs). gRPC 12703/12803은 `ss`에
`[::ffff:127.0.0.1]`로 보인다 — host network에서 dual-stack 소켓이 loopback에 묶인 모습이고, 호스트의
비-loopback IPv4 29개에서 전부 거부되는 것을 직접 확인했다(내 검증 스크립트가 `127.0.0.1:` 표기만 받던 것을
고쳤다).

## 2026-09-26 (오후) — 디스크가 포화된 호스트의 60초, 그리고 배포는 데이터를 지우지 않기로

**t57a.** #399를 설치하고 새 pinset `8451c8a3`으로 chain17을 돌렸다. 후보 빌드 49분 뒤, journal을
쓰기도 전에 `application_candidate`에서 죽었다. 이번에는 봉인된 stage 한 단어가 아니라 #399가 남긴
원인 원문(비밀 가림)이 stderr에 있었다 — `docker run --network none … ktm-application-schema head`가
60초 타임아웃. 같은 명령을 손으로 돌리니 정상 출력(`head: 400`)에 74초, `docker run --rm /bin/true`
하나에 112초였다. n150의 SATA SSD는 92% 차 있고 `/proc/pressure/io`의 `full`이 5분 평균 50%다.
컨테이너 하나 띄우는 데 1~2분이 드는 호스트에서 60초 정적 검사는 멈춤 감지가 아니라 오탐기다.
같은 이유로 ADR-069 뒤 직렬이 된 Map `up --wait`(code-server → webserver → daemon)도 300초로는
위험하다. 둘 다 올렸다(600초, 900초). 디스크 포화 자체는 열린 문제로 남긴다.

**배포 모델.** 봉인·신뢰 릴리스 단순화 설계를 소유자에게 올렸고 잃는 보장 목록 전체가 승인됐다.
하나는 설계의 전제를 바꿨다 — **DB를 배포마다 지우지 않는다.** 설계는 "새 pinset = DB 리셋"을
깔고 있었는데, 재조사해 보니 journal 상태기계의 대부분이 그 리셋 때문에 존재했다(리셋 도중 죽으면
어디서 재개하나, 이 DB가 이번 회차에 만든 그 DB인가). 리셋을 명시적 `--restart`로만 두면 재개도
receipt도 permit도 필요 없어지고, 전역 상태 파일 하나(absent/in_progress/committed)와 멱등
one-shot만 남는다. Map 쪽 결정은 ADR-102로 남겼다: migration forward-only, stamp bridge 없는
재스쿼시 금지, storage one-shot 멱등화, 런타임 `verify-identity`·argv 봉인 제거(loopback 가드만),
C7 attestation 체인 제거(ADR-094 대체). 대가도 함께 적어 두었다 — 배포가 더는 빈 DB 경로를 증명하지 않고,
손으로 만든 drift가 살아남고, 낮은 head로는 되돌릴 수 없다.

## 2026-09-26 — 재구축은 Map code-server를 한 번도 띄운 적이 없었다

어제 항목의 "재시도 예정"은 네 번 더 실패했다(t56c~t56h). 원인은 셋이 겹쳐 있었고, 봉인된
실패 출력 때문에 하나씩 벗겨 내는 데 사이클마다 1~2시간이 들었다.

**1. PinVi가 먼저 막았다 — SQLAlchemy 2.1.0.** 같은 날 나온 2.1.0이 bare `postgresql://`
URL의 기본 driver를 psycopg2에서 psycopg(v3)로 바꿨다. PinVi etl 이미지에는 psycopg2만 있어
dagster-postgres의 동기 엔진이 `ModuleNotFoundError: psycopg`로 죽었다(새로 빌드한 webserver만,
옛 이미지의 code-server·daemon은 멀쩡). Map #1265와 같은 무상한 핀 문제 — pinvi#565로 `<2.1`.

**2. 내 비상 패치가 두 사이클을 날렸다.** 서비스를 살리려고 `/opt` compose의 webserver/daemon
명령을 `-m`으로 되돌린 패치를 두 번 넣었는데 두 번째는 되돌리지 않았다. 그 상태로 t56g·t56h가
돌았고, 새 이미지의 봉인 entrypoint가 `-m` argv를 fail-close해 compose up에서 죽었다. 그 사이클의
journal은 패치본 compose sha(`9296daab…`)를 동결해 pinset `a7cc0414`는 재개 불가다. 신뢰 릴리스
사본(`8ac4ed17…`)으로 원복했고, 이 커밋이 새 pinset을 만든다.

**3. 근본 — `up --no-deps`가 depends_on을 지운다.** Manager의 pinned rebuild는 Map을
`up -d --no-deps --wait kor-travel-map-ui kor-travel-map-dagster kor-travel-map-dagster-daemon`로
띄운다. compose-go는 `--no-deps`에서 호출에 이름이 없는 서비스로의 간선을 지우므로, webserver가
code-server에 `service_healthy`로 의존해도 code-server는 **기동되지 않는다**(dockerd 로그상 어떤
재구축도 띄운 적 없음). 게다가 webserver healthcheck는 빈 `RepositoryConnection`도 통과시켜
`--wait`가 초록이었고, D1의 Dagster 단언은 instance storage의 run 개수뿐이라 code location을 안
본다 — 신뢰 compose로 돈 사이클이 끝까지 갔다면 저장소 0개인 Dagster가 GREEN으로 커밋됐을 것이다.
PinVi code-server·daemon도 같은 이유로 재구축이 정지·재생성한 적이 없어 DB 리셋을 건너 옛
이미지로 옛 코드를 서빙하고 있었다(어제 내가 수동으로 띄운 것).

**수정(Manager #399).** slot 이미지를 그대로 쓰는 비-slot
장기 실행 서비스를 frozen resolved compose에서 파생해("generation companion") owner slot과 같은
stop/up/readiness/image 대조/secret inspection에 태운다. 실제 `docker compose config`로 세 개
(Map code-server, PinVi code-server·daemon)가 나오는 것을 확인했다. 영속 포맷(v6 manifest, v8
journal, 7-slot)은 그대로다. 같은 PR에서 봉인 단순화의 첫 걸음으로 `rebuild-pinned` 실패 시
예외 체인 전체를 `.env` 비밀과 URL userinfo를 가려 stderr에 남긴다(JSON·종료코드는 그대로) —
이번에는 원문을 보려고 설치본 `cli.py`에 계측을 심고 파괴적 재구축을 다시 돌려야 했다. 그리고
PinVi code-server가 host network에서 `-h 0.0.0.0`으로 인증 없는 gRPC를 LAN에 열고 있어
`127.0.0.1`로 묶었다.

첫 커밋의 테스트는 반쪽이었다. 적대 리뷰가 companion 호출처 10곳 중 8곳은 하나씩 지워도 아무
테스트도 안 깨진다는 것을 확인했다 — 이번 결함(호출 하나에서 이름이 빠짐)이 그대로 재발할 수 있는
자리다. `cancel_probe_finalized`에서 commit까지, 이어서 committed 재개까지 도는 테스트를 더하고
n150에서 변이 검사로 10곳 + one-shot 제외 규칙 + 프로세스 환경 리댁션 12개가 각각 빨개지는 것을
봤다. 같은 규칙을 명령으로 검출하다 보니 **geo code-server도 host network에서 `0.0.0.0`**이었다.
geo 이미지의 workspace host를 확인하기 전에는 못 바꾸므로 알려진 예외로 등록하고, 해소되면 예외를
지우라고 빨개지게 했다.

**봉인·신뢰 릴리스 단순화(소유자 지시).** 네 덩어리(설치기 1,887줄, 재구축 실패 봉인, pinset·
journal·실행 레지스트리 결박, Map storage permit/receipt/intent)를 조사해 설계를 만들었다. 적대
리뷰가 짚은 쟁점: UI/API 사용자가 compose env를 직접 편집하므로 C6c 보호 참조 표는 파생 규칙으로
대체해야지 지우면 안 된다, 호스트 스크립트(repin.sh/gen_attest.py)가 v6/v8 파일에 묶여 있다,
committed never-reset 가드는 DB identity 없이는 안전하지 않다, 매 배포 DB 리셋(destructive-by-default)
자체가 상태기계의 근원이다. 잃는 보장 목록을 ADR로 올려 승인받은 뒤 단계적으로 진행한다.
