# tasks-acceptance 아카이브 — `T-VN-M05-ONESHOT-CONSUME` (완료)

> `T-VN-M05-ONESHOT-CONSUME`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-11-19).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-M05-ONESHOT-CONSUME

- [x] **T-VN-M05-ONESHOT-CONSUME — 격리 acceptance 성공이 execution identity를 소비하게 한다** (2026-09-08 충족, Manager #335)

**2026-09-07 실측으로 드러난 구멍이다.** 격리 M05 one-shot은 **본문 실패에만** 강제된다
— `_block_terminal_m05_execution`이 본문 phase에 `phase=None`(무조건 차단)을 남기지만,
`run-m05-isolated-e2e-once`의 **성공 분기**(`case 0)`)는 `exit "$driver_status"`뿐이고
`pin block-execution`이 없다. 그래서 **같은 execution identity에서 acceptance 본문을 두
번 돌릴 수 있다.**

**단순히 성공에도 무조건 차단을 걸면 안 된다.** 지금 상태는 `phase=None` 하나뿐이라
"소각(burned)"과 "소비(consumed)"가 구분되지 않고, 성공에 같은 것을 쓰면 방금 성공한
leaf가 `--verify-leaf`의 L8("terminal 차단 아님")에서 실패한다. 승격 근거가 스스로를
무효화하는 셈이다.

**해제 조건.**

1. 소비 상태를 소각과 **구분해서** 기록한다(예: scoped phase 또는 별도 필드).
   `is_unconditionally_blocked_current()`가 소비를 소각으로 세지 않아야 한다.
2. `_assert_current_m05_execution_is_runnable`이 **소비된 identity의 본문 재실행을
   거부**한다. 복구 경로는 rebind 또는 회전이며 그 사실을 진단 메시지가 말한다.
3. `--verify-leaf`의 L8이 소비된 identity의 leaf를 계속 통과시킨다.
4. 변이 검증: 성공 시 소비 기록을 지우면 red, 소비를 소각으로 취급하면 L8 게이트가 red.

**2026-09-08 충족 — 넷 다(Manager #335).**

scoped phase `execution_identity_consumed`로 남긴다. 그러면 셋이 동시에 성립한다:
`is_unconditionally_blocked_current()`가 소각으로 세지 않아 배포·회전이 안 막히고(소비는
"승격됐다"이지 "오염됐다"가 아니다), L8이 `entry.phase is None`만 보므로 통과한 leaf가
계속 검증되고, runnable assert가 이것만 따로 보고 재실행을 막는다.

**`result.json`에 키를 더하지 않았다.** 런처가 키 집합을 정확히 강제해
(`set(value) != expected_keys` → degraded → 무조건 소각) 그 계약을 건드리면 통과한
1~2시간 실행이 타 버린다.

**적대 리뷰가 내 변이 검증이 놓친 축을 잡았다(P1).** `has_block_for_current(phase=...)`
에서 `phase=`를 떼면 그 술어가 **모든** 차단 기록을 잡아, 인프라 phase로 scoped 기록이
남은 identity가 영구히 거부되고 진단은 엉뚱하게 `execution_identity_consumed`가 된다 —
#330이 넣고 #331이 되돌린 회귀와 같은 부류다. **내 9축은 "지우기"만 쟀고 "약화"를 재지
않았다.** 갈리는 유일한 상태(소비가 아닌 scoped 기록 하나)를 만드는 축을 더했다.

그리고 리뷰가 내 테스트 하나를 공허하다고 잡았다 — "아무 문자열이나 phase면 scoped
기록이 된다"를 재는 것이라 어떤 줄도 빨갛게 만들지 못했다. 지웠다.

**2항의 진단**은 `_PAIR_DIAGNOSTICS`가 아니라 상위 집합에 넣는다. 그 집합은 pair 실패
전용이고 "안의 모든 문자열이 발신된다"를 기존 테스트가 양방향으로 결박하므로, 다른
phase의 진단을 섞으면 그 결박이 거짓이 된다.
