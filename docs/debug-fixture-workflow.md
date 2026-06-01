# debug-fixture-workflow.md — fixture 저장 / replay 워크플로

본 문서는 `tests/fixtures/`의 fixture 기반 회귀 워크플로다. provider API 응답
녹화 + 변환 + replay로, **외부 API 호출 없이** provider별 변환 함수 회귀를
지속 검증한다.

## 1. 목적

- provider API 응답을 한 번 녹화하면 향후 변환 함수 회귀를 무한 검증.
- 외부 API 호출 없음 — CI에서 빠르고 안정.
- provider schema drift 발견 (payload_hash 변동) 시 회귀 즉시 인지.
- 새 provider 추가 시 최소 3개 fixture (정상/엣지/실패) 의무 (ADR-014).

## 2. fixture 디렉토리

```
tests/fixtures/
  visitkorea/
    festival_full_scan_seoul_2026_05.json
    festival_full_scan_empty_response.json
    festival_full_scan_missing_image.json
  mois/
    license_promoted_restaurant.json
    license_excluded_billiards.json
    license_closed_status.json
  krheritage/
    heritage_place_national_treasure.json
    heritage_area_with_boundary.json
    heritage_event_monthly.json
  kma/
    short_forecast_typical.json
    short_forecast_sky_change.json
    ultra_short_nowcast.json
  opinet/
    station_detail_typical.json
    station_detail_no_phone.json
  khoa/
    oceans_beach_info_donghae.json
    oceans_beach_info_no_image.json
  krforest/
    recreation_forest_typical.json
    trail_with_linestring.json
    mountain_weather_typical.json
  krex/
    rest_area_with_fuel_and_weather.json
    traffic_notice_road_closure.json
  standard_data/
    tourism_road_accessible.json
    museum_typical.json
    parking_lot_typical.json
  notice/
    kma_heavy_rain_warning.json
    khoa_coastal_isolation_warning.json
  place_phone_enrichment/
    kakao_local_response.json
    naver_search_response.json
    google_places_response.json
```

`tests/fixtures/<provider_short>/<function>_<case>.json` 패턴.

## 3. fixture JSON 스키마

```json
{
  "name": "festival_full_scan_seoul_2026_05",
  "function": "visitkorea.festival_to_bundles",
  "description": "VisitKorea 축제 정상 케이스 — 2026년 5월 서울 5건",
  
  "input": {
    "params": {
      "areaCode": "1",
      "eventStartDate": "20260501",
      "numOfRows": 50,
      "pageNo": 1
    }
  },
  
  "request": {
    "method": "GET",
    "url": "http://apis.data.go.kr/B551011/KorService2/searchFestival",
    "headers": {
      "Accept": "application/json",
      "serviceKey": "<REDACTED>"
    }
  },
  
  "response": {
    "status": 200,
    "headers": {"Content-Type": "application/json"},
    "body": {
      "response": {
        "header": {"resultCode": "0000", "resultMsg": "OK"},
        "body": {
          "items": {"item": [
            {"contentid": "12345", "title": "한강 봄꽃축제", ...}
          ]},
          "numOfRows": 50, "pageNo": 1, "totalCount": 5
        }
      }
    }
  },
  
  "parsed": [
    /* provider 라이브러리가 typed model로 파싱한 결과 (참고용) */
  ],
  
  "processed": [
    /* 변환 함수 결과 — FeatureBundle list dump
       기본은 핵심 필드만 (전체는 너무 큼) */
    {
      "feature": {
        "feature_id": "f_1111000000_e_abc1234567890123",
        "kind": "event",
        "name": "한강 봄꽃축제",
        "category": "01030200",
        "coord": null,
        "marker_icon": "star", "marker_color": "P-11",
        "status": "active"
      },
      "detail": {
        "event_kind": "festival",
        "starts_on": "2026-05-01",
        "ends_on": "2026-05-15",
        "content_id": "12345"
      },
      "source_record": {
        "provider": "python-visitkorea-api",
        "dataset_key": "visitkorea_festival_events",
        "source_entity_type": "festival",
        "source_entity_id": "12345",
        "raw_payload_hash": "abc..."
      },
      "source_link": {
        "source_role": "primary",
        "match_method": "natural_key",
        "confidence": 100,
        "is_primary_source": true
      },
      "file_sources": [
        {"source_url": "http://..../image.jpg", "role": "primary", "display_order": 0}
      ]
    }
  ],
  
  "assertion": {
    "type": "snapshot",
    "fields": [
      "feature.feature_id",
      "feature.kind",
      "feature.name",
      "feature.coord",
      "feature.category",
      "detail.event_kind",
      "detail.starts_on",
      "detail.ends_on",
      "source_record.raw_payload_hash",
      "source_link.source_role",
      "file_sources[*].source_url",
      "file_sources[*].role"
    ]
  },
  
  "meta": {
    "captured_at": "2026-05-21T10:00:00+09:00",
    "captured_by": "claude",
    "redactions": ["serviceKey", "api_key", "Authorization"],
    "provider_library_version": "python-visitkorea-api@<sha>",
    "notes": "totalCount=5인 정상 응답"
  }
}
```

