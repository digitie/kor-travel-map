# ADR-080: integrity finding 관측을 불변 generation과 observation set으로 정규화한다

- 상태: accepted
- 날짜: 2026-07-31
- 결정자: human, AI agent
- 관계: T-VN-H32R, #911, #912, migration `0071_integrity_observations`

## 컨텍스트

주소 검증 finding은 열린 `data_integrity_violations` 한 행의
`payload.observed_run_id`를 최신 run으로 덮어썼다. 같은 provider/dataset에서 run A와 B가
겹치면 B가 marker를 바꾼 뒤 A의 sweep이 A가 실제 관측한 finding을 미관측으로 오판해
`resolved`로 닫을 수 있었다. process-local lock은 여러 Dagster worker를 막지 못하고,
provider fetch 전체를 긴 DB transaction으로 감싸는 방식은 외부 API 지연 동안 lock을
보유한다.

## 결정

관측과 현재 finding 상태를 세 정규화 테이블로 분리한다.

1. `ops.integrity_observation_scopes`는 `(provider, dataset_key)`별 다음 generation과 최근
   authoritative generation을 저장한다.
2. `ops.integrity_observation_runs`는 external run id에 generation을 한 번만 배정하고
   collecting/authoritative/superseded 상태와 source/finding receipt를 보존한다.
3. `ops.integrity_finding_observations`는 run이 본 `dedupe_key` 집합을 불변 행으로 저장한다.

generation 배정과 close finalization은 scope row `FOR UPDATE`로 직렬화한다. typed receipt가
authoritative source 전체 관측, source 1건 이상, finding 전량 durable 기록을 증명할 때만
finalize한다. sweep은 current run의 observation을 anti-join하고, 더 새 collecting
generation이 이미 관측한 key도 보호한다. 새 authoritative generation이 먼저 완료됐다면
오래된 run은 `superseded`가 되어 sweep하지 않는다.

## 근거

- mutable payload marker가 사라져 다른 run이 한 관측 증거를 덮을 수 없다.
- 외부 fetch 동안 DB lock을 잡지 않는다. 짧은 generation 배정 transaction과 close
  transaction에서만 scope row를 잠근다.
- 더 새 partial/failing run은 close 권한을 얻지 못하지만 이미 durable하게 남긴 증거는
  과거 snapshot이 파괴하지 못한다.
- observation set은 finding 이력과 별도 수명·FK를 가져 JSONB 내부 운영 marker보다 쿼리와
  제약이 명확하다.

## 결과

- `record_address_validation_findings(run_id=...)`는 generation을 확보하고 dedupe-key
  observation을 같은 transaction에 기록한다.
- close는 receipt와 generation을 함께 finalize하며, `acknowledged`와 다른 subsystem key는
  기존처럼 건드리지 않는다.
- run/observation 이력 보존 정책이 추가로 필요해질 수 있다. 현재는 정확성 증거를 우선해
  자동 삭제하지 않는다.
- PostgreSQL 회귀는 A upsert→B upsert→A close, newer partial 보호, B close→A close,
  동시 generation allocation, receipt fail-close를 포함한다.
