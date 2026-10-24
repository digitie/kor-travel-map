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
