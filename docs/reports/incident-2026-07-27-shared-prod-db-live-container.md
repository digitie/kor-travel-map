# 인시던트 리포트 — 공유 prod DB 위 lane live 컨테이너 충돌 (2026-07-27)

> 요약: Lane B(codex)가 n150 prod에서 띄운 live 컨테이너가 **공유 production
> pinvi DB의 alembic head를 migration으로 전진**시켜, 배포로 고정(held)된
> compatible-pair의 pinvi 컴포넌트(`e60d1711`)가 기동 불가가 됐다. 이로 인해
> compatible-pair manifest가 "복원 불가능한 stale" 상태에 빠졌고, 이후 map 배포가
> 연쇄 실패했다. 복구 중 raw `docker compose up`이 2차 손상을 유발했다. 재발
> 방지 규율을 `docs/tasks.md` §공통 규율에 고정한다.

## 1. 타임라인

1. Lane A(Claude)가 `T-VN-LIVE-01` targeted live acceptance lane을 n150 prod에서
   반복 실행하며 map/pinvi pair를 여러 커밋으로 재-cut하던 중.
2. Lane B(codex)가 T-VN-08 등 작업을 위해 **`pinvi-api-tvn08-live` 컨테이너**를
   n150에 띄웠다. 이 컨테이너는 **production pinvi DB(`pinvi`@127.0.0.1:5432)를
   그대로 공유**하고, 컨테이너 startup에서 `alembic upgrade head`를 실행해 공유
   DB를 pinvi main 계열의 head(`20260721_0040`)로 **전진**시켰다.
3. 그 결과, 배포로 고정된 pinvi `e60d1711`(migration `~0037/0038`까지)은 자기보다
   앞선 DB revision(`0040`)을 만나 `Can't locate revision identified by
   '20260721_0040'`로 **기동 불가**가 됐다.
4. compatible-pair manifest는 `map=…/pinvi=e60d1711`을 active로 고정하고 있어,
   deploy·rollback 모두 `e60d1711` pinvi를 요구 → **manifest가 trap**에 빠졌다.
5. 복구 시도 중 **raw `docker compose up`**(prod manager 디렉토리)이
   `docker-compose.override.yml`(auto-load)을 함께 로드해 provider 런타임
   키를 map-api에 주입 → map-api 엔트리포인트가 fail-close(재시작 루프). 또한 실패
   deploy의 산출물로 map-api 이미지 태그(`latest-main`)가 `89cc8ba0`으로 바뀌며
   ui/dagster(`1f34586e`)와 리비전이 어긋나 이후 deploy 사전점검이 연쇄 거부했다.

## 2. 근본 원인

- **1차(외부·구조적)**: lane의 n150 live/dev 컨테이너가 **production DB를
  격리 없이 공유**하고, **startup auto-migration**으로 공유 DB head를 전진시킬 수
  있었다. compatible-pair 모델은 "배포된 컴포넌트의 코드가 DB head와 정합"을
  전제하는데, 어느 lane이든 공유 DB head를 앞서 전진시키면 held 컴포넌트가
  기동 불가가 되고 manifest가 복원 불가능해진다.
- **2차(복구 절차)**: prod manager 디렉토리에서 raw `docker compose`를 쓰면
  `docker-compose.override.yml`이 auto-load되어 provider 키가 주입된다. ktdctl은
  이 override 없이(base compose, sanitized) 배포하므로, raw compose는 prod 런타임
  계약을 위반한다.

## 3. 복구 (2026-07-27)

- pinvi를 **main head `6a035695`(#408 포함)로 재빌드**해 DB `0040`과 정합시킴
  (직접 `docker build`; compose build는 캐시로 재빌드 실패해 우회).
- map-api를 **base compose만으로(`-f docker-compose.yml`, override 제외) 재생성**해
  sanitized·healthy 복구.
- deploy 사전점검 3종을 순차 처리: (a) `_inspect_current_pair` 리비전 정합, (b)
  manifest-drift, (c) mandatory map-api health. (a)/(b)는 인시던트로 인한
  self-inflicted drift라 **검증-안전 tolerate로 임시 우회**(c7-blocked-recovery
  §4 선례), (c)는 map-api를 실제로 고쳐 충족. **deploy 성공 직후 ktdctl 패치를
  전량 원복**(가드 재활성).
- 결과: pair를 **`map=b0c95672 / pinvi=6a035695`**로 정식 전진(4 map runtime
  recreated+healthy, pinvi healthy, admin login 200, manifest 갱신).

  > **정정(2026-07-27, T-ADM-C6c/T-VN-03 smoke)**: 이후 배포된 map-api image의 revision label은
  > **`c8ed6164`**(b0c95672의 후손, 차이 docs-only라 route gate 런타임 동일)로 실측됐다. 현 배포
  > 정본은 **`map=c8ed6164 / pinvi=6a035695`**다. 위 b0c95672는 복구 시점 중간 상태로,
  > 후속 docs-backlog 커밋(c8ed6164) 재배포로 대체됐다. 근거:
  > `reports/t-vn-03-c6c-boundary-smoke-2026-07-27.md` §0.

## 4. 재발 방지 규율 (정본: `docs/tasks.md` §공통 규율)

- **R1 — lane live/dev 컨테이너의 prod 격리(필수)**: 어떤 lane이든 n150에서
  띄우는 live/dev 컨테이너는 **production DB·포트와 격리**해야 한다. 전용
  database(또는 schema) 또는 폐기용 복제본을 쓰고, **공유 prod DB에 대한 startup
  auto-migration을 금지**한다. 공유 prod DB의 alembic head 전진은 오직 조율된 배포
  단계에서만 수행한다. (특히 Lane B PinVi 결합 작업.)
- **R2 — prod manager 디렉토리에서 raw `docker compose` 금지**: auto-load되는
  `docker-compose.override.yml`이 provider 키를 주입해 map-api를 fail-close시킨다.
  prod 런타임 변경은 **ktdctl(base compose, sanitized)**로만 한다. 단일 서비스
  재생성이 불가피하면 **`-f docker-compose.yml`(base만)**을 명시해 override를 배제.
- **R3 — compatible-pair 함정 인지**: 공유 DB가 held 컴포넌트 head를 넘어
  migration되면 held 컴포넌트가 기동 불가가 되어 manifest가 trap된다. 복구는
  held 컴포넌트를 runnable revision으로 전진 + 재-cut. deploy 가드(리비전 정합·
  manifest-drift·mandatory-health)는 안전장치이므로 임시 우회 시 **성공 직후 즉시
  원복**한다.
- **R4 — cross-lane 배포 조율**: 두 lane이 같은 prod 페어/공유 DB를 동시에 만질
  때는 재-cut·live 실행 창을 겹치지 않게 하고, 한 lane의 live 컨테이너가 다른
  lane의 배포 대상 DB를 공유하지 않도록 lane 소유자가 사전 확인한다.
