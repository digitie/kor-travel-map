# ADR-061: kor-travel-concierge YouTube 그룹핑을 curated 테마 source로 삼는다

### 상태

Accepted (2026-07-08) — 사용자 결정. 큐레이션 관리를 concierge와 정합화(#15).

### 배경

kor-travel-map은 이미 kor-travel-concierge의 YouTube 장소 후보를 provider
`kor-travel-concierge-youtube`(dataset `youtube_place_candidates`)로 feature에
적재하고, 0031이 시드한 단일 curated_source + rule로 이를 하나의 `media-places`
테마에 후보화한다. 각 feature는 `detail.payload.kor_travel_concierge.youtube`에
channel/playlist/keyword provenance(id + title)를 이미 담고 있으나, 이 그룹핑은
`display_title` 라벨로만 소비되고 **테마 멤버십**으로는 쓰이지 않았다.

문제: `curated_source_rules`는 place_kind/category/region_scope로만 필터하고
`_APPLY_RULE_SQL`이 `theme_id = rule.theme_id`를 하드코딩해, **하나의 source가 정확히
하나의 테마로만** 팬아웃된다. concierge의 채널/재생목록을 개별 테마로 만들 수 없다.

### 결정

- `curated_source_rules`에 nullable jsonb **`detail_selector`** 추가(0042). rule이
  `{"path": [...], "value": ...}`로 "feature.detail의 특정 path 값이 value와 일치하는
  feature만"을 지정할 수 있게 하고, `_APPLY_RULE_SQL`에 `f.detail #>> path = value`
  술어를 추가한다. → 하나의 source를 detail 값별로 **여러 테마에 팬아웃**(한 rule = 한
  테마, partition은 detail_selector가 담당).
- 별도 concierge API 호출 없이, 이미 적재된 concierge feature의 detail youtube
  값에서 그룹핑을 유도한다(`sync_concierge_themes`). 그룹핑(channel/playlist)마다
  slug `concierge-yt-<channel_id>`/`concierge-pl-<playlist_id>`, `theme_group='media'`,
  `visibility='public'`, `default_curated=true` 테마 1개 + 그 그룹핑만 고르는
  detail_selector rule 1개(`default_action='curated'` — **auto-publish**)를 upsert하고
  apply로 후보를 즉시 채운다. 멱등(재실행 시 rule 중복 생성 없음).
- 트리거는 **on-demand**다: Dagster `concierge_theme_sync` asset을 수동 materialize.
  `curated_features_refresh` 일일 스케줄은 여전히 STOPPED(자동 켜지 않음).
- apply 술어 지원용 concierge youtube channel_id/playlist_id **부분 표현식 인덱스**
  (해당 feature만 대상 → 작고 빠름).

### 결과 / 트레이드오프

- 같은 물리 feature가 여러 채널/재생목록에 속하면 curated_features 행이 여러 개 생긴다
  (정상 — UNIQUE는 (theme_id, feature_id)). 지도 경로는 ADR 없이 `distinct_by_feature`
  (curated cross-theme dedup)로 물리 feature당 마커 1개만 그린다.
- keyword(자유 문자열 검색어) 그룹핑은 slug churn·프로리퍼레이션 위험이 커 초기 범위에서
  제외한다(channel + playlist만). 필요 시 후속에서 확장.
- concierge `/themes`에 change-feed가 없어, 사라진 그룹핑의 stale 테마는 남는다. 프룬은
  후속 과제.
