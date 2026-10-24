# 제한 native scalar의 독립 DML 비용 측정

PR1375 `8d365e03361b354fd63599c29bd8c4cc9a0132b6` 위의 별도 측정 runner다.
소스 커널·native writer·기존 시험을 변경하지 않는다. 최신 412 의존 통합 뒤 실제 측정한다.
현재 단계에서 운영 ARM CPU/RAM 저감, 전체 수집/ADR115 acceptance 완료를 주장하지 않는다.

## 실행 범위

`python -m scripts.ci.measure_scoped_native_scalar`는 Docker를 만들지 않고 계획만 출력한다.
`--run --output <새 JSON 경로>`만 자체 로컬 PostGIS container를 생성한다. 외부 DSN,
기존 container, 운영 주소, provider 호출 입력을 받지 않는다. UUID 이름/label/실제 생성 ID가
일치하는 container 한 개만 정리한다. 2CPU·메모리와 swap 각1536MiB·PID256 상한이다.
정본 application bootstrap와 post-migration runtime ACL을 수행하고 권한 경계를 확인한다.

고정 두 dataset/Feature의 primary name/phones와 원천 시각·원문·hash·record key를 template에
한 번 넣는다. serial/concurrent2는 각각 새 template clone을 사용하며 3회씩 교대로 측정한다.
계획·seed는 비용 구간 밖이고 native source/head/candidate/winner/finish 및 commit은 안에 있다.
각 run의 source 이력 수·head·base/effective 값·완료 receipt와 전체 canonical hash가 같아야 한다.

별도 clone에서는 두 backend PID가 실제 source DML 반환 후 어느 쪽도 commit 전에 barrier에
도착하도록 강제한다. 이 probe는 정확성 증거이며 성능 6회와 합치지 않는다. 성능 run에는
인위적 대기 barrier가 없다. SQL 왕복의 client 시각을 PG 서버 실행 시간으로 표현하지 않는다.

## 측정과 미완

elapsed, Python process CPU core-seconds, 전용 PG cgroup CPU core-seconds, 100ms Python RSS/
PG memory 표본, cgroup lifetime peak(제공 시), WAL을 나눠 기록한다. lifetime peak에는 bootstrap
이 포함되므로 phase peak로 쓰지 않는다. 계측 overhead/PG background와 미통제 OS page cache,
같은 작은 입력의 변동성을 명시한다. fresh DB는 cold cache를 의미하지 않는다.

초기 checkpoint: 순수 fixture/계획/물리 지표 단위 검사만 수행한다. 최신 412 통합,
자체 격리 PG 실제 6회·probe, 두 독립 리뷰·정확 CI는 아직 미완이다. 공개 API/UI·운영 활성화와
Weather/Transport 전파를 이 runner의 결과로 대신하지 않는다.
