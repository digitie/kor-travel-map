# T-225 — T-212e closure 재검증 리포트 (2026-06-13)

> 상태: **완료 — T-212e closure 재검증 유효**. 라이브 full reload 재실행 없이
> 현재 main 기준 문서/코드 증거 대조로 닫는다(인수기준 충족). 1차 입력은
> `docs/reports/t-212e-live-full-reload-final-2026-06-12.md`. 남은 항목은
> 라이브 검증이 필요한 **커버리지 갭**(코드 결함 아님)으로 후속 **T-229**에 분리.

## 0. 검증 방법

- 기준 트리: `feat/t-225-t212e-closure-recheck` (origin/main `25b286b`, #434 머지 포함).
  최초 분석은 `66ad85f` 기준이었고 #434 머지 후 rebase + delta 재확인했다(§7).
- 라이브 Docker 스택은 **재실행하지 않는다**(T-225 인수기준: 다른 agent의 T-212e
  결과가 충분하면 증거 대조로 종결). 5개 차원을 교차검증하고 각 gap/drift를
  독립 에이전트가 실제 파일로 **반증(adversarial verify)**했다. (서브에이전트 18,
  tool 호출 273.)
- 5개 차원: (1) Dagster asset 인벤토리 vs 리포트 커버리지, (2) `/v1` API 표면 vs
  리포트 라이브 검증, (3) 실패 provider 6건 수정의 현재 main 존재 여부,
  (4) 리포트 무결성(링크·수치·이슈), (5) T-212e 머지(#425) 이후 main 변경 영향.

## 1. 결론

**T-212e closure는 현재 main 기준으로 재검증되어 유효하다.** 리포트는 재작성
불필요. 데이터/적재/정합성/offline upload/백업복원/P99 증거가 현재 코드 표면과
정합하며, 남은 것은 라이브 검증이 미수행된 **커버리지 갭**(기능 결함 아님)뿐이다.

## 2. 인수기준 체크리스트 (tasks.md §확인 항목) — 전부 확인

| 항목 | 리포트 값 | 재검증 |
|------|-----------|--------|
| live full reload row | features 1,095,665 / weather_values 92,923 | ✅ §6.1·§5.3 자체 정합(중간 1,095,047 + trails 618 = 1,095,665), restore-verify 일치 |
| consistency gate 최종 | report `99159eea`, severity_max OK, F1~F6 count 0 | ✅ §3, 이슈 정합 |
| offline upload | CSV/TSV/JSONL 3포맷 + DELETE lifecycle | ✅ §4·§4.1, DELETE 엔드포인트 실제 구현(`offline_uploads.py`) |
| e2e / smoke / backup | Playwright 33/33, API smoke 17/17, backup/restore smoke | ✅ §5.1.2·§5.2·§5.3 |
| 대표 P99 | search 85.6 / nearby 102.0 / categories 8.8 / in-bounds 441.7ms | ✅ §6.3 표 존재 |
| 신규 표면 누락 여부 | T-221/222/223/224/226/227/228 표면 | ⚠ 일부 라이브 검증 누락(§5) |

## 3. 완전 정합 — 이상 없음

### 3.1 실패 provider 6건 — 수정 전부 현재 main에 존재 (PF-01~06)

| provider/asset | 수정 | 현재 main 위치(증거) |
|----------------|------|----------------------|
| `feature_place_standard_parking_lots` | #400 좌표 격리 + datagokr int 관용 파싱(1967fb6) | `providers/standard_data.py` `_coordinate_or_none`; datagokr pin `@48e458b` |
| `feature_place_krheritage_items` | result 레벨 복합키 병합 + 결측 key skip | `providers/krheritage.py` `KrHeritageItemKey` Protocol·nameless skip; pin `@6076b52` |
| `feature_place_mcst_culture` | T-220 CSV 재배선(#395) + #413 좌표 격리 | `providers/mcst.py` `FileDataClient.iter_csv`·`_coord_or_none`; pin `@c011f6e` |
| `feature_geometry_knps_records` | #420 LINESTRING 조립 + #424 nameless skip(Protocol `str\|None`) | `providers/knps.py` `name: str\|None`·skip; pin `@16e3954` |
| `feature_event_visitkorea_enrichment` | #392 `modified_time` datetime 재정렬 | `providers/visitkorea.py` `modified_time: datetime\|str\|None`·`_modified_time_str`; pin `@cebf543d` |
| `feature_weather_kma_mid_forecast` | provider #20/PR#21 요청 tmFc 폴백 | `providers/kma.py` `tm_fc` 12자리 검증; pin `@2592b740` |

### 3.2 리포트 무결성 (RI-01~17)

- 참조 문서/스크립트/ADR 전부 해석됨: `docs/mcst-feature-etl.md`, `docs/journal.md`,
  runbook §8(`docs/runbooks/docker-app.md`·`docs/backup-restore.md`),
  `scripts/docker-restore*.sh`·`with-pg-advisory-lock.py`. **broken link 없음.**
- 수치 자체 정합: **MCST 13종 합계 정확히 102,121**; source_records 합 1,111,885 vs
  features 1,095,665(델타 ~1.5%, dedup·좌표격리·nameless skip 방향과 일치);
  weather_values 92,923 = 실제 `feature.feature_weather_values`.
- 이슈 정합: #397/#407/#409 **CLOSED**, 보강 PR #417/#420/#424/#400/#410/#411/#413/
  #416/#392/#393 **MERGED**. alembic head `0023_t216f_rest_names` 일치.

### 3.3 identity drift 없음 — 리포트는 이미 post-rename 기준 (RI-14/15)

T-225 착수 시 가정한 "구 이름(`krtour.map`/`tripmate_agent_youtube`/`kraddr-geo`)
drift"는 **실재하지 않았다.** #429(T-226)가 리포트까지 새 이름으로 재작성해, 리포트는
이미 `kortravelmap.dagster.definitions` · DB `kor_travel_map` · `kor-travel-geo` ·
`kor-travel-concierge`(`feature_place_kor_travel_concierge_youtube`) 기준이다.
구 포트 9011~9013은 codex 스택 충돌 회피용 **명시적 편차**로만 등장하고 이후 표준
포트로 이전됐다(§0.1·§5.1.1).

### 3.4 post-merge 영향 — closure 유지 (PMI-01~03/06/07)

- #430 패키지 분리는 Dagster 모듈 경로·API app mount·`/v1` prefix를 옮기지 않음 →
  리포트의 reload 실행 명령(`materialize -m kortravelmap.dagster.definitions`,
  `uvicorn kortravelmap.api.app:app`) 유효.
- #425 이후 **신규 provider/feature asset 모듈 추가 없음**(전부 rename diff). 1,095,665
  feature 인벤토리·정합성 게이트 결과는 어떤 후속 커밋에도 무효화되지 않음.
- #431 shared-DB 모드는 opt-in overlay로 기본 DB명(`kor_travel_map`) 보존.

## 4. 정상 동작이라 갭 아님 (반증됨)

| 항목 | 판정 | 근거 |
|------|------|------|
| `/v1/ops/consistency/{issues,reports}` API | **갭 아님(ok)** | e2e `admin-ops.spec.ts`가 mock 없이 `/ops/consistency`를 실제 호출(라이브 33/33에 포함). backend 경로는 `/v1/admin/issues`와 동일 repo 함수 |
| `/v1/admin/backups`·`/restore` API | **갭 아님(ok)** | 설계상 opt-in(`..._BACKUP_COMMAND_ENABLED`) 얇은 command-plan 래퍼 — 실제 엔진(스크립트)은 §5.3에서 라이브 검증, HTTP 층은 단위테스트 10건 |
| `poi-cache-targets`·`provider-refresh-policies` | **갭 아님(info)** | T-212e **이전** 도입된 config CRUD(데이터 볼륨 무관), 라우터/단위테스트 보유. 신규/drift 표면 아님 |

## 5. 확인된 커버리지 갭 (코드 결함 아님 — 라이브 검증 미수행) → T-229

반증을 통과해 실재가 확인된 갭. 대부분 "리포트의 17/17 smoke가 대표 집합이라
미포함"이며, **curated 계열만 실질적**이다.

| ID | 갭 | 심각도 |
|----|----|--------|
| AS-01 | **`curated_features` Dagster 오버레이 4-asset + `curated_features_refresh` job이 reload에서 materialize/검증 안 됨** — 하위 provider feature만 적재(스케줄은 STOPPED라 운영 자동실행은 아님) | major |
| API-12 | **사용자/공개 `curated-*` read + `/v1/curated-features/{id}/tripmate-copy`(TripMate 인계 계약, ADR-049/052) 라이브 검증 0** | major |
| API-11 | admin `curated-*` 11개 엔드포인트 라이브 검증 0(T-223에서 별도 종결, 기능 결함은 아님) | minor |
| PMI-04 | Prometheus `/metrics`(기본 on, reload 이후 추가) reload smoke 미포함 | minor |
| PMI-05 | T-108 arm64(Odroid) multi-arch buildx 이미지 build+boot 미검증 | minor |
| API-02 | `/v1/features/batch`·`/features/nearby/by-target`(TripMate POI 계약) 미smoke(by-target은 frontend mock만) | minor |
| API-14 | `/v1/ops/providers`(+`/{provider}`) 라이브 미검증(e2e는 mock) | minor |
| API-15 | `/v1/ops/{metrics,api-call-logs,system-logs}` 라이브 미검증 | minor |
| API-17 | governance 리뷰 큐(dedup-reviews·enrichment-reviews·feature-update-requests) 라이브 미검증(dedup pending=0) | minor |
| API-19 | `/v1/debug/mois-license/{id}` 미검증(`debug/etl`은 e2e fixture로 검증됨 — 갭 아님) | minor |

## 6. 후속 분리 (T-229 등록)

라이브 스택이 필요해 T-225 범위(문서/코드 대조) 밖이다. **T-229**로 분리:

- (A) **curated 오버레이 라이브 검증**: `curated_features_refresh` materialize +
  admin/사용자 `curated-*` API + `tripmate-copy` 핸드오프 실데이터 검증. [AS-01, API-11/12]
- (B) **reload 이후 신규 표면**: Prometheus `/metrics` 라이브, arm64 buildx
  build+boot smoke. [PMI-04/05]
- (C) **smoke breadth 보강**: features/batch·nearby/by-target, ops/providers,
  ops 관측 엔드포인트, governance 리뷰 큐, debug/mois-license. [API-02/14/15/17/19]

## 7. #434 delta (포트 재기준)

T-225 분석(`66ad85f`) 후 **#434(로컬 포트를 docker-manager 기준 정렬)**가 머지돼
`25b286b`로 전진했다. 새 표준: **API 12701 · Dagster 12702 · admin UI 12705 ·
kor-travel-geo 12501**(구 12301/12302/12305/12201). T-212e 리포트와 본 리포트 §3.3의
포트 참조(12301번대)는 이제 한 세대 뒤처졌다 — **호스트 포트 config/문서 drift일 뿐,
reload 데이터 closure(row 수·정합성·P99는 포트 무관)에는 영향 없음.** #434는 신규
provider/asset/API 표면을 추가하지 않아 §3~§5 findings는 그대로 유효하다.
