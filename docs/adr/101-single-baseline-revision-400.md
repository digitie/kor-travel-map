# ADR-101 — `300`~`313`을 단일 baseline revision `400`으로 접고, 배포 봉인을 걷어낸다

- 상태: Accepted (2026-09-23)
- 관련: ADR-090(역할 분리), ADR-100(단일 LOGIN), ADR-099(curation seal)

## 결정

활성 Alembic graph를 **revision `400` 하나**로 만든다. `down_revision = None`이고,
`alembic/baseline/schema.sql`(head `pg_dump`)과 `seed.sql`을 적용한다. `300`~`313`
열네 개와 그 사이드카 111개는 삭제한다.

같은 변경으로 그 체인을 지키던 **봉인 장치**를 걷어낸다:

- `alembic/baseline/application-*.{json,sql,sha256}` — sidecar SHA-256 manifest와
  catalog/seed receipt
- `docker/application-schema-{contract,db-contract,fresh-300,fresh-finalize,final-permit}.py`
- `scripts/{build-baseline,build-application-300-candidate,build-application-300-paired-candidate,create-application-300-fresh-oracle,compare-schema-catalogs}.sh`
- `alembic/env.py`의 `0236 → 300` one-shot handoff(capability 파일·stamp 콜백·
  destination facet 봉인)

## 왜

### 되돌릴 수 있음에 값을 치를 이유가 없다

migration 체인이 긴 이유는 하나다 — **운영 중인 DB를 그 자리에서 올려야 하기
때문**이다. 그 조건에서만 "과거의 각 시점을 재생할 수 있다"가 값어치를 갖는다.

이 저장소는 운영 중이 아니고, 데이터 보존도 요구하지 않는다. 그 조건에서 체인이 남기는
것은 값이 아니라 비용이다: 같은 사실(role graph·ACL·procedure 본문)이 열네 revision에
흩어져 서로 어긋날 자리를 만든다. 실제로 이 저장소는 그 어긋남을 여러 번 겪었다 —
`_OPTIONAL_ROUTINES`, `_SHADOW_COLUMN_GRANTS`, `_maybe_conditional`은 전부 "조정기가
두 스키마 상태에서 돈다"는 사정 하나에서 나온 조건부다.

### 봉인은 그 체인을 위한 장치였다

receipt 사슬은 `0236 → 300` 이관이 **원본을 손대지 않았음**을 증명하려고 만들었다.
이관은 끝났고, 증명할 원본이 없다. 남은 것은 "빌드 시점 해시와 배포 시점 해시가 같은가"를
확인하는 파일 다발이고, 그것이 실제로 막은 사고는 없다. 반대로 막은 것은 있다 — seed의
`route.geom` 행이 존재하지 않는 컬럼을 가리키는데, 봉인 때문에 **고칠 수 없었다**
(`tests/integration/test_override_field_paths_point_at_real_columns.py`).

### 배포 permit이 지키던 성질은 한 줄로 옮길 수 있다

`application-schema-final-permit.py`(721줄)가 root 소유 mount와 서명 파일로 지키던 것은
결국 하나다 — **런타임이 자기 이미지와 다른 스키마의 DB에 붙지 않는다.** 그 성질은
`public.alembic_version`을 직접 읽어 잴 수 있고, 지금은 런타임 privilege preflight
(`src/kortravelmap/infra/db.py`)가 세 술어로 잰다:

- `applied_alembic_heads`가 정확히 `[application_schema_head()]`인가
- 그 표를 **읽을 수** 있는가
- 그 표에 **쓸 수는 없는가** (쓸 수 있으면 스키마를 바꾸지 않고 head만 고쳐 위 검사를
  통과할 수 있다)

세 술어는 각각 따로 빨개지는 것을 확인했다(`tests/unit/test_db.py`).

## 무엇을 잃는가

- **중간 revision으로 올라오는 DB를 받지 못한다.** `0236`이든 `307`이든, 이 이미지는
  해석하지 못하고 거부한다. 고치는 방법은 DB를 새로 만드는 것뿐이다. 운영 DB가 없으므로
  지금은 비용이 0이고, 생기면 그때부터 `401`을 쌓는다.
- **이미지 신원 결박이 사라진다.** Manager가 핀한 바로 그 이미지인지 컨테이너가 스스로
  증명하지 않는다. 그건 애초에 컨테이너가 증명할 수 있는 것이 아니었고(같은 이미지가
  거짓말할 수 있다), Manager 쪽 핀 확인은 그대로다.

## 어떻게 만들었나

손으로 옮기지 않았다. 빈 DB를 `313`까지 올린 뒤 `pg_dump`로 떴고, 같은 DB에서 두 번 떠
동일한지 확인했다. 정규화는 네 가지만 한다 — 매 덤프마다 바뀌는 토큰/버전 주석 제거,
`CREATE SCHEMA IF NOT EXISTS` 치환, `search_path` 고정 제거, 그리고 **ACL 블록마다 그
블록 소유자로 role 전환**. 마지막 것이 load-bearing이다: GRANT/REVOKE는 소유자만 할 수
있고 ADR-090 role은 `NOINHERIT`이며, 소유자가 아닌 GRANT는 오류가 아니라 **경고 후
무시**다 — 즉 exit 0이 적용의 증거가 되지 못한다.

같은 덤프에서 head 오라클(`alembic/head-schema.sql`)도 함께 떴고, 그 결과가 커밋돼 있던
파일과 **바이트 동일**했다. 덤프 파이프라인이 기존 오라클을 재현한다는 확인이다.

`tests/lint/test_baseline_schema_is_not_a_contract_oracle.py`가 두 파일이 같은 head를
서술하는지 대조한다. `401`이 붙어 head가 root보다 앞서면 그 대조는 스스로 비켜난다 —
그때부터 둘이 갈리는 것이 정상이고, 등식을 요구하면 revision을 더할 때마다 재스쿼시를
강요하게 된다.

## 다시 접을 때

`400` 위에 revision이 쌓여 같은 사실이 다시 흩어지면 같은 일을 반복한다: 빈 DB를 head까지
올리고, 덤프를 뜨고, `500`으로 접는다. 그 절차의 정본은 이 ADR과 `400_schema_baseline.py`의
docstring이다 — 전용 빌더 스크립트는 두지 않는다. 2,076줄짜리 빌더를 유지하는 비용이
몇 년에 한 번 하는 작업의 비용보다 컸다는 것이 이 ADR의 출발점이기 때문이다.
