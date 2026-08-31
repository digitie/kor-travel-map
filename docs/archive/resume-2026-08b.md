# resume-2026-08b.md — resume.md 아카이브 (2026-08-01 ~ 2026-08-04)

> `docs/resume.md`에서 2026-08-31 분리(규약 §8). 읽기 전용 이력.

## 2026-08-04 (2) — 재생성 실행·공개 표면 4,424 복구·H40 완결·H22 단일 PR

재생성 실행 완료(`0078` 직행, rev `2b2dee95`, 함정 2건 실측 — superuser 확장 사전 생성
필요·`sudo compose`). concierge 축 재적재로 **공개 표면 4,424건 복구**, 전부
`source_rule`(= **H40 완결**). H22A/B/C를 사용자 지시로 보류 해제하고 단일 PR로 구현 —
read model 2 + reclassify command + admin 패널 + mocked 6건 + live spec 저술 + 격리 스택
HTTP 파괴 검증 9흐름 통과.

**다음 한 작업**: H22 PR에 적대 리뷰어 2명(렌즈 분리) → CI green → 머지 → Lane A 다음
항목(H30B — 재적재 안정화 대기 중이면 Wave 2 barrier의 T-VN-31A). 잔여 재적재: provider
일일 스케줄 + CSV 5종(feature 적재 후). codex 41C prod enable은 재pin(#109)+CSV5 후.

T-VN-41D는 migration `0079`, strict private command, lost-attest receipt replay, late-run CAS
cancel, Manager lease/receipt state machine과 ephemeral Compose rehearsal까지 완료했다. command
5건, isolated PostgreSQL 3건, Manager 143건, actual Docker rehearsal 1건을 통과했고 n150/prod
접근은 없었다.
## 2026-08-04 — prod 0072 사고 → 폐기·재생성. H35 재정의

prod가 pin과 다른 7/31 이미지(`0bdecb1f`, head `0072`)로 배포되며 entrypoint 자동
migration이 `0063 → 0072`를 적용, 공개 큐레이션 표면이 **0건**이 됐다(데이터는 무손상).
**사용자 결정: 복구하지 않고 폐기 후 재생성** — H35 cutover·typed helper·결합 barrier
사문화(tasks.md 재정의 블록), tvn41은 무영향(자체 DB, 실측).

사고 시점 dump는 아카이브·복원검증 완료(`~/backups/krtour_map_0072_*.dump`, 오류 0줄).
재발 방지: PR #931(entrypoint EXPECTED_HEAD 게이트 + DB-ahead 즉시 실패; `MODE=none`은
2차 적대 리뷰로 도입 전 제거) + Docker-manager 이슈 #109(image↔pin 일치 게이트).
npm audit 전면 실패는 PR #932로 해소. **주의**: prod compose(manager 소유)는 고정 env
목록이라 EXPECTED_HEAD 결선은 manager compose 수정이 필요하다(별도 이슈) — 그 전까지
재생성 배포의 head 검증은 빌드 단계 수동 게이트(`alembic heads`=`0078`)로 한다.

**다음 한 작업**: #932·#931 머지 → n150에서 main 기준 api 이미지 재빌드(head 수동 검증)
·배포 → 빈 `krtour_map` 재생성(`0078` 직행) → 재적재(provider ETL +
`curated_features_refresh_job` + CSV 5종) → 확인 후 **T-VN-H22 단일 PR**(사용자 지시)
→ Lane A 다음 항목 순차 진행.
## 2026-08-03 — H22 착수 전 실측: 격리 대상이 0건이고 구조상 0건이다 (PR #929)

Lane A 다음 항목 T-VN-H22A(quarantine read model)를 시작하기 전에 규모부터 쟀다. 계획이
전제한 "격리된 canonical-only item"이 **이 DB에는 하나도 없다.**

라이브 prod 읽기 전용 실측에서 `curation_items` 3,530건이 **2×2의 대각선만** 채운다 —
legacy-marker collection 52개는 `curated_features` 투영본 3,044건만 담고, CSV collection은
네이티브 486건(`korean-tourism-100`·`arboretum`·`lighthouse`·`heritage`)만 담는다. 격리는
**비대각 칸**(legacy collection 안의 네이티브 item)을 요구하는데 그 칸이 비어 있다.
격리 clone에 `0065`를 실제로 적용해도 quarantine 0개/0건이었다. marker 생성자는 `0065`
하나뿐이고 1회성이라 **배포 후에도 영구 0건**이다.

그래서 **H22A/B/C 셋 다 대상이 없다.** 셋의 유일한 목적이 "격리된 item의 운영자 재분류"인데
재분류할 것이 영구히 없다. 조사가 함께 경고한 "배포 직후 `[0065 격리]` collection이 admin
UI에 설명 없이 등장" 문제도 collection이 생성되지 않아 소멸한다.

**종결 여부는 사용자 결정으로 남겼다** — 축소가 아니라 대상 소멸이라 임의로 닫지 않았다.
대신 전제를 배포 게이트에 박았다: H35 **preflight**가 `quarantine_candidates_before`를 0으로
검사한다. 경계 뒤에는 관측치만 남기고 거부하지 않는다.

