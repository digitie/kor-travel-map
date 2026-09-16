# tasks-acceptance 아카이브 — `T-VN-M02` (완료)

> `T-VN-M02`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-09-16).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 2개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-M02

```markdown
- [x] **T-VN-M02 — origin 보존과 불변** (결정 4, 구현 병합, 2026-09-16 완료). #1029의 `0227` provenance reader,
  immutable claim/origin ACL과 named hard-purge fence, unit/integration 회귀가 정본이다.
  ~~evidence를 남긴 상태에서의 purge 정책·backup/restore 실측 및 live acceptance가 남아
  있다.~~ **2026-09-08 정정 — 셋 중 둘은 이미 이 절의 것이 아니다**(아래 §잔여 참조).
  ~~남은 것은 live acceptance 하나다.~~ **2026-09-16 — 그 하나도 격리 스택에서 완주했다.** PinVi M05 paired
  attestation이 소비하는 Admin provenance 최상위 identity는 opaque `feature_id`와 별도 `feature_uuid`를
  함께 반환해야 하며, UUID-only projection을 재사용하지 않는다. reader/immutable claim UUID는 모두
  최상위 `feature_uuid`와 같지 않으면 fail-close한다. PinVi consumer도 이 반환 UUID를 M05 case의
  manual/old UUID와 각각 대조하기 전에는 paired live receipt를 승격할 수 없다.
```

**2026-09-07 전수 조사 — spec이 미병합 브랜치에만 있다(유실 위험).**

live acceptance spec은 `origin/feat/m01-m02-live-acceptance`에만 있고 main에는 없다
(main 대비 **64 behind / 2 ahead**, 2파일 +138줄). 그 브랜치가 정리되면 작업이
사라진다 — **회수가 가장 먼저다.** 병합만으로는 닫히지 않는다: spec은
`E2E_MANUAL_CREATE_WRITE=1` opt-in 격리 스택 전용이라 기본 skip이다.

이 절이 세는 것 중 **backup/restore 축은 이 항목의 것이 아니다** — §T-VN-M01이 그 축을
자기 전제에서 빼면서 `T-VN-H49` 계열로 넘겼다. 이 절만 계속 세고 있어 과대 계상이다.

**소유자 판정** 둘: purge 정책(evidence cascade/orphan·권한·409 계약)과
backup/restore 소유권.

**2026-09-07 소유자 판정 — 과대 계상분을 삭제한다.**

이 절이 세던 **backup/restore 축은 이 항목의 것이 아니다.** §T-VN-M01이 그 축을 자기
전제에서 빼면서 `T-VN-H49` 계열로 넘겼는데 이 절만 계속 세고 있었다. 소유자 판정으로
이 절의 범위에서 삭제한다 — 소유는 `T-VN-H49`(+ 자식들)이다.

**이 절에 남는 것은 둘이다.**

1. **live acceptance spec 회수** — spec이 `origin/feat/m01-m02-live-acceptance`에만
   있고 main에 없다(main 대비 64 behind / 2 ahead, 2파일 +138줄). 브랜치가 정리되면
   작업이 사라지므로 판정과 무관하게 먼저 한다. 회수해도 닫히지 않는다: spec은
   `E2E_MANUAL_CREATE_WRITE=1` opt-in 격리 스택 전용이라 기본 skip이다.
2. **purge 정책** — evidence cascade/orphan·권한·409 계약. **소유자 판정 대기.**

**2026-09-07 소유자 판정 — purge 정책을 `T-VN-H49` 계열로 이관한다. 이 절에는 live
acceptance 축만 남는다.**

**2026-09-08 잔여 정정 — 이 절이 세던 셋 중 둘이 해소됐는데 문장이 따라가지 않았다.**

| 이 절이 잔여로 적던 것 | 실제 |
|---|---|
| purge 정책 | **닫혔다** — 2026-09-08 소유자 판정과 migration 306(§T-VN-H49) |
| backup/restore 실측 | **이 항목의 것이 아니다** — 2026-09-07 판정으로 `T-VN-H49` 계열 |
| live acceptance spec 회수 | **끝났다** — spec이 main에 있다(`packages/kor-travel-map-admin/frontend/e2e/live/admin-manual-feature-create.live.spec.ts`) |
| live acceptance **실행** | **유일한 잔여** |

**그 하나가 막힌 이유는 셋이고, 그중 하나는 306이 절반 풀었다.**

1. ~~prod UI가 `admin`이라 `created_by_actor === "e2e-admin"`이 구조적으로 실패한다~~
   — **2026-09-16에 풀었다.** 그것은 계약이 아니라 **리터럴 한 줄**이었다. actor는
   BFF의 `adminUsernameFromEnv()`(→ `ADMIN_USERNAME`, prod는 미설정이라 기본 `admin`)
   에서 나와 `X-Kor-Travel-Map-Actor` → 도메인 커맨드 → `created_by_actor`로 간다
   (체인 전 구간 실측). 저장소의 기존 관용구
   (`ops-c7-read-auth.live.spec.ts`의 `process.env.E2E_ADMIN_USERNAME ?? "admin"`)와
   같은 형태로 환경에서 유도하게 고쳤다 — 결박할 것은 "로그인한 주체가 provenance까지
   실려 온다"이지 그 값이 아니다.
