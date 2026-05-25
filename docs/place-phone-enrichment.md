# place-phone-enrichment.md — 장소 전화번호 보강

본 문서는 `Feature(kind=place)`의 `PlaceDetail.phones`를 Kakao Local / Naver
Search Local / Google Places Text Search(New)로 보강하는 ETL이다.

> v2 1차 범위는 **전화번호만**. 영업시간 / 홈페이지 / 리뷰 / 사진 / Google
> Places detail 추가는 별도 결정 (후속).

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| 소유 | `python-krtour-map` |
| 실행 소유 | TripMate (Dagster) 또는 admin trigger |
| 기준 코드 | `krtour.map.places`, `krtour.map.load_feature_rows` |
| Feature.kind | `place` (보강 only — 새 feature 생성 X) |
| 상세 테이블 | `feature_place_details` |
| dataset_key | `place_phone_enrichment` |
| source_role | `enrichment` |
| category | **변경 없음** — 본 ETL은 기존 `place` feature의 `phones`만 보강. `features.category`는 그대로 유지 (`docs/category.md` §4 참고). 새 feature 생성 X, 카테고리 재할당 X |

## 2. Provider endpoint

### 2.1 Kakao Local

```
GET https://dapi.kakao.com/v2/local/search/keyword.json
Headers: Authorization: KakaoAK ${KAKAO_REST_API_KEY}
Params: query, x?, y?, radius?
```

응답: `documents[].phone`. 좌표 bias (`x`, `y`, `radius` m) 권장.

### 2.2 Naver Search Local

```
GET https://openapi.naver.com/v1/search/local.json
Headers: X-Naver-Client-Id, X-Naver-Client-Secret
Params: query, display?, start?, sort?
```

응답: `items[].telephone`. **현재 항상 빈 문자열** — 하위 호환 흡수만, source로
기대 X.

### 2.3 Google Places Text Search (New)

```
POST https://places.googleapis.com/v1/places:searchText
Headers: X-Goog-Api-Key, X-Goog-FieldMask
Body: {"textQuery": ..., "locationBias": {...}}
```

Field mask 필수:
```
places.id,places.displayName,places.formattedAddress,places.location,places.nationalPhoneNumber
```

응답: `places[].nationalPhoneNumber` (한국 전화번호 표준).

API 키 없으면 searcher 생성 안 함 (graceful disable).

## 3. DTO

```python
@dataclass(frozen=True)
class PlaceSearchCandidate:
    name: str
    address: str
    coord: PlaceCoordinate | None
    phone: str | None
    
    # confidence 점수 (0-100)
    name_confidence: int
    address_confidence: int
    coord_confidence: int
    total_confidence: int                     # 가중 평균 또는 max
    
    # source trace
    provider: str                             # canonical
    raw: dict                                 # provider 원문
```

## 4. searcher Protocol

```python
class PlacePhoneSearcher(Protocol):
    provider: str                             # canonical name
    
    async def asearch(self, feature: Feature) -> list[PlaceSearchCandidate]:
        """feature 기반 (name, address, coord)로 후보 검색."""
        ...

class KakaoLocalSearcher:
    provider = "kakao-local-api"
    async def asearch(self, feature): ...

class NaverLocalSearcher:
    provider = "naver-search-api"
    async def asearch(self, feature): ...

class GooglePlacesTextSearcher:
    provider = "google-places-api-new"
    async def asearch(self, feature): ...
```

## 5. 환경변수

**비밀값은 코드/문서/fixture/DB payload에 저장 금지** (ADR-021 + ADR-018):

```
KAKAO_REST_API_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
GOOGLE_PLACES_API_KEY=...
```

`place_phone_searchers_from_env()`가 가능한 searcher만 생성:
- `KAKAO_REST_API_KEY` 있으면 `KakaoLocalSearcher`
- `NAVER_CLIENT_ID + NAVER_CLIENT_SECRET` 모두 있으면 `NaverLocalSearcher`
- `GOOGLE_PLACES_API_KEY` 있으면 `GooglePlacesTextSearcher`
- 없으면 그 provider는 skip (정상)

