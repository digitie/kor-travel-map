# ADR-083: 비파생 UUIDv7 정본 generator와 응답 feature_id 값 전환

- 상태: accepted
- 날짜: 2026-08-05
- 결정자: human, AI agent

## 컨텍스트

ADR-068이 UUID 정본 identity로의 전환 골격(경계 alias 해석·backfill·rollout
순서 "PinVi 선전환 → checksum 일치 → 응답 전환")을 세웠고, T-VN-32A/B가 0080
결정적 backfill(uuid5 파생, 731,600행)과 dual read/write를 착지시켰다. 값
전환 직전 시점에 남은 결정은 세 가지였다: ① 신규 행의 정본 UUID generator를
파생(uuid5)으로 유지할지 비파생으로 전환할지, ② 파생 등식을 강제하던 DB
CHECK(0080/0081)와 소비자(PinVi) 검증 계약을 어떻게 개정할지, ③ 응답
`feature_id` 값을 UUID로 바꿀 때 어느 표면이 치환이고 어느 표면이 echo인지.

파생 generator를 유지하면 legacy id와 UUID가 영구 결합되어 T-VN-39(legacy
물리 제거)가 성립하지 않고, alias table이 "재계산 가능한 캐시"로 오독된다.
반면 비파생 전환은 "행별 파생 등식"에 걸려 있던 DB CHECK·PinVi 계약·alias-map
검증을 함께 개정해야 한다.

## 결정

1. **신규 행 정본 generator는 비파생 UUIDv7이다** (RFC 9562). app 정본은
   `kortravelmap.core.ids.make_feature_uuid()`, raw SQL 경로 안전망은 동일
   레이아웃의 `feature.uuid_generate_v7()`(0083)이며 fill 트리거가 이것을
   쓴다 — app/SQL generator 이원화를 금지한다. v7의 시간 정렬성은 내부
   인덱스 지역성 용도이며 **API 계약이 아니다**(feature_id·feature_uuid는
   opaque string).
2. **기존 731,600행(backfill 세대)의 파생 uuid는 영구 보존**한다(0082
   identity fence). 파생 함수(`feature_uuid_from_legacy` /
   `feature.feature_uuid_from_legacy`)는 역사 참조 전용으로 격하하고
   제거하지 않는다.
3. **사본 일치는 선언적으로 보장한다**: 파생 CHECK 2종(0080/0081)을 해제하는
   대신 `uq_features_identity_pair` UNIQUE + `fk_feature_aliases_identity_pair`
   복합 FK(ON DELETE CASCADE)가 `alias.feature_uuid == features.feature_uuid`
   사본 일치를 DB 계약으로 고정한다(0083).
   `count_features_missing_identity` 4축(uuid 결측·alias 결측·쌍 불일치·orphan
   alias) 관측이 replica-mode 우회의 보상 방어선이다.
4. **alias-map 소비 계약 개정**: 행별 uuid5 파생 등식은 계약에서 제거하고
   검증 = canonical shape + closed alias_kind + merkle root 대조로 한다.
   양 저장소 공용 golden(`contracts/feature-alias-map-v1-golden.json`)에
   `nonderived_v1` 벡터를 추가해 회귀 앵커로 고정한다. checksum 응답의
   `derivation_enforced: false`가 세대 표식이다.
5. **응답 값 전환(PR-2)은 read 표면 단일 원자 릴리스**다: projection에
   `feature_uuid`를 병행 select하고 응답 조립 경계에서만 `feature_id` 값에
   UUID를 대입한다(`kortravelmap.api.identity_projection`, 결측 fail-close).
   내부 join·keyset cursor·FK는 legacy 축을 유지한다.
6. **echo 예외(요청 표기 보존)**: batch found/missing 키·item `feature_id`
   **와 그 안의 `trip_card.feature_id`(item echo와 동일 값 — PinVi가 등식을
   런타임 강제)**, weather batch target echo, path-param echo(404 메시지 등),
   CSV import의 `requested_feature_id`, 감사 레코드(merge outcome·override·
   change request), operator raw lineage(sources/observations), 2차 참조
   (parent_feature_id·sibling_group_id)는 치환하지 않는다. 명문은
   integration-map.md §3.2와 `identity_projection` 모듈 docstring.
   **명시 결정(설계 초안과의 차이)**: 단건
   `GET /features/{id}/weather/forecast`의 `target_feature_id`는 echo가
   아니라 **해석된 target 표현**이므로 UUID 정본으로 치환한다 — 설계 문서
   §4 표의 "target echo 요청 보존"은 weather **batch** target에 한정한다
   (PinVi는 forecast 표면을 소비하지 않음을 실측).
7. **write/scope 입력은 경계 해석이 의무다**: 값 전환 후 클라이언트가 응답
   UUID를 body/scope로 되돌리므로, 모든 feature 참조 입력은 legacy 정본
   키로 해석(bulk 포함)하고, 신규 legacy id 발급 입력(admin create
   feature_id)은 UUID 표기를 422로 거부한다. UUID 타입 입력 컬럼
   (sibling_group_id)은 feature UUID 충돌 가드를 둔다.

## 근거

- 비파생 generator만이 identity와 파생 규칙을 분리해 T-VN-39(legacy 제거)의
  전제를 만든다 — alias table이 유일한 해석 경로라는 ADR-068의 원칙을
  실질화한다.
- 파생 CHECK 해제의 보안 공백은 절차적 보장(트리거)이 아니라 선언적
  제약(UNIQUE+복합 FK)으로 메꾼다 — `session_replication_role=replica` 우회
  창구를 DB 계약 층에서 좁힌다.
- 치환/echo 이분법은 "응답 identity는 UUID 정본, 소비자 상호작용 키는 요청
  표기"라는 단일 규칙으로, PinVi echo 등식 검증(런타임 강제 중)과 keyset
  안정성(cursor legacy 축)을 동시에 지킨다.

## 결과

- 0083 prod 적용 완료(2026-08-05): PinVi 쌍 PR(#430) 선배포 → Map api →
  dagster 순. 사전·사후 점검 쿼리 0/0, `derivation_enforced: false` 실측.
- PR-2 배포 시 curated detail snapshot은 빌더 UUID화에 따라 다음
  `curated_feature_detail_snapshots` asset 런에서 일제 재물질화된다(etag
  churn 1회는 계획 비용).
- PinVi user 스냅샷 재추출·핀 회전은 값 전환 배포 후 PinVi 재고정 PR에서
  수행한다(service 표면 무변경 — config 상수 회전 불요).
- 유예: PinVi CLI `--accept-uuid-literals`·`derivation_enforced` cutover 사전
  검사 배선, dagster entrypoint 기계 인터록(EXPECTED_HEAD 게이트 부재 보완).
