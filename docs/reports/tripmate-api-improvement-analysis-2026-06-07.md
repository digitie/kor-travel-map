# TripMate 연계 REST API 분석 및 엔드포인트 개선 제안 — 2026-06-07

본 보고서는 ADR-045 독자 프로그램 운영 모델에 따라 TripMate ↔ krtour-map 간에 OpenAPI(HTTP)로 노출되는 REST API 목록을 정리하고, 시스템의 **일관성(Consistency)**, **확장성(Extensibility)**, **유지보수성(Maintainability)** 관점에서 발견된 문제점 및 구체적인 엔드포인트 수정 제안을 담고 있습니다.

---

## 1. TripMate 노출 REST API 목록 정리

현재 `packages/krtour-map-admin/openapi.user.json` (TripMate 전용 OpenAPI Subset) 및 관련 명세(`docs/tripmate-rest-api.md`)를 기준으로 노출되는 API 목록은 다음과 같습니다.

### 공통 규약
*   **좌표계**: WGS84 (EPSG:4326), 직렬화 순서는 항상 **`lon, lat`** (경도, 위도) 형식을 준수합니다.
*   **성공 응답 Envelope**: 
    ```json
    {
      "data": <payload>,
      "meta": { "duration_ms": <처리시간_ms>, ... }
    }
    ```
*   **에러 응답 Envelope**: 
    ```json
    {
      "error": {
        "code": "ERROR_CODE",
        "message": "사용자 친화적인 메시지",
        "request_id": "uuid",
        "details": {}
      }
    }
    ```

### API 목록

| HTTP Method | Path | 설명 (기능 및 스펙) |
| :--- | :--- | :--- |
| **GET** | `/health` | 서비스 Liveness Probe (DB 등의 의존성 없이 항상 정적 `200 OK` 반환) |
| **GET** | `/version` | 배포 프로그램(admin), 메인 라이브러리(`krtour-map`)의 버전 및 커밋 해시 반환 |
| **GET** | `/categories` | `PlaceCategory` 정적 카탈로그(144건) 및 선택적인 현재 DB 내 적재 feature 수 반환 |
| **GET** | `/features/in-bounds` | bbox 범위 내 feature 경량 목록 및 시도/시군구/읍면동 단위 행정구역 클러스터 집계(rollup) 반환 |
| **GET** | `/features/{feature_id}` | 특정 feature의 정제된 상세 정보 (Pydantic DTO 기반) |
| **GET** | `/features/{feature_id}/weather` | 해당 feature 영역에 매칭되는 기상청(KMA) forecast_style별 최신 기상 예보 정보 반환 |
| **GET** | `/features/search` | 이름(pg_trgm 유사도) 및 공간 bbox 기반 keyset pagination 검색 |
| **GET** | `/features/nearby` | 특정 좌표(lon, lat) 기준 반경 `radius_m` 내 feature 목록 조회 (정렬: 거리순/이름순/최신갱신순) |
| **GET** | `/features/nearby/by-target` | 등록된 외부 POI(cache target) 고유 키 기준 반경 내 feature 목록 조회 |
| **GET** | `/providers/{provider}/last-sync` | 특정 provider(예: `python-mois-api`)의 데이터셋별 마지막 수집 성공/실패 시각 반환 |
| **POST** | `/tripmate/features/batch` | 여러 feature_id에 대한 batch 상세 정보 조회 (N+1 조회 문제 방지용, 한도 200건) |
| **POST** | `/tripmate/feature-update-requests` | 특정 범위/좌표/시군구/provider 대상 즉시 데이터 적재(refresh) 요청을 큐에 등록 |
| **GET** | `/tripmate/feature-update-requests/{request_id}` | 데이터 적재 요청의 진행 상태 및 Dagster run 매핑 상태 확인 |

> [!NOTE]
> **외부 POI 등록 및 연동 관련 (어드민 API)**
> TripMate는 지도 POI 동기화를 위해 아래의 API들을 호출하도록 설계에 반영되어 있으나, 현재 `/admin` prefix로 묶여 있어 TripMate 전용 스펙인 `openapi.user.json`에서는 누락되어 있습니다.
> *   `PUT /admin/poi-cache-targets/{external_system}/{target_key}`
> *   `DELETE /admin/poi-cache-targets/{external_system}/{target_key}`

---

## 2. 설계 분석 및 엔드포인트 수정 제안

일관성, 확장성, 유지보수성을 감안했을 때, 다음과 같은 지점에서 엔드포인트 개선 및 수정이 권장됩니다.

### ① POI Cache Target API의 Prefix 및 User Spec 누락
> [!IMPORTANT]
> **유지보수성 및 보안 측면의 핵심 개선 과제**

*   **현상 및 문제점**:
    *   TripMate가 호출해야 하는 POI 동기화용 `PUT`/`DELETE` 메서드가 `/admin` prefix로 묶여 있어, `openapi.user.json`의 `USER_OPERATIONS` 필터에서 **제외**되어 있습니다.
    *   이로 인해 TripMate 측에서 OpenAPI 클라이언트를 자동 생성(codegen)하면 동기화 메서드가 누락되며, 이를 해결하기 위해 전체 어드민 스펙(`openapi.json`)을 노출하면 내부 백업/복원 등 민감한 내부 API가 외부 통신 표면에 함께 노출되어 보안 경계가 모호해집니다.
