# tasks-acceptance 아카이브 — `T-VN-41F1D-E` (완료)

> `T-VN-41F1D-E`의 해제 조건 원문이다. 절은 닫혔고, live 문서
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

## T-VN-41F1D-E

**2026-09-06 완료.** 남았다고 적힌 "n150 data-dependent 실행"은 D2가 pinset `48166bd2`에서
수행했다 — lane이 v6 manifest·v8 journal·host attestation을 검증기에 넘기고 세 해시를
`result.json`에 남긴 뒤 `phase: passed`로 닫혔다. 검증기가 대조하는 축이 아래 열거와 일치한다.

`run-c7-prod-live-e2e.sh`(6-spec C7 prod gate)는 v6/v8 전환 이후 돌지 않았고 **앞으로도 이
baseline에서는 돌 수 없다** — `docs/runbooks/c7-prod-live-e2e.md`가 스스로
`[보존 이력 · 실행 금지]`이고 "300 baseline의 n150 배포에는 사용하지 않는다"고 적는다.
`T-VN-M01`의 restore 축과 같은 계열이다. 되살릴 조건: 300 baseline에 맞는 C7 prod gate 운영
순서가 생기면 그때 다시 세운다.

`/etc/kor-travel-map/`의 v6/v8 pinset 쌍 여섯은 같은 포맷의 이력이고 롤백 입력이라 퇴역
대상이 아니다. 퇴역한 것은 **포맷**이다 — v4/v5/v7이 `retired-de5206dc/`에 있다.
(ADR-102 결정 6 이후 러너는 v6/v8 사본을 읽지 않는다 — 위 사본은 운영자 정리 대상인 이력이다.)

```markdown
- [x] **T-VN-41F1D-E — 구 generation 퇴역·v6/v8 attestation 전환** (2026-09-06 완료)

  > 2026-08-25 — **저장소측(unit·script contract) 완료**. 남은 것은 F1D-D 순서를 따르는
  > n150 data-dependent 실행뿐이다. `E2E_C7_COMPATIBLE_PAIR_MANIFEST`가
  > `E2E_C7_PINNED_RUNTIME_MANIFEST` + `E2E_C7_REBUILD_JOURNAL`로 바뀌었고, runtime role은
  > 다섯에서 **일곱**으로(PinVi web/dagster 추가), host attestation은 version 3 → 4로,
  > 세 schema head와 pinset이 generation 값과 exact 대조된다. 2026-08-25에는 Manager의
  > manifest v6/journal v8에 맞춰 application `300` candidate evidence, application/Dagster
  > DB identity, root/finalize result, application/metadata permit까지 exact 검증하도록 올렸다.
  > 최종 보강에서는 PinVi DB의 PostgreSQL system identifier·name/OID·owner-login identity와 Dagster
  > metadata LOGIN role의 connection limit·password expiry·role/database-local setting 잔여까지
  > 같은 journal/permit field set으로 결박해 **세 DB identity**를 committed resume에서 재대조한다.
  > journal은 phase `committed` + candidate 전체 동등 + cancel probe `finalized`를 요구한다. v4를 억지로
  > 넣어 통과하는 경로는 만들지 않았고, runner 계약 테스트가 v4 env 부재를 단언한다.
  > 변이(phase/candidate/candidate evidence/DB identity/result/permit/cancel probe/schema
  > head/journal digest/pinset/image 대조/manifest version)가 전부 red임을 실측했다. 실행 전제: v6/v8은
  > `require_rebuildable_mode`가 걸려 rehearsal/rebuildable에서만 생성된다(n150은 해당).
  > 과거 v5/v7 파일은 보존 이력일 뿐 current runner 입력이 아니며, 현 세대 v6/v8 문서는
  > H46H의 committed fresh rebuild가 이미 만들었고, D1/F1D-E가 이를 후속 검증에 사용한다.

  `run-c7-prod-live-e2e.sh`와 `run-admin-feature-live-acceptance.sh`가 요구하는 v4
  `E2E_C7_COMPATIBLE_PAIR_MANIFEST`를 제거한다. root-owned snapshot은 v6
  `PinnedRuntimeManifest.active_generation`, 일곱 immutable image·Map/PinVi revision·세 schema
  head·pinset·application `300` candidate evidence를 확인하고 v8 journal/host attestation과
  함께 발행한다. v4/v5 manifest와 v7 journal을 억지 입력해
  통과하는 compatibility 경로는 만들지 않는다. final schema merge/재적재와 독립적으로 unit·script
  contract까지 완료하고, 실제 n150 data-dependent 실행은 위 F1D-D 순서를 따른다
  (그 순서는 `T-VN-FINAL-REBUILD` 배리어 뒤에 열린다).

### T-VN-FINAL-REBUILD — 주요 개발 완료 후 최종 acceptance 배리어 (2026-08-20 신설)

> **범위 정정(2026-08-26)**: H46H baseline의 파괴적 fresh rebuild는 사용자 승인에 따라
> 이미 실행·committed됐다. 이 task는 후보가 바뀌어 rebuild를 다시 해야 하는 경우가 아니면
> 재실행하지 않고, 남은 D1/D2/F1D-E와 41C의 최종 acceptance 순서·barrier를 소유한다.
```
