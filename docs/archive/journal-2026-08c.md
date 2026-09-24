# journal-2026-08c.md — journal.md 아카이브 (2026-08-28 ~ 2026-08-28)

> `docs/journal.md`에서 2026-09-24 분리(규약 §8). 읽기 전용 이력.

## 2026-08-28 — M05 `82850711…` terminal 보존과 runtime setup 진단

Map `35a433173dbd42c096ef08adceb1ae3c142444b4`·PinVi
`fed16a5c0f6e78ee32306b3733a7dc1c8a5641f9`·Manager
`eed1920186b5cb61182a955a6281e49230b80a84`·pinset
`8285071126a58e4807a035753261b0d1f0f4e713fa5934e9d1efa7cbf16f3af9`는 필수 CI와 exact-head
전문 적대 재리뷰 두 건의 GO 뒤 trusted `ktdctl pin rotate-pair`로 결박했다. 새 source의 단발
`run-pinned-rebuild-once`와 registry/public generation `match` gate를 통과한 뒤, 새 root-owned
leaf의 n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. exact unconditional terminal entry의
공개 고정 phase는 `runtime_setup`이다.

따라서 pair rotation·source materialization·Map/PinVi HTTP 계약 이전의 isolated runtime 준비 경계가
후속 Docker Manager 보정 범위다. HTTP·container·환경·output leaf·private receipt 원문은 열거나
보관하지 않았고, 이 pinset·source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는
setup 내부의 안전한 세부 경계만 공개 phase로 분리하고 raw exception은 기록하지 않는다. 이 문서의 merge
revision을 PinVi `admin`·`full` provenance에 다시 결박한 새 pair만 다음 one-shot 후보가 될 수 있다.

## 2026-08-28 — M05 `5592a1d4…` terminal 보존과 phase 수렴 보정

Map `757623973c2e6c082b78332fa25c278ef94f9bab`·PinVi
`358f607a039ffab2dabaadc2eddfc19a7e126f5c`·Manager
`a4d60d16650926c0ac5e5b9a3703c14797259ab4`·pinset
`5592a1d4d98d6757b6a5390a7283b64dc1302abb93ab2dc3b58ef1aed84066c0`는 모든 CI와
전문 적대 재리뷰 두 건의 GO 뒤 trusted `ktdctl pin rotate-pair`로 결박했다. 새 source의
`run-pinned-rebuild-once`와 registry/public generation `match` gate를 통과한 뒤, 새 root-owned
leaf의 n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 terminal이었고 root
registry의 exact unconditional entry는 원문 없이 고정 phase `driver_contract_failed`만 공개한다.

HTTP·container·환경·output leaf 원문은 열지 않았으며, 이 pinset·source pair·Manager source·output
leaf는 재실행하지 않는다. 후속 Manager는 unexpected ordinary exception을 무조건 generic phase로
덮어쓰지 않고, 이미 추적 중인 allowlist phase로만 수렴시켜 raw detail 없이 다음 immutable candidate의
수정 범위를 좁힌다. 이 문서의 merge revision은 PinVi `admin`·`full` provenance에 다시 결박한다.

## 2026-08-28 — M05 `5ad3b08c…` terminal 보존과 안전 phase 진단

Map `053904cebdb004ef1376c0c4cf0255efb02e5ba3`·PinVi
`1b29bfea86af92ad8fd946b967fe6cce331c797f`·Manager
`8f41a9bd797440bc867462da70be0d2dddf085f7`·pinset
`5ad3b08c762db115efe113f2254bea415e674d09677c47e28ba6c197b37bafe0`는 trusted `ktdctl
pin rotate-pair`, `run-pinned-rebuild-once`, registry/public generation `match` gate 뒤 n150 isolated
M04/M05 launcher를 정확히 한 번 실행해 root registry의 exact unconditional terminal entry로 차단됐다.
HTTP·container·환경·output leaf 원문은 열지 않았고 해당 source pair·Manager source·output leaf는 재실행하지
않는다.

후속 Manager `a4d60d1…`은 terminal registry의 공개 reason에 raw detail을 쓰지 않고 allowlist fixed phase만
남긴다. 이 Map 기록 revision을 새 PinVi `admin`·`full` provenance와 함께 다시 결박하고, Manager·PinVi CI와
exact-head 전문 적대 리뷰 두 건이 GO인 fresh pair만 다음 one-shot 실행권을 가진다.

