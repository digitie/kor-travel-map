# ADR-099: causal seal은 행별 digest를 접는다 — 전 행 payload를 한 배열에 모으지 않는다

- 상태: accepted
- 날짜: 2026-09-19
- 결정자: human, AI agent
- 관계: [ADR-086](086-typed-feature-subtypes.md)이 geometry를 kind별 subtype으로
  옮기며 세운 "geometry 필수/금지를 술어가 아니라 테이블 구조로 가른다"는 불변식을
  **되돌리지 않는다**. 이 ADR의 1단계는 스키마를 건드리지 않고, 2단계에서 route
  geometry를 보조 relation으로 옮길 때 그 불변식을 대체 fence로 보존한다.

## 컨텍스트

`feature.current_provider_curation_input_set`은 provider dataset 하나의 curation
input을 하나의 해시로 봉인한다. 그 해시는 기록만 되는 값이 아니라 **두 곳에서
읽어 비교하는 게이트**다.

- `feature.seal_provider_curation_snapshot_receipt` — 불일치 시 `23514`로 child를 죽인다.
- `feature.finalize_provider_curation_root` — 불일치 시 root 전체를 `stale_input`으로 뺀다.

문제는 그 해시를 **만드는 방식**이었다. 데이터셋 전 행의 13항 배열을 하나의
`jsonb_agg` 배열로 모은 뒤 그 text를 sha256했다. 크기가 **O(행수 × 행당 payload)**라
PostgreSQL의 jsonb 배열 상한 268,435,455 bytes에 걸린다.

2026-09-19 prod에서 그 벽에 닿았다.

```
feature_route_krforest_mountain_trails_job
  04:04 시작 → 4시간18분 지오코딩 완료 → 적재 → 봉인에서
  asyncpg.ProgramLimitExceededError:
    total size of jsonb array elements exceeds the maximum of 268435455 bytes
```

적재와 봉인이 **같은 트랜잭션**이고 봉인이 마지막이라 57,060행이 통째로 롤백된다.
`provider_sync.source_entities`의 `mountain_trail_segment`가 0행인 이유가 이것이다 —
**이 job은 한 번도 성공한 적이 없다.** 그리고 `FEATURE_LOAD_RETRY_POLICY`가
같은 자리에서 최악 네 번 죽으며 매번 4시간짜리 지오코딩을 처음부터 다시 한다.

### 측정

prod 실측(2026-09-19).

| 대상 | 행당 payload | 행 수 | 환산 | 상한 대비 |
|---|---:|---:|---:|---|
| route (`to_jsonb(route)`) | 43 kB | 57,060 | **2.45 GB** | 약 10배 초과 |
| route, `geom` 제외 | 633 B | 57,060 | 36 MB | 여유 |
| place (`to_jsonb(place)`) | 323 B | 980,970 (MOIS) | **302 MB** | **초과** |

geometry가 route payload의 **98.5%**인 것은 맞다. 그러나 place는 geometry를 갖지
않는데도 MOIS 규모에서 한계를 넘는다. 즉 **geometry를 어디로 옮기든 fold 자체가**
다음 큰 dataset에서 같은 벽에 닿는다. 현재 천장은 대략 43 kB 기준 6,200 route,
323 B 기준 83만 place다.

## 결정

### 1. fold를 행별 digest의 집계로 바꾼다 (rev `311_seal_member_digest`)

배열 **원소의 정의를 한 글자도 바꾸지 않고** 접는 방식만 바꾼다.

```
종전: jsonb_agg(13항 배열 ORDER BY key, feature_id)::text → sha256
변경: 행마다 digest(13항 배열::text) = 32 B
      → string_agg(bytea ORDER BY key, feature_id) → sha256
```

- **탐지 범위가 1비트도 줄지 않는다.** `canonical_input` CTE는 정본과 41줄 바이트
  단위로 동일하고, `to_jsonb(route)`는 여전히 geometry를 담는다. 그래서 이 단계는
  크기 결함만 고치고, **geometry를 어디에 둘 것인가라는 논쟁과 분리된다.**
