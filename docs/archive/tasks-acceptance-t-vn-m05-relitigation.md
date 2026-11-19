# tasks-acceptance 아카이브 — `T-VN-M05-RELITIGATION` (완료)

> `T-VN-M05-RELITIGATION`의 해제 조건 원문이다. 절은 닫혔고, live 문서
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

## T-VN-M05-RELITIGATION

**2026-09-07 신설.** #1189가 M05-3 탐지기를 붙이면서 드러난 것이다 — 계약 자체의
성질이지 탐지기의 결함이 아니다.

`feature.record_manual_provider_dedup_candidate`의 멱등성은 `evidence_fingerprint`가
같고 **그 case가 아직 미해결일 때만** 성립한다(baseline `schema.sql` 8180~8186행:
`LEFT JOIN ... resolutions` + `WHERE resolution.case_id IS NULL`). 그래서 admin이
`kept`로 판정한 쌍을 탐지기가 다시 보면 지문이 같아도 **새 case가 만들어진다.**
그 상태로 탐지를 주기화하면 admin 큐가 쳇바퀴가 되므로 #1189의 job에는 스케줄을
달지 않았다.

**어느 방향으로도 틀릴 수 있다는 것이 이 항목의 어려운 점이다.**
너무 세게 막으면 증거가 **실제로 바뀌었는데도** 새 후보가 안 올라오는 영구 침묵이
되고, 너무 약하게 막으면 무관한 필드 patch가 `row_revision`을 올릴 때마다 supersede
폭풍이 난다. 둘 다 조용히 실패한다.

- [x] **R1 — 판정된 쌍이 같은 증거로 다시 올라오지 않는다.**
  admin이 `kept`/`merged`/`manual_retired`로 판정한 case와 **지문이 같은** 후보는
  새 case를 만들지 않는다. 억눌렸다는 사실은 삼키지 않고 receipt나 실행 요약에 남는다.
- [x] **R2 — 증거가 바뀌면 다시 올라온다.**
  Feature의 score-facing 값(`kind`/`name`/`category`/`lon`/`lat`)이나 provider의
  current source head가 바뀌면 지문이 달라져 새 후보가 된다. R1의 차단이 이것을
  덮지 않는다. **두 방향 모두 게이트가 있어야 한다** — 한 방향만 재면 반대 방향
  결함이 조용히 통과한다.
- [x] **R3 — 무관한 변경이 재발행을 부르지 않는다.**
  score와 무관한 필드 patch로 `row_revision`만 올라간 경우 새 case가 생기지 않는다.
- [x] **R4 — 차단이 detector 권한을 넓히지 않는다.**
  탐지 로그인은 `ops.manual_provider_dedup_cases`를 읽을 수 없다(`_OPS_TABLE_PRIVILEGES`가
  빈 튜플). 그러므로 차단은 프로시저 안에서 일어나야 하고, detector에게 case 조회
  권한을 주는 방식은 채택하지 않는다.
- [x] **R5 — 차단이 켜진 뒤에야 스케줄을 단다.**
  R1~R4가 충족되면 #1189의 `manual_provider_dedup_detection` job에 스케줄을 붙이고,
  그때 job description의 "스케줄 없음" 문구를 함께 걷는다.
**2026-09-08 — R1~R5 충족(migration 305).**

차단 키를 `evidence_fingerprint`로 잡으면 안 됐다. 그 지문에는 두 Feature의
`row_revision`과 `source_head_observed_at`이 들어 있어 **score와 무관한 필드 patch
하나**로 달라진다. 판정을 실제로 좌우하는 것만 넣은 `decision_fingerprint`를 따로
뒀다 — snapshot에서 `row_revision`을 뺀 것 + provider의 현재 source 내용
(`raw_payload_hash`) + `scorer_id`.

**변이 검증이 설계를 한 번 고쳤다.** 처음엔 `source_record_key`도 넣었는데, 그것을
빼는 변이가 초록이어서 왜인지 보니 **같은 내용을 다시 fetch하면 record key만
바뀐다** — 넣으면 그때마다 차단이 풀린다. 내용을 뜻하는 것은 `raw_payload_hash`
하나다.

`superseded`는 차단 근거가 아니다. 탐지기가 만든 resolution이므로 그것으로 차단하면
탐지기가 자기 자신을 영구히 침묵시킨다.

**두 방향 모두 게이트가 있다**(통합 6건, 변이 다섯 축 전부 RED):

| 되돌린 것 | 어느 방향이 깨지나 | 결과 |
|---|---|---|
| 차단 자체 제거 | 과소차단(쳇바퀴) | RED ×2 |
| 지문에 `row_revision` 복원 | 과소차단 | RED |
| 지문을 `feature_uuid`만으로 축소 | **과잉차단(영구 침묵)** | RED |
| provider `raw_payload_hash` 제거 | 과잉차단 | RED |
| `superseded`도 차단 근거로 | 탐지기 자기 침묵 | RED |

R5로 탐지 job에 일간 스케줄(04:20 KST, 기본 `STOPPED`)을 붙였고, job description의
"스케줄 없음" 문구를 걷었다. 억눌린 수는 `suppressed_case_count`로 보고된다 —
세지 않으면 "후보가 없다"와 "이미 판정됐다"가 같아 보인다.