## 2026-08-28 — M05 Manager isolated admission 계약 명시

PinVi의 isolated Compose 경로는 trusted Docker Manager `ktdctl`가 transaction·pinset·Manager/Map/PinVi
revision에 exact 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만
열리도록 정렬했다. 호출자 환경변수 marker, 수동 Compose, 임의 receipt는 실행 권한이 아니며
legacy marker는 거절한다. receipt 발급·주입은 Manager #256, verifier와 실행 gate는 PinVi #500의
paired 변경이고, 본 문서는 Map 소비자 계약을 같은 규율로 갱신한다. 이 문서 변경은 새 pinset이나
n150 one-shot을 만들지 않는다.

## 2026-08-28 — M05 Docker Manager 공개 generation 계약 정렬

M05의 runtime pinning·Map/PinVi pair 결박·one-shot 실행 정본을 trusted Docker Manager
`ktdctl`로 통일했다. 새 후보는 `pin rotate-pair`의 원자 회전만 사용하며, 인증된
`/api/v1/runtime-pins`와 `/api/v1/pinned-runtime/generation` 공개 사본에서 완전한 이전
committed generation 또는 registry가 Map·PinVi revision과 pinset까지 exact로 차단한 terminal
generation의 `pending_rebuild` 또는 `match`를 확인한다. 새 launcher 뒤에는
`pinset_binding=match`를 다시 요구한다. partial·malformed·phase-scoped block·drift·unknown
generation은 gate를 열지 않는다. private manifest/journal, raw launcher output, 기존 terminal
artifact는 Map이 읽지 않는다.

Map C7 attestation의 manifest v6/journal v8 exact schema·키·version은 Docker Manager 공개
generation 계약과 paired PR로만 바꾼다. 이번 동시 정렬은 journal의 3개 PinVi role extension을
포함한 16-key exact dict와 committed 상태의 catalog reset·lifecycle block 의미까지 검증한다. 이
문서 정렬 자체는 새 n150 candidate나 one-shot을 만들지 않으며, 이전 terminal pinset을 재실행하지 않는다.

## 2026-08-28 — M05 `b46743ea…` terminal 보존 후 대기

Map `6bfa47038b439845662f89524531d2ef72374c2a`·PinVi
`340717de33b3672f7da84795626c4302eddd1176`·Manager
`00c33ad79f8e43b01fe543699428701aa9733c67`·pinset
`b46743ea72d86329d9574c21cc445fb9b33fdeaad07a2704a68a91fd7a0a89fe`는 PinVi·Manager CI와 exact-head 전문 적대
리뷰 두 건의 GO, clean trusted release, atomic pair rotation과 registry/public-copy gate 뒤 n150 isolated
M04/M05 launcher를 정확히 한 번 실행했다. 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact unconditional terminal entry와 public copy를 확인했다. 이 candidate·source pair·Manager
source·output leaf는 절대 재실행하지 않는다. 사용자 지시에 따라 새 source·pair·pinset 생성이나 후속 n150 실행은
여기서 멈추고, 현재 terminal 기록을 보존한 채 대기한다.

## 2026-08-28 — M05 finalization receipt P1 보정

전문 data-contract 적대 재리뷰는 이전 Manager `862e8bf…`가 main `try`의 unexpected ordinary exception만
`driver_contract_failed` receipt로 수렴하고 cleanup·terminal block의 ordinary exception은 result 없이 전파할 수
있다는 P1을 확인했다. 이 문제는 terminal `41be91fe…`의 raw artifact를 열거나 재실행하지 않고 정적 경계 검토로만
발견했다.

Manager `00c33ad…`는 main·cleanup·terminal block의 ordinary exception을 `BaseException`과 구분해 원문 없이
동일 fixed terminal receipt로 수렴시킨다. cleanup 및 terminal block 오류 주입 회귀도 추가했다. 다음 후보는 이
terminal 기록을 포함한 새 Map revision과 새 PinVi provenance, 이 Manager source를 fresh atomic pinset으로 결박하고
CI·정확한 head 전문 적대 리뷰 두 건을 통과한 경우에만 만든다.

## 2026-08-28 — M05 `41be91fe…` safe launcher terminal 보존

