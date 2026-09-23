# resume.md — 현재 진척도와 다음 한 작업

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

## 2026-09-19 (3) — 산사태 0행의 이유를 확정했다. 다음은 대량 역지오코딩이다

**다음 한 작업: 대량 역지오코딩이 일시적 실패 한 번에 전체를 버리는 것을 고칠 것.**

`src/kortravelmap/providers/mcst.py`의 `file_rows_to_bundles`는 **행마다 순차로**
`await _resolve_address(...)`를 부르고, 그 예외를 잡는 자리가 provider·dagster
어디에도 없다(저장소 전체에 `except GeoRequestError` 0건). prod 실측:

```
feature_place_mcst_culture_job        4회 시도 / 2h54m / FAILURE
  RetryRequestedFromPolicy: Exceeded max_retries of 3
    <- GeoRequestError: kor-travel-geo transport 실패: ReadTimeout
  마지막 시도는 upstream_requests_min=13 — 13개 dataset을 다 받아 놓고 죽었다
feature_route_krforest_mountain_trails_job
  04:04:24 STEP_START 이후 3시간 dagster 이벤트 0건
호스트: 4코어, load average 17
```

**실측한 분모.** geo reverse를 job과 같은 컨테이너·같은 설정으로 쟀다.

| 방식 | 20건 벽시계 | p50 | p95 |
|---|---:|---:|---:|
| 순차 | 2.6s | 86ms | 515ms |
| 동시 4 | 0.8s (3.3배) | 160ms | 212ms |
| 동시 8 | 0.4s (6.5배) | 134ms | 326ms |

동시성을 올려도 **건당 지연이 나빠지지 않는다** — geo가 병목이 아니라 왕복 직렬화가
병목이다. 그리고 p95가 0.5초인데 timeout은 10초다. ReadTimeout은 20배 이상치이므로
**timeout이 빡빡한 것이 아니라 이상치 한 번에 대한 내성이 0인 것**이 문제다.

**그런데 범인은 geo가 아니었다 — 원인을 다시 쟀다.**

처음에 나는 이 실패를 "geo가 느려서 timeout"으로 읽었다. 적대 리뷰가 그 전제를
의심했고(4코어에 load 17인데 geo는 CPU 0.15%로 유휴), 읽기 전용으로 다시 재니
전제가 틀렸다.

```
/proc/pressure/io   full avg300 = 25.5%   ← 전체 시간의 1/4 동안 모든 태스크가 디스크에 막힘
/proc/pressure/cpu  full avg300 =  0.0%   ← CPU는 병목이 아니다
geo 503 / E0500 (5시간)          0건      ← geo는 포화 신호를 낸 적이 없다
D 상태 프로세스                  postgres
04:05:00 최대 동시 run             8건
```

**04:03~04:05에 내가 feature job 7개를 동시에 띄웠고** weather 상시 run까지 8개가
4코어·단일 회전 디스크에서 겹쳤다. `docker/dagster.yaml`의 주석이 이미 그 사실을
적어 두었다 — *"provider job은 IO-bound이고 n150은 단일 회전 디스크를
weather/concierge/geo/airport와 공유한다. 올려도 수집이 빨라지지 않는다."*
그런데 geo를 대량 소비하는 asset에는 **pool이 붙어 있지 않다.** `concurrency.pools`
(`default_limit: 1, granularity: run`)와 `OPINET_API_POOL`·`KREX_NOTICE_SNAPSHOT_POOL`
이라는 선례가 이미 있는데 쓰이지 않았다.

**그래서 순서가 바뀐다.** 동시성을 *올리는* 것(배치 지오코딩)은 이 호스트에서
악화일 수 있다. 먼저 할 것은 ① geo 중량 asset에 pool을 붙여 **동시 실행을 묶고**,
② reverse/region 왕복을 **따로 세는** 계측을 넣어(오늘 그 수가 이 저장소에도 geo
저장소에도 없다) 분모를 만든 뒤, ③ 그 다음에 벽시계 deadline과 typed 분류를
넣는 것이다. 재시도·동시성 수치는 ②의 실측 없이 고르면 안 된다.

한계도 적어 둔다: pool은 `@asset` 데코레이터에 걸리는데 큐 경로는 그 래퍼를
**우회한다**(`feature_update_runner.py:432-433`). 즉 pool은 예약 경로만 묶는다.

**규모(조사로 정정됨).** MCST는 33,000이 아니라 13 slug 합계 **102,121행**이고,
행 수 1위는 **MOIS 980,970행**인데 그쪽은 단일 트랜잭션이라 90만 번째 행의 timeout이
앞서 적재한 전부를 rollback시킨다. dagster resource가 `region_fallback_radius_km=0.1`을
켜 두어 bjd가 안 나오는 좌표는 **행당 왕복 2회**다.

**OpiNet은 "마지막"이 아니라 "차단"이다.** `providers/opinet.py`도 주유소마다
`await reverse_geocoder(coord)`를 부른다 — 지금 쏘면 일일 쿼터를 태우고 같은
timeout으로 죽는다. 이 수정이 배포된 뒤에 쏜다.

**안전하다고 확인한 것.** MCST는 `retire_absent_from_snapshot`을 넘기지 않고 slug
단위로 커밋하므로 재실행이 안전하다(13개 중 2개 = 33,422행 이미 적재). 등산로는
`mountain_trail_segment`가 **0행**이라 은퇴시킬 것이 없어 지금 도는 run을 끝나게
두어도 파괴적이지 않다.

**runtime 상한이 34개 job 중 21개에 없다** — MOIS·MCST·등산로가 전부 거기 속하고
전역 6시간에만 매달린다. 다만 상한을 일괄로 붙이면 안 된다: MOIS는 순차 130ms ×
98만 = 35시간이라 7,200초를 붙이면 정상 run이 죽는다. 배치화 뒤에 측정해서 정할 것.

---

