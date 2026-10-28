# Rest432 영속 재관측의 제한된 첫 profile — 설계 초안

> **상태(2026-10-27): 대체됨(superseded).** 구현 전 설계 초안이다. 432 제한 profile은 PR #1418로
> 머지·배포됐고 결과의 정본은 [432 구현 원장](2026-10-26-rest-snapshot-atomic-implementation.md)이다.
> 새 profile은 기본 OFF이며 SH 스냅샷 경로는 동결됐다(동결 → 측정 → 퇴역 결정 대기). 현재 상태의
> 정본은 [ADR-115](../adr/115-scoped-concurrent-feature-writes.md)다.

## 상태와 근거

기준은 reader 후보65e4943d8ae21ef17123a33de4d74a107f30f473이다. 이 문서는 제품코드·
스키마·실제 PG·HTTP·Chrome·운영 변경 없이 다음 수용 단위만 정의한다. 별도 branch에서
작성하며431의 source/원 더티 WT는 건드리지 않는다.1415 머지 전에 문서 PR만 먼저 머지하지 않는다.

Root 결정과 읽기 전용 검토 T r2(SHAa90f20c3ea99e6bce66f3e3bd57fe0aba7114fbbf14f978385f11cb291934d43),
J 범위(SHAcb15a5c9a677930428c7cd81a41860d570fdfe3eb842409321ae6da9046a9c87)를 반영했다.
원장 원본은 별도 A에 보존한다. 이는 새 전체 repo 리뷰나 구현 수용이 아니다.

## 권위와 첫 입력

첫 profile은 현재 Transport Rest endpoint의 **단일 current-export-window 전체응답**만
받는다. Transport213c048의 service_exports.py는 요청 한 개 안에서 RR로 state/rows/주소를
읽으며 default500/max1000이고, current membership은 last_seen_at >= last_success_at−3일이다.
따라서 최근 이전 관측이 포함될 수 있다. 이 집합을 최신 upstream batch의 정확한 membership,
서버 frozen generation, absence-retire 또는 EX bootstrap 권위로 부르지 않는다.

새 호출은 cursor 없이 limit256을 명시한다. 기존 own-service HTTP의 `_transport_get`/
`_transport_json`과 Map의 `parse_export_page`/`require_current_collection`을 직접 재사용해
HTTP200·bounded 전체body·
source=krex_rest_area·aware last_success_at·failed/stale=False·has_more=False·next_cursor=None,
비어 있지 않은 고유 natural key와 count≤256을 함께 확인한다. page2를 이어 부분 등록하지 않는다.
257/has_more/nonnull cursor/잘린 body/잘못된 source·clock·중복·빈 입력이면 전체 거부한다.
215는 실제 수용 표본이며 운영 필수 개수로 하드코딩하지 않는다. 기존 item iterator는 EOF와
collection metadata를 잃으므로 그대로 완료권위를 부여하지 않는다.
단일 bounded 응답의 metadata/원body SHA를 보존하는 추가 경계이며 별도 TransportSDK 프로젝트나
외부 provider client 재구현·새 facade를 요구하지 않는다.

한 응답의 원 collection/EOF/page metadata·전체 export bytes SHA·원 item/native digest를
typed context에 결박한다. clock/generation은 다시 만들지 않고 원값을 보존한다. 아직 정하지
않은 Rest observation/postprocess domain·context 추가필드의 exact wire명은 구현 직전 단일
명세와 fixture로 고정한다. timestamp만으로 membership ID를 만들어 내지 않는다.

첫 apply는431이 적격이라고 판정한 unchanged 재관측 SH에 한정한다. 저장 DB와 membership,
Geo·현재token·policy·비scalar23개가 정확히 같아야 하며 retired=0이다. 기존 scalar 이력과
NULL 표현도431 계약대로 확인한다. 입력 부재를 근거로 삭제/퇴역하지 않는다. 적격하지 않은
입력은 deferred/reject이며 이미 등록된 artifact를 EX/legacy 경로로 낮추지 않는다. 새로운 값변경
범위나 EX bootstrap은 이번 profile에 암묵적으로 추가하지 않는다.

## 430 정적 재사용의 여섯 경계