Map `fa55316d858d95367b6a1ca6f17094408b543afe`·PinVi
`f9fce72fbc6ef73f3ec1700ef76995fdfc068e88`·Manager
`cd8b3054d9f49af88ef6f58e9319343c1453df27`·pinset
`41be91feb62feff039452e23a0d889c3b32c3e97e08c28e86ad0a1068ec8ad67`는 최신 CI와 exact-head 전문
적대 리뷰 두 건의 GO, trusted clean Manager release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact Map·PinVi·pinset의 unconditional terminal entry와 public copy를 확인했다. 이 candidate와
source pair·Manager source·output leaf는 절대 재실행하지 않는다. 다음 후보는 이 terminal 기록을 포함한 새 Map
revision, PinVi `admin`·`full` paired provenance revision, 예상하지 못한 ordinary driver exception도 원문 없이
`driver_contract_failed` fixed receipt로 남기는 Manager `00c33ad…` source를 새 atomic pinset으로 결박하고 최신
CI와 전문 적대 리뷰 두 건을 다시 통과한 경우에만 만들 수 있다.

## 2026-08-28 — M05 `5512ce12…` safe launcher terminal 보존

Map `73150672d26866122e231c085e9beefe81bfd776`·PinVi
`d8dc386dec7a800b83d457e1753b63f51470afc6`·Manager
`c31c8448fcade3ace84b0dbd0682328283ae20b9`·pinset
`5512ce12ca316e10404b9faf60eba8130815a4c7cdb3b91f4d8c80de1805cc8d`는 최신 CI와 exact-head 전문
적대 리뷰 두 건의 GO, trusted clean Manager release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact Map·PinVi·pinset의 unconditional terminal entry와 public copy를 확인했다. 따라서 이
candidate의 source pair·Manager source·output leaf는 절대 재실행하지 않는다. 다음 후보는 이 terminal 기록을
포함한 새 Map revision, 새 PinVi paired provenance, 새 Manager source를 새 atomic pinset으로 결박하고 최신 CI와
전문 적대 리뷰 두 건을 다시 통과한 경우에만 만들 수 있다.

## 2026-08-28 — M05 safe-result 부재 terminal 보존

Map `f90b7c28ee0a51cc5e2dce7a332e7feef9afe477`·PinVi
`fdff06ba746bf2de198fab075a356f88b9f228c9`·pinset
`fa28a6e7d7ee27b7bb6be6cd6c0a04ffc458cda329beca339a4ce6d038480381`은 최신 CI와 전문 적대
리뷰 두 건의 GO, trusted Manager `b45f54d5…` release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 허용된 durable safe result는
없었다. 원문 HTTP·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 `pin verify`는 exact pinset이 terminal로 차단됐음을 확인했다. 따라서 `fa28a6e7…`과
`a3f6a8f3…`·`22563762…`·`c700bd2e…`의 source pair·Manager revision·output leaf는 절대 재실행하지 않는다.
다음 후보는 이 terminal 기록을 포함한 새 Map revision과 새 PinVi provenance·새 Manager source를 새 atomic
pinset으로 결박하고, safe result 부재도 원문 없이 고정 분류·보존할 수 있을 때만 만들 수 있다.

## 2026-08-28 — M05 Map health terminal 보존

Map `bbb29d17751aa0ece0b76f3c8724a0073aa9dafc`·PinVi `663e21b4fdc2a4fc5e51a07f7a7532282aaa5423`·
pinset `c700bd2ec2d2c181e60c1dd99a13022ff8a2ce30bb19de3bb871806be80ee1ef`은 최신 CI와 전문 적대
리뷰 두 건의 GO, trusted Manager `4a6e1b0…` release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. durable safe result는 `map_health_http_failed`이고
cleanup은 통과했다. HTTP 원문·컨테이너 로그·환경값은 읽거나 보관하지 않았다.

driver는 이 pinset을 root registry에 조건 없이 terminal 차단했고 이후 `pin verify`가 재실행 불가를 확인했다.
`a3f6a8f3…`·`22563762…`·`c700bd2e…`의 source pair·Manager revision·output leaf는 절대 재실행하지 않는다.
다음 후보는 이 terminal 기록을 포함한 새 Map revision과 새 PinVi provenance·새 Manager source를 새 atomic
pinset으로 결박한 경우에만 만들 수 있다.

## 2026-08-28 — M05 HTTP terminal 보존과 단계 고정 분류 보정

