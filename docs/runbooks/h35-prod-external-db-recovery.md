# H35 prod external DB recovery gate

이 문서는 `T-VN-H35` 배포 전에 **외부 PostgreSQL prod DB 2개(app + Dagster)** 가
실제로 복구 가능한지 증명하는 전용 gate다. 목적은 migration 실행이 아니라,
writer가 멈춘 같은 시간 창에서 뜬 custom-format dump가 disposable PostGIS 16 scratch
서버에 복원되고, 복원된 DB가 prod baseline과 일치함을 증명하는 것이다.

기존 standalone `scripts/docker-backup.sh` / `scripts/docker-restore.sh`는 prod
external DB 복구 수단이 아니다. H35에서는 `scripts/run-prod-external-db-recovery-gate.sh`
만 사용한다.

## 안전 경계

- production 전용 명시 opt-in 없이는 실행하지 않는다.
- 실행자는 root여야 한다. state/evidence root는 root 소유 `0700`, 민감 파일은 `0600`
  이다.
- root가 user-writable checkout의 스크립트를 직접 실행하지 않는다. 실행 전에 정확한
  Git SHA를 `git archive`로 root 소유 `0555` snapshot에 설치하고, 그 snapshot의
  `scripts/run-prod-external-db-recovery-gate.sh`를 실행한다.
- docker-manager의 global mutation lock과 같은 파일을 non-blocking `flock`으로 잡는다.
  lock을 잡지 못하면 아무 dump도 만들지 않는다.
- API, Dagster web, Dagster daemon writer container가 정지돼 있고, app DB write
  transaction 수가 `0`임을 dump 직전과 두 DB dump 직후에 다시 확인한다.
- source DB 자격증명은 argv, stdout/stderr, manifest, Docker label/env에 넣지 않는다.
  root `0600` `PGSERVICEFILE` / `PGPASSFILE`을 임시 credential directory에 복사해
  read-only bind mount로만 PostgreSQL client container에 전달한다.
- PostgreSQL client image는 아래 digest로 고정하고 `--pull=never`만 쓴다.
  실행 시 local image ID도 evidence manifest에 기록한다.

```text
postgres@sha256:33f923b05f64ca54ac4401c01126a6b92afe839a0aa0a52bc5aeb5cc958e5f20
postgis/postgis@sha256:8b33190b6486ab9905dea999171817c1ac461733a7078dd4c836091c6e6b5d40
```

## 실행 전 설치

예시는 placeholder만 쓴다. 실제 prod 접속값과 경로는 local deploy runbook에서 확인한다.

```bash
cd <map-repo>
git fetch origin
git rev-parse origin/main

install_root=/opt/kor-travel-map/h35-external-db-gate/<40-char-sha>
sudo install -d -o root -g root -m 0555 "$install_root"
git archive --format=tar <40-char-sha> \
  docs/runbooks/h35-prod-external-db-recovery.md \
  scripts/run-prod-external-db-recovery-gate.sh \
  | sudo tar -x -C "$install_root"
printf '%s\n' '<40-char-sha>' | sudo tee "$install_root/GIT_REVISION" >/dev/null
sudo chown -R root:root "$install_root"
sudo find "$install_root" -type d -exec chmod 0555 {} +
sudo find "$install_root" -type f -exec chmod 0444 {} +
sudo chmod 0555 "$install_root/scripts/run-prod-external-db-recovery-gate.sh"
```

## 자격증명 파일

`PGSERVICEFILE`은 app와 Dagster service를 모두 담는다. `PGPASSFILE`은 두 service가
참조하는 host/port/database/user 조합만 담는다. 두 파일은 root 소유 `0600`이어야 한다.

```ini
[h35-app]
host=<prod-db-host>
port=<prod-db-port>
dbname=kor_travel_map
user=<app-db-user>
sslmode=prefer

[h35-dagster]
host=<prod-db-host>
port=<prod-db-port>
dbname=kor_travel_map_dagster
user=<dagster-db-user>
sslmode=prefer
```

## 실행

`--source-network`는 source DB에 도달하기 위한 client container network만 지정한다.
scratch server는 항상 별도 `--internal` network, no published ports, no host bind로
생성된다.

