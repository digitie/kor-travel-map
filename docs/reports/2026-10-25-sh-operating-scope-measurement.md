# SH 운영 후보의 실제 크기와 적용 범위

2026-10-25. 문서만 갱신한다. 수집 코드·SQL·잠금/메모리 상한·정책·실제 배포는 바꾸지 않는다.

## 실제 조회와 확인한 집합

첫 entity 집계는 현재 운영 Map API의 runtime 로그인 역할로 읽기 전용 transaction을 사용했다.
독립 current/연결/receipt와 후속 MCST 후보 집계는 같은 API 설정·로그인으로 접속한 뒤
`SET LOCAL ROLE ktm_feature_schema_owner`를 적용한 읽기 전용 관찰이다. 이 조회가
runtime 기본 권한만으로 모두 허용된다고 주장하지 않는다.
조회 당시 운영 schema는409였고 신규 provider-field 정책표는 아직 설치되지 않았다.
조회에는 statement timeout 3초와 lock timeout을 두었다. 원천 HTTP 재수집이나 DB 쓰기는 하지 않았다.
이력 표 전체 COUNT는 하지 않고 이력 규모는 PostgreSQL 통계의 추정치로만 읽었다.

| 현재 저장 집합 | 국가유산 | MCST 세계음식점 |
| --- | ---: | ---: |
| source entity | 4,279 | 9,494 |
| current source head | 4,279 | 9,494 |
| active primary place와 연결된 고유 Feature | 4,279 | 9,494 |
| area | 0 | 0 |

첫 entity 집계는 0.0054초, 독립 current/연결/receipt 집계는 0.414초였다.
API 컨테이너·이미지는 두 번째 조회 전후 같았다. 이 순간의 비교를 원자적 전체 수명 증명으로
확대하지 않는다. source_records 통계 추정은 247,898행이며 정확 COUNT가 아니다.

최근 영속 receipt의 집합 크기도 각각 4,279/9,494였다. 그러나 current head나 과거 receipt의
크기가 새 provider 응답 전체 입력 개수라는 뜻은 아니다. entity와 고유 Feature 개수가
같아도 개별 entity의 일대일 연결이나 모든 역할의 closure가 증명되지는 않는다.
실제 canonical fetch와 최종 typed
bundle을 다음 수용 단계에서 별도로 대조해야 한다.

## 현재 경로의 한계

이 저장 집합 전체를 한 번의 기존 SH 계획에 넣으면 입력 상한 2,730을 넘는다.
현재 플래너의 dependency 최소 3N도 각각 12,837/28,482로 기존 상한 8,192를 넘는다.
DB 증거 조회 요청을 잘게 나누는 것만으로 단일 manifest/apply의 상한이 해결되지는 않는다.

구현 중인 국가유산 증거 조회기의 전체 binary 256 KiB와 encoded 1 MiB 예산도 별개다.
요청 cardinality가 2,730 이하라는 사실만으로 실제 2,730건 성공이나 peak memory 상한을
증명하지 않는다. 25개 base 필드·원천 계보·metadata의 누적 크기를 포함한 실제 성공 N,
메모리와 쿼리 비용을 측정해야 한다. CASE로 안전하게 key를 비교해도 LIMIT만으로
과거 이력 전체를 읽는 비용이 입력 크기에 비례한다고 주장할 수 없다.

따라서 기존 설계의 국가유산/세계음식점은 적격성 의미와 제한된 합성 시험을 위한 후보이며,
현재 전체 저장 집합에 대해 운영 SH가 작동한다고 세지 않는다. 새 조회기·stamp SQL 경계나
격리된 소규모 두 transaction 성공도 실제 두 수집 worker와 전국 입력의 수용을 대신하지 않는다.

## 더 작은 MCST 후보의 읽기 전용 조사

13개 MCST dataset을 추가로 조사했다. 기존 `kcisa_common` 계열에서 현재 head가 2,730 이하인
집합은 캠핑 2,476개 하나라서 같은 계열의 소형 두 dataset을 바로 고를 수는 없다.
다른 `cntc_resrce` 계열의 후보는 다음과 같다.

| dataset | 현재 head / entity / 연결된 고유 Feature |
| --- | ---: |
| 독립서점 (49) | 327 |
| 카페서점 (50) | 1,059 |
| 아동서점 (51) | 786 |

