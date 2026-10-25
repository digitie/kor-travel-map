# 공항 snapshot 후처리의 원자적 저장과 제한된 정리

## 구현 범위

- 등록된 원 입력·관측·적용 결과에서 후처리 intent를 다시 검증한다. 기존 발견사항 저장, 원 counter와 수집 시각의 sync cursor, stale 발견사항 정리를 한 READ COMMITTED transaction에 결합한다.
- SQL begin은 실제 완료된 적용과 현재 executor fence를 확인한다. finish는 같은 transaction marker, 실제 authoritative 관측·발견사항 수와 원 cursor를 확인한 뒤 receipt를 저장한다. callback 실패·취소는 전체 rollback하고 commit 응답이 불명확하면 성공을 반환하거나 효과를 자동 재실행하지 않는다. 다음 시도는 SDK0 조회로 저장 상태를 먼저 확인해야 한다.
- 더 최신의 실제 snapshot 적용, authoritative 후처리, 원 source 집합 변경, 더 최신 sync cursor가 있으면 원 관측의 후처리를 거부한다. 단순 세대 예약 후 실패한 새 run은 기존 적용을 대체하지 않는다. 전체 finding 필드 지문과 정확 clock 표현은 정본 Python decoder가 검사하며 SQL은 저장 소속·실제 효과를 따로 대조한다.
- 종결된 root/child, Dagster 종결 확인, 만료된 lease와 마지막 변경 후 7일 경과를 모두 만족하는 임시 snapshot만 한 번에 최대16개 정리한다. 전역 protocol EX 후 전역0→dataset 정렬 순으로 quota를 잠그고 ledger를 함께 반환한다. 활성·미정산 입력 및 원천/Feature/가격/날씨 이력은 대상이 아니다.

## 확인과 남은 조건

전용 transaction/backend 순수 회귀10개가 통과했다. 같은 connection 결합, 부분 실패·취소 rollback, 저장 receipt replay와 commit 응답 손실을 확인했다. Ruff와 제품 Python4파일 mypy도 통과했다. 이 결과는 실제 PostgreSQL 효과나 운영 검증을 대체하지 않는다.

새 SQL은 전체430 migration·명시 ACL·실제 scheduled caller와 함께 합성해야 하며 단독 설치하지 않는다. 실제 PG의 stale executor/새 적용/실패 세대/권한/후처리 atomicity/정리 ledger 시험, 두 적대 리뷰, 전체 CI·live UI 및 운영 배포는 아직 남아 있다. 임시 quota는 메모리·CPU 실측 튜닝 결과가 아니다.
