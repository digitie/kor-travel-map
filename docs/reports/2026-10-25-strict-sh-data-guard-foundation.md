# Strict SH 데이터 guard foundation429 — 정의만 작성한 첫 checkpoint

## 범위

기준426 부모 `80c404926d3b983dc7ed205b378ee39f85f19285` 위에429의 비활성 private 함수와
installer 정의만 추가했다. `429_strict_sh_data_guards`는32자 이하이며 down428은 예약한
`428_bounded_curation_capture`다. 현재 worktree에는427/428이 아직 상속되지 않았으므로
전체 migration graph·fresh bootstrap·공식 oracle는 미검증이다. 다른 작업자의427/428
제품·runtime_privileges·기존 activation installer와 기존51 trigger 집합은 변경하지 않았다.

migration은 private 함수 네 개를 state procedure owner로 만들고, 입력 없는 private
installer는 schema owner로 만든다. PUBLIC/runtime/service/provider executor의 직접 EXEC는
회수하고 schema owner의 trigger 생성에 필요한 네 함수 EXEC만 부여한다. 소유자의 기존
CREATE 유무와 짧은 caller timeout을 보존한다. 새 runtime SD allowlist 항목이나 직접 표
권한은 추가하지 않는다. runtime_privileges 정본 동기화는428 부모 합성 뒤 별도 gate다.

## 정의한 경계

- `_strict_sh_data_context(boolean)`: 실제 현재 database/PID/P key/objsubid의 granted lock을
  읽는다. EX는 기존 후속 guard로 보내고, missingP/bareSH/EX-only의 SH는 epoch 전에23514다.
  strict SH는 현재 TX의 유일한 applying attempt·frozen manifest·scope owner/epoch를 읽기로
  확인한다. `_locked_scoped_feature_write_attempt`를 다시 호출하거나 lease 경과만으로 같은
  applying TX를 거부하지 않는다. 임의 세션 잠금의 물리 선행순서를 증명하는 함수가 아니다.
- statement guard는 위 검사를 epoch helper보다 먼저 호출한다. source_records도25관계에 포함한다.
- source row guard는 own dataset/named 기존 entity/head만 허용하며 새 record는 named entity에만
  붙인다. INSERT ON CONFLICT 후보의 first_seen_at을 기존 값과 같게 강제하지 않는다. 실제
  source identity/seen 규칙과 records UPDATE immutable 오류는 기존 trigger에 남아 있다.
  records DELETE는 SH append-only 계약으로 명시 거부한다.
- Feature/derived row guard는 policy 비활성 Feature도 정확 manifest/membership 검사에서 생략하지
  않는다. OLD/NEW Feature UUID와 base/candidate의 own primary source identity를 검사한다. 기존
  scalar/SI/stamp/typed 검사를 삭제하거나 성공으로 치환하지 않는다.
- installer는 정확25관계 statement와8관계 row trigger의33개 집합만 명시 설치할 수 있게 정의했다.
  P EX가 먼저 필요하고 새 설치는 table 이름 정렬 순서다. partial/disabled/다른 table·함수·event·args
  정의는 거부한다. migration은 installer를 실행하지 않고 기존 activation에서 호출하지 않는다.

BEFORE ROW는 UPDATE tuple 선점 뒤 실행될 수 있으므로 outside-target의 변경 거부와
missingP/bareSH의 epoch/tuple 전 거부를 구분한다. 모든 임의 수동 SQL의 deadlock0을
보장하지 않는다. tracking6의 L-only/final P→L, kernel private metadata와 sync 상태는
이25관계 분류에 넣지 않는다.

## 확인과 OPEN

전용 정적 unit7 PASS0.27초·Ruff2 PASS다. 최초 정적 lint10개는 긴 receipt literal/줄 길이와
assert 형식이었고, 소유 새 파일만 정렬했다. 실제 DB 명령·PG fixture·HTTP·운영 실행은0이다.
이 시험은 migration이 정의만 하고 installer를 호출하지 않는지와 소스상 prefix/집합 경계를
확인할 뿐, PL/pgSQL 실행이나 행 경합을 증명하지 않는다.

다음은 새 전용 integration source로 missingP/bareSH와 epoch·행 holder의 paired 순서,
source first_seen 후보 UPSERT, targetA/targetB, records immutability, disabled/partial/ACL
설치 실패 원복을 구체화하고 두 독립 FULL source gate를 받는 단계다. 그 뒤에만 별도
CPU 슬롯에서 owned PG를 실행한다. 아직 설치·runtime 권한 합성·공식 oracle·whole capture·
RC 전환·공통 parent 순서·durable 자동복구·전체39관계/126루틴 closure·두 worker·SH 활성화는
전부 미완이다. collector나 운영 수용으로 해석하지 않는다.

