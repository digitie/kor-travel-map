# tasks-acceptance 아카이브 — M05 계열 (완료)

> `T-VN-M05`와 `T-VN-M05-ACTIVATION`의 해제 조건 원문이다. 두 절 모두 닫혔고,
> live 문서 [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB
> (225,280 bytes) 상한을 넘겨 규약 §8대로 분리했다(2026-09-11).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다.
> 두 절에는 상대 링크가 없어 재기준화할 것도 없었다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-M05

```markdown
- [~] **T-VN-M05 — provider 발행 시 중복 판정** (결정 4 후단). 수동 Feature와 같은 실체를
  provider가 발행하면 dedup 후보로 올리고 **자동 병합하지 않는다.** admin이 병합/유지/수동본
  폐기를 고른다. 2026-08-21 사용자 선택은 paired cutover이며, ADR-097과
  `t-vn-m05-manual-provider-dedup-design-2026-08-21.md`가 immutable evidence·service event/ack·첫
  consumer rebind 계약을 소유한다.
```

**2026-09-07 전수 조사 — 판정 문단이 없다.**

이 절은 복원 블록만 있고 "무엇이 충족이면 닫히는가"를 적은 문단이 없다. 같은 형태의
§T-VN-M03이 실제로 판정돼 충족 처리된 선례가 있으므로 형식 자체가 무효인 것은
아니지만, ADR-097 §후속 4항목을 이 절로 옮겨 판정 가능한 조건으로 만드는 것이
선행이다.

**2026-09-07 — 조문을 세운다(ADR-097 §후속 + 설계 문서에서 이관).**

새로 지어낸 조건은 없다. 각 항목 끝에 출처를 밝힌다. ADR-097 §후속은 넷이고, 그중
"두 적대 리뷰 + isolated live E2E 뒤에만 completion receipt"의 **completion 발행은
`T-VN-M05-ACTIVATION`이 소유한다** — 이 절이 다시 세지 않는다(2026-09-04 중복 정리와
같은 규율).

```markdown
- [x] **M05-1 — evidence/delivery 스키마와 전용 실행 경계가 있다.**
  `ops.manual_provider_dedup_cases`·`..._resolutions`와
  `ops.feature_reference_reconciliation_{events,acks,subscriptions,leases}` 여섯 relation,
  전용 procedure(candidate 발행 / decision 확정 / lease / ack / subscription provision /
  case list·read), append-only 트리거, 네 M05 role의 two-phase bootstrap, 그리고
  case·resolution·event·ack·subscription의 canonical JSONL count+SHA-256 backup root가
  배포 baseline에 있다. (ADR-097 §후속 1 전단)
- [x] **M05-2 — restore가 이 evidence를 복원 가능한 형태로 검증한다.** (2026-09-08 충족)
  ownership/ACL/procedure repair → catalog preflight → evidence root 재계산 → live lease
  holder/expiry 무효화 → subscription별 immutable ack의 **연속 prefix**에서 `acked_through`
  재구축까지가 실행 가능해야 하고, 불연속 ack와 event/hash 불일치는 fail-loud여야 한다.
  (ADR-097 §후속 1 후단)
- [x] **M05-3 — candidate가 운영 경로에서 발행된다.** (2026-09-07 충족, #1189)
  manual origin Feature와 provider Feature를 **따로** 읽는 전용 detector가 `THRESHOLD_MANUAL`
  이상 쌍을 점수와 무관하게 `candidate`로만 기록하고(자동 병합하지 않는다), detector input
  count와 대규모 scope의 blocking 사실을 case receipt에 남긴다. detector relation에 대한
  직접 INSERT/UPDATE 권한은 executor procedure만 갖는다. (설계 §후보 탐지)
- [x] **M05-4 — Map 계약면이 동결됐다.**
  admin `GET /v1/admin/manual-provider-dedup-cases`·`GET .../{case_id}`·
  `POST .../{case_id}/decisions`와 service
  `GET /v1/service/feature-reference-reconciliations`·`POST .../{event_id}/acks`가
  구현·동결되고, `merged`/`manual_retired`는 DB session 생성 **전에** destructive
  kill-switch를 통과하며 stale 요청은 어떤 M05 행도 쓰지 않고 409를 durable하게 남긴다.
  (ADR-097 §후속 2 · 설계 §admin 판단과 동시성)
- [x] **M05-5 — Map admin UI가 판정을 안전하게 받는다.** (2026-09-08 충족, #1193)
  default `kept`, provider survivor 고정, destructive confirmation과 비어 있지 않은 reason,
  principal별 unacked age를 보여주며 generic dedup 화면을 재사용하지 않는다.
  (설계 §paired rollout과 검증 4)
  전용 라우트 `src/app/admin/manual-provider-dedup/`가 실재하고, `decision` 초기값이
  `"kept"`, survivor는 `decision === "merged"`일 때만 실린다(계약이 교차필드로 **양방향**
  막는다 — `manual_retired` + survivor도 422다). reason 공백과 확인 문구 불일치가 제출을
  막고, case를 바꾸면 `key`로 remount해 이전 판정이 남지 않는다.
- [x] **M05-6 — 첫 consumer가 durable receipt와 exact vendor를 갖는다.**
  immutable `delivery_attempt`(blocked|applied), unique final applied receipt, impact row가
  있고 exact vendor 핀이 걸려 있다. (ADR-097 §후속 3)
- [x] **M05-7 — isolated Map/consumer live UI E2E가 통과한다.**
  격리 실행에서 M05 UI assertion이 통과하고 그 사실이 서명된 attestation에 실린다.
  (ADR-097 §후속 4 전단)
```

**2026-09-07 실측 판정.**

| 조건 | 상태 | 근거 |
|---|---|---|
| M05-1 | **충족** | 여섯 relation이 `alembic/baseline/schema.sql`에 존재. `0234`/`0235`는 `300_schema_baseline`으로 접혔다 |
| M05-2 | **미충족** | `scripts/docker-restore.sh`(8줄)·`docker-restore-verify.sh`(7줄)가 본문 없이 `restore is disabled: backup artifacts are audit-only under the 300 baseline`을 찍고 `exit 2`한다. 두 스크립트에 `manual_provider`·`reconciliation`·`acked_through` 문자열이 **없다** |
| M05-3 | **미충족** | `record_manual_provider_dedup_candidate`의 **프로덕션 호출자 0건**. 등장하는 곳은 마이그레이션과 카탈로그 preflight 문자열뿐이다 — 프로시저는 있는데 부르는 코드가 없다 |
| M05-4 | **충족** | 5개 엔드포인트가 `openapi.json`에 동결 |
| M05-5 | **미충족** | `manual-provider-dedup`이 자동생성 `src/api/types.ts`에만 나온다. `src/app/admin/` 아래 라우트가 없다 |
| M05-6 | **충족** | PinVi `feature_reference_reconciliation` 세 테이블(delivery_attempts / applied_receipts / impacts) 실재 |
| M05-7 | **충족** | 2026-09-04 `e2e025`와 2026-09-07 `/root/pairv2-e2e-03` 모두 `status: passed` |

**남은 셋의 성격이 서로 다르다.**

- **M05-2**는 이 절의 고유 결함이 **아니다.** restore 비활성은 300 baseline 정책이고
  그 정책은 다른 절이 소유한다. 이 조건은 그 정책이 바뀌기 전에는 판정할 수 없다 —
  `T-VN-M02`의 purge가 restore proof에 걸린 것과 같은 구조다.

  **다만 "정책이 바뀌면 저절로 충족된다"는 뜻이 아니다(2026-09-08 정정).** 그 문구가
  잔여 작업량을 말하지 않아 오해를 낳았다. 실측하면 갈린다:

  | 축 | 상태 |
  |---|---|
  | backup | **있다.** `docker-backup.sh`가 M05 relation을 같은 repeatable-read 스냅숏에서 canonical JSONL + SHA-256으로 담는다(M05-1 충족의 근거) |
  | restore | **없다.** `docker-restore.sh`(8줄)·`docker-restore-verify.sh`(7줄)는 본문 없이 `exit 2` |
  | M05-2가 요구하는 다섯 단계 | **어디에도 없다.** `scripts/`·`docker/` 전체에서 `acked_through` 0건, "catalog preflight" 0건, restore 경로에 M05 relation 0건 |

  즉 정책이 풀려도 M05-2는 참이 되지 않는다. 그 정책은 "복구 경로를 만들 것인가"를
  열 뿐이고, M05-2가 요구하는 것은 그 위에 얹는 **M05 전용 복구 검증**이다 —
  전부 새로 지어야 하는 코드다. 정확한 상태는 "정책이 선행이고, 정책이 풀려도
  M05 전용 검증을 새로 지어야 한다"이다.
- **M05-3**은 실제 구현 공백이다. 계약·스키마·ACL은 다 있는데 **탐지기를 부르는 곳이
  없어** 후보가 한 건도 발행되지 않는다. 이것을 채우지 않으면 M05의 요지(자동 병합하지
  않고 후보로 올린다)가 운영에서 한 번도 일어나지 않는다.
- **M05-5**는 UI 구현 공백이다. M05-3이 없으면 보여 줄 case도 없으므로 **M05-3이 선행**한다.

**착수 순서**: M05-3 → M05-5 → (정책이 바뀌면) M05-2.

**2026-09-07 — M05-3 충족. 무엇을 고쳤나.**

M05-3이 미충족이던 이유는 "구현을 안 했다"가 아니라 **구현할 수 없었다**였다.
detector executor가 EXECUTE할 수 있는 routine은
`record_manual_provider_dedup_candidate` 하나뿐인데 그것은 *이미 아는* 쌍을 기록한다.
쌍을 찾으려면 manual origin을 증명하는 두 표를 읽어야 하는데, `runtime_privileges.py`의
`_MANUAL_FEATURE_TABLE_ACL`이 `ktm_feature_dagster_runtime`을 **이름으로** REVOKE한다.

| relation | dagster 읽기 | 근거 |
|---|---|---|
| `feature.features` | 가능 | `_CORE_FEATURE_GRANTS` |
| `provider_sync.*` 넷 | 가능 | `_ORDINARY_SCHEMA_PRIVILEGES['provider_sync']` |
| `feature_creation_origins` | 불가 | `_MANUAL_FEATURE_TABLE_ACL` |
| `manual_feature_identity_claims` | 불가 | 동일 |

migration 304가 그 공백만 여는 `feature.list_manual_provider_dedup_detector_manuals`를
추가한다(STABLE SECURITY DEFINER, EXECUTE는 detector executor만). 판정만 돌려주고
생성 command·principal·actor·시각은 돌려주지 않는다. **ADR-090 경계는 딱 그만큼
움직인다** — 새로 드러나는 사실은 "어느 Feature가 manual origin인가"이며 그 이상은 아니다.

**M05-3이 어떻게 채워졌나**(판정 자체는 위 조문 목록이 소유한다 — 체크박스를 두 곳에
두면 한 곳만 갱신된다):

  manual origin은 304의 reader로, provider는 `ST_DWithin(f.coord_5179, …)`로 **따로** 읽고,
  ADR-016 가중치로 낸 `THRESHOLD_MANUAL` 이상 쌍을 점수와 무관하게 candidate로만
  기록한다(`classify_decision()`·`select_master()`를 부르지 않는다). detector input
  count와 blocking 사실은 case receipt에 싣고, **후보가 0건이어도** 훑은 범위를
  `DetectionOutcome`으로 돌려준다. detector relation 직접 INSERT/UPDATE 권한은
  종전대로 executor procedure만 갖는다.

**당시 남아 있던 것은 스케줄이었다.** 프로시저의 멱등성이 미해결 case에만 성립해
admin이 `kept`로 판정한 쌍이 다음 실행에서 새 case가 됐다. `T-VN-M05-RELITIGATION`이
migration 305의 `decision_fingerprint`로 그것을 막고 일간 스케줄(04:20 KST, 기본
`STOPPED`)을 붙였다 — 2026-09-08 해소.

**2026-09-08로 둘 다 닫혔다.** M05-5는 전용 라우트로(#1193), M05-2는 아래 A~D단계로.
2026-09-07의 "정책이 바뀌기 전에는 판정할 수 없다"는 판정 자체가 틀렸다 — 정책을 바꾸지
않고도 조문이 요구하는 것을 지을 수 있었다. restore/swap은 여전히 닫혀 있다.

**2026-09-08 — M05-2 충족. 소유자 판정으로 300 baseline restore 정책부터 검토했다.**

조사가 앞선 판정 둘을 뒤집었다.

1. **"전부 새로 지어야 하는 코드다"는 틀렸다.** 다섯 단계는 커밋 `b2543d68` 직전에
   거의 조문 그대로 있었고 그 커밋이 지웠다(`docker-restore-verify.sh` 416줄 → 7줄,
   `docker-restore.sh` 442줄 → 8줄, `docs/backup-restore.md` 1020줄 → 94줄).
2. **"정책 근거가 스크립트 두 줄이 전부다"도 틀렸다.** `docs/backup-restore.md`,
   H46H 설계 리포트, 저널에 있고 **2026-08-26 소유자 결정**("이전 revision/기존 DB
   restore는 release gate가 아니다")까지 남아 있다.

**지배적 손실은 사고가 아니라 계획된 재구축이었다.** `pinvi-pair rebuild-pinned`가
Map revision이 바뀔 때마다 application DB를 `dropdb --force` 후 재생성하고, `.env` 값
하나가 바뀌어도 그 경로를 탄다. 그런데 manual-feature writer는 2026-09-05T20:27:59Z에
prod에서 켜졌고, **그 evidence를 담은 backup이 n150에서 한 번도 만들어진 적이 없었다.**
실측 당시 유일한 `map_application` 백업은 `0232_tvn37d_notice_empty_range` — 300
baseline보다 **앞선 세대**였다.

**restore를 켜도 이 손실은 막히지 않는다** — rebuild lifecycle 문제이지 restore 문제가
아니다. 그래서 evidence를 담는 것(A)이 선행이다.

| 조문 요구 | 상태 | 근거 |
|---|---|---|
| ownership/ACL repair | **닫힘(C)** | 리허설이 소유권을 벗기지 않고 복원하고, 복원본 카탈로그가 운영 DB와 바이트 단위로 같음을 실측했다(Manager #334) |
| catalog preflight | **닫힘(C)** | 같은 카탈로그 지문이 relation·routine·schema의 소유자·ACL·`prosecdef`·extension을 덮는다 |
| evidence root 재계산 | **닫힘(A+B)** | 열 relation을 하나의 스냅숏에서 canonical JSONL로 뽑고(#1194), manifest의 행 수·SHA-256과 대조한다 |
| 불연속 ack·event/hash 불일치 fail-loud | **닫힘(B)** | 다섯 종을 실패로 보고한다 |
| live lease holder/expiry 무효화 | **닫힘(D)** | `evidence_restore.invalidate_leases()` |
| 연속 prefix에서 `acked_through` 재구축 | **닫힘(D)** | `evidence_restore.rebuild_acked_through()` |

**초안에서 이 항목을 `[x]`로 적었다가 되돌리고, D단계를 지어 다시 닫았다. 조문을 다시
읽으니 내 근거가 두 요구를 비껴갔다.**

초안은 "`lease`를 evidence root에 담지 않으므로 fencing token이 되살아날 자리가
없다"고 적었다. 그것은 **번들에 대해서만** 참이다. `pg_dump`는 스키마 전체를 담으므로
**복원된 DB에는 `ops.feature_reference_reconciliation_leases`가 그대로 살아 돌아온다** —
dump 시점의 `worker_id`·`lease_epoch`·`lease_expires_at`을 달고. 조문이 말하는
"live lease holder/expiry 무효화"는 바로 그 행을 가리키지 번들을 가리키지 않는다.
무효화하지 않으면 복원 직후 죽은 worker의 fencing token이 유효해 holder가 둘이 된다.

`acked_through_sequence`도 같은 행에 있다(`leases`의 컬럼이지 `subscriptions`의 것이
아니다). B단계는 그 값을 Python으로 **계산**하지만 복원된 DB에 **쓰지 않는다.** 조문은
"재구축"을 요구한다.

즉 남은 둘은 과결박이 아니라 **진짜 안전 요구**다 — split-brain과 cursor 후퇴를 막는다.
조문을 완화할 일이 아니라 지을 일이었다.

**D단계(`kortravelmap.infra.evidence_restore`)가 그 둘을 복원본 DB에 대고 닫는다.**
`repair_restored_database()`가 preflight → cursor 재구축 → lease 무효화를 순서대로 한다.
`apply=False`면 아무것도 쓰지 않고, **preflight가 실패하면 수리하지 않는다**(검증되지
않은 상태를 고치는 것은 손상을 되돌릴 수 없게 확정하는 일이다).

무효화는 holder와 만료를 지우는 데서 그치지 않고 `lease_epoch`을 **올린다.** 복원본은
원본의 사본이라 epoch이 그대로면 원본을 향해 돌던 worker의 토큰이 복원본에서도 유효하다.
n150 실측으로 잰다 — 무효화 뒤 옛 `(worker_id, lease_epoch)`로 부른 진짜 ack 프로시저가
`lease_conflict`를 돌려주고 cursor가 밀리지 않는다.

preflight는 행 그래프에 더해 **트리거가 켜져 있는지**를 본다. `--disable-triggers` 복원은
append-only 보호를 지우지 않고 꺼 둔 채로 남기므로 행도 다 있고 카탈로그에 트리거도 있어
겉보기에는 멀쩡하다. 이름을 열거하지 않고 필수 relation에서 유도한다(DO NOT 15).

**n150 실측이 잡은 것.** 좌표를 유효 범위 밖으로 미는 index, 물려받은 provisioning에
기댄 테스트, ack가 holder를 놓아 주지 않는다는 사실, 그리고 **내가 지어낸 컬럼
이름**(`origin.command_id` — 실제는 `creation_command_id`). mutation 열 축은 전부
RED다(epoch·holder·expiry·prefix·drift·gate·trigger·dryrun·missing·claim). 그중 둘은
처음에 공허했다 — dry-run 단언이 롤백되는 트랜잭션에서 돌아 몰래 쓰는 구현을 못 잡았고,
연속 prefix 축은 정상 이력에 구멍이 없어 `max(...)`와 갈리지 않았다. 둘 다 고쳤다.

**부수로 드러난 순서 의존.** D단계 모듈이 알파벳 순으로 먼저 돌면서 정본 구독을 만들자
기존 M05 테스트의 두 단언이 조용히 무의미해졌다(`P0002` → `23514`, `provisioned` →
`already_provisioned`). 구독은 append-only singleton이라 그 성질들은 pristine DB에서만
관찰 가능하다. 관찰과 구독 생성을 session scope fixture 하나가 소유하게 바꿔 순서에
기대지 않게 했다 — 세 배치 순서에서 36건 모두 통과한다.

**실행이 아니면 못 찾았을 결함 셋**(전부 C단계에서, n150 실측으로):
`--no-owner --no-privileges`가 질문 자체를 불가능하게 하고 있었고, `search_path`
미고정으로 PostGIS 함수 495건이 거짓 양성이었으며, ACL 미정규화로 1건이 더 남았다.
거짓 양성은 진짜 drift를 덮으므로 없는 것보다 나쁘다.

**주장하지 않는 것.** 이 검증은 artifact 무결성, 복원된 카탈로그 정합, 그리고 복원본의
M05 delivery 상태까지다. 복원 자체(`pg_restore` 실행)도, RustFS 실물도, evidence root 밖
relation도, **rebuild 경계를 넘는 데이터 연속성**도 다루지 않는다 — 그 연속성은 이 절이 아니라 backup 주기화(`T-VN-H43`, 소유자 지시로 보류)와
off-box 사본(`T-VN-H49-OFFBOX`)이 소유한다. restore/swap은 여전히 닫혀 있고 이 작업이
그것을 열지 않는다.

## T-VN-M05-ACTIVATION

> 이 task는 `6d671ef1` 평면화 **이후**에 만들어져 복원할 원문이 없다. 아래는
> `docs/tasks.md`의 해당 줄이 이미 산문으로 서술하고 있는 재개 조건을 판정 가능한
> 형태로 옮긴 것이며, 새로 지어낸 조건은 없다.
>
> 종전에 이 task는 해제 조건이 **하나도 없는 채로** 게이트를 통과했다. 게이트가 이름
> 접두사만 보고 부모 `T-VN-M05`가 덮는다고 판정했는데, 그 섹션은 provider dedup
> 이야기이고 activation과 아무 관계가 없다.

```markdown
- [ ] **A1 — 회전은 원자적이다.** 재개는 새 Map revision·새 PinVi provenance·새 Manager
  source를 trusted `ktdctl pin rotate-pair`로 **함께** 결박한 새 pinset에서만 시작한다.
  terminal로 차단된 pinset·source pair·Manager source·output leaf는 재실행하지 않는다.
- [ ] **A2 — 실행은 단 한 번이다.** 회전 뒤 trusted `run-pinned-rebuild-once`가 current
  public generation을 만든 다음, 새 root-owned leaf에서 n150 isolated M04/M05 launcher를
  정확히 한 번 실행한다.
- [ ] **A3 — 승격 전제 셋을 모두 만족한다.** 최신 CI green · 전문 적대 리뷰 두 건 GO ·
  terminal 아님. 셋 중 하나라도 아니면 M04/M05 live acceptance attestation을 승격하지 않는다.
  성공 종료 receipt는 완료 이관된 `T-VN-M05-MAP-HEALTH-TRANSPORT`(Map `/health` 통과)와
  `T-VN-M05-ADMISSION-TERMINAL`(admission 경계 통과)의 관측 의무를 **함께 봉인한다** —
  같은 사건 하나를 세 task가 각자 기다리던 중복 부기를 여기 하나로 접었다.
- [ ] **A4 — 경계는 공개 API만 쓴다.** pinning·pair 결박·one-shot 계약은 Docker Manager
  trusted `ktdctl`과 `runtime-pins`·`pinned-runtime/generation` 공개 API만 사용한다.
  PinVi isolated Compose는 Manager가 transaction·pinset·세 source revision에 결박해 private
  `0600`으로 발급한 admission receipt를 no-follow 검증할 때만 허용하며, legacy 환경변수
  marker·수동 Compose는 권한이 아니다.
```

AC: A1~A4가 모두 참인 단일 실행에서 M04/M05 live acceptance attestation이 승격돼야 한다.
공개 registry의 고정 phase가 `runtime_setup`인 동안에는 이 task가 열려 있다.

### `docs/tasks.md`에서 이관한 재개 조건 원문 (2026-09-04)

> `docs/tasks-rule.md` §5는 "task당 위치는 하나 — `docs/tasks.md`에 한 줄, 해제 조건은
> `docs/tasks-acceptance.md`에 한 절. 본문을 중복하지 않는다"고 정한다. `docs/tasks.md`의
> 이 항목은 한 줄 규약을 어긴 1233자 산문이었고, 그 내용은 이 절이 소유해야 할
> 판정 근거·재개 조건이었다. 아래는
> 그 본문을 **원문 그대로** 옮긴 것이다 — 요약·축약·삭제 없음(2026-09-04 이관).

`a3f6a8f3…`·`22563762…`·`c700bd2e…`·`fa28a6e7…`·`5512ce12…`·`41be91fe…`·`b46743ea…`·`5ad3b08c…`·`5592a1d4…`에 이어 Map `35a43317…`·PinVi `fed16a5c…`·Manager `eed1920…`·pinset `82850711…`도 trusted `ktdctl pin rotate-pair`, 단발 pinned rebuild, registry/public generation `match` gate 뒤 n150 isolated M04/M05 launcher를 정확히 한 번 실행해 terminal로 차단됐다. 공개 registry의 고정 phase는 `runtime_setup`이며 HTTP·컨테이너·환경·output leaf 원문은 열지 않는다. 모든 terminal pinset과 각 source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는 isolated runtime setup의 ordinary exception을 raw detail 없이 더 좁은 allowlist phase로 수렴시켜 다음 immutable candidate의 보정 범위만 좁힌다. 이후 pinning·pair 결박·one-shot 계약은 Docker Manager trusted `ktdctl`과 `runtime-pins`·`pinned-runtime/generation` 공개 API만 사용한다. PinVi isolated Compose는 Manager가 transaction·pinset·세 source revision에 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만 허용하며, legacy 환경변수 marker·수동 Compose는 권한이 아니다. 재개 시에만 새 Map revision·새 PinVi provenance·새 Manager source를 atomic `pin rotate-pair`로 함께 결박한다. 회전 뒤에는 trusted `run-pinned-rebuild-once`가 current public generation을 만든 후 새 root-owned leaf에서 한 번만 실행하며, 최신 CI·전문 적대 리뷰 두 건·terminal 아님을 모두 만족해야 M04/M05 live acceptance attestation을 승격한다.

**2026-09-07 전수 조사 — 원장이 두 pinset 전 값을 현재형으로 적고 있었다.**

`docs/tasks.md`가 인용하던 식별자는 전부 `e2e025`(pinset `e6b52db4`, Manager
`b3217edc`, m04 `f08620a9…`, m05 `37320bb5…`, provenance `25a80946…`)의 것이었다.
그 실행 자체는 2026-09-04에 실제로 있었고 여기 기록으로 남긴다 — 다만 **현재가
아니다.**

현재 승격 후보는 `T-VN-PAIR-V2` §6·§7이 만든 실행이다:

| | e2e-02 | e2e-03 |
|---|---|---|
| pinset | `b229446a` | `b229446a` |
| Manager | `d36847e2` | `0406b14d` |
| m04 attestation | `293bb31f…` | `950762d6…` |
| m05 attestation | `60ad8168…` | `ac818411…` |
| status | passed | passed |

둘 다 정당하다 — Manager 기계는 execution identity별 one-shot이고 두 실행은 서로 다른
execution identity를 가졌다(각각 `c5791dfd…` 이전/이후 rebind).

**승격은 문서 행위가 아니다.** PinVi의 서명 activation receipt 발급·배포
(`pinvi/scripts/m05_activation_receipt.py`)이고 신뢰근거는
`pinvi/contracts/pinvi-m05-activation-receipt-trust-v1.json`이다. 기계가 강제하므로
"승격했다"고 적는 것만으로는 아무것도 승격되지 않는다.

**소유자 판정.** 위 두 실행 중 어느 것을 승격 근거로 삼는가(또는 현 Manager
`0406b14d`에서 한 번 더 받는가).

**2026-09-07 소유자 판정 — 승격 정의를 바꾼다. A1~A4를 기계가 실제로 강제하는 것에 맞춘다.**

바로 위 "승격은 문서 행위가 아니다"가 가리키던 경로가 **isolated scope에서는 존재하지
않는다**는 것이 적대 리뷰 P0로 드러났다. `m05_activation_receipt.py`는 `--scope`에
isolated를 받지 않고, attestation version 4와 isolated 필드는 staging/production
스키마에서 거부되며, 요구 증거 7종 중 `restore.json`·`reviews.json`이 격리 leaf에
없고, 서명은 vendored trust anchor 키가 아니다. `_attestation`의 isolated 분기는 **어느
진입점에서도 도달할 수 없는 死코드**이고, 그것을 덮는다는 유일한 테스트는 소스 문자열
grep이었다.

소유자가 **정의 변경**을 택했다. 다만 "원장에 적는다"로 바꾸면 위 P0가 무효라고 지목한
바로 그 상태가 되므로, **재계산 가능한 대조**로 정의한다.

### 승격의 새 정의

> `ktdctl`이 설치한 Manager의
> `scripts/m05_isolated_e2e.py --verify-leaf <leaf>`가 **exit 0**을 내고, 그 검증
> **receipt의 경로와 sha256**을 이 절에 기록한다.

**2026-09-08 개정(소유자 승인).** 종전 문구는 "그 **출력**을 이 절에 기록한다"였다.
그런데 `--verify-leaf`는 아무것도 쓰지 않았으므로, 승격 근거가 **사람이 옮겨 적은
문장**으로만 남았다 — 위 P0가 무효라고 지목한 바로 그 상태("기계 증적 없이 사람이 옮긴
문장")가 정의를 고치는 과정에서 검증 **결과** 쪽에 그대로 재생산됐다.
`T-VN-M05-VERIFY-RECEIPT` V3가 그것을 지적했고, 두 문장이 서로를 무효화한 채 남아
있었다(한쪽은 옮겨 적으라 명령하고 한쪽은 옮겨 적기가 사라져야 한다고 했다).

개정 근거 셋:

1. **정의의 의도를 더 잘 지킨다.** "재계산 가능한 대조"를 택한 이유가 옮겨 적은 문장을
   배격하는 것이었는데, 출력 텍스트 전사는 그 배격 대상 자체다. receipt sha256은 옮겨
   적을 수 없다 — 위조하려면 root-owned 0600 파일을 만들어야 한다.
2. **V4가 안전을 보장한다.** receipt는 통과 조건이 **아니므로**(`--verify-leaf`가 그
   존재를 보지 않는다) 인용해도 "receipt를 만들어 두면 승격된다"가 되지 않는다.
3. **재현 가능성이 는다.** 출력 15줄은 pin이 움직이면 무엇과 대조한 것이었는지 말하지
   못한다. receipt는 pinset·Map/PinVi revision·binding의 Manager revision·claim 이름을
   값으로 들고 있다.

그 명령이 보는 것(전부 지금 다시 계산할 수 있는 것뿐이다):

| | 검사 |
|---|---|
| L0 | leaf 루트와 **증적 파일의 부모 디렉터리들**이 검증기를 돌리는 특권 신원 소유의 정확 0700이고 symlink가 아니다 — leaf 안 **전체**를 재지는 않는다(그 잔여는 L0b가 진다) |
| L0b | 일회용 PinVi 체크아웃이 leaf 안에 남지 않았다 (`disposable_run_worktree_retained`) — 남으면 L0이 재지 않는 임의 모드 트리가 leaf 안에 있다 |
| L1 | harness 이름 / `status=passed` / `phase=completed` |
| L2 | 세 evidence 파일의 SHA-256을 **다시 계산**해 `result.json`이 적은 값과 대조 (O_NOFOLLOW·정확 0600·nlink 1·dev/ino 재확인으로 읽고, 해시한 그 바이트를 그대로 파싱) — **세 줄로 찍힌다** |
| L3 | pinset: attestation == result == 살아 있는 registry |
| L5 | execution identity: attestation == result, 그리고 registry(`current`+`history`)의 **한 binding**이 그 identity·현재 pinset·Map·PinVi revision을 동시에 들고 있다 |
| L4 | Manager source revision: attestation == result == **그 binding**의 값 (설치본과의 일치는 `is_installed=`로 보고만) |
| L6 | provenance의 Map·PinVi revision == pinned revision (**둘 다** 출력에 찍는다) |
| L6b | provenance가 **이 실행의 것**이다 — `execution_identity_sha256`·`manager_source_revision`·`pinset_sha256`·`transaction_id` 넷이 `result.json`과 같다. `transaction_id`는 실행마다 `secrets.token_hex(16)`이라 **예측 불가**다 |
| L7 | `m04_server_side_chain_verified` |
| L7b | m05 attestation payload의 `m04_attestation_sha256`이 `result.json`의 그 값과 같고 hex다 — L2가 그 값을 재계산해 대조하므로 M04 증적이 사슬 안에 들어온다 |
| L9 | leaf 값에서 재계산한 ledger claim이 root-only 0700 ledger에 실재한다 |
| L8 | pinset이 terminal 차단이 아니고, **leaf 자신의** execution identity에 **무조건**(`phase is None`) 소각 기록이 없다 — scoped 기록은 소각이 아니고, `current`의 소각은 보지 않는다 |

행 순서는 프로그램 출력 순서 그대로다(L5가 L4보다, L9가 L8보다 먼저 찍힌다).
L2가 파일 셋에 대해 세 줄이므로 **출력은 leaf당 15줄**이다.

**재현 절차.** 호스트 `n150`. `ktdctl`이 설치한 트리에서 그대로 실행한다:

```
sudo /opt/kor-travel-docker-manager/backend/.venv/bin/python     /opt/kor-travel-docker-manager/scripts/m05_isolated_e2e.py --verify-leaf <leaf>
```

`<leaf>`는 `/root/pairv2-e2e-03`·`/root/pairv2-e2e-02`. 검증기는 `KTDM_RUNTIME_PINS_FILE`/
`KTDM_RUNTIME_EXECUTIONS_FILE`이 없을 때 `/var/lib/kor-travel-docker-manager*`의 registry를
읽는다 — env로 갈아끼울 수 있으므로 **환경을 비운 채** 실행해야 위 출력과 같은 것을 본다.
검증기 자신의 revision은 `/opt/kor-travel-docker-manager/.ktdm-source-revision`이다.

**서명은 근거가 아니다.** 드라이버는 실행마다 `openssl genpkey`로 Ed25519 키를 새로
만들어 서명하고 실행 종료와 함께 지운다 — 공개키가 어디에도 남지 않아 사후 제3자
검증이 불가능하다. 서명이 봉인하는 것은 생성 시점의 내부 정합뿐이다. 근거는 셋이다:
root-owned `0600` leaf, 해시 사슬, 살아 있는 registry와의 일치.

**pin이 움직이면 같은 leaf가 다시 통과하지 않는다** — 그것이 이 정의가 문서 문장과
다른 점이다.

### A1 — 문구를 정정한다

원문은 "새 Map revision·새 PinVi provenance·새 Manager source를 `pin rotate-pair`로
**함께** 결박"이라고 적는다. 그런데 승격 후보 e2e-03이 쓴 Manager `0406b14d`는
03:11의 `rotate-pair`(그것이 결박한 Manager는 `205fbf35`)가 아니라 **07:08의
`pin rebind-execution`**이 결박했다.

rebind는 회피가 아니라 **trusted Manager release 업그레이드의 표준 경로**다 —
`pin verify`가 `manager_drift`를 보고 스스로 rebind를 안내하고, rollback/rotate-pair를
쓰면 불필요한 source SHA 변경을 강제한다. A1이 결박하려던 것은 "세 값이 서로 모순
없이 한 registry에 있다"이지 "한 명령이 셋을 동시에 썼다"가 아니다.

**정정**: A1은 `rotate-pair`가 Map·PinVi를 결박하고, Manager는 `rotate-pair` 또는
`rebind-execution`으로 같은 pinset에 결박돼 있으면 충족이다. 그 결박의 실재는
`--verify-leaf`의 L3·L4·L5가 다시 계산한다.

### A2 — 기계가 강제하는 것으로 다시 쓴다

원문은 "격리 launcher를 **정확히 한 번** 실행한다"이다. 코드를 읽어 확인한 기계의
실제 계약은 다르다:

| 실패 지점 | 기록 | 결과 |
|---|---|---|
| acceptance **본문**(`ledger_claim`·`m04_m05_e2e`·`m04_*`·`m05_*`) | `phase=None` 무조건 차단 | 그 execution identity로 본문 재실행 불가 |
| 본문 **이전** 인프라 phase | scoped 기록 | 보정 후 재실행 가능 |
| **성공** | 아무 기록도 남지 않는다 | — |

즉 one-shot은 **execution identity당**이고 **본문 실패에만** 강제된다.
`run-m05-isolated-e2e-once`의 성공 분기(`case 0)`)는 `exit "$driver_status"`뿐이고
`pin block-execution`이 없다.

**정정**: A2는 "한 execution identity에서 acceptance 본문이 한 번 완주한다"로 읽는다.
같은 pinset 아래 leaf가 셋 생긴 것은 계약 위반이 아니었다 — e2e-01은 본문 진입 전
preflight에서 거부돼 아무것도 소각하지 않았고, e2e-02·e2e-03은 Manager 업그레이드가
정당하게 만든 **서로 다른 identity**에서 각각 한 번씩 돌았다.

**남는 구멍을 이름 붙여 남긴다.** 성공이 identity를 소비하지 않으므로 **같은
identity에서 본문을 두 번 돌릴 수 있다.** 메우려면 "소각(burned)"과 "소비(consumed)"를
구분하는 새 상태가 필요하다 — 지금은 `phase=None` 하나뿐이라 성공에 같은 것을 쓰면
방금 성공한 leaf가 `--verify-leaf` L8에서 실패한다. **실행권 기계의 의미를 바꾸는
변경**이라 이 절에 묶지 않고 별도 항목(`T-VN-M05-ONESHOT-CONSUME`)으로 세운다.

### 남은 해제 조건

- [x] **P1 — `--verify-leaf`가 승격 후보 leaf에 대해 exit 0.** (2026-09-07 실측)

      **`ktdctl`이 설치한 Manager**로 두 후보가 모두 통과했다. 아래는 **프로그램이
      낸 출력 그대로**다 — 손으로 요약하면 그것이 곧 이 정의가 배격한 '문서 행위'다.

      ```
      # host: n150
      # installed Manager (ktdctl trusted release): f22f1a546b978f2dfbd1de4f547cc1fe80d69557
      # verifier: /opt/kor-travel-docker-manager/scripts/m05_isolated_e2e.py
      # date: 2026-09-07T16:19:04Z

      $ sudo /opt/kor-travel-docker-manager/backend/.venv/bin/python \
          /opt/kor-travel-docker-manager/scripts/m05_isolated_e2e.py --verify-leaf /root/pairv2-e2e-03
      PASS L0 leaf 신뢰 경계 — root-owned 0700: /root/pairv2-e2e-03 와 증적 파일의 부모 디렉터리 ['runtime', 'runtime/m04', 'runtime/m05']
      PASS L0b 일회용 worktree가 남지 않았다 — disposable_run_worktree_retained=False
      PASS L1 harness/status/phase — harness=m05-isolated-bridge-v1 status=passed phase=completed
      PASS L2 runtime/m04/m04-attestation.json — result.m04_attestation_sha256=950762d61116df96cee71c9364abfff4c847e1f576e2dce8aebc1898295074de recomputed=950762d61116df96cee71c9364abfff4c847e1f576e2dce8aebc1898295074de
      PASS L2 runtime/m05/attestation.json — result.m05_attestation_sha256=ac8184114459a3f249ef974e382b548100b9985bfa8229d456e2ecf5b6f6df9c recomputed=ac8184114459a3f249ef974e382b548100b9985bfa8229d456e2ecf5b6f6df9c
      PASS L2 runtime/isolated-runtime-provenance.json — result.runtime_provenance_sha256=652ac5bef4e37a8e8f8ae1a3ff212b15f83eb878f4462fbd71e9b316d7759209 recomputed=652ac5bef4e37a8e8f8ae1a3ff212b15f83eb878f4462fbd71e9b316d7759209
      PASS L3 pinset — attestation=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0 result=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0 registry=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0
      PASS L5 execution identity — attestation=5014f0c6874fd51d26c853876a738eebe822476b2931f5f69534483cfe1beba6 result=5014f0c6874fd51d26c853876a738eebe822476b2931f5f69534483cfe1beba6 registry_binding=found is_current=False
      PASS L4 Manager source revision — attestation=0406b14d0bcbdf9762a2027ff42c11a1bf17e5a7 result=0406b14d0bcbdf9762a2027ff42c11a1bf17e5a7 binding=0406b14d0bcbdf9762a2027ff42c11a1bf17e5a7 installed=f22f1a546b978f2dfbd1de4f547cc1fe80d69557 is_installed=False
      PASS L6 Map/PinVi source revision — provenance map=2099b8a671b4f5ddd4cc736e074d97b581675693 pinvi=f62e7ef1f2d898d1e71aafb12a2b17577eb689f9 registry map=2099b8a671b4f5ddd4cc736e074d97b581675693 pinvi=f62e7ef1f2d898d1e71aafb12a2b17577eb689f9
      PASS L6b provenance가 이 실행의 것이다 — execution_identity_sha256=5014f0c6874fd51d26c853876a738eebe822476b2931f5f69534483cfe1beba6==5014f0c6874fd51d26c853876a738eebe822476b2931f5f69534483cfe1beba6 manager_source_revision=0406b14d0bcbdf9762a2027ff42c11a1bf17e5a7==0406b14d0bcbdf9762a2027ff42c11a1bf17e5a7 pinset_sha256=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0==b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0 transaction_id=c3341ca0150445c43fe024cf44e08f90==c3341ca0150445c43fe024cf44e08f90
      PASS L7 M04 server-side chain — m04_server_side_chain_verified=True
      PASS L7b M04 증적이 사슬 안에 있다 — attestation=950762d61116df96cee71c9364abfff4c847e1f576e2dce8aebc1898295074de result=950762d61116df96cee71c9364abfff4c847e1f576e2dce8aebc1898295074de
      PASS L9 root-only ledger claim — ledger=/var/lib/kor-travel-docker-manager/m05-isolated-once claim=f021c8cf3f36b20e… present=True
      PASS L8 terminal 아님 — pinset_blocked=False leaf_execution_blocked=False
      leaf verification PASSED
      exit=0

      $ sudo /opt/kor-travel-docker-manager/backend/.venv/bin/python \
          /opt/kor-travel-docker-manager/scripts/m05_isolated_e2e.py --verify-leaf /root/pairv2-e2e-02
      PASS L0 leaf 신뢰 경계 — root-owned 0700: /root/pairv2-e2e-02 와 증적 파일의 부모 디렉터리 ['runtime', 'runtime/m04', 'runtime/m05']
      PASS L0b 일회용 worktree가 남지 않았다 — disposable_run_worktree_retained=False
      PASS L1 harness/status/phase — harness=m05-isolated-bridge-v1 status=passed phase=completed
      PASS L2 runtime/m04/m04-attestation.json — result.m04_attestation_sha256=293bb31f639f3065c79dceb55ea3ce34805debc3724416a4753959d2fdc00b03 recomputed=293bb31f639f3065c79dceb55ea3ce34805debc3724416a4753959d2fdc00b03
      PASS L2 runtime/m05/attestation.json — result.m05_attestation_sha256=60ad816859ce25f591edae9f866a5fe51617ed53cf0157b280a0a128b6e967b3 recomputed=60ad816859ce25f591edae9f866a5fe51617ed53cf0157b280a0a128b6e967b3
      PASS L2 runtime/isolated-runtime-provenance.json — result.runtime_provenance_sha256=36665196b4801ababa61e480a24f62b67e1dac104da0ecab8e438815dbfbae30 recomputed=36665196b4801ababa61e480a24f62b67e1dac104da0ecab8e438815dbfbae30
      PASS L3 pinset — attestation=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0 result=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0 registry=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0
      PASS L5 execution identity — attestation=c5791dfd40f1003da2d3aa6bff0758f90363bfc53ad9ac2906675170526aa0ae result=c5791dfd40f1003da2d3aa6bff0758f90363bfc53ad9ac2906675170526aa0ae registry_binding=found is_current=False
      PASS L4 Manager source revision — attestation=d36847e2f2e1b821c8e87e238561a64c0706a275 result=d36847e2f2e1b821c8e87e238561a64c0706a275 binding=d36847e2f2e1b821c8e87e238561a64c0706a275 installed=f22f1a546b978f2dfbd1de4f547cc1fe80d69557 is_installed=False
      PASS L6 Map/PinVi source revision — provenance map=2099b8a671b4f5ddd4cc736e074d97b581675693 pinvi=f62e7ef1f2d898d1e71aafb12a2b17577eb689f9 registry map=2099b8a671b4f5ddd4cc736e074d97b581675693 pinvi=f62e7ef1f2d898d1e71aafb12a2b17577eb689f9
      PASS L6b provenance가 이 실행의 것이다 — execution_identity_sha256=c5791dfd40f1003da2d3aa6bff0758f90363bfc53ad9ac2906675170526aa0ae==c5791dfd40f1003da2d3aa6bff0758f90363bfc53ad9ac2906675170526aa0ae manager_source_revision=d36847e2f2e1b821c8e87e238561a64c0706a275==d36847e2f2e1b821c8e87e238561a64c0706a275 pinset_sha256=b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0==b229446ac27382b48ad52d2022f2e9049d10350c8e13934e87cd7b1d973007e0 transaction_id=d4612b88ff2422b5f4323dd03ba4ea78==d4612b88ff2422b5f4323dd03ba4ea78
      PASS L7 M04 server-side chain — m04_server_side_chain_verified=True
      PASS L7b M04 증적이 사슬 안에 있다 — attestation=293bb31f639f3065c79dceb55ea3ce34805debc3724416a4753959d2fdc00b03 result=293bb31f639f3065c79dceb55ea3ce34805debc3724416a4753959d2fdc00b03
      PASS L9 root-only ledger claim — ledger=/var/lib/kor-travel-docker-manager/m05-isolated-once claim=d8c711b2c5b60e27… present=True
      PASS L8 terminal 아님 — pinset_blocked=False leaf_execution_blocked=False
      leaf verification PASSED
      exit=0
      ```

      두 leaf 모두 `is_installed=False`다 — L4가 설치본이 아니라 registry binding에서
      파생하지 않았다면 이 둘은 영원히 검증 불가였다는 뜻이다(#327이 고친 결함).
      **강화 전 결과는 근거로 쓰지 않는다.** 강화 전 검증기는 아무 디렉터리나 받았으므로
      그때의 exit 0은 이 조건을 만족시키지 않았다.
- [x] **P2 — 전문 적대 리뷰 두 건이 이 새 정의에 대해 GO.** (2026-09-08 5차에서 충족) 2026-09-07 1차는 두 건 모두
      NO_GO였고 그 P0가 이 정의 변경을 불렀다. 그 P1들의 처분도 함께 적는다 —
      CI green(재실행으로 해소), 서명의 사후 검증 불가(정의에서 근거로 쓰지 않음),
      A2 성공 미소비(별도 항목으로 분리).

      **2026-09-07 2차도 두 건 모두 NO_GO였다.** P0가 셋 겹쳤고 전부 정당했다 —
      검증기가 정의의 근거를 실제로 확인하지 않고 있었다. Manager #330이 넷을 고쳤다:

      | P0 | 무엇이었나 | 고침 |
      |---|---|---|
      | leaf 신뢰 경계 부재 | `lstat`/`st_uid`/`O_NOFOLLOW`가 **하나도 없어** `--verify-leaf`가 아무 디렉터리나 받았다 | `L0` 신설 + 모든 읽기를 신뢰 읽기로 |
      | 공개값 조립으로 통과 | L3~L6 입력이 전부 `-public` 0644 사본에서 읽힌다(리뷰어가 비-root로 실측) | `L9` — root-only 0700 ledger claim 실재 요구 |
      | 사슬에 M04 없음 | M04 증적을 해시만 하고 **한 번도 열지 않았다**. L7은 자유 불리언 | `L7b` — payload의 `m04_attestation_sha256`을 L2 재계산 값과 대조 |
      | L8이 current만 봄 | 승격 후보는 **둘 다 current가 아닌 identity**라 소각돼도 통과했다 | leaf 자신의 identity 차단을 본다 |

      **P0 하나는 이 문서의 결함이었다** — 위 L4 행이 "설치된 trusted revision"을
      요구하는데 코드는 `641dde6`(#327) 이후 registry binding과 대조한다. 그 상태로
      `is_installed=False` 출력을 P1 근거로 기록하면 **충족되지 않은 조건을 충족했다고
      적는 것**이 된다 — 이 정의 변경이 없애려던 바로 그 실패다. 위 행을 코드에 맞췄다.

      **위조 문턱을 정직하게 적는다.** `L9`가 올리는 것은 "공개값 베끼기"에서 "root"까지다.
      claim 이름 자체는 공개값에서 계산되고, 예측 불가 값(`transaction_id`)을 claim
      payload에 넣는 더 강한 닻은 기존 leaf를 무효화하므로 후속으로 남겼다.

      **3차도 두 건 모두 NO_GO였다.** 한 P0는 **#330이 만든 회귀**였다 — L8이
      phase-scoped 기록을 무조건 소각으로 읽어, 인프라 실패 뒤 보정해 통과한 leaf가
      영원히 검증 불가가 됐다(execution identity는 `(pinset, manager)` 파생이라 Manager를
      안 바꾼 재시도는 같은 identity다). `current`의 소각을 OR로 본 것도 함께 걷었다 —
      leaf와 무관한 다음 실패 하나가 history의 모든 증적을 무효화했다. #331이 고쳤다.

      **나머지 P0 넷은 전부 이 문서의 결함이었다.** 위 정의표가 강화 **이전** 검증기였고
      (L0·L7b·L9가 한 줄도 없었다 — 2차 L4 결함의 3배 재발), P1 기록은 프로그램이 내지
      않는 형식의 손 요약 4줄이었다. 표를 코드의 13축으로 다시 쓰고 출력을 그대로 실었다.

      **승격 근거의 수명을 숨기지 않는다.** `--verify-leaf`는 **아무것도 쓰지 않는다** —
      print만 하고 return한다. 그래서 위 출력 블록이 이 검증이 남긴 유일한 흔적이다.
      그 근거는 셋 중 무엇이 먼저 와도 재현 불가가 된다:

      | 무엇이 | 어느 축을 깨는가 |
      |---|---|
      | `pin rotate-pair` 한 번 | L3·L5·L6, 그리고 L4(binding 파생) (이것은 **의도된** 성질이다) |
      | execution history 500칸 링에서 두 binding이 밀려남 | L5, 그리고 L4(binding 파생) |
      | 두 후보 leaf 자신의 identity가 소각됨 | L8 |

      셋째는 #331이 좁혔다(무관한 실행의 소각은 이제 영향이 없다). 첫째·둘째는 남는다.
      **검증기가 durable receipt를 남기게 하는 것**은 별도 항목이 소유한다
      (`T-VN-M05-VERIFY-RECEIPT`).

      **4차는 갈렸다 — 코드 리뷰어 GO, 조문 리뷰어 NO_GO.** 조문 쪽 P0는
      "기록된 실측이 조문이 정의한 명령이 아니다"였고 정당했다. 그전 기록은 브랜치
      체크아웃의 스크립트로 낸 것이고, 그 호스트의 **설치본**은 조문이 근거로 쓰지
      않는다고 못 박은 강화 전 8축 검증기였다. Manager main(`44562d98`)을 `ktdctl`
      설치 경로로 배포한 뒤 **설치본으로** 다시 받아 위에 실었다.

      코드 쪽 P1은 #332가 전부 고쳤다:

      | 무엇이 | 고침 |
      |---|---|
      | 14축 중 넷(L1·L3·L6·L7)에 고립 게이트가 없었다 — 지워도 전부 초록 | 픽스처 knob + 고립 테스트 넷 |
      | 정확 mode 요구가 무방비(테스트가 0644/0755만 써서 `& 0o077`로 되돌려도 초록) | 0400·0500으로 잰다 |
      | `claim_name` 테스트가 planner를 안 부르고 **손복사본 세 번째**를 쓰고 있었다 | `ledger_filename`을 실제로 부른다 |
      | provenance의 결박 넷을 버리고 있었다 | **L6b 신설** — `transaction_id`가 예측 불가라 그 실행에 묶는다 |
      | L6 출력이 map만 찍어 증적에 PinVi revision이 없었다 | 둘 다 찍는다 |

      **승격을 정의하는 산출물의 CI.** Manager #330·#331·#332가 각각 백엔드·프론트엔드
      검사 green으로 병합됐고, 그 시점의 `pytest -q backend/tests`는 각각 1622·1624·1630
      passed / 3 skipped다.

      **P3·P4·P5의 측정 시점은 2026-09-07이다.** 셋 다 그 시점의 관측이며, `ktdctl pin
      verify`의 terminal 상태(P4)와 CI green(P3)은 시간이 지나면 변한다 — 재확인 없이
      현재형으로 읽으면 안 된다.

      **5차에서 두 건 모두 GO다 — P0 없음.** P2가 요구한 "전문 적대 리뷰 두 건이 이
      새 정의에 대해 GO"가 충족됐다.

      다만 코드 리뷰어가 **직접 변이를 돌려** 14축 중 여럿이 무방비임을 보였고, GO여도
      고쳤다(Manager #333). 그 부류가 이 절에서 반복된 것이기 때문이다:

      | 무방비였던 것 | 왜 안 잡혔나 |
      |---|---|
      | **L5 축 전체** | L5를 떨어뜨리던 세 테스트가 전부 다른 축을 함께 떨어뜨렸고, 단언이 **PASS 줄에도 찍히는 문자열**이라 축을 구분하지 못했다 |
      | L8의 pinset 절반과 fail-close 분기 | 픽스처가 항상 False를 냈다 |
      | L6b의 `transaction_id`·`manager`·`pinset`과 None 가드 | result와 함께 움직여 어긋낼 수 없었다 |

      `transaction_id`가 특히 뼈아프다 — 실제 위협(같은 pinset·같은 Manager의 **다른
      실행**이 만든 provenance 끼워넣기)에서는 나머지 세 필드가 전부 같으므로 **그
      필드만이 그 공격을 잡는다.** L6b를 신설한 바로 그 PR에서 게이트 없이 들어왔다.

      함께 고친 것: 정본 provenance 스키마와 검증기 키의 미결박(L9에서 이미 고친 결함의
      쌍둥이), 판독 실패 시 이미 잰 축이 한 줄도 안 찍히던 것, 그리고 L0 문구가 재는
      범위보다 넓던 것 — 그 잔여를 **L0b**로 올렸다.

      **다섯 라운드의 정직한 총평.** 매 라운드 실제 결함이 나왔고 검증기는 8축 → 15축이
      됐다. 그중 **둘은 앞 라운드 수정이 만든 회귀**였고 **셋은 픽스처가 결함을 가린
      것**이었다 — 실제에 없는 키를 지어내거나, duck-type 스텁으로 검사 축을 표현 불가능하게
      만들거나, 한 knob이 두 축을 함께 떨어뜨려 고립을 막았다. 이 절이 남기는 교훈은
      승격 조건 자체보다 **픽스처가 게이트를 조용히 무력화하는 방식**이다.
- [x] **P3 — 최신 CI green.** 핀된 PinVi `f62e7ef1`의 `api` 워크플로가 재실행으로
      success. 실패는 문서화된 flaky
      (`test_restore_backup_hotswap_cancellation_kills_script_process_group`)였다.
- [x] **P4 — terminal 아님.** `ktdctl pin verify`가
      `current_pinset_is_blocked=False`·`current_execution_is_blocked=False`·
      `generation_pinset_binding=match`.
- [x] **P5 — 공개 API만 사용.** 회전·rebuild·격리 실행이 trusted `ktdctl`과
      `runtime-pins`·`pinned-runtime/generation`만 썼다(A4 원문 그대로 충족).