*   **개선 제안**: TripMate가 호출할 수 있는 전용 경로를 `/tripmate/` prefix 하에 노출하고, 이를 `openapi.user.json`에 편입시킵니다.
    *   `PUT /tripmate/poi-cache-targets/{external_system}/{target_key}`
    *   `DELETE /tripmate/poi-cache-targets/{external_system}/{target_key}`

### ② `GET /features` (Bbox 조회)의 비일관적인 응답 셰입
> [!WARNING]
> **API 설계의 일관성(Consistency) 저해**

*   **현상 및 문제점**: `GET /features` 엔드포인트는 어드민 UI(legacy)와의 호환성 문제로 성공 응답 시 `{count, items}` 형태의 bare JSON을 반환합니다. 다른 모든 TripMate API들이 성공 응답을 `{data, meta}` envelope 형태로 감싸서 반환하는 단일 표준(DA-D-03)을 따르는 것과 일치하지 않아 혼란을 줍니다.
*   **개선 제안**: bare 응답을 반환하는 기존 `GET /features`를 `/admin/features/legacy-bbox`와 같이 어드민 전용 경로로 명시적 이전하여 외부 사용자가 잘못 호출하지 않도록 격리하고, `/features` 하위 경로는 100% `{data, meta}` envelope 구조만 갖도록 통일합니다.

### ③ 날씨 예보와 가격/미디어 서브 리소스 조회 구조의 확장성
> [!TIP]
> **시스템의 확장성(Extensibility) 및 클라이언트 편의성 개선**

*   **현상 및 문제점**: `FeatureDetail`에는 날씨와 유가 등 시계열성 데이터가 제외되어 있습니다. 날씨의 경우 `GET /features/{feature_id}/weather` 카드로 아주 잘 구조화되어 구현되어 있으나, 주유소 유가와 같은 가격 정보(`kind=price`)나 S3/RustFS 미디어 서브 리소스에 대한 조회 API 구조는 아직 대칭적으로 설계되지 않았습니다.
*   **개선 제안**:
    *   **단기**: 유가 등의 가격 정보를 weather 카드와 대칭적인 형태로 조회할 수 있는 `GET /features/{feature_id}/prices` API 명세를 선제 정의합니다.
    *   **장기**: `GET /features/{feature_id}` 상세 조회 시 `?include=weather,prices` 와 같이 관계된 서브 리소스를 함께 join하여 반환할 수 있는 파라미터를 추가하여 1-RTT 조회가 가능하도록 확장성 있는 통합 DTO를 고려합니다.

### ④ Batch 조회 API의 파라미터 구조 확장성
*   **현상 및 문제점**: TripMate가 사용하는 `POST /tripmate/features/batch`는 현재 단순 `feature_ids` 리스트만 바디로 받습니다. 클라이언트가 특정 화면(예: 지도 핀 표시용 경량 정보 vs 상세 요약 정보)에 따라 요약 필드만 필요로 할 때, batch API 스펙을 매번 변경해야 합니다.
*   **개선 제안**: `FeatureBatchRequest` Pydantic DTO에 향후 선택적으로 사용할 수 있는 필터 필드를 미리 고려해 둡니다.
    ```json
    {
      "feature_ids": ["f_1", "f_2"],
      "fields": ["feature_id", "name", "marker_icon"],
      "include_inactive": false
    }
    ```

### ⑤ 라우터 태그(Tags) 구조의 파편화 정리
*   **현상 및 문제점**: 라우터 등록 시 `/categories`는 `tags=["categories"]`, `/providers/...`는 `tags=["providers"]` 등으로 파편화되어 있어 OpenAPI codegen 시 클래스가 불필요하게 분할됩니다.
*   **개선 제안**: TripMate/user-facing에 속하는 공개 API들은 공통적으로 `tags=["features"]`로 모아서 그룹화하고, 업데이트나 배치 요청 등 TripMate 전용 뮤테이션은 `tags=["tripmate"]`로 묶어 클라이언트 클래스를 단순화합니다.

---

## 3. API 버전 관리 Prefix (`/v1`) 추가 검토

TripMate 공개 API에 `/v1` prefix를 도입하는 방안에 대한 장단점 분석 및 아키텍처적 평가입니다.

### 장점 (Pros)
1.  **점진적 이행(Graceful Migration) 가능**: TripMate와 krtour-map은 독립적으로 실행 및 배포되는 컨테이너 프로그램입니다(ADR-045). 향후 하위 호환성이 깨지는 변경(Breaking Change) 발생 시, `/v2` 엔드포인트를 신설하고 `/v1`을 한시적으로 유지하는 마이그레이션 유예 기간을 제공함으로써 무장애 운영이 가능해집니다.
2.  **공개 API 계약의 명확성**: 외부 연동 시스템(TripMate 등)에 API 버전 생명주기를 규격화하여 인지시키고, 안정적인 운영 인터페이스를 약속할 수 있습니다.