## 전용 integration source와 records DELETE 정정

첫 정의204를 보존한다. 전용 시험을 작성하며 기존 source_records immutable trigger가
UPDATE 전용임을 재확인했다. DELETE도 같은 오류로 막힐 것으로 가정한 부분은 제거하고,
SH records DELETE를 새 target guard에서 명시 거부한다. UPDATE의 기존 immutable 오류는
그대로 둔다. 이 정의는 어느 DB에도 설치하지 않았으며 종전204를 실제 검증 성공으로
재해석하지 않는다.

전용 integration25개 source를 추가했다. 정본 owned scalar bootstrap/ACL fixture와 기존
batch 실제 legacy seed→claim/manifest/begin 경로를 재사용한다. private installer의 명시
설치는 이 전용 owned fixture에만 있다. 원 공통 fixture/loader를 바꾸거나 가짜 성공 함수를
끼우지 않는다. missingP/bareSH와 epoch·Feature holder,17개 EX-only 관계, valid applying의
source UPSERT first_seen 보존·Feature 밖 target 거부·records DELETE/원 UPDATE 오류,
private EXEC 거부와 disabled/partial inventory 거부를 준비했다. schema owner의 명시 관리
SQL 시험과 실제 service login DML 경계를 구분한다.

`--collect-only`25 collected/1.17초이며 fixture/PG 실행은0이다. 이는 normal fullbatch/finish나
전체8 target·모든 설치 DDL rollback·취소/pool정리·ACL actual 수용을 닫은 결과가 아니다.
427/428 부모 및 권한 정본 합성과 두 독립 FULL source review 뒤에만 새 bounded runner와
정확 CPU 슬롯을 정한다. RC·자동설치·SH 활성화는 계속0이다.

## 정책 없는 manifest target의 우회 정정

aba4 source의 두 독립 FULL 검토에서 policy가 없는 inside-manifest Feature의 좌표·주소·
place 임의 필드 변경이 통과할 수 있음을 확인했다. 기존420 guard는 active policy가
없으면 조기 반환하며, manifest와 begin은 policy/lifecycle 적격성을 보장하지 않는다.
기존 target 검사만으로 active scalar 전제를 닫았다고 본 부분은 source P2로 보존한다.
이 정의는 실제 DB에 설치하거나 실행하지 않았다.

SH의 Feature/derived5관계에는 정확 manifest 검사 뒤 실제 active policy와 현재 active
lifecycle를 직접 요구한다. Feature UPDATE의 새 lifecycle도 active여야 한다. EX의 앞쪽
반환과 기존420 fieldset·stamp SI·typed 검사는 그대로 둔다. 일반 runtime이 가진
coord/address/place payload UPDATE 권한의 우회와, 별도 schema owner 관리 SQL인
lifecycle 변경을 구분한다. 자동 정책 등록이나 예외 성공 경로를 추가하지 않는다.

새4개 negative는 실제 canonical legacy loader로 만든 정책 없는 Feature를 진짜
claim/seal/begin의 manifest 안에 넣고 coord/address/place payload/lifecycle 변경을
23514로 거부하도록 작성했다. 추가1개는 실제 retired bundle을 legacy load하고 cutover한
뒤 active policy가 있어도 retired target의 SH 변경을 거부한다. 기존 active scalar
반복 UPDATE와 EX seed 검증 source는 보존한다. 정적7 PASS0.29초·Ruff2 PASS, 새 integration은
30 collected1.06초일 뿐이며 fixture/PG 실행은0이다. 부모 합성·권한 역할 정본·실제
positive/negative·공식 oracle·RC·전체 closure·SH 활성화는 여전히 미완이다.

새5개 source를 고정한 f6d 뒤 추가 순수 DTO 검증에서 `Feature.model_dump()`의 detail
dict 재입력이 ADR-018에 따라 거부됨을 발견했다. 원 typed detail을 보존한 뒤에는
retired 상태의 publication_state=suppressed 계약도 적용했다. 두 준비 오류를 보존하고
정본 검증기를 통과하는 retired fixture 구성을 확인했다. 원 collect는 함수 본문을
실행하지 않아 이 오류를 포착한 증거가 아니며, 제품 SQL 변경과 PG 실행은0이다.

두번째 검토자가 address negative의 plain text가 jsonb 입력 변환에서 먼저22P02를
일으킨다고 지적했다. address를 유효한 JSON object bind로만 정정해 실제 guard까지
도달하도록 했다. 기존 SQL guard와 오류 기대값은 그대로이며 실제 PG는 아직0이다.
