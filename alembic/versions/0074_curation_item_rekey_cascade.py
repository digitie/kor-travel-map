"""curation_item_id 재작성이 decision/import 이력을 끊지 않게 한다 (T-VN-H41).

## 왜 필요한가

dedup merge의 legacy-conflict detach(`merge_repo._DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL`)는
`feature.curation_items.curation_item_id`를 **새 UUID로 재작성**한다. `0045` 전환
트리거가 같은 UUID로 legacy row를 다시 만들 때 master의 active legacy row와 충돌하는
것을 피하려는 것이다(주석 `merge_repo.py:770-773`).

`0072`가 만든 `fk_curation_link_decisions_item`/`fk_curation_import_rows_item`은
`ON DELETE RESTRICT`이고 `ON UPDATE`를 지정하지 않아 기본값 `NO ACTION`이다.
decision이나 import row가 하나라도 달린 item을 재작성하면 그 UPDATE 자체가
FK 위반을 낸다. 컨테이너에서 재현했다 — `0072`만 적용한 DB에서 decision 1건을
가진 item의 `curation_item_id`를 바꾸면 즉시 `ForeignKeyViolationError`.

`0072`는 아직 prod에 미배포이므로 이 결함은 **이번 H35 배포로 처음 prod에 도달**한다.
`0073`의 트리거가 `source_rule` decision을 3,000건 넘게 새로 발급하므로, 배포
이후에는 dedup merge가 이 item을 건드릴 때마다 걸린다. 기존 merge 통합 테스트는
전부 `selection_origin='admin'` 픽스처를 쓰기 때문에 `0073` 트리거가 merge 경로에서
한 번도 발화하지 않았고, 그래서 이 결함이 지금까지 발견되지 않았다.

## 무엇을 하는가

decision/import row가 `curation_item_id`로 부모를 참조하는 4개 FK에
`ON UPDATE CASCADE`를 추가해, item이 재작성되면 그 이력도 같은 값으로 따라가게 한다:

1. `fk_curation_import_rows_item`
2. `fk_curation_link_decisions_item`
3. `fk_curation_link_decisions_import_row` — 합성 FK. import row 쪽도 ①로 캐스케이드된
   뒤에야 이 조합이 다시 일관되므로 같이 바꾼다.
4. `fk_curation_link_decisions_supersedes` — 자기참조 합성 FK. supersedes 사슬 전체가
   "같은 item"이라는 불변식을 이 합성 키로 강제하므로, item이 재작성되면 사슬의 모든
   행이 같은 값으로 옮겨가야 그 불변식이 유지된다.

`curation_items` 쪽의 역참조 FK 둘(`fk_curation_items_current_import_row`,
`fk_curation_items_accepted_link_decision`)은 이미 `DEFERRABLE INITIALLY DEFERRED`라
손대지 않는다 — commit 시점에는 위 4개 CASCADE가 이미 자식 쪽 값을 맞춰 놓는다.

## append-only 계약과의 충돌

CASCADE 액션은 내부적으로 자식 테이블에 평범한 `UPDATE`를 실행하고, 그 `UPDATE`는
`trg_curation_import_rows_append_only`/`trg_curation_link_decisions_append_only`를
그대로 통과한다 — `0072`가 `BEFORE UPDATE OR DELETE`를 조건 없이 거부하게 만들었기
때문이다. 그래서 `feature.reject_curation_history_mutation()`에 **정확히 하나의
예외**를 추가한다: `curation_item_id` **딱 하나만** 바뀐 `UPDATE`는 통과시킨다.
다른 컬럼이 하나라도 같이 바뀌면 여전히 거부한다 — 부모 키를 따라가는 것과 이력
자체를 고치는 것을 구분해, append-only 계약을 필요한 만큼만 좁힌다.

Revision ID: 0074_curation_item_rekey_cascade
Revises: 0073_curation_source_rule
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0074_curation_item_rekey_cascade"
down_revision: str | Sequence[str] | None = "0073_curation_source_rule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (constraint_name, table, column_sql, referent_table, referent_columns_sql)
_CASCADED_FKS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "fk_curation_import_rows_item",
        "curation_import_rows",
        "curation_item_id",
        "curation_items",
        "curation_item_id",
    ),
    (
        "fk_curation_link_decisions_item",
        "curation_link_decisions",
        "curation_item_id",
        "curation_items",
        "curation_item_id",
    ),
    (
        "fk_curation_link_decisions_import_row",
        "curation_link_decisions",
        "import_row_id, curation_item_id",
        "curation_import_rows",
        "import_row_id, curation_item_id",
    ),
    (
        "fk_curation_link_decisions_supersedes",
        "curation_link_decisions",
        "supersedes_decision_id, curation_item_id",
        "curation_link_decisions",
        "decision_id, curation_item_id",
    ),
)

_REJECT_FUNCTION_UNCONDITIONAL = """
CREATE OR REPLACE FUNCTION feature.reject_curation_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'curation import/link history is append-only'
    USING ERRCODE = '55000';
