# scalar batch의 내부 실행 단계 분리

## 변경 범위

기존 한 dataset·한 sealed attempt의 scalar batch를 네 구체 private 단계로 나눴다.
공개 함수·인자·기본값, 입력 정렬과 지문, MAX+1 중단·총1MiB·manifest8192,
협력적 전체30초 및 caller commit/rollback 계약은 그대로다.

| 단계 | 기존 실행 내용 |
| --- | --- |
| _begin_batch | statement deadline → SH 또는 EX/global gate → policy epoch → begin → sealed 입력·dataset·mode·regions·member 범위 검사 |
| _validate_batch_manifest | 모든 target 검증 → 실제 source union의 DISTINCT/LIMIT8193 → 정확 member 수 검사 |
| _apply_batch_items | 정렬된 항목의 기존 source/candidate/winner 적용과 결과 head 수집 |
| _finish_batch | 기존 입력 지문·head 순서의 같은 SHA256 → finish1회 |

_apply_batch는 위 단계를 같은 순서로 await한다. completed의 반환은 begin과
artifact binding 검사 뒤, manifest 검증·항목 DML·finish 앞의 기존 위치에 남겼다.
실패·취소를 잡거나 자체 commit/rollback하지 않으며 기존 caller에게 그대로 전파한다.
추출로 내부 traceback frame은 늘지만 새 재시도·await 내부 작업·SQL·권한은 없다.

목적은 후속 snapshot coordinator가 별도 계약·검증 아래 재사용할 실행 경계를
분명하게 하는 것이다. 이번 변경은 callback이나 coordinator, stamp/evidence/capture
처리를 추가하지 않는다. 실제 SH collector 완주·새 수집 배선·운영 활성화는 미완이다.

## 영향도와 의미 보존 증명

단계 분리의 최초 기준 main은 e07e2050b69cbd114fcdf208997381d0b9aa066e다.
이후 main e7874a00ccb7bacd13d5df897864e51ebca3ef71의 reader422·설계 문서를
통합했으며 단계 분리 모듈은 두 리뷰와 실제 PG 검증을 받은 c76 소스와 byte가 같다.
실제 Codegraph 조회는 _refresh_batch→_apply_batch와 protocol/epoch/begin/finish
edge를 확인했다. native apply edge 누락과 hexdigest 오결박이 있어 graph만으로
폐포를 주장하지 않고 실제 함수 본문 및 직접 caller 검색을 함께 대조했다.
기존 _apply_batch 직접 caller는 같은 모듈의 _refresh_batch 하나다.

감사 map-codegraph-dc8-actual-impact-j-r1.json
(SHA256 b01021578fbfedcdd4ba5f0c619cd70807e5bc66bdff5d056afcd148f7f71e94)와
map-batch-phases-source-proof-r1.json에 근거를 보존했다.
네 새 함수의 docstring과 마지막 전달 return을 제거하고 호출 자리에 본문을 펼치면
기존 _apply_batch 실행 AST와 정확히 같다. 그 외 기존 컴포넌트 AST·공개 signature와
SQL/오류 문자열 순서도 같다. SQL sidecar·migration·ACL·client·provider source는 수정하지 않았다.

## 이 문서 고정 시점의 검증과 남은 gate

- 기존 batch unit10 PASS/1.15초, 해당 모듈 Ruff와 strict mypy1 통과.
- 새 private 함수는 기존 statement를 이동했으므로 구현을 그대로 따라 쓰는 새 모의 시험은
  추가하지 않았다. 기존 실제 PG batch 회귀가 rollback·완료 재생·manifest·mode·owner·
  lease·pool1·SDK legacy claim·SH/EX 동등·짧은 cap을 검증한다.
- 두 독립 소스 리뷰 뒤 c76 정확 소스에서 기존 actual PG20 PASS/23.57초·skip0을
  확인했다. 실제 rollback·취소·완료 재생·manifest·mode·owner·SDK legacy claim·
  SH/EX 동등·짧은 cap·pool1 회귀이며 소유 CID/UUID·runtime backend는0으로 정리했다.
  감사 map1398-c76-local-acceptance.json과 원 로그/XML을 보존했다.
- 초기 c76 CI는 세 Python에서 부모 tasks04 본문423자 제한 위반으로 실패했다.
  제품 실패나 실제 PG 실패로 세지 않으며 원 로그를 보존했다. 이번 통합은 main의
  검토된283자 본문을 그대로 소비한다. c76 단계 분리와 부모의 기존 제품 byte가
  각각 보존되어 추가 로컬 PG는 실행하지 않았다.
- 이 문서 고정 시점 새 합성 HEAD의 정확 CI는 대기다. 새 CI 세대와 최종 부모 합성
  리뷰·수용은 PR 본문과 감사 원장을 참조하며 초기 실패와 구분한다.
- 운영/활성화0, 넓은 T-CWRITE 완료 체크는 변경하지 않았다.
