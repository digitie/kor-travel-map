"""433: tracking 장부는 L만, 단건 writer는 regime에서만 P, 418 GRANT를 소유자로 다시 낸다.

- WI-1: 큐레이션을 확정하는 쓰기만 P EX→L이다(권위 finish의 seal, SUCCESS 완결 전이).
  fill-starts·terminal은 L만, finish는 권위 여부로, 취소 전이는 SUCCESS 완결 인자로
  고른다. 430 write-prefix guard도 같은 분류로 좁힌다.
- DC-1: 414~418 단건·관리 writer 14개의 첫 진입을 regime 진입으로 바꾼다. provider 증거를
  먼저 잡는 넷(M05 셋·재활성화)은 epoch=0에서도 P SH로 적재와 직렬화한다.
  첫 활성화는 P EX 바로 뒤 epoch 표를 먼저 잠가 진행 중인 writer를 drain한다.
  epoch=0이면 P가 없고 epoch>0이면 P EX다. M05는 Feature FOR UPDATE 전에 provider
  source 증거를 적재와 같은 순서로 FOR SHARE한다.
- WI-3: 418의 GRANT는 grant option 없는 schema owner로 돌아 아무것도 주지 않았다.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from sqlalchemy import text

from alembic import op

revision: str = "433_protocol_entry_narrowing"
down_revision: str | None = "432_rest_snapshot_atomic"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA_OWNER: Final = "ktm_feature_schema_owner"
_STATE_OWNER: Final = "ktm_feature_state_procedure_owner"
_COMMAND_OWNER: Final = "ktm_curation_command_owner"
_DEDUP_OWNER: Final = "ktm_manual_provider_dedup_procedure_owner"
_REQUEST_OWNER: Final = "ktm_feature_request_procedure_owner"
_MANUAL_OWNER: Final = "ktm_manual_feature_procedure_owner"
#: canonical advisory_lock_key('kortravelmap:pipeline-lineage:mutation')(424와 같다).
_LINEAGE_KEY: Final = 6832465333779826081


class _Routine:
    """432 head의 정본 정의 하나. 시그니처는 regprocedure로, 본문은 SHA-256으로 고정한다.

    dataclass를 쓰지 않는다 — lint가 migration을 ``sys.modules`` 등록 없이 읽어 들이면
    ``from __future__ import annotations`` 아래의 dataclass 처리가 실패한다.
    """

    __slots__ = ("body_sha256", "edits", "kind", "owner", "security_definer", "signature")

    def __init__(
        self,
        signature: str,
        owner: str,
        kind: str,
        security_definer: bool,
        body_sha256: str,
        edits: tuple[tuple[str, str], ...],
    ) -> None:
        self.signature = signature
        self.owner = owner
        self.kind = kind
        self.security_definer = security_definer
        self.body_sha256 = body_sha256
        self.edits = edits


_TRACKING_EX: Final = "\nBEGIN\n  PERFORM ops.lock_provider_feature_tracking_protocol(true);\n"
_TRACKING_LEAF: Final = "\nBEGIN\n  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
_PROTOCOL_EX: Final = "\nBEGIN\n  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
_SINGLE_WRITER: Final = "\nBEGIN\n  PERFORM ops.lock_single_feature_writer_protocol();\n"
#: provider source 증거를 잡는 관리 writer(M05·재활성화). epoch=0에서도 P SH로 적재(P EX)와
#: 직렬화한다 — 적재는 한 transaction에서 bundle을 차례로 쓰므로 Feature를 쥔 채 다음 head를
#: 갱신한다. 증거를 먼저 잡고 Feature를 기다리는 writer와 P 없이 겹치면 순환이다.
_EVIDENCE_WRITER: Final = "\nBEGIN\n  PERFORM ops.lock_provider_evidence_writer_protocol();\n"
#: 첫 활성화는 P EX 바로 뒤 epoch 표를 가장 먼저 잠근다. 보호 표 25개를 차례로 잠그다 epoch
#: 표에서 기다리면, 진입만 지난 epoch=0 writer의 다음 DML이 이미 잠근 표에서 막혀 순환한다.
_ACTIVATION_OLD: Final = "\nBEGIN\n    PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
_ACTIVATION_NEW: Final = (
    "\nBEGIN\n    PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
    "    -- 433 DC-1: epoch=0 단건 writer는 진입에서 epoch 표 ACCESS SHARE를 쥔다. 다른 표보다\n"
    "    -- 먼저 이 표를 잠가 진입한 writer는 끝까지 쓰고, 새 진입은 여기서 새 epoch를 기다린다.\n"
    "    LOCK TABLE feature.provider_field_policy_epoch IN ACCESS EXCLUSIVE MODE;\n"
)

_FINISH_OLD: Final = (
    _TRACKING_EX
    + "  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN\n"
    "    RAISE EXCEPTION 'provider membership command requires provider executor'\n"
    "      USING ERRCODE = '42501';\n"
    "  END IF;\n"
    "  IF p_authoritative_snapshot_complete IS NULL THEN\n"
    "    RAISE EXCEPTION 'provider membership completion kind is required'\n"
    "      USING ERRCODE = '22023';\n"
    "  END IF;\n"
)
_FINISH_NEW: Final = (
    "\nBEGIN\n"
    "  IF p_authoritative_snapshot_complete IS NULL THEN\n"
    "    RAISE EXCEPTION 'provider membership completion kind is required'\n"
    "      USING ERRCODE = '22023';\n"
    "  END IF;\n"
    "  -- 433 WI-1: 권위 완료(seal)만 P EX 뒤 L, 비권위 완료는 장부 L만 잡는다.\n"
    "  PERFORM ops.lock_provider_feature_tracking_protocol(p_authoritative_snapshot_complete);\n"
    "  IF NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN\n"
    "    RAISE EXCEPTION 'provider membership command requires provider executor'\n"
    "      USING ERRCODE = '42501';\n"
    "  END IF;\n"
)
_CANCEL_TRANSITION_NEW: Final = (
    "\nBEGIN\n"
    "  -- 433 WI-1: root 완결을 부르는 SUCCESS 완결 인자 조합만 P EX 뒤 L이다.\n"
    "  PERFORM ops.lock_provider_feature_tracking_protocol(\n"
    "    p_result IS NOT DISTINCT FROM 'already_terminal'\n"
    "    AND p_target_status IS NOT DISTINCT FROM 'done'\n"
    "    AND p_dagster_terminal_status IS NOT DISTINCT FROM 'SUCCESS');\n"
)
_CANCEL_GUARD_OLD: Final = "  v_need_final boolean:=true;\n"
_CANCEL_GUARD_NEW: Final = (
    "  -- 433 WI-1: 취소 원장 쓰기는 L만 요구한다. P를 쥐었다면 EX여야 한다.\n"
    "  -- root 완결을 부르는 SUCCESS 전이는 정의 자체가 P EX 뒤 L을 먼저 잡는다.\n"
    "  v_need_final boolean:=false;\n"
)
_OPERATION_GUARD_OLD: Final = (
    "  v_need_final := TG_OP='DELETE';\n"
    "  IF TG_OP<>'DELETE' THEN\n"
    "    v_need_final := v_need_final OR NEW.status IN ('done','failed','cancelled');\n"
    "  END IF;\n"
    "  IF TG_OP<>'INSERT' THEN\n"
    "    v_need_final := v_need_final OR OLD.status IN ('done','failed','cancelled');\n"
    "  END IF;\n"
)
_OPERATION_GUARD_NEW: Final = (
    "  -- 433 WI-1: P EX 뒤 L은 큐레이션을 확정하는 쓰기(root 완료, 권위 child 완료)와\n"
    "  -- 삭제뿐이다. 실패·취소·비권위 완료·marker·start 보충은 장부 쓰기라 L만 요구한다.\n"
    "  v_need_final := TG_OP='DELETE';\n"
    "  IF TG_OP<>'DELETE' AND NEW.status = 'done'\n"
    "     AND (TG_OP='INSERT' OR OLD.status IS DISTINCT FROM 'done') THEN\n"
    "    v_need_final := NEW.kind = 'provider_feature_load_run'\n"
    "      OR COALESCE(NEW.payload ->> 'authoritative_snapshot_complete', '') = 'true';\n"
    "  END IF;\n"
    "  -- 완결된 root를 다시 바꾸는 쓰기도 확정 쓰기다(완결을 되돌릴 수 없게 P EX).\n"
    "  IF TG_OP='UPDATE' AND OLD.kind = 'provider_feature_load_run' AND OLD.status = 'done' THEN\n"
    "    v_need_final := true;\n"
    "  END IF;\n"
)

#: M05가 Feature 두 행을 잠그기 전에 provider 쪽 primary source 증거를 잠근다.
#: 순서는 provider 적재·``lock_current_provider_feature_source_evidence``와 같다
#: (entity/record/head → link → Feature). dataset 행은 잠그지 않는다 — M05 owner에게 그
#: 표의 권한이 없고, M05가 기다리지 않는 행은 순환을 만들지 못한다. head가 그사이 넘어가면
#: READ COMMITTED 재검사가 최신 head를 잠근 채 그 행을 건너뛴다. 실패 판정은 기존 본문이 한다.
_M05_EVIDENCE_PRELOCK: Final = """    -- 433 DC-1: regime 전에는 P가 없다.
    -- provider 적재와 같은 순서로 source 증거(entity/record/head 다음 link)를
    -- Feature보다 먼저 잡는다.
    FOR v_evidence IN
        SELECT link.source_entity_key
        FROM provider_sync.source_links AS link
        WHERE link.feature_id = {provider}
          AND link.source_role = 'primary'
        ORDER BY link.source_entity_key COLLATE "C"
    LOOP
        PERFORM 1
        FROM provider_sync.source_entities AS entity
        JOIN provider_sync.source_entity_heads AS head
          ON head.source_entity_key = entity.source_entity_key
        JOIN provider_sync.source_records AS record
          ON record.source_entity_key = head.source_entity_key
         AND record.source_record_key = head.current_source_record_key
        WHERE entity.source_entity_key = v_evidence.source_entity_key
        FOR SHARE OF entity, record, head;
        PERFORM 1
        FROM provider_sync.source_links AS link
        WHERE link.feature_id = {provider}
          AND link.source_entity_key = v_evidence.source_entity_key
        FOR SHARE;
    END LOOP;
