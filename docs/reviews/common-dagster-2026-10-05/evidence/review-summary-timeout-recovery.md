# 운영 Map Dagster summary unavailable 독립 진단

검토일: 2026-10-06. 사용자가 승인한 범위에 따라 실제 Map API 컨테이너 내부 application service 및 GraphQL 읽기 전용 조회를 수행했다. 제품·운영 설정·DB·서비스는 수정하지 않았다. native/UI 실행이나 성공 증거 수집은 수행하지 않았다.

진단 판정: 실제 unavailable의 직접 원인은 sensorState.ticks 조회에서 DB statement timeout이 발생하고, API의 bounded helper 10초 제한이 먼저 끝나는 경로다. repository/code location 건강 실패, 압축 응답, selector 불일치 또는 native fault 결과로 오인하지 않는다.

직접 확인:

1. 실제 API 컨테이너의 ApiSettings에서 dagster_request_timeout_seconds=30.0을 확인했다. URL·환경·자격증명은 출력하지 않았다.
2. 실제 summary query와 같은 변수/selector로 dagster_graphql.post_graphql을 호출했다. httpx.ReadTimeout으로 약10.012초에 실패했다. 같은 client 수명 계약으로 get_summary를 호출하면 data.status=unavailable이었다.
3. 같은 내부 endpoint에 Accept-Encoding identity를 명시한 읽기 전용 query를 보내 응답을 분리했다. version만 조회하면 HTTP200/0.058초/오류0, selector repository+pipeline만 조회하면 HTTP200/0.037초/오류0였다.
4. 동일 full summary는 HTTP500/15.151초/GraphQL 오류1, JSON7214bytes, content-encoding 없음이었다. 응답 본문은 출력하지 않았고 safe class name OperationalError를 추출했다.
5. 재조회한 서버 오류의 안전한 error path는 repositoryOrError → sensors → 0 → sensorState → ticks였다. 알려진 고정 오류 문구의 존재만 검사하여 canceling statement due to statement timeout을 확인했다. data=null이고 extensions.errorInfo가 존재했다. 스택 파일 basename은 sql_schedule_storage.py, fetch_ticks.py, loader.py, scheduling_methods.py 등이다. SQLSTATE는 확인되지 않았다.

소스 경로와 동작:

- packages/kor-travel-map-api/src/kortravelmap/api/routers/ops_pipeline.py:1601은 summary application service를 호출한다.
- dagster_query_service.py:67–81의 sensorState.ticks(limit:3)가 실패하는 실제 field다.
- dagster_graphql.py:838은 bounded_request에 명시적 전체 timeout을 넘기지 않는다.
- dagster_query_service.py:311–329는 HTTPError/ValueError를 잡아 unavailable의 안전한 envelope로 변환한다.

영향: 실제 UI summary의 status=ok 조건은 충족되지 않았다. 서비스가 건강하더라도 schedule storage query가 느리면 상세 summary를 얻지 못한다. 정상 최소 repository 조회와 장애가 난 tick query를 분리하여 확인했으므로 문제를 UI 로그인/cookie나 repository 자체의 로드 실패로 해석할 근거는 없다.

권고: 같은 full query를 반복하여 DB 부하를 늘리거나 단순히 전체 deadline을 늘리는 것보다, 해당 sensor tick SQL의 인덱스·실행 계획·데이터 규모를 읽기 전용으로 확인해야 한다. 현재 저장된 증거만으로 인덱스 누락, 특정 planner 선택 또는 데이터 증가 원인까지 단정할 수 없다. ticks가 없어도 핵심 repository 상태를 표시할지의 변경은 별도 제품 결정과 검증이 필요하다. 현재 source의 unavailable 반환은 실패를 정상 ok로 표시하지 않는 계약을 유지한다.

실행 방법: 승인된 SSH를 통해 actual Map API 컨테이너에서 python으로 ApiSettings, dagster_query_service와 dagster_graphql의 실제 함수를 호출했다. 별도 httpx AsyncClient에서 query-only GraphQL POST를 사용했다. 원격 stdout은 safe JSON만 전달하고 원래 exception 문자열, URL, host, DSN, credentials, SQL parameter 및 전체 payload는 출력하거나 이 보고서에 저장하지 않았다. raw 진단 응답은 16KiB 이하만 읽었다.

수행한 것과 미수행한 것: 실제 컨테이너 함수/실제 network read 수행. DB 연결을 통한 별도 SQL/EXPLAIN, index/schema 변경, 설정 변경, 작업 launch, native 실행 관찰 및 UI 성공 수집은 NOT_RUN. 기존 제품 FULL source PASS 및 운영 rebuild 증거 원문은 변경하지 않는다. 이 보고서는 summary 조회의 현재 실제 장애에 대한 한정 진단이다.
