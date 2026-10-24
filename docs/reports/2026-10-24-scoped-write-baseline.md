# ADR115 격리 native DML·seal 기준선

T-CWRITE-01의 작은 측정 도구다. 실제 운영 값·수집 속도 개선이나 전체 동시 쓰기 완료가 아니다.
기존 FeatureRepo·global fence·winner·API/DTO는 바꾸지 않는다.

## 고정 입력과 측정 경계

- fixture v1은 공개 데이터가 아닌 synthetic point 4개다. 원문 파일 SHA256으로 입력을 고정한다.
- independent는 두 dataset의 서로 다른 Feature, shared는 두 dataset의 claim/source/head/primary
  link가 같은 canonical Feature에 연결된 N:1 fixture다. source/record/Feature는 기존 제약을 지킨다.
  fixture 준비는 측정 밖이며 최초 identity 발급·자동 dedup의 성능을 측정한 것으로 해석하지 않는다.
- 측정은 기존 global fence 획득 → **수정하지 않은 load_bundles** → 기존
  capture_provider_curation_input의 causal seal → 같은 transaction commit이다.
  source/typed field patch를 benchmark SQL로 다시 구현하지 않는다.
- 두 writer의 실제 DML 시작/종료·PID·commit과 겹침을 기록한다. 현재 전역 fence에서는
  independent/shared 모두 DML overlap=0이어야 한다. 이후 scoped writer와 비교할 현재 기준선이다.
- provider HTTP/Geo·최초 identity 생성·absent retire·root finalize·API/UI는 이번 범위 밖이다.
  seal은 causal input seal이며 root receipt 발급·공개 완료를 의미하지 않는다.

## 격리와 반복

CLI는 외부 DSN이나 기존 container를 받지 않는다. 로컬 Unix Docker socket의 pinned PostGIS
testcontainer 하나만 생성하고 fresh schema를 bootstrap한다. DDL 뒤에는 운영 entrypoint와 같은
닫힌 runtime ACL 조정 routine을 호출하고 그 setup pool을 폐기한다. 별도 fresh worker pool은
실제 `ktm_feature_service` 최소권한 preflight와 session/current login을 검증한다. GRANT를
추가하거나 owner/superuser를 worker로 쓰지 않는다. 고정 fixture가 든 template DB를
clone하므로 각 trial의 최초 DB 상태가 같다. 생성에 성공한 정확한 DB 목록만 정리하고
성공/실패 모두 자기 container를 제거한다. 시작 중 취소도 thread 완료를 기다린 뒤 정리한다.
다른 서비스·DB·daemon은 다루지 않는다.

cold는 전용 PG 재시작 후 **shared_buffers 첫 실행**이다. OS page cache를 비웠다고 주장하지
않는다. warm은 같은 artifact의 즉시 native replay다. independent/shared 각각 cold+warm 3회가
기본이며 매 trial의 effective 집합(kind·name·coord·category·marker·place_kind)과
current source 수, seal membership, replay 원문 멱등을 확인한다.
처음 입력과 replay의 DML 양이 다르므로 cold/warm 차이를 cache 효과만으로 해석하지 않는다.

## 계측과 한계

- lock_wait_seconds는 client의 fence 획득 호출 경과시간으로 RTT를 포함한다.
  pg_locks의 대기/전체/advisory 수는 별도 100ms 샘플이며 모든 물리 row lock 수가 아니다.
- DML·seal·commit wall time과 두 writer의 실제 구간을 따로 기록한다.
- worker process CPU와 전용 PG container CPU를 core-seconds로 분리한다. meter overhead와
  전용 PG background 비용을 포함하며 기존 운영의 host CPU%나 ARM 개선율로 쓰지 않는다.
- worker RSS와 PG cgroup memory의 phase별 peak는 100ms **샘플 peak**다.
  Docker가 lifetime peak를 주면 별도 기록하며 없으면 null/사유를 남긴다.
- WAL은 외부 DB가 없는 전용 PG instance의 LSN 차이다. template clone/fixture 준비와
  restart는 측정 구간 밖이며 WAL을 특정 statement의 배타 비용으로 주장하지 않는다.
- 각 결과에는 Git HEAD/두 runner 파일 SHA256·tracked clean 여부, fixture SHA256, image digest/ID,
  architecture, PostgreSQL/schema head를 남긴다. dirty 결과는 release 전후 비교 증거로 수용하지 않는다.
- 기존 base winner의 도착 순서 의미를 바꾸지 않는다. 동일 effective 값만 검증하며
  deterministic winner/모든 lineage의 동일성은 T-CWRITE-02가 별도로 구현·검증해야 한다.

## 실행과 CI artifact

실측은 root와 자원을 조율한 Linux 환경 또는 CI의 격리 자원에서만 수행한다.
계획 조회는 Docker/DB를 시작하지 않는다.

```bash
python -m scripts.scoped_write_baseline
python -m scripts.scoped_write_baseline --run --repetitions 3 --output /tmp/cwrite-baseline-new.json
```

결과 파일은 atomic no-clobber로 발행한다. 기존 측정 기록을 덮지 않는다.
기존 integration lane(alpine/glibc)이 실제 3회 cold/warm 회귀를 실행하며
scoped-write-baseline-<lane> artifact를 보관한다. timing 임계값으로 CI를 느슨하게 하지 않는다.

## 검증 상태와 남은 범위

순수 fixture/구간 계산 첫 checkpoint는 Ruff와 unit 10건, 계획 조회를 통과했다.
실제 PG runner와 추가 회귀는 구현했으며 최종 검증 수치·두 리뷰·exact CI는 PR 기록에서 수용한다.
첫 실제 PG 실행은 필수 post-upgrade runtime ACL 조정이 빠져 원문 적재 전 거절됐고, 성공
JSON을 발행하지 않았다. 정본 초기화 순서를 보완한 후 두 lane의 실제 측정을 다시 수용한다.
로컬 container를 추가로 켰거나 운영 측정을 했다고 보고하지 않는다.

T-CWRITE-01의 writer/trigger 전수 inventory·실분포/대량 geometry·API/UI 기준선은 미완이다.
T02 membership/backfill·winner, T03 scope/epoch/gate, T04 실제 DML 동시 쓰기도 남아 있다.