이 세 개수는 현재 저장 집합의 관찰이다. 개별 연결의 closure, 새 fetch의 전체 입력,
원천 필드 전체의 일관성이나 typed manifest 1 MiB·reader 256 KiB 통과를 뜻하지 않는다.
독립서점/카페서점의 한 표본은 같은 11개 원천 필드였으나 아동서점 표본은 12개로 달랐다.
국가유산 adapter의 provider 이름만 바꾸어 재사용할 수 없으며, MCST의 이름·주소 자연키와
multi-member capture 의미를 보존하는 별도 적격성 검증이 필요하다. byte 예산·실제 성공 N을
측정하기 전에는 첫 운영 dataset 선정 또는 SH 활성화 완료로 기록하지 않는다.

후속 metadata 전용 조회는 0.185초였고 세 집합의 관찰 열 압축은 없었다. 현재 head의
원천 record는 정본 index의 key 동등 조건으로 한 건씩 조회했으며 payload 직렬화는 하지 않았다.
raw JSONB의 직접 저장 크기만 각각 193,851/678,475/529,309 byte였다. 현재 reader의
physical+4 누적 방식으로 raw+entity+head만 합쳐도 각각 312,299/1,063,185/829,199 byte여서
모두 256 KiB를 넘는다. 이 수치는 Feature/base/candidate/policy·배열·descriptor 예산을
추가하기 전의 하한이다. 따라서 세 후보 모두 현재 전체 증거 단일 조회로 수용할 수 없다.
증거 조회 분할과 전체 atomic manifest/apply 검증은 별개이며, metadata만으로 canonical
typed artifact/manifest 1 MiB의 통과 또는 실패를 확정하지 않는다.

## 후속 구현 순서와 완료 조건

1. 실제로 작은 독립 dataset 후보의 current/최종 입력과 typed converter 의미를 확인한다.
   같은 dataset을 종목·페이지로 나누어 독립 dataset인 것처럼 만들지 않는다.
2. 첫 운영 후보를 정할 때 exact provider/dataset·normalizer·원천 key/필드·Geo·stamp·은퇴
   의미와 multi-member capture를 보존한다. 이름이 자연키인 MCST에 국가유산 이름 갱신
   판정을 그대로 적용하지 않는다.
3. 큰 snapshot은 bounded planning chunk만 추가하고 완료했다고 표시하지 않는다.
   전체 manifest/dependency/apply의 실제 예산·정렬 잠금·단일 transaction 원자성·실패 복구를
   함께 설계하고 검증해야 한다. 단순 cap 상향이나 부분 commit으로 우회하지 않는다.
4. 실제 두 worker의 독립 dataset DML 중첩, 충돌·stale·worker 종료, 전체 결과/capture/seal,
   CPU/메모리와 운영 scheduler 제약을 검증한 뒤 적용한다. 기본 EX와 자동 활성화 OFF를 유지한다.
5. Map 수집 개선 수용 뒤 Weather·Transport·Common에 적용할 공통 부분을 전파한다.
   취소된 Weather·Transport 운영 export 활성화/Map 연동 검증을 재개하지 않는다.

T-CWRITE-04 및 큰 입력/실제 worker/운영 수용은 미완이다. 첫 작은 운영 후보는 조사 중이며
이 문서는 특정 dataset의 활성화 또는 배포 완료를 선언하지 않는다.

## 근거

원본은 private 감사 원장에 보존하고 공개 문서에는 접속·자격 정보를 싣지 않는다.

- root entity 조회: map-concurrency-n150-target-dataset-counts-root-r1.json,
  SHA-256 5e8656319e5ba02ca4ec6afc19406f4bfd05fd947b9e6a8c5c98d72f57906793.
- 독립 current/receipt 조회: map-sh-viability-current-counts-j-r1.json,
  SHA-256 9edccaa89c0d051c8c8f28264c9bdb2709c97240903157299db4c14e9a2a39fe.
- MCST 소형 후보 조회: map-mcst-small-scope-counts-j-r2.json,
  SHA-256 4da4baa017b4920b5eac9ec10aa41f1caecd91542553b763cc43fb001640d5ba.
- MCST metadata 예산 조회: map-mcst-metadata-viability-j-r3.json,
  SHA-256 7ec67747ca833bfd7e9d892e95003c9aca62cac38bce5d9a0607035f5d732e27.
- 기존 의미·원자성 경계: [SH 수집 설계](2026-10-25-sh-collector-integration-design.md),
  [ADR-115](../adr/115-scoped-concurrent-feature-writes.md).
