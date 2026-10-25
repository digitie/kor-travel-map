# Snapshot 복구 SD gateway 초안

## 범위

Root 통합 source 697160d 위에 신규 infra gateway와 순수 단위시험만 추가했다.
기존 product/SQL/권한·caller·Dagster 파일을 수정하지 않는다. 신규 파일이므로 기존 심볼
signature 영향도 평가는 해당하지 않는다. 독립 PR·실제 PostgreSQL 실행·설치·collector 활성화는 없다.

## 호출 경계

모든 함수는 이미 열린 caller transaction을 요구한다. 내부 begin/commit/rollback, SDK fetch,
직접 table SELECT/UPDATE, lease 시각으로 실행 권한을 추측하는 로직은 없다. 호출은 정본
SDK0 member read/register/claim/bind/begin/finish/seal SD만 사용한다. token은 전달값이며
DB가 실제 fence·lease·member·root를 매 명령에서 판정한다.

Root가 공지한 register7 인자, begin7 인자(artifact SHA 포함)와 bound attempt6개 read 출력에
맞추었다. 이 SQL 확장들은 기준 부모 뒤의 별도 합성 대상이다. 아직 wrapper/최종SQL 핀/ACL과
실제 호출 호환성을 수용하지 않았다. J의 expired ready plan reset은 별도 명령이며 이 초안에
임의 갱신·owner 교체를 넣지 않는다.

## 복구와 손상

member read는 단일 SD statement의 artifact/context/native digest를 재검증하고, 정본 codec에
expected pins를 전달한다. 원 artifact와 원 결과 bytes를 함께 보존한다. infra는 opaque context의
8192B/정확 SHA만 확인하며 Dagster observation 의미 검증은 import하지 않는다.

미등록 None과 손상을 구분한다. status/result/postprocess 부조합·부분 kernel binding·미래 상태,
naive lease 시각·다른 pins·손상된 canonical result는 예외로 닫는다. applied 이상은 같은
completed kernel attempt 관측을 요구한다. root 실패/취소 관측을 반환해도 상태를 되살리거나
원래 적재를 재실행하지 않는다. child_sealed는 done child와 함께 관측되어야 한다.

commit 응답을 잃은 caller는 member read에서 저장된 전체14필드+retired와 원 bytes를 받는다.
counter 재계산이나 DML 재실행 fallback은 없다. duplicate registration은 generation/fence
NULL만 수용하며 새 token으로 승격하지 않는다. 새 claim 반환값만 별도 token으로 전달한다.
lease 만료·시간 비교·stale fence의 최종 판정은 DB 소유다.

## 검증과 미완

순수 시험은 원 converter의 typed 공항 입력으로 canonical artifact/result를 만들고 SDK0
단일 읽기, 전체 원 결과, 상태·해시·pins 손상 거부, duplicate nonce 부재, 기존 kernel binding,
caller TX 부재 시 SQL0, 원 result bytes 전달과 commit0을 확인한다.

신규34개와 기존 input/result codec을 합친219개 순수 시험은2.62초에 통과했다.
Ruff2파일·strict mypy1파일·문서 redaction도 통과했다.

현재 실제 PostgreSQL/등록 SD 최종pin/429·430 ACL/unknown commit paired 실행/collector 연결은
미완이다. 이 초안을 SDK 실행 또는 정상 전체수집 수용으로 계산하지 않는다.

## 초기 준비 뒤의 driver 값 보강

초기05732의 UUID exact type 검사는 실제 asyncpg UUID subclass를 거부할 수 있었다.
PG 없이 설치된 driver의 실제 UUID 값을 통과시키는 반례를 확인하고 UUID 계열을 정본
UUID bytes 값으로 정규화했다. 이는 DB 권위를 추가하지 않는다. begin 반환은 정본 applying
JSON 전체를 전달하여 observation generation과 추가 kernel 필드를 버리지 않는다.
실제 SQL의 generation binding·최종 signature 호환성은 후속 정본핀 검토 대상이다.
