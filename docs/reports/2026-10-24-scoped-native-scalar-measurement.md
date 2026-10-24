# 제한 native scalar의 독립 DML 비용 측정

PR1375 `8d365e03361b354fd63599c29bd8c4cc9a0132b6` 위의 별도 측정 runner다.
소스 커널·native writer·기존 시험을 변경하지 않는다. 최종 412와 최신 native 합집합에서 실측했다.
현재 단계에서 운영 ARM CPU/RAM 저감, 전체 수집/ADR115 acceptance 완료를 주장하지 않는다.

## 실행 범위

`python -m scripts.ci.measure_scoped_native_scalar`는 Docker를 만들지 않고 계획만 출력한다.
`--run --output <새 JSON 경로>`만 자체 로컬 PostGIS container를 생성한다. 외부 DSN,
기존 container, 운영 주소, provider 호출 입력을 받지 않는다. UUID 이름/label/실제 생성 ID가
일치하는 container 한 개만 정리한다. 2CPU·memory1536MiB·memory+swap1536MiB
(추가 swap 0)·PID256 상한이다.
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

## 실제 격리 수용 결과

최신 native `2eb79bc80797be88a45b15c7cd6522001392691d`을 합친 runner
`4c9916d0b90406a0613ca8b41434260b6ec85696`에서 실제 full bootstrap/schema412/runtime ACL을
검증했다. 이미지 architecture는 amd64이며 2CPU·1536MiB·PID256 실제 설정도 확인했다.
초기 계획은 2dataset·2record라는 가장 작은 독립 DML shape다. 처리량 확대나 현실 분포의
대표성을 이 결과로 추정하지 않는다. 두 연결은 양쪽 mode에서 측정 전에 미리 확보한다.

별도 probe에서 두 backend PID가 source DML을 끝내고 미커밋 상태로 겹친 구간은
79.23ms다. 이 barrier 시간은 아래 성능 6회에 들어가지 않는다.
serial/concurrent2 각각 독립 fresh clone 3개에서 성공했고 모든 canonical output·source raw/head·
base/effective·완료 receipt hash가 일치했다. OOM=false/restart0, 정확한 생성 ID의 자체
container 제거를 SDK로 확인했다. shared/운영 DB·container는 사용하지 않았다.

| 지표(각 3회 중앙값) | 직렬 | 병렬2 | 병렬/직렬 |
| --- | ---: | ---: | ---: |
| elapsed | 273.81 ms | 158.42 ms | 0.579 |
| Python CPU | 27.06 core-ms | 26.84 core-ms | 0.992 |
| PG CPU | 237.85 core-ms | 247.94 core-ms | 1.042 |
| Python RSS 표본 최댓값 | 153.56 MiB | 153.85 MiB | 1.002 |
| PG cgroup 메모리 표본 최댓값 | 247.02 MiB | 247.66 MiB | 1.003 |
| WAL | 14336.00 B | 14392.00 B | 1.004 |

완료 시간은 줄었지만 PG CPU 중앙값은 약 4.2% 늘었고 CPU 절감 자체는 입증하지 못했다.
3회·2행·약0.15~0.28초라는 작은 구간이며 표본 memory는 peak 보장이 아니다. CPU/메모리
표본의 10% 확대 기준만 이 작은 shape에서 넘지 않았으며, 전체 ADR115 §9 수용을 대신하지 않는다.
API p95·실제 provider/Geo·대량/겹치는 Feature·운영 ARM·모든 writer 배선은 미검증이다.

초기 r1은 runner SQL literal의 closing quote 누락으로 prepare 단계에서 실패했다.
schema/ACL 뒤였지만 성능 표본은 0이며 실패 JSON과 cleanup=true를 보존했다. r2의 6회 성공은
중간 검증으로 남긴다. guard 추가 뒤 d83의 6회도 성공했지만 최종 수치는 위 4c 실행만 쓴다.
최종 412/최신 main 통합 뒤 bootstrap/activation 변화와 import 세대를 반영해 한 번 재확인했다.
최종 tuple의 schema-owner 역할 복원과 활성 fieldset 변경 거부는 setup 경계이며 계측 코드는
앞선 두 독립 소스 리뷰의 runner와 byte 단위로 같다.

- 전용 순수14건+native artifact 기존4건=18 PASS(1.13초), runner strict mypy/Ruff PASS.
- 원시 결과: `/tmp/map-native-measure-final-4c9916d0.json`, 로그: `/tmp/map-native-measure-final-4c9916d0.log`.
- 원시 JSON SHA256: `f3f33144390854288657d47209dada2c5c5f6092dd4b7fc1b1dad61d2dbd236f`.
- fixture SHA256: `b3b6a4950f12841afca22d1fb0b464a1c5d4f317beb1854f4b669b3c3362c63a`.
- runner SHA256: `64cd3944e648a2be957aee01aec78a3bb845f8585b80770b740e44122d154fc9`.

계측 source는 두 독립 리뷰를 통과했다. 최신 부모 합집합·이 문서 delta의 최종 확인과
정확 CI는 별도 gate다. 제품·계측 source는 추가 변경하지 않는다.
후속413 전역 SQL writer 배선은 이 schema412 측정에 들어가지 않으며 다른 증거로 수용한다.
공개 HTTP/UI·운영 활성화·Weather/Transport 전파는 실행하지 않았다.