| 경계 | 현재 정본과 필요한 최소 연결 | 보존 조건 |
| --- | --- | --- |
| 등록/DB domain | `_430_snapshot_registration.sql`의 Airport 전용 dataset/entity/domain gate에 DB-derived Rest 정적 분기 | root→child→정확member/triple/run, immutable payload/context SHA·pins9, STARTED/취소/격리 검증; 호출자 wire가 profile을 선택하지 않음 |
| 저장 read/gateway | `infra/provider_snapshot_recovery_repo.py` read/register 및 typed token/plan 함수 | infra 안의 Airport/Rest exact decoder dispatch만; Dagster 역의존0·임의 registry0·원lease/fence/reset 유지 |
| plan/apply | `client/_airport_snapshot.py`, `providers/kor_travel_transport_apply.py`의 정본 apply와431 reader | 잠금 전 Python RR 진단과 잠금 뒤 RC fresh검증을 분리; stored bytes/manifest/head/Geo/non-scalar 재대조 후 기존 SH kernel finish+14counter/retired 저장 |
| 관측/후처리 | Dagster observation/postprocess codec 및 `_430_snapshot_postprocess.sql`의 domain/asset gate | Rest asset `feature_place_transport_rest_areas`, 원clock/generation/full findings hash·14+retired, intentSHA/동일TX marker·실counts/sync proof 유지 |
| 실제 caller/runtime | 기존 opt-in runtime/runner·SDK0 재개 루프 | Rest 별도 명시OFF; 성공claim 뒤 fresh SDK0read, rootdone/sealed 원receipt 복구, failed/cancelled/취소/격리 차단, 유한 replan 유지 |
| quota/GC/설치 | 등록 quota/reservation·terminalGC·migration/ACL/startup/ORM/실제golden | 정확 Rest DS 명시row만; 미설정은 backpressure; active/unsealed GC0·원ledger 반환/최소ACL·Airport 불변 |

공통 helper 추출은 여섯 경계에서 실제 중복이 확인된 부분만 소유권을 합의해 시행한다. 별도
미호출 helper PR 여러 개를 먼저 활성화하지 않는다. feature/rawtable 권한이나 private capture
runtime EXEC를 넓히지 않으며 기존 typed fenced capture를 재사용한다.

현재 Rest codec은 `rest-area-prepared-typed-v1`과 provider=kor-travel-transport,
dataset_key=transport_rest_areas, source_entity_type=rest_area,
normalizer=transport-rest-area-name-phones-v1, Geo=transport-rest-area-geo-v1,
clock=aware-clock-preserved-v1, native=native-full-refresh-v1 및 설치code/SDK pins를 고정한다.
artifact1MiB·context8KiB·result/후처리 각4KiB를 유지한다.431 evidence4MiB와 decoder JSON
4,133,162B는 durable artifact wire 한도가 아니다. runtime/DB가 derive한 profile과 exact pins를
재검증하며 artifact 안의 문자열만 믿고 decoder나 권한을 선택하지 않는다.

## DB 원자성과 잠금

등록은 P_SH→actual ownparent SHARE→ownscopeX→root/child/member KEY SHARE 선취득→
정렬 quota(global0/정확DS)→control 순서를 유지한다. FK가 취득하는 tuple 잠금도 이 순서에
포함한다. 동일member/동일immutable bytes는 quota 접근과 nonce 노출/lease갱신 없이 기존
snapshot만 돌려주며 다른 입력은 거부한다. 신규등록의 quota2개+reservation+artifact+control은
한 TX다. 저장값/결과를 공개 source_records의 독립 원장으로 복제하는 방향이 아니다.

claim/renew는 P_SH→ownscopeX→control이며 root/member/quota 잠금0이다. 만료handoff만
새 generation/DBnonce를 받으며 성공claim 뒤 현재상태/binding을 SDK0로 다시 읽는다.
apply는 P_SH→전actualparent/scope/Feature/attempt→control 뒤 typed fenced capture와
kernel finish/result를 같은TX에 둔다. seal은 P_EX→L→root/member→control 정본을 유지한다.
reset은 exact dataset 확인→P_SH→actualparentSHARE→ownscope→oldattemptFORUPDATE→control이며
expired ready/exactcancelled만 허용한다. current applying/completed/reclaimed epoch 복원은 금지한다.

**현재430의 분리 TX와 구현할 선택A를 구분한다.** `_resume`은 apply 완료 후 새 read와
별도 postprocess coordinator·seal을 호출한다. `_airport_snapshot._unbound`/`_transaction`은
bound client를 거부하고 새 session.begin을 열며, `_snapshot_postprocess.run_snapshot_postprocess`
역시 자기 RC TX 안에서만 rollback_only callback·receipt 원자성을 보장한다. 이들을 outer TX에서
나열하는 것만으로 하나의 commit이 되지 않는다.