2. **cleanup이 없다 — 이것이 지금 막는 축이다.** 종전에 "306이 풀었다"고 적었는데
   **절반만 맞다**(2026-09-16 정정). #306이 만든 것은 `feature.purge_manual_feature`
   **프로시저**이고, 그것은 **HTTP로 노출돼 있지 않다** — API 라우터에 없어
   (`manual_feature_purge_repo.py`만 있다) spec이 부를 길이 없다. spec에 `purge` 호출은
   **0건**이고 spec 주석 자체가 "생성물을 지우지 않는다"고 적고 있었다. prod에서 돌리면
   지울 수 없는 행이 남는다 — 같은 형태가 `T-VN-D2-RESIDUE`로 이미 열려 있다.
3. 격리 스택이 **사라졌다**(2026-09-08 실측). `~/ktm-live-301`은 정지가 아니라
   컨테이너도 볼륨도 없고, 체크아웃은 alembic head `302`(저장소는 `307`)이며 `e2e/live/`에
   그 spec 자체가 없다. **재기동이 아니라 재구축이 선행이다.**

**그래서 남은 선택지는 둘이고 둘 다 소유자 판단이다.** (a) purge를 HTTP로 노출하고
spec에 cleanup을 붙여 prod D1에 편입 — 되돌릴 수 없는 삭제 경로를 여는 일이고, 아래
"왜 이관인가"가 그것을 restore proof(`T-VN-H49`)보다 먼저 하면 **순서 역전**이라고
적는다. (b) 격리 스택 재구축 — 원장이 애초에 의도한 경로.

그리고 spec은 `E2E_MANUAL_CREATE_WRITE=1` opt-in이라 병합만으로는 돌지 않는다.

**왜 이관인가 — 순서 때문이다.** hard-purge fence의 무조건 거부는 코드가 스스로
**잠정**이라고 적는다(`tests/integration/test_tvn_m01_manual_feature_create.py:180`
"restore proof가 생기기 전에는"). 되돌릴 수 없는 삭제 경로를 restore proof보다 먼저
여는 것은 순서 역전이고, 그 restore proof를 소유하는 곳이 H49다. purge는
backup/restore가 갚히기 전에는 **원리적으로 판정할 수 없다.**

**상세검토 결과 — 구현 축은 전부 충족이다(2026-09-07 4축 실측 + 반증).**

| 조건 | 상태 |
|---|---|
| `0227` provenance reader | 충족 — main + n150 prod DB 실측 |
| immutable claim / origin ACL | 충족 |
| named hard-purge fence | 충족 — `trg_features_manual_feature_hard_purge_fence` → `feature.reject_manual_feature_hard_purge()`, prod 배포·enabled |
| unit/integration 회귀 | 충족 — 정적 계약 2 + router unit 5 + 실 PostGIS 통합 1 |
| PinVi 소비자 계약 3조건 | 충족 — 응답이 최상위 `feature_id`(opaque)와 `feature_uuid`를 required로 병행, 불일치 시 `AdminManualFeatureInvariantError` fail-close, PinVi `_m04_server_side_chain`이 두 축을 M05 case의 manual/old와 **각각** 대조한 뒤에만 승격. `/root/pairv2-e2e-03`가 `m04_map_feature_uuid` + `m04_server_side_chain_verified: true`를 담고 `status: passed` |

**미병합 브랜치 둘의 처분(실측 확정).**

- `feat/tvn-m02-origin-immutability` — **회수 대상이 아니다.** tip 트리 해시가 병합된
  #1029(`57c9d99a`)와 동일하고(`c388f52b…`) 두 커밋 사이 `git diff --stat`이 빈 출력이다.
  38개 고유 커밋 전부가 squash로 들어갔다. 지워도 잃을 것이 없다.
