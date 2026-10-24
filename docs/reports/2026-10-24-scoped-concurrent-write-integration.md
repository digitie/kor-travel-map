# ADR115 구현 합집합 수용

초안 #1379는 #1371~#1378, #1380·#1381의 검토된 구현을 통합한다. 기능별 작은 PR·
독립 리뷰·실패/수정 증거를 보존하고 같은 코드 조합에서 실제 DB와 HTTP/UI를 확인한다.
이 합집합을 전체 collector/Geo/지역/identity 전환 완료로 보지 않는다.

## 소스와 문서 합성

제품 고정점은 `ebb62ccb80081cf5b13384273d2862a218f3798c`, schema는
`414_manual_dedup_protocol`이다. 이후 문서 정산은 제품 파일을 바꾸지 않는다.
추적 파일 2,298개를 부모들과 대조했다. 제품 파일은 한 파일을 제외하고 승인된 부모 중
하나와 blob이 같다. 유일한 합성 `infra/feature_repo.py`는 승인 native `e9554ab5`의 전체
본문에 #1380 전화 setter의 첫 gate 두 줄만 더한 것임을 byte 단위로 확인했다. 임의의
다른 source 병합을 수용하지 않았다.

공통 journal/resume 충돌은 날짜 항목 단위로 합쳤고 양쪽 원문의 모든 전체 항목이 결과의
부분수열임을 검사했다. `tasks-acceptance.md`는 양쪽 설계 변경을 함께 보존했다.
새 API/DTO 변경은 없으며 기존 reader 계약·원래 typed procedure/ACL을 유지한다.

## 검증 현황

초기 합집합 `071a7443`의 단위·실제 PG 집중145건이 123.97초에 통과했다. 여기에는 커널,
legacy fence, scalar winner, native, 실제 SIGKILL, SQL 직접 진입, 두 reader 회귀가 있다.
414와 두 caller gate를 합친 최종 집중 **175 passed(151.30초)**, 공식 oracle/metadata
**2 passed(22.80초)** 및 독립 교차 리뷰2인을 통과했다. 초기145에 새 범위가 포함됐다고
세지 않는다. Ruff·strict mypy(메인172/API·Dagster109파일)·import-linter4계약도 통과했다.
전체 lint의 첫 실행은372 passed/6기존skip와 문서 task 본문 길이1실패였다. task 사이의
새 안내가 이전 task 본문으로 계산된 원인을 제거한 뒤 전체 lint는
**373 passed/6 기존 skipped(51.74초)**로 통과했다. 원본 실패 로그는 보존한다.
정확 CI·최신 실제 HTTP/UI·머지/운영 수용은 아직 미완이다.

실제 worker SIGKILL은 #1378 전용 PG1건으로 입증했고, M05 실제40P01 재현·보강은 #1381의
PG8+unit4건으로 입증했다. 이 회귀를 전체 Dagster 감독/새 owner 인계/DB·host 사망이나
지역 이동 복구로 합산하지 않는다. 제한 측정 elapsed 273.81→158.42ms와 PG CPU 약4.2%
증가는 별도 작은 amd64 표본이며 운영 CPU 절감의 증거가 아니다.

기본 OFF·정책 seed0·운영 활성화0이다. [수용 현황](2026-10-24-scoped-concurrent-write-acceptance-status.md)의
미완 gate와 T-CWRITE 체크박스는 전체 acceptance 전까지 유지한다. Map에서 검증된 개선의
Weather/Transport 전파는 후속이며, 취소된 export 운영 활성화/Map 연동 검증은 재개하지 않는다.

## 전체 CI의 시험 격리 실패와 수정

`b460d5167`의 전체 CI는 OpenAPI·lint·frontend·Docker 4 workflow와 Python3버전/fixture를
통과했지만 실제 PostgreSQL 두 lane가 같은5건에서 실패했다. glibc는1425 passed/12 skipped/
5 failed, alpine은1419 passed/18 skipped/5 failed였다. coverage87.55% 통과나 기준선
artifact 업로드로 이 실패를 덮지 않는다. 두 원본 job 로그·해시를 감사 원장에 보존했다.

4건은 기존 `get_session`만 시험 연결로 대체하고 새 `get_read_snapshot_session`을 연결하지
않아 발생했다. 실제 제품의 DSN/권한/RO·RR 설정은 바꾸지 않고 기존 seed와 같은 fixture
연결을 새 dependency에도 연결한다. 남은 metrics 1건은 session-scope DB에 앞선 시험이
commit한 행을 무시하고 전체건수를1로 고정한 기대값 때문이다. 0/2 committed sibling을
추가한 수정전 제어군은2 passed/2 failed로 `3 == 1` 실패를 실제 재현했다.

수정은 주입 전의 전체 lifecycle total과 active kind별 기준값을 각각 읽고, 같은 writer가
commit한 place1건을 RC만 보는 반증과 RR의 이전 snapshot을 전체 dict로 비교한다.
주입 뒤 별도 연결에서 실제 total+1·place+1도 확인해 쓰기 실패를 RR 성공으로 세지 않는다.
기대값을3으로 바꾸거나 원래 검증을 삭제하지 않았다. 제품/DDL 변경은0이며 수정 후 정확
집중 PG·독립 리뷰와 새 전체 CI가 별도 수용 조건이다.

수정 커밋 `c5b63536325e7bf4c3c2cb9a079828f046bfb920`은 시험3파일만27줄 추가/4줄 삭제다.
수정 뒤 실제 PG/ASGI4파일 **48 passed(120.45초)**이며 기존 reader13과 실패가 발생한
후속 reader/지표/API fixture를 포함한다. 별도 성공 수를 초기175에 합산하지 않는다.
Ruff·redaction·diff 검사도 통과했다. 제품/DDL blob은 b460과 동일하므로 실제 UI는 최종
문서 정산 후 같은 제품의 정확 archive로 검증한다. 새 전체 CI와 실제 UI는 아직 미완이다.
