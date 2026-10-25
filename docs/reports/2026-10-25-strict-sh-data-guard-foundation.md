# Strict SH 데이터 guard foundation429 — 비활성 정의와 owned 검증

## 범위

최초426 부모 `80c404926d3b983dc7ed205b378ee39f85f19285` 위에429의 비활성 private 함수와
installer 정의만 추가했다. `429_strict_sh_data_guards`는32자 이하이며 down428은
`428_bounded_curation_capture`다. 당시427/428 미상속 상태에서 실제 migration graph·fresh
bootstrap·공식 oracle를 검증하지 않았다. 이후 검토된428 부모를 상속한 내용은 아래에
분리한다. 기존 activation installer와 기존51 trigger 집합은 변경하지 않았다.

migration은 private 함수 네 개를 state procedure owner로 만들고, 입력 없는 private
installer는 schema owner로 만든다. PUBLIC/runtime/service/provider executor의 직접 EXEC는
회수하고 schema owner의 trigger 생성에 필요한 네 함수 EXEC만 부여한다. 소유자의 기존
CREATE 유무와 짧은 caller timeout을 보존한다. 새 runtime SD allowlist 항목이나 직접 표
권한은 추가하지 않는다. 권한 정본 동기화는 아래428 부모 합성 단계에서 별도 검토한다.

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

## 428 부모 상속과 권한 역할 정본

정책 없는 target P2와 시험 준비 오류를 두 독립 source 검토로 보강한 뒤,
`b748bccfb19e4cedd9b081c660b2d4488e86366c` 부모를 합성했다. 부모의427 SQL/decoder와428
함수·통합37/공식 oracle1 결과 및 전체 문서 suffix를 보존한다. 뒤의427 prepare seam은
별도 부모이므로 아직 상속하지 않았다. 429 SQL과 integration30 source는 f2fb와 같다.

권한 정본은 state procedure owner 창에서 private4개 REVOKE와 schema owner dependency
EXEC만 복구한다. schema owner 창은 그 소유의 private installer1개 REVOKE만 수행한다.
5개 함수는429 이전 head에서 optional로만 건너뛰며 runtime/service/provider executor에
EXEC나 표 권한을 추가하지 않는다. reconcile은 installer를 호출하지 않는다. 새 회귀는
실제 owner별 ACL창·optional skip·dependency 수신 role을 확인한다.

429 graph를 생성하고 전용 migration/권한/정본 head/squash 단위67 PASS7.34초, Ruff4·
mypy1 PASS를 확인했다. 처음 존재하지 않는 graph 시험 파일명을 지정한 collection 오류는
시험 실행0인 채로 보존하고 실제 파일명으로 정정했다. tracked schema dump는 부모428의
실제 검증본 그대로이며429 공식 oracle가 아니다. 새 source 두 검토 뒤에만 별도 owned PG
준비를 진행한다. 429 실제30·전체8 targets/정상 finish·설치 중 DDL rollback·취소/pool정리·
전체 writer closure·RC·durable recovery·자동 설치·SH 활성화는 여전히 미완이다.

## 첫 owned 실제30 — 시험 가정 정정 전 FAIL 보존

514 source의 승인된 한 번 실행은 PG16.14/en_US.utf8에서25 PASS/5 FAIL이었다. XML
시간은15.000초, pytest console은15.69초이며 전체 결과는 FAIL로 보존한다. disabled trigger
관찰이 PostgreSQL char의 bytes `b'D'`를 문자열 `D`와 비교한1건, 정책 없는 target의
4개 negative가 정확 guard23514와 rollback까지 통과한 뒤 loader의 실제 all-null object
address를 SQL NULL로 잘못 가정한4건이다. 제품 SQL 오류가 재현된 것으로 해석하지 않는다.

시험은 tgenabled를 명시 text로 읽되 기대 상태 D를 유지한다. address는 허용하거나
성공으로 바꾸지 않고 실제 canonical load 뒤/SH TX 전의 현재 행 baseline과 rollback
뒤 lifecycle·coord·address·payload 전체가 같음을 검사한다. 기존 guard의 SQLSTATE와
constraint 기대값, 제품 SQL·ACL·예산은 그대로다. 이 시험 수정 후 실제 재실행은 아직0이다.

