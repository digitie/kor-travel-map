# Rest reader의 국소 JIT 비활성화

## 관측

`d8a08b9e`와 coverage7.17.0 CTracer를 사용한 owned215 시험은
`feature.read_transport_rest_snapshot_evidence`가3.002886초에 statement timeout으로
취소됐다. 전체30초 만료와는 별개이며 원 실패는 보존한다. byte quota 시험은 같은
source에서11개 등록 후12번째53000과 전체rollback을 확인했다.

JIT OFF 개입 시험에서는 같은 connection의 기존설정이 on·비용기준100000/
500000/500000임을 확인했다. 조회 동안만 off로 바꾸고 성공 뒤 on으로 복원했으며
reader2.274328초·atomic23.841489초, 전체215·필수 후처리·별도seal이 통과했다.
pytest case105.433초/전체runner117.679초는 다른 범위다. 실제 source2575/import52/
SDK53과 정확 CID·UUID·볼륨 정리를 검산했다.

이는 단일 개입 시험이다. 서버 CPU/RSS·JIT 컴파일 시간·실제 잠금 취득시각은 측정하지
않았으며 JIT가 이전 실패의 유일한 원인이라고 판단하지 않는다. 로컬 Python3.13.14/
SQLAlchemy2.0.55/asyncpg0.32.0·이미지는 CI와 달라 환경동등으로 표현하지 않는다.
원장 `map432-jit-off-A215-w-independent-actual-factcheck-r1.json`과 원 실패의
`map1418-d8a08-cov-A-failure-B-pass-root-actual-acceptance-r1.json`을 구분한다.

## 제품 범위와 복구

잠금 뒤 `_read_locked_evidence`는 기존 statement/lock 설정과 함께 jit를 읽는다.
서버3초·lock1초보다 짧은 caller 제한을 보존하고 조회 동안만 `SET LOCAL` 의미의
`set_config(..., true)`로 jit를 off로 둔다. 성공 뒤 세 설정을 원값으로 되돌린 후
원 raw 값을 반환한다. decoder·assessment·다른 후처리는 caller의 원 설정으로 실행한다.

조회나 설정 복원 중 SQL 오류·취소가 나면 추가 복원 SQL을 보내지 않고 원 오류를
전파한다. caller의 전체 TX rollback이 변경한 LOCAL 설정을 회수한다. 내부commit,
rollback/savepoint/retry·DB 전역 설정·SQL함수·ACL·한도 변경은 없다.

## 검증과 남은 작업

기존 입력/원 결과 회귀를 포함한 단위18개가 통과했다. 원 jit on/off와 더 짧은 제한의
조합에서 조회 중 off·적용 전에 원값복원을 검사하고, SQL오류/취소에서는 원 객체와
추가복원SQL 없음을 확인했다. Ruff와 해당 source mypy도 통과했다.
두 독립 제품 리뷰를 반영한 `81164788` 자체로 개입용 fixture 없이 coverage PG 시험을
통과했다. 실제215개·후처리·별도seal을 확인했고 reader2.333099초·atomic24.250820초다.
pytest case106.542초/전체runner119.767820초와 구분한다. source2576/import52/SDK53과
정확 CID·UUID·볼륨 정리를 독립 검산했다. 원장
`map432-reader-local-jit-product-A215-w-independent-actual-factcheck-r1.json`을 따른다.
환경 차이와 미측정 항목은 앞 절과 같으며 제품의 운영 성능으로 확대하지 않는다.

선행 `d8a08b9e` CI는 열 검사 모두 성공했다. JIT 제품과 추가 로그아웃 수정이 포함된
최종 커밋의 CI·새 UI 빌드/실제 UI·머지/배포는 별도로 남는다.
