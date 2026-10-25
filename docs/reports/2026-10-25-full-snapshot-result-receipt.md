# 동일 실행 복구의 원래 반환값 보존 조각

기준619a6d4f1의 별도 branch에서 처음 신규 module/unit/이 보고서를 추가했고, 이후 아래
미호출 저장/dispatch/lease SQL 조각을 준비했다. 기존 symbol이나
signature를 바꾸지 않아 AGENTS.md의 신규 파일 Codegraph 생략 조건에 해당한다. DB 저장,
권한, lease, actual apply와 SDK0 후속 재개, child/root 완료를 연결한 구현은 아직 아니다.
단독 PR·배포/활성화는 하지 않고 전체 동시 쓰기·복구 단위에 합성한다.

## 보존 계약

`FeatureLoadResult`의 적재6·capture2·Geo6 전체14필드와, 별도 원래 반환값인 `retired`를
빠짐없이 canonical ASCII JSON bytes로 보존한다. 과거 적재 카운트를 현재 DB에서 다시 계산하거나,
완료 kernel attempt의 capture2만으로 원래 결과를 채우지 않는다. `retired`도 기본0을 발명하지
않고 명시로 받는다. 명시 domain/version과 정확한 키만 지원한다.

카운트는 bool/float/string/null 없이 PG bigint 범위의 0 이상 정수다. 전체 snapshot의 causal
capture count와 64자리 소문자 hex hash는 필수다. 입력14필드가 향후 바뀌면 기존 결과 codec의
계약을 명시 변경해야 하며, source unit가 필드 누락을 검출한다. 기존 일반 loader의 capture-null
결과를 이 복구 형식으로 암묵 전환하지 않는다.

출력/입력은4096B로 제한한다. 모든 숫자를 PG bigint 최댓값으로 둔 최악 입력도1024B보다 작다.
decode는 raw bytes/ASCII/크기/두 object 모양을 JSON parse 전에 확인하므로 깊은 임의 구조를
만들지 않는다. 중복키·부분/extra·비정규 공백·미지원 version/domain·coercion을 거부하고,
복원값을 재인코딩한 전체 bytes까지 같아야 한다.

## 권위와 미완 경계

이 bytes 자체는 출처·무변조 또는 적용 완료 증명이 아니다. 후속 private control이 실제
root/child/member와 artifact/code/SDK/clock/domain, kernel attempt/owner/manifest 및 실행 fence에
결박하고, source 변경·kernel finish와 **같은 TX**에 결과를 저장해야 한다. DB raw DML 권한을
일반 runtime에 열어 이 형식을 신뢰하는 구현은 허용하지 않는다. 그 연결과 SQL 검증은 미완이다.

원래14필드+retired 복원은 `DagsterFeatureLoadResult`의 validation/observation receipt나
finding/sync 후속 처리 완료가 아니다. commit 이후 worker가 죽은 경우 원래 입력/관측 시계로
미완 단계를 재개하고 exact child/root 정산까지 연결하는 별도 경계를 건너뛰지 않는다.

## 확인

순수 unit120 PASS/1.36초, Ruff 통과다. 최초 Ruff2개는 새 시험 긴 줄, mypy1개는 새 dict의
value 타입 추론 문제였으며 수정 후 mypy1파일 통과했다. 실제 PG/운영/복구 실패 주입은0이다.
두 독립 source review와 전체 합성 CI를 아직 수행하지 않았다.


## 영속 저장·profile dispatch source 조각

기존 결과 module d11e는 Root/J/W의 독립 source 검토와 각각120개 시험을 통과했다. 그 검토는
다음 신규 SQL의 검토를 대신하지 않는다. 이 SQL 조각은 현재 어떤 migration에서도 호출하지 않는다.

