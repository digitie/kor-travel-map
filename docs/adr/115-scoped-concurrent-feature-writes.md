# ADR-115 — 데이터셋·지역 쓰기 범위와 Feature 병합 충돌을 분리한다

- 상태: accepted — 부분 구현. alembic 411~433(운영 head 432). 스냅샷 SH 경로와 스칼라 정책
  경로는 구현됐지만 **운영 OFF·동결**이다(DC-2 결정 대기). 현재 잠금 순서·writer 분류·동결
  조건의 정본은 §11이다. 2026-10-27 개정: §5.2(3)·§8(3)의 writer 분류(433 DC-1), §11 신설.
- 날짜: 2026-10-23(제안), 2026-10-27(accepted·개정)
- 결정자: 사용자(설계·문서화·후속 구현 요청), Codex(설계)
- 근거 코드: `cdd2614007a86e8627949cd1176c61eb14c0ce3e`(main, PR #1350).
- 원격 main 재확인: `beec868128500aff8827646c351c6bf2f34ec709`(PR #1352·#1353)는 문서만
  변경하며 기능 코드는 동일하다. ADR-114의 Weather 반나절 요약 예외도 별도 Valkey 범위로 보존한다.
  ADR-114가 먼저 배정되어 본 설계를 ADR-115로 변경했다.
- 관계: ADR-074·091·097·098·099·108·109·111·112·113 및 ADR-114(Weather·Transport Valkey 이행).
- 구현 착수 순서: 진행 중인 Weather·Transport 동시성 개선을 마친 다음 Map 구현.

## 1. 컨텍스트와 현재 보장

이 설계의 쓰기·identity·후보·seal 프로토콜은 **PostgreSQL에 유지되는 Feature**가 범위다.
최신 main의 [ADR-114](114-weather-transport-state-in-memory-db.md)는 Weather·Transport의
현재/예보를 Valkey 세대 교체로 옮기는 별도 proposed 설계다. 그 경로의 키·pointer·메모리 예산은
본 ADR이 재설계하지 않으며 PG/Valkey 간 원자적 transaction을 약속하지 않는다. 이행 전에 남아
있는 PG Transport writer와 이후 퇴역 명령은 PG 불변식·protocol gate를 지켜야 하고, 이행 뒤에는
퇴역 dataset을 동시 쓰기 실측 대상으로 사용하지 않는다. Valkey-only Feature에 PG의 UUID claim·
base/override·seal을 자동 적용하거나 ADR-114의 식별자 계약을 이 문서로 바꾸지 않는다. 경계의
구현·퇴역 상태는 T-CWRITE-01에서 다시 고정한다.

단순히 전역 잠금 이름에 dataset ID를 붙이면 안전하지 않다. 서로 다른 dataset의 source가
같은 Feature에 연결되면 필드·상태·큐레이션·seal의 읽기/쓰기 집합이 겹친다. 지역도 좌표 이동,
경계 geometry, 수동 병합 때문에 독립성의 증거가 아니다.

| 현재 정본 | 확인한 동작 | 바꿀 때 보존할 것 |
|---|---|---|
| `infra/feature_repo.py::lock_feature_curation_write`, `load_bundle` | source→Feature→link 의미 쓰기에 `feature-curation-write` 전역 xact fence | source head와 link의 증거, 갱신과 retire의 일관성 |
| `alembic/versions/_406_*.sql` | 대량 `feature-write-all` 배타 / 단건 공유, 뒤에 `curation-catalog-write` | provider root·관리 명령·trigger 경로까지 같은 충돌 규약 |
| `infra/merge_repo.py::merge_features` | master/loser 잠금, link·curation 재결합, loser retire·override·history | 병합 중 loser 재활성화 금지, 모든 참조의 정확한 재결합 |
| `alembic/head-schema.sql::apply_provider_feature_field_patch` | source 증거 잠금 후 Feature `FOR UPDATE`, revision 비교, base `(feature_id, field_path)` upsert | override가 provider에 덮이지 않음, typed geometry, raw hash lineage |
| ADR-098 / `create_provider_feature_with_initial_state` | `(dataset, kind, natural_key)` claim이 UUID를 결정, source link는 N:M | 같은 source entity가 Feature identity라는 가정 금지 |
| `_406_finalize_provider_curation_root.sql` | SERIALIZABLE, immutable child seal을 다시 검증하고 root receipt·candidate generation 작성 | 불완전/낡은 입력의 성공 봉인 금지, replay 멱등 |
| ADR-113 / `client.py::load_feature_bundle_batches` | 먼저 stream을 spool하고 한 쓰기 transaction에서 적재+seal | snapshot 원자성, 받기 중 열린 DB transaction 없음 |
| ADR-108 | MOIS는 별도 재개형 chunk 계약 | 기존 chunk/receipt 의미를 snapshot 전체 계약과 섞지 않음 |

현재 base 표는 provider별 후보를 모두 저장하는 표가 아니다. 같은 필드에 두 dataset이 쓰면
최종 base가 실행 순서에 좌우될 수 있다. 전역 직렬화는 동시에 깨지는 것을 막지만 공급자 우선순위를
정의하지 않는다. 이 설계는 **결정적 winner 규약을 먼저 구현**한 뒤 잠금을 나눈다.

2026-10-12 dataset 99의 11,820 Feature별 advisory 잠금이 공용 PostgreSQL lock table을
고갈시킨 사건(ADR-111)이 있다. 수십만 Feature에 advisory 잠금을 다시 하나씩 만들지 않는다.
현재 운영 상태·속도는 이 문서에서 새로 측정하지 않았다. ADR의 과거 수치를 개선 후 실측으로 쓰지 않는다.

## 2. 불변식과 범위

1. 같은 identity는 하나의 정본 UUID에 귀속한다. 재시도·지역 이동으로 새 Feature를 만들지 않는다.
2. effective 값은 현재 유효한 provider 후보의 결정적 winner에 active override를 적용한 결과다.
   winner의 dataset/entity/값 원문·검증 head/raw hash와 typed 값·Geo 증거가 같은 transaction에서 바뀐다.
   정책은 활성화된 revision만 적용하며, 그 revision과 영향 Feature 재계산은 원자적으로 전환한다.
   이 규칙은 배타 fallback과 세분화 flag OFF에서도 같다. 잠금 mode는 winner 의미를 바꾸지 않는다.
3. source 하나의 소실은 다른 활성 source·수동 보정·publication/quality 상태를 지우지 않는다.
4. 일반 snapshot은 적재·정당한 absent retire·seal까지 한 transaction이다. 지역으로 분할한
   full snapshot의 중간 결과를 새로운 전체 snapshot인 것처럼 공개하지 않는다.
5. 독립 쓰기는 실제 DB DML 구간이 겹쳐 실행된다. fetch만 병행하고 전역 쓰기는 줄 세우는 상태를
   최종 완료로 보고하지 않는다. 동일 Feature를 쓰는 충돌은 계속 직렬화한다.
6. advisory 잠금 개수는 Feature 수에 비례하지 않는다. 행 잠금도 무료는 아니므로 WAL·RAM·SSI
   predicate lock·long transaction 비용을 별도 측정한다.
7. provider client·Feature 공개 DTO·OpenAPI 소비자 경계는 유지한다. 새 runtime SQL은 기존
   security-definer/권한 경계를 따른다. schema 변경 시 migration·runtime privileges를 함께 갱신한다.

비목표: 자동 fuzzy dedup 신규 도입, 공개 API의 전역 release pointer 신규 도입, 과거 receipt 재작성,
시간 정확도가 불필요한 schedule의 동시 실행 수 무제한 증대, JIT/PG 전역 설정 변경.

## 3. 목표 모델 — 제안 표이며 현재 존재하는 표가 아니다

| 제안 구조 | 정본 키 / 내용 | 수명·인덱스 |
|---|---|---|
| `ops.feature_write_dataset_scopes` | dataset 자연키를 DB ID로 해석한 anchor, protocol version | dataset당 1행, PK; 전체 snapshot과 지역 작업의 계층 gate |
| `ops.feature_write_region_scopes` | `(dataset_id, scope_version, region_key)`, epoch·owner·lease·완료 상태 | PK; owner/lease 청소용 partial index, 무한 attempt 행 누적 금지 |
| `ops.feature_write_attempts` 및 manifest | idempotency key, run/root/attempt, scope, frozen input hash, source/claim/Feature/curation 의존 ID와 예상 revision | 고유 idempotency; 상태·updated_at, manifest는 정렬 stream/COPY |
| provider field 후보 원장 | `(feature_id, field_path, dataset_id, source_entity_key)`별 값 원문 record/hash·validated-through head·typed 값·Geo 해석 증거·유효 상태 | 이 키 UNIQUE, `(feature_id, field_path)` winner 조회 인덱스 |
| provider field 정책 | `field_path + dataset 자연키`, 명시 rank·null 정책·policy revision | 유일 정책 키; pending/active revision을 구분하고 배타 gate 아래 영향 closure와 원자 활성화 |
| 병합 정본 redirect | loser UUID→master UUID, merge receipt/revision | loser UNIQUE, 순환 금지; 기존 identity claim을 보존한 채 canonical 해석 |

표명은 구현 PR에서 코드와 함께 확정한다. 후보 원장은 기존 `feature_base_field_values`를
대체하는 또 다른 effective 표가 아니다. 후보가 원천별 정본, 기존 base는 winner projection,
effective typed storage는 override 적용 projection이다. 셋을 **동일 transaction**에서 갱신한다.
원문은 immutable source record를 참조하고 복제하지 않는다. **정책 활성화 scope의 모든 writer**는
후보 원장 갱신→active policy winner→base/effective projection·Geo 증거라는 동일 경로만 쓴다.
배타 gate는 그 의미를 구현하지 못한 legacy writer에게 쓰기 권한을 주는 우회로가 아니다.
기존 `apply_provider_feature_field_patch`가 base를 직접 갱신하는 동작은 이 scope에서 금지한다.
동일 프로시저를 후보/winner 경로로 전환하거나, DB에서 해당 legacy 호출을 거부한다. runtime의
projection 직접 DML 권한뿐 아니라 SECURITY DEFINER 루틴의 EXECUTE와 내부 호출도 검사해
우회가 없도록 한다. 후보 갱신·완전성/Geo 증거를 보장하지 못하는 writer가 필요하면 그 scope의
첫 policy cutover 자체를 막는다. gate만 배선됐다는 이유로 활성화하지 않는다.
geometry는 PostGIS typed 값/기존
geometry 참조를 쓰며 JSON 문자열로 큰 payload를 이중 보관하지 않는다.

기존 base 한 행은 마지막 winner만 담으므로 그것만 복사해 backfill 완료로 보지 않는다. 대상 scope의
**모든 활성 source membership**을 열거하고 각 current head별로 provider typed 변환·field 정책을
적용해 후보를 재구성한다. omitted carry-forward에 필요한 과거 원문은 그 필드의 마지막 검증된
값을 찾는 데만 사용하며, 임의의 과거 record를 독립 활성 후보로 부활시키지 않는다. membership
열거 digest·head revision과 필드별 복원/정당한 무값 사유를 보관해 후보 완전성을 검증한다.
원문/변환 revision/Geo 증거가 없어 복원할 수 없으면 해당 scope의 policy cutover와 세분화 enable을
거부한다. 값/lineage를 추측하거나 활성 상위 provider 후보를 생략한 채 하위 base만 확정하지 않는다.

초기 backfill은 shadow 계산이며 기존 공개값/정책을 바꾸지 않는다. 모든 writer에 protocol gate를
배선한 뒤에만 첫 정책을 활성화한다(§8 순서). 이후 정책 변경도 새 revision을 pending으로 저장하고
영향 closure를 미리 산정한다. **배타 protocol gate를 잡고** head/membership/policy revision을 다시
검증한 다음 영향 Feature의 winner/base/effective/Geo stamp·seal 의존 revision·cache/outbox를
전부 재계산하고 active policy revision을 **한 transaction으로** 바꾼다. 실패하면 기존 active revision과
공개값을 함께 유지한다. 재계산을 비동기 작업으로 등록한 것만으로 정책을 먼저 활성화하지 않는다.
큰 closure는 NVMe artifact/임시 표로 준비하되 이 원자적 전환을 감당 못 하면 enable하지 않는다.
일반 writer와 root는 active revision만 읽고 manifest/receipt에 봉인한다. gate 밖에서 준비한 낡은
revision은 적용 전 거부하며, 정책 변경 뒤 기존 child seal은 stale로 판정한다.

## 4. winner·삭제·병합의 정확성

### 4.1 필드별 결정적 선택

- active override가 있으면 effective에는 override가 우선한다. base winner는 계속 갱신하며
  revoke 때 최신 winner를 적용한다. lifecycle override는 ADR-090의 독립 규칙을 유지한다.
- provider 후보는 유효한 **dataset 전체 entity membership**와 current source head까지의 검증이
  입증된 것만 선택한다. `value_source_record_key/hash`는 값을 실제 제공한 immutable 원문이고,
  `validated_through_head_key/revision`은 그 값을 여전히 인정한 현재 head다. 둘은 다를 수 있다.
  R1 `{name, phone}` 뒤 partial R2 `{name}`면 phone 값 원문은 R1에 남기고, provider의 omitted
  유지 계약에 따라 R2까지 carry-forward했음을 같은 transaction에서 기록한다. head가 R2라는
  이유만으로 phone을 탈락시키지 않는다. 명시 null/tombstone은 정책대로 후보를 제거한다.
- 순서는 **명시된 필드별 provider rank → 그 provider가 보장하는 관측 최신성 → 안정된
  dataset 자연키/source entity key**다. 서로 다른 provider 시계를 직접 비교해 우선순위를
  뒤집지 않는다. `clock_timestamp()`·DB-local dataset ID·commit 도착 순서는 tie-break가 아니다.
- provider 최신성 비교가 불가능하면 그 provider의 기존 monotonic head 규약을 따른다. 동일
  관측 시각의 상이 payload는 정책에 정의된 안정 hash 순서로 판정하고 충돌 finding을 남긴다.
- 복수 dataset이 같은 필드를 소유하는데 rank/null 정책이 없으면 잠금 세분화 대상에서 제외하고
  fail-closed한다. 기존 코드에서 우선순위를 발견하지 못했다는 이유로 숫자를 임의로 seed하지 않는다.
  초기 정책은 실제 provider별 필드 계약·기존 canonical source fixture와 대조해 검토한다.
- omitted는 후보 변경 없음, explicit null은 field registry와 해당 정책이 허용할 때만 지우기다.
  빈 주소/geo partial 응답 보호(ADR-109)는 winner 이전의 후보 검증에서도 유지한다.
- Geo로 만든 후보에는 입력 좌표/주소의 digest, 실제 관측 `data_token`, transform revision과
  결과를 제공한 원문/호출 증거를 둔다. 같은 raw/head도 Geo token이 다르면 다른 해석이다.
  주소·행정코드·Geo 유도 필드와 Geo stamp는 **하나의 일관 그룹**으로 같은 해석 후보에서
  선택하며 필드별로 A/B를 섞지 않는다. 그룹 정책/완전성이 없으면 cutover를 거부한다.
  stamp는 수집을 방금 실행한 B의 run token이 아니라 실제 effective 그룹 winner의 검증 증거로
  쓴다. A(T1)가 winner인 상태에서 B(T2)가 들어오면 주소/stamp는 A/T1로 유지되고 Geo의 현행
  T2 기준 stale로 남는다. 그룹의 일부 active override가 있으면 provider 후보를 사람 값의 Geo
  증거로 사용하지 않는다. effective 입력과 해석 증거가 정확히 일치하는 경우에만 stamp를 두며,
  그렇지 않으면 stamp를 제거/보류한다. revoke 후 최신 그룹 winner와 그 증거를 원자 적용한다.

### 4.2 retire와 원천 소실

**지역 coverage membership**와 **dataset 전체 entity 유효성**을 분리한다. 지역 A의 완전 snapshot에서
누락되면 A coverage만 absent로 표시할 수 있다. 그것은 A→B 이동인지 dataset 전체 소실인지
증명하지 못하므로 전역 entity membership·필드 후보·Feature를 그 이유만으로 비활성화하지 않는다.
전체 dataset의 완전 snapshot, provider의 global tombstone, 또는 해당 identity에 대한 authoritative
entity lookup의 명시적 소실 답변이 있을 때만 전역 소실을 확정한다. 조회 timeout/불명확한 404는
소실 증거로 채택하지 않는다. 이동은 source identity의 monotonic 관측으로 B membership를 확정하고
A와 원자 재결합한다. A만 먼저 완료되거나 B가 실패하면 `pending-not-retire`로 남겨 마지막 검증된
후보/effective를 유지하고 bounded reconciliation을 예약한다. 이 프로토콜을 provider가 지원하지
못하면 지역 absent retire를 enable하지 않고 dataset 전체 authoritative 경로를 쓴다.

full/authoritative 및 정확한 coverage 증거가 있는 scope에서만 그 **coverage** membership을 비활성화한다.
증분·실패·부분 fetch·타임아웃·개수 하한 미달은 absent를 의미하지 않는다. 마지막 활성 source가
사라져도 user lifecycle override·manual origin을 검토한 typed state procedure만 retire할 수 있다.
다른 source가 남으면 **전역 소실이 입증된 source의** 후보만 제거하고 winner를 재계산하며 Feature 자체를 무조건 retire하지 않는다.
재관측은 같은 identity를 복구하고 명시적인 사용자 비활성화를 되돌리지 않는다.

### 4.3 명시 병합

새 수집에서 다른 dataset의 같은 이름/좌표를 자동으로 동일 Feature라고 추정하지 않는다.
기존 승인된 dedup 경로와 ADR-097 paired reconciliation을 유지한다. 명시 merge는 master/loser,
양쪽의 모든 identity claim/source membership/base 후보/override/curation·소비자 재결합 이벤트를
manifest에 포함한다. canonical redirect를 따라 최종 master를 다시 확인하고 source 증거와
revision을 재검증한 뒤 link 이동·후보 winner 재계산·loser retire·history를 원자적으로 적용한다.
서로 다른 active override의 충돌은 자동 우선순위로 숨기지 않고 기존 검토 정책에 따라 거부한다.
merge 후 늦게 도착한 loser writer는 redirect를 다시 해석해 전체 재계획하며 loser를 부활시키지 않는다.
redirect 순환·A→B/B→A·purge된 정본·kind 불일치는 명시 오류다. 물리 purge는 별도 관리 경로로 남긴다.

## 5. 쓰기 프로토콜과 잠금 순서

### 5.1 범위 계획과 지역 계층

지역은 `scope_version`을 가진 **수집 coverage 코드**다. 문자열 주소나 재해석되는 행정명으로
identity를 만들지 않는다. 초기 opt-in은 provider가 완전성을 보장하는 고정 지역 단위뿐이다.
좌표가 없는 source는 `unknown` scope에 두며 전체 dataset을 잠그는 의미로 사용하지 않는다.

- 지역 쓰기: dataset anchor `FOR SHARE` → 해당 region anchor `FOR UPDATE`.
- dataset 전체 snapshot/분할 불가능 작업: dataset anchor `FOR UPDATE` → 필요한 region anchors.
- 여러 dataset은 DB ID의 정렬 순서로 anchor를 모두 먼저 잡는다. 지역은 `(dataset_id,
  scope_version, region_key)` 순서다. 공유→배타 승격은 금지하고 처음부터 필요한 모드를 계획한다.
- 동일 dataset의 서로 다른 완전 지역은 동시 실행할 수 있고, 전체 snapshot은 그 지역 작업 모두와
  충돌한다. 전체 snapshot 두 dataset은 서로 다른 Feature라면 동시에 쓴다.
- 이동은 옛 지역 ∪ 새 지역의 scope를 예약한다. route/area의 경계 교차는 coverage manifest의
  모든 영향 지역을 포함한다. SQL bbox 결과만으로 source가 사라졌다고 판정하지 않는다.
  비지역 provider의 전국 snapshot을 작업자 편의로 잘라 지역 완전성을 발명하지 않는다.

### 5.2 계획, 잠금, 재검증, 적용

1. **받기**: 기존 ADR-113 spool/ADR-108 원천 artifact를 재사용한다. 네트워크·지오코딩은 DB 쓰기
   transaction 밖이다. spool은 NVMe 경로·디스크 예산을 지정하고 tmpfs/RAM 전체 적재를 피한다.
2. **계획**: read-only 조회로 mutation closure를 manifest에 작성한다. source head뿐 아니라
   retire 대상의 기존 link, merge의 canonical closure, rule/candidate/collection, seal 의존을 포함한다.
   전체 UUID 목록을 Python list로 올리지 않고 임시 표/정렬 커서·COPY를 이용한다.
3. **진입**: 데이터 writer는 쓰기 전에 protocol gate(P)를 잡는다. 새 규약 writer(scoped
   kernel)는 공유, 잠금 세분화가 미지원인 대량 경로·restore·DDL·정책 cutover는 배타다.
   **2026-10-27 개정(433 DC-1):** 단건·관리 writer는 regime 진입으로 들어간다. 정책 활성화
   전(epoch=0)에는 P를 잡지 않고 기존 행 잠금 순서(source→link→Feature)로만 직렬화하며,
   활성화 뒤(epoch>0)에는 배타 P다 — strict guard가 manifest 없는 공유를 거부하므로 공유가
   아니다. 첫 활성화가 진행 중인 epoch=0 writer를 drain하고, 진입을 건너뛴 DML은 23514로
   닫힌다(§11.3). provider tracking 장부 쓰기는 데이터 writer가 아니라 P 없이 L만 잡는다
   (§11.2). 단, policy 활성 scope의 의미 writer는 공유/배타 모두
   §3의 후보/winner 프로토콜을 구현해야 한다. 구형 직접 base writer는 gate mode와 무관하게
   DB에서 거부한다. 유지보수 restore도 활성 정책과 후보/projection의 일치 검증을 통과하기
   전에는 일반 쓰기를 재개하지 않는다. gate는 정상 쓰기끼리 직렬화하지 않는 잠금 경계다.
4. **정렬 잠금**: 아래 전체 순서를 모든 Python 호출·SQL procedure·trigger에 동일하게 적용한다.
   늦게 발견한 의존을 순서 밖에서 추가로 잡지 않고 rollback 후 manifest를 새로 만든다.
5. **재검증**: head/current record·claim/redirect·membership revision·정책 revision·rule revision·
   scope epoch를 잠금 뒤 다시 읽는다. 집합 추가/이동/삭제도 검사하며 다르면 40001로 전부 재계획한다.
   SERIALIZABLE root의 snapshot이 잠금 대기 전 것이면 SSI 실패를 정상 재시도한다.
6. **적용**: 원천→후보→winner/base→effective/subtype→상태·curation→receipt/seal을 하나의
   transaction에서 쓴다. 기존 typed procedure/ACL 경계를 보존하고 중간 commit하지 않는다.
7. **완결**: publish와 owner epoch 조건부 완료 표시를 같은 commit에 넣는다. 이후 root 완결은
   immutable child receipt와 현재 의존을 검증한다. 재계획 실패를 성공으로 표시하지 않는다.

전체 잠금 순서(신규 규약, ADR-111 순서를 그대로 확장한 것이라고 주장하지 않는다):

`protocol gate → dataset anchors → region/attempt anchors → identity claims(자연키 정렬)
→ source entity/head(정렬) → source link(정렬) → Feature UUID(정렬, FOR UPDATE)
→ subtype/base/override → catalog source/theme/rule → collection/item/candidate → job/receipt`

source/Feature 행은 `ORDER BY ... FOR UPDATE`의 실행 결과뿐 아니라 실제 경합 테스트로 순서를
증명한다. claim 부재는 PK/UNIQUE INSERT 경쟁으로 처리하고, 삽입도 자연키 정렬이다. 신규 Feature는
claim 확보 뒤 생성한다. 공유된 FK 부모/관련 Feature(parent/sibling)까지 closure에 넣는다.
대량 경로는 Feature별 advisory 잠금을 쓰지 않는다. PostgreSQL 행 잠금의 수는 대상 수에 비례해도
Feature별 advisory와 동일한 shared lock table 항목을 만들지 않는다. SSI의 predicate lock 승격은
별도 비용으로 측정한다. 고정 hash stripe를 Feature 대신 써 전국 작업 모두가 같은 stripe를 잡게
하는 방식은 진짜 동시 쓰기의 해법으로 채택하지 않는다.

### 5.3 catalog와 root도 빠지지 않는다

`feature-curation-write`만 바꾸고 `_406_*.sql`/`curation-catalog-write`를 남기면 대량 완결은 계속
직렬화된다. source/theme/rule별 anchor 행을 정렬해 catalog 범위를 잠그고, root가 영향을 주는
모든 rule의 변경을 manifest에 포함한다. rule 신설/삭제 phantom은 해당 source/theme anchor와
catalog revision으로 막는다. trigger가 다른 theme을 발견하면 같은 closure 규약을 따르거나
**전체 rollback 후** 배타 protocol gate로 다시 진입한다(공유→배타 승격 금지). 그 경로도 후보와
active policy winner 의미를 유지해야 한다. 의미가 미지원인 경로는 DB 거부/해당 scope의 policy
cutover 차단 대상이다. 잠금 세분화 지원 제외 경로가 남은 범위를 완료로 표현하지 않는다.
collection revision 하나를 공유하는 명령끼리는 계속 충돌하는 것이 맞다.

`tests/lint/test_feature_write_lock_order.py`가 SQL 호출과 trigger까지 펼치던 보호를 새 순서로
갱신한다. 무관한 두 bulk root의 실제 DML 중첩 및 같은 root의 replay 결과가 최종 완료 조건이다.

## 6. 원자적 공개·seal·Geo 토큰

초기 **PG 동시 쓰기 구현**은 staging 전체 복사나 새 active release pointer를 추가하지 않는다. 일반 dataset/정당한
지역 snapshot은 기존 한 transaction을 유지하므로 API reader는 commit 전/후 image만 본다.
작은 불변 provider 입력을 보존하는 재시도 artifact는 Feature 공개 snapshot 복사나 active release pointer가 아니다. 세부 검토는 [전체 snapshot·복구 설계](../reports/2026-10-25-full-snapshot-coordination-design.md)에 정리하며, 기존 transaction 공개·capture hash·후속 seal 의미를 바꾸지 않는다. 새 저장·복구 경로는 아직 구현되지 않았다. [작은 Transport pair 설계](../reports/2026-10-25-transport-small-native-pair-design.md)는 최초 검증 후보와 여섯 구현 단위를 정의한다. 현재 후보 수·단일 raw 크기는 전체 적격성 증명이 아니며, unchanged raw의 실제 적용 중첩·복구도 아직 검증하지 않았다.

현재 READ COMMITTED에서 같은 transaction을 쓰더라도 SELECT마다 snapshot이 달라진다.
따라서 관련 조회를 단일 SQL로 합치거나, **첫 SELECT 이전**에 read-only REPEATABLE READ
transaction을 시작해 응답 전체(참조 해석·본문·추가 조회)를 감싼다. 이미 autobegin된 READ COMMITTED
session의 중간에서 isolation만 올리는 방법은 금지한다. 이 규약의 구현·검증 전에는 다중 SELECT
응답이 단일 image를 보장한다고 주장하지 않는다. 별도 HTTP 페이지는 서로 다른 commit을 볼 수 있다.

2026-10-24 실제 PostgreSQL 구현 확인: 기존 `FOR SHARE` guard를 가진 reconciliation
snapshot 조회는 READ ONLY에서 25006으로 실패하므로 이 한 경로만 기존 권한 범위의
READ WRITE REPEATABLE READ를 사용한다. guard를 제거하거나 DML 권한을 추가하지 않는다.
metadata와 row lock 사이의 정상 경쟁 갱신은 40001이 될 수 있으므로 이 GET만 명시적인
재시도 가능한 503과 Retry-After를 반환한다. 다음 요청은 새 transaction에서 principal/scope
검사부터 다시 실행한다. 나머지 순수 reader는 READ ONLY를 유지한다. 이 예외는 별도 요청
페이지의 동일 snapshot이나 자동 내부 재시도를 보장하지 않는다.

현재 `packages/kor-travel-map-api/src/kortravelmap/api/routers/features.py`에서 확인한 검사 대상은
다음과 같다. 단일 SELECT로 끝나는 경로도 구현 단계에 확인해 분류한다.

| 경로/함수 | 서로 다른 SELECT가 섞일 수 있는 경계 |
|---|---|
| `get_feature` | `resolve_feature_ref_or_error` → `_public_feature_row_or_404` 및 상세 보조 조회 |
| `get_features_batch` | `resolve_feature_identities_bulk` → `get_service_feature_batch_items` |
| `list_features_nearby_by_target` | `get_poi_cache_target_by_key` → `features_nearby_poi_cache_target` |
| `get_feature_price_snapshot` | identity/공개성 조회 → 가격 current/history 조회 |

전체 inventory는 T-CWRITE-01에서 admin/curation·다른 router까지 확장하고, 실제 함수명을 코드와
대조한다. T-CWRITE-04에서 각 경로의 SELECT 사이 writer commit을 주입해 old/old 또는 new/new만
허용하고 old identity/새 본문·이전 total/새 items·주소/다른 Geo stamp 혼합을 거부한다.

지역 snapshot 여러 개를 하나의 전국 release로 공개해야 하는 provider는 지역별 commit으로
바꾸지 않는다. 이번 방식에서 제외해 전체 dataset anchor와 한 transaction을 유지한다. 향후
전체 generation staging+pointer 방식은 reader/retire/seal 모두를 바꾸는 별도 ADR이 필요하다.
MOIS의 기존 chunk 공개 의미는 ADR-108을 유지한다.

- child seal은 실제 source membership, winner/effective 의존 revision, policy revision, scope와
  입력 manifest digest를 봉인한다. 타 dataset의 병합·override·rule 변경이 seal을 낡게 하면 root는
  기존처럼 `stale_input`으로 판정하고 새 원천 fetch 없이 가능한 재계산을 예약한다.
- 기존 seal 입력 정의를 바꾸면 `input_set_formula` 세대를 올리고 구 receipt를 재해석하지 않는다.
  전체 payload `jsonb_agg` 대신 ADR-099의 정렬된 고정폭 member digest fold를 유지한다.
- `geo_data_token`/`DatasetRef`는 Geo의 활성 데이터 지문이지 Map 쓰기 세대가 아니다. run의 Geo
  토큰 관측이 섞이면 ADR-109/113대로 stale 재해석·stamp를 보류한다. 후보별 해석 증거와
  effective 그룹 winner의 stamp는 §4.1 규약으로 일치시킨다. 새 epoch를 Geo 지문처럼 쓰지 않는다.
- 이 설계가 대상으로 하는 **PG Feature**에는 전환할 공개용 active release pointer가 현재 없다.
  ADR-114의 제안 Valkey 세대 pointer는 별도다. 기존 Geo release 계획과
  theme candidate generation을 Map 전체 release로 부르지 않는다. cache target generation/outbox,
  ETag/row_revision·공개 `public_ready`/공간 인덱스가 commit과 함께 일치해야 한다.

## 7. worker 사망·취소·재시도

lease는 liveness 신호이며 쓰기 권한의 증거가 아니다. scope anchor의 monotonic epoch/owner가
fence다. claim은 짧은 transaction으로 epoch를 발급한다. 적용 transaction은 그 anchor를 잠근 뒤
현재 epoch/owner·취소 상태를 확인하고 끝까지 보유한다. 새 owner는 옛 적용 transaction이 끝나기
전 epoch를 교체할 수 없으며, 오래된 worker는 새 epoch를 본 뒤 더 쓰지 못한다.

- 프로세스/연결 사망: PG transaction rollback과 xact 잠금 해제가 먼저다. 살아 있는 orphan PG
  query는 기존 common run ownership/DB application_name 근거로 **해당 attempt만** 취소한다.
  `client_connection_check_interval`, statement/lock deadline을 유지하고 unrelated backend를 죽이지 않는다.
- 취소: 해당 run/root/attempt의 원장에 먼저 영속 반영하며 publish 조건을 거부한다. 취소와 commit
  경계의 승패는 anchor/attempt 행 잠금으로 판정하고 이미 완료된 commit을 실패인 척 지우지 않는다.
- 55P03·40P01·40001은 rollback 후 bounded exponential backoff+jitter와 전체 deadline으로
  재계획한다. 초기 예산은 기존 common 정책보다 늘리지 않고 실측 후 결정한다. 무한 retry 금지.
- commit 응답 유실은 같은 idempotency key의 완료 receipt를 재조회한다. payload/hash가 같으면
  replay, 다르면 충돌이다. 완료된 결과를 중복 공개하거나 새 epoch로 두 번 계산하지 않는다.
- spool/artifact가 온전하면 저장 재시도에서 외부 fetch를 반복하지 않는다. checksum/버전/완전성
  검증에 실패한 artifact만 다시 받는다. 미완 attempt/만료 lease janitor도 epoch CAS를 쓴다.
- 잠금 대기 중 pool connection을 무한 점유하지 않는다. 경합 원인·scope·attempt·elapsed를 기록하고
  관리자에는 재시도 가능한 상태를 표시한다. ADR-112 sweep의 tick 예산·독립 알림·root 복구를 유지한다.

## 8. 단계 전환과 되돌림

1. 측정/호출·trigger 전수 목록, 재현 fixture, field winner 정책을 먼저 만든다.
2. 후보 원장·정책·redirect·scope 원장을 additive migration으로 넣고 **기존 전역 잠금 아래에서**
   backfill·winner 비교·회복 테스트를 끝낸다. shadow 계산은 공개값을 바꾸지 않는다.
3. **정책 활성화 전** 모든 writer에 protocol gate(단건·관리 writer는 regime 진입)와
   후보/winner 의미 경로를 배포한다. **2026-10-27 개정(433 DC-1):** 단건·관리 writer는
   epoch=0 동안 P를 잡지 않는다. 첫 활성화가 그들을 drain한 뒤에는 같은 binary가 스스로
   배타 P를 잡으므로, 활성화를 위해 binary를 바꿔 끼우지 않는다(§11.3).
   전역 잠금 경로도 같은 의미를 쓰며 잠금만 배타다. 미변환 legacy 직접 base 호출은 DB에서
   거부한다. 필요한 writer가 의미 프로토콜을 지원하지 않거나 구 binary가 gate를 우회하면
   scope의 policy cutover와 세분화 enable을 모두 막는다. drain 후 API/CS/CLI·DB head를 확인한다.
4. 새 프로토콜은 feature flag 기본 OFF로 배포한다. §3의 완전성 검증·배타 gate 아래 원자적
   policy cutover를 통과시킨 뒤 독립 dataset 2개를 opt-in한다. 두 세션으로
   실제 쓰기 중첩을 확인한다. 공통 Feature/수동 명령은 이어서 충돌 시험한다.
5. 지역 opt-in, root/catalog·notice/merge/admin/cancel 경로 순으로 넓힌다. 잠금 세분화 미지원
   경로는 **동일 후보/active winner 의미를 구현한 경우에만** 배타 gate로 실행한다. 의미 미지원은
   쓰기 거부 또는 scope cutover 차단이다. 최종 수용에서 배타/거부/미전환 범위를 전수 공개한다.
6. live E2E/API/UI·복구·장애 주입·실측을 두 독립 적대 리뷰와 함께 통과한 구현 PR만 머지·배포한다.
   문서 PR의 CI 생략 지시는 구현 PR 검증 생략 권한이 아니다.

되돌림은 먼저 새 claim을 멈추고 진행 중 attempt를 drain/취소 후 commit 여부를 판정한다. 세분화
flag를 끄면 **후보 갱신·active policy winner→projection·Geo stamp 의미는 유지한 채**, 새 코드의
배타 protocol gate+전역 잠금만 사용한다. policy 비활성화나 legacy 직접 base 갱신으로 돌아가지
않는다. 후보 원장·active revision·receipt를 보존하고, 기존 직접 base 루틴 거부도 유지한다.
이 의미 경로가 고장 나면 쓰기를 정지하고 forward repair하며 legacy writer를 허용하지 않는다.
schema downgrade나 gate를 모르는 옛 binary로 롤백하지 않는다. 이상한 winner는 source 증거와
policy revision을 이용해 forward 재계산한다. 중단 전/후 run·epoch·image revision·schema head와
롤백 결과를 기록한다. Dagster daemon·다른 서비스 상태는 운영 지시 범위 안에서만 바꾼다.

## 9. 실측·수용과 위험

동일 NVMe/PG/코드세대·동일 artifact·동일 행/geometry 분포로 전후를 최소 3회 측정한다.
첫 실행과 warm cache를 구분하고 다른 collector 부하를 기록한다. 운영에서 병목을 만들려고
대량 전체 rebuild를 강제로 겹치지 않고 격리 복원본의 2/3 동시 writer로 먼저 검증한다.

| 축 | 반드시 보관하는 증거 |
|---|---|
| 진짜 동시 쓰기 | 각 attempt DB DML 시작/commit 구간, `pg_stat_activity` wait/transaction, 독립 2세션 overlap |
| 처리량·지연 | 전체 elapsed/rows·s, fetch/plan/lock wait/DML/seal/root 분해, API/UI p50/p95 |
| CPU·RAM | cgroup CPU core-seconds와 wall 기준, RSS/peak·memory.current/peak, PG 포함 총량, swap/OOM/restart |
| DB 비용 | lock 종류/최대 수, connection 수, deadlock/serialization retry, WAL bytes, temp bytes, buffers·계획 |
| 정확성 | 순서 반전/랜덤 지연 후 동일 canonical UUID·winner·raw hash·override·state·seal·public 조회 결과 |
| 복구 | fetch/쓰기/seal/commit 응답 경계 kill·cancel·연결단절, replay/epoch 충돌·janitor 결과 |

정확성/원자성 위반 0, 무한 정지 0, Feature 수 증가에 따른 advisory 잠금 선형 증가 0을 필수로
삼는다. 비교 가능한 동일 입력에서 독립 2작업 총 완료 시간이 직렬 기준보다 줄어야 한다.
CPU core-seconds/row와 peak RAM, API p95는 기준선 대비 10% 초과 악화하면 원인·대응을 문서화하고
확대하지 않는다(측정 오차도 함께 보고). wall CPU%만 낮아졌다고 개선이라 하지 않는다. 초기 병행은
2개로 제한하고 DB pool/queue/artifact bytes·개수 상한을 둔다. 이후 값은 실측으로 정한다.

주요 비용은 후보 원장 증가, manifest 정렬/temp I/O, 겹치는 Feature의 본질적 직렬화, SSI 충돌,
복잡한 root/trigger closure다. 전역 gate 제거만으로 이 비용이 사라진다고 약속하지 않는다.
세부 구현 순서와 반증 시나리오의 정본은 `docs/tasks-acceptance.md`의 T-CWRITE-01~09다.

## 10. 결과와 후속

긍정: 다른 dataset/완전 지역의 독립 DML을 병행하면서 공유 Feature와 seal의 정확성을 명시한다.
부정: 후보·정책·closure·fencing을 전수 구현해야 하므로 잠금 이름만 바꾸는 작은 패치가 아니다.
지금은 proposed 설계다. 두 적대 리뷰 후 doc-only PR을 CI 검토 없이 머지하며, 구현·운영 수용은
아래 task가 담당한다. ADR-111의 현행 잠금 규칙을 아직 superseded로 표시하지 않는다.

2026-10-27: 부분 구현이 운영 중이라 accepted로 바꿨다(§11). ADR-111은 superseded가 아니라
P·L을 앞에 둔 순서로 개정했다.

## 11. 구현 상태(2026-10-27, alembic 433 기준)

Codex PR(#1358~#1419) 리뷰를 정리한 PR이 이 절을 고정한다. 앞 절의 설계와 다르면 이 절이
현행 정본이다.

### 11.1 전역 잠금 순서

`P`(protocol gate, 411) → `L`(pipeline lineage, 424) → `kortravelmap:curation-import` →
`feature-curation-write` → `feature-write-all` → `feature-write:<id>` → `curation-catalog-write`

- P는 Feature 도메인 행 잠금(source→link→Feature)보다 먼저다. 같은 transaction에서 공유 P를
  배타로 올리지 않는다(23514 "upgrade requires replan").
- L 뒤에 P를 새로 잡지 않는다. 확정 진입은 P EX를 먼저, L을 나중에 잡는다.
- `tests/lint/test_feature_write_lock_order.py`가 head의 모든 루틴(중첩 CALL·trigger 포함)과
  Python helper 호출을 epoch=0·epoch>0 두 세계에서 이 순서로 센다. 일부러 어긴 fixture가
  빨개지는지도 같은 파일이 본다.

### 11.2 writer 분류

| writer | 잡는 것 |
|---|---|
| legacy 적재(fence)·curation import·root 완결·병합·purge·provider field patch·DDL·정책 cutover | P EX(무조건) |
| scoped kernel(411 begin) | P SH + 적용 중 manifest |
| 단건·관리 writer — SQL 10개(상태/lifecycle 4, 필드 override 2, 생성·승인 4)와 Python 관리 생성·patch·주소 override | regime 진입: epoch=0이면 P 없음, epoch>0이면 P EX |
| provider 증거를 먼저 잡는 관리 writer — M05 3개·재활성화 | 증거 진입: epoch=0이면 P SH, epoch>0이면 P EX(적재가 bundle을 차례로 쓰며 Feature를 쥔 채 다음 head를 갱신하므로 P 없이는 순환) |
| 전화 override(`set_feature_phones`) | P EX(fence) — enrichment가 같은 transaction에서 source record/link를 쓴다 |
| tracking 확정: seal·root 완결·권위 finish·SUCCESS 완결 취소 전이 | P EX → L |
| tracking 장부: ensure·attempt event·fill-starts·실패/취소 terminal·비권위 finish·취소 원장 | L만 |

- 장부 진입을 P를 쥔 transaction에서 부르면 23514(`ck_provider_tracking_prefix`)다. 확정 진입
  (P EX→L) 뒤의 재진입만 통과한다. 430 write-prefix guard도 같은 분류다. `done` 전이 중
  root(`provider_feature_load_run`)와 권위 child만 P EX를 요구하고, 나머지 provider job·취소
  원장 쓰기는 L(그리고 P를 쥐었다면 EX)만 요구한다.
- 권위 finish의 P EX 대기는 적재와 같은 무장 상한(`feature_load_curation_lock_wait_seconds`)을
  쓴다. 엔진 `lock_timeout`이 0이어도 gate가 1초로 줄이지 않는다(433 WI-2).

### 11.3 regime 진입과 cutover 안전성

- `ops.lock_single_feature_writer_protocol()`은 epoch 표를 평범하게 읽는다(ACCESS SHARE, 행
  잠금 없음). epoch>0이면 P EX를 잡는다.
- 첫 활성화는 P EX 바로 뒤 epoch 표를 먼저 ACCESS EXCLUSIVE로 잠그고, 그다음 보호 표 25개를
  잠근다. 진입만 지난 epoch=0 writer는 다른 표가 아직 비어 있으므로 끝까지 쓰고 commit하며,
  활성화는 그때까지 기다린다(drain). epoch 표를 목록 순서대로 잠그면 이 writer의 다음 DML과
  순환한다(433 적대 리뷰). cutover 중에 들어온 진입은 epoch
  표에서 기다리고, PL/pgSQL은 문장의 잠금을 snapshot보다 먼저 얻으므로(READ COMMITTED) 새
  epoch를 읽고 P EX를 잡는다. 오래된 snapshot의 RR/SERIALIZABLE writer는 412 barrier·430
  strict guard에 23514로 닫힌다.
- M05는 두 Feature를 `FOR UPDATE`하기 전에 provider 쪽 primary source 증거(entity/record/
  head, 그다음 link)를 적재와 같은 순서로 `FOR SHARE`한다. 414가 P로 막았던 역순을 P 없이
  없앤다. dataset 행은 잠그지 않는다 — M05가 기다리지 않는 행은 순환을 만들지 못한다.
- epoch=0에서 같은 Feature를 쥔 대량 writer가 있으면 단건 writer는 그 행에서 그 transaction이
  끝날 때까지 기다린다(종전처럼 P에서 1~5초 뒤 503이 아니다). 다른 Feature는 기다리지 않는다.
- 실제 PG 시험: `tests/integration/test_single_writer_regime_entry.py`.

### 11.4 SH 스냅샷·스칼라 정책 경로는 운영 OFF·동결이다(DC-2 1단계)

- 2026-10-27 운영 읽기 전용 확인: 스냅샷 flag(AIRPORT·REST·KRHERITAGE_EXCLUSIVE) 미설정(기본
  OFF), `provider_field_shadow_scopes` 미설정, epoch 0, active policy 0행, write attempt 0행.
- **운영에서 `feature.activate_provider_field_policy`를 부르지 않는다.** 되돌릴 수 없다 —
  deactivate 경로가 없고, strict guard trigger 33개와 projection guard가 모든 writer에 영구히
  붙으며, 설치가 보호 표 ACCESS EXCLUSIVE를 상한 없이 기다린다.
- flag를 켜거나 정책을 활성화하기 전에 해소할 조건(리뷰 지적 ID): Rest·Airport runner의
  부적격 입력 fallback·scope 축소·비활성 override/retired 거부·lease와 plan reset·GC 실패 전파
  (D1·D2·C2-04·C1-01~05·D11·D12·D15), 잠금·예산(SH의 1초 gate 대기·30초 예산 안의 COMMIT·
  reader 예산·반복 decode/hash·행/재진입 pg_locks 스캔 — F-DES-02~04·D3·C1-09·C2-09·C2-01·
  C2-07·B4·A1-05·A2-04), 활성화·보존(deactivate·installer 잠금·attempt/manifest prune — B3·
  B9·C2-06·A1-03·B5·C1-06), 기타(heritage EX 상한·427 인덱스·URL 예산·encoder 단일화 등).
- 다음 단계는 측정이다(Airport·Rest EX 적재의 elapsed·P 보유·lock wait, 427 인덱스 크기·
  idx_scan). 경합 사례가 측정되지 않으면 ADR-117로 이 경로를 퇴역한다(권장). 그때 P를 DDL·
  유지보수 gate로만 남길지 ADR-111 모델로 되돌릴지 함께 정한다.
