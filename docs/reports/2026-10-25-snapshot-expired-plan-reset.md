# 만료된 snapshot kernel 계획의 typed reset

> 2026-10-27 정밀화: 아래 현재 상태/미호출·설치PG0 표기는 최초430 검토 checkpoint의
> 역사다. 기존 expired reset의 live READY 거부는 유지하며, 실제 재현과 현재 executor의
> 별도433 후속은 [bound stale 복구 기록](2026-10-27-bound-snapshot-stale-replan.md)을 따른다.

## 범위와 현재 상태

Root697160d 위 미호출 SQL 조각이다. 기존 artifact/control/attempt schema·일반 kernel·공유
430 wrapper/권한/model/golden은 수정하지 않는다. 별도 PR·SQL 설치·PG·RC/SH 활성화0이다.
등록의 header P2 보정 b0ebebc 및 Root D 전체 합성은 별도 의존이며 다른 작업자 파일을 바꾸지 않는다.

`reset_expired_provider_snapshot_plan(snapshot,generation,fence,expected_attempt,expected_owner,
expected_manifest)`은 current typed executor가 준비된 만료 계획만 해제하는 SD다. 일반 renew와
기존 attempt owner 변경은 제공하지 않는다. expired ready 또는 정확히 결박된 cancelled만
기존 cancel 후 control binding 세 값을 NULL로 만든다. 완료 결과/applying/preparing은 거부한다.
이미 binding NULL이면 `needs_read`만 반환해 옛 임의 attempt의 reset 성공을 주장하지 않는다.
실제 취소+해제한 TX만 `reset`을 반환한다. old attempt의 owner/epoch/manifest/result는 불변이다.

순서는 P SH→actual own parent SHARE→own whole scope UPDATE→old attempt FOR UPDATE→control이다.
외부 dataset/region/EX attempt는 actual attempt row 잠금 전에 거부하고 잠금 뒤 재검증한다.
Root `_lock_provider_snapshot_executor`는 old attempt 뒤에만 호출한다. root/member/L/quota 잠금0,
quota와 artifact·lease·generation·fence·결과 변경0이다. existing cancel의 조건부 scopeowner 해제로
이미 다른 epoch가 잡은 소유권을 되살리거나 빼앗지 않는다. live ready는55P03으로 보수 거부한다.

Root 최종 owner 창에서 private artifact/attempt SELECT 및 attempt row-lock용 UPDATE 권한,
control SELECT/UPDATE와 기존 arm/scope/cancel/typed executor helper EXEC가 필요하다.
일반 runtime raw table 권한은 추가하지 않고 기존 provider executor만 새 typed SD EXEC를 받는다.
정확 owner/권한 배선과 startup 정본은 Root 소유이며 현재 파일은 이를 대신하지 않는다.

복구 caller는 동일 immutable artifact/context를 canonical decode하고 최신 bounded evidence로
새 attempt/owner/key를 claim→append→seal→bind한다. 같은 attempt key 재호출은 lease 갱신이 아니다.
동일 입력을 다시 fetch하지 않으며 applied 결과가 있으면 저장된 원래 결과를 반환한다.
전체 planning deadline/재계획 횟수와 실제 정상 fullapply·worker death 재개는 아직 수용되지 않았다.

## 검증 계획

같은 전용 integration source에서 canonical 등록/기존 claim·seal·bind를 사용해 만료 reset과
새 계획 결박, stale executor/owner/manifest 및 live lease 거부, reset TX rollback과 응답유실의
needs_read, applying holder와 bounded 대기 후 rollback/재계획을 검사한다. fixture에서 lease 시각을
바꾸는 관리 SQL은 만료 장애 주입이며 실제 시간 경과나 typed lease 갱신 성공으로 세지 않는다.
정상 적용 결과 전체/commit 응답유실/worker death는 Root D 후속 수용과 묶어야 한다.

## 첫 고정 checkpoint

전용 통합 source9개를 수집만 했다(1.07초). 기존 canonical 등록 source는 Root 합성 뒤
사용하도록 함수 안에서 import하며, inline 설치나 관리자의 가짜 artifact로 대체하지 않는다.
빈 manifest는 reset의 준비 상태/소유권 시험용이며 artifact 전체 적용 성공으로 주장하지 않는다.
신규9개는 만료 취소·새owner 결박, stale generation/fence/owner/manifest와 live lease5반례,
reset rollback/needs_read, 실제 applying holder 경합·rollback 후 reset, 기존cancel 뒤 다른
attempt의 scopeowner 보존을 검사할 source다. original ready의60초 lease와 SQL timeout을
정본 API로 설정하며 만료 시각만 관리 장애 주입으로 바꾼다. 초기 Ruff 스타일4/5오류 원로그를
보존하고 수정 뒤 Ruff/format·redaction·diff 검사를 통과했다. 실제 PG/ownerACL/전체apply는0이다.

## 합성 begin ABI 정렬

원 d75가 기준으로 삼은 초기 Root helper 이후 `begin_provider_snapshot_apply`가 필수
artifact SHA를 받는7인자로 바뀌었다. 제품 reset SQL은 그대로 두고, canonical 등록에 실제
제출한 payload bytes의 SHA256을 시험 args에 보존해 applying holder의7번째 인자로 넘긴다.
원9개 시험의 assert·timeout·빈 계획 의미는 바꾸지 않는다. source 호환성 보정이며 실제
PG 실행이나 artifact 전체 적용 수용은 아니다. 원 d75와 최초 source 검토는 보존한다.