첫 runner는 pytest 실패에서 중단되어 정상 source/SDK post 블록에 들어가지 못했다.
따라서 이를 수행했다고 주장하지 않는다. 별도 읽기 전용 후관찰에서 source2428개
bytes/OID/mode와 SDK53개 hash가 같고 실제 import13개가 고정 Git과 일치함을 확인했다.
정확 CID/UUID0/global scalar0/volume1 부재도 saved cleanup과 새 조회로 확인했다.
원8개 증거와 result를 보존하며, 보충 관찰로 원 FAIL을 PASS로 다시 쓰지 않는다.

## 95e 실제30 통과와 다음10개 source

두 source·실행기 검토 뒤95e의 새 owned30 한 번은 모두 통과했다. XML14.969초와
pytest console15.61초를 구분하며, source2428/SDK53 전후·실제13 Git import·정확 CID/UUID0/
volume1 정리도 확인했다. 첫514의25 PASS/5 FAIL과 누락 post 블록 보충은 별도로 남기고
성공 수에 합산하지 않는다. 이는 위 전용30 범위의 수용이며 운영 활성화가 아니다.

같은 파일에 다음10개 source를 추가했다. 아직 PG에서 실행하지 않았다.

- 기존 공개 SH batch API로 실제 두 Feature apply→finish→commit한 뒤 별도 연결에서
  name/head와 completed attempt·result digest를 확인한다. monkeypatch 성공 경로는 없다.
- 같은 dataset의 A만 manifest에 넣고 B의8개 target별 DML을23514로 거부한다. base/candidate/
  stamp는 runtime 직접 쓰기 grant가 없어 schema owner 관리 SQL로 구분한다. 나머지5개는
  실제 service login이다. 42501은 성공으로 세지 않고 source/Feature guard의 constraint나
  정확 message를 확인하며 실패 TX rollback 뒤 B의 관찰값이 같아야 한다. Geo 없는 stamp는
  기존 행을 가정하지 않고 B의 INSERT 시도를 검증한다.
- owned outer TX에서 원33개 trigger를 제거한 뒤 중간 relation인 feature.features에 같은
  이름의 builtin trigger를 만든다. nested installer의 CREATE 충돌42710 뒤 신규 strict
  trigger0과 원 collision의 OID/정의/상태 보존, outer rollback 뒤 원33개 복원을 확인한다.

40개는 수집만 확인했다. 제품 SQL·migration·권한·공유 fixture는 바꾸지 않았고 신규
source의 두 검토 전 PG 실행은0이다. cancellation/pool 물리 정리와 전체 writer closure,
공식429 oracle·RC·durable recovery·collector 활성화는 여전히 OPEN이다.

### 기존 stamp UPDATE의 정확 manifest 경계 보강

ce41의 stamp INSERT negative는 무조건 topology INSERT 거부에서 끝나므로 outside-manifest
검사를 삭제해도 통과한다는 source 검토 지적을 받았다. 기존 INSERT 거부는 보존하고,
실제 기존 stamp의 UPDATE에 대한 별도1개 source를 추가했다. 기존 stamp 경계 helper의
canonical GeoLoadContext와 EX full loader로 같은 dataset의 A/B stamp를 만든다. A만
manifest에 넣어 실제 SH begin한 뒤 schema owner의 B timestamp UPDATE가 정확
`candidate Feature is outside the applying manifest`/23514로 거부되어야 한다. 42501이나
다른 stamp guard의 거부를 성공으로 세지 않는다. rollback 뒤 relation OID·토큰·outcome·
관측시각과 전체 두 stamp가 이전 관찰과 같아야 한다. 새41개는 source 수집만 확인하며
PG는 아직 실행하지 않았다. 제품 SQL·공유 fixture 변경은0이다.

### 활성화 전 context 비용 OPEN

매행 `_strict_sh_data_context`의 applying/NOT exclusive/apply_txid 조회에 정확히 맞는
인덱스는 아직 없다. 기존 expired partial index가 terminal 행을 제외할 수 있으므로
전체 이력에 반드시 선형 증가한다고 단정하지 않는다. 활성화 전 canonical claim→cancel
이력0/1000과 실제 applying1 조건에서 정확 내부 SELECT의 EXPLAIN/BUFFERS, 실제 helper
호출의 CPU/wall을 분리 실측해야 한다. 바깥 EXPLAIN으로 SPI 내부 비용을 주장하지 않는다.
이 checkpoint는 성능 코드·인덱스 변경이나 새 PG 실측을 포함하지 않는다.

