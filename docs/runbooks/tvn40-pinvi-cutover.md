# T-VN-40 인수 ② — PinVi cutover 실행 순서 (S3~S6)

Map 인수 ①(prod `0104 → 0223`, mapping 4,424)이 끝난 뒤 남은 ②를 실행하는 유일한 순서다.
**Map 쪽에는 데이터 mutation이 없다** — ②의 전부는 PinVi 쪽이다(`docs/tasks.md` §T-VN-40 인수 실행).

이 문서의 명령은 적대 검증 2명(배포·롤백 렌즈 / 계약·불가역 렌즈)이 n150 실측으로 P1 14건을
잡아낸 뒤의 **수정본**이다. 초안 그대로 실행하면 (a) alembic이 한 줄도 돌지 않고 (b) S4가 404로
끝나며 (c) prod Map API와 공유 RustFS까지 재생성됐다.

## 0. 선행 조건 (전부 만족해야 시작)

1. **PinVi PR #451 머지 완료.** Map 인수 ④는 `map_user_openapi_sha256 == pinvi_user_vendor_sha256`을
   강제하는데(`tests/unit/test_vnext_contract_artifacts.py`), PinVi `main`의 vendored user spec은
   `66fc83b3…`이고 Map은 `6a2ee0f9…`다. **배포 pair commit은 #451 머지 커밋 이후여야 한다.**
2. **provenance 재핀 결정.** PinVi가 봉인하는 `map_release_revision`은 요청 결과가 아니라
   vendored 상수(`contracts/kor-travel-map-service-provenance-v1.json`, 현재 `4672aa96…`)다.
   실제로 export를 서빙하는 prod Map은 그 자손 커밋이며, client·route·DB 어디에도 둘을 대조하는
   지점이 없다 — 즉 **사실이 아닌 문장이 append-only로 봉인될 수 있다.**
   → 배포 pair commit에서 provenance를 **실제 배포되는 Map 커밋으로 재핀**한 뒤 S4를 실행한다.
   (대안: 상수가 "벤더된 계약 리비전"임을 receipt·journal에 명시하고 진행. 재봉인은 가능하지만
   거짓 provenance 행이 영구히 남고 preflight가 새 revision 기준으로 `ready=false`가 된다.)