`processed`는 변환 결과의 **expected snapshot**. assertion이 snapshot이면
runner가 actual ↔ expected를 dict 비교.

## 4. 민감정보 마스킹 (자동)

fixture 저장 helper(`tests/fixtures_helper.py`)가 다음 키를 자동 마스킹:

```python
SENSITIVE_KEYS = {
    # provider API 키
    "api_key", "apiKey", "service_key", "serviceKey", "ServiceKey",
    "Authorization", "X-Goog-Api-Key",
    # 플랫폼 키
    "X-Naver-Client-Id", "X-Naver-Client-Secret",
    "KakaoAK",
    # 기타
    "secret", "Secret", "password", "Password", "token", "Token",
}

def mask_sensitive(obj):
    if isinstance(obj, dict):
        return {k: ("<REDACTED>" if k in SENSITIVE_KEYS else mask_sensitive(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_sensitive(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 20 and obj.isalnum():
        # 길이 + alphanumeric → API key 가능성 → 부분 마스킹
        # (단, 일반 ID와 구분 어려움 → 보수적: 자동 마스킹 안 함)
        return obj
    return obj
```

URL 쿼리스트링의 `serviceKey=` 도 자동 마스킹:
```python
import re
def mask_query_string(url: str) -> str:
    return re.sub(r"(serviceKey|api_key|apiKey)=([^&]+)", r"\1=<REDACTED>", url)
```

## 5. fixture 저장 (녹화)

라이브러리는 fixture 저장 helper를 제공한다 (디버그 모드에서):

```python
# tests/fixtures_helper.py
from krtour.map.providers import visitkorea
from krtour.map.fixtures import save_fixture, mask_sensitive

async def capture_festival_fixture():
    visitkorea_client = AsyncVisitKoreaClient(service_key=os.environ["VISITKOREA_SERVICE_KEY"])
    
    params = {"areaCode": "1", "eventStartDate": "20260501", "numOfRows": 50}
    
    # 1. provider 호출 + raw response 저장
    raw = await visitkorea_client.raw_search_festival(**params)  # provider lib helper
    
    # 2. 변환
    items = visitkorea_client.parse_festival_response(raw)
    bundles = list(visitkorea.festival_to_bundles(items, fetched_at=kst_now()))
    
    # 3. fixture dump (마스킹 자동)
    save_fixture(
        path="tests/fixtures/visitkorea/festival_full_scan_seoul_2026_05.json",
        name="festival_full_scan_seoul_2026_05",
        function="visitkorea.festival_to_bundles",
        description="VisitKorea 축제 정상 케이스 — 2026년 5월 서울 5건",
        input={"params": params},
        request={"method": "GET", "url": raw.url, "headers": mask_sensitive(raw.headers)},
        response={"status": raw.status, "headers": dict(raw.headers), "body": raw.json()},
        processed=[b.model_dump(mode="json") for b in bundles],
        assertion={"type": "snapshot", "fields": _default_snapshot_fields(bundles)},
        meta={"captured_at": kst_now().isoformat(), "captured_by": "claude",
              "redactions": ["serviceKey"]},
    )

asyncio.run(capture_festival_fixture())
```

녹화는 사람/에이전트가 수동으로 (외부 API 호출이 필요하므로 CI에서 자동 안 함).
새 케이스 발견 시 1회 녹화 → 영구 회귀.

