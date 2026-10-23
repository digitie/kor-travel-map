# 수집 쓰기 fence 재진입 왕복 절감 — ADR115 선행 코드

## 범위

기준 main은 `974e2d0258c53efdffaa1446abed30603d0c72a3`이다. 기존 snapshot spool은
upstream 수집·역지오코딩을 쓰기 transaction 밖에서 끝낸다(ADR113). 그 뒤 load_bundles,
load_bundle, source/link/Feature helper가 같은 transaction에서 전역 fence SQL을 반복한다.
전역 fence의 이름·획득 순서·충돌 범위를 유지하며 이미 획득한 transaction의 재진입만 줄인다.

이 코드는 T-CWRITE-01의 안전 선행 개선이다. dataset/지역 간 실제 DML 동시 쓰기,
후보 원장·결정적 필드 winner·scope epoch/manifest·reader 일관성은 아직 구현 완료가 아니다.
T-CWRITE-01 전체 운영 기준선과 T-CWRITE-02~09 checkbox는 닫지 않는다.

## 수명과 실패 규약

- 실제 AsyncSession의 성공한 fence SQL 뒤에만 session.info에 단일 증거를 남긴다.
- session root/획득 savepoint와 실제 DB connection root/획득 savepoint를 함께 확인한다.
  bind 변경·연결 invalidation·commit/rollback·새 transaction이면 이전 증거를 쓰지 않는다.
- root에서 잡은 fence는 하위 savepoint rollback 후에도 유효하다. 획득한 savepoint가
  끝나면 보수적으로 다시 SQL을 실행한다. rollback은 잠금을 놓고 release는 보존하지만
  두 경우 모두 검증을 단순하게 재획득한다.
- SQL 실패·취소에는 성공 증거를 기록하지 않는다. 첫 획득의 한정된 긴 대기 및 timeout
  복원 규칙은 유지한다. 다른 writer가 같은 fence를 잡는 동안은 여전히 대기한다.
- 후보/winner·identity·source head·link·override·seal의 의미나 권한은 바꾸지 않는다.

## 실행 증거와 한계

- 기존 대기 정책·snapshot spool·SQL trigger 잠금 순서 집중 시험 27 PASS.
- 실제 PostgreSQL의 신규 경계 8 PASS: root 50회→fence SQL 1회, commit/rollback 뒤
  재획득, root와 savepoint 소유 구분, 외부 connection 종료, 실패·취소 뒤 재시도.
  다른 세션의 pg_try_advisory_xact_lock으로 실제 배타성/해제를 확인한다.
- 변경 파일 Ruff 및 feature_repo strict mypy PASS. 전체 Ruff에는 기준 main에 있던
  docs/handoff/n150-scripts/dagster-job-status.py 및 scripts/check_journal_update.py의
  기존 경고 7건이 있다. 이 PR에서 관련 없는 파일을 고치지 않는다.
- codegraph 영향도는 기존 fence가 도달하는 392 node/391 edge로 확인했다.
  전체 회귀·CI·두 독립 리뷰·실제 HTTP/UI·운영 CPU/RAM 전후 수용은 별도이며 아직 미완이다.

50회→1회는 helper 재진입의 SQL 건수다. 전체 수집 CPU 98% 저감이나 dataset 동시 쓰기
달성을 의미하지 않는다. 실제 수집 입력에서 fence 보유 시간·DB round-trip/CPU를 측정한 뒤
후속 후보 원장과 scope gate 구현으로 이어간다. 운영 쓰기·배포는 수행하지 않았다.