- `feat/m01-m02-live-acceptance` — **spec 파일만 회수했다.** 그 spec은 저장소 전체에서
  그 브랜치에만 있었고(전 리모트 스캔 결과 1개), main의 어떤 live spec도
  `/creation-provenance`를 부르지 않았다. 같은 브랜치의 문서 커밋(`f14c58c1`)은
  가져오지 않았다 — 빈 ```` ```markdown ```` 펜스 2줄을 넣는 흠이 있고, 본문이 주장하는
  잔여 조건(fresh restore·backup/restore)은 2026-09-06/09-07 판정으로 이미 무효다.

**이 절에 남는 조건 — 하나.**

- [x] **live acceptance 실행** — `admin-manual-feature-create.live.spec.ts`가
  `E2E_MANUAL_CREATE_WRITE=1`로 격리 스택에서 완주한다. **2026-09-16 충족.**

  live301(api `13711` · web `13712` · dagster `13714`)에서 **2 passed (47.9s)** —
  `auth.setup` + 본 검사. 그리고 **검사가 초록인 것과 DB가 그렇게 된 것은 다른 사실이라**
  따로 셌다: `feature.features` 1 → 2, 그리고 `feature.feature_creation_origins`에

      origin_kind          manual_admin
      created_by_actor     e2e-admin
      invoker_role         ktm_feature_api_runtime
      procedure_definer    ktm_manual_feature_procedure_owner
      creator_principal_id admin-ui-bff.manual-feature-create.v1

  이 절이 요구한 "origin이 단건 admin 경로의 principal/role 계약을 정확히 싣는다"가
  이것이다 — 로그인한 주체가 BFF를 지나 SECURITY DEFINER 경계 너머 provenance까지
  실려 왔다.

  **이 spec은 한 번도 실행된 적이 없었다.** 2026-09-16에 actor 리터럴 결함을 찾은 것도
  실행이 아니라 체인을 읽어서였다. 즉 통과한다는 것이 알려져 있지 않았고, 이번이 첫
  실행이다. 첫 실행이 초록이라는 사실 자체가 이 조문의 값이다.

  **예고한 대로 행이 하나 남았다**(1 → 2). cleanup이 없다는 아래 서술이 실측으로
  확인됐다는 뜻이고, 격리 스택이라 차단 사유가 아닐 뿐 prod 불가 근거는 그대로다.

  **스택을 세우며 막힌 것 둘(다음 사람을 위해).** (1) 체크아웃을 옮기면
  `scripts/*.sh` 실행권한이 빠진다 — `preflight-ports.sh: Permission denied`.
  (2) **Dagster 메타DB가 통째로 없었다** — `kor_travel_map_dagster` 롤도 DB도 없어
  `password authentication failed`로 섰다. 앱 DB(`ktm_live_301`)는 멀쩡했고 head도
  `309_t39_feature_id_rekey`로 저장소와 같았다. 롤·DB를 만들고
  `DAGSTER_HOME=.dagster-migrate dagster instance migrate`(public 22 테이블)까지 해야
  런처의 사전검증을 지난다. spec 자체는 Dagster를 쓰지 않지만 `run-admin-stack.sh`에
  건너뛰기 경로가 없다.

  **아래 서술은 2026-09-08 시점이라 이미 낡았다 — 대조용으로 남긴다.**
  **배포 prod에서 돌리지 않는다**
  — prod UI는 `KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=admin`이라 spec의
  `created_by_actor === "e2e-admin"` 단언이 구조적으로 실패하고, spec은 cleanup을 하지
  않아 지워지지 않는 write를 prod DB에 남긴다.

  **왜 지워지지 않나(2026-09-08 규명).** admin API의 `DELETE /{feature_id}`는 soft
  `action="retire"`이고 hard purge는 `trg_features_manual_feature_hard_purge_fence`가
  거부한다. 즉 이 항목의 prod 불가는 `T-VN-M02-TRUNCATE-FENCE`와 **같은 fence**에서 온다 —
  두 항목을 따로 판정하면 안 된다.

  실행처는 n150 `~/ktm-live-301`이다. ~~그 스택은 이미 `e2e-admin`·create token·flag가
  spec과 맞다(현재 정지 상태 — 재기동이 선행한다).~~ ~~**2026-09-08 재실측 — 정지가 아니라
  없다.** 컨테이너도 볼륨도 존재하지 않고(`ktm-live-301-pg` 부재, `ktm_live_301` 볼륨 부재),
  그 체크아웃은 alembic head **302**(저장소는 305)이며 `e2e/live/`에 해당 spec 자체가 없다.
  설정 산물(`~/.ktm-live-301-admin-pw`, `.env`, `live301-start.sh`)과 runner 이미지는
  남아 있으므로 재구축은 가능하지만 **재기동이 아니라 재구축이 선행이다.**~~

  **2026-09-16 재실측 — 위 문단은 틀렸다.** `ktm-live-301-pg`는 떠 있었고(5일째),
  체크아웃(`0af5f36d`, 2026-09-11)에 spec이 들어와 있었으며 앱 DB head는 `309`로
  저장소와 같았다. **재구축이 아니라 체크아웃 전진 + api/ui 기동**이었다. 이 항목이
  "막혀 있다"고 적힌 채 여덟 날 열려 있던 이유의 절반은 그 기록이 낡았기 때문이다 —
  `T-VN-D2-RESIDUE`와 같은 모양이고, `docs/tasks-rule.md` §6이 그 형태를 다룬다.
