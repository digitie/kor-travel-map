# `alembic/legacy_versions/` — 실행되지 않는 아카이브

`0001` ~ `0104` 체인 109개 파일. **alembic은 이 디렉터리를 보지 않는다** —
`alembic.ini`의 `script_location = alembic`은 `alembic/versions/`만 스캔하고,
그곳에는 `0200_schema_baseline` 하나만 있다.

## 왜 지우지 않았나

이 파일들이 **여전히 정본인 사실**이 하나 있다: "무엇이 지워졌는가."

현행 스키마에는 지워진 것이 *없다*는 사실만 남고 이름은 남지 않는다. `0097`이
`feature.features`에서 걷어낸 legacy status/delete 계열 8개 컬럼, `0104`가 지운
`data_origin` / `data_version`과 `feature.feature_versions` /
`ops.feature_change_requests` 두 테이블 — 이 이름들을 소스 코드가 다시 참조하지
못하게 막는 정적 차단선
(`tests/unit/test_tvn34c_feature_state_inventory.py`)이 그 목록을 **여기서 읽는다.**
손으로 적으면 뒤처지고, 실제로 두 번 뒤처졌다.

그 차단선은 아카이브에서 읽은 목록이 현행 head와 여전히 맞는지도 확인한다 —
누가 같은 이름의 컬럼을 되살리면 `alembic/baseline/schema.sql` 대조에서 선다.

## 왜 되살리면 안 되나

체인은 **어떤 DB에서도 다시 실행되지 않는다.** prod는 2026-08-13 in-place
cutover로 이미 `0104`를 지나왔고, 새 DB는 `0200`에서 시작한다.

여기 파일을 `versions/`로 되돌리면 alembic이 **중복 revision으로 거부한다** —
`versions/0201_squash_bridge.py`가 `0104_tvn36_final_fence`를 선언하고 여기
`0104_tvn36_final_fence.py`도 같은 id를 선언하기 때문이다. 두 디렉터리를 한
`version_locations`에 함께 담는 것도 같은 이유로 불가능하다.

과거 세대의 SQL을 참조할 일이 있으면 **읽기만** 하라.
`rg <패턴> alembic/legacy_versions/`.

## 여기를 script directory로 쓰는 곳

아카이브 세대를 **실행**해야 하는 코드는 이 디렉터리만 담은 별도 Config를 만든다
(`versions/`와 함께 담을 수 없으므로).

- `tests/integration/`의 세대별 migration 테스트 28곳 —
  `config.set_main_option("version_locations", …/"legacy_versions")`
- `src/kortravelmap/cli/_h35_schema.py:_campaign_config()` — H35 캠페인은 설계상
  target(`0079_cache_target_writer_drain`)에 앵커된 도구다. 이 때문에 **런타임
  이미지에도 이 디렉터리가 실린다**(1.6MB). `.dockerignore`로 빼면 그 도구가
  런타임에 깨지므로 그대로 둔다 — 값어치보다 새 지뢰가 크다는 판단이다.

## 이 디렉터리를 지우는 조건

위 차단선이 아카이브가 아닌 다른 정본에서 금지 목록을 얻게 되면
(예: 금지 목록을 별도 데이터 파일로 물화), 그때 이 디렉터리와
`tests/unit/test_migration_immutability.py`의 `0056` sha 핀을 함께 지운다.