## 6. fixture replay (회귀 테스트)

```python
# tests/fixtures/conftest.py
import json
from pathlib import Path
import pytest
from krtour.map.fixtures import load_fixture, replay_fixture, RUNNERS

def _discover_fixtures(provider: str | None = None) -> list[Path]:
    root = Path("tests/fixtures")
    paths = root.rglob("*.json") if provider is None else (root / provider).glob("*.json")
    return sorted(paths)

@pytest.fixture(params=_discover_fixtures())
def fixture_path(request):
    return request.param

@pytest.mark.fixture_replay
def test_fixture_replay(fixture_path):
    fixture = load_fixture(fixture_path)
    runner = RUNNERS[fixture.function]
    actual = runner(fixture.input)
    replay_fixture(fixture, actual)
```

`RUNNERS`는 함수 dispatch dict:

```python
# krtour.map.fixtures
RUNNERS = {
    "visitkorea.festival_to_bundles": _run_visitkorea_festival,
    "mois.license_record_to_bundle": _run_mois_license,
    "opinet.station_detail_to_bundle": _run_opinet_station,
    # ...
}

def _run_visitkorea_festival(input_: dict) -> list[dict]:
    from krtour.map.providers.visitkorea import festival_to_bundles
    # fixture의 response.body에서 items 추출 → typed model 재구성 → 변환
    items = _items_from_fixture_response(input_)
    bundles = list(festival_to_bundles(items, fetched_at=kst_now()))
    return [b.model_dump(mode="json") for b in bundles]
```

## 7. assertion 타입

| type | 의미 |
|------|------|
| `snapshot` | actual ↔ expected dict 전체 비교 (특정 fields만 비교 가능) |
| `schema_only` | expected의 schema만 확인 (실제 값은 무시 — 결정성 낮은 timestamp 등) |
| `required_fields` | expected에 있는 필드는 actual에 모두 존재 (extra는 허용) |
| `count` | bundle 개수만 비교 |
| `equal_keys` | dict의 key set이 같음 |

```python
def _assert_snapshot(actual: list[dict], expected: list[dict], fields: list[str]):
    """JSONPath-like field 선택 후 비교."""
    for a, e in zip(actual, expected, strict=True):
        for field in fields:
            assert _extract(a, field) == _extract(e, field), \
                f"mismatch at {field}: actual={_extract(a, field)} expected={_extract(e, field)}"
```

## 8. payload_hash 변동 = schema drift 시그널

fixture의 `source_record.raw_payload_hash`가 변동하면 provider response schema
변경 가능성. CI가 자동 감지:

```python
@pytest.mark.fixture_replay
def test_payload_hash_stable(fixture_path):
    fixture = load_fixture(fixture_path)
    runner = RUNNERS[fixture.function]
    actual = runner(fixture.input)
    
    # response body를 변경 없이 재계산 → 동일 해시여야 함
    for actual_bundle, expected_bundle in zip(actual, fixture.processed, strict=True):
        a_hash = actual_bundle["source_record"]["raw_payload_hash"]
        e_hash = expected_bundle["source_record"]["raw_payload_hash"]
        assert a_hash == e_hash, (
            f"raw_payload_hash drift detected!\n"
            f"  fixture: {fixture_path}\n"
            f"  expected: {e_hash}\n"
            f"  actual:   {a_hash}\n"
            f"  Possible cause: provider response schema changed, or "
            f"canonical_json() ordering changed."
        )
```

drift 발견 시:
1. provider 라이브러리 변경 확인
2. provider response가 실제로 바뀐 거면 fixture를 새로 녹화 (새 PR)
3. 변환 함수가 추가 필드를 처리하도록 변경 필요한지 판단

## 9. 시나리오 매트릭스 (provider별 최소 3개)

| 케이스 종류 | 예시 |
|------------|------|
| 정상 | typical 응답 |
| 엣지 — 빈 필드 | 좌표 없음, 주소 없음, 전화 없음 |
| 엣지 — 다중 | image 2개 이상, sibling 형성 가능 |
| 엣지 — 경계값 | 좌표 한국 영역 밖 (validation 검증), 날짜 미래/과거 극단 |
| 엣지 — UTF-8 | 특수문자, 한글-한자 혼합 (특히 행사 제목) |
| 실패 — 필수 필드 누락 | ValidationError 발생 |
| 실패 — schema drift | raw_payload_hash 변경 → 새 source_record |
| 폐업/취소 | MOIS: 영업중 아님 (excluded) |
| 제외 업종 | MOIS: 미용실 / PC방 / 동물병원 |