"""
_M05_DECLARE_OLD: Final = "    v_source record;\n"
_M05_DECLARE_NEW: Final = "    v_source record;\n    v_evidence record;\n"
_M05_RECORD_FEATURES: Final = """    PERFORM 1
    FROM feature.features AS locked
    WHERE locked.feature_id IN (p_manual_feature_id, p_provider_feature_id)
    ORDER BY locked.feature_id
    FOR UPDATE;
"""
_M05_RESOLVE_FEATURES: Final = """    PERFORM 1
    FROM feature.features AS locked
    WHERE locked.feature_id IN (v_case.manual_feature_id, v_case.provider_feature_id)
    ORDER BY locked.feature_id
    FOR UPDATE;
"""


def _single_writer(signature: str, owner: str, body_sha256: str) -> _Routine:
    return _Routine(signature, owner, "p", True, body_sha256, ((_PROTOCOL_EX, _SINGLE_WRITER),))


def _evidence_writer(signature: str, owner: str, body_sha256: str) -> _Routine:
    edits = ((_PROTOCOL_EX, _EVIDENCE_WRITER),)
    return _Routine(signature, owner, "p", True, body_sha256, edits)


#: 432 head에서 산출한 정본. 하나라도 다르면 아무것도 바꾸지 않고 실패한다.
_ROUTINES: Final[Mapping[str, _Routine]] = {
    # ── WI-1 tracking prefix ────────────────────────────────────────────────
    "ops.fill_provider_cancellation_starts_command": _Routine(
        "ops.fill_provider_cancellation_starts_command(uuid,text,timestamp with time zone)",
        _COMMAND_OWNER,
        "f",
        True,
        "d4c3b1f6ec12d7a1d1e0a7380af131aee4e471676efadb0a06c87dbf39fe8708",
        ((_TRACKING_EX, _TRACKING_LEAF),),
    ),
    "ops.transition_provider_feature_operation_terminal_command": _Routine(
        "ops.transition_provider_feature_operation_terminal_command("
        "uuid,text,text,text,text,timestamp with time zone,timestamp with time zone,boolean)",
        _COMMAND_OWNER,
        "p",
        True,
        "2de51e4f2d396469a5c3e564fc22c88aed92bcd7c438a1c68fd1a6a060362fb8",
        ((_TRACKING_EX, _TRACKING_LEAF),),
    ),
    "ops.finish_provider_feature_membership_command": _Routine(
        "ops.finish_provider_feature_membership_command("
        "uuid,bigint,text,text,boolean,timestamp with time zone)",
        _COMMAND_OWNER,
        "p",
        True,
        "f54034d6113ab3a9f2d9379ddf4ade459f2b03ca2e2642ee5e6024287f62ff91",
        ((_FINISH_OLD, _FINISH_NEW),),
    ),
    "ops.transition_provider_cancellation_job_command": _Routine(
        "ops.transition_provider_cancellation_job_command(uuid,uuid,text,text[],text,text,text,"
        "timestamp with time zone,timestamp with time zone,boolean,text,text[])",
        _COMMAND_OWNER,
        "f",
        True,
        "7fa30f72d34ed02e468ccdb401d7dc9722089ab7ce5ea8d3e30f3ab86c628bf7",
        ((_TRACKING_EX, _CANCEL_TRANSITION_NEW),),
    ),
    "ops.reject_pipeline_cancellation_prefix": _Routine(
        "ops.reject_pipeline_cancellation_prefix()",
        _SCHEMA_OWNER,
        "f",
        False,
        "4e1b65c81bdc59068f1abb66101985edef670bb4eb33167a6c5defc8d36f32c9",
        ((_CANCEL_GUARD_OLD, _CANCEL_GUARD_NEW),),
    ),
    "ops.reject_provider_feature_operation_raw_dml": _Routine(
        "ops.reject_provider_feature_operation_raw_dml()",
        _SCHEMA_OWNER,
        "f",
        False,
        "6adc2a65e0e01dff38c79b67908ff7039f925bd173bde0ec1edeecfde66a5b4a",
        ((_OPERATION_GUARD_OLD, _OPERATION_GUARD_NEW),),
    ),
    # ── DC-1 단건·관리 writer(414 M05) ──────────────────────────────────────
    "feature.record_manual_provider_dedup_candidate": _Routine(
        "feature.record_manual_provider_dedup_candidate(uuid,uuid,jsonb,jsonb)",
        _DEDUP_OWNER,
        "p",
        True,
        "3ce2fd66671e2fff9758f48a26907eb6f55d519f3ec6b408606e287dcf048477",
        (
            (_PROTOCOL_EX, _EVIDENCE_WRITER),
            (_M05_DECLARE_OLD, _M05_DECLARE_NEW),
            (
                _M05_RECORD_FEATURES,
                _M05_EVIDENCE_PRELOCK.format(provider="p_provider_feature_id")
                + _M05_RECORD_FEATURES,
            ),
        ),
    ),
    "feature.resolve_manual_provider_dedup_case": _Routine(
        "feature.resolve_manual_provider_dedup_case(uuid,text,text,bigint,bigint,uuid,text,text,bigint)",
        _DEDUP_OWNER,
        "p",
        True,
        "2b4fda6088f19aee1952f593239b6b77e338e8bc5169392bfd719ccc00866b37",
        (
            (_PROTOCOL_EX, _EVIDENCE_WRITER),
            (_M05_DECLARE_OLD, _M05_DECLARE_NEW),
            (
                _M05_RESOLVE_FEATURES,
                _M05_EVIDENCE_PRELOCK.format(provider="v_case.provider_feature_id")
                + _M05_RESOLVE_FEATURES,
            ),
        ),
    ),
    "feature.resolve_manual_provider_dedup_case_v2": _evidence_writer(
        "feature.resolve_manual_provider_dedup_case_v2("
        "uuid,text,text,bigint,bigint,uuid,text,text,bigint)",
        _DEDUP_OWNER,
        "fd679983218c28cfc9b3a8a2a89adbc64cc8a0fbf26574afe91edbf2b81ed3c9",
    ),
    # ── DC-1 첫 활성화의 drain 순서 ──
    "feature.activate_provider_field_policy": _Routine(
        "feature.activate_provider_field_policy(uuid,bigint,text[])",
        _STATE_OWNER,
        "p",
        True,
        "6d77dfef6816f1844995e462a2878801cdca84343eb8bd7c53eb46d4f8564f26",
        ((_ACTIVATION_OLD, _ACTIVATION_NEW),),
    ),
    # ── DC-1 (415 state/lifecycle) ──────────────────────────────────────────
    "feature.transition_admin_feature_state": _single_writer(
        "feature.transition_admin_feature_state(uuid,text,text,text,bigint,text,text,text)",
        _STATE_OWNER,
        "315ba346bf74f5a7070c3a9572ac1b8d69c5cbfec08fbc5675db3b78fb381f81",
    ),
    "feature.reactivate_admin_feature_state": _evidence_writer(
        "feature.reactivate_admin_feature_state(uuid,bigint,text,text,bigint,text,text)",
        _STATE_OWNER,
        "8dc92d2732f4df5b9ce725e7a87a412b649aedd15b5df96d3f2cd5267a431de5",
    ),
    "feature.transition_feature_state": _single_writer(
        "feature.transition_feature_state(uuid,text,text,text,bigint,jsonb)",
        _STATE_OWNER,
        "7d4c61d702d40670dce0d54fdf7302a4b3d71356b9e9a59fefe3a5c65897d7bf",
    ),
    "feature.author_lifecycle_override": _single_writer(
        "feature.author_lifecycle_override(uuid,text,text,boolean,text,text,bigint)",
        _STATE_OWNER,
        "6d41dae0b6e0a2061fb714383d6a44022acf576088724256e9514ebb62ebc4de",
    ),
    "feature.revoke_lifecycle_override": _single_writer(
        "feature.revoke_lifecycle_override(uuid,text,bigint)",
        _STATE_OWNER,
        "54cedafcd9949fd487a2045b03474024da21c1153becd852d316ed2a13b45702",
    ),
    # ── DC-1 (416 field override) ───────────────────────────────────────────
    "feature.author_feature_field_overrides": _single_writer(
        "feature.author_feature_field_overrides(uuid,bigint,text,text,bigint,jsonb,jsonb)",
        _STATE_OWNER,
        "d6d4fe6e79c12c35c17d1dacc5c9fd4e0a2582ee6dcb633f7642eaa9faf11b24",
    ),
    "feature.revoke_feature_field_overrides": _single_writer(
        "feature.revoke_feature_field_overrides(uuid,bigint,text,text,bigint,text[])",
        _STATE_OWNER,
        "1caae987df653cba227091841b84b5d8af18cbc23b76aa0fea3ad3376aaa00bc",
    ),
    # ── DC-1 (418 creation) ─────────────────────────────────────────────────
    "feature.approve_feature_request_with_initial_state": _single_writer(
        "feature.approve_feature_request_with_initial_state(uuid,jsonb,bigint)",
        _REQUEST_OWNER,
        "90c3d14cf7178106ae519d61e51ba495665aafce2505b1b1d3f071125e851191",
    ),
    "feature.create_admin_manual_feature_with_initial_state": _single_writer(
        "feature.create_admin_manual_feature_with_initial_state(jsonb,bigint)",
        _MANUAL_OWNER,
        "b34737dfceafa23d9dd09419b7881300915cfea343d483de1be996b0bd53c7cf",
    ),
    "feature.create_feature_with_initial_state": _single_writer(
        "feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)",
        _STATE_OWNER,
        "df05b6283cdb4fff02927ab22656e298adb893bf68622bfe74528d19d20cb4e9",
    ),
    "feature.create_provider_feature_with_initial_state": _single_writer(
        "feature.create_provider_feature_with_initial_state(jsonb,jsonb,text,text,text,jsonb)",
        _STATE_OWNER,
        "7ddecd0ab4833f669f6d81ed418256cff997aa4ea1fced63b4e00438f8506800",
    ),
}


def _edited_body(name: str, body: str) -> str:
    """검토한 바늘을 정확히 한 번씩만 바꾼다. 하나라도 어긋나면 이 revision은 멈춘다."""
    routine = _ROUTINES[name]
    if hashlib.sha256(body.encode()).hexdigest() != routine.body_sha256:
        raise RuntimeError("432 body changed: " + name)
    if "lock_single_feature_writer_protocol" in body or "lock_provider_evidence_writer" in body:
        raise RuntimeError("433 entry already present: " + name)
    changed = body
    for old, new in routine.edits:
        if changed.count(old) != 1:
            raise RuntimeError("433 edit anchor is not unique: " + name)
        changed = changed.replace(old, new, 1)
    single_writer = routine.edits[0] in {
        (_PROTOCOL_EX, _SINGLE_WRITER),
        (_PROTOCOL_EX, _EVIDENCE_WRITER),
    }
    if single_writer and "lock_scoped_feature_write_protocol" in changed:
        raise RuntimeError("single writer kept an unconditional protocol entry: " + name)
    return changed


def _planned_replacements(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    """카탈로그 행을 검증하고 ``(name, owner, CREATE OR REPLACE 정의)`` 목록을 돌려준다."""
    if len(rows) != len(_ROUTINES) or {str(r["name"]) for r in rows} != set(_ROUTINES):
        raise RuntimeError("433 routine inventory differs from revision 432")
    replacements: list[tuple[str, str, str]] = []
    for row in rows:
        name = str(row["name"])
        routine = _ROUTINES[name]
        if (
            row["owner"] != routine.owner
            or row["kind"] != routine.kind
            or bool(row["prosecdef"]) is not routine.security_definer
            or row["language"] != "plpgsql"
            or row["definition"].count(row["body"]) != 1
        ):
            raise RuntimeError("433 owner/kind/security/definition changed: " + name)
        changed = _edited_body(name, str(row["body"]))
        replacements.append(
            (name, routine.owner, row["definition"].replace(row["body"], changed, 1))
        )
    return replacements


_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK(destination_head IN (
        '300',
        '301_m03_import_children',
        '302_m03_child_issuance',
        '303_m05_payload_hash_domain',
        '304_m05_detector_manuals',
        '305_m05_relitigation_fence',
        '306_m02_manual_feature_purge',
        '307_m02_truncate_fence',
        '308_t39_provider_identities',
        '309_t39_feature_id_rekey',
        '310_seoul_source_move',
        '311_seal_member_digest',
        '312_route_geometry_sidecar',
        '313_single_service_role',
        '400',
        '401_retire_map_kma_refresh',
        '402_remove_map_weather_data',
        '403_drop_kma_notice_lineage',
        '404_transport_provider_identity',
        '405_mois_freshness_sla',
        '406_feature_write_gate',
        '407_feature_geocode_stamps',
        '408_kor_travel_geo_releases',
        '409_geo_release_item_reasons',
        '410_provider_field_shadow',
        '411_scoped_feature_write_kernel',
        '412_provider_scalar_projection',
        '413_legacy_sql_protocol_entry',
        '414_manual_dedup_protocol',
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol',
        '419_retire_pg_transport_values',
        '420_exclusive_provider_refresh',
        '421_stamp_writer_boundary',
        '422_heritage_evidence_reader',
        '423_exclusive_context_select',
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol',
        '427_transport_airport_reader',
        '428_bounded_curation_capture',
        '429_strict_sh_data_guards',
        '430_provider_snapshot_recovery',
        '431_transport_rest_reader',
        '432_rest_snapshot_atomic',
        '433_protocol_entry_narrowing'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    Path(__file__).with_name("_433_single_writer_entry.sql").read_text(encoding="utf-8"),
    Path(__file__).with_name("_433_evidence_writer_entry.sql").read_text(encoding="utf-8"),
    "REVOKE ALL ON FUNCTION ops.lock_provider_evidence_writer_protocol() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.lock_provider_evidence_writer_protocol() "
    "TO ktm_manual_provider_dedup_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.lock_single_feature_writer_protocol() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.lock_single_feature_writer_protocol() "
    "TO ktm_feature_runtime,ktm_manual_provider_dedup_procedure_owner,"
    "ktm_manual_feature_procedure_owner,ktm_feature_request_procedure_owner",
    # WI-3: 418은 이 GRANT를 schema owner로 냈다(경고만, 부여 0). 함수 소유자로 다시 낸다.
    "GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean) "
    "TO ktm_manual_feature_procedure_owner,ktm_feature_request_procedure_owner",
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE ktm_feature_schema_owner",
)

_CATALOG_SQL: Final = """SELECT n.nspname||'.'||p.proname AS name,p.oid::bigint AS oid,
 r.rolname AS owner,p.prokind::text AS kind,p.prosecdef,l.lanname AS language,
 p.provolatile::text AS volatility,p.proconfig AS config,p.proacl::text[] AS acl,
 p.prosrc AS body,pg_get_functiondef(p.oid) AS definition,
 pg_get_expr(p.proargdefaults,0) AS defaults,p.proargnames AS names,p.proargmodes::text[] AS modes
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=ANY(CAST(:oids AS oid[]))
 ORDER BY n.nspname COLLATE "C",p.proname COLLATE "C"