## 6. Resource keys

`load_feature_rows()`의 resource:

```python
@dataclass(frozen=True)
class PlaceEnrichmentResources:
    searchers: list[PlacePhoneSearcher] = field(default_factory=list)
    env: dict[str, SecretStr] | None = None          # 환경변수 override
    http_transport: Any | None = None                # httpx.AsyncClient 공유
    
    # 동작 파라미터
    min_confidence: int = 70                         # candidate 채택 임계
    max_phones: int = 3                              # PlaceDetail.phones 한도
    enrichment_version: str = "place-phone-v1"
```

## 7. 보강 흐름

```python
async def enrich_place_phones(
    feature: Feature, place_detail: PlaceDetail, *,
    searchers: list[PlacePhoneSearcher],
    min_confidence: int = 70, max_phones: int = 3,
) -> tuple[PlaceDetail, list[PlaceSearchCandidate]]:
    """기존 phones 유지하면서 보강. 최대 max_phones."""
    
    if len(place_detail.phones) >= max_phones:
        return place_detail, []
    
    # 1. 모든 searcher 동시 호출 (asyncio.gather)
    candidate_lists = await asyncio.gather(*[
        s.asearch(feature) for s in searchers
    ], return_exceptions=True)
    
    # 2. 합치고 confidence 순 정렬
    all_candidates: list[PlaceSearchCandidate] = []
    for result in candidate_lists:
        if isinstance(result, Exception):
            continue                                # 한 searcher 실패해도 진행
        all_candidates.extend(result)
    all_candidates.sort(key=lambda c: c.total_confidence, reverse=True)
    
    # 3. min_confidence 통과 + 전화번호 있음 + 중복 제거
    used_candidates = []
    new_phones = list(place_detail.phones)
    seen = set(p.replace("-", "") for p in new_phones if p)
    for c in all_candidates:
        if len(new_phones) >= max_phones: break
        if c.total_confidence < min_confidence: continue
        if not c.phone: continue
        normalized = c.phone.replace("-", "")
        if normalized in seen: continue
        new_phones.append(c.phone)
        seen.add(normalized)
        used_candidates.append(c)
    
    if not used_candidates:
        return place_detail, []
    
    # 4. PlaceDetail 갱신
    new_detail = place_detail.model_copy(update={
        "phones": new_phones,
        "payload": {
            **place_detail.payload,
            "place_phone_enrichment": {
                "version": "place-phone-v1",
                "candidates_used": [
                    {"provider": c.provider, "phone": c.phone,
                     "confidence": c.total_confidence}
                    for c in used_candidates
                ],
            },
        },
    })
    return new_detail, used_candidates
```

## 8. source trace

사용된 candidate마다 `source_records` + `source_links` 생성:

```python
for candidate in used_candidates:
    payload_hash = make_payload_hash(candidate.raw)
    source_record_key = make_source_record_key(
        provider=candidate.provider,
        dataset_key="place_phone_enrichment",
        source_entity_type="place_search_candidate",
        source_entity_id=_candidate_id(candidate),
        raw_payload_hash=payload_hash,
    )
    sr = SourceRecord(
        provider=candidate.provider,
        dataset_key="place_phone_enrichment",
        source_entity_type="place_search_candidate",
        source_entity_id=_candidate_id(candidate),
        raw_payload_hash=payload_hash,
        raw_data=candidate.raw,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    await source_repo.upsert(sr)
    
    link = SourceLink(
        feature_id=feature.feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.ENRICHMENT,
        match_method="place_phone_search",
        confidence=candidate.total_confidence,
        is_primary_source=False,
    )
    await link_repo.upsert(link)
```

**`feature_id`는 재계산 X** — provider normalize 단계에서 정해진 값을 유지
(ADR-009).

## 9. `load_feature_rows` 통합 동작

