"""T-VN-33 후속 — 정리·감사 write 해금 + 멱등 키를 identity triple에 맞춤.

Revision ID: 0092_tvn33_offline_cleanup
Revises: 0091_tvn33_cutover_fence

이 revision이 고치는 것은 모두 0091이 남긴 것이다.

1. ``reject_inactive_offline_upload_membership``이 DELETE와 정리 UPDATE까지 거부해
   dataset ``is_active=false`` 또는 operation ``is_enabled=false``가 되는 순간 기존
   ``ops.offline_uploads`` 행이 **영구 잠금**됐다. FK가 ``ON DELETE RESTRICT``라
   상위 scope/operation/dataset 행도 못 지우므로 탈출 경로가 없었다.
2. ``reject_inactive_provider_dataset``이 DELETE에서도 OLD쪽 활성 검사를 돌아,
   비활성 dataset의 **카탈로그 행 자체**(operation scope / operation)를 지울 수
   없었다. 1을 고쳐 upload 행을 지워도 상위 행은 그대로 남는다.
3. 같은 가드가 ``ops.managed_files``에도 붙어 있어, dataset을 비활성화하면 그
   dataset이 남긴 파일의 registry 기록을 **갱신할 수 없었다**(INSERT/UPDATE/DELETE
   전부). 그 실패는 ``file_registry.registry_guard``가 삼키므로 조용한 감사 공백이
   된다.
4. 멱등 UNIQUE가 ``(provider_dataset_id, sync_scope, checksum_sha256)`` 3열이라
   identity triple(0091이 scope PK를 pair→triple로 올렸다)과 어긋났다.

0090/0091과 같이 **forward-only**다(``downgrade``는 RuntimeError). 2·3의 함수 정의는
되돌릴 수 있지만 4는 아니다 — UNIQUE를 4열에서 3열로 좁히는 것은 데이터 의존이고,
그 충돌 상태는 upgrade()가 정상 write로 열어 준 상태다(형제 operation에 결박된 같은
checksum 두 행). 되돌릴 수 없는 단계가 하나라도 있으면 revision 전체가 되돌릴 수
없다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0092_tvn33_offline_cleanup"
down_revision: str | Sequence[str] | None = "0091_tvn33_cutover_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 활성 검사를 거는 write. ``ops.offline_uploads``에서 이 두 상태로 들어가거나
# 머무는 UPDATE만이 membership에 **새 실행**(validation/load import job)을 건다 —
# ``mark_offline_upload_validating`` / ``mark_offline_upload_loading`` /
# ``attach_offline_upload_load_job``이 그것이다. 나머지 UPDATE(uploaded/validated/
# validation_failed/loaded/load_failed/cancelled/deleting)와 DELETE는 이미 있던
# 행을 정리하는 write다.
_NEW_WORK_STATUSES: tuple[str, ...] = ("validating", "loading")


def _execute_sql_script(sql: str) -> None:
    """asyncpg prepared statement가 거부하는 복수 DDL을 현재 transaction에서 실행한다."""
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


def _offline_upload_guard_sql() -> str:
    """offline upload membership 가드 — 정리 write 면제판."""

    new_work_literals = ", ".join(f"'{status}'" for status in _NEW_WORK_STATUSES)
    return f"""
        CREATE OR REPLACE FUNCTION provider_sync.reject_inactive_offline_upload_membership()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
            requires_active boolean;
        BEGIN
            -- offline upload의 identity도 triple이다(operation_key NOT NULL +
            -- fk_offline_uploads_exact_operation_scope). 소유권 비교도 triple이라
            -- operation_key만 갈아끼워 **어느 실행에 결박됐는지**를 조용히 바꿀 수
            -- 없다. 이 검사는 정리 write에서도 면제하지 않는다 — 정리는 행을
            -- 없애거나 상태를 내리는 것이지 소유권을 옮기는 것이 아니다.
            IF TG_OP = 'UPDATE'
               AND (OLD.provider_dataset_id, OLD.sync_scope, OLD.operation_key)
                   IS DISTINCT FROM
                   (NEW.provider_dataset_id, NEW.sync_scope, NEW.operation_key) THEN
                RAISE EXCEPTION 'offline upload membership ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_scope_ownership_immutable';
            END IF;
            -- 활성 검사는 **새 작업을 여는 write**에만 건다: INSERT와,
            -- {new_work_literals}로 들어가거나 머무는 UPDATE.
            --
            -- 0091은 이 검사를 DELETE에도 걸었다. 그래서 dataset을 비활성화하거나
            -- operation을 disable하면 그 membership에 결박된 기존 upload 행이
            -- UPDATE도 DELETE도 안 되는 상태로 굳었고, FK ``ON DELETE RESTRICT``가
            -- 상위 행 삭제까지 막아 운영자에게 탈출 경로가 없었다. 가드의 목적은
            -- 비활성 membership에 **새 실행을 거는 것**을 막는 것이지 이미 있는
            -- 행의 정리를 막는 것이 아니다.
            --
            -- 정리 UPDATE까지 함께 허용해야 하는 이유: ``deleting``으로의 전이는
            -- ``OFFLINE_UPLOAD_DELETABLE_STATES``(= 진행 중이 아닌 상태)에서만
            -- 되므로, ``validating``/``loading``/``uploading``에 있던 행은 종료
            -- 상태로 내려오지 못하면 DELETE 예외만으로는 여전히 잠긴다.
            IF TG_OP = 'INSERT' THEN
                requires_active := true;
            ELSIF TG_OP = 'UPDATE' THEN
                requires_active := NEW.status IN ({new_work_literals});
            ELSE
                requires_active := false;
            END IF;
            IF requires_active AND NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'dataset scope is absent or disabled for normal writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_scope_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;
    """


def _dataset_guard_sql() -> str:
    """dataset 활성 가드 — DELETE의 OLD쪽 검사만 면제한다.

    0091 원본은 ``IF TG_OP <> 'INSERT'``로 UPDATE와 DELETE 양쪽에서 OLD쪽
    ``assert_active_provider_dataset``을 돌렸다. 그래서 dataset을 비활성화하면 그
    dataset을 참조하는 9개 테이블의 행을 **지울 수도** 없었다. UPDATE쪽 OLD 검사는
    그대로 둔다 — 계약 fixture ``inactive_dataset_existing_operation_update``가
    비활성 dataset의 operation UPDATE 거부를 executable contract로 못박고 있다.
    """

    return """
        CREATE OR REPLACE FUNCTION provider_sync.reject_inactive_provider_dataset()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id THEN
                RAISE EXCEPTION 'provider dataset ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
            END IF;
            -- DELETE는 새 실행을 거는 write가 아니라 정리다. 행을 없애는 것이
            -- 비활성 dataset에 새 작업을 기록하지 않으므로 OLD쪽 활성 검사를
            -- 건너뛴다. 참조 무결성은 FK RESTRICT 사슬이 그대로 지킨다.
            IF TG_OP = 'UPDATE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;
    """


def _managed_file_guard_sql() -> str:
    """``ops.managed_files``는 활성 검사 대상이 아니다 — 소유권 immutable만 남긴다.

    registry는 storage 객체의 거울이다. dataset을 비활성화해도 그 dataset이 남긴
    파일은 그대로 있고, 삭제·orphan·missing 기록은 새 실행이 아니라 정리와 감사다.
    0091은 이 테이블에도 ``reject_inactive_provider_dataset``을 걸어 비활성 dataset의
    파일 상태 변화를 INSERT/UPDATE/DELETE 어느 쪽으로도 적을 수 없게 만들었고,
    호출부는 ``file_registry.registry_guard``(``except Exception``)로 감싸므로 그
    실패는 로그 한 줄만 남기고 사라진다.

    소유권 immutable 검사는 유지한다 — 계약 fixture
    ``inactive_dataset_managed_file_owner_clear``가 그 거부를 못박고 있다.
    """

    return """
        CREATE FUNCTION provider_sync.reject_managed_file_dataset_rebinding()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id THEN
                RAISE EXCEPTION 'provider dataset ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        DROP TRIGGER IF EXISTS trg_managed_files_active_dataset_write ON ops.managed_files;
        CREATE TRIGGER trg_managed_files_dataset_ownership
            BEFORE INSERT OR UPDATE OR DELETE ON ops.managed_files
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_managed_file_dataset_rebinding();
    """


def _idempotency_constraint_sql() -> str:
    """멱등 UNIQUE를 identity triple + checksum 4열로 재정의한다.

    이름은 0090이 붙인 것을 유지한다 — 열 집합만 바뀐다. writer의 ``ON CONFLICT``가
    이 열 집합을 중재자로 지목하므로 ``offline_upload_repo``의 ``_RESERVE_SQL``과
    ``_GET_BY_CHECKSUM_SQL``이 같이 4열이 아니면 42P10 또는 잘못된 행을 읽는다.

    3열 → 4열. 0091이 scope PK를 triple로 올리면서 같은 (dataset, scope)에 형제
    refresh operation을 등록하는 것이 정상 write가 됐다. 그런데 멱등 키가 3열로
    남아, operation을 교체(A disable → B enable)한 뒤 같은 파일을 다시 올리면
    **이미 없어진 operation에 결박된 옛 행** 때문에 UNIQUE 위반이 났다. 형제
    membership 테이블의 identity UNIQUE도 ``operation_key``를 포함한다
    (``uq_import_job_datasets_exact_identity`` = job_id + triple,
    ``uq_feature_update_request_datasets_identity`` = request_id + triple).
    """

    return """
        ALTER TABLE ops.offline_uploads
            DROP CONSTRAINT IF EXISTS uq_offline_uploads_dataset_scope_checksum,
            ADD CONSTRAINT uq_offline_uploads_dataset_scope_checksum
                UNIQUE (provider_dataset_id, sync_scope, operation_key, checksum_sha256);
    """


def upgrade() -> None:
    _execute_sql_script(_offline_upload_guard_sql())
    _execute_sql_script(_dataset_guard_sql())
    _execute_sql_script(_managed_file_guard_sql())
    _execute_sql_script(_idempotency_constraint_sql())


def downgrade() -> None:
    raise RuntimeError("T-VN-33 is forward-only: rebuild the development database from final ETL.")
