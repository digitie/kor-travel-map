# tasks-acceptance 아카이브 — `T-VN-CURATION-SEAL-ACL` (완료)

> `T-VN-CURATION-SEAL-ACL`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-09-16).
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

## T-VN-CURATION-SEAL-ACL

```markdown
- [x] T-VN-CURATION-SEAL-ACL — **적재 seal 함수를 적재 role이 실행할 수 없다** (2026-09-16 완료)
```

**무엇이 참이면 닫히는가.**

1. [x] `ktm_feature_dagster_runtime`으로 접속한 적재가 curation seal을 통과한다 —
   prod에서 provider asset 하나가 실제로 완주한다. **2026-09-16 충족.**
2. [x] 그 권한이 `infra/runtime_privileges.py`의 렌더링 모델에 들어간다. 마이그레이션에
   직접 `GRANT`만 적고 모델이 모르는 상태로 두지 않는다 — 모르면 다음 재적용에서
   조용히 사라진다(지금이 그 상태다). **2026-09-16 충족 — 재적용을 실제로 겪고 살아남았다.**
3. [x] 이 축을 재는 회귀가 있다. **실 role로** 적재 경로를 태우는 것이어야 한다 —
   migrator/superuser로 도는 통합은 ACL을 구조적으로 관측하지 못한다. **2026-09-16 충족.**

**무엇이 깨졌나 — 2026-09-11 실측.**

prod에서 `feature_place_standard_museums`를 적재하니 상류 조회를 지나 DB 쓰기에서
멈췄다:

    asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied for function current_provider_curation_input_set

**실측 ACL** (prod, head 309):

    owner = ktm_feature_schema_owner
    acl   = ktm_feature_schema_owner=X, ktm_curation_command_owner=X

적재 login role은 `ktm_feature_dagster_runtime`이고 그 목록에 없다. 그리고 runtime
identity는 **설계상 `SET ROLE` 경로를 하나도 받지 않는다**
(`runtime_privileges.py`: "runtime identity는 이 `SET ROLE` 경로를 하나도 받지
않는다"). 즉 우회로가 없다.

**재키 회귀가 아니다.** `alembic/baseline/schema.sql`과 `alembic/head-schema.sql`이
**둘 다** `ktm_curation_command_owner` 하나에만 준다 — prod는 정본과 일치한다. 은퇴한
`0209_tvn40_provider_curation_seal`이 `ktm_feature_runtime`에도 주었으나 그 문장은
baseline으로 접히면서 사라졌고, `runtime_privileges.py`는 이 함수를 **아예 모른다.**

**범위가 좁지 않다.** `capture_provider_curation_input`은 `client.load_feature_bundles`
가 `curation_dataset`을 받을 때 불리고, `dagster/etl.py`는 **snapshot이 아닌 모든**
적재에 그것을 넘긴다. 즉 그 부류 provider 적재가 prod에서 전부 막혀 있다.

**왜 여태 안 보였나.** prod `feature.features`가 0행이었다 — 이 prod에서 provider
적재가 한 번도 성공한 적이 없다. 그리고 통합 테스트는 ACL이 바인드되지 않는
identity로 돈다. 조문 3이 그 구멍을 겨냥한다.

**주의 — 권한 확대다.** runtime login에 함수 EXECUTE를 더하는 변경이므로, 무엇을
열어 주는지(이 함수는 집계 읽기다)와 무엇을 열지 않는지를 먼저 적고 적대 리뷰를
거친다.

**어떻게 닫혔나 — 2026-09-16 실측.**

**조문 1.** 현 prod에 `feature_place_standard_museums_job`을 정식 경로
(`dagster job launch`)로 제출해 run `0f70d0d5`가 `SUCCESS`로 끝났다. 그리고 **적재가
남긴 것을 셌다**:

| | 실행 전 | 실행 후 |
|---|---|---|
| `feature.features` | 0 | **1,047** |
| `provider_sync.source_entities` | 0 | **1,047** |
| `ops.curation_provider_snapshot_receipts` | 0 | **1** |

세 번째 줄이 이 조문의 핵심이다. 영수증은 적재가 seal 함수에서 해시를 **받아온 뒤에만**
쓰이고(`_seal_authoritative_curation_snapshot`), `finish_provider_feature_membership_command`
가 `authoritative_snapshot_complete`와 영수증 유무가 어긋나면 거절한다. 즉 영수증 1건은
"EXECUTE가 목록에 있다"가 아니라 **"적재가 그 함수를 실제로 실행해 결과를 봉인했다"**의
증거다: `data.go.kr-standard/datagokr_museums`, `source_entity_count=1047`,
`source_input_set_hash=7358285d…`.

**조문 2.** 배포 재적용을 실제로 겪고 살아남았다. prod DB는 t44a 배포가 **새로 만든
것**이다(`kor_travel_map` 생성 2026-09-15 12:29:55Z) — 즉 grant는 맨 DB에 렌더링 모델이
다시 붙인 것이다. 오늘 실측:

    dagster_seal = true      (적재 login은 실행할 수 있다)
    dagster_claim = true     (자매 claim 해석기)
    api_seal = false         (API login은 못 한다 — 좁힌 grant가 경계를 지킨다)

조문 2가 겨냥한 위험이 "다음 재적용에서 조용히 사라진다"였고, **그 재적용이 실제로
일어난 뒤에 쟀다.** 코드를 읽어 확인하는 것과는 다른 종류의 증거다.

**조문 3.** `tests/integration/test_runtime_privileges_acl.py`의
`test_provider_curation_seal_runs_on_the_loader_path_as_the_real_logins` —
`dagster_runtime_engine`으로 **접속해서** raw SQL이 아니라 적재가 쓰는
`capture_provider_curation_input`를 부른다. 반대편은 API login이 42501을 받는 것을 보되,
**그 표를 읽을 수 있음을 먼저 확인한 뒤에** 본다(그 전제가 없으면 표 권한이 없어도 같은
42501이라 경계가 풀려도 초록이다).

**변이로 빨강을 확인했다 — 그리고 그 변이가 이 조문의 존재 이유를 보인다.** EXECUTE는
그대로 두고 호출부가 함께 거는 `provider_sync.provider_datasets` SELECT만 걷었더니:

| 검사 | 결과 |
|---|---|
| `test_provider_curation_seal_is_executable_by_the_loader_login` (migrator·카탈로그 술어) | **passed** |
| `test_provider_curation_seal_runs_on_the_loader_path_as_the_real_logins` (실 login·적재 경로) | **failed** |

조문 3이 "migrator/superuser로 도는 통합은 구조적으로 관측하지 못한다"고 적은 것이
바로 이 차이다. 정상 상태에서는 이 파일 8건 전부 초록.
