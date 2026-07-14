# concierge-feature-etl.md — kor-travel-concierge export pull·정규화·적재 ETL

본 문서는 `kor-travel-concierge`(YouTube/AI 여행 콘텐츠에서 추출한 장소 후보)
export를 provider로 **pull → 정규화 → 적재**하는 ETL 계약이다. 후보의 생성·
geocoding evidence·검수는 concierge가 하고, kor-travel-map은 그 export를 HTTP로
끌어와 `FeatureBundle`로 정규화하고 `feature_id`/`SourceRecord`/`SourceLink`를
만들어 PostGIS에 적재하는 **feature owner**다.

코드 정본: `src/kortravelmap/providers/kor_travel_concierge.py`.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider (canonical) | `kor-travel-concierge-youtube` |
| dataset_key | `youtube_place_candidates` |
| source_entity_type | `extracted_place_candidate` |
| Feature.kind | `place` |
| 변환 모듈 | `kortravelmap.providers.kor_travel_concierge` |
| 주 변환 함수 | `kor_travel_concierge_items_to_bundles` |
| inactive helper | `kor_travel_concierge_inactive_entity_ids` |
| Dagster resource/asset | `kor_travel_concierge_youtube_features` / `feature_place_kor_travel_concierge_youtube` |
| env prefix | `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*` |
| 로컬 체크아웃 | `F:\dev\kor-travel-concierge` |

## 2. 범위 / 책임 (경계)

- `kor-travel-concierge`: YouTube/AI 후보 추출, 검수, 외부 geocoding evidence,
  snapshot/changes export HTTP API. export 계약(스키마·cursor·operation 의미)의
  **정본은 공급(producer) 측 문서**다.
- `kor-travel-map`: export item JSON → `FeatureBundle` 순수 변환, 최종
  `feature_id`/`SourceRecord.source_record_key`/`SourceLink` 생성, PostGIS 적재,
  철회 라이프사이클(inactive 전환).
- kor-travel-map Dagster: export fetcher resource, feature DB session, (선택)
  reverse geocoder, transaction, 알림.

wrapper/adapter/gateway/client facade 금지(ADR-006). kor-travel-map에는 client
facade가 아니라 **fetcher resource + 순수 변환 함수**만 둔다. export 측 계약 누락·
불일치는 concierge에서 먼저 정렬한다(ADR-044 — 데이터 정합성 1차 책임 = 공급 측).

## 3. fetcher 경로 / 소비 계약

kor-travel-map fetcher가 소비하는 외부 경계 표면:

```
GET /api/v1/features/changes    # 기본 — ledger 재생(철회 전파 포함)
GET /api/v1/features/snapshot   # opt-in — active upsert만(철회 미전파)
```

소비 측 기대치(정본은 공급 측 문서, 본 repo는 미러만):

- 응답 envelope: `{items, has_more, next_cursor}`
- 인증 헤더: `X-API-Key`
- env: `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL`,
  `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY`
- API key: kor-travel-concierge에서 외부 소비자용으로 발급한 DB `read` scope 키. BFF/operator용
  static `API_KEYS`는 사용하지 않는다.
- export 경로에 downstream(소비자) 이름을 넣지 않는다 — 중립적
  `/api/v1/features/{snapshot,changes}`.

**endpoint 선택(2026-07-14 기본값 전환)** —
`KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_SYNC_ENDPOINT`:

- `changes`(기본): producer export ledger는 **후보당 1행**(최신 operation)으로
  압축돼 있어, cursor 없이 시작하면 전체 ledger(upsert/reject/tombstone)를
  sequence 순으로 재생한다 → full sync와 철회 전파를 한 번에 만족하며 매 실행
  멱등이다.
- `snapshot`(opt-in): **active `upsert`만** 반환한다. producer의 제거 목록/
  soft-delete(→tombstone)·검수 회수(→tombstone)가 소비되지 않아 철회된 후보가
  지도에 영구 잔존한다. 철회 전파가 무의미한 일회성 초기 적재 검증에만 쓴다.
- producer는 2026-07-14(T-171)부터 공급 GET을 순수 읽기(durable dirty outbox
  동기화)로 바꿨다 — 소비 폴링 비용이 후보 수와 무관해졌고, 응답 스키마·cursor·
  operation 계약은 불변이다.

## 4. export item → FeatureBundle 변환

export item의 기본값: `provider=kor-travel-concierge-youtube`,
`dataset_key=youtube_place_candidates`, `source_entity_type=extracted_place_candidate`.

