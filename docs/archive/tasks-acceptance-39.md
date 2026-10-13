# tasks-acceptance 아카이브 — `T-VN-39 — **완료(2026-09-11, #1197 `e8c66c47`)**` (완료)

> `T-VN-39 — **완료(2026-09-11, #1197 `e8c66c47`)**`의 해제 조건 원문이다. 절은 닫혔고, live 문서
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

## T-VN-39 — **완료(2026-09-11, #1197 `e8c66c47`)**

> 이 절은 판정 근거로 남긴다. 착지 실측은 아래 "착지 확인"이고, 후속 셋은
> `T-VN-39-DEPLOY` · `T-VN-39-ECHO` · `T-VN-39-PROVIDER-PAGINATION`이 소유한다.

**착지 확인(head-schema 실측).** feature_id류 컬럼 52개가 uuid이고, text로 남은 셋은
정당한 생존자다 — `manual_feature_purge_records.legacy_feature_id` ·
`ops.tvn36_legacy_freeze_preflight_manifest.legacy_feature_id` · plpgsql 지역변수
`v_legacy_feature_id`. shadow `feature_uuid` 컬럼 0개.
`ck_feature_aliases_legacy_alias_shape`가 주소 등록부를 지킨다.
게이트: GitHub CI 9종 전량 · n150(provider 실제 설치) dagster 575 · api 1,223 ·
lint+unit 2,832 · 제품 SQL 786문 head Parse · live(DB→API→브라우저, 필터 3갈래
200/200/422).


```markdown
- [ ] T-VN-39 — **KTM·PinVi write-fence cutover**

  consumer-first 배포, write fence와 순차 전환을 수행한다. **T-VN-33C의 legacy
  column/index/route/repository/trigger/table은 서비스 전 단계 원칙에 따라 같은 final-schema
  migration에서 이미 물리 삭제한다.** 따라서 이 task는 T-VN-33 보존·rollback·removal을
  소유하지 않는다. 이후 task가 만든 held component만 그 task의 manifest와 함께 판단하며,
  intermediate data는 backup/restore가 아니라 최종 schema ETL로 재생성한다.
```

**2026-09-07 전수 조사 — 유일한 실질 blocker는 미구현 대체물이다.**

removal manifest (c)의 대체물 `provider_sync.notice_states`가 **구현된 적이 없고, 그
구현을 소유하는 열린 항목이 없다.** 대체 대상 두 테이블은 현행 정상 writer 경로이므로
그것부터 옮기지 않으면 물리 제거가 성립하지 않는다.

규모 실측(prod): text/varchar `%feature_id%` 컬럼 40개, `feature.features` 참조 FK
34개, `feature_id`를 언급하는 인덱스 57개, baseline `schema.sql`에서 `feature_id`
언급 900줄. **이 백로그에서 가장 큰 축이다.**

manifest (b) provider_sync source lineage는 **이미 제거 완료**이므로 충족 처리해도
된다.

**2026-09-08 소유자 판정 — 계약을 개정해 (c)를 뺐다.**

