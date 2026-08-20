# ADR-095: notice 발효 전 철회를 empty 효력 범위로 표현한다

- 상태: accepted
- 날짜: 2026-08-21
- 결정자: human, AI agent

## 컨텍스트

`feature.feature_notices`는 `valid_start_time`과 `valid_end_time`을 각각
`timestamptz`로 보존한다. `valid_end_time`은 예정 종료일이 아니라 provider
feed에서 효력이 끝났다고 관측한 시각이다. 그러므로 미래 발효 공지가 발효 전에
철회되면 `valid_end_time < valid_start_time`이 될 수 있다. 실측 예시는
`start=2026-07-13`, `end=2026-06-02`다.

이 상태에 순서 CHECK를 추가하면 정상적인 철회가 ETL 실패로 바뀐다. 반대로 두
timestamp만 읽으면 "효력 범위가 없음"이라는 사실을 별도 typed 값으로 표현할 수
없다. 원안의 모든 notice read를 `tstzrange @>`로 바꾸는 방식은 미래 발효 KMA
특보를 발효 전까지 숨길 수 있어 제품 의미가 달라진다.

## 결정

1. `feature.feature_notices.valid_during`을 두 timestamp에서 파생되는 PostgreSQL
   `tstzrange GENERATED ALWAYS AS ... STORED` 컬럼으로 추가한다.
2. 정상 값은 `[valid_start_time, valid_end_time)`로 만든다. 한쪽 경계만 있으면
   해당 방향의 무한 경계를 사용하고, 두 경계가 모두 없으면 `NULL`을 유지한다.
3. `valid_end_time < valid_start_time`이면 range 생성자에 잘못된 순서를 넘기지
   않고 `empty` range를 저장한다. writer가 이 파생 컬럼을 직접 쓰는 경로는 없다.
4. 공개·admin의 active notice 술어는 기존 `valid_end_time <= now()` 의미를
   유지한다. 따라서 미래 발효 공지는 계속 노출되고, 이미 종료된 notice는 기존
   방식으로 감산된다. 이번 변경은 저장 표현만 추가하며 응답/OpenAPI 계약은
   바꾸지 않는다.
5. 이 컬럼에는 GiST 인덱스를 추가하지 않는다. 현재 notice는 feature당 subtype
   한 행이고 active 판정은 의도적으로 upper-bound 기반이므로, ADR-087에서
   폐기한 range hot-path 전환을 다시 도입하지 않는다.
6. `0231_tvn37d_notice_empty_range`는 기존 행을 다시 계산하는 stored-column DDL이므로
   writer fence/maintenance window에서 적용한다. migration은 `lock_timeout = 30s`를
   transaction-local로 설정해 잠금 대기를 무기한 허용하지 않고 fail-closed한다.

## 근거

- provider가 실제로 만드는 `end < start` 상태를 손실 없이 표현한다.
- 현재 공개 경고의 사전 노출 의미를 보존한다.
- 두 timestamp를 애플리케이션마다 재해석하지 않고 DB가 한 번 파생한다.
- 기존 read 계획과 `idx_feature_notices_validity`를 변경하지 않는다.
- 운영 중 무기한 잠금 대기를 방지하고, 잠금 확보 뒤의 rewrite 비용은 적용 전
  테이블 크기/WAL·maintenance window 점검으로 관리한다.

## 결과

- `valid_during`은 내부 typed subtype read에서 사용할 수 있으며 empty 여부를
  `isempty(valid_during)`으로 판정할 수 있다.
- 기존 `NoticeDetail`과 공개 응답은 그대로라 소비자 재배포가 필요 없다.
- range 표현 자체는 generated column을 지원하는 schema head가 필요하므로
  migration `0232_tvn37d_notice_empty_range`를 사용한다.
- 향후 notice 유형별로 미래 발효를 숨기려는 요구가 생기면 이 ADR의 active
  술어 결정을 별도 제품 결정으로 갱신해야 하며, 단순히 `@> now()`로 바꾸지 않는다.