```python
await load_feature_rows(
    async_session,
    feature_items=bundles,
    source_record_items=...,
    place_phone_searchers=place_phone_searchers_from_env(),    # 또는 직접 list
    place_enrichment_resources=PlaceEnrichmentResources(
        min_confidence=70, max_phones=3,
    ),
)
```

내부:
1. feature 적재 후
2. `Feature(kind=place)` 각각에 대해 기존 `PlaceDetail.phones` 검사
3. < `max_phones`이면 searcher 호출 + 보강
4. 사용된 candidate → `source_records(dataset_key="place_phone_enrichment")`
5. 연결 → `source_links(source_role="enrichment")`
6. `PlaceDetail.payload.place_phone_enrichment` 요약 저장

## 10. confidence 점수 계산

```python
def _calc_confidence(feature: Feature, candidate: PlaceSearchCandidate) -> int:
    # name 유사도 (jaro_winkler, 0-100)
    name_score = int(jellyfish.jaro_winkler_similarity(
        normalize_kr_place_name(feature.name),
        normalize_kr_place_name(candidate.name),
    ) * 100)
    
    # address 유사도
    address_score = _address_similarity(feature.address, candidate.address)
    
    # 좌표 거리 (m → 점수, 100m 이내 100점)
    coord_score = 0
    if feature.coord and candidate.coord:
        dist_m = _haversine_m(feature.coord, candidate.coord)
        coord_score = int(max(0, 100 - dist_m / 10))    # 1000m=0점, 100m=90점
    
    # 가중 평균 (이름 0.5, 주소 0.3, 좌표 0.2)
    total = int(0.5 * name_score + 0.3 * address_score + 0.2 * coord_score)
    return total
```

## 11. Dagster

| 항목 | 값 |
|------|----|
| 적재 방식 | on-demand (admin trigger) 또는 일 1회 batch |
| asset 이름 | `feature_place_phone_enrichment` |
| suggested cron | 일 1회 또는 수동 |
| group | `features_quality` |
| ConcurrencyConfig | `kakao_local: 2`, `naver_search: 2`, `google_places: 1` |

호출량 제한 (Google Places는 호출당 비용 발생):
- `min_confidence=70` 기본 → 노이즈 후보 거름
- batch 단위로 N place씩 (예: 100개)
- 이미 `phones` 채워진 place는 skip

## 12. 검증

### fixture (≥ 3)

- `kakao_local_response.json` — Kakao 응답 (좌표 bias)
- `naver_search_response.json` — Naver 응답 (telephone 빈 값)
- `google_places_response.json` — Google Places (nationalPhoneNumber)
- `enrichment_skipped_already_3_phones.json` — 이미 3개 있어 skip
- `enrichment_low_confidence.json` — min_confidence 미달 candidate

### 통합 테스트

- `place_phone_searchers_from_env()` env 분기
- 동일 feature 2회 호출 → idempotent (같은 candidate 중복 추가 X)
- 한 searcher 실패해도 다른 searcher 진행 (`return_exceptions=True`)
- `source_links(role=enrichment)` 정확히 candidates_used 수만큼

## 13. 후속 확장 (보류)

- 영업시간 보강 (Google Places `regularOpeningHours.periods` →
  `FeatureOpeningHours`)
- 홈페이지 보강 (Kakao `place_url`, Google `websiteUri`)
- 리뷰 링크 (Naver/Kakao 가게 페이지)
- Google Places 상세 (rating, photo) — 별도 API 비용 평가 후
- 보강 비용 모니터링 (Google Places 호출당 비용)

각 확장은 별도 ADR + PR.

## 14. 비밀값 보호

```
✗ fixture JSON: API key 평문 저장 금지 (자동 마스킹)
✗ DB payload: API key 평문 저장 금지
✗ 로그: API key 평문 출력 금지 (SecretStr로 보호)
✗ git commit: .env 절대 commit X
✓ vault / systemd EnvironmentFile / TripMate secret manager 사용
```
