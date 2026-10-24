# ADR115 격리 source/typed-patch/seal 기준선

T-CWRITE-01의 작은 측정 도구다. 실제 운영 값·수집 속도 개선이나 전체 동시 쓰기 완료가 아니다.
기존 FeatureRepo·global fence·winner·API/DTO는 바꾸지 않는다.

## 고정 입력과 측정 경계

- fixture v1은 공개 데이터가 아닌 synthetic point 4개다. 원문 파일 SHA256으로 입력을 고정한다.
- independent는 두 dataset의 서로 다른 Feature, shared는 두 dataset source가 같은 canonical
  Feature에 붙은 경우다. 임의 Feature UUID 덮어쓰기 대신 기존 source/head/link와 typed patch를 쓴다.
- 두 writer의 실제 global fence 대기, source/typed DML, causal input seal, commit을 나눠 잰다.
  provider HTTP/Geo·전체 load_bundle identity 경로·root finalize·API/UI는 범위 밖이다.
- 전용 testcontainer와 snapshot template의 trial DB를 쓴다. CLI는 외부 DSN을 받지 않는다.
- cold는 전용 PG 재시작 후 shared_buffers 첫 실행, warm은 같은 artifact 즉시 replay다.
  OS page cache를 비웠다고 주장하지 않는다. cold/warm 각 3회가 기본이다.
- worker CPU와 전용 PG container CPU, RSS·memory의 샘플 peak, WAL을 구분한다.
  샘플 peak는 실제 cgroup lifetime peak와 다르며 자료가 없으면 null/사유로 남긴다.

## 현재 checkpoint와 미완

첫 checkpoint는 고정 fixture의 bounded 읽기·검증과 구간 계산·실행 계획을 구현한다.
실제 PG runner/측정·회귀·CI evidence 배선은 이어 구현하며 아직 완료가 아니다.
로컬 DB/container·운영 접속은 하지 않았다. 결과 수치는 실제 실행 뒤 PR 수용 기록에 남긴다.

T-CWRITE-01의 writer/trigger 전수 inventory·실분포/geometry·API/UI 기준선은 별도 미완이다.
후속 T02 membership/backfill·winner, T03 scope/epoch/gate, T04 실제 DML 동시 쓰기를 대신하지 않는다.
