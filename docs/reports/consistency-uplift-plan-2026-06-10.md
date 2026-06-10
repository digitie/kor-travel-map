# Cross-repo 일관성 uplift 액션 플랜 (2026-06-10)

> **상태 (2026-06-10 2차 갱신)**: 의사결정 **전 항목 종결** — D-01(b 잠정)·D-02~05(a)·
> D-06(수정: `/admin/etl` 유지)·D-07(a)·D-08/09(권고안)·D-10(T-066 운영 개시 전 버킷
> 분리)·D-11(익명)·D-12(`found`+status)·D-13(KASI류 고유 ETL — 중복 없음).
> krtour-map 정본 반영: **ADR-050~052 + tasks T-217a~g + CLAUDE.md**. 본 문서의
> KR-01→T-217b, KR-02→완료, KR-03→ADR-050 #2, KR-04→T-217d, KR-06→T-217f,
> 검토 보고서 §3.2 A-2(D-07)→T-217g로 task화됨.
> **추가 결정 사항(사용자 보정)**: tripmate-agent export 경로는 downstream 이름 없이
> `/api/v1/features/{snapshot|changes}` — krtour fetcher 정렬은 T-217a (TA-01/T-066과
> 동시 배포). 의사결정 의존 항목은 D-번호
> ([`decisions-needed-2026-06-10.md`](decisions-needed-2026-06-10.md))를 참조.
> **검토 근거**: [`service-completeness-review-2026-06-10.md`](service-completeness-review-2026-06-10.md)
> (기준 커밋: krtour `0e45bd7` / TripMate `4a10a5b` / tripmate-agent `a443ca0`).
> **TripMate 측 상세**: [`tripmate-side-actions-2026-06-10.md`](tripmate-side-actions-2026-06-10.md).
> **tripmate-agent 측 상세**: 해당 repo `docs/cross-repo-consistency-actions-2026-06-10.md` (직접 전달 완료).

---

## 1. 일관성 현황 점수와 목표

| 축 | 현황 | 주요 감점 요인 | M4 완료 시 목표 |
|---|---|---|---|
| API 계약 (코드↔코드) | **60/100** | C-1 batch `found`, C-2 구모델 배선, C-4 export 미구현, C-5 `max_items` | 95 — E2E로 검증된 계약 |
| 문서↔구현 | **65/100** | TripMate DEC-01 노후 전제, 통합 문서 구식 경로 | 90 — 정본 1곳 + view 구조 |
| R&R 경계 | **75/100** | RustFS 버킷, 제보 릴레이, tombstone, 계약 정본 위치 | 95 — D-01~04 확정·기록 |
| 운영 가시성 | **80/100** | provider 신선도 대시보드, 후보 provenance 동선 | 90 |

점수는 상대 지표(감점 요인 해소 추적용)다. 절대평가가 아니라 액션 완료 체크의 분모로 쓴다.

## 2. 액션 백로그

표기: 🔴 P0(가치 사슬/계약 차단) · 🟡 P1 · ⚪ P2. `의존` 열의 D-는 의사결정,
TM-/TA-/KR-는 액션 간 의존. 의사결정 D-01~13 **전 항목 종결(2026-06-10)** — 액션은
의존 순서(§3)에 따라 착수 가능하다. krtour-map 측 액션은 tasks T-217a~g로 추적.

### 2.1 python-krtour-map (KR-)

