# tasks-acceptance 아카이브 — `T-VN-M05-VERIFY-RECEIPT` (완료)

> `T-VN-M05-VERIFY-RECEIPT`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-11-17).
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

## T-VN-M05-VERIFY-RECEIPT

**2026-09-07 신설.** 3차 적대 리뷰가 잡았다 — `--verify-leaf`는 **아무것도 쓰지 않는다.**
print만 하고 return하므로, 승격 근거가 원장에 붙인 출력 텍스트로만 남는다. 조문이
"승격은 문서 행위가 아니다"라며 배격한 상태 — 기계 증적 없이 사람이 옮긴 문장 — 가
정확히 검증 **결과**에 남아 있다.

그리고 그 근거는 셋 중 무엇이 먼저 와도 재현 불가가 된다: `pin rotate-pair`(의도된
성질), execution history 500칸 링에서 binding이 밀려남, leaf identity 소각.

- [x] **V1 — 검증이 root-owned receipt를 남긴다.** (2026-09-08, Manager #335)
  `--verify-leaf`가 통과·실패 모두에 대해 검증 시각·검증기 revision·leaf 경로·읽은
  registry 파일 경로·정의표의 **모든 축**(현재 15줄) 각각의 결과와 detail을 root-owned 0600 파일로 남긴다 — 축이 늘면 receipt도 함께 는다.
  **실패도 남긴다** — 통과만 남기면 "검증한 적 없다"와 "검증했는데 떨어졌다"가 같아 보인다.
- [x] **V2 — receipt가 그 시점의 대조 입력을 함께 싣는다.** (2026-09-08, Manager #335)
  pinset·Map/PinVi revision·binding의 Manager revision·claim 이름을 값으로 싣는다.
  나중에 pin이 움직여 재현이 불가능해져도 **무엇과 대조해 통과했는지**는 남는다.
- [x] **V3 — receipt가 원장 인용을 대체한다.** (2026-09-08 충족)
  조문이 출력 텍스트를 옮겨 적는 대신 receipt 경로와 그 sha256을 인용한다. 옮겨 적기가
  사라져야 이 항목의 요지가 달성된다.

  **2026-09-08 — 승격 정의를 개정하고(소유자 승인) 배포된 빌드로 실측했다.**

  `install-ktdm-trusted-release`로 `ee281b5`(#335)를 n150에 설치하고
  `pin rebind-execution`으로 재결박한 뒤(`execution_binding: manager_drift → current`)
  두 승격 후보를 검증했다. **둘 다 15축 전부 PASS, exit 0.**

  | leaf | receipt | sha256 |
  |---|---|---|
  | `/root/pairv2-e2e-02` | `/var/lib/kor-travel-docker-manager/m05-verify-receipts/pairv2-e2e-02-20260908T045824773930Z.json` | `b65b1d79ccca2c30fe989625bba8c23b9e49f69cbc7ffd3a8ae93220e5ba027c` |
  | `/root/pairv2-e2e-03` | `…/m05-verify-receipts/pairv2-e2e-03-20260908T045803209001Z.json` | `06f8383d54afd157b1923f170cec7bf323ab74603b3a287d423b07228e9a6365` |

  디렉터리와 파일 모두 `root:root`, 각각 `0700`/`0600`.

  **재배포가 과거 증적을 무효화하지 않았다** — 설치본은 `ee281b5`인데 두 leaf의 binding
  Manager revision은 `d36847e2`/`0406b14d`다(`is_installed=False`). L4·L5가 설치 revision이
  아니라 **registry binding**에서 파생하도록 만든 설계가 정확히 이 경우를 위한 것이었고,
  이번 배포가 그것을 처음으로 실증했다.

  receipt가 싣는 것: `pinned_pair`(pinset·Map·PinVi revision), `leaf_binding`(execution
  identity·binding Manager revision·`is_current_execution`), `ledger_claim_name`,
  `registry_paths` 셋, `verifier`(설치 revision + **검증기 스크립트 자신의 sha256**
  `8ef83e0a…`), `coverage`, 축 15개 각각의 결과와 detail.

  **이 표가 종전의 30줄 전사를 대체한다.** 해시는 옮겨 적을 수 없다 — 위조하려면
  root-owned 0600 파일을 만들어야 하고, V4가 receipt를 통과 조건에서 배제하므로 그렇게
  만들어 둬도 승격되지 않는다.
- [x] **V4 — receipt 자체가 위조 문턱을 낮추지 않는다.** (2026-09-08, Manager #335)
  receipt는 검증의 **기록**이지 근거가 아니다. `--verify-leaf`가 receipt의 존재를
  통과 조건으로 삼지 않는다(그러면 receipt를 만들어 두는 것으로 통과할 수 있다).

**2026-09-08 — V1·V2·V4 충족, V3는 열려 있다(Manager #335).**

`--verify-leaf`는 정말로 아무것도 쓰지 않았다. **V2가 요구하는 값은 전부 이미
지역변수로 살아 있었고** print 문자열에만 들어갔다 버려지고 있었다 — 모아서 receipt로
내는 것이 대부분의 일이었다.

**가장 날카로운 지점은 신뢰 경계 거부였다.** 그 경로는 한 문장만 인쇄하고 `return 1`이라
`checks`가 빈 채로 끝났다. receipt를 붙였어도 내용이 비었을 것이고, "실패도 남긴다"가
가장 필요한 실패 종류가 바로 그것(leaf가 가짜라는 판정)이다.

**조문 문구 하나를 정정한다.** V1이 "정의표의 **모든 축**(현재 15줄)"이라 적었는데,
15줄은 **full-pass 경로에서만** 맞다. 조기 종료 경로는 16번째 식별자를 내고 L3~L8을
억제해 4~8줄이 된다. receipt는 잰 축을 그대로 싣고 `coverage`로 **어디서 멈췄는지**를
말한다 — 그것이 "모든 축"의 실현 가능한 형태다.

**V3가 남은 이유.** 이 조문은 receipt **경로와 sha256을 원장이 인용**할 것을 요구하는데,
그러려면 배포된 빌드로 실제 검증을 한 번 돌려야 한다. #335가 머지되고
`install-ktdm-trusted-release`로 배포한 뒤(그 자체가 execution identity를 바꿔 rebind를
부른다) 실행할 일이다.

**그리고 V3는 조문끼리 충돌한다.** §T-VN-M05-ACTIVATION의 승격 정의가 "**그 출력을 이
절에 기록한다**"고 **명령**한다. V3를 채우려면 그 문장도 함께 고쳐야 하며, 그것은 승격
정의의 개정이므로 소유자 판정이다.

**변이 검증**(초기 9축 + 적대 리뷰 후속 5축 = 14축 전부 RED). 넷은 처음에 공허했다 —
소비·marker 배선이 `finally` 안에 인라인이라 직접 잴 수 없었다. 이 파일이 이미 같은
이유로 `driver_exit_code`를 꺼낸 전례가 있어 같은 방식으로 추출했다.