**이번에 닫은 것 (#1253).** `feature.feature_notices` 0행의 원인이 둘이었다.

1. 변환이 상류의 유일한 위치 단서를 버렸다. `ocrnFrcstIssuInsttNm`을 10,562건
   전수로 재 보니 **98.5%가 행정구역**(97%가 `충청남도 당진시` 꼴)인데
   `landslide_forecast_issues_to_bundles`가 빈 `Address()`를 박았다.
2. **데이터셋이 통째로 사라져도 job은 SUCCESS였다.** 10,467건을 받아 전부 버리고
   notice 0건으로 끝났는데 결과는 초록이었다. 적재율 하한을 두 적재 경로 모두에
   걸었다 — 버린 것이 남긴 것보다 많으면 적재하지 않고 죽는다.

**아직 열린 것.** D2 lane BLOCKED(`admin feature live acceptance: direct fixture
seed failed` — acceptance 하네스, prod 아님), 활용신청 4건(ansan / gyeonggi-muslim /
jeju / special-streets — 소유자 조치).

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

## 2026-09-16 (4) — 백업 알림은 보류, 대신 진행 중이던 사고를 고쳤다

**다음 한 작업: `T-VN-H49` 또는 `T-VN-H49-OFFBOX`** — `T-VN-H49-BACKUP-STALENESS`
조문 1(알림 경로)은 **소유자 지시로 보류**한다.

**보류 전에 얻은 것.** `geo_dagster`·`concierge`·`pinvi` 백업이 09-12부터 5일째
`Permission denied`로 실패 중이던 것을 찾아 고쳤다(git이 `scripts/*.sh` 실행 비트를
벗겼고 crontab은 경로를 직접 실행한다). 조문이 열려 있는 동안 같은 형태가 세 DB에서
재발한 것이다.

**원장 정정.** 조문 1의 "(a) api 컨테이너만 마운트한다"는 틀렸다 — api·dagster 둘 다
`backup_root`가 없고, Dagster op config schema엔 키 자체가 없으며, 자동 기록되는 F9
행은 예외 없이 `observed=false`다. 그리고 **없는 디렉터리가 진짜 중단과 같은 신호**가
되는 F9 결함은 알림과 독립이라 따로 고칠 수 있다.

**재개할 때 첫 일은 채널 실배달 육안 확인이다.** 설계는 확정돼 있다(소유권 →
`kor-travel-docker-manager`, 채널 → ntfy). 기대치 모델 초안이 그 저장소에 미커밋으로
있다: `config/backup-policy.yml` · `services/backup_policy.py` ·
`services/backup_watchdog.py`. 소비자가 없어 커밋하지 않았다.

**열린 항목(활성 셋):** `T-VN-H49-BACKUP-STALENESS` 조문 1(**보류**) ·
`T-VN-H49` · `T-VN-H49-OFFBOX`. 보류 셋: `T-VN-41C` · `T-VN-H43` · `T-101`.


## 2026-09-16 (3) — M02·LEDGER-ARCHIVE 완주. 활성 항목이 H49 계열 셋만 남았다

**다음 한 작업: `T-VN-H49-BACKUP-STALENESS` 조문 1** — F9는 판정하지만 **사람에게 닿는
경로가 없다**. Dagster 배치에 `backup_root` 볼륨이 없고 `ops.feature_consistency_reports`를
아무도 폴링하지 않는다. 425건이 조용히 실패한 이유가 검사 부재가 아니라 **보는 사람
부재**였으므로, 검사를 더하는 것으로는 닫히지 않는다.

**`T-VN-M02` 완료.** live301에서 `E2E_MANUAL_CREATE_WRITE=1`로 **2 passed (47.9s)**,
DB 실측으로 `manual_admin` / `e2e-admin` / `ktm_feature_api_runtime` /
`ktm_manual_feature_procedure_owner` / `admin-ui-bff.manual-feature-create.v1` 확인.
**이 spec은 한 번도 실행된 적이 없었다** — 첫 실행이 초록이다.

**원장 기록이 또 낡아 있었다.** "격리 스택이 없다"(2026-09-08)는 틀렸고 pg는 5일째 떠
있었다. 실제로 막던 것은 (1) 체크아웃 이동 시 사라지는 `scripts/*.sh` 실행권한,
(2) **Dagster 메타DB 통째 부재**(롤·DB 생성 + `dagster instance migrate` 필요)였다.
spec 자체는 Dagster를 안 쓰지만 `run-admin-stack.sh`에 건너뛰기 경로가 없다.

**`T-VN-LEDGER-ARCHIVE`도 함께 닫았다.** 조문 2·3은 #1239가 이미 넣은 것이었는데 표기만
열려 있었다. 오늘 원장이 다시 220 KiB를 넘어 그 도구를 **실전에서 썼고**, 닫힌 절 둘을
검산 통과 후 옮기고 넷을 이유와 함께 거절했으며, 삭제 게이트가 아카이브 미커밋 상태를
잡아냈다 — 코드가 있다는 것보다 강한 근거다.

**열린 항목(활성 셋, 전부 H49 계열):** `T-VN-H49-BACKUP-STALENESS` 조문 1 ·
`T-VN-H49` · `T-VN-H49-OFFBOX`.
**보류 셋**(잔여로 세지 않음): `T-VN-41C` · `T-VN-H43` · `T-101`.

**오늘 네 번 낡은 기록에 막혔다** — `T-VN-D2-RESIDUE`(나흘), `T-VN-DAGSTER-STORAGE`
조문 1(배포가 증거를 지움), `T-VN-M02`(여드레), `T-VN-LEDGER-ARCHIVE`(사흘). 넷 다
**일이 남아서가 아니라 기록이 따라가지 않아서** 열려 있었다. `docs/tasks-rule.md` §6이
이 형태를 다루지만 규약만으로는 부족하다 — 조문을 닫는 PR이 그 조문을 실제로 닫는지
보는 장치가 없다.


## 2026-09-16 (2) — seal ACL 닫힘, 그리고 prod는 배포마다 새로 태어난다

**다음 한 작업: `T-VN-M02`** — 소유자 판단이 먼저 필요하다. 격리 스택을 다시 세울
것인지, purge를 HTTP로 노출할 것인지. 후자는 원장 기준 **순서 역전**이다(복원 증명은
`T-VN-H49`가 소유한다).

**`T-VN-CURATION-SEAL-ACL` 완료.** 세 조문 전부 실측으로 닫았다 — prod run `0f70d0d5`
`SUCCESS`(`features 1047 · seal 영수증 1건`), 배포 재적용 뒤에도
`dagster_seal=true / api_seal=false`, 실 login으로 적재 경로를 태우는 회귀 추가(변이
빨강 확인). 같은 실행으로 `T-VN-DAGSTER-STORAGE` 조문 1도 현 세대에서 다시 섰다.

**알아 둘 것 — prod DB는 배포가 새로 만든다.** `kor_travel_map` 생성 시각 =
t44a 배포 시각. 그래서 "prod에서 …가 완주한다" 형태의 조문은 다음 배포에서 `[x]`만
남고 근거가 사라진다. 규약은 `docs/tasks-rule.md` §6. 전수 확인상 실제로 그 자리였던
것은 `T-VN-DAGSTER-STORAGE` 조문 1 하나다.

**n150 네 세션 게이트에 mypy가 없다.** `sample_ids=()` 한 줄이 게이트 전부를 초록으로
지나 CI lint에서만 빨개졌다. PR 전에 mypy 3종 + lint-imports를 따로 돌린다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-M02`, `T-VN-H49`/`-OFFBOX`, `T-VN-H49-BACKUP-STALENESS` 조문 1.


## 2026-09-16 — 일일 예산은 만들지 않는다 (분자를 재서 나온 결론)

**다음 한 작업: `T-VN-LEDGER-ARCHIVE` 조문 2·3** — 원장 분리가 fence parity를
검산하게 하고, 아카이브를 삭제 감시 대상에 넣는 일. 조문 1(220KB 아래)은 닫혔다.

**쿼터 축이 전부 닫혔다.** `T-VN-QUEUE-QUOTA`(6/6)와 `T-VN-KREX-TPS-FANOUT`(4/4)
둘 다 완료로 이관했다. 조문 3의 답은 **"집행하지 않는다"**였다 —
`ops.provider_refresh_policies`가 prod에서 **0행**이고(seed도 0) 행이 없으면
`_skip_reason()`이 fail-**open**한다. gate가 그 테이블을 읽게 만들면 읽을 값이 없어
통과시켜 **코드 상수보다 나빠진다.** **분모가 아니라 분자를 재서** 판단했다 —
전국표준데이터는 하루를 넘기려면 총건수 166,000이 필요한데 실측 최대가 **18,883**
(`parking`)이다. visitkorea 5%, 산림청 0.6~6%, `krairport` **0건**(번들 데이터).
가장 좁은 `opinet`(300/일)은 이미 run당 예산이 있다. (`special_street`가 prod 키로
403인 것은 관측했으나 **평가 대상에서 제외**한다 — 2026-09-16 지시.)

**장치 대신 구멍 셋을 닫았다:** khoa 페이지 절대 상한 + stall 지문(선언 총건수 하나가
틀리면 하루치를 넘길 수 있었다), `opinet_run_call_budget`의 `le` 300→150(2 run × 300
= 600이 **설정 가능**했다).

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3, `T-VN-LEDGER-ARCHIVE` 조문 2·3,
`T-VN-M02`, `T-VN-H49`/`-OFFBOX`, `T-VN-D2-RESIDUE`, `T-VN-CURATION-SEAL-ACL`.


## 2026-09-15 — t44a 배포 완료, async 이관이 prod에서 돈다

**다음 한 작업: `T-VN-QUEUE-QUOTA` 조문 6 — 분모가 *있는* provider에 일일 예산을
둘지 판단.** krex는 TPS로 닫혔고(`T-VN-KREX-TPS-FANOUT` 조문 1·2·4), 남은 것은
분모가 있는 쪽이다.

`#1235`(provider 13개 async-only) 머지 후 t44a 재핀 전 사이클 GREEN — D1 live
Playwright 11 passed, D2 `phase=passed`. **prod에서 직접 읽어** 새 라이브러리(동기
`close` 없음, 전부 coroutine)와 gate(`{'krex': 0.2}`, 4건 선언, 계수기보다 바깥)가
살아 있는 것을 확인했다. **버전 문자열로는 판별되지 않아**(13개 전부 `0.1.0`) 코드의
성질을 물었다.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3(정책 테이블 `max_concurrent` 집행),
`T-VN-QUEUE-QUOTA` 조문 6, `T-VN-LEDGER-ARCHIVE` 조문 2·3, `T-VN-M02`,
`T-VN-H49`/`-OFFBOX`, `T-VN-D2-RESIDUE`, `T-VN-CURATION-SEAL-ACL`.


## 2026-09-15 — provider 13개 async-only 이관 (브랜치 `feat/provider-async-tps-migration`)

**다음 한 작업: n150 4세션 게이트 결과 확인 → PR → 머지.** 그 뒤 prod 재핀
(`/root/chain17.sh`)이 따라온다 — provider 핀이 13개 바뀌었으므로 이미지 재빌드가 필요하다.

형제 `python-*-api` **13개 전부**가 native async only + 공유 TPS 제어로 재작성됐다
(사용자 개편). Map을 그 표면에 맞췄다 — 핀 13개, fetcher 20개 async 전환, 경계 4곳,
manifest 재생성, 계약표 13행.

**어제의 krex TPS 브랜치(`python-krex-api` `feat/http-tps-limit`)는 흡수됐다.** 새
라이브러리가 그 기본값과 검증을 그대로 갖고 있다(실측 확인). 머지하지 않고 접는다.
**Map 쪽 `provider_rate_gate`는 살아남는다** — 새 `rate_limiter=` 주입은 한 이벤트
루프 안에서만 성립하고 Map의 fan-out은 프로세스를 가로지른다.

검증(기준선 비교):

| | 브랜치 | HEAD 기준선 |
|---|---:|---:|
| dagster 세션 | 680 passed / **10 failed** | 675 passed / **같은 10 failed** |
| 실패 집합 | — | **IDENTICAL(회귀 없음)** |

남은 10건은 dagster 버전 환경 문제(`test_storage_migration_command` 9 +
`test_definitions` 1). tests/lint 288 passed(conformance 38 포함), ruff 전 트리 clean.

**열려 있는 것:** `T-VN-KREX-TPS-FANOUT` 조문 3·4(정책 테이블 집행 여부, prod 실측),
`T-VN-QUEUE-QUOTA` 조문 6(분모가 있는 provider의 일일 예산),
`T-VN-LEDGER-ARCHIVE` 조문 2·3.


## 2026-09-14 — 분모가 없는 provider를 분모 없이 막았다 (krex TPS 5)

**다음 한 작업: `T-VN-QUEUE-QUOTA` 조문 6 — 분모가 **있는** provider에 일일 예산을
둘지 판단.** 조문 5(`krex`)는 닫혔다.

**`krex`는 일일 한도를 기다리지 않고 축을 바꿨다.** 포털 네 면 어디에도 일일 수치가
없고 남은 길은 문의뿐이었는데, **이 provider에서 실제로 조일 수 있는 것은 간격이다.**
`python-krex-api` `feat/http-tps-limit`이 `KrexHttp`에 token bucket을 넣어 **초당
5건**을 넘기지 않는다(`max_rps` 기본 `5.0`, `KrexClient`/`AsyncKrexClient`로 전달).

세 가지를 일부러 다르게 했고 각각이 그냥 두면 틀렸을 자리다:

- **버스트 없음(capacity=1)** — capacity가 `max_rps`면 가득 찬 버킷에서 5건이 즉시
  나가고 그 초에 지속분이 더해져 **첫 1초에 10건**이다. 상한이지 평균이 아니다.
- **재시도도 요청이다** — 버킷이 재시도 루프 **안**에 있다.
- **락이 `threading.Lock`이다** — `_run_sync`가 호출마다 새 루프를 만들고 러닝 루프가
  있으면 별도 스레드에서 돈다. `asyncio.Lock`은 스레드를 전혀 막지 못하면서 막는 것처럼
  읽히고, 경합하면 처음 본 루프에 묶여 다음 루프에서 `RuntimeError`를 낸다(3.14 재현).

검사기는 일곱 변이로 확인했다(상한 끄기 / capacity 되살리기 / 기본값 / acquire를 루프
밖으로 / client 미전달 / go 포털만 우회 / 우회하는 새 전송 자리) — 각각 다른 테스트가
잡는다. 마지막 것은 AST로 `session.get(...)` 자리가 하나임을 본다. **효과 검사는 지금
있는 경로만 보므로 새 경로는 아무 테스트도 건드리지 않고 상한을 비켜 간다.**

**그리고 Map 쪽에서 내가 틀렸다.** "큐 러너가 순차 처리하므로 합계 5 TPS"라고
적었는데, 적대 리뷰 둘이 **독립적으로** 뒤집었다 — 그 순차성은 run **하나 안에서**의
이야기다. 큐 센서는 틱당 RunRequest를 10개 내고(`RUNNING`, 15초 틱),
`docker/dagster.yaml`이 `tag_concurrency_limits`로 **4를 동시에** 돌린다. run마다
프로세스가 다르니 `KrexClient`도 버킷도 넷 → **최대 20 TPS.** krex를 직렬화하는 것은
아무것도 없다(scope advisory lock은 키가 다르고, Dagster pool은 asset에만 있는데 큐
경로가 asset을 우회하며, `provider_refresh_policies.max_concurrent`는 **읽히기만 하고
집행되지 않는다**).

**닫혔다고 적은 구멍이 현재 설정으로 열려 있었다.** 지금 보증되는 것은 "프로세스당
5 TPS"이고 합계가 아니다. 남은 작업을 `T-VN-KREX-TPS-FANOUT`으로 뺐다 — 고칠 자리는
`max_rps`가 아니라 **provider 단위 동시성 집행**이고, 스키마
(`ops.provider_refresh_policies.max_concurrent`)는 이미 있다.

**아직 Map에 반영되지 않았다** — `pyproject.toml`의 krex 핀이
`c6d8717ec2b712cc952bc566b351f07a7cd3824a`다. krex PR 머지 후 repin이 따라온다.

t43a 배포 완료(`e3fddce81`, 전 사이클 GREEN — D1 live Playwright 11 passed,
D2 phase=passed). prod 실측으로 OpiNet 예산 140/90과 큐 skip 6건이 살아 있는 것을
확인했다.

분모 조회는 끝났다 —
`opinet` **300/일**(저장소가 1,500으로 알고 있었다), `krheritage`·`mois`는 **키가
없어 한도 자체가 없고**(mois는 data.go.kr 파일데이터가 기관 자체 다운로드 URL을
가리킨다 — 이관됐지만 파일 경로는 그대로다), `krex`만 **미공개**라 문의가 남았다.
2026-09-14에 넷을 다 봤고 결과가 갈렸다: **opinet 300/일**(저장소가 1,500으로 알고
예산 600을 세웠다 — 켜면 첫날에 막혔을 값, 140/300/90으로 고침), **krheritage는
인증키가 없어 한도 자체가 없다**(위험은 쿼터가 아니라 차단), **mois도 키가 없다**
(data.go.kr 파일데이터가 기관 자체 다운로드 URL을 가리킨다 — "사이트 무응답으로 확인
실패"라고 적었던 것은 같은 날 뒤집혔다: 죽은 것은 사람용 포털이고 파일 호스트는
살아 있었으며, 깨진 것은 Referer 없는 내 curl이었다), **krex는 일일 한도 미공개라
TPS 5로 막았다**(위 참고).

**급하지 않다.** 2026-09-14 prod 실측 feature asset materialization **0건**이고
feature cron schedule은 전부 꺼져 있다 — 쿼터가 압박받는 상황이 아니다. 큐 예산
장치는 분모를 보고 나서 필요한지 판단한다("측정 전에 상한 숫자를 바꾸지 않는다").
KMA·에어코리아는 평가 대상에서 제외(2026-09-14 지시).

`T-VN-QUOTA-ARITHMETIC`은 여섯 조문 전부 `[x]`로 닫혔다. 분모 실측(오퍼레이션마다
따로 걸린다) · 분자(`upstream_requests_min`, #1229) · 쿼터성 실패의 재시도 차단
(#1227) · 증폭기 선언 · UI 보증 제거 · KMA 재활성화 전제. prod 배포 t41a·t42a 두
사이클 GREEN.

**조사 중에 blocker 하나를 찾아 고쳤다.** `DISABLED_FEATURE_LOAD_SCHEDULES`
(2026-09-09 사용자 지시로 KMA·AirKorea 자동 적재 중지)는 **시계만** 껐다. prod는
cron이 아니라 feature update queue로 도는데(schedule 전부 STOPPED, 큐 센서만
RUNNING) 큐 runner에 꺼진 operation의 spec이 그대로 있었고 정책 게이트는 row가
없으면 fail-open이다 — 즉 **사용자가 끈 provider가 살아 있는 경로로 나가고 있었다.**
지금은 큐 경계가 `DISABLED_FEATURE_LOAD_OPERATION_KEYS`를 읽어 건너뛴다.


## 2026-09-11 — T-VN-39 재키가 착지했다 (#1197, `e8c66c47`)

`feature.features.feature_id`가 uuid다. 서버가 적재 시점에 발급하는 UUIDv7이고 어떤
입력에서도 유도되지 않는다. 예전의 `f_*` 주소는 `feature.feature_aliases.alias`의
**주소 등록부**로 옮겨 갔고, 그 주소로 들어와도 같은 Feature가 나온다(ADR-098).
**바깥 이름은 하나도 바뀌지 않았다** — 바뀐 것은 값의 출처뿐이다.

같은 날 보안 PR #1198(maplibre-gl 6 · Next 16.3.4 · sharp 0.35.4)이 먼저 들어갔고,
재키 PR이 그 위에 얹혔다.

### 착지 시점 게이트

| 층 | 결과 |
|---|---|
| GitHub CI 9종 | 전량 초록 |
| n150 — provider **실제 설치** | dagster 575 · api 1,223 · lint+unit 2,832(환경 실패 14) |
| 제품 SQL 786문 head Parse | 초록 (587 → 786) |
| live — 필터 3갈래 | 200 / 200(빈 목록) / **422** |
| live — DB→API→실제 브라우저 | 통과 |

### 이 작업이 남긴 규칙 다섯

1. **검사가 초록인 것과 결함이 없는 것은 다른 사실이다.** 가르는 방법은 검사에
   결함을 일부러 넣어 보는 것뿐이다 — 그렇게 해서 FK 검사가 **항진명제**였음을
   찾았다(정본을 마이그레이션과 함께 움직이는 덤프에서 읽고 있었다).
2. **하한은 "판단 대상 수"가 아니라 "대상을 실제로 몇 개 보았는가"에 건다.**
   앞의 것은 결함이 고쳐지는 순간 0이 되어 빨개진다.
3. **개수 세기는 전칭 명제가 아니다.** 표면을 열거해야 "변환 안 된 자리"가 보인다 —
   uuid 필터 하나가 그래서 500인 채로 남아 있었다.
4. **쪼개서 빠르게 도는 하네스는 그 자체가 프록시다.** 통합을 9묶음으로 나눠 돌면
   세션 공유 DB에 쌓이는 상태가 보이지 않는다. 머지 전에 한 번은 CI와 같은 방식으로.
5. **결함을 만든 자리와 그것을 가린 자리는 따로 있을 수 있다.** API 패키지의
   autouse echo-resolve가 uuid 해석 축을 구조적으로 관측 불가로 만들고 있었다.

### 열린 후속 둘

- **API 패키지 conftest의 echo-resolve가 재키 이전 세계를 모사한다**
  (`feature_id=ref`). 그 patch가 깔린 채로는 "legacy 주소가 uuid로 바뀌는가"와
  "없는 참조가 422인가"를 관측할 수 없다. 지금은 그 축을 재는 테스트가 자기
  resolver를 설치해 우회한다. echo 자체를 재키 뒤 모양으로 바꾸는 것은 이 패키지
  테스트 47곳이 참조 문자열을 그대로 기대해 별도 작업이다.
- **datagokr/krheritage upstream의 페이지네이션 퇴화.** Map은 위임을 끊어 스스로를
  지켰지만(`total` 권위 페이지네이터), 근본 수정은 provider 쪽이다. 다른 소비자는
  여전히 노출돼 있다.

### 다음 한 작업

**prod Map 배포.** Map revision이 바뀌었으므로 D2 재핀 사이클 전체가 따라온다
(rotate → rebuild → 이미지 → repin → preflight → D1 → D2). `docs/` 안의 prod 배포
절차와 PinVi token pair 규약을 따른다.

그 뒤 **T-VN-34C paired fresh-live 레인**은 여전히 별도다 —
`consumer-rollout-v1.json`의 T-VN-40 paired consumer receipt가 `pending`이고, 그
blocking_reason 자체가 "Map Admin provenance가 opaque feature_id + required
feature_uuid로 바뀌었으니 full-admin artifact를 다시 vendoring하고 PinVi M05
attestation을 붙여 paired acceptance를 다시 돌려라"다.

## 2026-09-08 (3) — 원장이 밀려 있던 둘을 정리하고 계약 하나를 개정했다

두 PR이 머지됐다 — Map #1194(9개 체크 전부 통과), Manager #335.

| 항목 | 상태 |
|---|---|
| `T-VN-M05-VERIFY-RECEIPT` | **완료** — V1~V4 전부. 원장만 밀려 있었다 |
| `T-VN-M02` | 잔여 셋 중 **둘이 이미 해소**됐는데 문장이 안 따라갔다 |
| `T-VN-39` 소유자 판정 | **없어졌다** — 계약 개정으로 |
| 열린 항목 | 8 → **6**(보류 셋 포함) |

**`T-VN-M02`의 잔여는 하나뿐이다.** purge 정책은 306이 닫았고, backup/restore 축은
2026-09-07 판정으로 `T-VN-H49`가 가져갔으며, live acceptance **spec 회수도 끝났다**
(main에 있다). 남은 것은 **실행**이고 그것이 막힌 이유는 셋인데 그중 하나는 306이 절반
풀었다 — "지워지지 않는 write"는 hard-purge fence가 유일한 삭제 경로를 거부해서 생긴
것이었고 이제 감사되는 purge 명령이 있다. 남은 것은 prod UI의 actor 불일치와, 무엇보다
**격리 스택 재구축**이다(`~/ktm-live-301`은 정지가 아니라 사라졌고 302 head다).

**`notice_states` 계약 개정(소유자 승인).** removal manifest에서 (c)를 뺐다 — 대체를
정당화한 "문자열 시각 판정"이 `T-VN-35B`/`T-VN-37D`로 이미 없어졌고, 그 항목의
`fenced_by`(`T-VN-37B`)는 **원장에 존재한 적이 없는 유일한 entry**였다. 목표 상태 DDL은
"채택되지 않음" 표시만 달고 남긴다 — 지우면 같은 논의를 다시 해야 한다.

### 착수 가능 — 소유자 판정 없이

1. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 이제 판정 대기가 없다. 컬럼 37 · FK 34 ·
   인덱스 57의 rekey 공학이고, `feature.features`가 0행이라 데이터 이행 위험이 없다.
2. **`T-VN-M02` live acceptance** — `~/ktm-live-301` 재구축이 선행이다.
3. **`T-VN-H49` 잔여** — `geo` 예약 성공 누적과 문서 갱신.

### 소유자 판정 대기 — 둘

1. `T-VN-H49` **manual Feature hard purge**는 닫혔다. 남은 것은 off-box 목적지 —
   호스트·계정·**root가 쓸 수 있는** ssh 키. 코드는 이미 있다.
2. 없음(`notice_states`가 해소되어 하나로 줄었다).

### 미조치 리뷰 findings

적대 리뷰 23건 중 7건을 고쳤다. 남긴 P2 셋은 동작 결함이 아니라 설계 여백이다 —
second-level cascade가 복구점 밖, `count_rows_dynamic`의 `search_path` 폭, DELETE fence는
여전히 origin.

**오늘 배운 것.** 리뷰 셋이 각각 같은 맹점을 찔렀다 — 변이 축이 "코드를 **지우면**
빨개지나"만 묻고 "이 술어가 덮는 **범위**가 맞나"를 묻지 않았다. 그리고 공유 session DB의
**전역 집계 단언을 여섯 번** 고쳤다(전부 "무엇이 일어났나"가 아니라 "DB가 비어 있나"를
재고 있었다).


## 2026-09-08 (2) — purge를 열고, TRUNCATE fence와 소비 기록을 닫았다

| 항목 | 상태 |
|---|---|
| `T-VN-H49` hard purge 정책 | **완료** — migration 306, 소유자 승인 |
| `T-VN-M02-TRUNCATE-FENCE` | **완료** — migration 307, `ENABLE ALWAYS` |
| `T-VN-M05-ONESHOT-CONSUME` | **완료** — Manager #335 |
| `T-VN-M05-VERIFY-RECEIPT` | V1·V2·V4 완료, **V3만 남음**(소유자 판정 포함) |
| 열린 항목 | 8 → **5**(보류 셋 포함) |

**purge가 자기 복구점을 들고 다닌다.** 소유자가 건 "restore proof 먼저" 전제는 문자
그대로는 아직 안 맞는다(복원 메커니즘은 증명됐지만 복구점이 없다). 지우기 전에 cascade로
사라질 행을 전부 담게 해서 그 전제를 우회했고, 그 우회를 소유자가 승인했다.

**TRUNCATE fence는 `ENABLE ALWAYS`다.** origin이면 `replica` 한 줄로 사라지고, 그 한 줄은
이 표를 TRUNCATE할 수 있는 유일한 행위자가 언제든 쓴다 — 정직한 위협 모델은 적대자가
아니라 실수다.

### 적대 리뷰 둘이 내 변이 검증의 구멍을 잡았다

Manager 리뷰(14건 → 2 확정)의 P1이 결정적이었다 — 소비 검사의 phase 필터를 **약화**하는
변이가 초록이었다. **내 변이 축은 "지우기"만 재고 "약화"를 재지 않았다.** 그 부류를
전부 다시 봐야 한다. Map 306/307 리뷰는 이 글 쓰는 시점에 진행 중이다.

### 착수 가능 — 소유자 판정 없이

1. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 가장 큰 축이고 소유자 판정 대상이 아니다.
   대체 identity와 fence가 이미 prod에 있고 `feature.features`가 0행이라 데이터 이행
   위험이 없다. 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다.
2. **`T-VN-M02` live acceptance** — `~/ktm-live-301`을 **재구축**해야 한다(정지가 아니라
   사라졌고, 체크아웃은 302 head이며 spec 자체가 없다). purge가 열려 cleanup 이야기는
   풀렸다.
3. **`T-VN-H49` 잔여** — `geo` 예약 성공 2건 더 쌓이기를 기다리는 것과 문서 갱신.

### 소유자 판정 대기 — 셋

1. `T-VN-M05-VERIFY-RECEIPT` **V3** — receipt 인용이 승격 정의의 "출력을 이 절에
   기록한다"와 충돌한다. 그 문장의 개정이 함께 가야 한다.
2. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·**root가 쓸 수 있는** ssh 키.
3. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가.


## 2026-09-08 — T-VN-M05 완주. 열린 항목은 여섯이고 소유자 판정은 셋이다

| 항목 | 상태 |
|---|---|
| `T-VN-M05` | **완료** — 조문 M05-1~M05-7 전부 충족 |
| M05-2 | evidence export(A)·오프라인 검증(B)·리허설 소유권 증명(C)·**복원본 수리(D)** |
| M05-5 | 전용 admin 라우트 `src/app/admin/manual-provider-dedup/` |
| 실측 | n150 M05 통합 42건, 세 배치 순서 36건, 변이 14축 전부 RED |
| restore 정책 | **변함없이 닫혀 있다**(2026-08-26 소유자 결정) |

M05-2를 닫으면서 판정을 한 번 되돌렸다. "lease를 evidence root에 담지 않으니 fencing
token이 되살아날 자리가 없다"는 **번들에 대해서만** 참이었다 — `pg_dump`는 스키마 전체를
담으므로 복원본에는 lease 행이 dump 시점 `(worker_id, lease_epoch)`를 달고 살아 돌아오고,
복원본은 사본이라 그 토큰이 양쪽에서 동시에 유효하다.

### 착수 가능 — 소유자 판정 없이 지금 할 수 있는 것

1. **`T-VN-M05-VERIFY-RECEIPT`** — V1·V2·V3 미충족. `verify_leaf`는 정말 아무것도 쓰지
   않는다(`m05_isolated_e2e.py:2388-2405`). 다만 **V2가 요구하는 값은 전부 이미 지역변수로
   살아 있다**(pinset·Map/PinVi revision·binding의 Manager revision·claim). 두 갈래 함정:
   신뢰 경계 거부 경로(`:2445`/`:2448`)는 axis를 하나도 안 남기고 `return 1`하므로 "실패도
   남긴다"가 가장 필요한 곳이 비어 있고, V3는 조문 `:1386-1388`이 "출력을 이 절에
   기록한다"고 **명령**하고 있어 조문 정정이 함께 간다.
2. **`T-VN-M05-ONESHOT-CONSUME`** — 성공 분기가 아무것도 안 남긴다. **소비를 scoped
   `phase`로 기록하면 L8 호환이 공짜로 풀린다**(L8은 `entry.phase is None`만 본다).
   **`result.json`에 키를 추가하면 안 된다** — 런처가 정확한 키 집합을 강제해
   (`run-m05-isolated-e2e-once:505-519`) 불일치가 성공한 실행을 무조건 소각한다.
3. **`T-VN-M02-TRUNCATE-FENCE`** — 원장 서술 둘이 틀렸다(아래 §정정). 트리거를 더하는
   비용은 통합 테스트 **0곳**이다.
4. **`T-VN-39`의 TEXT `feature_id` PK 제거** — 소유자 판정 대상이 아니다. 대체 identity
   (`feature_uuid` + unique 둘)와 fence 트리거가 이미 prod에 있고 `feature.features`는 0행이라
   데이터 이행 위험이 없다. 남은 것은 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다.
5. **`T-VN-H49` 잔여** — `geo` 예약 성공 2건 더 쌓이기를 기다리는 것과 문서 갱신뿐이다.

### 소유자 판정 대기 — 둘

~~`T-VN-H49` manual Feature hard purge 정책~~ — **2026-09-08 판정·구현 완료**(migration
306). 감사되는 운영 명령으로 열되 UI 버튼이 아니고, purge가 자기 복구점을 담아 H43
보류에 묶이지 않게 했다. claim의 두 역할을 갈라 tombstone을 관리 가능하게 했고 ADR-093에
개정 한 문장을 박았다. 상세는 `docs/tasks-acceptance.md` §T-VN-H49.

1. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·**root가 쓸 수 있는** ssh 키. 코드는 이미 있다
   (`offbox_backup_sync.py`, CLI, 상태 API). `/opt` `.env`에 `KTDM_OFFBOX*` 0개.
2. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가. 새 선행 항목을 세울
   것인가, 아니면 removal manifest에서 (c)를 뺄 것인가(frozen 계약 개정).

**보류/제외 셋**: `T-VN-41C`·`T-VN-H43`·`T-101` — 셋 다 재개 조건이 아직 발화하지 않았다
(41C·H43은 실 production 전환, T-101은 SLO 정의와 ADR-073 의미 택일).
**외부 추적**: `GM-17`(가장 마지막).

### 정정 — 이전 실측 둘이 틀렸다

- **"n150에 예약 백업이 아예 없다"는 틀렸다.** `digitie` crontab에 `geo_dagster`·
  `concierge`·`pinvi` 셋이 매일 돌고 2026-08-21부터 **18일 연속 성공**했다. root로 실행한
  조회가 `/root/backups`를 봤고 cron은 `KTDM_BACKUP_ROOT=/home/digitie/backups`를 쓴다 —
  **다른 디렉터리를 보고 "없다"고 적었다.** `map_application`이 어느 cron에도 없는 것은
  `T-VN-H43`의 의도된 보류다.
- **"TRUNCATE CASCADE가 hard-purge fence를 통째로 우회한다"도 틀렸다.** CASCADE 폐포 30개
  중 10개에 BEFORE TRUNCATE 가드가 켜져 있어 실제로는 중단된다. fence가 그 거부에 기여하지
  않고 진단이 엉뚱한 이유를 대는 것이 진짜 결함이다. "통합 테스트 24곳"도 **14곳**이고,
  `_db_cleanup.py:49`가 이미 `session_replication_role = replica`로 돌아 트리거를 더해도
  **0곳이 깨진다**. 원장이 놓친 더 큰 구멍은 `ops.feature_requests`로, TRUNCATE 가드도
  append-only 가드도 없다.
- **`~/ktm-live-301`은 "정지"가 아니라 사라졌다** — 컨테이너도 볼륨도 없고, 그 체크아웃은
  302 head이며 해당 spec 자체가 없다. `T-VN-M02` live acceptance는 재기동이 아니라 재구축이
  선행이다.


## 2026-09-06 — D2 lane이 api-audit까지 완주했다

| 항목 | 상태 |
|---|---|
| pinset | Map `631f1abc` + PinVi `b9637375` |
| `T-VN-D2-API-AUDIT` | **완료** — `ktdm-d2-008` `phase: passed`, runner exit 0 |
| lifecycle | 56 = 7 operation × 8 phase (`helper-api-audit` 8개) |
| evidence | `phase: evidence-validated`, 파일 집합 exact, FK 제약 18, 리포트 2 |
| api-audit | counts 3·1·7·3, FK 18/8, `feature_ids`·`feature_uuids` 각 1건 |
| 선행 축 | ACL preflight 55/55, D1 11 passed |

`feature_id` 규칙은 서로 다른 실행이 만든 Feature **셋**으로 배포 DB에서 확인했다 —
새 규칙(uuid 재현) 3/3 일치, 구 규칙(run_id 재계산) 3/3 불일치.

### 다음 한 작업

**2026-09-07 소유자 판정 4건이 들어왔다.** 열린 항목은 15 → **11**이 됐다(보류/제외 3 포함).

| 판정 | 결과 |
|---|---|
| 승격 정의 변경 | `T-VN-M05-ACTIVATION` — 문서 행위가 아니라 **재계산 가능한 대조**로 정의. Manager `--verify-leaf`가 해시 사슬과 살아 있는 pin registry를 대조한다. 서명은 근거에서 뺐다(키가 실행마다 새로 생겨 사후 검증 불가) |
| 과대 계상 삭제 | `T-VN-M02`에서 backup/restore 축 제거 — 소유는 `T-VN-H49` 계열 |
| H34는 CSV만 | `T-VN-H34` **완료**. 범위 밖 넷은 지우지 않고 acceptance에 남겼다 |
| D1이 자격증명을 갚음 | `T-FE-MOCK-FLAKE` **완료** |

**착수 가능 — 순서대로.**

1. `T-VN-M02` **spec 회수** — 미병합 브랜치 유실 위험. 판정과 무관하게 먼저.
2. `T-VN-H49` 자식 셋 복원 리허설 — Manager `rehearse-restore` 결함을 고쳐 배포한 뒤
   실행한다(`geo_dagster`·`concierge`는 백업 0건이라 `create` 선행).
3. `T-VN-M04` — 조문을 세웠고 reject 통합 테스트를 더했다. CI green이면 닫힌다.

**소유자 판정 대기 — 여섯.**

1. `T-VN-M05-ACTIVATION` A2 — "실행은 단 한 번"의 기준(기계는 execution identity당 1회를
   강제한다. 한 pinset 아래 leaf가 셋 생겼다).
2. `T-VN-M02` purge 정책 — evidence cascade/orphan·권한·409 계약.
3. `T-VN-H49` 자식 셋의 리허설 **기록 위치**.
4. `T-VN-H49` 부모 — 고착 `load_jobs` 해소를 위한 prod 쓰기 승인.
5. `T-VN-H49-OFFBOX` — 목적지 호스트·계정·ssh 키. **그리고 n150에 예약 백업이 아예 없다**
   (root crontab 없음·timer 없음·logrotate 미설치, geo·geo_dagster·concierge 백업 0건).
6. `T-VN-39` — `provider_sync.notice_states`를 어디가 소유할 것인가. 가장 큰 축이다.

**보류/제외 셋**: `T-VN-41C`·`T-VN-H43`·`T-101`. **외부 추적**: `GM-17`(가장 마지막).

## 2026-09-06 — D2 통과, receipt 승격

| 항목 | 상태 |
|---|---|
| `T-VN-M01` 활성화 | **완료** — ACL 55/55(rebuild 앞뒤 두 번) · 거부 축 4/4 403 · witness 8관계 zero-write · 성공 축 201 |
| kill-switch | `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true` (2026-09-05T20:27:59Z) |
| D2 스펙 | **in-lane 통과** — main·recovery 각 `{"counts":{"passed":2},"result":"passed"}` |
| `T-VN-41F1D-D2` | **통과** — `phase: passed` / `status: complete` (2026-09-06T01:47:03Z, runner exit 0, 1분 43초) |
| D2 증거 | `phase: evidence-validated` — 파일 집합 exact(10), lifecycle 48, FK 제약 18, 리포트 2 |
| D2 잔여물 | 독립 측정으로 0 — acceptance 소유 row 0, 라벨 컨테이너 0, BLOCKED/ACTIVE/RESULT 없음 |
| 선행 축 | 같은 pinset에서 ACL preflight 55/55 · D1 11 passed(29.9초) |
| 게이트 | 결함마다 `tests/lint/` 탐지기, 전부 변이로 red 확인 |
| pinset | Map `ab3640f8` + PinVi #535 — rebuild `48166bd2…`, generation `56d331a7…` |

### 다음 한 작업

**`T-VN-41C`의 구조적 순환에 대한 소유자 판정.** 선행 배리어는 전부 닫혔다 — D1·D2·
`T-VN-41F1D-E`·`T-VN-M01` 완료. 41C의 relay·reconciliation은 **구현이 끝나 있다**(2026-09-06
재조사가 종전 서술을 정정했다). 남은 셋 중 앞의 둘은 셋째가 풀리기 전에는 착수할 수 없다:

1. **런타임 결선** — 배포 Map 컨테이너에 `..._CACHE_TARGET_SERVICE_PRINCIPALS`가 없어 service
   표면이 401이고 relay 관계 19개가 전부 0행이다.
2. **enable 경계 구현** — PinVi가 production에서 sync enable을 거부하며, 그 조문이 기다리는
   "root-owned final C7 enable boundary"가 Manager에 없다.
3. **구조적 순환** — 켜면 `environment_sha256`이 바뀌어 rebuild가 필요한데, Manager
   `require_rebuildable_mode`는 cache-target 값이 inert여야 rebuild를 허용한다. **현
   lifecycle(rehearsal/rebuildable)에서 enable과 pinned rebuild는 상호배타다.**

셋 중 하나를 골라야 한다 — (a) lifecycle을 옮긴다, (b) Manager가 cache-target 축을
`environment_sha256` 결박에서 분리한다, (c) enable을 실 production 전환 시점까지 미룬다.
(a)는 rebuild 능력을 잃고, (b)는 Manager 계약 변경이며, (c)는 41C를 그때까지 여는 것이다.
`docs/tasks.md`의 41C 줄과 `tasks-acceptance.md` §T-VN-41C가 정본이다.

`GM-17`은 소유자 지시로 **가장 마지막**이다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정 — 이 줄이 순서를 뒤집어
적고 있었다). `GM-17`은 소유자 지시로 **가장 마지막**이다.
`T-VN-D2-API-AUDIT`(helper의 `api-audit`/`purge` 경로가 한 번도 실행된 적 없음)은 D2 완주와
분리했다 — 고치려면 clone lane의 content digest 계약까지 함께 판단해야 한다.

### 이번에 확인된 운영 사실

- **증거 계약 위반은 스펙이 통과한 뒤에야 드러난다.** `_validate_evidence`가 정확한
  파일명 집합과 action별 키를 요구하는데 그 검증이 스펙 통과 뒤에 돌기 때문이다. 그래서
  결함이 병렬로 안 보이고 배포 스택 실행 한 번에 하나씩 직렬로 나온다 — 열두 번을 그렇게
  썼다. 게이트를 로컬에서 유도해 미리 깨뜨리는 것이 그 비용의 유일한 대안이다.
- **executor 이미지를 같은 `:local` 태그로 다시 빌드하면 핀이 가리키던 이미지가 사라진다.**
  live attestation이 image ID를 exact로 들고 있어 재빌드 순서를 지켜야 한다.
- **`rolinherit=false`라 privilege 확인에 `::regclass`를 쓸 수 없다.** Map 역할 전부가
  NOINHERIT이므로 preflight는 catalog join으로만 판정한다.


## 2026-09-05 — 새 pinset에서 D1 통과, D2는 helper 결함 셋을 고치고 재실행 대기

`af6d7061`(Map `c72456f6` + PinVi `f4401659`)로 rebuild를 마쳤고, attestation을 재발행해
verifier가 PASS했다. D1은 통과했다. D2는 seed에서 죽었고 원인 셋을 전부 고쳐 실 DB에
대고 seed → cleanup → audit을 통과시켰다.

| 항목 | 상태 |
|---|---|
| pinset | **`af6d7061`** = Map `c72456f6` + PinVi `f4401659` |
| rebuild | 성공 (`2acd8e97…`, generation `31622c79…`) |
| host attestation v4 | 재발행 `10ad0f0f…` — **verifier PASS** |
| C7 executor image | `sha256:f760bf6c…` (라벨 `c72456f6`) |
| `T-VN-41F1D-D1` | **통과** — 데이터 비의존 live UI 11/11, 33.2초, 핀 자신의 스펙 바이트로 실행 |
| `T-VN-41F1D-D2` | helper 결함 셋 수정 완료, 실 DB 사이클 통과. **재실행 대기** |
| D2 lane 상태 | `BLOCKED` 해제 — 잔여물 0 실측 후 `clear-blocked`, 증거는 `adjudicated-…`에 보존 |

### 다음 한 작업

**helper 수정을 머지한 뒤 pinset을 한 번 더 돌린다.** 설치 스냅샷 디렉터리 이름이
`E2E_C7_EXPECTED_GIT_COMMIT`에 결박돼 있고 그것이 attestation의 `repository_commit`·
generation의 `map_source_revision`과 exact여야 하므로, Map revision이 바뀌면
rotate-pair → rebuild → attestation 재발행 → 스냅샷 재설치 → executor 이미지 재빌드 →
D1 → D2가 따라온다. 전 과정이 이번에 스크립트로 남았다.

그 뒤 순서는 **`T-VN-41F1D-E` → `T-VN-41C`**다(2026-09-06 정정). `GM-17`(Manager production compose
required-set 완화)은 소유자 지시로 **가장 마지막**이다.

### 이번에 확인된 운영 사실

- **out-of-band DB 패치는 다음 rebuild에 증발한다.** 어제 배포 DB에 손으로 준
  `GRANT SELECT ON public.alembic_version TO ktm_feature_migrator`가 rebuild로 사라졌고,
  그래서 helper의 진짜 결함이 드러났다. DB가 선언된 계약으로 수렴하는 건 좋은 성질이지만
  그런 패치에 기댄 green은 근거가 되지 못한다.
- **rebuild가 `BLOCKED` lane을 가로지르면 `recover`가 구조적으로 불가능하다.**
  `begin-recovery`가 BLOCKED의 execution identity와 현재 identity의 일치를 요구하는데
  rebuild가 여섯 필드를 전부 바꾼다. 이때의 정본 경로는 잔여물을 직접 측정해 0임을 확인한
  뒤 `clear-blocked`로 정리하고 증거를 남기는 것이다.

### 남아 있는 소유자 판정

- `docker/*.py` 여섯 파일이 `mypy --strict` clean인데도 검사 밖이다(n150 실측). 프로덕션
  기동을 막는 `application-schema-final-permit.py`가 그중 하나다. 편입 비용은 0이지만
  `application-schema-fresh-finalize.py`(5건)·`dagster-storage-migrate.py`(4건)는
  정리가 필요해 경계를 어디에 둘지가 판단이다.
- CI의 mypy는 핀이 없다(`mypy>=1.10`). 새 mypy 릴리스가 검사를 조이면 무관한 PR에서
  `lint` job이 붉어질 수 있다 — 기존 세 스텝도 같은 노출을 갖는다.
