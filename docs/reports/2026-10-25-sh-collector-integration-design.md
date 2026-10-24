# A4 실제 수집기의 제한 SH 연결 설계

2026-10-25. 기준 source는 A3 d47639e0f51a2539c8edcf02c52aa6ff5263f7ec다.
이 문서는 구현 전 계약 초안이며 제품/DDL/시험/운영 변경0이다. 두 설계 리뷰 전에 SH 코드를
수정하지 않는다. A3의 정확 CI/UI와 이후 이 설계의 코드·운영 수용을 대신하지 않는다.
[ADR-115](../adr/115-scoped-concurrent-feature-writes.md)의 T-CWRITE-04와
[A3 EX 한정 연결](2026-10-24-exclusive-provider-full-refresh.md)의 후속이다.

root/J의 별도 읽기 메모와 위 source를 대조했다. 기존 writer inventory를 재작성하지 않고
새로 필요한 최소 경계와 필수 반례를 정리한다. 본문은 작성 시점 설계이며 이후 정확 SHA별
리뷰·실험 수용은 PR 본문/감사 원장을 참조한다.

## 가장 작은 구현과 단계 분리

첫 PR은 국가유산 한 scope의 실제 SDK 최종 snapshot에 대해 **전량 기존 canonical primary
place/같은 정책 revision/name-only/지원 외 불변**일 때만 SH를 선택하는 wrapper다. 기본값은
지금의 EX 경로이고 자동 활성화0이다. 별도 provider의 적격성 구현과 실제 두 dataset DML
중첩은 두 번째 수용 단위다. 국가유산 종목 코드만 나눈 두 입력은 같은 dataset이므로 병렬
성과로 세지 않는다. MCST에 Heritage A1을 그대로 적용하지 않는다.

최소 구현 파일 후보는 새 infra SH full-snapshot 모듈, client의 명시 Options routing,
국가유산 진단 호출의 현재 DB evidence 준비, 좁은 SQL 검증/동일 Geo stamp 재관측 entry,
전용 PG/실제 asset 시험이다. 아직 migration 번호를 할당하지 않는다. 기존 scalar single/batch의
공개 계약과 unsupported 거부를 유지한다. 기존 A3 EX guard를 SH에 통째로 개방하지 않는다.
Settings/실제 worker flag의 새 전파는 첫 wrapper 수용 뒤 별도 작은 범위로 결정한다.

최종 fetch/Geo/converter 뒤 load 호출에서 동적 준비하며, 상위 transaction-bound client는
계속 거부한다. pool1에서 짧은 planning TX→fresh RC apply→기존 sync 성공→별도 SERIALIZABLE
child receipt→root completion을 유지한다. 지원 외를 발견하면 SH DML 이전에 전체 EX로 다시
계획하거나 명시 reject한다. apply 중 stale/owner/epoch/timeout/23514이면 전체 rollback이며
그 TX에서 SH→EX 승격이나 일부 commit은 없다. root 정책이 허용한 bounded fresh retry만 별도다.

## 실제 두 제공자의 최소 의미 차이

| 제공자와 실제 경로 | 첫 SH 허용 범위 | 허용하지 않는 주장 |
| --- | --- | --- |
| Heritage `heritage_items_to_bundles`→`run_feature_place_krheritage_items`→tracked asset | 고정 composite identity의 기존 place, 이름만 달라지고 파생 category/marker/Geo/파일 등 불변 | 종목 두 개를 서로 다른 dataset으로 취급하지 않음 |
| MCST `file_rows_to_bundles`→`run_feature_place_mcst_culture`→multi-member asset | 먼저 `world_restaurants_csv` 한 실제 slug의 동일 이름·주소/key인 반복 입력 | 이름변경은 같은 identity의 scalar 갱신이 아님 |

`providers/mcst.py`의 `_build_bundle`은 `natural_key = "::".join([name, raw_address or ""])`를
source_entity_id와 파생 Feature alias의 근거로 쓴다. `mcst-name-v1`의 presence가 있어도 이름이
바뀌면 identity도 바뀐다. 안정 ID를 임의 추가하거나 이름변경을 Heritage처럼 승인하지 않는다.
MCST 최소 지원은 원 raw/이름/주소/key/타입·Geo 불변인 반복 수집이며 source 재관측·동일 winner와
stamp/capture의 실제 DML을 수행하는 경우다. 사용자에게 보이는 이름변경 성공의 증거는 아니다.
이름/주소 변화는 첫 SH DML 전에 부적격이며 정본 EX의 신규 identity 의미를 유지한다.