```bash
sudo /opt/kor-travel-map/h35-external-db-gate/<40-char-sha>/scripts/run-prod-external-db-recovery-gate.sh \
  --i-understand-this-is-production \
  --expected-git-sha <40-char-sha> \
  --manager-lock-file <docker-manager-global-mutation-lock> \
  --state-dir /var/lib/kor-travel-map/h35-external-db-recovery \
  --pgservice-file /root/h35/pg_service.conf \
  --pgpass-file /root/h35/pgpass \
  --app-service h35-app \
  --dagster-service h35-dagster \
  --app-db kor_travel_map \
  --dagster-db kor_travel_map_dagster \
  --source-network host \
  --api-container kor-travel-map-api-latest \
  --dagster-web-container kor-travel-map-dagster-latest \
  --dagster-daemon-container kor-travel-map-dagster-daemon-latest
```

## Gate 단계

1. opt-in, root UID, root-owned immutable snapshot, image digest, disk 여유를 검사한다.
2. docker-manager global mutation lock을 잡고 해제 전까지 유지한다.
3. API/Dagster writer container가 stopped 상태인지 확인한다.
4. source app DB에서 active write transaction 수, Alembic head, schema marker, 핵심
   row-count snapshot을 읽는다.
5. source Dagster DB에서 active write transaction 수, schema marker, 핵심 row-count
   snapshot을 읽는다.
6. 같은 lock/window 안에서 app DB와 Dagster DB를 full custom archive로 dump한다.
   dump는 ownership/ACL을 보존한다.
7. 각 dump에 SHA-256을 쓰고 `pg_restore --list`를 남긴다.
8. source writer-quiesced 상태를 다시 확인한다. 값이 바뀌었으면 fail-close한다.
9. disposable PostGIS 16 scratch volume/container/network를 생성한다. network는
   `--internal`, scratch auth는 scratch-only `POSTGRES_HOST_AUTH_METHOD=trust`다.
10. scratch DB 2개를 만들고 `pg_restore --no-owner --no-privileges --exit-on-error`로
    실제 복원한다.
11. scratch의 Alembic head, schema marker, 핵심 row-count snapshot이 source와 같은지
    비교한다.
12. 성공하면 scratch container/network/volume과 source credential copy를 제거하고,
    root-private evidence bundle만 남긴다. 실패하면 `BLOCKED`와 failure journal,
    scratch identity를 남기고 scratch 자원을 임의 정리하지 않는다.

## PostgreSQL dump 비신뢰 코드 경계

`pg_restore`는 archive 안의 SQL을 실행한다. 따라서 source DB가 삽입한 restore-time SQL은
host가 아니라 disposable scratch PostGIS container 안에서만 실행해야 한다. scratch server는
published port, host bind, prod network, prod credential이 없고, 성공 뒤 제거된다. 실패 뒤에는
조사 가능성을 위해 scratch identity만 보존하고 operator가 runbook에 따라 직접 폐기한다.

## Evidence

성공 bundle은 아래 파일만 남긴다.

- `manifest.json`: run id, Git SHA, image refs, local image IDs, source network mode,
  scratch identities, dump filenames, SHA-256, source/scratch snapshot digests
- `app.dump`, `dagster.dump`: custom-format dump
- `app.pg_restore.list`, `dagster.pg_restore.list`
- `app.source.snapshot.json`, `dagster.source.snapshot.json`
- `app.scratch.snapshot.json`, `dagster.scratch.snapshot.json`
- `SUCCESS`

실패 bundle은 `SUCCESS` 대신 아래를 남긴다.

- `BLOCKED`
- `failure-journal.txt`
- `scratch-identity.json`
- cleanup 금지 안내

## 실패 복구

이 gate는 source DB에 쓰지 않는다. 실패해도 원본 prod DB는 불변이어야 한다. `BLOCKED`가
있으면 임의 `docker rm`/`docker volume rm`/evidence 삭제를 하지 말고 다음을 기록한다.

1. `manifest.json`의 run id와 Git SHA
2. `scratch-identity.json`의 container/network/volume 이름과 Docker ID
3. 실패 단계와 stderr 요약
4. source DB의 Alembic head와 writer-quiesced 재확인 결과

operator는 실패 원인을 수정한 뒤 새 run id로 다시 실행한다. 같은 scratch identity를
재사용하지 않는다.
