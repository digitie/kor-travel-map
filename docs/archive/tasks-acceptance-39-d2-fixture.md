# tasks-acceptance 아카이브 — `T-VN-39-D2-FIXTURE` (완료)

> `T-VN-39-D2-FIXTURE`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-11-28).
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

## T-VN-39-D2-FIXTURE

```markdown
- [x] T-VN-39-D2-FIXTURE — **D2 fixture의 소유 핸들을 재키 뒤 앵커로 옮긴다** (2026-09-11 완료)
```

**무엇이 참이면 닫히는가.**

1. `scripts/admin_feature_live_fixture.py`의 provider fixture가 자기 Feature를
   **정본 uuid**로 들고 다닌다 — `CAST(:feature_ids AS uuid[])` 바인드 10곳에
   legacy 주소가 들어가지 않는다.
2. D2 lane이 seed → 감사 → cleanup을 완주하고 `RESULT.json`이 남는다.
3. 잔여물 0이 실측으로 확인된다(`/root/adjudicate.sh`의 네 counter).

**무엇이 깨졌나 — 2026-09-11 실측.**

D2 direct seed가 이렇게 죽는다:

    asyncpg.exceptions.DataError: invalid input for query argument $1:
    ['f_global_w_47c05e70793daee8', ...] (invalid UUID: length must be
    between 32..36 characters, got 27)

    SELECT (SELECT count(*) FROM feature.features
            WHERE feature_id = ANY(CAST($1 AS uuid[]))) AS features, ...

**질의는 uuid 축으로 옮겼는데 값의 출처는 안 옮겼다.** 이것이 T-VN-39가 고치려던
바로 그 부류이고, 하네스 자신이 그 부류로 남아 있었다.

**왜 alias로 우회할 수 없나.** 이 seed는 core 프로시저를 직접 부른다. ADR-098 결정
6과 309(`trg_features_legacy_alias` 영구 제거)에 따라 **alias가 생기지 않고 그것이
정상이다** — 하네스 주석이 스스로 그렇게 적고 있다. 그래서
`make_feature_id(...)`가 만든 `f_global_*` 주소는 재키 뒤 **DB 키가 전혀 아니다.**

**왜 재계산도 안 되나.** `candidate_feature_uuid()`는 비파생 랜덤 UUIDv7이다
(0083). run_id에서 유도할 수 없다. 이 파일은 같은 문제를 API-owned 경로에서 이미
한 번 풀었고, 그 답이 "재계산이 아니라 **재현**"이었다 — 소유권 키로 **조회**한다.

**그래서 해는 T-VN-39가 만든 앵커다.** provider 경로의 Feature identity는
`provider_sync.provider_feature_identities`의
`(provider_dataset_id, feature_kind, natural_key)` claim이 소유한다(ADR-098). 이
fixture의 natural key는 `{run_id}:{kind}`이고 dataset은 `_ensure_dataset`가 run별로
만든다. 즉 소유 uuid는 그 claim 한 번의 조회로 **재현**된다 — seed 전에는 행이
없으므로 빈 집합이 되어 "이미 존재하는가" 사전 검사도 그대로 성립한다.

**범위.** `_feature_ids(run_id)`의 소비자 전부(바인드 10곳)와 seed payload의
`feature_id` 슬롯. payload는 admin 경로처럼 후보 uuid를 실어야 한다.

**주의 — prod에 쓴다.** 이 lane은 prod feature DB에 seed하고 지운다. 고친 뒤
첫 실행은 잔여물 counter 넷을 전후로 재고 증거를 남긴다.

**2026-09-11 — 자매 lane에도 같은 부류가 남아 있다(이 절의 것이 아니다).**
적대 리뷰가 `scripts/admin_feature_clone_live_state.py`에서 둘을 더 짚었다:
`_API_OWNED_AUDIT_FOREIGN_KEY_REFERENCES = 8`(같은 alias 한 행을 더 센다)과,
evidence 키 집합을 `feature_ids` 없이 **정확히** 요구하는 검사(그 키는 #1176부터
나오고 있다). clone lane은 D2와 다른 소비자이므로 여기서 고치지 않는다 — 그 lane을
다시 돌릴 때 함께 본다.