### 단점 및 우려사항 (Cons)
1.  ** SemVer 및 빌드타임 타입 검증 정책(D-3, D-4)과의 역할 중복**:
    *   현재 krtour-map의 D-3(SemVer + 이원 schema) 및 D-4(TripMate OpenAPI typescript codegen) 정책은 빌드 타임 타입 시스템 정적 검증 및 CI drift gate를 통한 동기화를 선호합니다. 따라서 빌드 타임에 타입 불일치를 감지하므로 런타임 URL 버전 분기의 실익이 다소 적을 수 있습니다.
2.  **내부 어드민 UI용 API와의 혼선**: 어드민 백엔드/프론트엔드는 단일 묶음 배포물(ADR-035)이므로 `/v1`과 같은 버저닝이 오히려 코드 파편화를 유발할 수 있습니다.

### 권장 제안
*   **사용자/TripMate 공개 API에만 `/v1` Prefix 선택적 일괄 적용**:
    *   내부 관리용 API(`/admin/*`, `/ops/*`, `/debug/*`)는 prefix 버저닝을 제외합니다.
    *   `openapi.user.json`에 포함되는 공개 API(`/features/*`, `/tripmate/*`, `/categories`, `/providers/*`)에 대해서만 라우터 단위에서 공통으로 `/v1` prefix를 선언하여 노출합니다.
    *   *예시 경로:*
        *   `GET /v1/features/in-bounds`
        *   `GET /v1/features/{feature_id}`
        *   `POST /v1/tripmate/features/batch`
        *   `PUT /v1/tripmate/poi-cache-targets/{external_system}/{target_key}` (tripmate prefix 이전 적용)
    *   **도입 방법**: FastAPI `APIRouter` 또는 `app.include_router()` 시점에 `prefix="/v1"` 파라미터를 사용하면 소스코드의 물리적 구조 변경 없이 매우 단순하고 안전하게 도입이 가능합니다.

---

## 4. TripMate 서비스 확장을 위한 추천 API 제안

향후 TripMate의 기능 다변화와 지도 경험 고도화를 위해 krtour-map 독립 프로그램 측에 추가하면 가치 있는 API 목록 제안입니다.

### ① 시계열 가격 정보 조회 API (`GET /v1/features/{feature_id}/prices`)
*   **배경**: 현재 데이터 모델에는 OpiNet 유가 등 `kind=price` 데이터가 DB(`price_values`)에 수집·적재되고 있으나 조회용 API가 정의되지 않은 상태입니다.
*   **필요성**: TripMate의 여행 경로 내 최저가 주유소 피드를 구성하거나, 상세 카드에서 유가 추이를 그래프로 렌더링하기 위해 특정 주유소의 날짜별 가격 히스토리를 반환하는 대칭적 API가 필요합니다.

### ② 검색어 자동완성 API (`GET /v1/features/autocomplete`)
*   **배경**: 현재의 `GET /v1/features/search`는 pg_trgm 유사도 기반의 전체 텍스트 검색을 지원하므로, 타이핑 중 실시간 자동완성(Debounced Typeahead)을 처리하기에는 무거운 쿼리가 발생합니다.
*   **필요성**: 사용자가 입력창에 단어를 타이핑할 때 초경량으로 장소명을 매칭하여 상위 5~10개의 후보를 실시간 노출하기 위한 prefix 인덱스(또는 pg_trgm 간소화) 기반 자동완성 API가 요구됩니다.

### ③ 선형 공간 정보(트래킹/경로) 조회 API (`GET /v1/features/{feature_id}/paths`)
*   **배경**: 국립공원/트래킹 코스(`kind=route`) 등의 데이터가 모델에는 있으나, 현재 상세 API는 place나 event처럼 단일 점(point) 좌표 기준으로만 설계되어 있습니다.
*   **필요성**: TripMate 지도상에 걷기 코스, 트래킹 경로, 드라이브 코스 등의 전체 선형 geometry 정보(GeoJSON `LineString` 등)를 온전하게 그려주기 위해 경로 정보를 리턴하는 전용 API가 필수적입니다.

### ④ 실시간 유고 및 휴무 알림 Webhook / SSE 구독 API
*   **배경**: 공지사항(`kind=notice`)이나 축제·행사 일정(`kind=event`)에 천재지변, 공사, 행사 취소 등으로 인한 갑작스러운 유고 또는 특별 휴무 상태가 갱신됩니다.
*   **필요성**: TripMate 측에 상태 변경 이벤트를 실시간으로 푸시(Webhook 또는 Server-Sent Events)해 줌으로써, 해당 여행지에 대해 일정을 잡은 여행자들에게 TripMate가 즉시 "행사 취소 알림" 푸시 메시지를 보낼 수 있게 하는 유용한 백엔드 허브 역할을 수행할 수 있습니다.
