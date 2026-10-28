# 작은 전체 dataset의 bounded evidence chunk 계획과 큰 snapshot의 별도 로드맵

> **상태(2026-10-27): 대체됨(superseded).** 작성 시점의 설계다. 구현은 411~432로 머지됐고
> ([432 구현 원장](2026-10-26-rest-snapshot-atomic-implementation.md)), SH 스냅샷·스칼라 정책
> 경로는 운영에서 꺼진 채 동결됐다(동결 → 측정 → 퇴역 결정 대기). 현재 상태의 정본은
> [ADR-115](../adr/115-scoped-concurrent-feature-writes.md)다. 이 문서로 활성화나 운영 수용을
> 판단하지 않는다.

2026-10-25. 설계만. 정본 읽기 기준 f89b6416470168521b03b009f45d87374c4fb720(제품은7e와동일) + 별도 reviewed reader3bfa51bc8d52cf17cd05d49f479bfbc82d9e75af의 실제 공개 인터페이스. 이 문서는 실제 운영 수집기의 구현·활성화 완료를 뜻하지 않는다. 잠금·stamp 기반은 PR #1394로 머지됐고, reader는 PR #1395에서 별도로 검증 중이다.

## 0. 먼저 통과해야 할 실제 전체 입력 문턱

[작은 reader 비용 관찰](2026-10-25-heritage-reader-cost-observation.md)은 같은 fixture의 무관 current 묶음0/1만에서만 측정했다. 17건 성공·18건 예산 거부는 해당 payload의 결과이며 일반 page 크기가 아니다. 실제 전국 입력·전체 apply30초·worker 복구는 이 측정으로 수용하지 않는다.

- 현재 확정된 첫 SH 운영 pair는 없다. Heritage4279/world9494는 기존2730/8192 문턱 밖이다. MCST49/50/51은 reader whole256KiB가 raw+entity+head에서 이미 넘는다(7ec677… 원시 metadata); reader **호출당** 예산으로 나누는 것은 검토할 수 있으나 full artifact 예산을 나누는 허가는 아니다.
- exact public DTO 구조·8-per-node 순회의 offline 하한을 계산했다. FeatureBundle→Feature/Coordinate/Address/Urls/PlaceDetail→SourceRecord/Link/presence 구조를 유지하고 모든 문자열 **값** 길이를0으로 낮춰도 coord가 관찰된49/50/51은 item2094B, full batch는49(327)=684778B/50(1059)=2217586B/51(786)=1645924B/52(411, coord 미관찰이므로 None skeleton)=845056B다. 50/51은 raw를 비운 구조만으로 prewalk1MiB에서 불가다. 49/52는 하한이1MiB보다 작다는 것뿐이며 실제 성공은 미증명이다.
- 근거 map-small-snapshot-structural-budget-j-r2.json SHAe61c60ad4c78d1b944bd49b46fe1203b74c5d1d57d2f884ef8d8c2b62f3ecaf9. 유효 public DTO skeleton은 provider conversion/실제 수집 fixture가 아니다. 원천 값은 직렬화하지 않았다. JSONB physical 크기를 prewalk/UTF8 artifact 크기로 그대로 더하지 않는다. 411건 DS52 raw byte는 이번 metadata query 대상도 아니다.
- **MCST adapter 구현 전** 기존 SDK·정본 converter가 내놓은 실제 한 전체 snapshot의 최종 typed input으로 현 `_prepare_batch`/전체 artifact gate 성공을 먼저 관찰해야 한다. 필요한 실제 public 입력 수집·안전한 취급/실행은 별도 설계·두 리뷰·실측 수용으로 닫을 범위이고 여기서는 하지 않았다. 옛 DB row 수도 새 fetch 전체 크기 증거가 아니다. 이후 모든 실제 run에서 같은 gate를 DML 전에 다시 수행한다.
- gateway는 전량 canonical converter/주소검증/Geo 결과가 나온 뒤 caller가 독점 소유한 입력이다. 2730 MAX+1/중복 Feature·source entity/단일 DS/전체 prewalk+encoded1MiB/depth64, manifest8192개+DB총byte1MiB/append256개·128KiB, participant32, apply30s를 그대로 유지한다. 단1개의 고정 scope조차 실패하면 잘라서 성공시키지 않는다.

## 1. 실제 연결 seam — 기존 코드를 잘못 우회하지 않는다

