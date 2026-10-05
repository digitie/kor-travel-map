# Map summary tick 조회 개선안 독립 검토

검토일: 2026-10-06. 판정은 제안된 두 GraphQL literal 변경의 좁은 계약·실제 읽기 전용 진단 기준 PASS이다. 새 제품 후보 FULL 리뷰나 새 rebuild/live 성공 판정은 아니다. 제품 파일, 운영 프로세스 설정 및 shared DB는 수정하지 않았다.

권고: overview에서 ticks를 없애는 대신 ticks(limit:3, statuses:[STARTED,SKIPPED,SUCCESS,FAILURE])를 scheduleState와 sensorState 두 곳에 사용한다. 현재 설치 schema의 모든 tick 상태를 명시하므로 최근 tick의 상태·시간·오류 정보를 유지하면서 전체 history의 batch window 경로를 회피한다. Common UI/DTO를 바꾸지 않는 가장 작은 개선안이다.

소스 및 UI 계약 확인:

- Map summary query는 scheduleState와 sensorState 각각 ticks(limit:3)를 조회한다.
- parser는 recent_ticks를 보존하고 Map Common panel은 첫 tick을 lastTick으로 변환한다. Common sensor 표와 schedule 상세는 해당 상태·시간을 표시한다. sensor의 최근 오류를 사용하는 별도 schedule-panel도 존재한다.
- 기존 DTO recent_ticks는 빈 배열 기본값이며 tick 조회 여부를 별도로 표현하지 않는다. 따라서 단순 tick 생략은 '조회하지 않음'을 '빈 이력'과 구분하지 못한다. unknown 필드·UI 설명 없이 생략하는 안은 권고하지 않는다.
- tick 후속 조회를 추가하는 분할안은 예산/부분 실패/캐시 merge 계약을 새로 요구하므로 이번 직접 원인을 해결하는 최소 변경보다 크다.

직접 실제 endpoint 검증:

1. 실제 설치 GraphQL introspection의 InstigationTickStatus enum은 정확히 STARTED, SKIPPED, SUCCESS, FAILURE 네 값이었다. InstigationState.ticks의 statuses 인자는 해당 enum의 list였다. introspection errors=0.
2. 실제 Map API 컨테이너의 별도 python exec 프로세스에서 query 문자열 두 occurrence만 메모리로 바꿨다. 실행 중 API 서버의 전역 값이나 소스 파일은 바꾸지 않았다.
3. 기존 실제 get_summary와 기존 bounded HTTP/client 계약으로 호출한 결과 status=ok/errors=0/2.077초, repository1/jobs39/schedules30/sensors10/recent runs30이었다. 반환된 ticks는30개, state당 최대3개, 실제 상태는 SKIPPED였다.
4. 원래 full query는 별도 진단에서 HTTP500/15.151초, sensorState.ticks의 DB statement timeout이었다. tick을 두 곳 모두 생략한 진단은0.094초에 core counts/state를 얻었으나 ticks가0개였으므로 생략안을 최종 권고로 삼지 않는다.

primary 구현 검토: 같은 실제 설치 버전 Dagster GraphQL 1.13.24의 get_instigation_ticks는 nonempty statuses이면 repository batch loader를 사용하지 않고 instance.get_ticks(origin,selector,limit,statuses)를 호출한다. SQL get_ticks는 selector 및 legacy NULL-selector origin 조건과 timestamp DESC에 limit을 적용한다. get_batch_ticks는 selector별 전체 history에 rank window를 계산한 뒤 rank<=limit을 적용한다. 제안안은 SQL 이력 전체를 Python으로 읽는 우회가 아니다.

본인 로컬 실제 API/SQLite 검증: Dagster1.13.24의 새 own cache instance에 각 TickStatus 한 건씩 서로 다른 timestamp로 작성했다. 상태 필터 없는 limit3과 네 상태를 명시한 limit3의 tick ID가 동일했고, limit4에서는 네 상태 전체가 포함됐다. 가짜 batch loader는 호출되면 예외를 내도록 설정했으며 실제 get_instigation_ticks(all4 statuses)는 batch 호출 없이3개를 반환했다. 최초 테스트 fixture는 SUCCESS TickData의 run_ids=[]를 누락해 ParameterCheckError가 났으며 본인 fixture만 수정한 뒤 위 검증이 통과했다.

메모리·실패 의미: HTTP4MiB cap/10초 deadline, selector 필터, active cap1000 및 recent limit30은 그대로 유지한다. 결과 tick도 state당 limit3으로 제한한다. per-selector 호출은 상태 수에 따라 DB 조회 수가 늘지만 현재 actual40개 state의 전체 결과가2.077초였다. 향후 규모나 DB 응답 악화 시 기존 timeout/unavailable/error 계약을 유지해야 하며 정상 ok로 강제해서는 안 된다.

호환 범위: 현재 enum 네 값을 모두 포함하므로 유효 상태의 필터 의미를 보존한다. 다만 batch rank의 timestamp 동률에서3개 초과 반환 가능성과 direct LIMIT3, legacy NULL-selector 이력 포함 여부는 완전한 동일 결과를 보장하지 않는다. strict 최근3 의미와 기존 storage legacy 호환을 확인하는 테스트가 적절하다. 향후 Dagster enum 값이 늘면 '전체 상태' 상수·계약 검증도 함께 갱신해야 한다.

실행 경계: 승인된 actual 컨테이너 함수/network read 및 own SQLite 쓰기만 수행했다. 제품/DB schema/index/history cleanup/운영 환경·서비스 변경, native job 실행 및 UI gate는 NOT_RUN. 새 제품 변경이 고정되면 두 독립 FULL source 리뷰, 테스트, 새 rebuild 및 live 검증이 필요하다. 원래 장애 진단 원문은 별도 불변 보존한다.

본인 local 재현 사본: /home/digitie/.cache/recovery-map-tick-status-probe.py. 실행 Python: /home/digitie/.cache/map-common-recovery-venv/bin/python. 실제 endpoint 원문·URL·DSN·credential·SQL parameter는 이 보고서에 저장하지 않았다.
