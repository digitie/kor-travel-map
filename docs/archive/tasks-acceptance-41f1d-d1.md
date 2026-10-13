# tasks-acceptance 아카이브 — `T-VN-41F1D-D1` (완료)

> `T-VN-41F1D-D1`의 해제 조건 원문이다. 절은 닫혔고, live 문서
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

## T-VN-41F1D-D1

```markdown
- [~] **T-VN-41F1D-D1 — 최종 격리 리허설·provenance attestation** *(공동, docs-only)*

  > H46H의 fresh rebuild와 data-independent UI/provenance subset은 committed됐다. 남은 D1
  > 후속은 `T-VN-FINAL-REBUILD` barrier가 현재 candidate를 유지한다고 판정한 뒤 실행한다.

  C3가 결선된 새 generation에서 schema head, canonical `409` receipt, finalize와 **데이터
  비의존** 관리자 UI smoke(로그인 포함)를 기록한다. 2026-08-06 n150 rebuild는 committed했고
  Map application `0087_route_area_subtypes`, Map Dagster `29b539ebc72a`, PinVi `20260804_0049`와
  fixture `finalized`/정확한 `409 PIPELINE_CANCELLATION_UNSAFE`를 확인했다.

  **선행**: T-VN-33 merge와 `T-VN-FINAL-REBUILD`의 current candidate 확인이다. H46H가 이미
  수행한 `rebuild-pinned --confirm`의 v6/v8 evidence를 사용하되, 이전 C3의 pin·smoke는 새
  schema acceptance 증거로 재사용하지 않는다. Manager의 tracked Map source가 병합 SHA와 같고, Map API/UI/Dagster/daemon 및 PinVi
  API/Web/Dagster 일곱 image의 immutable ID·각 schema head·resolved compose/pinset/OpenAPI
  provenance가 candidate에 attest되어야 한다. v6 active generation과 v8 journal만 실행
  authority이며 이전 compatible-pair manifest를 재사용하지 않는다.
```