- `client/__init__.py:1196–1219`: `load_feature_bundles(...curation_dataset=...)`는 한 TX의 load+현재집합 capture. MCST는 `mcst_features.py:191–214`→`assets._load:1345–1387`→`etl.py:441–463`의 authoritative non-retire 분기에서 **이 메서드**로 들어온다. A3 Options가 있는 `load_authoritative_feature_snapshot:1506–1585`에만 새 option을 넣으면 MCST 실제 배선이 아니다.
- 명시 exact provider/dataset·retire mode의 SH 옵션은 defaultNone/추가SQL0, transaction-bound caller 거부를 유지한다. 선택된 전체 입력에서만 아래 prepare→apply를 순차 수행하며 pool1에서 연결을 동시에 두 개 빌리지 않는다. 아직 옵션 이름/새 signature는 확정하지 않는다.
- Heritage의 실제 path는 `assets.py:352–409`의 geometryless-area retire이므로, SH의 retire0 판정 없이는 적용하면 안 된다. MCST는 `retire_absent_from_snapshot`이 없고 없어진 CSV 행을 보존하는 기존 의미다. 이를 임의로 retirement로 바꾸지 않는다.
- 기존 `load_feature_bundle_batches:1417–1456`/BundleSpool은 전량 fetch 후 단일 TX라는 경계의 참고일 뿐이다. 이것을 SH whole artifact 또는 kernel budget 통과 증거로 쓰지 않는다.

## 2. 작은 전체 input 안에서만 증거 조회를 나누는 계획

### A — 불변 입력 준비

1. upstream/공개 SDK/converter/주소검증/Geo가 끝난 **같은 전체 source 입력**을 고정한다. fetched/imported clock·raw hash·Geo token·normalizer registry version을 이번 operation에 결박한다. 재계획 중 SDK 재수집이나 다른 coroutine의 DTO/raw 변이는 금지한다. 기존 frozen wrapper만으로 nested DTO 불변이 되지 않으므로 별도 소유/복제 경계를 정한다.
2. 현 full `_prepare_batch`로 canonical sort/전체 input_digest와 실제 byte 성공을 확인한다. 여기서는 최대1MiB 입력을 보관하는 현 tuple/DTO 정책을 유지한다. reader chunk 때문에 이 full tuple을 제거했다고 주장하지 않는다.
3. input 전체의 canonical source keys/Feature UUID는 고정 크기 배열로 보관한다. 최대2730/중복0, 순서와 대상 집합의 digest를 만든다. 원천 자연키·provider label을 임의로 UUID identity로 바꾸지 않는다.

### B — 한 RO RR snapshot에서 chunk planning

4. 별도 짧은 **REPEATABLE READ READ ONLY** TX에서 STABLE pure-read SD reader를 순차 호출한다. reader에 protocol/epoch rowlock/DML/volatile side effect를 넣지 않는다. 한 STABLE call의 statement snapshot만으로 여러 RC call의 같은 snapshot이 되지 않으므로 RC 여러 SELECT를 같은 계획이라고 부르지 않는다.
5. 각 requested chunk에 direct metadata-first/최초 detoast guard/binary256KiB/encoded1MiB를 독립 적용한다. 한 chunk의 알려진 `budget_exceeded`는 아직 full-DS EX 사유가 아니라 그 요청을 둘로 나눌 수 있는 신호다. 전량을 방문하며 request64 같은 시작 page 크기는 성능 선택일 뿐 전체N을64로 제한하지 않는다. 단일 entity도 예산/압축/shape를 만족하지 못하면 그 전체 SH 계획은 known unsupported다.
6. adaptive split은 최대2N-1 방문의 유한 상한과 전체 planning wall deadline을 둔다. deadline/취소/DB transport error는 `unsupported`가 아니며 자동 EX 재시도하지 않는다. 무한 chunk 분할·마지막 성공 chunk만 수용·오류를 빈 결과로 바꾸기 금지다.
7. chunk를 decode→exact old/new SDK/A1 의미 비교→compact dependencies/고정폭 fingerprint 누적 뒤 즉시 폐기한다. 전체 raw/base/candidate evidence를 list로 합치지 않는다. 전량 보관 가능한 것은 (a)원래 bounded input, (b)kernel 제한 안의 compact manifest≤8192/1MiB, (c)기존 stamp SD가 요구하는 full target vector≤2730/1MiB, (d)고정폭 전체 fingerprint와 row/byte 합계뿐이다. 각 합계/배열도 별도 예산을 실제 검사한다. 이것은 peak RSS 증명은 아니다.
8. 첫 snapshot의 policy epoch/target-set digest·전체 header/policy fieldset·normalizer authority를 각 chunk가 같은 값으로 반환하게 한다. epoch는 새 caller 라벨이 아니라 SD가 읽은 DB singleton 값이다. 실제 reviewed422 reader3bfa의 `_422_read_heritage_evidence.sql:23,290–291`은 DB singleton을 읽은 top-level policy_epoch를 이미 반환하고 `heritage_evidence_reader.py:269–291`가 해석한다. 이 기존 인터페이스를 참조하며 epoch 반환 기능이 없다고 가정하지 않는다. 다만 MCST 지원 자체는 그 Heritage 전용 구현에 들어 있지 않다.
9. compact evidence fingerprint는 타입태그·길이prefix·C정렬의 고정폭 fold로 정의한다. JSON null/SQL NULL, 생명주기, row_revision, all-role membership+head, policy/header, R1/R2 provenance, non-name base24, Geo stamp/token과 의미에 영향을 주는 모든 read dependency를 포함한다. 불완전한 hash를 authority로 삼지 않는다. server payload 일괄 json_agg를 새로 만들지 않는다.

