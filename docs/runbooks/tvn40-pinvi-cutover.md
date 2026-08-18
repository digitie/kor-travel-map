# T-VN-40 인수 ② — PinVi cutover 실행 순서 (S3~S6)

Map 인수 ①(prod `0104 → 0223`, mapping 4,424)이 끝난 뒤 남은 ②를 실행하는 유일한 순서다.
**Map 쪽에는 데이터 mutation이 없다** — ②의 전부는 PinVi 쪽이다(`docs/tasks.md` §T-VN-40 인수 실행).

이 문서의 명령은 적대 검증 2명(배포·롤백 렌즈 / 계약·불가역 렌즈)이 n150 실측으로 P1 14건을
잡아낸 뒤의 **수정본**이다. 초안 그대로 실행하면 (a) alembic이 한 줄도 돌지 않고 (b) S4가 404로
끝나며 (c) prod Map API와 공유 RustFS까지 재생성됐다.

## 0. 선행 조건 (전부 만족해야 시작)

> **2026-08-19 갱신 — PR #1000(T-VN-41S)이 순서를 바꾼다.** 그 PR은
> `openapi.service.json`을 바꾸고(`c6f9aba6…` → `8019e36f…`, +298/-4) `consumer-rollout-v1.json`의
> T-VN-40 receipt 해시 2개를 함께 옮기며 T-VN-41 receipt의 `candidate_verified` 블록을 되돌린다.
> 따라서:
> - **pair commit은 #1000 머지 이후여야 한다**(그 전 커밋으로 배포하면 이미지가 receipt와 다른 service
>   계약을 담는다).
> - PinVi는 **service 스냅샷도 재vendor**해야 한다. 그러면 §0-2가 "재핀하지 않는다"고 적은
>   provenance lockstep이 **이번엔 실제로 발동한다** — `contracts/kor-travel-map-service-provenance-v1.json`의
>   `service_openapi_sha256`+`map_release_revision`, `tests/unit/test_kor_travel_map_cache_target_contract.py`
>   상수, `PINVI_KOR_TRAVEL_MAP_CACHE_TARGET_EXPECTED_SOURCE_REVISION` env를 한 커밋에서 옮긴다.
> - **S4는 그 재핀 이후에 한 번만 봉인한다.** 먼저 봉인하면 재핀 뒤 preflight가 새 revision 기준으로
>   `ready=false`가 되어 재봉인이 필요하다(mapping 표는 immutable이라 재봉인 자체는 가능하다).
>
> 결정된 실행 순서: **#1000 머지 → Map prod를 그 head로 재배포 → PinVi service 재vendor + provenance
> 재핀 PR 머지(= PinVi pair commit) → S3 → S4 → S5 → S6 → ④ receipt complete.**


1. **PinVi PR #451 머지 완료.** Map 인수 ④는 `map_user_openapi_sha256 == pinvi_user_vendor_sha256`을
   강제하는데(`tests/unit/test_vnext_contract_artifacts.py`), PinVi `main`의 vendored user spec은
   `66fc83b3…`이고 Map은 `6a2ee0f9…`다. **배포 pair commit은 #451 머지 커밋 이후여야 한다.**
2. **provenance 상수의 의미 — 재핀하지 않는다(2026-08-19 검증 결론).**
   PinVi가 봉인하는 `map_release_revision`은 vendored 상수
   (`contracts/kor-travel-map-service-provenance-v1.json`, `4672aa96…`)다. 처음에는 "실제 서빙 커밋과
   달라 거짓 문장이 봉인된다"고 판단했으나, 계약 렌즈 검증이 이를 뒤집었다:
   - 이 상수는 live `/health` revision이 아니라 **vendored service 계약의 release identity**다
     (`core/config.py:552-564`가 cache-target expected source revision과 대조한다).
   - `4672aa96`의 `openapi.service.json` sha256이 provenance의 `service_openapi_sha256`(`c6f9aba6…`)과
     일치하고, service·user 스펙 바이트는 `4672aa96 → 현재 main` 전 구간 **불변**이다. 따라서
     "service 계약이 `c6f9aba6`인 release에 대해 봉인됐다"는 문장은 참이다.
   - 재핀은 vendoring chore가 아니라 receipt 흐름 결정이다: `UNIQUE(map_release_revision)` 때문에
     이미 봉인된 receipt가 backfill에서 conflict가 되고 새 scope에 **두 번째 receipt**가 생긴다.
     `PINVI_KOR_TRAVEL_MAP_CACHE_TARGET_EXPECTED_SOURCE_REVISION` env와
     `tests/unit/test_kor_travel_map_cache_target_contract.py:25`까지 같은 순간에 옮겨야 한다.
   → **S4는 현재 상수 그대로 봉인한다.** 다만 이 상수의 의미가 어디에도 문서화돼 있지 않으므로
   receipt 발행 시 journal에 "봉인된 `map_release_revision`은 서빙 커밋이 아니라 vendored service 계약
   identity"라고 남긴다.
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