```python
from kortravelmap.providers.kor_travel_concierge import (
    kor_travel_concierge_items_to_bundles,
)

bundles = await kor_travel_concierge_items_to_bundles(
    items,                       # export item JSON iterable
    reverse_geocoder=reverse_geocoder,   # optional (Dagster resource, 기본 None)
)
```

- `source_record.source_entity_id = str(candidate.id)` — 모든 operation에 동일하게
  보내며 후보 수명 동안 불변. 이 키가 inactive 매칭·feature_id anchoring의 기준이다.
- producer는 `place.address.{legal_dong_code,sido_code,sigungu_code}`를 **항상
  None**으로 보낸다 — bjd는 소비자(kor-travel-map)가 좌표 reverse geocoding으로
  채운다. (producer 로드맵에 place 실데이터 주입 계획이 있다 — 적용되면 전 item
  payload_hash가 재발급되며, 소비자는 재수신하면 된다.)
- Feature detail 원본 payload는 `detail.payload.kor_travel_concierge`에 저장한다.
  출처 UX가 읽는 평면 key는 계속 `detail.facility_info`를 우선한다.
- **YouTube 수집 provenance(producer 2026-06-25 확장)**: `youtube.source_type`/
  `source_value`/`source_title`/`source_search_query`/`corrected_search_query`는
  nested payload로 그대로 실리고(curated source rule이
  `{payload,kor_travel_concierge,youtube,source_title}` 등을 직접 읽음), 출처 UX용
  평면 미러 `facility_info.youtube_source_*` key로도 노출한다(값 없으면 key 생략).

## 5. operation 라이프사이클

| operation | 처리 |
|-----------|------|
| `upsert` | 즉시 `FeatureBundle`로 적재(검수 통과 후보 또는 payload 변경 후보). **기존 feature가 provider 소유 inactive면 복구(재활성화)** |
| `reject` / `tombstone` | 해당 feature **inactive 전환** — skip으로 끝내지 않음 |

- `reject`/`tombstone`을 skip-only로 처리하면 철회된 후보가 feature로 영구 잔존해
  데이터 품질을 해친다. 따라서 MOIS Step C(폐업→inactive)와 **동형**으로 inactive
  전환한다. `kor_travel_concierge_inactive_entity_ids`가 inactive 대상
  `source_entity_id`를 모은다.
