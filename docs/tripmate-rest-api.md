# TripMate 소비용 krtour-map REST API 매핑

> **상태**: 2026-06-12, ADR-048 / T-216a~g + curated_features 문서 계약 기준.
> **역할**: 이 문서는 TripMate가 어떤 krtour-map API를 소비하는지 정리하는 view다.
> 전 표면 REST 계약의 단일 정본은 [`docs/rest-api.md`](rest-api.md)이고, 기계 정본은
> `packages/krtour-map-admin/openapi.user.json` / `openapi.json`이다. 충돌 시 OpenAPI를 우선한다.

## 1. 연결 원칙

- TripMate는 krtour-map DB에 직접 접근하지 않고, `python-krtour-map`을 운영 코드에서 직접
  import하지 않는다(ADR-045).
- `TRIPMATE_KRTOUR_MAP_API_BASE_URL`은 host root까지만 포함한다.
  예: `http://127.0.0.1:9011`.
- `/v1`는 base URL이 아니라 path에 둔다.
  예: `GET {base}/v1/features/search`.
- 호환성은 고려하지 않는다. pre-1.0 단계에서는 `/v1` clean cut으로 정리하고, 구 unprefixed
  경로와 alias는 유지하지 않는다(ADR-048).
- `KRTOUR_MAP_ADMIN_SERVICE_TOKEN`이 설정된 환경에서는 service read `POST /v1/features/batch`
  호출에 `X-Krtour-Service-Token`을 붙인다. (`/tripmate/*` namespace는 제거됐다 — krtour-map은
  TripMate 전용이 아니다.)

## 2. TripMate 소비 표면

| TripMate 기능 | krtour-map API | 비고 |
|---------------|----------------|------|
| 지도 viewport | `GET /v1/features/in-bounds` | bbox + optional cluster |
| 주변 feature | `GET /v1/features/nearby` | cursor paging |
| POI target 주변 | `GET /v1/features/nearby/by-target` | target write는 admin/operator flow |
| feature 상세 | `GET /v1/features/{feature_id}` | `feature_id`는 opaque string |
| trip view batch | `POST /v1/features/batch` | service read, `ServiceToken` 적용 대상 |
| 검색 | `GET /v1/features/search` | `bbox`는 분리 4-float |
| 날씨 카드 | `GET /v1/features/{feature_id}/weather` | `forecast_style`별 grouping |
| 카테고리 | `GET /v1/categories` | 긴 TTL 캐시 가능 |
| provider 신선도 | `GET /v1/providers/{provider}/last-sync` | 사용자 표시 또는 admin 상태판 |
| 운영 feature 추가/수정/삭제 | `/v1/admin/features*` | TripMate public client 직접 호출 금지 |
| 운영 refresh 실행 | `/v1/admin/feature-update-requests*` | admin/operator flow만 |
| 비로그인 공개 해수욕장/축제 뷰 | `GET /v1/public/*` 후보 | T-130용 제안 사양. 아직 OpenAPI 미포함 |
| 테마형 curated trip plan import | `GET /v1/curated-features*` 후보 | `curated_features` → TripMate `curated_trip_plans` 1:1 복사. 아직 OpenAPI 미포함 |

`/tripmate/feature-update-requests*`는 제거됐다. 사용자가 새 장소 추가, 정보 수정, 폐업 삭제를
제안하는 큐는 TripMate app DB가 소유하고, 운영자 승인 뒤 `/v1/admin/features*` 또는
`/v1/admin/feature-update-requests*`로 전달한다.

## 3. 응답 계약 요약

성공 응답은 항상 `{data, meta}`다. `meta.request_id`는 모든 성공 응답에 존재한다.

```json
{
  "data": {
    "items": []
  },
  "meta": {
    "duration_ms": 12,
    "request_id": "01J...",
    "page": {
      "page_size": 100,
      "next_cursor": null,
      "total": null
    }
  }
}
```

목록의 `items`는 항상 배열이다. Batch 조회처럼 id-keyed map이 필요한 응답은 `items`를 쓰지 않고
`found`를 쓴다.

```json
{
  "data": {
    "found": {
      "f_1111014700_p_019c0211c8a5ec4e": {}
    },
    "missing": []
  },
  "meta": {
    "duration_ms": 12,
    "request_id": "01J..."
  }
}
```