작은 최종 입력과 observation context를 각각1MiB/8KiB로 제한한 immutable artifact 행에 보관하고,
자주 갱신하는 lease/fence와 원 apply 결과4KiB를 별도 작은 control 행으로 분리했다. 따라서
renew마다 큰 payload를 다시 읽거나 입력 SHA256을 재계산하는 구조를 피한다. artifact는 실제
member UUID UNIQUE와 child/member composite FK·root FK를 가지며, 실제 parent/run/exact triple
검증은 이후 등록 SD에서 해야 한다. FK만으로 그 권위를 증명했다고 하지 않는다.

blob은 canonical source history나 공개 Feature 상태의 새 정본이 아니다. 같은 실행을 재개하기 위한
한정된 입력 사본이며 source_records를 대체하거나 별도 후보 원장으로 사용하지 않는다. DB 자체가
NVMe/승인 n150 SSD에 있으므로 이중 파일·DB commit 대신 하나의 PG transaction 경계를 선택한다.
quota 예약/GC/typed 등록·claim·renew·apply 명령과 권한 배선은 아직 없다. active/unsealed GC0과
quota를 잡기 전 P SH→own scope 순서도 후속 구현에서 닫아야 한다.

새 private member dispatcher는 P EX+L 보유 및 RC를 요구하며 잠금을 새로 취득하지 않는다.
실제 child/member UUID를 root와 exact triple에서 먼저 해석하고 그 UUID로 artifact를 조회한다.
artifact 행 부재에서는 기존 aggregate를 쓰며, 이를 legacy EX로 한정하는 것은 후속 typed SH apply의
필수 등록/삭제 방지 불변식이다. 현재 dispatcher가 원 적용의 EX 모드까지 증명한 것은 아니다.
행이 있으면 root/child/run/triple/profile 전부를
대조한다. prepared/control 누락/결과 미완은 거부한다. 적용된 bounded profile은 기존428 capture가
완전하다고 판정한 결과만 반환하며 legacy aggregate로 조용히 바꾸지 않는다.

현재 dispatcher를 load/child/root의 기존 호출자에 연결하지 않았고 새 tables/functions의 owner/ACL,
모델·schema dump·startup, 실제 PG 시험, 전체 forward migration430도 미완이다. SQL은 source draft이며
기능 수용·자동 복구·SH 활성화 또는 운영 변경이 아니다. 실제 source/실패 주입 검토가 더 필요하다.


lease SD source도 추가했다. explicit input/context SHA를 대조한 뒤 P SH→actual own parent SHARE→
whole ops scope UPDATE→control 순서이며 quota나 root/member tuple을 뒤늦게 잡지 않는다.
실제 running STARTED root/단일 child member·활성 dataset/operation·취소/격리 없음을 확인한다.
원 generation/fence가 일치하고 살아 있을 때만 같은 lease를 갱신하고, token 없는 회수는 이전
lease가 만료한 뒤에만 DB가 새 generation/nonce를 발급한다. stale token을 새 권위로 전환하지 않는다.
기존 kernel owner나 원 applied_generation/result는 변경하지 않는다. 이는 논리 실행 lease이고
물리 worker 신원 attestation이나 live old backend 종료 증명이 아니다. 이 SD도 권한/실제 시험/호출자
미연결 source이며 아직 실행하지 않았다. initial registration/duplicate 발급 경계는 J 별도 조각이다.


member UUID를 먼저 조회하는 private SDK0 읽기 SD도 source로 준비했다. actual root/child/member
소속을 확인한 뒤 artifact를 찾고 불일치와 부재를 구분한다. 한 STABLE statement snapshot에서
입력 bytes/context/원 결과와 root·child·취소 상태를 반환한다. active lease의 nonce는 노출하지
않으므로 같은 artifact를 읽었다고 실행 lease를 가로챌 수 없다. terminal 상태도 읽을 수 있으나
자동 재활성화하지 않으며, claim/apply/seal의 fresh 검증을 대체하지 않는다. 이 함수도 현재 미호출이고
runtime EXEC/ACL 및 실제 PG/SDK0 경로 연결은 미완이다.
