# ADR115 실제 동시 쓰기 수용 현황

2026-10-24의 구현·증거를 단계별로 구분한다. 이 문서는 ADR115와 T-CWRITE-01~09의
전체 완료 선언이 아니다. 각 PR의 최신 정확 커밋 CI를 확인하고 부모부터 수용해야 한다.
feature branch를 base로 둬 CI가 발행되지 않은 상태는 통과가 아니다.

## 구현과 검증

| PR | 구현 범위 | 확보한 증거 | 남은 수용 |
| --- | --- | --- | --- |
| #1370 | 격리 직렬 기준선 | 두 독립 리뷰·정확 CI·두 PostGIS lane 통과 후 머지 | 전체 운영 기준선·동시 쓰기의 증거는 아님 |
| #1371 | 411 scope/epoch/manifest·membership 재검증, 기존 writer protocol→global 순서 | 실제 커널·bootstrap·메타데이터·기존 fence, 두 독립 리뷰 | CI에서 발견한 잠금 관측 시험을 고친 정확 HEAD의 전체 CI |
| #1372 | 순수 multi-SELECT reader 29개, 별도 read-only RR·인증 세션 | 실제 순서 반전·pool1·권한·세션 정리, 두 독립 리뷰 | 새 읽기·인증 세션 fixture 수정 뒤 정확 전체 CI |
| #1373 | 412 기존 primary Feature의 명시 name/phones winner | 실제 PG16·unit18·lint369/기존skip6·공식 oracle/metadata2, 두 독립 리뷰 | #1371 시험 수정 통합 뒤 정확 전체 CI·통합 수용 |
| #1374 | 후속 GET 13개 | 실제 PG11·순수 읽기 RR, 행 잠금 GET의 RW/RR·40001→503 후 새 요청 복구, 두 독립 리뷰 | 부모 머지 후 main 재기반·정확 CI |
| #1375 | 제한 native source/head→후보→winner→완료 receipt | 단위4+native PG5+기존 lineage1, 독립 TX의 미커밋 source 쓰기 중첩·예외/취소 rollback·동일 입력 재시도, 두 독립 리뷰 | 전체 collector 배선·실제 프로세스 사망·정확 CI·운영 |
| #1376 | 제한 native 직렬/병렬2 비용 runner | 각 fresh clone 3회·동일 출력/receipt hash·별도 미커밋 중첩 probe·정확 자체 자원 정리, 두 독립 소스 리뷰 | main 재기반·정확 CI, 대량/공유 Feature/운영 ARM 수용 |
| #1377 | 413 기존 SQL 직접 호출 7개의 첫 protocol EX | 단위/실제 PG/전체 lint407·기존skip6, 공식 oracle/metadata2, 타입 정리 뒤 PG/unit29, 두 독립 리뷰 | main 재기반·정확 CI, 나머지 SQL writer와 mixed binary 전수 수용 |

실제 Chromium·BFF/API·PostgreSQL 수용은 reader/kernel 합집합에서 12건 통과했다.
실제 로그인·파일 목록/상세/검색·issues·datasets·metrics·Feature 상세·모바일·로그아웃을
확인했고 page error·비의도 쓰기·예상 밖 HTTP 오류는 0건이었다. 이 증거는 지도 타일,
가격 지도 클릭, native writer/413 운영 전환 또는 모든 수집기의 UI 수용을 대신하지 않는다.
이후 #1371/#1372 수정은 시험 파일뿐이고 관련 제품 blob은 해당 UI 세대와 같다.

## 실측의 의미

작은 amd64 fixture(2dataset·2record, 각 모드 3회)에서 직렬→병렬2 중앙값은
273.81→158.42ms였다. PG CPU는 237.85→247.94 core-ms로 약4.2% 늘었으므로
CPU 절감은 입증하지 못했다. 메모리 100ms 표본은 실제 peak 보장이 아니며 운영 ARM,
전체 provider·Geo·API p95를 대표하지 않는다. 원시 해시와 한계는
[측정 보고서](https://github.com/digitie/kor-travel-map/blob/c91bb31164ad89936f2b61095d67953638445f44/docs/reports/2026-10-24-scoped-native-scalar-measurement.md)에 있다.

정적 [SQL writer inventory](2026-10-24-scoped-sql-writer-inventory.md)는 235개 routine과
Python caller·trigger를 분류했다. 정적 후보 수를 독립 writer 수나 실제 장애 재현으로 세지
않는다. M05 역순의 실제 재현·수정과 state/override/identity/catalog 경계는 후속이다.

기존 시험의 `worker-loss` case는 RuntimeError/CancelledError 주입 후 정상적인 context
rollback이다. 실제 OS 프로세스 사망으로 세지 않는다. 별도 SIGKILL·PG 연결/잠금 해제·
동일 artifact 재시도·완료 receipt 중복 방지 검증은 후속으로 진행한다.

## 전환 조건과 후속 전파

모든 T-CWRITE 체크박스는 전체 수용 전까지 미완이다. 특히 SQL/trigger/Python writer 전수
목록, 활성 policy 의미의 전체 writer 지원, 신규 identity·membership·Geo·지역 이동,
root/catalog·중단/재계획·실부하와 배포/되돌림 훈련은 남아 있다. 기본 OFF·정책 seed0·
운영 활성화0을 유지하며 배타 gate만 추가했다고 의미 프로토콜이 완성됐다고 보지 않는다.

Map의 해당 개선을 수용한 뒤 Weather·Transport의 실제 저장·복구 경로와 대조하여 적용한다.
공통 재시도/실행 소유권/자원 제한은 kor-travel-common을 우선 재사용하되 Map 전용
Feature/membership/winner 표를 복제하지 않는다. 각 서비스에서 이미 있는 원자 CAS·범위 잠금을
중복 도입하지 않고 전후 CPU·메모리·실패 복구를 다시 측정한다.

사용자가 취소한 Weather·Transport export 운영 활성화·Map 연동 검증은 재개하지 않는다.
이번 Map 동시 쓰기 요청을 해당 schedule enable 승인으로 해석하지 않는다.