| ID | 우선 | 액션 | 의존 |
|---|---|---|---|
| KR-01 | 🟡 | **tombstone/reject → feature inactive 경로 구현**: `tripmate_agent_items_to_bundles()`의 skip(`providers/tripmate_agent.py:87`)을 deactivate 연동으로 보강(MOIS Step C 동형). 1단계로 skip 건수 WARN/admin 이슈 노출도 가능 | D-03 |
| KR-02 | 🟡 | **신규 task 등록**: KR-01(라이프사이클), 제보 수신 API(D-02 승인 시), provider 신선도 대시보드(D-07 승인 시)를 `docs/tasks.md`에 T-2xx로 | D-02/03/07 |
| KR-03 | 🟡 | **tripmate-agent 계약 링크 정리**: D-04 확정 후 `docs/rest-api.md`(또는 external-apis 절)에서 tripmate-agent 정본 계약 문서로 링크 + 소비 측 기대(fetcher의 `{items,has_more,next_cursor}`/`X-API-Key`/env 키) 요약 | D-04 |
| KR-04 | 🟡 | **cross-repo 연동 정본 문서 신설** (예: `docs/integration-map.md`): 3-시스템 포트(9011/9012/9013/15433 · 9021/9022 · 9041/9042)·연동 방향·인증 방식(C-9)·envelope 차이(C-10)·계약 정본 위치를 1장으로. 각 repo CLAUDE.md/AGENTS.md에서 링크. "한쪽 갱신이 타 repo 전제에 전파 안 되는" 구조적 사고(DEC-01류) 재발 방지 | D-08 |
| KR-05 | ⚪ | **geocoding R&R 1줄 명시**: tripmate-agent 후보 지오코딩(제안) vs krtour kraddr-geo 재검증(정본 확정)의 역할 차이를 architecture.md 또는 ADR-049 보강에 기록 | — |
| KR-06 | 🟡 | **YouTube evidence 노출 형태 확정**: feature detail의 `urls`/`detail`/`raw_refs`에 영상 링크·타임스탬프·confidence가 소비 가능한 형태로 나오는지 점검·보강 — TripMate TM-08(출처 배지 UX)의 선행 | D-05 |
| KR-07 | ⚪ | **경미 문서 2건**: CLAUDE.md에 REST 버전 거버넌스(GA 후 `/v2` N-1 동시지원) 1줄, architecture.md에 고정 포트 표기(또는 의도적 생략 주석) | — |
| KR-08 | 🟡 | **T-066 완료 후 live fetch smoke**: Dagster `tripmate_agent_youtube_features` live 전환 — cursor 영속(`provider_sync_state`)·페이지네이션 가드·재시도 멱등성 검증. T-212e(실데이터 full reload) 항목에 합류 | TA-01 |
| KR-09 | ⚪ | **merge history 노출 확인**: `feature_merge_history`가 admin feature 상세에서 조회 가능한지 점검, 없으면 task 등록 | — |

### 2.2 TripMate (TM- — 상세는 tripmate-side-actions 문서)

| ID | 우선 | 액션 (요약) | 의존 |
|---|---|---|---|
| TM-04/05 | 🔴 | DEC-01 폐기 + 연동 문서 2종 갱신 (노후 전제 해소 — 코드 변경 없음) | — |
| TM-01/02/03 | 🔴/🟡 | 계약 수정: batch `found`, in-bounds `max_items`, `meta.cluster` optional | — |
| TM-06 | 🔴 | feature 라우터 재배선(etl_bridge 제거) + 평면 `lon`/`lat` DTO 매핑 | TM-01~03 |
| TM-07 | 🟡 | openapi-typescript/httpx client 생성 (krtour T-210d·e의 짝) | krtour T-212e |
| TM-08~11 | 🟡 | 출처 배지 UX · kind 화이트리스트 · 공유 뷰 권한 · 지도 성능 정책 | KR-06, D-05 |
| TM-12/13 | 🟡 | admin 표면 축소 · FeatureSuggestion 릴레이 배선 | D-06, D-02 |
| TM-14 | 🟡 | TM-항목의 TripMate task 등록 (krtour T-210b~e 짝 맞춤) | — |

### 2.3 tripmate-agent (TA- — 상세는 해당 repo 문서)

