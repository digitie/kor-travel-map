# scripts/n150 — n150 재핀 사이클 호스트 스크립트

ADR-102 결정 6에 따라 n150 `/root`에만 있던 재핀 사이클 스크립트를 저장소에서 버전
관리한다. 저장소가 정본이고, 호스트 사본은 그것을 복사한 것이다.

| 파일 | 역할 |
| --- | --- |
| `chain17.sh` | 전체 사이클: pair 계약 preflight → 회전 → Manager rebuild → `chain16.sh` |
| `chain16.sh` | 후반부: C7 executor 이미지 → `repin.sh` → M01 ACL preflight → D1 → lane 정리 → D2 |
| `repin.sh` | 핀 원장 대조, executor 이미지 라벨 확인, `/root/.d2-live.env`의 비밀 아닌 두 키 갱신, D2 fixture DSN 유도 |
| `run-d2.sh` | D2 러너를 D1과 같은 체크아웃(`/home/digitie/ktm-c7-$MAP`)에서 실행 (chain16의 systemd unit) |
| `adjudicate.sh` | rebuild가 가로지른 v4 BLOCKED lane을 잔여물 0 실측 뒤 `clear-blocked`로 정리 (chain16 lane 정리 단계) |

## DB에 닿는 법 — instance를 적지 않는다

스크립트에는 Map DB instance의 이름·port·superuser가 없다(ADR-103 — prod Map DB는 전용
instance에서 공용 instance로 옮긴다). DB 접근은 **실행 중인 Map API 컨테이너**에서 유도한다.
그 컨테이너는 세 스크립트(`repin.sh`, `chain16.sh` M01 preflight, `adjudicate.sh`)가 D2 러너와
같은 방법으로 찾는다: `docker compose --project-directory /opt/kor-travel-docker-manager ps
--no-trunc -q "$E2E_C7_MAP_API_SERVICE"`, 정확히 하나. 러너가 도는 compose project(`run-d2.sh`의
cwd)로 좁히므로 같은 service 라벨을 단 다른 stack(격리 live 등)의 컨테이너를 집지 않는다.
`tests/unit/test_n150_scripts_have_no_instance_literals.py`가 이름이 아니라 효과를 지킨다 —
PostgreSQL client 호출, DSN의 `host:port/`, port flag, 유도한 API 컨테이너가 아닌 곳으로의
`docker exec`가 없다.

- `adjudicate.sh`의 잔여물 네 줄은 그 컨테이너 **안에서** `docker exec -i <api> python -I -B -`로
  센다. 프로그램은 컨테이너 자신의 `KOR_TRAVEL_MAP_PG_DSN`(`+asyncpg`를 떼고)으로 붙어
  `READ ONLY` transaction에서 `SET LOCAL ROLE ktm_feature_schema_owner` 뒤 세고 `ROLLBACK`한다.
  `run_id`는 bind parameter다. 비밀은 호스트 argv를 건너지 않고, 도구는 아무것도 쓰지 못한다.
- `repin.sh` 3단계는 `/root/.d2-live.env`의 `E2E_ADMIN_FEATURE_FIXTURE_PG_DSN` 한 줄을 그
  컨테이너의 `KOR_TRAVEL_MAP_PG_DSN`으로 바꾼다(2026-09-28 실측으로 두 값은 사용자·host:port·DB·
  비밀번호가 같다). helper가 `docker inspect`를 직접 불러 값을 메모리에서만 다루고 출력하지 않는다.
  쓰기 전에 사용자 = `E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE`, 경로 =
  `/$E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE`, scheme ∈ {`postgresql`, `postgresql+asyncpg`}
  (D2 러너 `validate_env`와 같다)이고 따옴표 없이 source할 수 있는 문자만 있는지 본다. 파일은 같은
  디렉터리의 0600 임시 파일에 쓰고, 소비자와 같은 `set -a; .`로 그 임시 파일을 읽은 **값**이
  API DSN과 같을 때만 rename한다(`:~`처럼 문자 검사는 지나도 tilde 확장으로 바뀌는 값을 막는다).
  rename 뒤에는 그 키가 정확히 한 줄로 바뀌었는지 센다.
  DB가 어느 instance로 옮겨 가든 다음 주기의 repin이 그 값을 따라간다.
- `chain16.sh`의 M01 ACL preflight는 여전히 `KOR_TRAVEL_MAP_PG_DSN`을 fixture DSN으로 덮는다.
  repin 뒤에는 같은 값이라 결과가 같다 — preflight가 D2가 쓸 바로 그 DSN을 본다는 것을 남긴다.

## 설치

운영자가 root로 `/root`에 복사한다. 스크립트는 서로를 `/root/<이름>`으로 부른다.

```sh
# 저장소 체크아웃에서 (예: /home/digitie/ktm-c7-src, 원하는 main 리비전)
sudo install -o root -g root -m 0700 scripts/n150/chain17.sh scripts/n150/chain16.sh \
  scripts/n150/repin.sh scripts/n150/run-d2.sh scripts/n150/adjudicate.sh /root/
```

호스트 사본을 손으로 고치지 않는다. 고칠 것이 있으면 저장소에서 고치고 다시 복사한다.

## 무엇이 Manager 쪽인가

- `chain17.sh`는 회전과 rebuild를 **Manager의 sanctioned launcher**로 한다 —
  `/opt/kor-travel-docker-manager/scripts/rotate-pinned-pair`와 `run-pinned-rebuild-once`.
  Map 스크립트가 Manager 상태를 직접 쓰지 않는다.
- pair 계약 preflight(M05 `m05_isolated_e2e.py --rotation-preflight`)는 회전 전의
  **hard gate**다. 거부되면 아무것도 바꾸지 않고 멈춘다.
- 핀 원장은 `ktdctl pin show`로만 읽는다. Manager의 내부 파일(v6 pinned runtime
  manifest, v8 rebuild journal, 앞으로의 `deploy-status.json`)은 읽지 않는다.

## ADR-102로 사라진 것

D1·D2는 핀된 SHA의 평범한 `git archive` 체크아웃에서 돌고, 그 기능 단언이 게이트다.
다음은 더 만들지도 읽지도 않는다.

- `gen_attest.py`와 host attestation(`/etc/kor-travel-map/c7-prod-live-e2e-attestation.json`)
- `/etc/kor-travel-map/c7-pinned-runtime-{generation-v6,rebuild-v8}-*.json` 사본
- root 소유 러너 스냅샷 `/usr/local/lib/kor-travel-map/{c7-runner,admin-feature-live-acceptance}/<sha>/`
  (`source-manifest.json` 포함)
- `.d2-live.env`의 `E2E_C7_PINNED_RUNTIME_MANIFEST`·`E2E_C7_REBUILD_JOURNAL` (`repin.sh`가 지운다)

호스트에 남은 위 파일은 운영자가 정리한다. 러너는 그것이 있든 없든 보지 않는다.

## BLOCKED 정리

`adjudicate.sh`는 D1·D2와 같은 체크아웃의 상태 helper로 **v4** BLOCKED만 정리한다. 옛 v3
BLOCKED가 남아 있으면 이유와 함께 멈춘다 — runbook `admin-feature-live-acceptance.md` §6대로
그것을 만든 커밋의 도구로 정리한다. chain16은 판정 뒤에도 BLOCKED가 남으면 D2 전에 멈춘다.
