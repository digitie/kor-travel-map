# tasks-acceptance — T-VN-D2-API-AUDIT (완료, 아카이브)

원장 [`docs/tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB 상한에 닿아 닫힌 절을 옮겼다(2026-11-10, 규약 §8). 원문 그대로다.

## T-VN-D2-API-AUDIT

```markdown
- [x] T-VN-D2-API-AUDIT — D2 fixture helper의 `api-audit` 경로를 실행 가능하게 만든다 (2026-09-06 완료)
```

**2026-09-06 완료.** 러너가 `api-audit`을 실제로 부르고 `ktdm-d2-008`이 `phase: passed`로
닫혔다 — lifecycle 56 = 7 operation × 8 phase(`helper-api-audit` 8개), evidence
`phase: evidence-validated`, api-audit counts 3·1·7·3 / FK 18·8. feature_id 규칙은 서로
다른 실행이 만든 Feature **셋**으로 배포 DB에서 확인했다. 상세는
[`docs/tasks-done.md`](../tasks-done.md).

`purge`는 여전히 열려 있지 않다 — hard purge는 `T-VN-M02`가 fence하고, supervisor 허용
목록은 호출자가 생길 때 함께 연다(게이트가 단언한다).

**왜 열었는가.** `run-admin-feature-live-acceptance.sh`는 `run_helper`를 `seed`·`cleanup`·
`audit`으로만 부른다. `api-audit`과 `purge`는 helper에 구현돼 있으나 **한 번도 실행된 적이
없고**, 그래서 그 안의 계약이 검증된 적이 없다. 2026-09-06 적대 리뷰가 셋을 찾았고 둘은
고쳤다(operation 이름·성공 status를 `domain_command_registry`에서 유도). 남은 하나가 이
항목이다.

**남은 결함.** `_admin_fixture_feature_id`가 `{name}:{lon:.6f},{lat:.6f}`를 자연키로
`feature_id`를 재계산한다. M01 이후 서버는 `manual::{feature_uuid}`를 쓰고 그 uuid는
서버가 발급하는 **랜덤 UUIDv7**이라, run_id만으로는 원리적으로 재계산할 수 없다. 따라서
`_inspect_api_owned`의 `feature_id != expected_feature_id` 대조와
`_audit_complete_api_owned`의 `feature_ids != (feature_id,)`는 항상 실패한다.

**왜 D2와 분리하는가.** 같은 함수를 clone 러너의 content digest 계약이 함께 쓴다 —
`scripts/run-admin-feature-clone-live-acceptance.sh`가 셸 안에서 같은 규칙을 재현하고
`tests/unit/test_admin_feature_live_acceptance.py`가 두 파생의 일치를 단언한다. 즉 이
수정은 두 lane의 계약을 함께 판단해야 하고, D2 완주 경로에는 필요하지 않다.

**해제 조건.**

1. `_admin_fixture_feature_id`가 **행의 `feature_uuid`로** 서버 규칙을 재현한다
   (`category="manual_feature_v1"`, `source_natural_key=f"manual::{uuid}"`). 재계산이
   아니라 재현이므로 랜덤 uuid에도 성립하고, router 규칙이 바뀌면 여전히 실패한다.
2. clone 러너의 content digest가 같은 규칙으로 옮겨지거나, D2와 clone이 서로 다른 규칙을
   쓴다는 사실이 두 곳에 명시된다. 어느 쪽이든 `tests/unit/test_admin_feature_live_acceptance.py`의
   두 파생 일치 단언이 실제를 반영해야 한다.
3. 러너가 `api-audit`을 실제로 부르고, 그 실행이 배포 스택에서 통과한다. 부르지 않으면
   1·2가 다시 잠복한다 — **이 항목의 요지가 그것이다.**
4. 변이 검증: operation 이름·성공 status·feature_id 규칙을 각각 되돌리면 게이트가 red가
   된다.

**새 helper action을 더할 때 함께 고쳐야 하는 곳 — 다섯이다** (2026-09-06에 전부 CI
게이트가 됐다). `run_helper api-audit`을 더하면 `helper-api-audit` operation과
`direct-api-audit.json`(+ stderr sibling)이 생긴다.

| 곳 | 안 고치면 | 언제 알게 되나 |
|---|---|---|
| `run-admin-feature-live-acceptance.sh`의 `LANE_OPERATIONS` | `run_supervisor`·`run_executor`가 `die` | **즉시** |
| `admin_feature_live_supervisor.py`의 `--helper-action` **choices** | argparse가 **exit 2** — lifecycle도 출력 파일도 쓰기 **전**이라 lane에 아무 흔적이 없다 | 배포 스택 실행 1회, 게다가 **엉뚱한 곳**을 가리킨다 |
| `admin_feature_live_state.py`의 해당 mode `required_operations` | lifecycle 파일 이름 대조에서 죽는다 | 배포 스택 실행 1회 |
| 같은 파일의 해당 mode `expected_names` | 파일 집합 exact 대조에서 죽는다 | 배포 스택 실행 1회 |
| 호출을 `recover_run`에도 두면 **recovery 쪽 두 집합** | normal/recovery는 별개 계약이다 | recovery 실행 1회 |

**둘째가 이 표를 다섯 줄로 만든 이유다.** 2026-09-06에 앞의 넷만 고치고 `ktdm-d2-007`을
돌렸더니 이렇게 나왔다:

    lifecycle 48개 = 6 operation × 8 phase     helper-api-audit은 0개
    direct-api-audit.json 없음
    runner die: "owned fixture cleanup left residue"

설치된 스냅샷도 러너 호출부도 멀쩡했고, 실패는 cleanup residue를 가리켰지만 실제
잔여물은 0이었다(독립 측정). 원인은 supervisor의 인자 검증이었다. **흔적을 남기지 않는
실패는 진단을 한 겹 멀게 한다.**

이제 두 게이트가 다섯을 덮는다:

- `tests/lint/test_lane_operations_are_declared_once.py` — `run_new`/`recover_run`
  각각의 호출부에서 산출물 이름과 operation 집합을 유도해 검증기의 두 집합과 각각
  exact 대조
- `tests/lint/test_supervisor_accepts_every_helper_action.py` — 러너 호출부의 action을
  유도해 supervisor 허용 목록과 helper 구현 action에 양방향 결박

착수할 때 그 둘이 시키는 대로 함께 고쳐라 — CI에서 먼저 red가 난다.