### C — compact manifest 예약 후 한 RC apply

10. RO RR TX를 닫고 같은 pool의 별도 짧은 RC TX로 기존 claim→append≤256→seal을 수행한다. preparing/ready 상태만 남는 실패는 정확 own attempt를 cancel하고 lease 경계를 보존한다. 새 테이블·서버 export snapshot·별도 고권한 session을 첫 버전에 추가하지 않는다. planning과 apply 사이의 공백은 아래 재검증으로 닫는다.
11. apply는 **READ COMMITTED 한 TX**. protocol SH→policy epoch SHARE→기존 begin 순서를 지킨다. begin은 participant DS 전부를 ID순으로 선점(own wholeDS UPDATE/외부SH)→모든 source/head→all-role links→Feature 순이며, 기존 revision/head/membership digest 및 신규 link 재검증을 그대로 사용한다. claim이 증가시킨 own dataset epoch는 claim 반환/기존 kernel이 검증하며 planning epoch와 단순 등호로 비교하지 않는다. planning policy epoch는 lock 후 새 statement에서 비교한다.
12. 기존 kernel은 선언 manifest 외 claim/redirect/catalog/전체 phantom 완결성을 보장한다고 선언하지 않는다. DML 전에 전체 exact input identity/active-policy target set/current provider claim/행 상태를 추가로 검증해야 한다. 첫 subset은 모든 role가 정확 지원 primary 하나이며 다른 link/provider/shared-source/retired 복구/new identity/Geo·분류·base 변화이면 EX다. 범위를 넓히려면 closure 전체를 지원해야 한다.
13. begin으로 **전체 manifest 잠금을 잡은 뒤**, 아직 source DML 전, 같은 chunk boundary로 fresh STABLE SELECT들을 다시 읽고 의미를 전수 검사한다. source/head/link/Feature lock+policy epoch가 재검증 사이의 변화를 실제 막는지 경합 시험으로 증명한다. private policy/candidate/base/claim/stamp에 이 lock들로 막히지 않는 writer가 하나라도 있으면 이 설계는 아직 OPEN이다. chunk hash가 계획과 다르면40001로 TX전체 rollback, bounded fresh plan만 허용한다. policy epoch 변경을 `known unsupported`로 뭉개지 않는다.
14. **모든 chunk가 통과하기 전에 첫 source DML을 하지 않는다.** whole snapshot exact input_digest/full manifest를 다시 확인하고 기존 native batch source/candidate/winner DML을 수행한다. DML 중 오류·취소·worker 사망은 한 TX 전체를 되감는다.

## 3. stamp와 batch orchestration의 실제 추가 seam

현재 `_421_validate_scoped_stamps.sql:48–69`는 applying/sameTX/SH/입력digest와 **전체 manifest target set**을 검사한다. chunk별 stamp SD 호출을 허용하지 않는다. 순서는 begin → full target stamp preflight → 모든 chunk fresh eligibility와 전체 capture-closure guard → 전체 native source DML → full target stamp reobserve → 정확 capture1회 → kernel finish1회다. accepted source key==input 검증은 reobserve 단계에 유지한다. stamp evidence가 바뀌면40001이며, 행당now()는 같은TX clock으로 기존 의미를 보존한다.

현재 `scoped_provider_batch._apply_batch:203–262`는 begin→source loop→finish를 한 함수에서 처리하여 위 preflight/reobserve를 끼울 수 있는 public phase가 없다. 최소 제품 변경 후보는 이 함수를 같은 validation/DML/finish 내부 단계로 분리하고, **새 명시 full-snapshot coordinator**에서만 typed stamp/evidence 단계를 사이에 두는 것이다. 기존 batch default 동작·signature·caps를 유지하거나, 명시 typed snapshot 인자를 추가하는 대안은 따로 두 리뷰해야 한다. 임의 callback/중간commit/finish 후 applying 상태검사 완화를 사용하지 않는다. 이 seam 없이 actual SH collector 완성이라고 할 수 없다.


### 3-A. 새 full input/result/replay domain

현 `_prepare_batch`의 scalar digest만 새 whole-snapshot 완료 의미로 재사용하지 않는다. 순서/전체 bound 검증은 재사용하되, 새 coordinator domain에는 **전체 typed input 그 자체**와 provider/dataset/type, exact membership/run identity, registry/reader schema version, policy epoch/header fingerprint, 전체 compact evidence fold, Geo context/token, retire mode, 전체 capture-closure fingerprint를 넣어 canonical prewalk/encoded 각각1MiB를 다시 검사한다. scalar digest의64문자만 넣고 실제 full input byte 검사를 생략하지 않는다. 이 domain의 추가 overhead 때문에 기존 scalar가 통과해도 full snapshot이 거부될 수 있으며 그 의미를 보존한다.

