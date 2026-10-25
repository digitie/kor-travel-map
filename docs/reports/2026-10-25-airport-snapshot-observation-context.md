# 공항 immutable 입력의 원 관측 context

## 소유 범위와 권위

수용된 typed codec `891dccd09fb2ce022440ed03025aa2560913a352` 위에 새 Dagster
`airport_snapshot_observation.py`, 그 unit, 이 보고서만 추가한다. 기존 codec,
validation, GeoCallStats, DTO, ETL/assets/client/DB/control/권한은 바꾸지 않는다.
기존 심볼·signature가 변하지 않는 신규 파일이므로 AGENTS.md의 Codegraph 영향도
생략 조건에 해당한다. 별도 PR 없이 전체 복구·동시 쓰기 수용 단위에 합성한다.

성공은 immutable artifact에 묶인 관측값의 순수 복원이다. 파일·환경·SDK·HTTP·DB
조회나 새 시계 생성은 없다. EOF의 실제 전체성, pins의 코드/SDK 출처, member UUID,
root/member/fence와 영속 bytes의 결박, lease, findings, postprocess 완료와 운영 수용은
별도 control/apply 경계가 담당한다. collector 연결과 활성화는 0이다.

## 고정 API와 envelope

`encode_airport_observation_context(artifact_bytes, pins=..., root_run_id=...,
observation_generation=..., upstream_eof=..., geo_stats=...)`는 canonical bytes를 반환한다.
`decode_airport_observation_context(raw, artifact_bytes, expected_pins=...,
expected_root_run_id=...)`는 artifact와 원 관측값을 가진 `RestoredAirportObservation`을
반환한다. mutable DTO와 Stats는 독립 복원하며 이후 caller가 독점 소유한다.

Envelope의 정확한 12키는 `version`, `domain`, `artifact_sha256`, `pins`,
`root_run_id`, `observation_generation`, `upstream_eof`, `validation_mode`, `dropped`,
`source_observations`, `validation`, `geo_stats`다. version은 정수1, domain은
`airport-snapshot-observation-v1`, validation_mode는 `strict`, dropped는 정수0,
upstream_eof는 명시 bool True만 지원한다. source_observations는 decode한 완전한 tuple
길이이며, artifact_sha256은 전달한 artifact 전체 bytes의 SHA256이다.

pins는 기존 codec의 정확한 9키다: `code_revision`, `sdk_inventory_sha256`, `provider`,
`dataset_key`, `source_entity_type`, `normalizer_revision`, `geo_domain`, `clock_domain`,
`native_domain`. expected pins와 root가 다르면 거부한다. source/member UUID는 이
context에 중복 저장하거나 추론하지 않는다.

root는 exact str·UTF8 1..128B·printable·앞뒤 공백 없음이며 내부 `::retry:`를 허용하지
않는다. generation은 exact str·UTF8 최대160B이며 root와 같거나 `root::retry:N`이다.
N은 leading zero 없는 양의 정수이며 PostgreSQL bigint 범위를 넘지 않는다.
현재 retry 횟수로 원 generation을 재생성하지 않는다.

## 원 clock과 전체 검증

모든 bundle record의 fetched_at가 ISO 값·fold·timezone identity까지 같아야 한다.
UTC singleton, 이름 있는 builtin fixed offset, Asia/Seoul ZoneInfo의 경계를 보존하고,
복원값은 artifact의 원 datetime이다. context에 별도 fetched_at를 기록하지 않는다.

실제 `validate_feature_bundles_address`를 실행해 total이 tuple 길이이고 error_count가0일
때만 지원한다. validation에는 total/issue_count/error_count/warning_count와
full_summary_sha256을 저장하고 decode 때 모두 재현한다. hash는
`airport-validation-full-v1` domain으로 전체 summary의 total/issue_count/error_count/
warning_count/evidence_grade_counts/name_state_counts/issues를 묶는다. 모든 issue의
feature_id/source_record_key/code/severity/message/provider_address/bjd_code/sigungu_code를
포함한다. `as_metadata`의 향후 절단·표본 정책에 의존하지 않는다. 현재 정본
as_metadata는 모든 issue를 반환하지만 이를 hash 계약으로 사용하지 않는다.
경고를 오류나 성공으로 바꾸지 않고 실제 전체 summary를 반환한다.

## Geo 통계와 예산

geo_stats는 JSON null 또는 calls/failures/empty/reuse/observed_data_tokens의 정확한
5키다. 실제 GeoCallStats exact class, builtin Counter와 builtin set만 지원한다.
Counter의 누락 키와 명시0을 보존하고 새 Counter/set으로 복원한다. 고정 endpoint 및
reuse 키만 허용하며 각 수와 Counter 합은 0..PostgreSQL bigint다. 관측 token은 최대32개,
각 `dd1-`와 32hex 형식이며 artifact Geo observed set과 정확히 같아야 한다.

Stats None은 Geo None 또는 Geo observed None일 때 지원한다. Stats empty set과
artifact Geo empty set도 지원하지만 Geo observed None과 혼합하지 않는다. codec이
지원하는 artifact frozenset은 첫 context 범위에서 Stats builtin set과 결박하지 못하므로
명시 미지원이다. mutation으로 만든 Stats token None, 외부 Counter/str/int subclass는
hook 호출 전에 거부한다. HTTP 호출 실적의 진실성은 이 순수 복원으로 증명하지 않는다.

전체 context는 envelope 포함 UTF8 최대8192B, JSON parse 전 깊이8/lexical node256으로
제한한다. 중복 키·NaN·잘못된 UTF8·extra·비정규 bytes를 거부한다. variable 원 입력은
각각 작은 타입/길이/키/수량 한도를 먼저 확인한다. artifact는 기존 1MiB/2730/깊이64와
Airport subset 한도를 올리지 않고 기존 decoder로 확인한다. validation과 tokens,
clock, pins 또는 artifact가 바뀐 context는 전체 canonical bytes 비교에서 거부한다.

## 실제 순수 결과와 한계

신규71 unit가 5.21초에 모두 통과했다. 실제 public TransportAirport→기존 native converter의
synthetic15를 사용했다. 정상 샘플은 artifact49,954B/context1,093B이고 경고 샘플은
artifact50,524B/context1,095B였다. 후자는 실제 validation warning15/issue15/error0이며
encode/decode의 전체 issue와 hash, metadata가 같다. 이 크기는 해당 synthetic fixture
한정이며 운영 공항15나 전체 입력 fit의 측정이 아니다.

원 clock·retry generation·artifact SHA·canonical 왕복, Stats None/empty/explicit0와
독립 alias, 원 fetched_at 불일치, validation error, foreign hook0, 키/핀/통계/issue hash
변조와 입력 예산을 검증했다. full summary와 issue projection은 정본 필드 전체를
기계적으로 대조했다. 첫64 PASS/5.88초와 첫 Ruff6개 형식 실패는 별도 원로그로
보존하고 own import/분리 assertion을 고쳤다. 최종 Ruff2파일과 strict mypy1파일은
통과했다. 기존 codec891d 및 공유 파일 변경은0이다.

아직 두 독립 source 리뷰, 전체 단위 합성 CI, durable 등록/apply/완료 처리와 실제
재시작 경로는 수용하지 않았다. 이 checkpoint의 PG·운영·외부HTTP·SDK 재호출은0이다.
EOF=True는 호출자의 명시 관측이며 전체 원천을 새로 증명하는 권위가 아니다.