END;
$$
"""

_REJECT_FUNCTION_ALLOW_REKEY = """
CREATE OR REPLACE FUNCTION feature.reject_curation_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  -- merge의 legacy-conflict detach가 curation_items.curation_item_id를 재작성할 때,
  -- 위 4개 FK의 ON UPDATE CASCADE가 같은 문장 안에서 이 행의 curation_item_id만
  -- 따라오게 만든다. 그 부모-키 재작성은 이력 변경이 아니다 — curation_item_id
  -- **하나만** 바뀌었을 때만 통과시키고, 다른 컬럼이 하나라도 같이 바뀌면 여전히
  -- 거부한다.
  --
  -- 이 트리거 함수는 curation_import_batches(curation_item_id 컬럼이 없다)에도
  -- 그대로 붙는다. plpgsql에서 `NEW.curation_item_id`처럼 정적으로 필드를 참조하면
  -- 그 컬럼이 없는 테이블에 대해 함수가 실행될 때 UndefinedColumnError로 죽는다
  -- (실행해서 확인함). 그래서 `to_jsonb(NEW) ? 'curation_item_id'`로 **동적**으로
  -- 존재 여부를 먼저 확인하고, 나머지도 jsonb 경로로만 접근한다.
  IF TG_OP = 'UPDATE'
     AND to_jsonb(NEW) ? 'curation_item_id'
     AND (to_jsonb(NEW) ->> 'curation_item_id')
             IS DISTINCT FROM (to_jsonb(OLD) ->> 'curation_item_id')
     AND to_jsonb(NEW) - 'curation_item_id' = to_jsonb(OLD) - 'curation_item_id'
  THEN
    RETURN NEW;
  END IF;

  RAISE EXCEPTION 'curation import/link history is append-only'
    USING ERRCODE = '55000';
END;
$$
"""


def upgrade() -> None:
    # `0073`의 backfill이 DEFERRABLE INITIALLY DEFERRED인
    # `fk_curation_items_accepted_link_decision`(0072)을 건드려 놓은 채로 트랜잭션이
    # 이어진다(alembic은 기본적으로 전체 upgrade를 한 트랜잭션에서 실행). PostgreSQL은
    # 그런 지연된 제약 이벤트가 `curation_items`에 걸려 있는 동안 그 테이블(또는 그것을
    # 참조하는 FK)에 대한 ALTER TABLE을 거부한다("cannot ALTER TABLE ... because it has
    # pending trigger events" — 컨테이너에서 실제로 이 에러로 재현했다). 아래 DROP/ADD
    # CONSTRAINT 전에 지연된 검사를 지금 강제로 통과시킨다 — 데이터는 이미 정합하므로
    # 실패하지 않는다.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    for name, table, columns, referent_table, referent_columns in _CASCADED_FKS:
        op.execute(f"ALTER TABLE feature.{table} DROP CONSTRAINT {name}")
        op.execute(
            f"ALTER TABLE feature.{table} "
            f"ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({columns}) "
            f"REFERENCES feature.{referent_table} ({referent_columns}) "
            f"ON DELETE RESTRICT ON UPDATE CASCADE"
        )
    op.execute(_REJECT_FUNCTION_ALLOW_REKEY)


def downgrade() -> None:
    # upgrade()와 같은 이유 — 같은 트랜잭션에서 먼저 실행된 마이그레이션(예: 0073의
    # downgrade)이 지연된 FK 이벤트를 curation_items에 남겨 뒀을 수 있다.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    op.execute(_REJECT_FUNCTION_UNCONDITIONAL)
    for name, table, columns, referent_table, referent_columns in _CASCADED_FKS:
        op.execute(f"ALTER TABLE feature.{table} DROP CONSTRAINT {name}")
        op.execute(
            f"ALTER TABLE feature.{table} "
            f"ADD CONSTRAINT {name} "
            f"FOREIGN KEY ({columns}) "
            f"REFERENCES feature.{referent_table} ({referent_columns}) "
            f"ON DELETE RESTRICT"
        )