**첫 설계는 틀렸고 적대 리뷰가 반증했다.** 나는 이 검사를 verify에 hard check로 두면서
"격리가 생기면 어차피 `public_items_verify`가 깨지니 원인만 이름으로 바꾸는 것"이라고 적었다.
실측하면 **격리 1건이 생겨도 공개 수는 3,043 그대로**다 — 격리 조건은 `status`·
`source_present`·accepted link 어느 것도 요구하지 않아 공개 집합과 독립이다. 즉 그것은
경계 **뒤**의 새 거부 경로였고, 거기서 거부되면 출구가 없다(csv5는 accepted prior receipt
요구 / migrate 재실행은 `schema_before=0063` 요구인데 DB는 이미 `0078` / `0065` downgrade는
durable state에 fail-close). **#925에서 내가 잡아냈던 index signature 함정과 같은 계열을
내가 다시 만든 것이었다.**

회귀는 "0이다"를 확인하지 않는다 — 시드에 legacy-marker collection이 없어 공회전이 된다.
대신 legacy collection 안에 네이티브 item을 **실제로 만들어** ① `0063`에서 후보로 잡히고
② head까지 밀면 `0065`가 실제로 격리하며 ③ 그런데도 verify의 check는 늘지 않는지를 함께
고정한다. ③은 변이로 확인했다 — verify에 hard check를 되돌려 넣으면 깨진다.

부수로 내 informational 쿼리의 3값 논리 버그를 잡았다 — `NOT (… OR …)`에서 `migrated_from`
키가 없는 collection은 `NULL OR false = NULL` → `NOT NULL = NULL`로 걸러진다. 격리 건수는
`0065`와 같은 긍정형 술어라 영향 없었고, 합이 3,044 ≠ 3,530으로 안 맞아 발견했다.

**다음 한 작업**: 사용자가 H22 종결을 결정하면 반영하고, 아니면 Lane A의 그다음 항목으로
넘어간다. H35는 여전히 Docker-manager 이슈 #99(pin이 결함 있는 `d50bb2c5`에 묶여 있음) 대기.
## 2026-08-03 — H35 적대 리뷰: 실행 전 잡아야 했던 helper 결함 2건 (PR #925)

최종 exact HEAD `d50bb2c5`에 적대 리뷰어 2명 + refute/reproduce 검증(15 에이전트)을 붙였다.
리뷰어가 낸 findings 6건은 **전부 기각**됐고, synthesizer가 직접 측정하며 찾은 2건이
살아남았다. 둘 다 격리 컨테이너에서 독립 재현했다.

**① `idx_features_public_weather_coord_5179_gist` signature가 어떤 DB와도 안 맞는다.**
`kind = 'weather'::text`를 요구하는데 `feature.features.kind`가 `character varying`이라
PostgreSQL은 항상 `((kind)::text = 'weather'::text)`로 deparse한다. 이 index가 영구
non-canonical이 되고 **head에서 partial probe가 통과할 수 없다**(수정 전 실패 1건 →
수정 후 7건 전부 통과).

파급이 크다 — `run_migrate`의 forward 재개 경로(`schema_before != TARGET_SCHEMA`면 upgrade)가
그 앞 게이트에 막혀 **죽는다**. migrate commit 뒤 receipt를 잃으면 csv5는 accepted prior
receipt를 요구해 못 가고 migrate는 다시는 accepted를 못 낸다 → DB는 정확히 목표 상태인데
남은 출구가 **PITR 없는 prod의 단일 dump 복원**이 된다.

**② 공개 item 카운트가 `source_present`를 빠뜨려 de-publish를 못 잡는다.**
실제 공개 술어(`_LIST_FEATURE_ITEMS_SQL`)는 `AND i.source_present`를 포함하는데 helper
카운트 두 곳에 없었다. 실측: item 1건을 source-absent로 만들면 실제 API는 3,042인데
게이트는 3,043을 계속 보고한다. **내가 이슈 #99에 올린 SQL에도 같은 결함이 있어 정정했다.**

기존 회귀가 못 잡은 이유도 고쳤다 — 단위는 합성 `_states()` 맵, 리허설은 `_PRE_REVISION`
에서만 probe라 실제 `pg_get_indexdef`를 head에서 검사하는 경로가 없었다. 회귀 3건을
추가하고 전부 변이로 falsifiability를 확인했다.

