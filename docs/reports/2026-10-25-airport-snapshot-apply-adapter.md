# 저장된 공항 입력의 SH apply adapter 미호출 초안

기존 코드·SDK 의미를 유지하는 작은 전체 공항 입력부터 실제 적용 경계를 연결한다.
현재 조각은 아직 collector에서 호출하지 않고 migration도 설치하지 않는다.
입력·observation codec의 검토된 source741069와 Root의 저장·원 결과·lease·apply receipt
source508a를 별도 integration worktree에 합성했다. 다른 원본 저장소의 변경은 복사하지 않았다.

## 구현한 경계

- 입력 bytes를 expected pins의 정본 codec으로 다시 복원한다. 준비된 RR evidence는
  적용 권위가 아니며 eligible/전체 EOF/정본 scope를 요구한다.
- P SH와 policy epoch를 확보하고 기존 kernel의 정렬된 모든 parent→scope→source/link/
  Feature 잠금을 유지한다. 새 begin은 control fence와 실제 등록 artifact SHA를 대조한다.
- 잠금 뒤 정본427 SD를 새 statement로 읽고 decoder 결과 전체를 준비 evidence와 비교한다.
  불일치·미지원이면 source DML 전에 거부하며 EX로 암묵 전환하지 않는다.
- 기존 native batch의 manifest 검증·source record/head·후보·winner 적용과 finish를 재사용한다.
  기존 helper의 반환 의미를 바꾸거나 별도의 provider client를 구현하지 않는다.
- 같은 적용 TX에서 기존 integrity observation run을 원 observation_generation으로 먼저
  예약한다. worker 재개 시점이 원천 적용 순서보다 뒤로 밀려 새로운 generation을 받지 않는다.
- 작은 typed SD가 실제 잠긴 manifest/primary source의 Feature revision과 원 payload의
  record 존재를 적용 전후에 읽는다. 이를 원 features_updated/source_records_inserted로
  계산하고 그 자리에서 full14+retired를 보관한다. 후속 재시도에서는 재계산하지 않는다.
- bounded capture를 같은 TX source-head와 확인한 뒤 kernel completed/apply_txid와 원 결과를
  함께 control에 기록한다. commit 응답 유실 후 이 apply를 재호출하지 않고 SDK0 member read를
  사용하는 후속 worker 연결이 필요하다.
- 첫 profile은 SH unchanged Airport만 허용한다. bind는 EX attempt를 거부한다. 미지원 입력의
  기존 EX fallback은 이 profile을 등록하기 전에 기존 경로로 결정해야 한다.

SDK0 read는 원 kernel attempt/owner/manifest/status/input digest/lease metadata도 반환하도록
확장했다. binding 불일치나 applied인데 kernel completed가 아닌 상태는 거부한다.
executor fence는 이 read에 노출하지 않는다. 기존 raw 읽기 권한은 추가하지 않는다.

## 확인과 남은 작업

순수9개가1.30초에 통과했고 Ruff2파일·제품 mypy1파일도 통과했다. 실제 정본 converter/codec/
427 decoder와 synthetic DB wire를 사용했다. 원 counter와 capture 보존, 잠금 뒤 evidence 변경,
source 누락·DML 오류·잘못된 artifact/pins/preparation/TX의 fail-closed를 확인했다.
실제 asyncpg UUID subclass를 순수 경로에서 사용해 canonical UUID로 정규화했다.
초기 시험의 오류 메시지 regex2개와 형식 오류는 고쳤으며 PG 실패/수용으로 계산하지 않는다.

현재 시험은 DB 호출 대역을 사용한다. 실제 source DML·권한·잠금 순서·동시성·성능을 증명하지
않는다. SQL·새 adapter의 독립2인 검토, whole430 owner/ACL·head oracle·startup 합성,
quota 설정/terminal GC, expired plan reset/SDK0 gateway, 원자 후처리 coordinator/receipt,
기존 public finish 우회 차단과 실제 collector/step retry 연결이 남았다.
새 profile의 실제2worker/EX/leaf 경합, commit 전후 worker 종료와 응답 유실/lease·quota 장애
통합 시험 및 전체 CI·live UI·운영 배포/실측 전에는 동시 쓰기를 활성화하지 않는다.

## 준비 판정과 실제 입력의 P1 결박 수정

두 독립 리뷰에서 bc224가 입력A의 실제 eligible 준비를 입력B에 재사용할 수 있음을
순수 반례로 확인했다. 같은 entity의 변경 raw나 다른 Geo 주소를 가진 canonical artifact도
기존 `_inputs`와 DB evidence끼리의 비교만으로는 source DML을 막지 못했다.
초기9개 mock 시험은 이 반례를 포함하지 못했으며 실제 PG 성공을 뜻하지 않는다.

기존 RR reader 아래 의미 판정을 공유 pure assessment로 분리했다. apply는 실제 입력 bytes를
decode하고 잠금 뒤 fresh SD evidence를 읽은 후 실제 bundle/Geo와 함께 이 평가를 다시 한다.
기존 eligible 플래그만으로 DML에 들어가지 않는다. 기존 준비 API signature와 RR/read-only
요구는 유지하며 새 helper에 DB/SDK/Geo I/O는 없다. 평가 실패는 EX로 암묵 전환하지 않는다.

실제 converter·codec로 만든 대체 raw의 부정 반례를 추가했다. 신규10+기존 준비14개가
24 PASS/1.73초였고 Ruff3파일도 통과했다. 초기 refactor의 dataset 지역변수 누락은 Ruff에서
확인해 고쳤다. 잠금/권한/전체430 PG 수용은 아직 별도이며 원 bc224 HOLD는 보존한다.