Map `b8d108bd…`·PinVi `50c875f5…`·pinset `22563762…`은 root registry/public-copy gate를 통과한 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. durable result의 고정 분류는
`runtime_http_failed`였고 cleanup은 통과했다. raw HTTP 응답·컨테이너 로그·환경 출력은 읽지 않으며,
동일 pinset·Manager source·output leaf는 어떤 사유로도 재실행하지 않는다. root registry는 이
candidate를 같은 고정 분류로 즉시 terminal 차단했다.

Manager #253은 다음 fresh candidate에서 HTTP 실패를 호출 단계별 허용 enum으로만 기록하도록 보정한다.
새 Map 기록 revision과 PinVi `admin`·`full` paired provenance revision을 atomic `pin rotate-pair`로 함께
회전하고, CI·전문 적대 재리뷰 두 건·registry/public-copy gate가 모두 정합할 때만 새 root-owned
output leaf에서 M04/M05 live E2E를 정확히 한 번 실행한다.

## 2026-08-28 — M05 installed-wheel preflight terminal 보존과 새 pair 조건

Map `e6c08e25…`·PinVi `932fb140…`·pinset `a3f6a8f3…`의 isolated launcher는 trusted release 검증 뒤,
installed wheel의 project-root 계산이 runtime registry보다 먼저 실패해 종료했다. Docker·Compose·DB·driver
ledger 전이었지만 단회 실행권은 이미 사용됐으므로, Manager root registry는 이를 `launcher_preflight` terminal
evidence로 차단했다. 같은 pinset·Manager source·output leaf는 어떤 사유로도 재실행하지 않는다.

Manager #253은 trusted venv의 `python -I`가 `sys.prefix`로 canonical `/opt` root를 인식해 external registry와
public copy를 선택하도록 보정했고 전문 적대 재리뷰 두 건의 GO를 받았다. 다음 candidate는 이 Map 기록 revision과
PinVi 후속 provenance revision을 atomic pair rotation으로 새 pinset에 결박한 뒤, CI와 registry/public-copy gate를
다시 통과해야만 n150 M04/M05 isolated E2E를 정확히 한 번 실행할 수 있다.

## 2026-08-28 — M05 atomic pair rotation과 ledger 선행 gate 반영

Manager 전문 보안 재리뷰는 terminal seed에서 Map·PinVi를 role별로 회전하면 intermediate pinset이
one-shot ledger를 소비할 수 있음을 P1으로 확인했다. Manager PR #253 source `02cc8de…`는 terminal current의
single-role 회전을 거부하고 `pin rotate-pair`의 단일 registry replace로 두 source를 함께 회전한다.
M05 launcher도 source pair preflight 뒤에만 ledger를 claim한다.

따라서 Map `e6c08e25…`·PinVi `932fb140…`의 final `a3f6a8f3…`만 새 candidate가 된다. invalid pair,
intermediate state, static image digest 추측, 과거 terminal candidate 재실행은 여전히 허용하지 않는다.

## 2026-08-28 — M05 Docker Manager runtime pin registry 반영

Docker Manager #251은 Map·PinVi revision과 terminal pinset lifecycle의 정본을 source 상수에서
trusted release 밖 root-owned runtime pin registry로 옮겼다. Map `e6c08e25…`와 PinVi
`932fb140…`은 추적되는 seed를 편집하지 않고 host에서 `pin init` 뒤 atomic `pin rotate-pair`로
`a3f6a8f3…` candidate를 만든다. `cbb577d3…` seed는 terminal historical evidence로 보존한다.

새 candidate는 `pin verify`의 registry·공개 사본 gate, root-owned Manager provenance, PinVi pair의
source/OpenAPI/image identity가 모두 맞을 때만 한 번 실행한다. intermediate state, static image digest
추측, 과거 terminal candidate 재실행은 허용하지 않는다.

## 2026-08-28 — M05 PostGIS baseline digest source 병합

Map PR #1099는 `e6c08e2598a6f8b6fda605be271e8d384213de58`로 병합됐다. Compose `postgres`는
application `300` baseline reference의 immutable PostGIS digest를 직접 사용하고, unit gate는 reference의
repository·image ID와 Compose 값을 exact 비교한다. 전문 적대 리뷰 두 건은 P0/P1 없이 GO했고 lint,
OpenAPI, fixture replay, Python 3.11/3.12/3.13 및 PostGIS 통합 CI가 모두 통과했다.

