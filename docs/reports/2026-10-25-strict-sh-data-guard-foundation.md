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
  source identity/seen 규칙과 records immutable 오류는 기존 trigger에 남아 있다.
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
