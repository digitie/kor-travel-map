# ADR115 실제 동시 쓰기 구현 진행

## 검증된 출발점

기준선 PR [#1370](https://github.com/digitie/kor-travel-map/pull/1370)은 2026-10-24에
머지됐다. 검증한 후보는 `2a53dce7cabfa594ce2a699550ae5dafe78b37ad`, 머지 커밋은
`1b7abe3257a513f8ffb9e8dba8ed50ac8c71bc69`이며 두 tree는 같다. 두 독립 리뷰의
미해결 P0/P1/P2는 0건이다. 정확한 후보의 다섯 CI workflow가 모두 성공했다.
실제 PostGIS glibc는 1,312 passed/12 skipped, alpine은 1,306 passed/18 skipped다.
skip은 해당 lane의 기존 분기이며 새 동시 쓰기 검사를 건너뛴 결과가 아니다.
두 artifact의 checkout `7dbe8ae5411a3256cdc3cc086a7a3f5b725b9117`와 후보 tree,
runner/fixture 해시·schema 410·runtime ACL·12개 측정 phase를 별도로 대조했다.

이 결과는 4개 점으로 만든 synthetic fixture의 **기존 직렬 쓰기 기준선**이다.
warm은 동일 입력 replay여서 cold와 실제 DML량이 다르다. 이를 cache 효과나
운영 ARM의 CPU/RAM 개선율로 해석하지 않는다. 두 수집의 fetch만 병행한 결과를
독립 DML 중첩으로 세지 않는다. 운영 쓰기·정책 seed·잠금 세분화 활성화는 없다.

## 이번 구현의 소유권과 의존 순서

1. T-CWRITE-02: 현재 shadow에서 모든 활성 source/head의 후보 완전성, 명시된
   정책만 사용하는 결정적 scalar winner와 base/effective 물화, legacy 직접 patch의
   우회 거부를 구현한다. Geo 일관 그룹 증거와 provider rank를 추측하지 않는다.
2. T-CWRITE-03: dataset/region/attempt anchor, 단조 epoch, 제한된 manifest와
   공유/배타 protocol gate를 additive migration으로 구현한다. 단독 kernel의
   테스트 성공은 전체 writer/trigger 전환이나 활성화 승인이 아니다.
3. T-CWRITE-01/04: Python·SQL·trigger writer inventory와 잠금 순서를 대조한다.
   API의 순수 다중 SELECT reader에는 첫 SELECT 전 read-only REPEATABLE READ를
   적용한다. 쓰기 또는 lease를 변경하는 GET는 별도로 구분한다.
4. 후보·gate·전체 closure가 연결된 뒤 독립 dataset/정당한 완전 지역의 두 세션
   **실제 DML 구간** 중첩, 공유 Feature 충돌, 역순·실패·취소·재시도와 reader image를
   반증한다. root/catalog/merge와 대량 geometry 경로가 남으면 이를 전수 완료로 세지 않는다.
5. 두 독립 최종 리뷰, 정확한 HEAD의 CI·격리 실데이터/API/UI·동일 입력 3회 실측을
   통과한 범위만 단계적으로 배포한다. 초기 병행은 2개이며 CPU/RAM/API 지연의
   회귀 기준은 ADR115 §9를 따른다.

기존 native writer는 새 의미 프로토콜의 완전성이 입증될 때까지 배타 fallback을 유지한다.
새 공유 gate에서 기존 배타 경로로 승격하지 않고 전체 rollback 후 재계획한다.
원천 수집·지오코딩은 쓰기 transaction 밖에서 하고 저장 재시도는 검증된 artifact를 재사용한다.
새 공개 DTO·provider client facade·Map/Valkey 간 원자적 commit은 만들지 않는다.

## Weather·Transport 전파 조건

Map의 해당 개선이 실제 다중 세션·실패 복구·비용 측정을 통과한 **뒤** 두 저장소를
대조한다. 후보는 제한 retry/deadline, attempt 소유 query 정리, artifact 재사용,
순수 reader snapshot, 변경 없는 값의 DML 생략이다. 공통 정책은 kor-travel-common의
기존 Python 경계를 활용하고 Map의 Feature 전용 후보/claim/curation 모델은 복제하지 않는다.
각 저장소에서 실제 병목과 전후 수치를 다시 측정하며, 기존 수집·이력·통계 API 계약을 보존한다.
Map 연동 export의 운영 활성화·검증 보류 지시는 그대로다.

## 아직 통과하지 않은 수용 조건

T-CWRITE-01~09의 전체 acceptance는 모두 원문을 유지한다. 이번 진행 기록은 체크박스
완료 근거가 아니다. provider 실제 rank·Geo 일관 그룹·모든 membership backfill,
redirect/merge·catalog/root의 전체 closure, 실제 scoped DML·지역 소실/이동,
장애 주입·대량 부하·운영 단계 확대와 Weather·Transport 적용은 후속 수용 대상이다.