MCST 별도 적격성은 실제 public provider의 CSV typed row와 정본 converter를 사용해 raw key 전수,
미지 필드/과대 입력/normalizer evidence를 fail-closed 검증해야 한다. Heritage validator에
provider 문자열만 바꾼 facade는 만들지 않는다. fixture는 기존 `test_providers_mcst.py`의
world restaurant row와 actual FileDataClient/CSV HTTP대역으로 시작하고 외부 네트워크는0이다.
국가유산과 `mcst_world_restaurants_csv`는 실제 다른 dataset이지만, participant/head/Feature가
실제로 독립임을 별도 확인한 경우에만 DML 중첩 기대가 성립한다.

MCST는 `mcst_features.py`의 별도 multi-member asset이다. `ensure_tracked_multi_member_asset`의
frozen exact memberships, 시도 slug 표식, 실패 slug의 sync-success 금지, 전체 정상 결과 수와
완료 membership 수 일치 검증을 보존한다. 일반 `run_tracked_feature_asset`으로 바꿔 끼우지 않는다.
한 slug fixture가13개 dataset 전체 성공을 의미하지 않고, 실패한 slug를 빈 authoritative 성공으로
봉인하지 않는다. 각 실제 load의 RC capture와 후속 별도 SERIALIZABLE membership receipt/root를
원래 호출자로 검증한다. Heritage의 기존 provider_run_lock 미사용 사실과 pool1 호환 시험도 구분한다.

## 입력과 현재 DB 증거의 결합

A1은 pure 진단이고 collector_ready=False다. 현재 raw를 오늘 converter revision으로 다시
변환했다고 해서 과거 revision의 정본 증거가 생기지 않는다. 현재 source head/정확 record,
정책에 저장된 normalizer revision과 supplied field evidence, canonical UUID/primary link/claim,
현재 typed projection, 현재 Geo stamp를 한 planning 응답으로 읽고 증거 hash를 묶는다.
이 증거가 불완전하면 SH 불가다. A1의 감사 clock/파생 alias 제외는 그대로 적용하되 claim은
DB에서 재검증한다. 이름 파생 category/marker/주소/image alt 변화, source link identity,
kind/parent/lifecycle/expiry/admin evidence 변화는 SH 불가다. file_sources는 첫 SH에서는 빈 값만
허용한다. 기존 legacy 미소비 사실을 업로드 성공으로 바꾸지 않는다.

전체 입력은 A3처럼 원순서와 실제 Geo 사용/토큰·retire 옵션·scope·정책 선택을 바인딩한다.
과거와 현재 stamp/normalizer evidence도 같은 입력 domain에 포함해 claim의 immutable input_digest와
결합한다. 이는 stamp를 manifest의 가짜 source_head로 위장하는 방식이 아니다. canonical 순서는
잠금/closure에만 쓴다. 2730/MAX+1/합계1MiB/depth64, 실제 2N+모든 관련 distinct head <=8192,
32 participant 등 기존 상한을 늘리지 않는다. 5000개 일반 fetch와 chunk commit은 후속이다.

planning은 protocol SH+policy epoch SH를 먼저 잡는 별도 경로여야 한다. A3 prepare의
lock_feature_curation_write(EX)를 재사용하면 앞 SH apply와 다음 planning을 직렬화하므로
SH collector의 DB 중첩 목표를 달성하지 못한다. 같은 dataset owner/anchor 직렬화는 유지한다.
모든 current/head/claim/evidence 조회는 bounded bulk이고 N개별 왕복을 만들지 않는다.

## Geo stamp는 없어도 되는 부수 효과가 아니다

현행 feature_geocode_stamp_repo.py:110–118은 동일 token/outcome에도 stamped_at을 갱신한다.
features의 BEFORE UPDATE revision은 stamp-only 변경을 추적하지 않는다. 따라서 planning의
기존 stamp 전체 비교값(Feature ID/version/data/outcome/stamped_at)을 bounded evidence로 보관한다.
apply는 kernel의 dataset→source/head→link→Feature 순서 뒤 canonical UUID순으로 **기존 stamp
행을 FOR UPDATE**하고 그 전체 증거를 재검증한다. missing stamp는 SH에서 새로 생성하지 않는다.
변경/누락/다중관측 token/Geo outcome 변화는 첫 source DML 이전에 거부한다.

