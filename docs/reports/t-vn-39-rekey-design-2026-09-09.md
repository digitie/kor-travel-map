# T-VN-39 재키 설계 보고서 (2026-09-09)

이 항목의 첫 설계 문서다. 착수 전 조사에서 `docs/reports/`에 재키 관련 파일이 0건,
`docs/journal.md`에 `T-VN-39` 언급이 0건이었다.

## 1. 본체는 재타입이 아니라 멱등 앵커 교체다

`feature.features.feature_id`를 uuid로 바꾸면 **둘 중 하나가 반드시** 일어난다.

| writer가 보내는 값 | 결과 |
|---|---|
| provider가 계산한 `f_*` 그대로 | 22P02 (즉시 실패, 시끄럽다) |
| 새 UUIDv7 | `ON CONFLICT (feature_id) DO NOTHING`이 **영원히 안 걸린다** |

후자는 DDL 오류도 타입 오류도 내지 않는다. 1회 적재만 하는 테스트는 전부 초록이고,
증상은 **두 번째 ETL**에서 처음 나온다. 그래서 identity 해석 재설계는 재키의 부수
효과가 아니라 본체다. 축은 ADR-098이 정했다.

## 2. 축을 세 번 틀렸고 세 번 다 실측이 잡았다

| # | 틀린 것 | 무엇이 잡았나 |
|---|---|---|
| 1 | `source_links`의 `source_role='primary'`에 `UNIQUE (source_entity_key)` | **통합 1179건 중 17건 red.** identity 이행 중에는 구·신 Feature가 둘 다 primary다 |
| 2 | 축 자체를 `source_entity_key`로 잡은 것 | `providers/opinet.py` — entity id는 제품별, 자연키는 주유소별이고 가격이 **같은 anchor Feature에 누적**된다(N:1) |
| 3 | 루틴을 정규식으로 치환 | `fence_features_identity_update`가 **조건절 중복 + 오류 메시지 오염**. 컴파일은 되고 뜻만 틀린다 |

세 번 다 "단위 테스트 초록"으로는 못 잡았다. 1번은 단위 게이트 24건이 통과한 뒤
통합에서 터졌다.

## 3. 경계를 넘는 `feature_uuid`는 지우지 않는다 — **값을 바꾼다**

재키가 `feature.features.feature_uuid` **컬럼**을 없애지만, 그 이름이 붙은 **출력**은
소비자 계약이다. 실측:

- `feature_uuid`를 읽는 API 경로가 다수(`identity_projection.py:27`,
  `routers/features.py`·`admin_features.py`·`curations.py` 여러 곳).
- 소비 모델 중 `extra="forbid"`가 **573개**. 키를 지우면 즉시 거부된다.
- `ops.feature_reference_reconciliation_events`는 append-only라 payload 모양이
  **영구히 두 가지**가 된다 — 필드 삭제로는 고칠 수 없다.

**규칙**:

| 자리 | 처분 |
|---|---|
| jsonb payload 키, `RETURNS TABLE` 컬럼, API 응답 필드 | **유지**하고 값을 `CAST(feature_id AS text)`로 공급 |
| 프로시저 `OUT o_feature_uuid` (내부 Python 호출자만) | 계약(target §3)이 지우라 했으므로 **삭제**하고 호출자를 고친다 |
| 테이블 컬럼 | 삭제(또는 텍스트 짝이 없으면 `feature_id`로 개명) |

2026-09-09 1차 재작성은 22개 루틴 **전부에서** `feature_uuid`를 0으로 지웠고 그중
**9개가 이 경계를 넘었다.** 체계적 결함이지 우발이 아니다.

## 4. 실측된 재키 규모

전부 `alembic/head-schema.sql`에서 유도했다. 숫자를 원장에 박지 않는다 — 2026-09-08의
"인덱스 57"이 실측 59와 어긋났다.

| 항목 | 수 |
|---|---|
| 재타입 컬럼 | 34 (shadow 유도 13 · alias 조회 21) |
| shadow 컬럼 삭제 | 13 |
| 컬럼 개명 | 3 (`manual_feature_purge_records` 2, `tvn36_legacy_freeze_preflight_manifest` 1) |
| DROP해야 하는 FK | 40 (features 참조 34 + 2차 파급 6) |
| 재생성 FK | 34 (composite 11 중 6은 기존 FK에 흡수되어 영구 삭제) |
| 고쳐야 하는 루틴 | 34 (본문 `feature_uuid` 22 · text 시그니처 20, 최대 598줄) |

## 5. DDL의 함정 셋

1. **`ALTER COLUMN ... USING`은 서브쿼리를 못 받는다.** alias 조회가 필요한 21개
   컬럼을 서브쿼리로 쓰면 마이그레이션이 통째로 실패한다. 함수로 감싸고, 매칭 실패를
   **조용한 NULL이 아니라 RAISE**로 만든다. 임시 컬럼 추가/UPDATE/DROP 방식이었다면
   그 21개 컬럼의 인덱스·제약을 전부 다시 열거해야 했다.