| ID | 우선 | 액션 (요약) | 의존 |
|---|---|---|---|
| TA-01 | 🔴 | **T-066 export API 구현**: `GET /api/v1/krtour/features/{snapshot\|changes}` — krtour fetcher 기대치(`X-API-Key`, `limit`/`cursor`, `{items,has_more,next_cursor}`, cursor 안정성) 체크리스트 준수 | — |
| TA-02 | 🟡 | 계약 정본 문서 독립(plan 문서 §7 → `docs/krtour-export-api.md`류) + OpenAPI 노출 | D-04 |
| TA-03 | 🟡 | export 노출 정책 구현(검수 통과만 / 전부+confidence) | D-05 |
| TA-04 | 🟡 | RustFS 버킷 결정 반영(분리 시 마이그레이션) | D-01 |
| TA-05 | 🟡 | `category_code_suggestion` ↔ krtour 8자리 코드 매핑 기준(T-065)을 krtour `GET /v1/categories` 정본으로 고정 | — |

## 3. 실행 순서 (마일스톤)

```
M1 문서 정합 (코드 0줄, 즉시) ─ TM-04/05 · KR-07 · KR-04(D-08 승인 시)
   └ 효과: "krtour HTTP 미존재" 착시 제거 → TripMate 계획 재정렬
M2 계약 수정 (소규모 코드) ──── TM-01/02/03 · D-01~05 의사결정 처리
M3 공급 사슬 완결 ───────────── TA-01(T-066) → KR-08(live smoke) · KR-01(D-03 승인 시)
   └ 게이트: krtour Dagster가 tripmate-agent 실데이터를 cursor 증분 포함 정상 적재
M4 소비 사슬 완결 ───────────── TM-06(배선) → TM-07(타입 생성, krtour T-212e 후)
   └ 게이트: E2E — trip 생성→지도 탐색(in-bounds)→검색→POI 첨부(batch)→날씨 카드
M5 UX·운영 보강 ─────────────── TM-08~13 · KR-06(M4 전 선행 가능) · D-06/07 표면 정리
```

**병렬성**: M1은 전부 병렬. M2의 TM-과 D-처리는 독립. M3(공급)과 M4의 TM-01~03(소비
계약 수정)은 서로 독립이므로 동시 진행 가능 — 직렬 의존은 TA-01→KR-08, TM-06→E2E뿐.

## 4. 재발 방지 (구조적 조치)

1. **연동 정본 1곳 + view 구조** (KR-04): 계약은 공급자 repo가 정본, 소비자 repo 문서는
   "view + 정본 링크" 머리말 필수 — krtour `docs/tripmate-rest-api.md`가 이미 이 형식이며
   TripMate·tripmate-agent 측 문서도 동일 형식으로 통일.
2. **분기 1회 cross-repo 정합성 audit**: 본 검토(원격 전제·계약 필드·포트)를 체크리스트화
   해 krtour `docs/runbooks/`에 등재 — 형제 repo는 반드시 origin/main 기준으로 실측
   (이번 검토에서 TripMate 워크트리가 133커밋 stale였음).
3. **타입 생성 클라이언트** (TM-07): 수기 필드명(`items` vs `found`류) 사고의 원천 차단.
4. **외부 추적 task 짝 맞춤**: 한 repo가 "외부 추적"으로 둔 task(krtour T-210b~e)는 상대
   repo 백로그에 대응 항목이 존재해야 한다 — TM-14로 정렬, 이후 신규 외부 task에 관행화.

## 5. 완료 기준 (Definition of Done)

- [ ] C-1~C-8 전 항목 해소 (코드 또는 문서) — §1 계약 축 95점
- [ ] D-01~09 전 항목 의사결정 기록 (채택/기각 무관, 결정 자체가 완료 조건)
- [ ] M4 E2E 시나리오 1회 green (실데이터: krtour T-212e 환경)
- [ ] KR-04 연동 정본 문서가 3-repo 진입 문서(CLAUDE.md/AGENTS.md)에서 링크됨
- [ ] 분기 audit 체크리스트가 runbook에 등재됨