새 result domain은 full input digest + accepted current head 집합 + Geo/stamp 재관측 결과 + **정확 canonical capture count/hash** + exact operation/member를 결박한다. 이를 위해 capture 뒤 finish를 호출하고 result_digest에 그 결과를 포함시키는 설계다. 기존 scalar의 digest/DB byte 공식/finish signature를 느슨하게 만들지 않는다. 기존 batch의 expected_digest 비교를 새 coordinator-domain으로 바꾸는 private phase 경계는 코드 소유/별도 리뷰가 필요하다.

현재 attempt에는 result_digest만 있고 완전한 FeatureLoadResult/원래 run의 seal 복구 정보가 자동 저장되는 것은 아니다. 따라서 **completed를 새 full 성공으로 반환하지 않고 보수적으로 recovery-required 거부**한다. 현재 DB capture와 hash가 같다고 과거 insert/update 계수를 발명하지 않는다. 원 run과 영속 full-result/receipt의 정확 recovery 권위가 별도로 검증되기 전 자동 replay 성공은 지원하지 않는다.

### 3-B. 전체 DB capture-closure와 메모리 — 구현 차단 OPEN

현 `feature_repo.capture_provider_curation_input:2201–2224`는 source input만 hash하는 함수가 아니다. `current_provider_curation_input_set`(f89 head-schema4775–4838)는 **dataset 전체**의 current entity/head/link/core, `to_jsonb(place/other subtype)`, active override JSON·geometry를 row 표현에 포함하고 전체 digest 집계를 한다. 새 input에서 빠져 DB에 남은 entity나 거대 operator override는 요청 reader chunk와 full input byte cap 밖일 수 있다. reader chunk가 통과했다고 capture 메모리가 안전해지지 않는다.

첫 작은 subset의 최소 보수안은 다음의 **DML 전 추가 guard**다. (a) DB capture 대상 전체 source/entity/link/Feature 집합이 지원 input/manifest closure와 정확히 같아야 하며, retained old entity·새 source/link가 하나라도 추가되면 known unsupported로 EX다. MCST의 기존 no-retire 의미를 바꾸거나 옛 행을 지우지 않는다. (b) 실제 capture가 읽을 모든 subtype·override/geometry 및 가변 필드를 metadata-first로 전수 inventory한다. 처음에는 active override가 존재하면 전부 EX라는 제한도 가능하나 그것만으로 place/payload 전체 bound를 대신하지 않는다. (c) metadata/encoded expansion과 전체 집계 공간의 보수 상한을 실제로 증명하기 전 SH DML을 하지 않는다. 이 guard 함수/완결성은 아직 구현·검증되지 않았다.

기존 exact2N+M manifest는 input 밖 read-only Feature를 임의로 더하면 scalar/stamp full-set 등식과 충돌한다. 따라서 첫 subset은 input 밖 capture 관계를 거부하는 것이 가장 작다. 더 넓은 read-closure를 지원하려면 별도 명시 protocol/권한·lock 모델이 필요하며, digest 하나로 생략된 payload/closure를 승인하지 않는다.

capture 메타데이터·읽기 epoch/header/모든 subtype·override 행은 실제 kernel/정본 EX writer 잠금으로 보호되는지 증명해야 한다. 보호되지 않는 writer/phantom이 있으면 여기서 멈춘다. STABLE과 숫자 metadata가 있다고 giant `to_jsonb`/override json_agg를 먼저 평가해도 된다는 뜻이 아니다. 단일 row의 압축·detoast/geometry 경계도 기존 primitive와 같은 수준으로 증명하고, 필요하면 bounded row encoder로 **정확 old canonical hash를 바꾸지 않는** 경로를 설계해야 한다. 새 축약 hash/부분 seal/잠금 승격으로 우회하지 않는다.

같은 함수는 child seal(head11080–11084)과 root finalize(head5368–5373)에서도 다시 평가된다. load TX의 guard/lock 증명은 commit 뒤 이 단계로 영속 전파되지 않는다. child의 **자기 SERIALIZABLE snapshot 안에서** 같은 전체 DB closure·payload budget guard를 canonical 함수 평가 전에 다시 수행해야 한다. root finalize의 기존 protocolEX→oldglobal/SERIALIZABLE과 canonical hash 비교도 유지하며 그 평가 앞의 같은 budget 증명이 필요하다. 단순히 load guard의 true를 후속 단계에 복사하지 않는다.

후속 guard가 실패하면 이미 성공한 load commit을 rollback한 것처럼 쓰거나 자동 EX load를 재실행하지 않는다. 원래 child/root TX를 실패·미완으로 남기고 같은 run의 receipt 복구로 분리한다. **현재 whole capture/storage budget·fresh lock coverage·후속 seal guard는 미완이며 이 설계는 implementation-ready가 아니다.**

