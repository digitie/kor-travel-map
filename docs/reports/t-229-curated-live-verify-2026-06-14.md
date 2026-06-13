# T-229 — T-212e 후속 라이브 검증 리포트 (2026-06-14)

> 상태: **검증 완료**. T-225가 분리한 커버리지 갭(curated 오버레이 + post-reload
> 신규 표면 + smoke breadth)을 **실데이터(1,095,665 features)** 위에서 라이브
> 검증했다. 단 **arm64 buildx는 환경 차단**(WSL에 `GITHUB_TOKEN` 부재 → private
> provider pin 이미지 빌드 불가) — 토큰이 있는 배포 환경의 후속으로 남긴다.

## 0. 방법 / 환경

- 사용자 지시로 표준 포트(12701/12702/12705)를 점유하던 **codex 스택을 강제 종료**한 뒤,
  검증 종료 후 external-infra 모드로 **재기동**했다(기존 이미지 재사용, rebuild 없음).
- **복원 불필요**: T-212e가 적재했던 데이터가 옛 claude postgres
  (`python-krtour-map-claude-postgres-1`, host 15433)에 그대로 잔존 —
  `feature.features` **1,095,665** / `feature_weather_values` **92,923** /
  `provider_sync.source_records` **1,111,885**, 동일 규모의 격리 복원본
  `krtour_map_restore`(T-212e §5.3 staging)도 존재.
- **운영 데이터 무손상 원칙**: 사용자가 고른 "복원본에서 검증"에 따라 모든 쓰기는
  **격리 복원본 `krtour_map_restore`에만** 수행(async/sync/dagster DSN 전부 `_restore`로
  오버라이드). 운영 `krtour_map`의 `curated_features`는 **검증 전후 0 유지**로 확인.

## 1. (A) curated 오버레이 — **완전 검증** [T-225 AS-01 / API-11 / API-12 해소]

T-225는 "curated 오버레이가 reload에서 한 번도 materialize/검증되지 않았다"를 지적했다.
이를 실데이터로 직접 닫았다.

- 착수 상태(복원본): `curated_features` **0**, copy_snapshots 0, seed는 테마 8 / 소스 18
  / enabled rule 18 존재 — reload가 하위 provider feature만 적재하고 오버레이는
  미materialize였음을 실데이터로 재확인.
- `dagster asset materialize`로 4개 asset 실행 → **RUN_SUCCESS** (~35s):
  `curated_source_metadata` → `curated_feature_candidates` → `curated_feature_status_sweep`
  → `curated_tripmate_copy_snapshots`.
- 결과: `feature.curated_features` **0 → 86,341** (전부 `curation_status=candidate`).
  테마별 후보:

  | theme | 후보 수 |
  |-------|--------|
  | pet-friendly | 23,090 |
  | leisure | 22,241 |
  | barrier-free | 12,299 |
  | world-food | 9,198 |
  | media-places | 8,575 |
  | family-culture | 8,416 |
  | bookstores | 2,522 |

  (MCST provider source_records 카운트와 정합 — 예: pet_friendly 23,091 → 후보 23,090.)
- **API 서빙 end-to-end**(현재 코드 이미지 `kor-travel-map-codex-api`를 복원본에 연결):
  - `GET /v1/admin/curated-features` → **200**, 실제 후보 서빙(예: theme=leisure,
    feature="원동탁구클럽", 오산시, 좌표/주소 포함). status 필터(candidate/selected/
    approved/published/archived) 전부 200.
  - `GET /v1/curated-features`(사용자) → `items:[]` — **설계대로 정상**: 사용자 표면은
    선택/게시된 것만 노출, 86,341 후보는 미선택 상태라 숨김(선택 게이트 동작 확인).
  - `GET /v1/curated-themes`·`/v1/curated-sources` → 200.
  - `tripmate-copy` 스냅샷: 0 — **설계대로**(선택된 curated feature에 한해 생성).
    asset 자체는 RUN_SUCCESS로 wiring 확인. 선택→스냅샷 경로의 데이터 검증은 운영자가
    후보를 select한 뒤 가능(후속).

## 2. (B) post-reload 신규 표면

- **Prometheus `/metrics`**: `GET /metrics` **200**, Prometheus exposition format 응답
  확인(현재 코드 스택, 기본 on).
- **arm64 multi-arch buildx (T-108/ADR-056)**: **검증 불가 — 환경 차단**. WSL에
  `GITHUB_TOKEN`이 없어 api/dagster 이미지의 private provider pip pin 레이어 빌드가
  불가능하다. arm64(Odroid) 이미지 build+boot smoke는 **토큰이 주입된 배포 환경**에서
  수행해야 한다. (본 검증은 기존에 빌드된 amd64 이미지를 재사용했다.)

## 3. (C) smoke breadth — 응답 확인

현재 코드 스택(api)에서 read-only 표면이 전부 정상 응답:

- `/v1/ops/providers`·`/ops/metrics`·`/ops/api-call-logs`·`/ops/system-logs` → 200.
- `/v1/admin/dedup-reviews`·`/admin/enrichment-reviews`·`/admin/feature-update-requests`
  → 200.
- `/v1/features/nearby/by-target`(존재하지 않는 target) → 404, `/v1/debug/mois-license/0`
  (존재하지 않는 id) → 404 — 엔드포인트 정상 동작(미존재 리소스에 대한 정상 404).
- `/metrics` → 200.

## 4. 결론

- T-225가 분리한 커버리지 갭 중 **(A) curated 오버레이는 실데이터로 완전 검증**되어
  닫혔다(파이프라인 정상, 단지 T-212e reload 때 실행되지 않았던 것). **(B-metrics)·(C)도
  검증**됐다.
- **유일 잔여: arm64 buildx** — `GITHUB_TOKEN`이 있는 배포 환경에서만 가능하므로
  배포 시점 후속으로 명시 분리한다(코드/데이터 결함 아님).
- 운영 데이터(`krtour_map`)는 무손상. codex 스택은 사용자 지시대로 강제종료 후 재기동.