`GET /v1/features/in-bounds`에서 clustering을 적용하면 payload는 `data.clusters[]` /
`data.items[]`이고, 적용된 granularity는 `meta.cluster.cluster_unit`에 둔다.

```json
{
  "data": {
    "clusters": [],
    "items": []
  },
  "meta": {
    "duration_ms": 8,
    "request_id": "01J...",
    "cluster": {
      "cluster_unit": "sigungu"
    }
  }
}
```

## 4. 에러 계약

오류는 RFC 7807 `application/problem+json`을 쓴다. `code`와 `request_id`는 top-level 확장
멤버다.

```json
{
  "type": "https://krtour-map/errors/feature-not-found",
  "title": "Feature not found",
  "status": 404,
  "detail": "feature 없음",
  "code": "FEATURE_NOT_FOUND",
  "request_id": "01J...",
  "errors": []
}
```

표준 코드는 `docs/rest-api.md` §4를 따른다.

## 5. 필드 불변식

- `feature_id`는 UUID가 아니라 opaque string이며, TripMate는 파싱하지 않고 그대로 저장한다.
- `feature_id` 값은 provider 재적재, 사용자 수정, version 승급, soft delete에도 바뀌지 않는다.
  정체성이 바뀌는 사건은 새 feature + link로 모델링한다.
- 좌표 필드명은 `lon`/`lat`가 cross-repo 정본이다. TripMate DEC-07도 이쪽으로 정렬한다.
- `cluster_key`는 행정구역 자연키(sido/sigungu/eupmyeondong 코드)이므로 유지한다.
- 시스템 surrogate 식별자는 `*_id`, 자연키/복합키는 `*_key`를 쓴다.

## 6. TripMate 후속

- **T-181**: `/v1` hard cutover lockstep, problem+json 파싱, `page_size`/`max_items`/bbox
  4-float, `meta.page.next_cursor`, batch `data.found` 반영.
- **T-182**: TripMate DEC-07 좌표명을 `lon`/`lat`로 하향 정렬.
- **T-210e** ✅(2026-06-11): krtour-map에 `packages/krtour-map-user-client/`
  (`@krtour/map-user-client`) — `openapi.user.json` 생성 TS 타입 + named alias +
  ADR-048 표면 단언 + CI drift gate. TripMate frontend는 vendoring 또는 같은
  openapi-typescript 버전 자체 codegen으로 pin(패키지 README 참조).

## 7. 사용자 제안 연동 합의 (ADR-051, 확정 2026-06-11 — T-217c)

TripMate 사용자 feature 추가/수정/삭제 제안의 전송 구간은 **기존
`/v1/admin/features*` change API**다(신규 suggestions API 없음, ADR-051). TripMate
admin 1차 승인 → 본 API 호출 → krtour-map `change-requests` 큐 최종 반영의 2단 검토.
TripMate 측 질의 5건(해당 repo `docs/integrations/krtour-map-rest-api.md` §7)의 확정:

| # | 항목 | 확정 |
|---|---|---|
| 1 | review_mode | 기본 **`require_review`** 유지(krtour-map 최종 반영 권한 보존). 운영 합의 시 `KRTOUR_MAP_ADMIN_FEATURE_CHANGE_REVIEW_MODE=immediate`(전역) |
| 2 | idempotency_key | `feature_id` 미지정 create에서 **결정적 feature_id** 생성(`make_feature_id(source_type="user_request", source_natural_key=idempotency_key)`) — 같은 key 재시도=같은 feature_id. **`idempotency_key=suggestion_id` 권장** |
| 3 | 출처 태깅 | 전용 필드 없음 — **`operator: "tripmate-admin"` + `reason` 머리 `[suggestion:<id>]` prefix** 컨벤션. change-requests 큐가 reason을 표시하므로 출처 식별 가능(D-11 익명 — 사용자 개인정보 비전송) |
| 4 | admin 인증 | admin API는 **9011 `/v1/admin/*`**(9012는 admin UI). 코드 게이트는 `admin_destructive_enabled` kill-switch, 호출자 인증은 인프라 계층(SSO/IP allowlist, ADR-005) |
| 5 | closure | 영구 폐업/사용자 삭제 = **soft `DELETE`**(`user_deleted_*`, provider 재적재 부활 차단) / 일시 중단 = `POST .../deactivate`(`status='inactive'`) |