SERIALIZABLE transaction 안에서 처음 blocking gate SELECT를 실행하면 gate 대기 전에 snapshot을 잡을 수 있다. gate 획득 뒤 SELECT를 한 번 더 했다는 사실만으로 최신 snapshot을 증명하지 않는다. child에는 현재 첫 protocol gate가 없고, tracking은 lineage/root/cancellation을 선점한 뒤 seal/finalize로 간다. 관리자 취소의 SUCCESS 전이는 lineage 선점 없이 job/member를 잡고 finalize의 protocolEX로 들어가는 경로도 있다. 따라서 새 SH/control→root와 기존 root→EX의 역순을 전 경로에서 닫아야 한다. transaction 전 session gate 후보도 동일 connection·취소/응답 유실·pool 반환 전 해제·직접 SD 경로를 검증하기 전 채택하지 않는다. 기존 snapshot 의미나 caller 권한이 이미 완결됐다고 가정하지 않는다.

### 3-C. 단일 outer30s 계약과 아직 정하지 않은 준비/복구 시간

새 작은 snapshot coordinator의 **한 outer asyncio.timeout(30.0)**는 `begin → full stamp preflight → 전체 chunk fresh reader → 실제 SDK의 로컬 canonical 재구성/A1 비교 → source/candidate/winner DML → full stamp reobserve → canonical capture → kernel finish` 전체를 둘러싼다. 외부 provider HTTP/Geo 네트워크는 이 적용 TX 안에서 하지 않는다. 기존 `_refresh_batch` 내부30s만 두거나 각 chunk마다30s를 새로 시작해서 전체시간을 늘리지 않는다. 개별 DB/reader/SDK 호출 timeout은 `min(기존 더 짧은 timeout, outer remaining)`으로만 줄일 수 있다.

asyncio timeout은 동기 CPU 함수를 OS 수준으로 선점하지 않는다. 각 bounded chunk/항목 전후 monotonic remaining을 확인하고 실제 SDK/primitive의 단일 동기 구간 비용을 측정해야 한다. 이 계약을 이미 구현한 hard wall guarantee라고 부르지 않는다. statement_timeout30s/lock_timeout1s도 기존의 더 짧은 caller값을 보존하며, 현재 statement가 끝난 뒤 새 설정이 적용되는 경계는 별도로 시험한다.

**caller commit은 이 outer30s에 포함하지 않는다.** commit/rollback/connection cleanup에는 별도의 유한deadline을 정의·시험하고 원장에 따로 기록한다. commit cancellation/연결 끊김은 결과 불명확 상태일 수 있으므로 같은 원 run/attempt의 recovery-required이며 DML/EX를 자동 반복하지 않는다. 그 별도deadline의 정확 값과 recovery API는 아직 OPEN이다.

planning RR 전체 wall deadline과 fresh plan 최대 횟수/재계획 전체 누적deadline도 아직 정하지 않은 **설계 OPEN**이다. 임의의 횟수나 현재 각 SELECT3s를 전체 계획 보장으로 발표하지 않는다. 코드 작성 전에 값·bounded split 총호출수와 실제CPU/RAM·lease 상호작용을 정하고 두 리뷰·실측 수용으로 닫는다. 이 원칙 보강은 coordinator나 전체 운영 경계가 구현ready라는 판정이 아니다.

### 3-D. 최종 collector 활성화의 자동 복구 gate — precursor 거부와 구분

아래의 private staging은 동일 provider 입력의 재시도를 위한 작은 불변 artifact다. ADR-115 §6에서 제외한 Feature 전체 복사·공개 active release pointer와 구분한다. 해당 ADR의 한 transaction 공개·기존 capture hash·후속 child/root seal 의미는 유지하며, 새로운 protocol이나 활성화 범위를 이 문서로 변경하지 않는다.

앞의 completed→recovery-required 보수 거부는 precursor의 안전한 실패 정책일 뿐, 사용자가 요구한 **최종 collector 자동 복구 완료**가 아니다. 최종 활성화 전에는 다음 영속 권위와 자동 상태전이를 실제 검증해야 한다. 수동 개입만 기다리며 영구 stuck인 경로를 완료로 세지 않는다.

