# kor-travel-concierge provider loader 검증 — 2026-06-15 (claude)

사용자 지시("concierge provider loader 검증"). kor-travel-map이 kor-travel-concierge
feature export(`/api/v1/features/{snapshot,changes}`)를 pull·적재하는 **소비자 코드**를,
실제 concierge export **생산자 계약**(origin/main)과 대조한 conformance 감사다.

- **기준 커밋**: map `origin/main`(#439 후) · concierge `origin/main 9fabbcf`.
- **방식**: 5-에이전트 병렬 검증(① item 스키마 필드별 ② 페처/페이지네이션 ③ operation
  lifecycle·식별 키 ④ 로더 내부 버그 ⑤ 테스트 정합) + 종합. concierge는 origin/main
  기준 실측(`git show/grep origin/main:`). 본 리포트 작성자가 핵심 발견(C-01)의 linchpin을
  직접 재확인(concierge `feature_export_service.py:146-148` admin 코드 None, map `ids.py:145`
  bjd_part).
- **대상 코드**: `src/kortravelmap/providers/kor_travel_concierge.py`(변환),
  `packages/kor-travel-map-dagster/.../provider_fetchers.py`(페처),
  `.../dagster/assets.py`(asset 배선). 상수 provider=`kor-travel-concierge-youtube` /
  dataset=`youtube_place_candidates` / entity_type=`extracted_place_candidate`.

## 1. 결론

**로더는 근본적으로 정합·정상이다.** 16개 계약 항목 OK(§3) — silent data drop·스케일
버그 없음. **유일한 실질 결함은 feature_id 결정성(C-01/C-02)** 이며 본 PR에서 ADR-057로
수정했다(ADR-057, #440). 나머지 하드닝(C-04~C-08)은 **오늘 활성 버그 0**의 latent 항목으로
후속 PR에서 해소했고, concierge측 P-01도 concierge #83으로 머지됐다(잔여 권장 1건:
source_entity_id 불변성 계약 테스트).

## 2. 수정/후속 요약

| ID | sev | 한 줄 | 처리 |
|----|-----|-------|------|
| C-02 | HIGH | `category`가 feature_id에 포함 + enrich 전 None → 채워지면 재export로 feature_id 분기(중복) | ✅ ADR-057, 본 PR |
| C-01 | HIGH | producer가 admin 코드 항상 None → bjd가 optional geocoder에만 의존 → geocoder 유무로 feature_id 분기 | ✅ ADR-057, 본 PR |
| C-03 | MED | 해피패스 테스트 픽스처가 producer가 안 보내는 admin 코드 주입 → C-01 은폐 | ✅ 본 PR(픽스처 None + 회귀 테스트) |
| C-04 | MED | inactivate 매칭 키(고정 상수, exact SQL) ↔ upsert 저장 키(payload+normalize) — 오늘 일치, 향후 alias 시 silent miss | ✅ 후속 PR(identity triple 상수 강제 + drift 경고) |
| C-05 | MED | operation open-world 분류(`!=upsert`→전부 inactivate) — 새 operation 추가 시 live feature 파괴적 비활성화 | ✅ 후속 PR(폐쇄 분류: reject/tombstone만 inactivate, unknown skip+warn) |
| C-06 | LOW | 페처 anti-stall 가드(커서 비전진/누락) 미테스트 | ✅ 후속 PR(가드 테스트 2종) |
| C-07 | LOW | `base_url`에 경로 segment 있으면 httpx 절대경로 join이 삭제 (+settings 예시 포트 12401 stale) | ✅ 후속 PR(settings 문서 + 12401→12601 정정) |
| C-08 | INFO | producer 유래 golden 픽스처 부재 → 스키마 drift 미감지 | ✅ 후속 PR(producer-only extras 보존 conformance 테스트) |
| P-01 | LOW | **concierge측**: `limit`에 `Query(ge=1,le=500)` 바운드 없음(silent clamp) | ✅ concierge #83 머지(이슈 #82) |

## 3. 계약 정합 (검증 OK — 혼동 방지 기록)

- **경로** `/api/v1/features/{snapshot,changes}`(map `provider_fetchers.py:89` ↔ concierge
  `routes.py` `@router.get`), **인증** `X-API-Key`(map :93 ↔ concierge `security.py`),
  **쿼리** `limit`/`cursor`, **엔벌롭** flat `{items,next_cursor,has_more}`(data 중첩 없음),
  **limit** default 200 / max 500(map `Field(le=500)` ↔ concierge `normalize_limit`),
  **커서** opaque base64(sequence) 단조 증가 — map anti-stall 가드 정상 케이스 미발동.
- **operation** enum `{upsert,reject,tombstone}` lowercase 일치. snapshot=upsert만,
  changes=3종. upsert→bundle, 비-upsert→inactivate.
- **식별 트리플** provider/dataset/entity_type 글자 단위 일치(`normalize_provider_name`
  no-op). **source_entity_id=str(candidate.id)** 가 upsert·reject/tombstone 동일 →
  inactivate 조인 매칭.
- **confidence_score** 0.0–1.0(concierge `video_analysis_service.py:156` clamp) → map ×100
  (0≤v≤1일 때만) → 0.86→86, **이중 스케일 없음**.
- **raw_payload_hash** `sha256:<hex>` producer 주입 → map 우선 사용(feature_id 아닌
  source_record_key용). **place/youtube/evidence/address 필드명·중첩 전부 존재**, producer
  extra(video_summary 등)는 무시되나 raw_data·detail.payload에 보존 — drop 없음.
- **reject/tombstone→status='inactive'** lifecycle(`assets.py` → `feature_repo`
  `_INACTIVATE_BY_ENTITY_IDS_SQL`) — `source_entity_id` 키라 feature_id 불안정성에 **면역**.

## 4. 핵심 발견 상세 (C-01/C-02 — 본 PR 수정)

`make_feature_id`는 `bjd_code`(prefix+hash)와 `category`를 식별자에 넣는다(`ids.py:145,149`).
concierge는 admin 코드를 항상 None(`feature_export_service.py:146-148`), category를 enrich
전 None(`:138-139`)으로 보내고 enrich 후 payload 변경 upsert로 재export하므로, 두 늦은-바인딩
값이 feature_id를 분기시켜 같은 후보가 새 feature로 중복된다. 안정 키 `candidate.id`가 이미
있으므로 ADR-057로 식별자를 거기에 고정(`bjd_code=None` + 고정 IDENTITY category + 상수
source_type)하고, 실제 bjd/category는 Address/Feature 가변 속성으로 in-place 갱신한다.
회귀 테스트 2종(geocoder 유무 동일 id / category None↔8자리 동일 id) 추가.

## 5. 후속

- **map (해소됨 — 후속 PR)**: C-04 identity triple을 상수로 강제(upsert 저장 == inactivate
  매칭 == feature_id source_type) + payload drift 경고 / C-05 operation 폐쇄 분류(upsert만
  적재, reject/tombstone만 inactivate, unknown skip+warn) / C-07 base_url scheme+host[:port]
  문서화(+예시 포트 12401→12601 정정) / C-06 페처 anti-stall 가드 테스트 2종 / C-08
  producer-only extras 보존 conformance 테스트.
- **concierge (그쪽 repo)**: ~~P-01(`limit`에 `Query(ge=1,le=500)`로 명시적 422 계약)~~
  **완료 — concierge #83 머지**(이슈 #82, T-081: 두 endpoint `limit` 422 바운드 + 회귀
  테스트 2종). 잔여 권장 1건: `source_record.source_entity_id`가 한 후보의 upsert·reject/
  tombstone export에서 byte 동일하다는 계약 테스트(map inactivate 조인 전제).