Root가 선택한 A는 **load DML+원14counter/retired+필수 ETL/observation/sync/findings+
postprocess receipt**를 공통 caller-owned coordinator의 한 RC connection/TX에서 commit한다.
planning RR·외부 HTTP/Geo·codec 준비는 그 TX 밖에서 끝내고, coordinator가 정본 P_SH→
전actualparent/scope/Feature/attempt→control 순서와 유한 deadline을 소유한다. Rest로 정확히
분기한 lowlevel apply의 명시 session seam을 재사용하고 kernel finish/capture/result 뒤 같은
session의 반환bytes로 pure intent를 만든다. 이어 기존 begin postprocess SD→동일 connection의
rollback_only bound callback→finish receipt를 수행한 뒤 한 번 commit한다. 미commit control/
result를 다른 unbound session으로 읽거나 callback이 자기 connection/commit을 열게 하지 않는다.
원 Airport public own-TX API는 보존하며 그 호출을 새 coordinator의 원자적 내부 단계로 위장하지 않는다.

registration/claim과 **control child/root seal은 이 한 commit 밖**이다. seal은 durable 원결과/
receipt를 읽는 기존 P_EX→L→root/member finalization을 유지하며 SH→EX 승격하지 않는다.
따라서 이 선택은 seal까지 한 commit이라는 뜻이 아니다. apply/result와 필수 후처리의 원자성이
T-CWRITE04에서 닫을 구현 목표이며 선택 문서만으로 완료 처리하지 않는다. 실제 partial rollback·
unknown-commit SDK0/DML0·fence/두writer 증거가 필요하다. postprocessed replay는 원receipt 비교
뒤 sideeffect0이어야 하며 finish(A→B)·marker 단독commit은 완료 proof가 아니다.

### 후처리 공유 topic의 필수 열린 경계

J 원장 e41110a2와 T 독립 d693de88의 소스 조사에서 finding이 있으면
`dataset_projection → provider_sync`, 없으면 sync 뒤 zero-row stale UPDATE의 statement trigger로
`provider_sync → dataset_projection` 순서가 가능하다. bump는 즉시 같은 topic 행을 UPSERT하며
GUC defer/비동기 경계가 없다. actual PG 교착 재현은0이고 기존 Airport 정본1DS 범위이므로
운영 deadlock으로 확정하지 않는다. 서로 다른 DS의 ownscopeX만으로 이 역순은 제거되지 않는다.

S3는 첫 topic DML 전 trusted TX seam에서 두 topic을 고정 `COLLATE "C"` 순서로 선취득할
접점과 행 누락 시 fail-closed 경계를 구체화해야 한다. 정본 bump/알림 성공 조건을 생략하거나
일반 caller·rawtable ACL을 넓히지 않는다. S5는 다른 DS의 empty/nonempty barrier로 두 순서의
wait/cycle을 실제 관측하고 `55P03` timeout과 `40P01` deadlock을 구분한다. 첫 topic 취득부터
commit까지 남는 작업·대기·실제 직렬화 구간을 측정하며 최종 코드 결론은 그 실물 증거 뒤 정한다.

## quota와 실측

현재430의 global16MiB/256 snapshot·Airport4MiB/64 snapshot만 존재하며 Rest quota는 없다.
used_rows는 source215개가 아니라 저장 snapshot 개수다. Rest 수치는 이 설계에서 발명하지 않는다.
실제215 artifact/context bytes와 결과/후속 각각4KiB 예약, 보존7일/예상스케줄·중복/재시도
잔량을 측정해 정확 DS row 정책을 제안한다. 부족/미설정은 실패하며 global/기존Airport 한도를
자동 확대하지 않는다. physical heap/TOAST/WAL/RSS와 logical quota는 별도 계량한다.

기존 boundedcapture2730관계행/row256KiB/encoded1MiB, reader statement3초/lock1초 및
wholeempty/EOFFalse를 유지한다. reader215 fit는 kernel manifest/두scalar 경계/counter/capture/
후처리·seal fit 증거가 아니다. 소유된 같은215를 실제apply까지 검증하고 초과는 전체 거부한다.
동시worker CPU/RSS·잠금 분포는 두 물리 writer 시험의 별도 수용이다.

## 수용 전 열린 항목

- 기존 service fetcher의 typed 단일응답 metadata/context와 exact domain/sha framing.
- unchanged 범위의 잠금 후 fresh검증 및 다른 profile/DS 입력의 명시 거부.
- 선택A의 load/필수후처리 한TX 실제 구현·rollback/응답유실 증거; registration/claim/seal은 별도TX 유지.
- 실215 wire/context/manifest/capture/latency/CPU/RSS와 정확 quota policy.
- 실제 두writer/unknowncommit/취소/backenddeath/GC/Airport 비간섭 및 최종golden/최소ACL/CI.

후속 구현·시험을 진행하더라도 기존 Airport 및 새 Rest runtime opt-in은 계속OFF다. 이 문서는432 구현 승인·PG 생성·수집/운영
활성화 권한이 아니며 [구체 작업·시험](2026-10-26-rest-snapshot-registration-tasks.md)으로만 넘긴다.