- apply TX의 마지막에서 `FeatureLoadResult` 정본14필드(`feature_repo.py:2141–2169`의6 load계수·capture count/hash2·Geo계수6)를 정확히 저장한다. source/candidate/winner/stamp DML, canonical capture count/hash, full input/result domain, 원 root/run/exact member·attempt·manifest·owner/fence를 **같은 TX의 finish와 원자 저장**한다. 현재의 result_digest64만으로 원래 계수를 복원할 수 있다고 하지 않는다. 기존 durable receipt가 이 전부를 보증하면 재사용하고, 없으면 작은 private control row/좁은SD를 설계한다.
- load14는 outer asset 결과 전체가 아니다. 실제 ETL은 주소 검증 finding·AddressFindingObservationReceipt·feature_ids/provider/dataset을 별도로 다루고, 수집 sync cursor와 stale finding close도 후속 단계다. load commit 뒤 사망을 저장14만으로 곧바로 child seal로 건너뛰면 미수행 단계가 누락된다. 이 단계들의 동일 clock·원 artifact·정확 결과/receipt와 순서를 영속화하거나 SDK/Geo 재수집 없이 결정적으로 재개하는 계약이 추가로 필요하다. 기존 member done의 noop도 fresh capture 증거가 아니므로 원 immutable receipt와 저장 context를 대조해야 한다. 이 배선은 OPEN이다.
- 한 frozen member의 유효 artifact는 단일 불변 binding으로 묶는다. context 조회는 member를 먼저 찾고 그 뒤 domain/input/version을 대조한다. 다른 digest로 조회해 applied 행이 없는 것을 미적용으로 오인하지 않는다. 실제 root↔child↔member 소속·취소/quarantine/terminal을 함께 확인하고, 단순 root/member FK 둘만으로 같은 실행이라 단정하지 않는다. 기존 begin의 최대32 participant dataset 정렬을 own dataset 하나로 축소하거나 control row부터 잡지 않는다. 이 정렬·handoff와 정본 tracking의 lock 순서를 함께 검증해야 한다.
- 최소 새 상태 후보는 attempt FK의 immutable context+versioned exact-result envelope다. payload key집합/계수 bigint범위·capture hash64·identity/UTF8 길이를 제한하고 row encoded bound를 정적으로 산출·실제검증한다(예: 결과 본체는4KiB 이하를 목표로 검증하되 아직 확정값 아님). preparing context와 completed result의 허용 전이를 SQL이 강제하고, result 저장+finish 중 어느 하나만 commit되는 상태는 금지한다. 일반 runtime raw DML/대형 임의 JSON 기록권한을 주지 않는다.
- 같은 run의 post-commit 응답 손실/worker 사망은 **saved result**를 읽어 source DML0/SDK refetch0으로 정확한 후속 child/root seal을 재개한다. 다른 run/member/artifact/domain은 재사용을 거부한다. 새 소유 worker는 caller UUID 자기주장 대신 검증할 정본 worker/run lease·generation의 handoff authority(현재 collector executor lease는 미구현)를 통해서만 원 attempt에 접근한다. kernel p_owner와 live backend/rowlock/lease 경계를 바꾸지 않고, stale owner는 새로운 executor fence를 넘어서 result overwrite/중복 finish/후속 seal을 할 수 없어야 한다. 확정할 lease resolver와의 실제 결박 API는 아직 설계 OPEN이다.
- commit 전 사망에도 동일 source를 재수집하지 않으려면 frozen input이 worker 프로세스 밖에서 재사용 가능해야 한다. 기존 정본 durable input이 없다면 현재1MiB 이내 canonical input을 private immutable staging으로 한 번 저장하고 digest/code·SDK/schema version을 결박하는 최소안이 필요하다. 일반 process-local DTO/BundleSpool 메모리를 durable authority라고 부르지 않는다. 저장한 typed input의 strict decode/re-hash와 동일 clock·Geo/retire 의미를 검증하며, 일부만 남은 staging은 apply하지 않는다. 새큰입력 지원과 달리 여기서는 기존1MiB cap을 그대로 적용한다.
- old apply backend가 살아 잠금을 쥔 경우 lease 만료만으로 lock을 지우거나 중복 쓰기하지 않는다. rowlock/transaction 종료를 기다리는 유한 retry와 canonical handoff를 사용한다. rollback 사망은 staged same artifact로 새 준비/apply, completed 사망은 saved-result only 복구를 구분한다. fresh capture가 원 saved hash와 달라 후속 seal이 stale라면 원 run의 정확 stale/terminal 상태를 자동 정산하고 정본 정책에 따른 새 operation으로만 전진한다. 예전 input DML을 임의 재실행하거나 count를 발명하지 않는다.
- retention은 한 attempt의 고정크기 context/result와 최대1MiB input, dataset별 active reservation 제한을 기본으로 한다. 전체/per-dataset retained byte·row quota, retry horizon, GC batch/wall cap과 tombstone/terminal 상태를 설계·측정한다. **값은 아직 OPEN**이며 저장소가 차면 새 claim 전에 backpressure한다. active/applying/미봉인 child/root 복구 행은 GC하지 않고, 완료·확인된 terminal만 horizon 뒤 bounded GC한다. 복구 가능한 원장을 먼저 지운 뒤 manual-only로 만드는 방식은 불가다.

최종 gate 시험은 commit 직전/직후 실제 SIGKILL, 결과 저장/finish 중간 실패의 원자 rollback, post-commit 응답 손실 뒤 saved14필드 동일·DML/SDK0, 중복 delivery·stale owner/handoff·다른run/artifact 거부, lease 만료 중 live backend, retention pressure/GC와 아직 봉인되지 않은 member 복구다. 새로운 control schema/SD는 사용자 기존 범위 안의 설계 대상이지만 제품 두 리뷰·실제 복구 검증 전에는 collector 활성화 완료로 세지 않는다.

## 4. SDK/A1·R1 권위는 chunk와 별개다

