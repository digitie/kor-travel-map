# 제한 scalar 갱신의 같은 의미 배타 실행

## 문제와 범위

ADR115 §8은 세분화 flag OFF에서도 후보 갱신·active winner·projection 의미를 유지하도록
요구한다. 기존 legacy loader는 활성 source link의 동일값 UPSERT도 거부되며, 현재 제한
native helper는 SH를 먼저 획득하므로 EX manifest로 호출하면 승격23514를 낸다. 따라서
legacy로 돌아가거나 EX plan만 기존 helper에 전달하는 방식은 같은 의미의 배타 실행이 아니다.

`refresh_exclusive_provider_scalars`를 별도 내부 진입으로 추가한다. 기존
`refresh_scoped_provider_scalars`의 signature와 SH 동작은 유지하고 source/head→후보→winner→
완료 receipt 본문을 한 private 함수로 공유한다. EX 진입은 정본 `lock_feature_curation_write`로
protocol EX→기존 전역 fence를 먼저 획득하고, 이후 policy epoch→begin 정렬 잠금→대상 재검증을
따른다. SH는 기존 protocol SH를 유지한다. 두 모드 모두 sealed attempt의 mode와 일치해야
하며 region 없는 기존 primary place·명시 name/phones·동일 artifact 검증만 지원한다.

이 진입은 **일반 collector fallback이 아니다.** 주소/Geo·신규 identity·link·retire·지역·파일과
그 외 bundle 의미를 지원하지 않는다. helper를 호출하기 전 적격성·지원 외 필드 불변을 증명할
planner, 안정 identity 제공자, 전체 snapshot seal, 영속 fetch artifact와 worker 인계는 후속이다.
DB 정책을 끄거나 guard를 우회하지 않으며 DDL·DTO·OpenAPI·API/프론트·기본 설정 변경0이다.
새 진입은 실제 수집 경로에 연결하지 않고 policy seed/운영 변경0을 유지한다.

## 실제 검증

신규 실제PG6개(예외/취소 매개변수 포함), 기존 native5개와 artifact4개를 같은 최종 실행에서
합쳐 **15 PASS/29.68초**다. 앞선 독립 실행과 중복 합산하지 않는다. owned PostGIS는 기존 정본
scalar fixture의 고유UUID·local daemon·2CPU/1.5GiB/PID256 제한과 finally 정리를 사용한다.

- SH와 EX가 같은 원천 artifact에서 같은 raw/hash·관측 clock·후보 value/availability/reason·
  검증 hash/clock/normalizer·name/phones projection을 생성한다. 각기 다른 고유 dataset의
  UUID/record key를 동등 의미 비교에서 제외하며 해당 실제 lineage 경계는 기존 native 시험과
  DB guard가 검증한다.
- EX의 정확 protocol key/PID `ExclusiveLock`와 기존 curation 전역 advisory를 확인한다.
  독립 dataset의 실제 SH writer가 정확 같은 protocol key에서 EX backend에 대기하며,
  EX transaction 종료 뒤 적용을 완료한다. 이 시험은 EX의 직렬화 증거이며 SH 동시성이나
  CPU 절감의 새 증거로 세지 않는다.
- 실제 source DML 직후 예외/취소 주입은 old head·후보·projection으로 rollback된다.
  같은 EX attempt/artifact 재시도 뒤 성공하고 완료 receipt 재호출은 source DML0이다.
  정상 context rollback 시험이며 OS worker 사망으로 부르지 않는다.
- 실제 SH blocker가 만든55P03 뒤 old head/후보/projection 불변과 fresh TX의 같은 artifact
  복구를 확인한다. EX plan을 SH 진입으로 대체하면 기존23514, SH plan을 EX 진입으로 대체하면
  ValueError 뒤 전체 rollback되며 원래 mode 진입으로 성공한다. 같은 TX 승격을 허용하지 않는다.

처음 Ruff의 복합 assert1건은 PG 실행 전에 두 assert로 나눴고 제품 의미 변경은 없었다.
전체 lint373 PASS/기존6skip(28.18초), strict mypy1·Ruff·import4계약도 통과했다.
정확 CI·독립 적대 리뷰2명·최신 실제 UI/HTTP와 운영 수용은 아직 후속이며 기존418 UI를
이번 새 내부 entry의 호출 증거로 사용하지 않는다.