A3 _419 guard는 feature_geocode_stamps를 일반 SH에서23514로 막는다. 단순 EX predicate 제거는
불가하다. 새 좁은 SD entry만 현재 applying SH+sameTX+owner/epoch+완전 target/source manifest를
확인하고, 기존 stamp의 ID/token/outcome이 동일하며 새 관측 시각만 바뀌는 원자 update를 허용하는
방식이 최소 후보다. 기존 private context를 무조건 bool 확장하거나 session.info/prefix를 권한으로
삼지 않는다. runtime의 임의 core/base/Geo 변경과 직접 stamp DML은 계속 거부한다. 정본 active
projection/source 검증은 유지한다. 이 SQL 허용 방식은 두 SQL 설계 리뷰 후 확정한다.

새 관측 stamped_at은 같은 apply TX의 source→candidate→winner와 함께 commit하고 결과 지문에
묶는다. 완료 replay는 현재 capture+target revision+stamp를 재구성해 저장 지문과 맞는 때만
source/candidate/winner/stamp/finish DML을 생략한다. 과거 insert/update 숫자는 복원하지 않는다.
현재 stamp를 옛 성공에 붙이거나 stamp를 생략한 batch dict를 FeatureLoadResult로 포장하지 않는다.

## retire 0과 capture/receipt

정본 feature_repo.py:4061 retire_geometryless_area_features_by_source는 대상이0이어도 먼저
EX helper를 호출한다. SH에서 이 함수를 그냥 호출하면 승격 거부다. 반환 입력이 모두 place라고
retired=0을 추정하지 않는다. SQL의 정본 geometryless active area+feature_areas 부재+primary link+
provider/dataset/entity type predicate를 dataset 전체에 대해 planning과 apply에서 동일하게 확인하는
좁은 SD 0대상 검증이 필요하다. apply는 dataset anchor와 epoch/gate 아래 재검증해 compliant writer를
배제한다. 한 건이라도 있으면 SH 적용 전에 EX 경로다. shared entity의 active place+area는 퇴역
여부와 무관하게 계속 reject하고 별도 entity area retire 성공과 구분한다.

같은 RC TX에서 source/candidate/winner/stamp 적용→실제 full provider count/hash capture→attempt
finish를 수행한다. subset attempt receipt와 full capture, 후속 SERIALIZABLE semantic receipt는
서로 다른 증거다. full digest/capture/stamp 결과를 domain으로 묶는다. wrapper가 자기 plan을
소유하므로 A3의 실패/취소 bounded cancel과 짧은 caller cap·lease 한계를 그대로 적용한다.

### Geo 관측 증거와 기존 semantic seal의 한계

정본 `current_provider_curation_input_set`은 Geo stamp를 포함하지 않는다. A3의
`_read_target_state`는 attempt의 완료/replay 지문에만 stamp를 결합한다. 이를 반환한
FeatureLoadResult의 count/hash와 후속 SERIALIZABLE child/root receipt가 stamp까지 검증한다고
주장하지 않는다. typed curation/row_revision이 그대로인 stamped_at 또는 token-only 변화는
기존 child/root seal에서 검출된다는 보장이 없다. token/outcome/typed 주소 변화와 단순 동일
Geo의 재관측 시간 변화도 서로 다르다.

가장 작은 A4는 기존 seal의 범위를 유지하면서 SH apply의 같은 TX에서 stamp 재관측을 원자
commit하고, **attempt replay 시** stamp 변경을 거부하는 계약이다. capture 뒤 stamp-only 변화가
있어도 후속 child/root가 반드시 실패해야 한다는 새 요구를 이 PR에 암묵적으로 넣지 않는다.
그 강한 요구가 필요하면 원 run/input/attempt와 결합한 별도 Geo 증거의 영속 전달·fresh
SERIALIZABLE 재검증·receipt domain 확장을 독립 설계하고, 현재 count/hash를 재명명해 위장하지
않는다. A4 수용 원장에서도 source/typed curation receipt와 attempt Geo 관측 범위를 나눠 쓴다.

## 실제 운영 DML 병행의 별도 차단층

packages/kor-travel-map-dagster/src/kortravelmap/dagster/assets.py:195/218과 docker/dagster.yaml:56–57은
GEO_HEAVY_POOL=kor_travel_map.kor_travel_geo, default_limit1/granularity run을 명시한다. 국가유산과
MCST의 해당 asset들은 같은 pool을 선언한다. 따라서 SDK/asset 함수를 격리 fixture에서 동시에
호출해도 운영 Dagster run 두 개가 함께 DML에 진입한다고 결론내릴 수 없다. queue 경로는 원본
runner를 직접 호출해 이 pool을 우회한다는 문서 경계도 별도다. 실제 plane의 override는 여기서
조회하지 않았다.