"""
_PRESERVED: Final = (
    "name",
    "oid",
    "owner",
    "kind",
    "prosecdef",
    "language",
    "volatility",
    "config",
    "acl",
    "defaults",
    "names",
    "modes",
)


def upgrade() -> None:
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    # 데이터 writer(P)와 tracking writer(L)를 모두 비운 뒤 정의를 바꾼다. 순서는 P 다음 L이다.
    bind.execute(text("SET ROLE " + _STATE_OWNER))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SELECT pg_advisory_xact_lock(CAST(:key AS bigint))"), {"key": _LINEAGE_KEY})
    signatures = [routine.signature for routine in _ROUTINES.values()]
    resolved = bind.execute(
        text(
            "SELECT signature,to_regprocedure(signature)::oid::bigint AS oid "
            "FROM unnest(CAST(:signatures AS text[])) AS signature"
        ),
        {"signatures": signatures},
    ).all()
    missing = sorted(str(signature) for signature, oid in resolved if oid is None)
    if missing:
        raise RuntimeError("433 signature not found in revision 432: " + ", ".join(missing))
    oids = [int(oid) for _signature, oid in resolved]
    rows = bind.execute(text(_CATALOG_SQL), {"oids": oids}).mappings().all()
    replacements = _planned_replacements(rows)

    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    needs_create = sorted(
        {(routine.owner, name.split(".", 1)[0]) for name, routine in _ROUTINES.items()}
        | {(_STATE_OWNER, "ops")}
    )
    granted: list[tuple[str, str]] = []
    for owner, schema in needs_create:
        if owner == _SCHEMA_OWNER:
            continue
        has_create = bool(
            bind.scalar(
                text("SELECT has_schema_privilege(:owner,:schema,'CREATE')"),
                {"owner": owner, "schema": schema},
            )
        )
        if not has_create:
            # owner/schema는 위 고정 whitelist에서만 온다.
            bind.execute(text("GRANT CREATE ON SCHEMA " + schema + " TO " + owner))
            granted.append((owner, schema))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    for _name, owner, definition in replacements:
        bind.execute(text("SET ROLE " + owner))
        bind.execute(text(definition))
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    after = bind.execute(text(_CATALOG_SQL), {"oids": oids}).mappings().all()
    if len(after) != len(rows):
        raise RuntimeError("433 replacement inventory changed")
    for prior_row, updated_row in zip(rows, after, strict=True):
        for key in _PRESERVED:
            if prior_row[key] != updated_row[key]:
                raise RuntimeError("433 replacement metadata changed: " + key)
        name = str(updated_row["name"])
        if updated_row["body"] != _edited_body(name, str(prior_row["body"])):
            raise RuntimeError("433 replacement body differs from its plan: " + name)
    for owner, schema in granted:
        bind.execute(text("REVOKE CREATE ON SCHEMA " + schema + " FROM " + owner))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")
