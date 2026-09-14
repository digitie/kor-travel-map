# tasks-acceptance 아카이브 — `T-VN-PAIR-V2` (완료)

> `T-VN-PAIR-V2`의 해제 조건 원문이다. 절은 닫혔고(`docs/tasks-done.md`에 기록),
> live 문서 [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB
> (225,280 bytes) 상한에 **78 bytes 앞까지** 차 있어 규약 §8대로 분리했다(2026-09-14).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다.
> 이 절에는 상대 링크가 없어 재기준화할 것도 없었다.
>
> **분리 전에 쟀다.** 이 절을 들어냈을 때 나머지 항목의 체크박스 파싱이 달라지지
> 않는 것을 `parse_checkboxes`로 확인했다(변화 0건). 2026-09-14에 제목 기준으로
> 원장을 통째로 쪼개려다 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다 —
> 코드 fence가 절 경계를 가로질러 `inside_fence` 판정이 뒤집혔다. 이 절은 fence가
> 짝을 이루고 파싱되는 항목이 0개다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-PAIR-V2

**2026-09-07 실측 — 종전 서술의 과소·과대 계상을 함께 정정한다.** 네 축을 병렬 조사하고
48건을 반증에 부쳐 27건이 정정됐다. 아래는 반증을 통과했거나 정정된 것만 적는다.

**과소 계상 — 소비자는 하나가 아니라 셋이다.**

| 소비자 | 지점 | 성질 |
|---|---|---|
| `apps/api/app/core/config.py` | `_load_m05_pair_provenance` 봉투 단언, **모듈 스코프에서 호출** | v2를 먹이면 `import app.core.config`가 `RuntimeError`로 죽는다 — 요청 오류가 아니라 **컨테이너 기동 실패**(실측 재현) |
| `scripts/m05_activation_attestation.py` | 같은 봉투 단언 복사본 | `AttestationError` |
| `scripts/m05_activation_receipt.py` | 같은 봉투 단언 복사본 | `ReceiptError` |

config.py는 봉투 검사 한 줄로 끝나지 않는다 — `source_revision`이 반환 튜플과 6개 모듈
상수로 흘러가고, 그 상수가 활성화 receipt 대조(`:1792-1795`)와 Map image digest
대조(`:1853-1861`)에 쓰인다. 편집 규모는 **약 50~70줄, 지점 6~7개**다.

**과대 계상이었던 것 — 조사 1차에서 "최대 blocker"로 지목했으나 반증됐다.**

- 서명된 활성화 receipt는 blocker가 **아니다**. TTL 상한 7일·기본 24시간으로 만료가 하드
  강제되고 매 활성화마다 새로 서명되므로 보존할 장기 receipt가 없다.
- 되돌리기 위험도 v2가 만드는 것이 아니다. stale `source_revision`이 Manager preflight에
  거부되는 성질은 **v1에서 이미 상시적**이고, 지워지는 두 값은 커밋된 계약 파일과 그
  15개 커밋 이력에 평문으로 남아 있어 n150 root 전용 상태가 아니다.
- Map 원장이 비용을 기록하지 않는다는 것도 사실이 아니다. 기록은 있고(resume.md·tasks.md·
  journal.md 여러 곳) 부족한 것은 **건별 회계**다.

**실제로 남는 안전 공백 하나.** Manager의 **v2 회전 preflight는 아무 대조도 없이 통과**
시킨다(`m05_isolated_e2e.py:2165-2172`). 그래서 "v2 계약 + v1-only 소비자" 조합을 회전
전에 잡지 못하고, 그 조합은 컨테이너 기동 실패다. §5/§7의 Manager 작업에서 이것을 함께
닫아야 한다 — 회전 시점에 target revision의 Map blob digest를 계약과 대조하면 된다.

**비용(왜 하는가).** 2026-09-01 이후 Map 변경으로 강제된 재핀 **12건**, **12건 전부
rebuild 동반**. 그중 **10건은 상류 admin OpenAPI가 바이트 동일**한 채 revision 라벨만
옮겼다(상류 blob sha256이 12개 핀에 걸쳐 두 값뿐). v2는 그 두 필드를 계약에서 걷어내므로
그 10건의 계약 diff가 사라진다.

**선행은 끝나 있다.** Manager dual-read는 구현·배포 완료(n150 `/opt/.../m05_isolated_e2e.py`
확인)이고 v2 happy-path 테스트도 있다. 생성기의 되돌림은 커밋된 JSON이 v2가 되는 순간
자기 무장해제하므로 **생성기 변경은 순서상 마지막**이다.

**해제 조건 7항의 소유자 배분** — 소비자 3(§1 dual-read+사용처 열거, §2 v1 계약 그대로
기동, §4 v2 게이트+양방향 변이) · 생성기 1(§3 `--write` v2 재생성) · Manager 3(§5 preflight
실측, §6 회전→rebuild→격리 e2e, §7 v1 분기 제거).


```markdown
- [x] T-VN-PAIR-V2 — PinVi M05 pair 계약 v2 이행 (2026-09-07 완료)
```

**왜 여는가.** Map revision이 두 곳에서 선언된다 — pin registry(정본)와 PinVi가
vendoring한 pair 계약. Manager의 회전 preflight가 둘을 exact 대조하므로, 어긋나면
회전이 거부된다. 거부 자체는 옳다(2026-09-02에 71분 rebuild를 다 태운 뒤 거부당한
사고를 앞으로 당긴 것이다). 문제는 **Map의 어떤 변경이든 PinVi 커밋을 강제한다**는
것이고, 그것이 곧 새 pinset과 rebuild다. 이중 선언 결함 계열(`AGENTS.md` DO NOT 15).

**진짜 관문은 생성기가 아니라 소비자다(2026-09-05 실측).** PinVi의
`scripts/generate_m05_pair_contract.py`는 **이미 v2를 계산한다** — `build_contract`가
`{"map": surfaces, "version": 2}`를 만든다. 그런데 곧바로 `_in_committed_envelope`가
커밋된 v1 봉투로 되돌린다. 이유가 코드에 적혀 있다: 소비자
`apps/api/app/core/config.py`의 `_load_m05_pair_provenance`가 **모듈 스코프**에서
`set(raw) == {"map", "runtime_image_digests", "version"}`과 `version == 1`을 단언하고,
surface마다 `source_revision`을 요구한다. 계약만 뒤집으면 PinVi API 컨테이너가
**import에서** 죽는다. Manager 격리 preflight는 v1/v2를 함께 읽으므로 회전 전에 잡지
못하고, 실패는 rebuild를 태운 뒤에야 드러난다.

즉 이 작업의 크기는 "생성기 한 줄"이 아니라 **소비자 이행**이다.
`_load_m05_pair_provenance`가 돌려주는 `source_revision`과 `runtime_image_digests`의
downstream 사용처를 먼저 세어야 한다(`scripts/m05_activation_attestation.py`,
`apps/api/tests/unit/test_m05_*`).

**완료 (2026-09-07).** §1~§7 전부 닫혔다.

| 항목 | 상태 |
|---|---|
| §1 소비자 dual-read | **완료** — PinVi #538 |
| §2 v1 계약 그대로 기동 | **완료** — pinset `78cad481…` |
| §3 계약 v2 재생성 | **완료** — PinVi #539 (version 2, `runtime_image_digests` 제거, `source_revision` 0건, digest 16개 무변경) |
| §4 v2 게이트 + 변이 | **완료** — PinVi 9건 · Manager 12건 전부 red |
| §5 PinVi 커밋 없이 새 Map 수용 | **완료** — 정적·실행 양쪽 |
| §6 회전 → rebuild → 격리 e2e | **완료** — `status: passed` |
| §7 Manager v1 분기 제거 | **완료** — Manager #323 |

**§3의 실제 선행은 "생산자 배선"이었고, 그것을 두 번 틀렸다.** 원장은 소비자를
하나로 봤지만 셋이었고(1차 정정), 배선을 하고 나서도 **전문 리뷰어 2명의 적대
검토**가 P0 두 건을 잡았다. 둘 다 "사본을 걷어냈으면 정본을 가리켜야 한다"를
반쯤만 한 데서 나왔다.

| # | 무엇을 틀렸나 | 어떻게 드러났을 것인가 |
|---|---|---|
| P0-1 | evidence의 네 표면 블록은 **attestation이 계약을 복사한 것**인데, receipt가 5키 완전 일치를 리터럴로 요구했다 | v2로는 **어떤 receipt도 만들 수 없다** — 회전·rebuild·repin·D1을 다 태운 뒤 마지막에 막힌다 |
| P0-2 | `service` 표면 revision의 정본을 pin registry로 착각했다. 정본은 PinVi `kor-travel-map-service-provenance-v1.json` | digest는 전부 일치해 preflight도 `_pair`도 통과하고, **71분 rebuild 뒤 PinVi 컨테이너가 기동 실패** |

**표면마다 생산자를 이름 대어 정한다** (attestation `_surface_revisions`, receipt
`surface_revisions`, Manager `_service_release_revision`):

| 표면 | v1 | v2 정본 |
|---|---|---|
| admin·full·user | 계약이 선언 | Map pinned revision (Manager pin registry) |
| service | 계약이 선언 | PinVi service-provenance 계약 |

**픽스처가 두 P0을 다 가리고 있었다.** receipt 테스트가 evidence의 표면 블록을 손으로
적어 **실제 생산자가 낼 수 없는 문서**를 만들고 있었다. 이제 vendored 계약에서 그대로
가져온다 — 계약이 v1이든 v2든 픽스처가 자동으로 그 모양을 따른다.

**Manager 안전 공백도 함께 닫았다.** 종전 원장이 지목한 대로
(v2 회전 preflight가 무조건 통과) 회전 대상 Map revision의 네 표면 blob digest를
계약과 대조하도록 앞으로 당겼다 — 격리 e2e가 rebuild **뒤에** 하던 그 대조다.

**§5 — v1이었다면 71분이 따라왔을 자리.** Map `main`이 pinned `631f1abc`에서 5커밋
앞섰는데 세 표면 blob이 전부 바이트 동일하고 v2 계약의 네 digest와 일치했다.
회전 preflight가 그 Map revision을 **PinVi 커밋 없이** exit 0으로 수용했고, 어긋난
revision(`db319a47`)에는 두 digest를 찍으며 거부했다(음성 대조).

**§6 실측 (pinset `b229446a`).**

| 단계 | 결과 |
|---|---|
| 회전 | rotation #40, pinset `b229446ac273…` |
| rebuild | `success: true`, `phase: committed` |
| 격리 M05 e2e | **`status: passed`**, `phase: completed`, m04·m05 attestation 해시 존재, cleanup 정상 |

**§6에서 PAIR-V2와 무관한 선행 결함 하나가 드러났다.** Playwright runner 이미지 핀이
v1.62.1인데 PinVi lockfile은 1.63.0이었다(회전 **전** pinned PinVi도 이미 1.63.0이었으므로
이 회전이 만든 드리프트가 아니다). 두 값이 어긋나면 `/ms-playwright` 캐시가 적중하지
않아 본문 브라우저 기동에서 무조건 소각인데,
`_assert_playwright_runner_matches_pinned_source`가 **실행권 소비 전에** 잡았다 —
게이트가 설계대로 동작해 한 사이클을 아꼈다(Manager #322).

**§7 — 걷어낸 뒤 변이 검증이 공허한 게이트 둘을 찾았다.**

1. `_pair`가 v1을 다시 받도록 되돌려도 초록이었다 — v1 거부를 확인하는 테스트가 없었다.
2. `"pair contract v2 must not declare a source revision"` 전용 검사는 **도달할 수
   없었다.** 바로 위 entry 스키마 검사가 먼저 잡기 때문이고, dual-read 도입 때부터
   그랬다. 그 검사와 어휘를 걷고 기존 테스트가 실제 진단을 단언하게 고쳤다.

진단 어휘 게이트도 양방향으로 만들었다(allowlist 항목이 실제로 발신되는지도 본다) —
한 방향만 보니 죽은 어휘가 넷 쌓여 있었다.

**§7 뒤 확인 실행.** v1 분기를 걷어낸 Manager(`0406b14d`)로 같은 pinset에서 격리 M05 e2e를 한 번 더 돌려 `status: passed`를 다시 받았다 — 걷어낸 것이 회귀를 만들지 않았다는 증거다(rebuild는 pinset이 그대로라 불필요했다).

**되돌리는 방법.** v1 pinset으로 재개해야 하면 Manager #323을 revert한다. 그 판단에
필요한 신호는 거부 메시지가 낸다: `pair contract version is unsupported`.

**해제 조건.**

1. 소비자 이행이 먼저다. `apps/api/app/core/config.py`가 v1·v2를 **함께** 읽고, v2에서는
   `source_revision`·`runtime_image_digests` 없이 동작한다. 그 두 값의 downstream
   사용처가 전부 대체되거나 제거된 것을 사용처 열거로 보인다.
2. 1이 병합돼 PinVi API 컨테이너가 **v1 계약 그대로** 정상 기동한다. dual-read이므로
   이 시점에 계약은 아직 v1이다 — 소비자만 앞서 나간다.
3. 그 뒤에 계약을 v2로 재생성한다(`--write`). `map.full`/`map.admin`에서
   `source_revision`이, 최상위에서 `runtime_image_digests`가 사라진다. 나머지 digest는
   그대로다.
4. PinVi 게이트가 v2 계약에 `source_revision`이 **없음**을 단언한다. 되살리면 red가
   되는 것을 변이로 보인다. 그리고 `config.py`를 v1-only로 되돌리면 red가 되는 것도
   함께 보인다 — 소비자와 계약이 한쪽만 움직이면 깨져야 한다.
5. Manager `--rotation-preflight`가 **PinVi 커밋 없이** 새 Map revision을 수용한다.
   실측으로 보인다 — 같은 PinVi revision + 다른 Map revision으로 preflight를 통과시킨다.
6. 그 pinset으로 회전 → rebuild → 격리 M05 e2e가 `status: passed`.
7. 6이 green인 뒤에야 Manager의 v1 분기를 뗀다. **먼저 떼지 않는다** — 현재 pinset으로의
   재개 경로가 즉시 막힌다(Manager 주석이 그 이유를 적는다).

**하지 않는 것.** v1 계약 파일을 지우지 않는다. 파일명이 `-v1`을 담고 있으나 그것은
경로이지 버전 선언이 아니다 — 버전은 문서 안의 `version` 필드다. 경로를 바꾸면 Manager가
읽는 위치와 갈라진다.