2. **`ALTER COLUMN TYPE`이 인덱스·CHECK를 자동 재구축한다.** 인덱스 59개를 열거할
   필요가 없다. 단 `DROP COLUMN`이 조용히 함께 지우는 둘은 재생성해야 한다 —
   `ck_feature_reference_reconciliation_events_replacement`,
   `idx_manual_provider_dedup_cases_decision_fence`.
3. **뷰 `feature.public_features`의 조인 5곳이 `((x.feature_id)::text = (core.feature_id)::text)`.**
   그대로 재생성하면 결과는 맞고 **인덱스만 죽는다.** CI는 0행이라 관측되지 않고
   prod에서만 느려진다.

## 6. 검사기가 낡아 있었다 — 재키보다 먼저 고쳤다

`alembic/baseline/schema.sql`은 rev 300 시점 덤프인데 유도형 검사기 다섯이 거기서
현행 계약을 유도했다. 루틴 본문 수가 baseline 155 vs head 163이고,
`uq_manual_feature_identity_claims_exact`를 baseline은 UNIQUE **제약**으로 head는 부분
유니크 **인덱스**로 본다 — 낡음이 "덜 본다"에 그치지 않고 **모양을 틀리게 본다.**

`alembic/head-schema.sql`을 오라클로 세우고 최신성 게이트와 재발 차단 lint를 달았다.

## 7. 부수로 잡은 함정

- **revision id는 32자 이하여야 한다.** `alembic_version.version_num`이 `varchar(32)`라
  35자 이름은 DDL을 **전부 성공시킨 뒤** stamp에서 죽고, 통합 전량이 setup error로
  뒤덮인다. 진단(`StringDataRightTruncationError`)이 revision 이름을 가리키지 않는다.
- **CHECK 식은 DB와 ORM에서 다르게 렌더될 수 있다.** `position(x in y)`(SQL 표준)를
  PostgreSQL이 그 형태로 보존해 deparse하므로 migration의 함수형과 갈리고
  `alembic check`가 drift로 잡는다. 양쪽을 `strpos`로 맞춘다.
- **`tests/integration/test_postgres_role_bootstrap_on_existing_db.py` 19건이 통합
  전량에서만 실패**하는 것은 회귀가 아니라 n150 메모리 압박이다(테스트마다 자체
  컨테이너, free 0 / available 4GB). 격리 실행은 양쪽 브랜치 모두 19/19 통과한다.
- **geo live 5건**은 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` 미설정이었다. prod에
  결선된 키(32자)로 5/5 통과한다. **그 키는 VWorld 키(36자)와 다르다** — geo가 같은
  형식의 자체 키를 발급하고, VWorld 키를 넣으면 쓰레기 키와 똑같이 401이다.

## 8. 남은 것

- 루틴 23개 재작성본에 적대 검증 29건 반영 (§3 규칙이 그중 9건을 한꺼번에 푼다)
- 재키 DDL 한 트랜잭션 + provider identity 백필 + wrapper 프로시저
- `db.py`·`runtime_privileges.py`의 시그니처·컬럼 리터럴
- 계약 핀과 fingerprint 재실측
- prod 배포 + live e2e UI

## 8-1. 남은 변경 표면 (2026-09-09 실측)

수치는 **언급 수(파일 수)**다. 전부가 수정 대상은 아니지만 전부 확인 대상이다.

| 영역 | `f_*` 리터럴 | `feature_uuid` 참조 | `CAST(... AS text)` | `::regprocedure` |
|---|---|---|---|---|
| `src` | 15(5) | 374(15) | 103(16) | 15(1) |
| `packages` | 52(11) | 200(24) | 0 | 0 |
| `tests` | 433(59) | 359(38) | 29(13) | 31(10) |
| `scripts` | 12(3) | 15(1) | 13(1) | 1(1) |

`packages`의 `f_*` 52건은 대부분 **mock e2e spec**이라 백엔드를 타지 않는다 —
재키로 깨지지 않는다(다만 실제 계약과 다른 세계를 시뮬레이션한다는 사실은 남는다).

## 8-2. 원자성 — 이 조각들은 따로 착지할 수 없다

아래는 재키와 **같은 커밋**이어야 한다. 먼저 바꾸면 현행 스키마에서 깨지고, 나중에
바꾸면 재키 직후 깨진다.

| 조각 | 왜 원자적인가 |
|---|---|
| `feature_subtype.py`의 `feature_uuid` 배선 | subtype 표의 컬럼이 NOT NULL이다 — 지금 빼면 INSERT가 죽고, 재키 후 남기면 42703 |
| `db.py` 시그니처 리터럴 12 | startup preflight가 live DB와 양방향 대조한다 |
| `runtime_privileges.py` 컬럼 GRANT | 없는 컬럼에 GRANT하면 42703으로 ACL 재조정 전체가 롤백된다 |
| `create_*` 프로시저 호출자의 `o_feature_uuid` | OUT 파라미터가 사라진다 |
| keyset `CAST(... AS text)` | `uuid > text`는 42883 |

그래서 브랜치는 재키가 착지할 때까지 **의도적으로 red**다. 게이트는 그 시점의 n150
통합 전량이다.