`providers/krheritage_native.py:321–392`의 A1은 diagnostic(collector_ready=False)이며, old normalizer revision과 old Geo가 명시적으로 일치해야 실제 public validator로 R1/R2를 rebuild한다. 오늘 revision을 옛 raw에 붙이거나 current head R2를 base R1이라고 바꿔 호출하지 않는다. field별 R1이 섞이면 첫 subset에서 EX, SQL NULL/JSON null도 구분한다.

MCST `mcst-name-v1`은 supplied name 증거이지 전체 old projection revision 선언이 아니다. MCST에 Heritage raw13/A1을 그대로 호출할 수 없다. 이름+주소가 자연키이고 바뀌면 새 identity가 되는 실제 public converter 의미를 보존한다. 기존 저장 provenance로 full R1 rebuild authority를 증명하지 못하면 known unsupported/EX다. 새 전용 pure adapter의 별도 검토 없이 base equality를 A1 누락의 임의 면제로 쓰지 않는다. 원천 정상 EX 수집에서 향후 새 evidence를 영속화하는 안도 별도 설계이며, 옛 raw backfill 추정은 금지다.

## 5. finish/capture/영속 seal은 같은 뜻이 아니다

- kernel finish1회는 전체 source·winner·stamp DML과 같은 RC TX다. 같은 TX 마지막에서 기존 `capture_provider_curation_input`을 **1회** 호출하여 전체 dataset의 count/hash를 얻고, 그 결과를 새 result domain에 결박한 뒤 finish/commit한다. chunk마다 capture/완료receipt를 만들지 않는다.
- 실제 child 영속 receipt는 `client.finish_dagster_feature_membership:987–1010`의 별도 SERIALIZABLE TX와 `feature_operation_repo:672–705`의 정본 seal이다. RC begin과 합치지 않는다. root 성공/모든 member 확정은 그 뒤의 별도 정본 단계다.
- MCST는 정확한 원래 memberships를 모두 load 성공 뒤 emit하고 그 exact member들의 후속 seal을 처리한다(`mcst_features.py:127–139,251–253,306–326`). 일부 sibling 실패는 전체 run 성공이 아니지만 이미 commit한 다른 DS를 되감는 기존 분산 원자성을 새로 주장하지 않는다.
- commit 불명확/finish 후 child seal 실패는 원래 run·attempt/current capture를 대조하는 복구다. completed attempt를 새 run의 성공으로 유용하거나 새 DML을 무조건 실행하지 않는다. immutable raw/full input은 재계획에 재사용하되 Geo 재해석이 필요해 결과가 바뀌면 새 artifact domain으로 명시하며 이전 attempt와 섞지 않는다.

## 6. EX fallback 분류

지원하지 않는 provider/정본 revision·raw shape·단일 entity budget·new entity/retire 의무·Geo/base 변화는 명시 known reason으로 whole input의 EX 준비 경로를 선택할 수 있다. 단, active 정책 아래 기존 bounded EX도2730/1MiB를 넘으면 fallback이 가능하다고 속이지 않고 unsupported-whole-snapshot으로 실패한다. 정책을 끄거나 legacy guard를 우회하지 않는다.

40001/stale/55P03/시간초과/연결 끊김/취소/예상하지 않은 reader reason/잘못된 SD schema/SQL 오류는 known unsupported가 아니다. 정확 own plan을 취소하고 원래 실패를 보존한다. fresh plan은 정해진 횟수·총wall 예산 안에서만 같은 불변 입력을 사용한다.

## 7. 큰 전체 dataset의 별도 streaming kernel 로드맵

Heritage4279/world9494는 작은 경로의 chunk reader를 넣어도 current full artifact/manifest 한도가 남는다. 기존 API cap을 올리거나 작은 attempt 여러 개를 전체 성공으로 합치는 후속이 아니다.

