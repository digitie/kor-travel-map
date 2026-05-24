# 장소 전화번호 보강

Kakao Local, Naver Search Local, Google Places API Text Search(New)를 feature 보강 source로 사용해
`feature_place_details.phones`를 채운다. 현재 구현 범위는 전화번호 추가만이다. 영업시간, 홈페이지,
리뷰 링크, 사진, Google place detail 확장은 별도 결정 후 같은 문서와 코드에 이어서 추가한다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| 소유 | `python-krtour-map` |
| 실행 소유 | TripMate Dagster/resource |
| 기준 코드 | `krtour_map.places`, `krtour_map.db.load_feature_rows` |
| `Feature.kind` | `place` |
| 상세 테이블 | `feature_place_details` |
| source trace | `source_records`, `source_links(source_role="enrichment")` |

## Provider 계약

이 기능은 provider 원문을 앱 모델로 바로 쓰지 않는다. 검색 결과 candidate를
`PlaceSearchCandidate`로 정리한 뒤, 이름/주소/좌표 기반 confidence가 기준 이상이고 전화번호가
있을 때만 `PlaceDetail.phones`에 추가한다.

- Kakao Local keyword search: `GET https://dapi.kakao.com/v2/local/search/keyword.json`
  - header: `Authorization: KakaoAK ${KAKAO_REST_API_KEY}`
  - 전화번호 필드: `documents[].phone`
  - 좌표가 있는 feature는 `x`, `y`, `radius`로 위치 bias를 준다.
- Naver Search local: `GET https://openapi.naver.com/v1/search/local.json`
  - header: `X-Naver-Client-Id`, `X-Naver-Client-Secret`
  - 공식 문서상 `telephone`은 하위 호환용 빈 요소다. 값이 오면 흡수하지만 전화번호 source로
    기대하지 않는다.
- Google Places Text Search(New): `POST https://places.googleapis.com/v1/places:searchText`
  - header: `X-Goog-Api-Key`, `X-Goog-FieldMask`
  - field mask에는 `places.nationalPhoneNumber` 또는 `places.internationalPhoneNumber`를
    명시해야 한다.
  - Google 키가 없으면 searcher를 만들지 않는다.

공식 문서:

- Kakao Local keyword search: <https://developers.kakao.com/docs/latest/ko/local/dev-guide#search-by-keyword>
- Naver Search local: <https://developers.naver.com/docs/serviceapi/search/local/local.md>
- Google Places Text Search(New): <https://developers.google.com/maps/documentation/places/web-service/text-search>

## 설정

비밀값은 코드, 문서, fixture, DB payload에 저장하지 않는다. TripMate는 Dagster resource 또는 환경
변수로 searcher를 구성한다.

```bash
KAKAO_REST_API_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
GOOGLE_PLACES_API_KEY=...
```

`place_phone_searchers_from_env()`는 위 값을 읽어 가능한 searcher만 만든다. Naver는 Client ID와
Secret이 모두 있어야 활성화된다. Google은 아직 키가 없으면 비활성 상태가 정상이다.

직접 resource로 넘길 수도 있다.

```python
from krtour_map import load_feature_rows, place_phone_searchers_from_env

searchers = place_phone_searchers_from_env()

load_feature_rows(
    session,
    feature_items=features,
    place_detail_items=place_details,
    place_phone_searchers=searchers,
)
```

또는 `place_enrichment_resource`에 다음 키를 둘 수 있다.

- `place_phone_searchers`
- `place_searchers`
- `place_enrichment_env`
- `place_http_transport`
- `kakao_rest_api_key`
- `naver_client_id`
- `naver_client_secret`
- `google_places_api_key`

## DB 적재 동작

`load_feature_rows()`는 `place_phone_searchers` 또는 `place_enrichment_resource`가 있을 때만
전화번호 보강을 수행한다.

1. `Feature(kind="place")`와 기존 `PlaceDetail`을 feature_id로 매칭한다.
2. searcher가 반환한 candidate를 confidence 순으로 정렬한다.
3. 기존 전화번호와 중복되지 않고 `min_confidence` 기준을 통과한 전화번호만 최대 3개까지 추가한다.
4. 사용된 candidate는 `source_records(provider=..., dataset_key="place_phone_enrichment")`로
   남긴다.
5. feature와 source row의 연결은 `source_links(source_role="enrichment")`로 남긴다.
6. 적용 요약은 `PlaceDetail.payload.place_phone_enrichment`에 저장한다.

전화번호 보강은 feature_id를 다시 계산하지 않는다. provider 검색 결과가 불확실하거나 전화번호가
없으면 기존 `PlaceDetail`을 그대로 둔다.
