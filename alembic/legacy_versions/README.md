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
cutover로 이미 `0104`를 지나왔고, 새 DB는 `0200`에서 시작한다. 여기 파일을
`versions/`로 되돌리면 두 개의 root(`0001`, `0200`)를 가진 그래프가 되어
`alembic heads`가 갈라진다.

과거 세대의 SQL을 참조할 일이 있으면 **읽기만** 하라.
`rg <패턴> alembic/legacy_versions/`.

109개 파일 전체의 경로+byte digest는
`tests/unit/test_alembic_squash_boundary.py`가 고정한다. 파일 하나라도 바꾸거나
추가·삭제하면 archive digest가 달라진다. active integration suite가 이 revision을
`upgrade`/`downgrade`/`stamp` 대상으로 되살리는 것도 같은 gate가 거부한다.

## 이 디렉터리를 지우는 조건

위 차단선이 아카이브가 아닌 다른 정본에서 금지 목록을 얻게 되면
(예: 금지 목록을 별도 데이터 파일로 물화), 그때 이 디렉터리와
`tests/unit/test_migration_immutability.py`의 `0056` sha 핀을 함께 지운다.