첫 wrapper PR에서는 이 Geo 보호 pool을 바꾸지 않는다. 먼저 실제 두 dataset의 DB write 구간
중첩을 real converter/client/tracking fixture로 증명하고, Geo 요청 구간과 DB 구간을 분리하는
worker 설계/Geo capacity 수용을 후속 결정한다. Geo pool 자체를 무조건2로 늘리는 것은 이 설계의
승인이 아니며 운영 변경0이다. Weather/Transport 전파도 이후 각 실제 병목/실패 반례를 기준으로 한다.

## 구현 전에 확정할 필수 반례

| 경계 | 실제 입증과 기대 |
| --- | --- |
| DB 현재 증거 | 옛 head/normalizer 불명/claim·link·membership·epoch 교체는 첫 DML 전 stale/EX |
| Geo | missing stamp, stamp-only 갱신, token/outcome/주소 중 하나 변경을 별도 세션 commit 후 재검증 실패 |
| 동일 Geo | 실제 source DML과 stamp stamped_at 재관측이 한 TX, 2번째 stamp 실패 시 전부 rollback |
| retire | 입력 밖 별도 area1이면 EX, same entity는 reject, dataset 전체0일 때만 SH retired0 |
| 범위/상한 | raw/분류/파일/관리증거/부모/kind 변화와 2731/1MiB초과/실manifest8193은 source·stamp·receipt0 |
| replay | A→B→옛A completed와 새plan을 각각 검사, capture/stamp 변경 뒤 거짓 완료 금지 |
| 취소/회복 | 두 번째 source/stamp DML 실패, 반복 취소, 실제 process kill→전체 rollback+동일artifact fresh retry |
| 잠금 | 실제 두 독립 dataset의 첫 source DML 뒤 commit 전 barrier; 서로 다른 PID/xid, 정확 SH, global EX 없음 |
| 충돌 | 같은 dataset 직렬화, shared Feature 충돌, old EX 양방향 차단/승격23514/55P03 rollback |
| tracked 경로 | public SDK HTTP대역+real converter/client/actual asset/tracking, RC capture→별도 SERIALIZABLE child/root |
| 기본 OFF | 선택 없음은 추가 planning SQL0/정본 기존 결과, A3 EX fallback 동등 |
| worker | 실제 Geo pool/worker scheduling·ARM CPU/WAL/RSS 수용을 DB fixture 성과와 분리 |

첫 PR은 Heritage 한 scope의 정확성을 먼저 닫고, 두 번째 제공자의 독립 진단·실제 DML overlap과
worker scheduling 수용을 별도 미완으로 둔다. 실제 두 번째 adapter를 fake dataset으로 대체하지 않는다.
최종A3 CI/UI 수용을 먼저 진행하며 본 문서는 코드진행 허가나 전체 동시쓰기 완료 판정이 아니다.


## 권장 작은 PR 순서와 수용 종료 조건

1. 현재 문서 PR: Heritage·MCST identity 차이, stamp/retire/capture/worker 경계와 반례를
   두 명이 독립 검토한다. 문서 수용은 구현 수용이 아니며 전체 T 체크는 그대로 둔다.
2. Heritage 제한 SH wrapper: 실제 SDK/Geo 최종 입력의 현재 DB evidence→SH 계획/apply→
   stamp 재관측→capture→후속 receipt를 actual PG/asset으로 닫는다. 같은 dataset 직렬화는 유지한다.
3. MCST 반복 입력 지원: 별도 정상화/현재 evidence 비교와 multi-member 계약 보존을 수용한다.
   실제 독립 두 dataset에서 첫 DML 후 미커밋 barrier를 동시에 관측하고 같은 winner·capture/
   후속 receipt 및 실패 원자성을 확인한다. raw scalar 두 세션 실험과 구분한다.
4. worker·배포 전 수용: Geo pool의 현재 보호 목적과 source/Geo/DB 단계별 병목, 실제 worker
   종료/복구·ARM CPU/RSS/WAL·빈 집합/급감 guard를 확인한다. 승인 없이 pool/정책/운영값을 켜지 않는다.

현재 이 문서는 위 1의 초안이며 2~4의 구현·실측은0이다. UI는 실제 화면 흐름만 UI로 기록하고
직접 helper/API 호출은 실제 PG/HTTP 증거로 분리한다. Weather/Transport는 Map 수용 뒤 각 저장소의
실제 수집 경로/정책/병목에 맞는 후속이며 취소된 export 활성화/Map 연동 운영 작업을 재개하지 않는다.
