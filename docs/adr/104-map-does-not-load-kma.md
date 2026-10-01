# ADR-104: Map은 KMA(기상청)를 적재하지 않는다 — KMA는 kor-travel-weather가 소유한다

- 상태: accepted (2026-10-01, 소유자 결정)
- 관련: ADR-010(weather 두 축, 이관 문서), ADR-045(Dagster code location), ADR-088(operation 카탈로그
  정본), ADR-102(migration 전진 배포), `docs/etl/upstream-quota.md`

### 맥락

- data.go.kr 서비스 키를 kor-travel-weather와 함께 쓰고, 한도는 서비스가 아니라 **오퍼레이션마다**
  걸린다(`docs/etl/upstream-quota.md` §1). weather는 KMA 단기·초단기·중기·특보를 자기 Dagster에서
  적재한다.
- Map은 2026-09-09부터 KMA 자동 적재를 **코드 목록으로만** 끄고 있었다
  (`DISABLED_FEATURE_LOAD_SCHEDULES` → schedule 미생성, `DISABLED_FEATURE_LOAD_OPERATION_KEYS` →
  큐의 targeted 요청 skip). 그 장치는 의도적으로 **능력을 남겼다** — Dagster UI launch·백필,
  `provider_dataset` scope 큐 요청, C7 live 인수의 `external_system:c7-e2e` 요청은 그대로 KMA를
  불렀다. DB 카탈로그도 KMA refresh operation 5개를 enabled로 들고 있어 `/ops/datasets`가 갱신
  capability를 냈다.

### 결정

1. **Map Dagster에서 KMA 적재 경로를 지운다.** 끄는 것이 아니라 정의째 없앤다.
   - `kortravelmap.dagster.kma_weather` 모듈(asset 5종·결과 타입·격자 루프)과 그 job·schedule.
   - `resources.py`의 `kma_weather_client_factory`·`kma_datagokr_client`·`kma_weather_alert_records`,
     `provider_fetchers.fetch_kma_weather_alerts`.
   - 큐 runner(`feature_update_runner.py`)의 KMA spec 5개와 resource 팩토리, handler registry
     (`providers/feature_operation_registry.py`)의 KMA binding 5개.
   - `DISABLED_FEATURE_LOAD_SCHEDULES`의 KMA 이름 5개 — 시계도 능력도 없으니 "끈 목록"에 남을 이름이
     아니다. 목록 자체는 AirKorea·미신청 데이터셋 때문에 남는다.
2. **DB 카탈로그에서 KMA 적재 operation을 끈다** — migration `401_retire_map_kma_refresh`.
   provider가 `python-kma-api`인 dataset의 `refresh`·`feature_load` operation을 `is_enabled = false`로
   내린다. 이름이 아니라 **provider 정체성**으로 고르고, 남은 enabled 행이 있으면 실패한다.
   API 요청 membership(`_ACTIVE_DATASET_MEMBERSHIPS_SQL`)·`/ops/datasets` capability·offline upload
   후보·sync state가 모두 `operation.is_enabled`로 join하므로 이것이 API·UI launch 경로를 닫는다.
3. **지우지 않는 것.**
   - 카탈로그 행(operation·scope·dataset): import job·요청·sync state의 exact FK가 가리킨다. dataset은
     `is_active`로 남아 이미 적재된 KMA feature·weather fact·notice 읽기가 그대로 된다.
   - `preview` operation과 `api/etl_fixtures.py`의 KMA fixture: fixture-only이고 외부 호출이 0이다.
   - `kortravelmap.providers.kma`의 변환·정체성 계약(Protocol, 변환 함수, dataset key, alert
     natural key): 위 preview와 기존 데이터의 정체성이 그것을 쓴다(ADR-006 — wrapper가 아니라 변환).
     Dagster 설정 전용이던 `parse_weather_extra_points`·`parse_mid_region_features`·
     `KmaMidRegionSpec`는 지웠다.
4. **함께 지운 죽은 코드**: settings `kma_weather_extra_points`·`kma_weather_max_grids_per_run`·
   `kma_mid_region_features`·`kma_weather_alert_lookback_days`(설정은 `extra="ignore"`라 남은 env는
   무해하다), KMA 대상 좌표 조회(client `list_poi_cache_target_coords` 등 4개와 repo 함수),
   asset 한국어 라벨·API 기본 cron 표의 KMA 항목.
5. **재도입 방지 검사** `packages/kor-travel-map-dagster/tests/test_map_dagster_has_no_weather.py` —
   이름이 아니라 정체성과 효과에 결박한다.
   - 정체성: 시드 카탈로그에서 `python-kma-api` 소유 operation key를 유도하고, Definitions의 job·
     schedule·sensor·asset, handler registry, 큐 runner(`provider_dataset` scope)가 그 key를
     받지 않는지 본다.
   - 효과: Map 런타임 소스(`src/`, `packages/*/src`)가 KMA client 패키지(핀된 provider 표면
     manifest의 `package`)를 import하거나 KMA data.go.kr 서비스 경로(`1360000`)를 쓰지 않는지 본다.
   - DB 축은 `tests/integration/test_provider_catalog.py::test_head_enables_no_kma_load_operation`이
     head DB에서 KMA enabled 적재 operation이 0인지 본다.

### 결과

- Map의 KMA upstream 호출은 0이다. 키의 KMA 오퍼레이션 한도는 weather가 전부 쓴다.
- 이미 적재된 KMA feature는 읽히지만 더는 갱신되지 않는다. (2026-10-01 prod 실측: Map DB에 KMA
  feature 0건, KMA sync state 0행, KMA 멤버십을 가진 import job·요청 0건 — 잃는 갱신이 없다.)
- C7 prod live 러너(`scripts/run-c7-prod-live-e2e.sh`)의 KMA write spec 셋(`ops-c7-kma-*-write`)은
  이제 요청 단계에서 거부된다(카탈로그에 enabled operation이 없다). 러너는 2026-09-09부터 이미 돌 수
  없었다 — schedule allowlist가 가리키는 KMA schedule이 그날부터 만들어지지 않았다. 배포 게이트
  (`scripts/n150/chain16.sh`의 D1·D2)는 이 러너를 쓰지 않는다. 러너 가족의 퇴역 또는 비-KMA 재기반은
  후속 결정으로 남긴다.
- 되살리려면 새 ADR과 새 migration으로 한다 — 401은 forward-only다.

### 후속(이 결정 밖)

- `pyproject.toml`의 `python-kma-api` 의존 핀 제거(provider 표면 manifest·적합성 게이트와 함께).
- Manager compose의 `KOR_TRAVEL_MAP_KMA_WEATHER_*` env 제거(무해하지만 죽은 값).
- C7 러너 가족(`run-c7-prod-live-e2e.sh`, `ops-c7-*` spec, 관련 unit 테스트) 정리.
