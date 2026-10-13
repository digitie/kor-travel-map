# tasks-acceptance 아카이브 — `T-VN-M04` (완료)

> `T-VN-M04`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-13).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 4개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-VN-M04

```markdown
- [x] **T-VN-M04 — 범용 Feature 요청 큐** (결정 2, 구현 병합). #1029의 `0233` service submit/admin
  approve·reject queue와 `manual_request` origin, OpenAPI/ACL/restore gate가 정본이다. 첫 consumer
  PinVi #458과 Map #1051 service re-vendor를 반영한 PinVi #465는 병합됐지만 paired
  request→approval receipt와 isolated acceptance는 `T-VN-41C`에서 완료한다.
```

**2026-09-07 전수 조사 — 위임이 dangling pointer다.**

`docs/tasks.md`와 이 문서가 "남은 paired request→approval receipt와 isolated
acceptance는 `T-VN-41C`가 소유한다"고 적어 왔다. 그런데 **§T-VN-41C 어디에도 "M04"가
없다** — 받는 절이 그 범위를 수락한 적이 없다. 게다가 41C는 보류라 잔여를 세지
않으므로, 위임이 유효했다면 이 범위는 아무도 세지 않는 상태였다.

위임한 물건은 이미 산출됐다 — `T-VN-PAIR-V2` §6의 e2e-03 m04 attestation이
`scope: isolated`·`status: passed`이고 `map_pending_receipt_sha256`·
`pinvi_approval_sha256`을 담는다.

**선행**: 위임 문장을 걷고 이 절이 자기 해제 조건을 갖는다. 그 조건은 위 산출물로
판정 가능해야 한다.

**2026-09-07 — 위임을 걷고 판정 가능한 조문을 세운다.**

위임 문장은 dangling pointer였다(위 참조). 아래가 이 절의 해제 조건이며, 전부 이미
산출된 물건으로 판정한다.

```markdown
- [x] **M04-1 — 큐 표면이 병합됐다.** `/v1/service/feature-requests`(SERVICE)와
  `/v1/admin/feature-requests{,/{id},/{id}/approve,/{id}/reject}`(OPERATOR)가
  `route_policy.py`·`openapi.json`에 있고, service 번들(`openapi.service.json`)에는
  service 경로만 노출된다. DB 권한은 submit=service_executor /
  approve·reject=admin_executor로 `runtime_privileges.py`에서 갈린다.
- [x] **M04-2 — origin이 `manual_request`다.** `models.py`의 origin_kind CHECK와
  `feature_request_repo.py`의 `manual_request_v1`, 통합 테스트
  `test_feature_request_submit_then_admin_approval_creates_only_manual_request_feature`
  와 `…_direct_relation_access_and_invalid_payload_are_denied`.
- [x] **M04-3 — restore evidence를 뜬다.** `scripts/docker-backup.sh`가 app snapshot에서
  `feature_requests.jsonl`을 캡처하고 count/sha256을 남기며
  `test_docker_backup_runbook.py`가 고정한다. (restore 쪽이 그 해시를 대조·거부하는지는
  이 절의 범위가 아니다 — backup/restore 축은 `T-VN-H49` 계열이 소유한다.)
- [x] **M04-4 — paired request→approval receipt가 격리에서 실측됐다.** 단일 격리 실행의
  **두 서명**이 같은 `feature_request_id`로 서로를 가리킨다.
  (a) `m04-attestation.json` — `scope=isolated`·`status=passed`·`version=2`,
      `map_pending_receipt_sha256`·`pinvi_approval_sha256`이 marker가 아니라 PinVi API
      재조회로 독립 재계산돼 일치(`_pinvi_m04_approval_snapshot` ↔
      `_validate_m04_ui_marker`), PinVi 컨테이너 라벨이 pinset의 PinVi revision과
      `io.pinvi.build.environment=isolated`에 결박.
  (b) `m05/attestation.json` — `m04_server_side_chain_verified=true`,
      `m04_attestation_sha256`이 (a)의 파일 해시와 동일,
      `m04_map_request_sha256`·`m04_map_provenance_sha256`·`m04_map_feature_uuid`가
      Map `/v1/admin/feature-requests/{id}`=approved와
      `/v1/admin/features/{uuid}/creation-provenance`.origin_kind=`manual_request`에서
      나온 값.
- [x] **M04-5 — reject도 실제로 호출된다.** admin reject가 pending→rejected 전이를 만들고
      사유·resolution command를 보존하며 **Feature를 만들지 않는다**는 것을 통합 테스트
      `test_feature_request_admin_rejection_closes_the_request_without_a_feature`가
      프로시저를 직접 불러 보인다.
```

**M04-4 판정 근거 — `/root/pairv2-e2e-03`** (Manager `0406b14d`, pinset `b229446a`,
Map `2099b8a6`, PinVi `f62e7ef1`):

| | 값 |
|---|---|
| `feature_request_id` | `24cdee5f-ef1a-4876-8be3-7460db79ce05` |
| m04 attestation | `950762d6…` (`scope=isolated`, `status=passed`, `version=2`) |
| m05 attestation | `ac818411…` (`m04_server_side_chain_verified=true`) |
| Map feature uuid | `01a07ab9-a007-74c4-9cf9-4629987034a7` |
| leaf `result.json` | `status=passed`, `phase=completed` |

해시 사슬은 **독립 재계산으로 확인했다** — n150에서 9개 파일을 `sha256sum`해
`result.json`의 값과 대조했고 전부 일치했다(적대 리뷰 2가 수행). `/root/pairv2-e2e-02`
(Manager `d36847e2`)도 같은 형태로 passed다.

**M04-5는 이 조사가 만든 것이다.** reject는 라우터·프로시저·ACL·OpenAPI에 전부
있었으나 **호출하는 테스트가 없었다.** 승인만 검증된 큐는 "거절이 무엇을 남기는지
아무도 모르는" 상태이고, 그대로 닫으면 reject 회귀는 운영에서만 드러난다.
