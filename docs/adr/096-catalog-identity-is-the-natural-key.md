# ADR-096: catalog identity는 자연키다 — migration은 Identity 대리키를 고정하지 않는다

- 상태: accepted
- 날짜: 2026-08-21
- 결정자: human, AI agent
- 관계: [ADR-069](069-provider-datasets-canonical.md)가 DB 소유로 세운 provider dataset의
  **identity 해석을 명시**한다. [ADR-088](088-provider-dataset-operation-and-observation-model.md)
  의 operation·scope 적재도 같은 규칙을 따른다. 실패 사례는 `docs/journal.md` 2026-08-21 항목.

## 컨텍스트

`0229`+`0230`+`0231` 묶음 배포가 `0230_tvn_c05_krforest_datasets`에서 멈췄다.

```
TVN-C05 provider_dataset_id 73 is already assigned to
python-datagokr-api/standard_special_streets;
expected python-krforest-api/krforest_wildfire_risk_forecast
```

`alembic/env.py`는 `run_migrations()` 전체를 한 transaction으로 감싸므로(≠
`transaction_per_migration`) 30회 재시도가 매번 전량 롤백됐고, 함께 올라갈 `0229`·`0231`도
같이 무산됐다. API는 끝내 뜨지 않았다.

`0230`은 `provider_dataset_id` 70~74를 SQL에 그대로 적었다. 그런데 그 컬럼은
`Identity(always=True)`이고, `provider_sync.provider_datasets`의 정본 identity는
`uq_provider_datasets_identity (provider, dataset_key)`다. **대리키는 계약이 아니라 그
데이터베이스 안에서만 뜻이 있는 지역값이다.** 실제로 값이 갈려 있었다 —
`python-datagokr-api/standard_special_streets`를 baseline seed는 69번으로, prod는 73번으로
들고 있었다.

이 결함이 특히 위험했던 이유는 실패 방식이 아니라 **성공했을 때의 모습**이다. 가드가
없었다면 dataset은 `ON CONFLICT (provider_dataset_id) DO NOTHING`으로 조용히 건너뛰고,
operation·scope는 같은 숫자를 그대로 써서 **남의 dataset에 달라붙었을** 것이다. FK는 그것을
막지 못한다 — 가리키는 행이 실제로 있기 때문이다.

CI는 늘 초록이었다. 통합 테스트 DB는 `0200_schema_baseline`이 `alembic/baseline/seed.sql`을
실행해 만들어지고, 그 seed에는 C05 catalog가 이미 70~74로 들어 있다. 그 DB에서 이
migration은 순수 no-op이라 **prod 조건을 한 번도 보지 못했다.** 대리키를 적는 관행이
위험하다는 신호를 어떤 게이트도 낼 수 없었다.

## 결정

`alembic/versions/` 아래의 migration은 `provider_sync` catalog를 **자연키로만** 쓴다.

1. **대리키를 지정하지 않는다.** dataset INSERT는 `provider_dataset_id`를 열 목록에서 빼고
   identity sequence가 번호를 매기게 둔다. `OVERRIDING SYSTEM VALUE`는 baseline dump
   (`seed.sql`)만의 것이다.
2. **자식 행은 JOIN으로 번호를 되찾는다.** `provider_dataset_operations`·
   `provider_dataset_operation_scopes`는 `(VALUES ...) JOIN provider_datasets ON provider,
   dataset_key` 형태로 넣는다. 숫자를 두 번 적지 않으므로 잘못된 dataset에 붙는 경로가
   구조적으로 없다.
3. **충돌 판정은 자연키로 한다.** `ON CONFLICT (provider, dataset_key)`.
4. **sequence 보정은 되감지 않고, INSERT보다 먼저 돈다.** `GREATEST(max(id),
   현재 last_value)`. 뒤에 두면 정작 그 보정이 필요한 상태(뒤처진 sequence)에서 INSERT가
   먼저 죽는다 — `nextval`이 이미 쓰이는 번호를 돌려주고, 자연키 arbiter는 대리키 PK
   충돌을 잡지 못한다.
5. **적재 후 사후 단언을 둔다.** 선언한 dataset·operation·scope가 실제로 섰는지, 이미 있던
   dataset의 계약(`source_kind`/`capabilities`)이 선언과 같은지, operation이 `is_enabled`
   인지 확인하고 아니면 중단한다. "선언됐다"와 "돌 수 있다"는 다르다.

이 규칙은 `tests/lint/test_alembic_surrogate_identity_literals.py`가 강제한다 —
migration의 SQL 문자열에 `OVERRIDING SYSTEM VALUE`가 있거나, catalog INSERT의 `VALUES`
행이 정수 리터럴로 시작하면 실패한다.

## 대안과 기각 사유

- **prod에서 73번을 다른 번호로 옮긴다.** 기각. 18개 표가 `provider_dataset_id`를 FK로
  참조한다. 무엇보다 migration의 상수를 맞추려고 운영 데이터의 identity를 바꾸는 것은
  인과가 거꾸로다.
- **migration이 노리는 번호를 비어 있는 값으로 바꾼다.** 기각. 같은 결함을 한 칸 옆으로
  옮길 뿐이다. 다음 환경에서 그 번호가 차 있으면 똑같이 멈춘다.
- **대리키 배치를 환경 간에 강제로 맞춘다(seed 재적용·번호 재정렬).** 기각. 대리키를
  전역 계약으로 승격시키는 선택이고, 그 순간 모든 환경이 같은 순서로 같은 행을 만들어야
  한다는 제약이 생긴다. `Identity(always=True)`를 쓰기로 한 결정과 정면으로 어긋난다.

## 결과

- **환경마다 `provider_dataset_id`가 다르다. 그것이 정상이다.** prod에서 C05 5종은
  104~108을 받았고 baseline seed는 70~74다. 두 값을 비교하는 게이트를 만들지 않는다.
- 대리키를 표시용으로 노출하는 곳(admin UI의 `#{provider_dataset_id}`)은 환경 지역값을
  보여 주는 것이다 — 환경을 넘겨 인용하지 않는다.
- 재사용 가능한 교훈은 좁은 SQL 규칙이 아니다. **테스트가 만드는 세계가 곧 게이트가 볼 수
  있는 세계의 상한이다.** seed로 만든 DB만 보는 한 seed와 다른 DB의 결함은 보이지 않는다.
  identity·번호·순서처럼 환경마다 갈릴 수 있는 축은, 갈린 상태를 테스트가 **명시적으로
  만들어** 두어야 한다.

## 검증

- `tests/integration/test_tvn_c05_catalog_migration.py` — 대리키 70~74를 전부 남이 선점한
  DB를 만들고, catalog 세 표를 자연키로 정규화해 통째로 스냅숏해 delta를 단언한다.
  뒤처진 sequence 복구, 계약 불일치 거부, 사후 단언 네 가지 분기를 각각 고정한다.
- `tests/lint/test_alembic_surrogate_identity_literals.py` — 재발 차단.
- prod 덤프 리허설(2026-08-21): 587M 사본에서 `0225→0229→0230→0231` 30초 통과,
  fail-closed runtime ACL 조정 exit 0, 73번 선점자 자식 0으로 무사, sequence 103→108.