inactive/soft-deleted feature는 **batch/단건 read의 `found`에 status와 함께 반환**된다
(D-12, T-217b) — `missing`(미존재)과 "철회/폐업됨"을 구분하라.

## 8. curated_features → curated_trip_plans import 계약 (문서 계약, 2026-06-12)

테마형 source(세계음식점, 독립서점, 카페가 있는 서점, 도서관, 무장애 관광지 등)는
krtour-map `feature.curated_features` overlay가 소유한다. TripMate의 저장 정본명은
`app.curated_trip_plans` / `app.curated_plan_pois`다. TripMate API의 `/notice-plans`
또는 `notice_plan_id`는 기존 호환 alias일 뿐이며, 신규 DB/ORM/문서에서는
`curated_trip_plans`를 쓴다.

제안 엔드포인트와 상세 payload는 [`docs/curated-features.md`](curated-features.md)를
따른다.

- `GET /v1/curated-themes`
- `GET /v1/curated-sources`
- `GET /v1/curated-features`
- `GET /v1/curated-features/{curated_feature_id}`
- `GET /v1/curated-features/{curated_feature_id}/tripmate-copy`

복사 규칙:

- krtour-map `curated_features` 1건 = TripMate `curated_trip_plans` 1건.
- 하위 장소·정류점·추천 POI는 TripMate `curated_plan_pois`로 복사한다.
- TripMate는 `source_system='krtour-map'`,
  `source_curated_feature_id`, `source_curated_feature_version`, `source_etag`,
  `source_imported_at`을 저장한다.
- TripMate는 krtour-map DB를 직접 읽지 않고 REST payload snapshot만 저장한다.
- `feature_id`는 opaque string으로 저장하고 파싱하지 않는다.

## 9. YouTube 후보 feature detail 소비 계약 (T-217f — TripMate TM-08 선행)

provider `tripmate-agent-youtube`(marker `P-13`, kind `place`,
`detail.place_kind="youtube_place_candidate"`) feature의 출처 배지/영상 카드 UX는
**`detail.facility_info`만 읽으면 된다** (평면 key, 값 없으면 key 자체 부재):

| key | 의미 |
|---|---|
| `youtube_video_id` / `youtube_video_url` / `youtube_video_title` | 출처 영상 |
| `youtube_channel_id` / `youtube_channel_title` | 채널 |
| `youtube_playlist_id` / `youtube_playlist_title` | 플레이리스트(있을 때) |
| `timestamp_start` / `timestamp_end` | 영상 내 언급 구간 (`"HH:MM:SS"`) |
| `transcript_excerpt` | 자막 발췌 |
| `gemini_url_evidence` | Gemini URL 분석 근거 |
| `confidence_score` | **0~100 정수** 신뢰도(소스 매칭 confidence와 동일 정규화) |
| `description` / `gemini_enriched_description` / `category_label` | 설명/카테고리 라벨 |

원본 export item 전체는 `detail.payload.tripmate_agent.{youtube,evidence,...}`에
보존된다(디버그/확장용 — UX는 facility_info 우선). export는 검수 통과 후보만
내려오므로(D-05) 별도 검수 상태 분기는 불필요하다.

## 10. T-130 공개 해수욕장/축제 뷰 (제안 사양)

TripMate T-130(`/public/*`)은 비로그인 공개 API이며, 현재 차단 조건은 krtour-map
사용자 OpenAPI에 해수욕장/축제 전용 뷰와 닫힌 detail 스키마가 없다는 점이다. krtour-map
쪽 제안 사양은 [`docs/public-views-api.md`](public-views-api.md)에 둔다.

제안 엔드포인트:

- `GET /v1/public/beaches`
- `GET /v1/public/beaches/map-markers`
- `GET /v1/public/beaches/{feature_id}`
- `GET /v1/public/festivals/monthly`
- `GET /v1/public/festivals/map-markers`
- `GET /v1/public/festivals/{feature_id}`

구현 전 주의:

- 해수욕장은 `detail.place_kind="beach"`를 1차 판별 기준으로 쓴다. 문서의
  `01050100`과 현재 provider 코드의 `01020300` category drift는 T-222에서 정리한다.
- KHOA 수질/index는 weather metric 확장 또는 별도 marine 표면 중 하나로 확정해야 한다.
- 축제 monthly 뷰는 `EventDetail.starts_on`/`ends_on` 기간 겹침 집계가 필요하다.
