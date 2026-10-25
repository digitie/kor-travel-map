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
  원5..300 lease·기존logical예약을 보존한다. 아래 순수계량 뒤 Rest 전용8MiB/16 snapshot
  row 정책을 정확 active Rest DS에만 명시했다. global16MiB/256·Airport4MiB/64는 그대로다.
  미설정·소진53000은 유지하며 실제 등록/GC/중복과금 수용은 아직 아니다.
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
432 migration 초기15 statements/후처리3함수 분리만 확인했다. 계획의 RR→RC/frozen binding/reset,
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

## Rest quota 정책의 별도 delta

T의 guarded 순수215 계량 원장
`map432-t-rest-215-pure-logical-reservation-measurement-r2.json` SHA
`3933b453ba6b35fc680e8e16789417fa533e63e76ab723c13bb94d64b7ab97c0`를 사용했다.
정본 lab `_bundle(0..214)`/원clock를 보존한 정상 Dagster Stats builtinset 입력은 artifact
735271B/context1475B이고 결과·후처리 각4096B 고정예약을 더한 logical reservation은744938B다.
원 lab Geo frozenset artifact735277B는6B 더 커 보수 예약744944B로 따로 계산했다. 실제 원천
HTTP/DB apply/물리 heap·WAL·RSS 측정은 아니다. synthetic body44448B/result후보503B/후처리후보
892B를 actual upstream 또는 각4KiB 예약 축소 근거로 사용하지 않았다.

정본 기본 schedule은 월요일04:20 Asia/Seoul(`20 4 * * 1`)이며 terminal GC는7일 초과다.
경계 지연의 기존1+새1과 유한 새root 잔량을 수용하도록 Rest8MiB/16 snapshot을 명시한다.
보수 wire에서는11개8194384B가 fit이고12개8939328B는 거부된다. 허용 최대 payload1MiB+
context8KiB+결과/후처리8KiB=1064960B일 때7개 fit/8개 거부다. 동일 member·동일 bytes 중복은
기존 immutable lookup이 quota 이전에 반환해 추가과금하지 않으며 실제 DB 회귀는 남는다.
manual 새root는 무제한이 아니고 소진 시53000 backpressure를 받는다. active/unsealed GC 금지와
terminal7일 반환은 그대로다. 두 DS 정책의 합12MiB/80은 global16MiB/256 안에 있지만 물리메모리
여유나 CPU 처리량 보장이 아니다. 운영 schedule/override/활성 상태는 조회·변경하지 않았다.

새 seed는 SchemaOwner window의 정확 active Rest DS `INSERT SELECT` 한 문장이다. 임의 DS
기본값/ON CONFLICT 갱신/기존한도 확대·사용량 초기화가 없고 DS 부재는 미설정53000을 유지한다.
초기15파일 checkpoint `c73bb7c2`/inverse `19289739`는 보존하고 이 정책2기존+2신규파일은 별도
검토한다. migration은 이제16 ordered statements이며 SQL 설치·실제 quota/GC·215 apply fit은
여전히 미완이다.

## RC 잠금 후 reader의 별도 서버 한도 보완

Root가 확인한 P2는 실제 코드 경계 불일치였다. 431 SD 자체에는 timeout CONFIG가 없고
초기 Rest RC apply의 fresh SELECT는 outer 기본30초 statement_timeout을 그대로 받았다.
새 회귀 원본5 FAIL을 보존한 뒤 Rest provider의 해당 SELECT만 기존 bounded helper로 서버3초/
lock1초 이하(기존보다 짧으면 그대로)로 제한했다. 정상 조회 뒤 저장한 caller 원2설정을 복원한
다음 decoder/assessment를 실행한다. SQL 오류·취소 뒤에는 복원 SQL로 원오류를 덮지 않고
caller 전체 rollback 계약에 맡기며 SET LOCAL도 rollback으로 복원된다. Airport/SD SQL/ACL/
공통 helper/outer30초/원결과·counter·capture는 바꾸지 않았다.

명시30000/1000·기존750/250·원0 설정과 reader 오류/취소를 포함한 관련 Rest apply/plan 및
기존 transaction_limits 총44 PASS1.62초, Ruff·strict mypy1 source PASS다. 원5 FAIL과 최초
import 정렬 lint1 FAIL도 보존했다. 이것은 순수 실패주입이며 실제 PostgreSQL timeout/rollback/
215 apply/capture 수용은 별도다. 초기 J15와 quota4의 기존 리뷰는 원핀에 한정해 유지하고
이 product1+unit1+report1 보완을 별도 delta로 검토한다.