1. **새 명시 protocol/domain**의 필요성을 먼저 결정한다. 현재 작은1MiB/2730/8192 도메인은 그대로 둔다. large stream의 총 row/byte/임시디스크/lease/CPU/deadline 한도는 실제 fetch 전체 크기와 SSD/PG의 별도 설계·두 리뷰·실측 수용으로 정하며 아직 숫자를 발명하지 않는다.
2. upstream를 lock 없이 끝까지 읽고 불변 owned staging에 bounded chunk로 저장한다. 실제 SDK EOF/완전 페이지 소비와 cap 도달의 차이를 증명한다. chunk hash·순서·전체 rowcount/hash·원래 operation/membership·source/Geo version을 결박하고 최종 manifest를 원자 고정한다. 부분 fetch를 전체 seal로 승격하지 않는다. 새 uploader/file_sources 기능을 이 이름으로 끼우지 않는다.
3. 고정 폭 leaf dependency를 외부 정렬하여 **전체** participant→source/head→link→Feature lock 순서를 먼저 완성한다. 별도 durable staging/plan을 쓴다면 ACL/불변성/정리/위변조/목표집합·phantom 검증을 새 정본으로 검증한다. 요약 digest 하나를 기존 kernel의 생략된 leaf 권한 대신 넣지 않는다. 필요한 새 closure 표현은 새 protocol에서만 설계한다.
4. 한 RC apply TX에서 모든 잠금과 전수 검증 후 bounded SQL batch/cursor로 source/candidate/winner/Geo·분류/base/기존 retire를 처리한다. chunk commit0/최종 finish·capture1회. 행 수만 늘린 PL/pgSQL 전체 tuplestore·JSON배열을 만들지 않는다. MVCC/dead tuple/locktable·sort spill/temp disk/WAL·취소 비용을 PG/host cap 안에서 실측한다.
5. worker 실제 SIGKILL/connection death의 전량 rollback·소유 lease 회수/동일 불변 staging retry·completed recovery·staging 삭제를 증명한다. 일반 EX/SH 충돌 및 두 실제 독립 DS의 미커밋 DML 중첩을 시험한다.
6. 30s 안에 큰 전체 apply가 들어온다고 가정하지 않는다. bulk SQL/정렬·쿼리 비용 개선과 실제CPU/RSS/WAL/전체elapsed의 수용 기준을 먼저 제시한다. 새 deadline이 필요하다면 별도 설계·두 리뷰·실측 수용 대상이며 현재30s를 몰래 늘리는 해결책이 아니다. pool/worker/concurrency quota·기존 scheduler/Geo-heavy pool의 실제 운영 제약도 별도 확인한다.

## 8. 소유 경계/필수 반례/현재 OPEN

기존 reader(W)·stamp SD(T)·client/asset/tracking의 각 소유권은 바꾸지 않는다. 새 coordinator, chunk plan adapter, 전체 capture guard와 child/root 배선의 구현 소유자는 아직 정해지지 않았으므로 root가 경계를 고정하기 전 어느 기존 파일도 수정하지 않는다. 이 문서는 소유자에게 전달할 설계이며 coordinator 구현 승인으로 세지 않는다. 초기 root의 CODEGRAPH_NO_DOWNLOAD=1 status는 malformed SQLite schema로 실패했고 원 index는 보존했다. 이후 격리 Git archive와 고정 Linux Codegraph0.9.5에서 init/index/status 및6심볼의 callers/callees/impact를 실제 완료했다(1438파일/39136노드/96032엣지/파일오류0). SQLite 후속 관찰의 첫 권한 오류도 보존했고, 별도 읽기 복사·quick_check와 CLI 집계를 대조했다. 원 소스·도구 bytes와 소유 컨테이너 정리를 확인한 감사 SHA는 b01021578fbfedcdd4ba5f0c619cd70807e5bc66bdff5d056afcd148f7f71e94다. 동명이인·동적 native apply 누락·SQL SD 미해석·일부 테스트 helper 오연결 때문에 이 graph를 완결된 호출 그래프로 쓰지 않으며 실제 소스 경로를 함께 대조했다. PR #1398의 기존 batch 내부 단계 분리는 이 영향 분석과 두 리뷰·격리 PG20통과를 거쳤지만, 현재 coordinator/collector 배선·운영 SH는 아직 없다. 이후 option·signature·새 호출 경계를 바꿀 때도 해당 변경의 영향 분석을 별도로 확인한다.

- chunk1 뒤 policy/row/head/모든-role link/Geo stamp/retired 변경, 중간 entity 삭제·새 link 삽입, RR 일관성 vs RC 혼합 반례, kernel 뒤 fresh snapshot의 잠금 대기/40001.
- compressed/oversize entity 하나, 마지막 chunk budget/schema 오류, split deadline,2700여개 전체 byte gate 실패, metadata와 encoded1MiB의 다른 초과.
- giant effective override/retained input 밖 entity·거대 place payload·다른 subtype/새로운 child/root snapshot의 capture guard 실패, canonical oldhash 완전 일치와 실패시부분seal0.
- all raw가 아닌 compact state만 유지함을 실제RSS로 검증, sdk converter의 R1 provenance 부재시 EX, source 재수집 없이 bounded replan.
- stamp full-set 불일치/acceptedhead 불일치, 마지막 DML 실패·worker 실제 사망→전량rollback; child SERIALIZABLE seal 실패를 load rollback으로 오인하지 않음.
- actual final input1MiB gate 성공·정확 전용 adapter·full writer lock coverage·새 coordinator/reader 전체SQL 두 리뷰·actualPG/실제asset+tracking·실제worker 측정 전까지 구현ready/운영 SH PASS는 아니다.

근거: 현재 source `scoped_provider_refresh.py:62–106`, `scoped_provider_batch.py:35–107,203–262`, `scoped_feature_writes.py:159–199`, `_411_append_manifest.sql` 전체 byte 식, `_411_begin_attempt.sql` 전체 잠금/RC 조건, `_421_validate_scoped_stamps.sql` full-set/sameTX 검사, client/asset/tracking 위 위치. source/호스트 운영 변경0.