기존 `29fbcdd…` terminal candidate는 그대로 보존하고 재실행하지 않는다. 다음 단계는 이 병합 revision의
 paired application candidate를 PinVi `admin`·`full` provenance에 결박한 뒤 Manager runtime pin registry를
 회전하는 것이다.
그 새 candidate만 n150 isolated M04/M05 live E2E를 정확히 한 번 실행할 수 있다.

## 2026-08-28 — M05 fresh baseline PostGIS image drift 원인 확정

`29fbcdd…` isolated candidate는 `baseline_reference_invalid`로 terminal 처리됐고 재실행하지 않는다.
원문 Docker log·stderr·환경값은 읽지 않았다. exact Map `9c64e862…`의
`application-reference.json`, manifest sidecar, 그리고 tracked baseline artifact를 정적으로 재검증한
결과, 이전에 기록한 `application-seed.sql` 불일치는 없었으며 모든 declared digest가 실제 bytes와
일치했다. 따라서 그 주장은 철회한다.

n150의 읽기 전용 image identity 확인에서는 Map Compose의 부동 `postgis/postgis:16-3.5-alpine`
태그가 baseline reference가 결박한 immutable PostGIS image와 달랐다. 이 baseline은 catalog receipt를
exact image identity에 결박하므로, 새 fresh DB가 다른 image에서 생성되면 receipt mismatch로
fail-close하는 것이 정상이다. Map Compose를 baseline reference digest에 직접 고정하고, committed
Map revision을 PinVi pair·Manager pinset에 재결박한 새 candidate만 실행한다.

## 2026-08-28 — `c1ad5a3e…` root-owned one-shot committed

PinVi `41a36ee6…`·Map `9c64e862…`의 `c1ad5a3e…` candidate는 exact Manager trusted release에서
root-owned structured launcher로 정확히 한 번 실행돼 `committed` 됐다. durable result는 generation
`8eedf171…`, Map application `300`, Map Dagster `29b539ebc72a`, PinVi `20260824_0101`을 확인한다.
이제 이 immutable pair에서만 isolated M04 승인·Map `rebind`·PinVi terminal receipt/ACK과 signed M05
activation attestation을 실행한다.

## 2026-08-28 — M05 provenance 재결박과 새 one-shot candidate

`030b12fc…`은 Map `9c64e862…` 및 committed API/UI image identity를 사용한 generation으로 보존하며 재실행하지
않는다. `6269138f…`은 durable journal/manifest를 남기지 못한 pre-journal 단회 시도로 보존하며 raw stderr를 읽거나
재실행하지 않는다. `53d4639f…`은 installed launcher execute bit 미보존으로 admission 이전에 끝났고 durable output·ledger·raw stderr가 없어 재시도하지 않는다. PinVi `41a36ee6…`은 M05 attestation pair와 이 실행 경계를 기록하고, Manager `c1ad5a3e…`는
그 exact PinVi/Map source와 canonical hash를 고정한다. 다음 official rebuild는 installer가 executable로 보존한 root-owned structured result launcher로
이 새 pinset에서 단 한 번이며, 성공한 committed generation만
isolated M04/M05 live mutating E2E와 signed activation attestation에 사용한다.

## 2026-08-28 — M05 scoped cleanup generation committed

Manager `519edd9…`, PinVi `69a5ac65…`, Map `9c64e862…`의 `030b12fc…` pinset은 trusted n150 release에서
official `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 committed 됐다. seven-runtime generation과 Map
application `300`·Map Dagster·PinVi `20260824_0101` schema head를 고정 필드만으로 확인했다. historical candidate와
원문 stderr·DB catalog 값은 읽거나 재사용하지 않았다. 다음 단계는 같은 immutable pair의 isolated M04/M05 live
mutating E2E와 activation attestation이며, 성공 전 두 코드 PR은 병합하지 않는다.

## 2026-08-28 — M05 v2 permit scoped external membership cleanup

사용자의 완주 지시에 따라 target 밖 stale membership 철회는 Manager root-owned v2 permit의 exact
`revoke_external_memberships` scope로만 허용한다. permit은 transaction·pinset·PinVi DB identity에 결박되고, PinVi는
legacy permit 또는 다른 scope를 reset 전에 거부한다. PostGIS 회귀는 target→external·external→target 두 방향 모두에서
target membership만 제거되고 external role은 보존됨을 확인한다. Manager `519edd9…`, PinVi `69a5ac65…`, Map
`9c64e862…`의 `030b12fc…`만 다음 n150 official candidate다.
