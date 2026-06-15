# Cross-repo 포트·계약 정합성 audit — 2026-06-15 (claude) — DA-D-06

문서 정합성 스윕 PR #438(`docs-consistency-sweep-2026-06-14.md`)의 후속 **DA-D-06**.
스윕이 `integration-map.md`의 kor-travel-concierge 포트를 `12401`(docker-manager
Prometheus와 충돌) → `12601`/MCP `12602`/web `12605`로 정정했는데, integration-map은
cross-repo **정본 지도**이므로 공급자 측 값을 [`runbooks/cross-repo-audit-checklist.md`](../runbooks/cross-repo-audit-checklist.md)
§0 원칙대로 **각 형제 repo origin/main 기준으로** 교차 확인했다.

- **기준 커밋(origin/main, `git fetch` 후 실측)**:
  - kor-travel-map: `47df2ff` (#438 머지 후)
  - kor-travel-concierge: `9fabbcf`
  - **kor-travel-docker-manager: `126b281`** — 고정 host 포트 정본 owner(ADR-052 amendment)
  - kor-travel-geo: `0bb7855`
  - TripMate: **로컬 미체크아웃** → 본 audit 범위 외(§5)

## 1. 결론

**DA-D-06 = 확정.** `integration-map.md` §1 포트표 + §3/§4 concierge·geo 계약이 전부
공급자 origin/main과 정합한다. #438의 concierge `12601`/`12602`/`12605` 정정이
**양측 정본으로 검증**됐다(구 `12401`은 docker-manager Prometheus 포트로 충돌 확정).
**본 repo 추가 수정 없음.**

## 2. 포트 교차 확인 — integration-map §1 ↔ 공급자 origin/main 실측

| 시스템 | integration-map §1 표기 | 공급자 origin/main 실측 | 출처 | 판정 |
|---|---|---|---|---|
| kor-travel-map | API 12701 · admin 12705 · Dagster 12702 · pg 5432 · rustfs 12101/12105 | `KOR_TRAVEL_MAP_API_PORT=12701`, `_DAGSTER_PORT=12702`, `_UI_PORT=12705` | docker-manager `.env.example` | ✅ |
| **kor-travel-concierge** | **API 12601 · MCP 12602 · web 12605** | concierge `API_HOST_PORT=12601`/`MCP_HOST_PORT=12602`/`FRONTEND_HOST_PORT=12605` **및** docker-manager `KOR_TRAVEL_CONCIERGE_API_PORT=12601`/`_MCP_PORT=12602`/`_UI_PORT=12605` | 양측 일치 | ✅ |
| kor-travel-docker-manager | pg 5432 · rustfs 12101/12105 · Grafana 12205 · cAdvisor 12301 · Prometheus 12401 | `RUSTFS_API_PORT=12101`/`_CONSOLE_PORT=12105`, `GRAFANA_PORT=12205`, `CADVISOR_PORT=12301`, `PROMETHEUS_PORT=12401`, `KOR_TRAVEL_GEO_DB_PORT=5432` | docker-manager `.env.example` | ✅ |
| (보조) kor-travel-geo | 12501 | `KOR_TRAVEL_GEO_API_PORT=12501` + geo `README` `--port 12501` | docker-manager + geo | ✅ |

- concierge **MCP host 12602 → container 12402**(compose 매핑 `"${MCP_HOST_PORT:-12602}:12402"`).
  integration-map의 호스트 포트 12602 표기가 정확하다.
- docker-manager가 geo **UI 12505**(`KOR_TRAVEL_GEO_UI_PORT`)도 관리하나 integration-map은
  geo를 보조로 두고 API 12501만 표기 — kor-travel-map 데이터 흐름과 무관해 drift 아님.

## 3. 계약 spot-check — §3/§4 (concierge export · geo)

- **concierge feature export**(integration-map §3/§4):
  - 경로 `/api/v1/features/{snapshot,changes}` — `backend/ktc/models/feature_export.py` /
    `routes.py`. ✅ (§2 다이어그램 + §3 `/api/v1/features/*`와 일치)
  - 인증 `X-API-Key` — `backend/ktc/core/security.py:22` `API_KEY_HEADER_NAME = "X-API-Key"`. ✅
  - 무-envelope `{items, next_cursor, has_more}` — `feature_export_service.py:430`
    `FeatureExportPage(items=…, next_cursor=…, has_more=…)`, `routes.py:478-499`. ✅
  - 계약 정본 `docs/feature-export-api.md` origin/main 존재. ✅ (§4 인용 유효)
- **geo geocoding**(integration-map §4): `POST /v2/{geocode,reverse}` @ `12501` — geo
  `README`/`CHANGELOG` origin/main 확인. ✅ (구 `8888` 잔재 없음)

## 4. Cross-repo 발견 (공급자 repo 측 — 본 repo 비대상)

- ⚠️ **concierge `docs/architecture.md:21`** (origin/main `9fabbcf`)가 kor-travel-map을
  옛 이름 **`python-krtour-map`**으로 표기. 본 repo 수정 대상 아님 — **concierge 측
  후속**(naming 현행화 → kor-travel-map/kortravelmap)으로 분계한다. integration-map은
  이미 전환기 명칭 note(§머리말 L12-14)를 보유해 본 repo 영향 없음.
- 체크리스트 §2(전제 신선도) 관점에서 concierge가 kor-travel-map을 "주기 pull"하는
  pull 모델 서술은 ADR-053과 정합(되살아난 `/tripmate/*`·`data.next_cursor` 등 없음).

## 5. 미검증 (범위 외, 후속)

- **TripMate**(api 9021 · web 9022 + batch `found`/cursor 계약): TripMate repo 로컬
  미체크아웃 + docker-manager 비관리(consumer 자체 소유 포트 — 인프라 스택 밖).
  본 DA-D-06(concierge 포트) 범위 밖이며, 분기 1회 **quarterly cross-repo audit**
  (체크리스트 §1~4 전수, TripMate origin/main 기준)에서 함께 점검한다.

## 6. 조치

- 본 repo 코드/문서 수정 없음(`integration-map.md`는 #438에서 이미 정합). 본 리포트로
  **DA-D-06 종결**. concierge-side naming(§4)은 concierge 후속, TripMate 전수 대조(§5)는
  quarterly audit로 위임.