- **되돌리기 재활성화(producer #202, 2026-07-14 반영)**: concierge 검수 UI의
  soft-delete/제거 목록·검수 회수(needs_review 재전환, grounding 실패 재판정)는
  `tombstone`/`reject`를, **되돌리기·재확정은 같은 후보의 `upsert` 재발행**을
  만든다. 소비 측은 이 재-upsert에서 `load_bundle`의 provider self-heal(동일
  payload fast-path·변경 payload upsert 경로 모두)로 feature를 active로 복구한다.
  `user_request` feature와 `prevent_provider_reactivation` override는 복구하지
  않는다. 회귀:
  `tests/integration/test_feature_repo_load.py::test_kor_travel_concierge_revert_*`.
- reject/tombstone item의 `rejection_reason`(검수 note)은 현재 raw_data
  (`SourceRecord.raw_data`)에만 보존된다 — inactive 전환 자체에 사유 컬럼을 쓰는
  구조화 기록은 미구현(후속 결정 필요 시 producer `rejection_reason` 소비).
- inactive 전환된 feature의 외부 경계(OpenAPI) 응답: batch/단건 read에서 `found`에
  **포함하되 status(inactive)를 노출**한다 — `missing` 처리하면 "삭제됨"과
  "철회됨"을 구분할 수 없다. 기존 admin deactivate read 정책과 동일하다.
- producer 측 export 게이트(미러): `upsert`는 검수 확정(`matched`/`user_corrected`)
  + 장소 매칭 + grounding 통과 후보만 나온다. `needs_review`로 되돌아가거나
  grounding 실패(unverified/missing)로 재판정된 기노출 후보는 `tombstone`으로
  회수된다(T-165/#202). 소비 측 분기는 operation 3종으로 불변이다.

## 6. feature_id 결정성

concierge feature_id는 안정 식별자에만 고정한다 —
`(kind=place, source_type=provider/dataset 상수, source_natural_key=candidate.id)`.
feature_id 파생에서 `bjd_code`(→`f_global_` prefix)와 `category`(고정 identity
category)를 **뺀다**. 가변 bjd·category는 식별자가 아니라 표시·공간 속성으로
in-place 갱신한다. (구 ADR-057에서 결정 — 정본 구현 `_item_to_bundle`,
`docs/adr/057-concierge-feature-id-stable-candidate-id.md`.)

## 7. Dagster

| 항목 | 값 |
|------|----|
| asset 이름 | `feature_place_kor_travel_concierge_youtube` |
| schedule | `feature_place_kor_travel_concierge_youtube_monthly_schedule` |
| resource 이름 | `kor_travel_concierge_youtube_features` |
| group | `features_place` |

`core.providers.CANONICAL_PROVIDER_NAMES`에 `kor-travel-concierge-youtube`가
등록된다.

## 8. 검증

- producer export API 배포 후 n150 live 환경에서 DB `read` 키로 snapshot/changes를 각각
  다중 page 소비하고 cursor 비반복·export ID 비중복·내부/write 403을 확인한다. fake response와
  계약 테스트는 배포 전 회귀 게이트이며 live smoke를 대체하지 않는다.
- 회귀: geocoder 유무 동일 feature_id, category None↔8자리 동일 feature_id,
  provenance 평면 key 유/무 (`tests/unit/test_providers_kor_travel_concierge.py`).
- 라이프사이클 회귀: tombstone→inactive→재-upsert 복구(동일/변경 payload)와
  `prevent_provider_reactivation` 차단
  (`tests/integration/test_feature_repo_load.py::test_kor_travel_concierge_revert_*`).
- fetcher 회귀: 기본 `changes` 소비·`snapshot` opt-in·cursor 전진
  (`packages/kor-travel-map-dagster/tests/test_provider_fetchers.py`).

## 9. 이행 노트 (clean cut)

- canonical provider name은 `kor-travel-concierge-youtube`. 구 alias나 호환 shim은
  만들지 않는다(ADR-046 정렬).
- 구 provider name으로 적재된 dev DB feature가 있으면 삭제 후 새 snapshot을 재적재
  한다. provider name이 `feature_id`/source 자연키에 들어가므로 자동 rename
  migration은 만들지 않는다.

## 10. 이관된 결정 (구 ADR)

- **(구 ADR-049)** `kor-travel-concierge` YouTube/AI 장소 후보 export를 provider로
  HTTP pull·정규화한다. `feature_id`/`SourceRecord.source_record_key`/`SourceLink`
  생성과 PostGIS 적재는 kor-travel-map 책임이고, kor-travel-map에는 client facade가
  아니라 fetcher resource + 순수 변환 함수만 둔다(ADR-006). `upsert`만 즉시 bundle로
  적재하고 `reject`/`tombstone`은 별도 상태 전이로 처리한다. 근거: concierge는 외부
  provider, kor-travel-map은 feature owner이며 full snapshot+incremental changes를
  모두 pull해 재동기화/운영 효율을 분리한다. (§2~5, 7에 통합.)
- **(구 ADR-050)** `reject`/`tombstone` operation을 skip으로 끝내지 않고 해당
  feature의 **inactive 전환(+사유 기록)**으로 처리한다(MOIS Step C와 동형). fetcher는
  `/api/v1/features/{snapshot,changes}`를 소비하고 계약 정본은 공급 측에 둔다(ADR-044).
  근거: skip-only는 철회 후보를 영구 잔존시켜 품질을 해치고, 계약 정본을 공급 측에
  두면 본 repo는 미러·소비만 해 drift가 준다. inactive read 노출 정책은 §5에 통합.
- **(구 ADR-053)** provider identity를 clean cut한다 — canonical provider name
  `kor-travel-concierge-youtube`, 변환 모듈 `kortravelmap.providers.kor_travel_concierge`,
  주 함수 `kor_travel_concierge_items_to_bundles`, inactive helper
  `kor_travel_concierge_inactive_entity_ids`, Dagster
  `kor_travel_concierge_youtube_features` 계열, env `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_*`,
  detail payload key `detail.payload.kor_travel_concierge`. 구 alias/shim 금지.
  근거: provider identity를 외부 소비자 이름에 묶으면 직접 관계 오해가 생기고,
  clean cut해야 canonical name·자연키·resource·env가 영구 호환 매핑 없이 같은
  어휘를 공유한다(ADR-046). 실데이터 적재 전 변경이라 재적재가 장기 유지비가 낮다.
  (§1, 4, 7, 9에 통합.)
  - **2026-07-13 보강**: consumer credential은 producer ADR-36의 DB `read` scope 키만
    사용한다. BFF/operator static admin 키를 공유하지 않으며, scope migration과 live read/write
    검증, BFF admin overlap 회전이 끝난 뒤 구 static 키를 제거한다.