테스트 marker:
```python
@pytest.mark.fixture_replay
@pytest.mark.parametrize("fixture_path", _discover_fixtures("visitkorea"))
def test_visitkorea_all_fixtures(fixture_path):
    ...
```

## 10. fixture 갱신 (provider response 변경 대응)

1. 변동 감지 (fixture replay CI 실패)
2. 사람이 변경 분석:
   - provider 라이브러리 typed model이 변경되었나?
   - response schema가 실제로 변경되었나?
   - 본 라이브러리 변환 함수가 적응해야 하나?
3. 변환 함수 수정 + 새 fixture 녹화
4. PR (ADR-021)
5. 회귀 추적: 같은 함수의 **기존 fixture도 통과해야 함** (역방향 호환)

## 11. 디버그 UI에서 fixture 저장 (옵션)

`krtour.map_admin`의 `/debug/fixtures` 엔드포인트:

```
POST /debug/fixtures
  body: {
    "provider": "visitkorea",
    "function": "festival_to_bundles",
    "case_name": "festival_full_scan_seoul_2026_05",
    "input": {...}
  }
  → live API 호출 + 변환 + fixture 저장 → 저장 경로 반환
```

운영자가 admin에서 trigger. 인증 없음 (ADR-005), 내부망만.

## 12. fixture 디렉토리 위치

- `tests/fixtures/`: 코드 작성 단계에서 ext4 (소량, git 포함).
- 대용량 (예: 전국 적재 검증용 100k row 응답)은 NTFS `data/fixtures/` (git 제외)
  + 회귀 테스트에서 환경변수 path로 참조.

## 13. provider별 capture 책임자

| provider | 최초 fixture 작성자 | 갱신 책임 |
|----------|------------------|----------|
| visitkorea | 본 라이브러리 PR | 본 라이브러리 PR |
| mois | 본 라이브러리 PR | 본 라이브러리 PR |
| (모든 provider) | 본 라이브러리 PR | 본 라이브러리 PR |

provider 라이브러리(`python-*-api`)는 자체적으로 typed model 테스트만 갖는다.
본 라이브러리는 그 위에서 "본 라이브러리 변환 함수의 회귀"를 검증.

## 14. 운영 체크리스트

- [ ] 모든 provider 변환 함수 ≥ 3 fixture (정상/엣지/실패)
- [ ] 모든 fixture에 `redactions` meta 명시
- [ ] CI `pytest tests/fixtures -q` 통과
- [ ] payload_hash 회귀 테스트 활성
- [ ] 새 provider 추가 PR 검토 시 fixture 3개 확인 (PR template Verification
      체크리스트)

## 15. fixture 작성 안티패턴 (PR 차단)

| 안티패턴 | 대안 |
|---------|------|
| `Authorization` / `serviceKey` 평문 저장 | 자동 마스킹 강제 |
| fixture 1개만 (정상만) | 최소 3개 |
| `assertion: snapshot` + fields 미지정 → 전체 비교 | 결정성 낮은 필드(`created_at`, UUID) 제외 |
| fixture 안에 시간 의존 (`now()` 기반) | `fetched_at`을 fixture에 박은 고정 시각 사용 |
| provider 응답 통째로 fixture에 → 큰 JSON | 핵심만 추출 (응답 5건이면 충분) |
| 같은 fixture 여러 함수에서 공유 | 함수별로 별도 fixture (디스커버리 단순) |

## 16. v1 fixture 이식 (코드 작성 단계)

v1의 `tests/fixtures/` 디렉토리가 있다면 (v1 브랜치 참고):

1. 디렉토리 구조 유지 (`<provider>/<function>_<case>.json`)
2. payload_hash는 v2에서 재계산 → 새 값으로 갱신
3. assertion fields는 v2 DTO 필드명에 맞춰 수정
4. `processed` snapshot은 v2 변환 함수로 재생성
5. 새 PR로 일괄 이식 + replay 통과 확인
