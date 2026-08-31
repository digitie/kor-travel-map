# Map 백로그 정체 — 근본원인 분석과 개선 결정

> 2026-08-31. 사용자 지시("장기 정체의 근본원인 분석 후 개선, 과계약·과결박 유연 수정")로
> 수행. 분석 3인(타임라인 포렌식 / 결박 전수 감사 / 트레드밀 구조) + 적대 리뷰
> 2인(진단 반박 / 완화안 반박)의 5-agent 워크플로우 산출을 종합했다. 적대 리뷰가
> **진단 4건을 반박하고 완화안 4건을 기각**했으며, 이 문서는 살아남은 것만 싣는다.
> 반박된 항목도 §5에 남긴다 — 같은 처방이 다시 제안되는 것을 막기 위해서다.

## 1. 정량 사실 (적대 리뷰 통과분)

- 정체 구간 2026-08-24~31 8일간 두 저장소 비-merge 386커밋. Map 08-27~29 3일의
  35개 PR(#1084~#1121)은 **non-docs 파일 0개** — 전부 M05 terminal 기록이었다.
  단, 같은 3일 Manager는 비-merge 152커밋 중 132건(87%)이 코드였다. 즉 "코드가 안
  나왔다"가 아니라 **엔지니어링이 세리머니 저장소 밖에서 벌어지고 기록만 Map에 쌓였다.**
- M05 계열 terminal pinset은 tasks.md 명시 23개 + journal 4개 = **27개**. committed는
  2건. 실패 phase 분포: `foreign_membership` 6 · `target_not_isolated` 3 ·
  `runtime_setup_admission` 3 · `launcher_safe_result_unavailable` 3 ·
  `driver_contract_failed` 3 · 기타 인프라 phase 9 — **실제 검증 대상인
  `m04_m05_e2e`는 0건.** 후보 예산 전부가 acceptance 본문 도달 전에 소진됐다.
- 4개 candidate(`41be91fe`·`5512ce12`·`b46743ea`·`9b6eab1e`)를 태운 진짜 원인은
  Compose override의 `ports: !reset` **한 줄**이었다(`eca5d08`). acceptance 문서
  스스로 "source와 무관한 정적 결함이므로 source를 바꿔서는 통과할 수 없었다"고
  적었다 — 그 구간의 pair 회전은 증명 가능하게 무용했다. 그리고 **발견 수단은 root
  forensic의 rendered config 열람**이었고, 그 도구(`--forensic-capture`)는 결함 수정
  16시간 뒤에야 명시화됐다(`b67aeb7`).
- head 리터럴(Map 6 + Manager 11)이 `301`을 되돌리게 만들었고(`fa982118`), 봉인
  digest 3지점이 그 다음 층에서 다시 막았다. 08-30~31 이틀이 그 고정을 푸는 데
  들었다(ADR-42/43).

## 2. 근본원인 판정

**정체는 논리적 봉쇄(livelock)가 아니라 반복 단가의 발산이다.** 적대 리뷰가
"livelock/트레드밀" 판정을 반박했다 — `T-VN-FINAL-REBUILD`의 B1~B4는 미래 전칭이
아니라 acceptance **직전 1회 평가**이고, 복구 경로(`pinset 재cut`)가 문서에 명시돼
있으며 실제로 08-26에 그 경로로 committed generation이 만들어졌다. 문제는 도달
가능성이 아니라 **한 사이클의 단가와 정보 산출**이다.

한 사이클 = pair 회전 + 단발 rebuild + one-shot 실행, 산출 = **terminal phase enum
1개**. raw output을 보존하지 않았으므로(`ports: !reset`을 stderr 한 번이면 즉시
볼 수 있었다) 결함 1건 규명에 여러 사이클이 들었고, one-shot 규칙이 실패한 pinset을
영구 소각하므로 사이클마다 3-repo 회전이 필요했다. **단가를 만드는 세 인자:**

1. **관측 결핍** — 실패 시 phase enum 외 아무것도 남기지 않는 규칙. (CONFIRMED)
2. **무조건 소각** — phase-scoped 차단 기계가 registry에 **이미 구현·테스트돼
   있는데**(`BlockedExecution.phase`, `BlockedPinset.matches(phase=)`) 유일한 호출부
   `m05_isolated_e2e.py:306`이 `phase=`를 넘기지 않아 모든 terminal이 무조건
   차단이 됐다. 인프라 실패가 acceptance 실패와 같은 형벌을 받았다. (CONFIRMED —
   배선 누락 한 곳)
3. **값/상태 고정** — head 리터럴 17곳, 봉인 catalog digest의 live 대조 3곳,
   exact-field-set 사본 60곳(`_CONTRACT_FIELDS` 11필드가 5곳 동일 사본). 스키마
   진화 한 걸음이 다층 고정을 순서대로 뚫어야 했다. (CONFIRMED; ADR-42/43이 head와
   digest 층은 이미 해소)

부수 원인(독립 확인): 원장 무결성 — 배리어 해제 조건이 문서 평면화로 삭제된 **다음
날** 그 task가 완료 처리됐다(`6d671ef1` → `b3bbd3a3`). 이것은 과결박의 증거가
아니라 **원장이 삭제에 무방비**였다는 반대 방향 증거다.

## 3. 채택한 개선 (적대 리뷰 통과분만)

| # | 대상 | 변경 | 근거 판정 |
|---|---|---|---|
| I-1 | Manager `m05_isolated_e2e.py:306` | `block_current_execution`에 `phase=` 배선 + `RuntimeExecutionRegistry.blocks(next_phase)`를 `BlockedPinset.matches`와 동형으로 추가. 무조건 차단은 lifecycle 축이 아니라 **phase 집합** `{ledger_claim, m04_m05_e2e}`로 선언 | CONFIRMED — 기계는 있고 배선만 없다 |
| I-2 | Manager forensic capture | 비-production에서 `--forensic-capture` **기본값** 반전. bounded 256KiB stderr → root 0600 private leaf. `_RAW_ENV_NAMES` 스크럽 유지. 규약 문구를 "원문을 읽지 않는다"에서 "원문을 공개 registry·tracked 문서·대화 기록으로 옮기지 않는다"로 축소 | CONFIRMED — `!reset` 사고의 직접 처방 |
| I-3 | Map `tasks-acceptance.md` B1~B3 | 삭제하고 :80-84의 실행 시점 exact-equality에 판정 위임. **B4는 유지** — env/compose/role-ACL 표면은 런타임 대조가 덮지 않는다 | STRENGTHENED (삭제) / REFUTED (B4 포함 삭제) |
| I-4 | Manager harness | active v6 generation manifest의 `map_application_head`·OpenAPI SHA·image ID를 `source_materialization`에서 유도값과 exact 대조 — B1~B3가 주장하던 성질을 처음으로 **기계가** 강제 | 리뷰 1 counter_proposal |
| I-5 | Manager 문서 | `runtime-pin-registry.md:95` "모든 terminal 재실행 금지" → 코드 실제 동작(pre-claim 실패는 같은 pinset 재시도 가능, `5b53730`)으로 정정. `:77-80` "중단·재개 금지" 절도 실동작으로 정정. **registry에서 항목 삭제는 금지** — append-only 감사 성질 유지 | CONFIRMED |
| I-6 | Map 원장 | `MAP-HEALTH-TRANSPORT` B4·`ADMISSION-TERMINAL` C3(동일 사건 중복 부기)를 `T-VN-M05-ACTIVATION`의 조건으로 접고 두 task를 완료 이관. 25→21 | CONFIRMED |
| I-7 | Map 게이트 | (a) tasks.md에서 체크박스 줄 삭제 시 tasks-done.md 대응 추가 없으면 실패, (b) `[x]` 항목의 hex 인용은 세 저장소 중 하나에서 해석되거나 file:line일 것, (c) live `journal.md`·`resume.md`를 220KB 게이트 대상에 추가 + `check_journal_update.py`가 당월 archive shard 기입 인정 | CONFIRMED ×3 |
| I-8 | Manager lint | Map 로컬 체크아웃(ADR-044)의 emitter frozenset과 Manager frozenset 동일성 교차 대조 테스트 — 계약-as-data 4단계 중 **1단계만** | CONFIRMED (축소판) |
| I-9 | Manager parser | result/receipt 4개 parser만 `forbid_extra=False` — fence는 exact 유지. receipt 무결성은 `payload_sha256`이 이미 결박 | 메커니즘 CONFIRMED (비용 산정만 정정) |
| I-10 | PinVi | `test_tvn40_migration_immutability.py`의 exact 파일 목록 → 기존 파일 digest 불변 + 신규 추가 허용. T-349 국소 차단 해제 | CONFIRMED (국소 결함으로 재분류) |

## 4. M03과의 관계

`301`은 `chain/301-carrier`(PR #1125)에서 착륙 중이다(통합 실패 6→5→2→1건, 남은
1건도 fixture 결함). M03 잔여(child command 발급)는 `302` migration이 선행하며 별도
설계 결정 3건이 필요하다 — 이 보고서의 범위 밖, `docs/resume.md`가 소유한다.

## 5. 기각된 처방 (재제안 방지)

| 처방 | 기각 사유 |
|---|---|
| B4 삭제/기록 강등 | B4만이 env·compose·role/ACL 표면을 덮는다. 실측상 B4는 디버깅을 막은 적 없다(08-27~29 Manager 132건 코드 커밋) — 강제한 것은 "디버깅 후 이전 journal 재사용 금지"뿐 |
| execution identity에 `attempt_ordinal` 추가 | identity의 제3자 재유도 가능성이 죽고 3-repo lockstep이 하나 더 생긴다. phase-scoped 차단이 같은 문제를 결박 추가 없이 푼다 |
| ledger claim을 `m04_m05_e2e` 직전으로 이동 | claim과 본문 사이에 durable mutation(Idempotency-Key POST, secret 발급)이 실재한다. claim 경계 불변식은 코드에 명시돼 있다 |
| `KTDM_DEPLOYMENT_ENVIRONMENT` 3단계 terminal_policy | n150 설치본 shim은 `/opt` `.env`(production)를 읽는다 — 이미 08-19에 "사실오류"로 공식 정정된 전제의 재탕. 환경 축이 아니라 phase 축을 쓸 것 |
| v6 identity에서 Manager revision 제거 | "verifier A의 거부"와 "verifier B의 거부"가 붕괴해 지금 증상이 방향만 바뀐 채 재발한다 |
| registry에서 pre-mutation terminal 항목 제거 | 삭제 API가 생기는 순간 "이 원장은 삭제된 적 없다"를 다시는 주장할 수 없다. 문서상 지위만 legacy audit으로 정정 |
| terminal raw stderr를 세션/대화로 직접 판독 | 해당 프로세스 env에 PinVi 비밀값이 실린다. 디스크 0600 leaf까지만 |
| terminal 기록 PR을 ndjson 배치로 | 사이클에서 가장 싼 산출물의 최적화 — 병목은 실행당 정보 산출이다 |
| 적대 리뷰 요건 완화 | 실측 반대 — 08-28 리뷰가 자가복구의 진단 삭제, 감사 fail-open, root 권한 축소 3건 등 실결함을 냈다 |

## 6. 확인하지 않은 것

- I-1~I-9 적용 후 실제 사이클 단가의 변화 — 다음 M05 실행에서 측정해야 한다
- 분석가들의 커밋 분류 비율(13.9% 등)은 분류 스크립트 미제출로 검증 불가 판정 —
  이 문서는 그 수치를 의사결정 근거로 쓰지 않았다
- `tasks-acceptance.md`의 미해석 SHA 2건(`1f20ab36`·`02168ad5`)의 원 출처