**대체를 정당화한 결함이 이미 없다.** manifest 항목이 대는 이유는 하나,
"문자열 시각 판정"이다. 그런데 두 표의 시각 컬럼은 전부 typed다 —
`notice_lineage_states.changed_at`·`valid_until`, `notice_lifecycle_scopes.applied_at`이
모두 `timestamp with time zone`이고 writer도 `CAST(:closed_at AS timestamptz)`와
`>= scope.applied_at`로 typed 비교를 쓴다. 저장소에 남은 `pg_input_is_valid`는
`_frozen_h35_ended_notice_hidden_sql` 하나뿐이고, 그것은 0079 세대 표면을 리허설용으로
**일부러 글자 그대로 보존한** 함수다(그 docstring이 "현행 코드가 이 형태를 되살리는 것을
막기 위해 이 함수 안에만 존재한다"고 적는다). 즉 살아 있는 결함이 아니라 박제다.
문자열 시각 판정은 `T-VN-35B`와 `T-VN-37D`가 이미 없앴다.

**fence가 처음부터 없었다.** 이 항목의 `fenced_by`는 `T-VN-37B`인데 그런 항목은 원장에
**존재한 적이 없다.** 다른 여섯 entry는 전부 실재하는 fence를 가리킨다(34C·32C·33C·
36D·38C·40C) — (c)만 유일하게 fence 없이 등록돼 있었다. 그 fence가 소유했어야 할
`tstzrange` 표현은 `T-VN-37D`가 다른 표(`feature.feature_notices.valid_during`)에 이미
착지시켰다.

**새로 짓는 쪽의 값이 없다.** `notice_states`가 주는 것은 정규화(`valid_during` +
`is_current` 부분 유니크 + GiST)인데, 그 값을 사려면 살아 있는 writer 경로
(`feature_repo.py:3226-3500`)를 통째로 재작성하고 freeze 계약을 재계산해야 한다. 그런데
두 표 모두 **prod 0행**이고, 성능 문제는 `T-VN-37`이 이미 해결했다(20.4초 → 0.19초,
118.4초 → 0.36초). 해결된 문제를 위해 살아 있는 경로를 재작성하는 셈이고, 그 근거 문장은
이미 거짓이다.

**목표 상태 기술은 지우지 않는다.** `contracts/vnext/target-schema-v1.sql`의
`notice_states` DDL과 invariant는 "**채택되지 않음**" 표시만 달고 남긴다 — 정합성 요구가
생기면 다시 꺼낼 값이 있고, 지우면 같은 논의를 처음부터 다시 해야 한다(오늘
`b2543d68`이 지운 실측 기록을 되살린 것과 같은 이유다).

**이 판정이 틀릴 수 있는 지점.** `notice_states`가 성능이 아니라 **정합성**을 위한
것이었다면 판단이 뒤집힌다 — `is_current` 부분 유니크와 range 중첩 금지는 지금 두 표가
선언적으로 강제하지 못하는 불변식이다. 다만 그것을 요구하는 조문을 저장소에서 찾지
못했고, manifest가 대는 이유도 "문자열 시각 판정" 하나뿐이었다.

**2026-09-09 실측 — 본체는 재타입이 아니라 멱등 앵커 교체다.**

`feature_id`를 uuid로 바꾸면 둘 중 하나가 **반드시** 일어난다. provider가 계산한
`f_*`를 그대로 보내면 22P02이고, 새 UUIDv7을 보내면
`create_feature_with_initial_state`의 `ON CONFLICT (feature_id) DO NOTHING`이 **영원히
걸리지 않아** 매 ETL마다 중복 Feature가 생긴다. 후자는 DDL 초록·1회 적재 테스트 전부
초록이고, 증상은 **두 번째 ETL**에서 처음 나온다.

**앵커 축을 두 번 틀렸고 두 번 다 실측이 잡았다.**

1차(09-08): `provider_sync.source_links`의 `source_role='primary'`에
`UNIQUE (source_entity_key)`를 심었다가 **통합 1179건 중 17건이 빨개졌다** —
identity 이행 중에는 구·신 Feature가 둘 다 primary이고
`tests/integration/test_notice_lifecycle.py:529`가 그 형태를 의도적으로 재현한다.

2차(09-09): 되돌린 뒤 조사가 **축 자체가 틀렸다**는 것을 보였다.
`src/kortravelmap/providers/opinet.py`는 `source_entity_id`가 제품별
(`f"{uni_id}:{prodcd}"`, :689)이고 `source_natural_key`는 주유소별(`uni_id`, :697)이며,
그 경로 docstring이 "단일 제품 가격을 **같은 price anchor feature에 누적**"이라
명시한다(:762). entity → Feature가 정당하게 **N:1**이므로, entity를 축으로 삼으면 새
제품코드마다 새 Feature가 주조된다 — 재키가 고치려던 중복을 재키가 만든다.

**확정 축**: `(provider_dataset_id, feature_kind, natural_key)`.
`make_feature_id` 입력(`bjd_code|kind|category|source_type|source_natural_key`)에서
ADR-068 결정 2가 배제하라고 한 `bjd_code`·`category`만 뺀 것이다. 착지처는
`provider_sync.provider_feature_identities`(308)이고, `feature.features`로 가는 FK를
두지 않는다 — claim이 Feature보다 먼저 서야 하기 때문이며
`feature.manual_feature_identity_claims`가 같은 이유로 같은 모양이다.

**규모**는 숫자를 박지 않는다(2026-09-08의 "인덱스 57"이 실측 59와 어긋났다). 산출
쿼리로 둔다 — `information_schema.columns`의 `%feature_id%` 비-uuid 컬럼,
`pg_constraint`의 `confrelid='feature.features'::regclass`, `pg_indexes`의
`feature_id|feature_uuid` 언급.

**부수 발견**: `tests/integration/test_khoa_{rekey_hardening,recategorize_cleanup}.py`는
제품 코드를 0줄도 타지 않았다 — `_cleanup_sql()`이 아카이브 상수를 읽어 부분문자열만
확인하고 자기 파일의 SQL을 반환한다. 삭제했고, 삭제 전후 유닛·lint가
`244 failed / 2508 passed`로 동일했다.

**남은 것.** 이 항목의 소유자 판정 대기는 사라졌다. `T-VN-39`에 남는 것은 legacy TEXT
`feature_id` PK 제거 하나이고, **그것은 판정 대상이 아니다** — 대체 identity
(`feature_uuid` + unique 둘)와 fence 트리거가 이미 prod에 있고 `feature.features`가
0행이라 데이터 이행 위험이 없다. 남은 것은 컬럼 37 · FK 34 · 인덱스 57의 rekey 공학이다
(2026-09-07 조문이 적은 "컬럼 40개"는 `pg_catalog`/`information_schema`를 뺀 실측에서
37개다).