## 공식429 oracle와 최신 main·공항427 상속

| 실제 실행 | 고정 source | XML 시간 | 범위 |
| --- | --- | --- | --- |
| owned30 PASS | 95e980b60 | 14.969초 | 최초30 경계·권한·정책/lifecycle 거부 |
| 새11 PASS | cba93b900 | 17.086초 | 기존 SH batch 정상 commit·8관계 대표 target 거부·설치 중 DDL rollback·기존 Geo stamp UPDATE |
| 공식oracle1 PASS | cba93b900 | 33.281초 | canonical300 fresh bootstrap→429 dump 생성·공식 재dump 비교 |

각 console 시간은15.61/17.67/34.01초다. source 파일의41개 수집과 별도 실제30/11을
구분하며, 단일 최종 source에서41개를 한 번 실행했다고 주장하지 않는다. 원514의
25 PASS/5 FAIL과 누락 post검사·별도 읽기 보충도 보존하고 성공 수에 합산하지 않는다.
두 owned 실행에서 원33개 trigger의 명시 설치는 전용 fixture에만 있었고 운영 설치는0이다.

공식 bootstrap은 runtime reconcile을 호출하지 않았으며 새 audit dump를 공식 구현으로
재dump해 비교했다. 기존 tracked428 oracle를429의 의미적 정답으로 삼지는 않았다.
새 dump SHA256은 `893e61bb8532bc1dd0c9c4d56aeec7941af33eac649a32bd9ca40ea305b3175f`다.
parent428의1655 block에서1665 block으로, 신규 private함수5+ACL5와 receipt CHECK의429
literal1개만 달라진다. 기존 객체 제거0, 기존 trigger block 전체가 같고33개 strict guard의
자동 설치도0이다. 네 state-owner 함수는 schema-owner dependency EXEC만, schema-owner
installer는 추가 EXEC grant 없이 PUBLIC 회수 상태다.

공식 실행의 source2428/SDK53 전후·실제9 Git import, 새11의 실제17 Git import와 정확
CID/UUID0/global scalar0/volume1 정리를 확인했다. 비용·RSS·ARM 성능 수용은 아니다.
공식 oracle 뒤 검토된 root428 최종 `c98a0bce3546419489034c628d0109c97cc06d96`을 상속한다.
최신 main의 가격 이력 API와 최종427 준비 함수·시험·문서 suffix를 부모 그대로 보존하며
429 제품 SQL과 기존 시험은 cba 그대로다. dump만 실제 생성된429 파일로 채택한다.

이 단계는 기본 대표 DML와 정상 scalar batch commit을 확인했을 뿐 전체 mutation 조합을
닫지 않는다. cancellation/pool 물리 정리, context 내부 SELECT plan/CPU 비용, 전체39관계/
126루틴 writer closure, whole capture fresh lock/RC 전환, durable 자동복구·두 collector·
운영 활성화·배포는 OPEN이다. 최종 합성 source 두 검토와 정확 head CI도 별도이며,
private installer는 기존 activation 경로에서 여전히 호출하지 않는다.

### 최종 receipt 실행 배선 규약 정정

최종 정적 검사86개 중84 PASS/2 FAIL(14.90초)은 receipt 검사가 실행 문장을
`_UPGRADE_STATEMENTS` tuple에서 추출하는 규약과 새 migration의 직접 execute 배선이
맞지 않아 발생했다. 실제 공식 dump의 CHECK에는429가 포함돼 있었고 원 실패는 보존했다.
검사를 완화하지 않고 같은 CHECK 문자열을 정본 tuple/loop로 실행하도록 정렬했다.
CREATE 권한 유무 양쪽의 실제 Python upgrade 실행 trace는 각각28/26문장으로 변경 전후
완전히 같으며 SQL·role·GUC·순서는 유지된다. 정정 뒤 같은 정적86개가13.96초에 통과했다.
새 PG 실행은 없으며 앞의 실제 oracle와 owned 결과를 새 실행으로 합산하지 않는다.