3. Map prod를 pair commit으로 재배포해 둔다(현재 `14ec2368`; #998 hotfix 미반영).
   **Map export root는 재배포로 바뀌지 않는다** — `ops.curation_cutover_identity_mappings`는 0223이
   한 번만 적재하는 immutable 표이고 40C manifest D11이 retain으로 못박았다.
4. ①~④ 동안 dedup merge 금지.

## S3 — PinVi prod 재배포 (prod mutation)

> `ktdctl pinvi-pair rebuild-pinned`는 **세 DB 파기형**이라 쓰지 않는다.
> n150 설치본 `ktdctl`에는 `db-backup` 서브커맨드가 **없다**(그 코드는 Windows 체크아웃에만 있다).

### S3-1 복구점 (백업이 유일한 되돌림 수단이다)

`0055~0059`의 `downgrade()`는 전부 `RuntimeError`를 던진다 — 스키마를 `0049`로 되돌리는 경로는 없다.

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
sudo docker exec pinvi-postgres pg_dump -U pinvi -p 12800 -d pinvi -Fc \
  -f /tmp/pinvi_0049_pre-tvn40-2_$TS.dump
sudo docker cp pinvi-postgres:/tmp/pinvi_0049_pre-tvn40-2_$TS.dump /home/digitie/backups/pinvi/
sudo docker exec pinvi-postgres rm /tmp/pinvi_0049_pre-tvn40-2_$TS.dump
cd /home/digitie/backups/pinvi
sudo sha256sum pinvi_0049_pre-tvn40-2_$TS.dump | sudo tee pinvi_0049_pre-tvn40-2_$TS.dump.sha256
sudo docker exec -i pinvi-postgres pg_restore --list < pinvi_0049_pre-tvn40-2_$TS.dump | head
```

- `~/backups/pinvi`는 `root:root 0755`라 **sudo로 써야 한다**(최상위 `~/backups`는 digitie 소유).
- 기본 포트가 5432가 아니라 **12800**이다. `-U pinvi -d pinvi`를 반드시 준다.
- `.env` 백업: `sudo cp .env .env.bak-tvn40-2-$TS`.

### S3-2 exact-commit source snapshot

`git clone --depth 1`은 **임의 `<sha>`를 체크아웃하지 않는다**(기본 브랜치 tip을 얕게 복제할 뿐).
`.git`을 지운 뒤에는 트리≠커밋을 확인할 방법이 사라지고, Dockerfile은 revision 라벨을 트리와
대조하지 않는다 — 라벨만 정확한 가짜 exact-commit 이미지가 만들어진다(T-VN-34/36에서 실제로 발생).

```bash
SHA=<pinvi pair commit 40hex>
git clone --filter=blob:none --no-checkout https://github.com/digitie/pinvi.git ~/pinvi-src-$SHA
git -C ~/pinvi-src-$SHA fetch --depth 1 origin $SHA
git -C ~/pinvi-src-$SHA checkout --detach $SHA
test "$(git -C ~/pinvi-src-$SHA rev-parse HEAD)" = "$SHA"
rm -rf ~/pinvi-src-$SHA/.git
```

`test`가 통과해야만 `.git`을 지운다.

### S3-3 `.env` 갱신 + 롤백 태그

```bash
cd ~/kor-travel-docker-manager
sudo docker tag a3282c80a6fe pinvi-api:rollback-3b87c19c
sudo sed -i -e "s#^PINVI_REPO_DIR=.*#PINVI_REPO_DIR=/home/digitie/pinvi-src-$SHA#" \
            -e "s#^PINVI_SOURCE_REVISION=.*#PINVI_SOURCE_REVISION=$SHA#" .env
```

`pinvi-api:latest-main`은 mutable 태그라 다음 단계의 build가 현재 prod 이미지를 태그에서 떼어낸다.
현재 `PINVI_SOURCE_REVISION=6325d814…`는 **돌고 있는 이미지(`3b87c19c`)와도 불일치**하는 stale 값이다.

### S3-4 이미지 빌드 — 세 개를 함께

manager의 `_attest_pinned_runtime_candidate_images`는 **pinvi-api·pinvi-web·pinvi-dagster 세 이미지
모두** `org.opencontainers.image.revision == PINVI_SOURCE_REVISION`을 요구한다. api만 빌드하면
revision drift로 이후 manager 경유 검증이 fail-close하고, 남은 sanctioned 복구는 파기형
`rebuild-pinned`뿐이다. web을 안 빌드하면 이번 소비자 UI(cutover 패널 등)도 존재하지 않는다.

```bash
sudo docker compose --env-file .env -f docker-compose.yml -f docker-compose.override.yml \
  build pinvi-api pinvi-web pinvi-dagster
docker image inspect pinvi-api:latest-main \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

라벨이 `$SHA`와 같아야 한다. web은 Next.js 빌드라 시간·디스크가 필요하다(사전에 build cache 확인).

### S3-5 마이그레이션 one-shot (`0049 → 0059`)

`run_pinvi_admin_bootstrap()`은 **credential file을 가장 먼저** 읽고 없으면 `exit 1` 한다 —
`alembic upgrade head`는 그 뒤 줄이라 **호출조차 되지 않는다**. compose 서비스 정의에는 그 env도
mount도 없다(manager가 실행 시점에 주입한다: `compose_service.py:4157-4170`).

credential은 반드시 `.env`의 `KTDM_C6C_PINVI_ADMIN_EMAIL` / `KTDM_C6C_PINVI_ADMIN_PASSWORD`
**그대로** 쓴다. 다른 값을 넣으면 `ensure_bootstrap_admin`이 prod admin 비밀번호를 조용히 회전시키고
모든 admin 세션을 폐기한다(계획에 없는 prod mutation).

파일 요건(`read_bootstrap_admin_credential_file`): 절대경로 · 일반파일 · mode 정확히 `0600` ·
`st_nlink == 1` · 소유자 uid == 컨테이너 euid(0) · 1~4096 바이트 · `{"email","password"}` 두 키만
(extra 금지, password 8~200자).

```bash
sudo install -m 0600 /dev/null /root/pinvi-bootstrap.json
# 값은 화면에 남기지 않는다 — .env에서 직접 읽어 파일로 쓴다
sudo docker compose --env-file .env -f docker-compose.yml -f docker-compose.override.yml \
  --profile bootstrap run --rm --no-deps \
  -v /root/pinvi-bootstrap.json:/run/pinvi/bootstrap-admin.json:ro \
  -e PINVI_BOOTSTRAP_ADMIN_CREDENTIAL_FILE=/run/pinvi/bootstrap-admin.json \
  pinvi-admin-bootstrap
sudo rm -f /root/pinvi-bootstrap.json
```

성공 판정: 출력 JSON `{"action":"unchanged|updated","pinvi_head":"20260814_0059"}`.
DB 확인: `sudo docker exec pinvi-postgres psql -U pinvi -p 12800 -d pinvi -At -c "SELECT version_num FROM app.alembic_version"`.

### S3-6 컨테이너 재생성 — 반드시 `--no-deps`

`pinvi-api`의 `depends_on`은 `pinvi-postgres`·`pinvi-db-init`·`rustfs`·**`kor-travel-map-api`**다.
`--no-deps` 없이 `--force-recreate`하면 **prod Map API와 공유 RustFS, PinVi Postgres까지 재생성**된다.
실측상 config hash가 바뀐 것은 `pinvi-api` 하나뿐이다(새 curation token 2개 때문).

```bash
sudo docker compose --env-file .env -f docker-compose.yml -f docker-compose.override.yml \
  up -d --no-deps --force-recreate --wait --wait-timeout 300 pinvi-api
```

판정 4개: DB head `20260814_0059` · 컨테이너 env의 두 raw token 길이 각 64(0 아님) ·
`curl -s 127.0.0.1:12801/openapi.json | grep -c curation-cutover` ≥ 2 · image revision == `$SHA` + healthy.

**롤백**: 스키마는 forward-only라 되돌리지 않는다(0059 유지). 이미지만
`PINVI_API_IMAGE=pinvi-api:rollback-3b87c19c … up -d --no-deps --force-recreate pinvi-api`.
구 이미지는 0059 위에서도 기동한다(런타임에 head 검증 없음, 0051/0052가 추가한 컬럼은 전부 nullable).
스키마까지 되돌려야 하면 S3-1 덤프 복원뿐이다.

## S4 — mapping receipt 봉인 (prod mutation · 불가역)

**경로에 `/api/v1` prefix가 없다.** prod PinVi OpenAPI의 경로는 `/admin/notice-plans/…` 형태다.
`require_role("admin")`은 권한 실패도 **404**로 반환하므로 경로 오타를 권한 문제로 오진하기 쉽다.
그리고 이 라우트는 **`Idempotency-Key`를 받지 않는다**(그 헤더는 `/backfills` 전용).

1. admin JWT: `POST http://127.0.0.1:12801/auth/login` (`.env`의 `KTDM_C6C_PINVI_ADMIN_EMAIL` /
   `KTDM_C6C_PINVI_ADMIN_PASSWORD`) → 응답의 access token을 `Authorization: Bearer`로 사용한다
   (쿠키는 Secure라 `http://127.0.0.1`로 재전송되지 않는다).
2. 봉인: `POST http://127.0.0.1:12801/admin/notice-plans/curation-cutover/mapping-receipts`
   (헤더 `Authorization: Bearer …`, 선택 `X-Request-Id`).

성공 판정: `201`(신규) 또는 `200`(replay) +
`mapping_root=69eb85ecb178569bc87665ee1100b0a34ade4274512e5492e358c50a19140710` ·
`mapping_root_version=ktm-curation-cutover-mapping-v1` · `mapping_count=4424` +
`SELECT count(*) FROM app.ktm_curation_cutover_mapping_receipt_items` = 4424.

멱등성은 **키가 아니라 내용 기반**이다: 같은 release에 receipt가 있으면 status/root/count와 4,424개
item 튜플을 전량 대조해 동일하면 200 replay, 하나라도 다르면 409. 전 과정이 하나의 SERIALIZABLE
트랜잭션 + advisory lock이라 부분 커밋이 없고, 응답만 유실돼도 재요청이 replay로 수렴한다.

불가역성: receipt/items에 append-only 트리거(DELETE/TRUNCATE `55000`), UPDATE는 pending→completed
한 방향만, `UNIQUE(map_release_revision)`. **잘못 봉인하면 in-place 수정 경로가 없다.**

## S5 — legacy preflight (read-only)

`GET http://127.0.0.1:12801/admin/notice-plans/curation-cutover/legacy-preflight` →
`ready=true`를 기록한다. **`POST …/backfills`는 호출하지 않는다** — PinVi prod의
`curated_trip_plans`/`curated_plan_pois`가 0행이라 전환 대상이 없다(prod no-op).

## S6 — canonical collection 59개 import (prod mutation, 사용자 결정 2026-08-18)

`POST http://127.0.0.1:12801/admin/notice-plans/imports/kor-travel-map-curation-collections`
· body `{"collection_id":"<uuid>","mode":"create"}` · `Idempotency-Key`(UUID) 필수 · 201/200(replay).

- 59개 구성: concierge 채널 26개/1,481 · 재생목록 13개/1,462 · `media-places` 20개/1,481(합계 4,424).
  최대 440 item < 상한 2,000이라 413 없음.
- 응답이 `source_curation_collection_{revision,etag}` · `item_set_hash`(`ktm-db-item-set-v1`) ·
  `copied_poi_count`를 함께 봉인하므로 각 plan이 Map collection의 revision/ETag에 결박된다.
- collection UUID 열거: Map public `GET /v1/curations/collections`.
- 되돌리기: plan soft delete + 백업 복원.
