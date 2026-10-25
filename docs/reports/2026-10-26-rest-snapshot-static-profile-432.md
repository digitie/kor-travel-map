# Rest432 정적 등록·session apply 초안

## 현재 범위

최신 main df8776903에서 만든 공동 WT의 J 소유 source 초안이다. Root만 stage/commit한다.
새 432 migration/정적 Airport·Rest 분기/명시 session apply와 gateway·private helper 권한을
준비했으며 실제 SQL 설치·PG·HTTP·수집·운영 활성화는 아직0이다. 기존430 SQL 원본과
Airport 공개 own-TX API는 보존한다. 전체432 수용이나215 apply fit 완료로 표현하지 않는다.

## 보존한 경계

- DB가 derive한 정확 dataset에 따라 Airport 기존12 context keys/2730 상한과 Rest13 keys/
  256 상한을 분리한다. Rest export_window는 T와 합의한11 keys·current-export-window/
  strict EOF·원body bytes/SHA·aware clock metadata를 보존한다. SQL header는 DTO 권위가
  아니며 후속 canonical codec이 원clock/내용을 다시 검증한다.
- root/child/member/FK/P/parent/scope/quota/control 순서와 immutable 중복/nonce 비노출·
  원5..300 lease·기존logical예약을 보존한다. Rest quota row는 아직 없어53000으로 거부한다.
  이를 기능완료로 처리하지 않고 실제215 artifact/context/각4KiB 예약 및7일·스케줄·재시도
  잔량 계량 뒤 명시정책을 정한다. global16MiB/Airport4MiB·64 자동확대는 없다.
- provider lowlevel과 client apply_rest_snapshot_in_session은 caller session에서만 동작한다.
  저장Restcodec·실제431 SD의 잠금 후 fresh evidence·동일membership/Geo/policy/23비scalar를
  재검증하고 기존 SH kernel/counter/capture/result14+retired0를 같은TX에 둔다. commit/새
  SDK/EX fallback/seal은 하지 않는다. 정확kernel40001/known evidence race만 typed replan으로
  분류하고 stalefence/일반serialization/연결오류는 성공·reset으로 바꾸지 않는다.
- 새 SchemaOwner private topic helper는 정확 두 행을 C순 FOR UPDATE한 뒤 count2를 요구한다.
  PUBLIC/runtime/Service/Executor EXEC0, CommandOwner EXEC만 추가한다. validated begin의
  fence/domain/원결과/marker 뒤, work 직전에만 호출하며 bump/INSERT/알림 생략0이다.
  기존일반caller의 교착 부재나 직렬화 비용 개선은 아직 증명하지 않았다.
- infra gateway는 exact trusted pins triple의 고정 두 decoder만 선택한다. wire 문자열·foreign
  equality hook으로 profile을 선택하지 않는다. 기존 read/register 서명·원결과 복원은 보존한다.

## 순수 확인과 미완

계획/apply/gateway/startup5모듈115 PASS, strictmypy6 source PASS, Ruff11 file PASS와 실제import/
432 migration15 statements/후처리3함수 분리만 확인했다. 계획의 RR→RC/frozen binding/reset,
교차domain·위조eligible·변경evidence·정확DBAPI분류·privateEXEC True/None 거부를 포함한다.
DB는 대역이며 실제fence·PG 권한·물리race·SQL 설치 수용이 아니다. 원 초기 ACL1FAIL은
frozen430 tuple에 섞인432권한을 별도tuple로 분리했고 unit2FAIL은 고정오류문자열의 검사오기였다.
모든 원log를 보존했다. 캐시 Ruff0.17.2의 기존db.py format차이는 원main에서도 재현돼 무관한
기존 포맷을 바꾸지 않았다. 설치된 pglast가 없어 SQL parser 수용으로 표현하지 않는다.

등록/후처리의 새 정적 분기·선취득 부분을 역제거하면 기존430 등록1함수/후처리3함수의
전체bytes와 정확히 같다. 별도원장 map432-j-static-profile-initial-inverse-proof.json
SHA1928973910e57a6778c9ec1ae19159d88990b27123a9bd3f80334b4ea520ffff에 원본을 고정했다.
실제215 전체 apply/30초·각reader3초·capture2730/256KiB/1MiB fit, quota/GC중복과금·두writer·
unknowncommit/backenddeath/취소·실topic serial구간·최종공식golden/CI/OFF caller 수용은 남는다.