**n150 실행은 하지 않았다.** 사용자 승인은 받았지만 (a) pin된 `d50bb2c5`가 이 결함 2건을
포함하고, (b) orchestration 소유자인 Docker-manager가 실제 cutover를 여러 차례 시도해 전부
pre-forward fail-close 후 rollback한 상태이며 지금은 T-049 진단 도구를 구현 중이다
(PR #100/#101 머지). Docker-manager 이슈 #99에 확정 gate 값과 이번 결함, pin 갱신 요청을 남겼다.

**다음 한 작업**: PR #925 CI green 확인 후 머지 → 이슈 #99에 새 SHA 통보 →
`map_release_revision` pin 갱신은 Docker-manager 소유. 그 뒤 다음 백로그 작업으로 이동.
## 2026-08-03 — H35 §5 gate를 실 prod 데이터로 실측 (0063→0078 전 구간 일치)

runbook §5가 선언한 phase gate 값을 **실제 prod 백업 clone**에서 확인했다(prod 무접촉,
포트 노출 없음). 이전 실측은 `0074` head 기준이었는데 그 뒤 `0075~0078`이 추가돼
재검증이 필요했다.

```
preflight  0063_pipeline_root_id / 공개 item 3,265          → 일치
migrate    0078_cache_target_gc_observe / 3,043 / invalid 0 → 일치
csv5       파일 5 / accepted 222 / rejected 0 / 3,265        → 일치
```

**`0075~0078`(cache_target 계열)이 curation 공개 표면을 바꾸지 않는다**는 것이 추론에서
실측으로 확정됐다. 세부와 주의사항은 runbook §10.1에 적었다 — 특히 이 실측은 helper를
우회한 것이라 §11의 "network-free 리허설"(helper 경유) 항목을 **대체하지 않는다**.

T-VN-41(#917/#923/#924)은 codex가 머지 완료했고 n150 부하도 load 0.76으로 정상화됐다.

**다음 한 작업**: §11 실행 승인 조건 중 남은 것 — 최종 exact HEAD 적대 리뷰(진행 중),
보안 감사·CI green, 그리고 **사용자의 명시적 n150 실행 승인**. 배포는 비가역이고
PITR이 없으므로 승인 없이 실행하지 않는다.
## 2026-08-02 (codex) — H35 scope validator delegate-chain fingerprint 보완

재리뷰에서 top-level `ops.is_valid_feature_update_scope(text,jsonb)`가 의존하는
`ops.is_valid_feature_update_scope_0074(text,jsonb)`와
`ops.is_valid_feature_update_scope_0052(text,jsonb)`가 function inventory에서 빠진 P1을 확인했다.
required inventory를 schema-qualified exact regprocedure 5개로 바꾸고 각 함수의 name/identity args/result,
body/config/volatility/parallel/security-definer/leakproof/strict/owner를 canonical fingerprint에 포함했다.

실제 PostGIS `0063→0078→CSV5→GC/replay→verify`에서 여섯 scope의 대표 valid/invalid와 generation-7
512자 target key 경계를 top/0074/0052 각각 실행했다. 두 delegate별 동명 exact-signature body/config/
속성 drift와 동명 wrong args+result drift도 verify가 DB/runtime/external mutation 0으로 거부함을 확인했다.

**다음 한 작업**: 새 exact HEAD의 CI와 보안 감사를 통과시키고 동일 유일 reviewer의 재승인을 받는다.
## 2026-08-02 (codex) — H35 NO-GO 구조·PostGIS 리허설 해소

`0075~0078` final verify를 relation/column/PK·UK·FK·CHECK/index/trigger/function/sequence의 PostgreSQL
semantic catalog fingerprint 검증으로 강화했다. constraint column/action/validation/deferrability,
index expression/predicate/valid-ready-live, trigger enabled/bound function, function body/config/volatility,
relay sequence ownership과 scope validator를 exact하게 고정한다.

실제 PostGIS에서 `0063→0078`, CSV5, generation-7 stream/source/snapshot/reconciliation/outbox/delivery/
claim, bounded GC 최초·replay와 final evidence를 한 번에 재현했다. drop·동명이형 constraint/index/trigger,
invalid/not-ready index, disabled trigger, function drift와 stale/expired/mixed/Merkle, 네 backlog, foreign GC
observation, `csv5→verify` chain skip를 모두 mutation 0으로 거부한다. GC observation ID는
`h35:{transaction_id}:cache-target-snapshot-gc:v1` golden vector로 고정했다. 운영 순서는
`csv5 → gc → exact 5-writer final fence → Map verify → PinVi final boundary`로 정렬했다.

**다음 한 작업**: Docker-manager의 동일 observation ID·receipt round-trip 및 전체 CI와 보안 감사를
exact 양쪽 HEAD에서 확인하고, 동일 독립 리뷰어의 재승인을 받는다.
## 2026-08-02 (codex) — H35 5단계 receipt CI fixture 정렬

PR #924의 Python 3.11/3.12/3.13 CI는 모두 같은 기존 unit fixture가 새 공통 receipt key
`cache_target_evidence`와 `csv5→gc→verify` chain을 반영하지 않아 1건 실패했다. 생산 validator는
그 누락을 의도대로 거부했으므로 느슨하게 만들지 않고 fixture에 앞 phase evidence `null`과 `gc`
receipt를 추가했다. H35 contract unit **46건**과 대상 Ruff가 통과했다.

**다음 한 작업**: Agent B의 GC/final evidence 반례 matrix와 Docker-manager 전체 receipt validator를
결합한 최종 exact HEAD에서 전체 CI를 통과시킨 뒤 단일 적대 리뷰를 요청한다.
## 2026-08-02 (codex) — H35 GC·PinVi 최종 DB 증적 hardening

Map helper 체인을 `preflight→migrate→csv5→gc→verify`로 완성했다. `gc`는 outer cutover transaction
UUID에서 결정적으로 만든 observation run ID로 기존
`AsyncKorTravelMapClient.drain_expired_cache_target_snapshots`만 호출한다. session advisory lock,
batch transaction, `0078` observation의 `ON CONFLICT` 멱등성을 그대로 사용하며 attempt 삭제 건수가
아니라 최종 expired·unreferenced backlog 0, referenced 보존, 저장 observation과 fresh count 일치로
재실행을 승인한다.

모든 receipt에 `cache_target_evidence` exact key를 추가했다. 앞 네 phase와 rejected verify는 `null`이고,
accepted verify만 read-only repeatable-read view에서 PinVi ready stream, 양의 epoch/version, unexpired 최신
snapshot header/item/live source Merkle와 material watermark 일치, 네 backlog 0, deterministic GC
observation 일치를 확인한 `ktm-cache-target-final-evidence/v1` object를 발급한다. mixed/stale snapshot,
invalid hash, non-ready/blocked stream과 backlog는 fail-close한다.

**다음 한 작업**: Agent B가 새 5단계 receipt·GC replay·증적 반례 black-box/integration matrix를
소유하고 Docker-manager가 receipt 전체 exact validator와 journal을 결합한다. 모두 합친 최종 exact
HEAD에만 적대 리뷰어 1명을 요청하며, 그 전에는 n150을 실행하지 않는다.
## 2026-08-02 (codex) — H35 Map typed helper Agent A 구현

candidate API image에 credential/path-free `preflight`·`migrate`·`csv5`·`verify` helper와 canonical
CSV5 resource를 포함했다. 계약·schema·CSV5를 서로 독립인 private module로 분리했고, stdin/argv
실패도 stderr 없이 secret-free JSON 한 줄로만 반환한다. live DB identity는 transaction UUID,
`map_application`, `current_database()`, PostgreSQL system identifier의 NUL-framed SHA-256을 매 phase
mutation 전에 재계산한다. `0064`/`0068`/`0069` partial state는 revision별 단일 statement prefix와
canonical access path만 허용하며, Alembic 출력은 bounded internal sink에 버린다.

CSV5는 image 내 manifest/hash와 5개·486행·accepted 222/rejected 0을 고정하고 exact complete state만
멱등 skip한다. focused Ruff, strict mypy, import-linter, curation unit 36개와 기존 0064/0068/0069
migration integration 3개가 통과했다.

**다음 한 작업**: Agent B가 helper black-box/mutation-zero matrix와 scratch `0063→0078` rehearsal을
독립 구현하고, Docker-manager typed journal과 결합한 누적 delta를 적대 리뷰한다. 그 전에는 n150을
실행하지 않는다.
## 2026-08-02 (codex) — H35×T-VN41 cutover 보정 문서 checkpoint

과거 H35 `NO_GO` runbook과 `0072`/`0078` 일부만 보는 helper를 실행 정본에서 제외했다.
새 runbook은 Docker-manager one-process lock/journal과 Map의 credential/path-free typed helper 경계를
분리하고, 공개 표면 `3,265→3,043→3,265`, CSV5 accepted `222`/rejected `0`, `0075` preflight,
`0075→0078` 구조 검증을 exact gate로 고정한다. Map Agent A(helper)와 Agent B(검증)는 이 문서의
exact head를 공통 계약으로 병렬 구현할 수 있다.

**다음 한 작업**: 문서 PR의 exact head를 적대 리뷰 2명에게 맡겨 설계 승인을 받은 뒤에만 Agent A/B
구현을 시작한다. PR #923이 포함된 최신 `origin/main`에 rebase했으며, 그 전에는 n150을 실행하지 않는다.
## 2026-08-02 (codex) — T-VN-41 command principal 최소 권한 구현

source PUT/DELETE와 refresh create에 relay consumer umbrella를 재사용하면 writer token이 read/claim/ack/
nack/snapshot까지 획득하는 권한 역전이 생긴다. exact `cache-target:command`를 추가하고 기존
`cache-target:consumer` umbrella는 enum·validator·인증 fallback에서 clean cut 제거하기로 했다. command
principal도 consumer·snapshot·recovery 경로를 호출할 수 없다.

한 canonical `(consumer_id, sorted external_systems)` binding마다 command, consumer, restore, recovery
exact 역할 profile을 각각 하나씩 요구한다. 다중 disjoint binding은 허용하되 external system 소유권,
token digest, `principal_id`는 전역 unique다. 단, 같은 `consumer_id`는 정확히 한 canonical binding만
소유하며 여러 system은 한 sorted union으로 표현한다. 역할 누락·중복·혼합/부분 scope, 비정렬 allowlist와
설정된 admin/service/ops/metrics/cursor secret 및 public VWorld/API key digest 충돌도 fail-close한다.

17개 service cache-target/refresh operation에 machine-readable `x-required-service-scope`를 넣고 route →
scope → caller role → runtime passed scope를 하나의 inventory로 고정했다. 51개 wrong-role 조합은
metadata/domain service 호출 0회에서 `403`이다. request-bound reconciliation은 scope-only 검사 뒤에만
metadata를 조회하고 consumer/system 결박을 다시 검사한다. command writer가 PUT/DELETE CAS 후 source GET이나 refresh
`Location` polling GET을 수행할 때는 consumer credential로 전환해야 한다. generation 7 exact pair pin을
writer/backfill/consumer 활성화의 선행 조건으로 옮겼다.

full/service OpenAPI와 admin generated types를 재생성했다. service SHA-256은
`622ea54c98e9b0c09592cf84aced36227992c6bdf256742a3532b892f0efccf2`다. router 172건, OpenAPI export
12건, API strict mypy 61개 파일, 대상 Ruff, OpenAPI all drift, frontend `gen:types:check`가 통과했다.
PinVi contract generation 7 재핀과 caller credential 전환은 아직 완료하지 않았고 별도 paired PR이
소유한다.

**다음 한 작업**: public-key/consumer-owner hardening을 포함한 새 exact head를 두 독립 적대 리뷰에 다시
넘겨 GO를 받은 뒤 최종 전체 gate를 실행한다.
## 2026-08-02 (codex) — T-VN-41C referenced snapshot 보존 추세 alert

Dagster run metadata만으로 직전값을 찾는 stateless 추정은 metadata 정리·재실행·op retry에 따라 기준선이
달라져 채택하지 않았다. migration `0078_cache_target_gc_observe`로 acquired GC run별 referenced
item/header count를 `ops.poi_cache_target_snapshot_gc_observations`에 영속화했다. GC 전역 lock 안에서
관측 identity를 배정하고 같은 `Dagster run_id` retry는 최초 row와 분류를 재사용하며 overlap skip은
표본에서 제외한다. 직전 acquired와 마지막 적격 baseline을 각 row에 별도로 복사하고, 300초 미달·동일/역행 DB 시각 표본은
다음 baseline으로 승격하지 않는다. config가 달라져도 직전 acquired보다 비전진한 표본은 fail-close하므로
짧은 재실행이 이후 급증을 흡수하지 않는다. 이력은 기본 90일로 bounded다.

hourly op는 직전 acquired 대비 loss delta와 마지막 적격 baseline 대비 elapsed seconds·시간당 증가율,
item/header 보존 ceiling을 exact metadata로 남긴다. 기본 ceiling은 16,800,000 item/168 header,
증가율은 100,000 item/hour와 1
header/hour이며 300초 미만 간격은 증가율을 추정하지 않는다. 초과는 reason별 boolean, 통합
`referenced_alert`, Dagster warning으로 드러내되 정상 GC를 retry하지 않는다. count 감소는 간격과
무관한 inventory-loss 경보이며 overlap/unavailable/nonforward는 threshold와 별도 observation issue다.
관측은 파생 데이터라 app-only rollback에서 table을 보존하고 forward recovery한다. 명시적 downgrade는
table을 폐기하며 0078 재-upgrade 뒤 빈 기준선부터 안전하게 재개한다.

**다음 한 작업**: n150 격리 DB에서 migration → 수동 GC → schedule ON → 다음 hourly tick을 연속 실행해
실제 관측 delta/rate와 임계값 warning을 확인하고, GC 유입률 상회·remaining backlog 0를 함께 증명한다.
## 2026-08-02 (codex) — T-VN-41 canonical Unicode identity 보강

최종 적대 리뷰에서 NFC-equivalent `target_key` 두 개가 raw text 자연키로는 공존하지만 Merkle leaf에서
같은 identity로 축약되어 snapshot을 영구 500으로 막는 P1을 발견했다. `external_system`과 `target_key`를
API 422, repository, `poi_cache_targets`/stream/source-head/feature-update scope DB CHECK에서 trim된 NFC
canonical form으로 강제했다. `cache_target_keys`도 root 자연키와 같은 512자 상한을 사용한다. 비정규
source·refresh scope는 durable head/request 생성 전에 거부하고 정확한 constraint와 snapshot 회귀를 추가했다.

**다음 한 작업**: exact WIP 두 독립 재리뷰와 전체 gate를 통과한 뒤 Map final commit/OpenAPI를 PinVi에
재핀하고 n150 100,000/100,001 snapshot live gate를 실행한다.
## 2026-08-01 (codex) — T-VN-41 fixed snapshot durability·bounded GC

service 일반 snapshot 첫 page가 repository에서 header/items를 INSERT하고도 read-only session 종료 때
rollback되어, 응답 UUID의 다음 cursor가 사라지는 P1을 live E2E에서 발견했다. route가 DTO 구성까지
포함한 transaction을 소유해 commit 실패/예외에는 200을 내지 않도록 고쳤다. 응답에는
`created_at`/`expires_at`을 필수로 노출한다.

내구화 뒤 full snapshot이 누적되지 않도록 generic 경로를 single-flight로 분리했다. source head와 같은
transaction에서 증가하는 `cache_target.state_applied` material watermark를 global cursor와 별도 header에
저장하고 epoch/watermark가 현재 값과 exact할 때만 재사용한다. advisory lock 뒤 별도 stream share barrier
statement가 기존 outbox writer 완료 뒤 identity/head를 읽게 해 lock-wait stale MVCC 누락을 막는다.
모든 outbox writer transaction은 head/target/link 접근 전에 stream을 잠그고 여러 system이면 정렬 순서로
모두 선취한다. 이 stream → head/target/link 순서로 각 system cursor가 같은 stream에서 늦게 commit되는
더 낮은 relay를 추월하지 않는 commit-safe contiguous prefix가 되게 한다. 번호의 global uniqueness는
서로 다른 stream 사이의 commit 순서를 뜻하지 않는다.
DB trigger는 stream lock을 재확인한 뒤 명시적 global sequence에서 relay를 배정한다. Identity/default의
trigger 전 할당을 제거해 raw/future insert도 allocation-before-lock 순서를 우회하지 못한다.
link/refresh/stream-reconciled event는 재사용을 깨지 않는다. 재사용 cursor는 safe replay lower-bound라
consumer가 이후 event를 idempotent하게 다시 읽는다. Map은 handoff 전 75분, PinVi는 실제 수신 시 60분의
잔여수명을 각각 검사하며 부족하면 `503 + Retry-After` 또는 consumer fail-close다.
barrier lock wait 5초/statement 5분을 넘기면 single-flight를 해제하고 barrier/build별 retryable `503`으로
실패한다. server cursor의 per-FETCH timeout과 별도로 두 scan/모든 INSERT를 누적 5분 deadline으로 묶는다.

reuse miss 시 system별 미만료·미참조 generic snapshot이 2개면 세 번째 full copy를 거부한다. 가장 오래된
expiry까지 동적 `429 + Retry-After`를 반환해 유효 cursor를 삭제하지 않고 live 저장량을 stream
cardinality의 2배로 제한한다. request-bound 감사 snapshot은 admission count에서 제외한다.
단일 materialization은 100,001행에서 잘라 100,000 item 초과를 tuple/Merkle 생성 전에
`413 snapshot_item_limit_exceeded`로 거부한다. 향후 bounded streaming/material 공유는 #922로 분리했다.

hourly background drain은 전역 physical-connection try-lock, system round-robin, batch별 새 transaction,
3,300초/statement/no-progress 예산을 사용한다. exact remaining과 total/unexpired/referenced count는 종료
시 한 번만 세고 overlap skip에서는 unknown이다. 기본 1,000×2,000은 실행당 상한이므로 production enable
전에 n150에서 migration, 수동 GC, schedule ON, 다음 tick의 backlog 0 순서 확인이 필수다.
reconciliation 감사 snapshot은 terminal 상태도 보존하므로 referenced 증가율과 보존 임계치 alert를
별도로 검증한다.

**다음 한 작업**: 독립 적대적 리뷰 2건과 Map/PinVi CI를 통과시킨 뒤 exact image를 다시 빌드해 n150
격리 GC soak·isolated live UI recovery E2E와 최종 prod gate를 완료한다.
## 2026-08-01 — H35 게이트 ① 실증 완료 (CSV 재import로 공개 표면 3,265 복원)

배포 게이트를 격리 clone에서 **실제 import 경로로 재현**했다(`parse_curation_csv` →
`resolve_feature_matches` → `_adopted_match` → `import_curation_rows`, HTTP/인증만 제외):

```
배포 전 baseline (0063)          공개 노출 item  3,265
마이그레이션 직후 (0064~0074)     공개 노출 item  3,043   (-222)
CSV 재import 후                  공개 노출 item  3,265   (±0)  PASS
```

CSV 222행 전량 채택(미채택 0), `csv_explicit_feature_id` decision 222건 생성.

**이 과정에서 내가 문서에 박은 게이트 값이 틀린 것을 잡았다.** 1차 실행이 3,265로
나와 기대값 3,266에 1 모자랐는데, 그 1건은 `[빵이네] 강원도여행정보`
(`selection_origin=admin`, **`item_status='rejected'`**)였다. 공개 목록 술어는
`i.status = 'included'`를 요구하므로(`curation_repo.py:589`) **애초에 노출되지 않던
항목**이다. 즉 3,266은 "링크 수"이고 "공개 노출 수"가 아니다 — 링크 수를 게이트로
쓰면 **정상 배포에서도 FAIL**이 뜬다. 공백도 223이 아니라 **222**로 정정했다.

**다음 한 작업**: H35 배포 실행. 게이트 ①은 통과 확인됐고, 남은 확인은 n150
포화 상태(현재 T-VN-41 lane이 사용 중)와 배포 타이밍 조율이다. 배포는 비가역이라
실행 전 사용자 확인이 필요하다.
## 2026-08-01 — H40/H41 머지 완료, H35 배포 절차 확정 (B′ + CSV 재import)

PR **#918**(문서·스크립트)과 **#919**(`0073`+`0074`)를 8/8 CI green으로 머지했다
(`origin/main` = `e1afb1cf`). H40의 `0073`(source-rule provenance)과 H41의
`0074`(curation_item_id rekey CASCADE)가 모두 main에 있다.

**격리 restore clone 재측정으로 확정한 것** — prod 백업을 포트 노출 없는 임시
컨테이너에 복원하고 `0064~0074`를 적용:

- trusted link **3,266 → 3,043** (~~공백 223건~~ → **정정: 공개 공백은 222건**.
  위 2026-08-01 게이트 실증 항목 참조 — 223번째는 `rejected`라 애초에 미노출)
- H41 FK 4개 전부 `ON UPDATE CASCADE`, decision 달린 item의 PK 재작성 실제 성공

**223건 복구 경로를 코드로 확정했다.** "재import하면 붙는다"는 추론이었는데,
#907/#910이 자동 링크를 조인 탓에 안 붙을 가능성이 있었다. `_RESOLVE_FEATURES_BATCH_SQL`
첫 UNION 분기가 명시 `feature_id`로 정확히 1행을 내고 `_adopted_match`가 그것만 채택하므로,
**조인 것은 `address_hint` 단독 링크이고 명시 `feature_id` 경로는 그대로**다 → 222행 전량 복구된다.

**소요 시간 수치는 폐기했다.** 근거였던 1,754초와 이번 79.9초 모두 **dagster가 도는
상태**에서 쟀는데 실제 배포는 `h35_migrate.sh`가 dagster를 멈추고 돌린다 — 둘 다 경합을
잰 값이다. 다만 B′는 시간제한 없는 일회성 컨테이너를 쓰므로 **정확한 초수가 필요 없다.**

n150 재측정 시도는 중단했다: 그 시점 4코어 박스에 load 11.6 / iowait 44.7%였고
T-VN-41 lane이 Playwright buildx 빌드 + 라이브 스택 2벌을 **현재 사용 중**이라
(컨테이너 9개, `RestartCount=0`) 정리도 불가능했다. 내 측정 프로세스·컨테이너는 정리했다.

**다음 한 작업**: H35 배포 실행. 절차는 `docs/tasks.md`의 "확정된 최종 순서" 표 —
범위 `0064~0074`, 3(마이그레이션)과 4(`ktdctl deploy`) **사이에 CSV 재import**를 넣는다.
(중단 게이트 값은 위 게이트 실증 항목에서 **공개 노출 item = 3,265**로 정정됐다.)
## 2026-08-01 (codex) — T-VN-41 immutable DELETE/PUT receipt

`0076_cache_target_receipt`이 applied source event의 target UUID와 apply 시점 `lock_version`을 append-only
영수증으로 고정한다. DELETE exact replay는 mutable tombstone row가 사후 UPDATE돼도 이 immutable
version으로 최초 post-delete ETag를 복원한다. 0075 기존 active receipt는 outbox ETag에서, DELETE는
transaction timestamp가 일치하는 tombstone에서만 backfill하고 불확실한 drift는 migration을 중단한다.
PUT/DELETE response는 non-null UUID `target_id`/`entity_tag`와 양의 `target_sequence` DTO로 generation
4-tuple을 완성했고, GET은 identity/sequence가 nullable인 read DTO로 분리했다.

**다음 한 작업**: OpenAPI/export/types와 Alembic metadata gate를 포함한 Map 전체 검증 뒤 Map/PinVi 교차
E2E에서 응답 유실 DELETE exact retry와 후속 새 incarnation PUT의 수렴을 재확인한다.
## 2026-08-01 (codex) — T-VN-41 migration을 main 최신 head 뒤의 `0075`로 선형화

PR #917을 main에 rebase하면서 T-VN-H40/H41의 `0073_curation_source_rule`과
`0074_curation_item_rekey_cascade`를 먼저 적용하고, cache-target generation/outbox 스키마를
`0075_cache_target_outbox`로 재번호화했다. 호환용 merge revision이나 병렬 Alembic head를 만들지
않고 `0072 → 0073 → 0074 → 0075` 단일 체인을 유지한다. 새 PostGIS DB에서 전체 체인
upgrade/downgrade와 직접 경계 `0074 ↔ 0075` 왕복 검증을 통과했다.

**다음 한 작업**: 독립 적대적 리뷰어 2명이 지적한 rebase 후 PinVi provenance 재핀과
`0074 ↔ 0075` 직접 downgrade 검증을 반영하고, exact head CI와 n150 격리 live UI recovery
E2E를 다시 통과시킨 뒤 Map/PinVi PR을 순서대로 머지한다.
## 2026-08-01 — T-VN-H40 `0073` 구현 완료, T-VN-H35 배포는 여전히 대기

`0073_curation_source_rule`을 넣었다. `0072`가 공개 표면 fail-close를 넣으면서 기존
link을 전부 `legacy_unattributed`로 이관해 격리 restore clone에서 공개 노출 가능
link이 3,266 → 0이 됐는데, concierge projection 3,044건은 근거가 실재한다. `0073`이
`match_basis`에 `source_rule`을 더해 **검증 4조건을 통과한 것만** 승격하고,
`curation_items` 트리거로 앞으로 생기는 link에도 같은 근거를 붙인다. 승인 근거 판정이
공개 표면(denylist)과 merge(whitelist) 두 곳에 다른 모양으로 있던 것도
`infra/curation_link_basis.py` 한 곳으로 모아 양쪽 whitelist로 맞췄다.

**다음 한 작업**: PR #918(문서·스크립트, CI green·CLEAN)과 이 PR을 머지한 뒤,
T-VN-H35 배포를 B′ 경로로 진행한다. `0064~0073` 마이그레이션은 실측 1,754초(29분)로
`ktdctl deploy`의 하드코딩 `--wait-timeout 120`을 크게 넘으므로 마이그레이션을 배포와
분리해 돌린다. 배포 전 공개 표면 before/after exact count를 restore clone에서 다시
잰다 — 이번엔 `0073`까지 포함해서.
## 2026-08-01 (codex) — T-VN-41 restore fence stream identity 결박

restore fence의 대체 reconciliation 참조를 단일 UUID FK에서
`(external_system, superseded_reconciliation_request_id)` composite FK로 강화했다. referenced
reconciliation의 `(external_system, request_id)` unique key와 결합하므로 다른 stream의 유효한 UUID를
receipt에 넣거나 parent stream을 사후 변경할 수 없다. nullable receipt는 기존 count/UUID CHECK와
`MATCH SIMPLE`이 함께 `0/null`만 허용한다. clean migration upgrade/downgrade와 ORM metadata,
same-stream exact replay, cross-stream raw INSERT/UPDATE 거부를 PostGIS에서 검증한다.

**다음 한 작업**: Map/PinVi exact functional head를 독립 적대적 리뷰어 2명이 다시 검토하고,
두 리뷰의 P0~P2가 없을 때 exact candidate image로 n150 isolated/live recovery를 실행한다.
## 2026-08-01 (codex) — T-VN-41 restore fence receipt 상관 불변식

DB CHECK에 있던 `superseded_reconciliation_count`/request UUID 상관 불변식을 HTTP
응답 DTO에도 fail-close로 맞췄다. count `0`/UUID `null`, count `1`/UUID non-null만
허용하고 나머지 두 조합은 validation error다. OpenAPI 3.1 object-level `oneOf`도 같은
`0/null`, `1/format: uuid` branch를 기계 계약으로 고정한다. recovery operation ID는
UUID로 타입화해 임의 문자열 producer 결과가 consumer 인과관계로 전달되지 않게 했다.

**다음 한 작업**: PinVi contract pin을 새 functional owner SHA와 service OpenAPI SHA-256으로
갱신하고 producer/consumer CI와 isolated restore contract를 검증한다.
## 2026-08-01 (codex) — T-VN-41 restore fence reconciliation 교착 제거

restore fence가 active `preparing|running` reconciliation을 남겨 구 completion은 epoch 변경으로
실패하고 새 begin은 active 충돌로 실패하던 P1을 제거했다. fence transaction은 구 request를 terminal
`superseded`/`restore_fenced`로 종결하고 phase version을 올려 active slot을 비운다. preparing과
running의 snapshot/root shape는 별도 DB CHECK로 보존하고 stream별 active request는 partial unique
index로 하나만 허용한다. 구 request의 snapshot/seal/completion은 모두 명시적 conflict다.

durable fence receipt와 service 응답은 최초 claim 무효화 수, delivery 대체 수, reconciliation 대체
수와 request UUID를 노출한다. exact replay는 이 값과 epoch/control/phase version을 바꾸지 않는다.

**다음 한 작업**: 생성 service OpenAPI와 admin types를 별도 commit으로 고정하고 PinVi pin/PR CI 및
isolated restore에서 구 request 차단과 새 epoch begin을 검증한다.
## 2026-08-01 (codex) — T-VN-41 prior epoch delivery terminal supersession

restore fence가 active lease만 retry로 풀고 구 epoch pending/retry/dead를 남겨 새 epoch claim을 막던
P1을 제거했다. epoch N+1 transaction은 더 낮은 epoch의 모든 non-delivered delivery를 terminal
`superseded`로 종결하고 lease binding, `superseded_at`, version과 fence별 count를 원자 기록한다.
claim은 현재 epoch만 선택하며 old dead는 DLQ/replay/reconciliation dead gate에서 제외된다. exact fence
replay는 delivery version을 다시 올리지 않는다. ops/API/admin status는 누적 `superseded_count`를
backlog/dead와 분리해 노출한다.

**다음 한 작업**: 기능/OpenAPI/admin generated types SHA를 PinVi contract pin에 반영하고 PR CI 및
isolated restore epoch live에서 old delivery 0회 재전달과 새 epoch 도달을 검증한다.
## 2026-08-01 (codex) — T-VN-41 reconciliation receipt 인과관계 보강

Map의 `cache_target.reconciled` event payload에 reconciliation `request_id`를 필수로 추가했다.
typed payload는 request/snapshot UUID, actual/expected Merkle root, succeeded status와 contract
version 여섯 필드만 허용하며, envelope `source_payload_fingerprint`는 expected root와 같도록
integration/API/OpenAPI 회귀를 고정했다. 이제 PinVi는 request→sealed fixed snapshot→terminal
receipt 인과관계를 inbox commit에서 직접 검증할 수 있다.

admin one-step reconciliation의 operation receipt와 operation 조회에도 request-bound `snapshot_id`를
노출했다. isolated live gate는 응답 UUID가 초기 설정 snapshot과 다름을 확인하고, 최종 stream
`last_snapshot`이 바로 그 응답 UUID로 전이될 때까지 기다린다.

functional producer/schema/test/docs commit과 생성된 service OpenAPI artifact commit은 별도 SHA로
분리해 PinVi contract pin provenance가 두 경계를 각각 추적한다. paired PinVi consumer와 n150
isolated live 전까지 `T-VN-41A/B/C`와 production enable은 계속 open/off다.

**다음 한 작업**: PinVi generation 2 contract pin을 두 Map SHA와 service OpenAPI SHA-256에 맞춘 뒤
PR CI와 isolated request/snapshot receipt live를 통과시킨다.