### 부모428 권한 인벤토리 CI 정정 상속

검토된 부모 `5ed45f1f3dc8eb55511c8d85b61e83e9d660dfed`의 catalog signature 규약 정정을
추가 상속했다. capture 함수 존재 검사는 schema/name 카탈로그 조회로, metadata dependency
GRANT는 기존 카탈로그 서명 치환으로 정렬한다. 300의 optional skip과422~427의 capture
부재 조건, 모호한 overload 거부·owner별 역할 창·제품 SQL·공식 dump는 유지한다. 부모의
최초 CI 실패와 실제37/oracle1은 그대로 구분하며 이번 상속으로 새 PG를 실행하지 않았다.
공통 journal/resume은 자체 최신 prefix 뒤 부모 전체 suffix를 보존한다.

추가 상속 뒤 signature lint를 포함한 집중 정적96개가13.35초에 통과했고 Ruff5파일·graph
동등성·redaction/차이 검사를 확인했다. 최종 두 source 리뷰와 정확 CI는 아직 미완이다.

### ac441 CI의 마지막 role 관찰 규약 정정

정확 ac441 CI에서 lint/OpenAPI/frontend/Docker build workflow는 통과했지만 Python3.13의
core 검사에서3825 PASS/7 SKIP 뒤 role 관찰 lint1개가 실패했다. 원 job 로그와 checkout
tree를 보존했으며 재실행하지 않았다. receipt tuple만으로는 실행기의 마지막 role을
관찰하지 못하는 추출 규약 문제였다. migration은 실제로 schema owner를 남기고 있었다.

정본 tuple에 실제 receipt CHECK와 마지막 SET ROLE 문장을 담고, 앞 문장은 기존 receipt
위치의 tuple[:-1] loop에서, 마지막 문장은 기존 GUC 복구 뒤 tuple[-1]로 실행한다.
표시용·미실행 SQL을 넣거나 lint를 완화하지 않는다. ac441 대비 CREATE 권한 유무 양쪽
upgrade execute trace28/26 전체가 같으며 기존5 SQL sidecar·runtime ACL·41시험·공식
dump는 바꾸지 않았다. lint 전체와 전용 migration unit은381 PASS/기존6 SKIP,39.13초다.
새 정확 CI와 두 source delta 검토는 별도이며 PG 재실행·운영 설치·활성화는0이다.
### 부모427 metadata 반사식 수정의 429 상속

정확46666의 Python3개·fixture와 다른4 workflow 통과를 확인했으며 두 PostGIS lane은
관측 시점에 진행 중이다. 같은 부모의427 CI에서 확인된 metadata 인덱스 누락/반사식 차이는
원결과로 보존하고 재시도하지 않는다. 원 ac441의 세 Python role lint 실패도 별도 보존한다.

검토된428 `cac89e092611e64330cfc90c184e28ca3ed2c0e2`을 상속해 models의 인덱스3 표현식과
해당 순수 시험을427의16ac 원문 그대로 반영한다. 16ac의 새 owned PG에서 원 fresh300→427
metadata 검사를 수정 없이 실행한1 PASS/17.172초(전체34.564초), Git2417/SDK53·실제import11·
정확 정리 기록은 부모 보고서에 보존한다. 이는 합성429에서 새로 실행한 검사나 최종 CI가 아니다.
429 sidecar·권한·41시험·공식 dump와28/26 ordered upgrade trace는46666 그대로다. 공통
journal/resume은 자체 prefix 뒤 cac89 전체 suffix를 보존하며 다른 부모 문서를 삭제하지 않는다.
이번 합성의 두 source 검토·새 정확 CI, 취소/pool·전체 writer closure·RC·durable 복구·
collector/운영 활성화는 별도로 미완이다. 제품 동작·상한·공유 fixture 변경과 새 PG 실행은0이다.

합성 뒤 metadata/429 migration·role/receipt/signature/문서 규약 집중 검사는39 PASS/기존1 SKIP,
2.31초이며 Ruff·redaction·diff 검사도 통과했다. 새 PG 실행은 없고 최종 source 검토·CI는 별도다.
