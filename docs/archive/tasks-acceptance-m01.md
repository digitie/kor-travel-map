# tasks-acceptance 아카이브 — `T-VN-M01` (완료)

> `T-VN-M01`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-13).
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

## T-VN-M01

```markdown
- [x] **T-VN-M01 — admin Feature 생성 API clean cutover** (2026-09-06 완료). Map PR #1029
  (merge `57c9d99a`)에 `0226_m01_manual_feature_create`의 DB/ACL/backup manifest와 API·Admin BFF가
  함께 착지했다. PinVi direct-create fail-close는 [PinVi #458](https://github.com/digitie/pinvi/pull/458)로
  완료됐다. 남은 것은 `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false`를 유지한
  route 활성화 전 fresh restore/ACL/live gate다.
```

**활성화 전제 셋** (설계 문서 §1). 셋을 모두 만족하기 전에는 플래그를 `true`로 바꾸지
않는다. **2026-09-06에 셋 다 닫혔고 플래그는 `true`다.**

| 전제 | 상태 |
|---|---|
| PinVi `new_place` 직접 create 제거 배포 | **완료** (PinVi #458) |
| M01 DB/API/admin UI + 최소 backup·restore·ACL reconciliation 배포 | DB/API/UI 완료(#1029). ACL reconciler는 API 부팅마다 실행. **ACL 축 55/55**(rebuild 앞뒤 두 번). **restore 축은 300 baseline이 대체**(아래) |
| 전용 BFF 자격 성공 · PinVi/일반 AdminBFF 거부 · DB zero-write smoke | **완료** — 성공 201, 거부 4/4 403, witness 8관계 증분 0 |

**ACL 축 — 2026-09-05 배포 런타임 실측 통과(55/55).** `scripts/m01_activation_preflight.py`가
설계 §8.1~8.3을 재실행 가능한 형태로 확인한다. 아무것도 쓰지 않으므로(catalog
`has_*_privilege`/`pg_has_role`만) 활성화 전 프로덕션에서 그대로 돌린다. §8.2가
**"restore 뒤 동일"**을 요구하므로 restore·rebuild 뒤에도 다시 돌린다. 확인 내용:

    role 속성(NOLOGIN NOINHERIT) · membership exact option(admin/inherit/set)
    교차 멤버십 부재 · runtime login의 owner SET ROLE 불가
    claim/origin direct SELECT/INSERT/UPDATE/DELETE/TRUNCATE 부재(API·Dagster·PUBLIC)
    relation owner = ktm_feature_schema_owner
    wrapper  create_admin_manual_feature_with_initial_state  api=true  dagster=false public=false
    generic  create_feature_with_initial_state               api=false dagster=true  public=false

**restore 축 — 300 baseline이 대체했다(소유자 판정 2026-09-06).** 설계 §10.3은
`pg_restore --no-owner --no-privileges` 뒤 owner repair·ACL reconciler·§8.3 재통과를
요구한다. 그런데 그 설계(2026-08-19) **이후**의 300 baseline 결정이 복구 경로를 없앴다 —
`scripts/docker-restore.sh`·`docker-restore-verify.sh`·`docker-restore-swap.sh` 셋 다 본문
없이 종료하며 이유를 이렇게 적는다:

    restore is disabled: backup artifacts are audit-only under the 300 baseline
    Alembic archive replay, previous-revision restore, and hot swap are unsupported

즉 검증된 복구 형식이 존재하지 않으므로 이 전제는 **수행 가능한 형태가 아니다.** 같은
방향의 운영 결정이 원장에 이미 있다 — `T-VN-H43`이 "n150은 실 production이 아니며 손상 시
재적재가 정책"이라 적는다. 그래서 restore 축을 활성화 전제에서 **뺀다.**

되살릴 조건: 300 baseline에 맞는 검증된 restore 경로가 생기면 §10.3을 그대로 다시 세운다.
그때 §8.3 재통과는 `scripts/m01_activation_preflight.py`가 그대로 수행한다 — 그 스크립트를
남긴 이유가 이것이다.

**남은 순서 — 2026-09-06 기준 셋 다 수행됐다.**

| 단계 | 결과 |
|---|---|
| (1) 플래그 활성화 | `KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=true` (`/opt/kor-travel-docker-manager/.env`, 2026-09-05T20:27:59Z, 백업 `.env.bak-pre-m01-activation-20260905T202759Z`). `environment_sha256`이 바뀌므로 rebuild가 따라왔다 |
| (2a) 거부 축 | `scripts/m01_activation_live_gate.py` — 잘못된 자격 조합 넷이 전부 **403**: 자격 없음 · admin proxy secret만(일반 AdminBFF) · create token만 · proxy secret + 틀린 create token. body는 **유효한 것**을 보낸다 — 422가 아니라 자격 때문에 거부됐음을 보이려면 body 검증보다 자격 검증이 먼저 돌아야 한다 |
| (2b) zero-write 축 | 같은 스크립트가 거부 실행 전후로 witness 8관계(`feature.features`·`feature_places`·`feature_state_transitions`·`manual_feature_identity_claims`·`feature_creation_origins`·`ops.feature_overrides`·`domain_commands`·`domain_command_results`) count를 대조 — **증분 0** |
| (2c) 성공 축 | 플래그가 켜져야 관측 가능하다고 적었던 그것이다. 배포 스택에서 `POST /v1/admin/features` → **201**(2026-09-05 실측). D2 lane이 매 실행 재관측한다 |
| (3) D2 | 이제 503에 막히지 않는다. 잔여는 D2 자신의 lane 완주다 |

**ACL 축은 rebuild 뒤에도 다시 측정했다.** §8.2가 "restore 뒤 동일"을 요구하므로 활성화
rebuild 앞뒤로 각각 돌려 **두 번 다 55/55**였다. 즉 플래그 활성화가 ACL 계약을 흔들지
않는다는 것이 값으로 남아 있다.

**아직 이 배포에서 한 번도 돌지 않은 것.** backup 축은 저장소에 구현돼 있으나
(`scripts/docker-backup.sh`가 4관계 count·PK 순 canonical JSONL SHA-256 root를 manifest에
쓴다) 이 배포에는 backup root 설정도 산출물도 없다(2026-09-06 실측). 활성화 전제로 세지
않지만 사실로 남긴다 — `T-VN-H49` 계열이 소유한다.