- 32바이트 고정폭이라 구분자 없이 이어 붙여도 경계가 모호해지지 않는다.
- 보존 필수 네 가지를 그대로 옮긴다: 두 `count`, `max(imported_at)::date`,
  `ORDER BY source_entity_key, feature_id`, `FILTER (WHERE ... IS NOT NULL)` +
  빈 집합 `COALESCE`.
- **시그니처를 바꾸지 않는다.** `CREATE OR REPLACE`가 되어야
  `ktm_curation_command_owner`의 EXECUTE GRANT가 보존된다. 바꾸면 DROP+CREATE가
  되어 조용히 사라진다.

선례는 같은 스키마 안에 있다 — `materialize_theme_candidate_generation`이 이미
행별 digest → 정렬 집계로 같은 종류의 집합 해시를 만든다.

### 2. 해시 공식의 **세대**를 receipt에 남긴다

이 fold는 같은 입력에서 다른 값을 낸다. 두 비교 지점은 **같은 run의 receipt만**
재대조하므로 게이팅은 깨지지 않는다(투입 시점에 진행 중 curation root가 0건임을
실측으로 확인했다). 그러나 이미 저장된 receipt는 이후 **영원히 재계산되지 않는다.**

세대를 적어 두지 않으면 **"공식이 바뀌었다"와 "값이 변조됐다"가 같은 관측으로
보인다.** 그래서 `ops.curation_provider_snapshot_receipts`와
`ops.curation_source_observation_receipts`에 `input_set_formula smallint`를 더한다.
기존 행은 1, 이 revision 이후 발급분은 2다. 열거는 `IN (1, 2)`로 **좁게** 둔다 —
다음 공식이 생기면 그때 넓히는 것이 맞고, 미리 열면 아무도 확인하지 않은 값이 들어온다.

### 3. geometry 분리는 **다음 단계**다 (rev 312)

소유자 지시는 *"등산로는 postgis 형태로 별도의 보조테이블에 저장"*,
*"등산로와 같은 건 route 에 저장"*이다. 즉 route 정체성은 유지하고 geometry
저장소만 분리한다. 그 변경은 2단계에서 한다.

**순서를 이렇게 두는 이유.** 1단계는 표를 만들지 않고 행을 건드리지 않으며
애플리케이션 코드를 한 줄도 바꾸지 않는다. 실패해도 forward revision 하나로
되돌아간다. 되돌리기 비싼 절반을 뒤에 두는 것이 옳다. 그리고 1단계만으로
등산로 적재가 풀리므로, 2단계는 크기 압박이 아니라 **자기 근거**로 판단할 수 있다.

## 고려한 대안

**geometry만 옮기고 fold는 두기.** 기각. route는 43 kB → 712 B로 줄지만 place가
남는다 — MOIS 980,970행이 302 MB로 초과하고, ADR-034 7단계에서 같은 실패가
그대로 재현된다. 새 천장이 약 26만 행으로 올라갈 뿐이다.

**적재를 청크로 쪼개 부분 커밋.** 기각. 이 asset은
`retire_absent_from_snapshot=True`라 청크 커밋이 "스냅샷에 없는 것을 은퇴한다"는
의미를 깬다. 봉인 항의 크기를 줄이는 것 외에 길이 없다.

**봉인 함수의 route arm에서 `to_jsonb(route)` 대신 컬럼을 열거.** 기각.
member 정의가 바뀌어 탐지 범위 변화를 함께 논증해야 하고, 새 컬럼이 생길 때마다
이 함수를 고쳐야 한다. fold만 바꾸면 그 논증이 필요 없다.

## 결과

- `feature_route_krforest_mountain_trails_job`이 처음으로 봉인을 통과할 수 있게 된다.
- MOIS 인허가 bulk(ADR-034 7단계)가 같은 벽에 닿지 않는다.
- 이 revision 이전 발급 receipt는 `input_set_formula = 1`로 남아, 재계산 불가가
  변조와 구별된다.
- 검사는 **효과**에 결박했다 — 행수는 같고 payload만 1,000배 다른 입력에서
  중간 집계 길이가 같은지를 재고(`행수 × 32 B` 고정), 옛 fold가 실제로 자라는 것을
  대조군으로 함께 증명한다
  (`tests/integration/test_seal_fold_has_no_size_ceiling.py`).
