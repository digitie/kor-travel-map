"""H35 ``0063→0078`` cutover의 Map-owned typed helper entrypoint.

Docker-manager가 writer fence, 전역 lock/journal, backup/restore와 runtime lifecycle을
소유한다. 이 모듈은 stdin request를 한 phase로 dispatch하고 stdout에 receipt 한 줄만
출력한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Never, cast

from kortravelmap.cli._h35_contract import (
    CONTRACT_VERSION,
    OPERATIONS,
    H35ContractError,
    H35IdentityError,
    H35Request,
    Operation,
    Receipt,
    check,
    parse_request,
    receipt,
    receipt_digest,
)
from kortravelmap.cli._h35_csv5 import (
    EXPECTED_CSV_ACCEPTED,
    EXPECTED_CSV_FILES,
    EXPECTED_CSV_ROWS,
    collect_csv5_verify_state,
    run_csv5,
)
from kortravelmap.cli._h35_schema import (
    EXPECTED_POST_PUBLIC,
    TARGET_SCHEMA,
    collect_verify_state,
    image_revision_check,
    run_migrate,
    run_preflight,
)


async def _run_verify(request: H35Request) -> Receipt:
    (
        schema_request,
        schema_identity_check,
        schema,
        schema_public,
        structural_checks,
        structural_counts,
    ) = await collect_verify_state(request)
    csv_request, csv_identity_check, csv_state, csv_public = await collect_csv5_verify_state(
        request
    )
    checks = [
        schema_identity_check,
        csv_identity_check,
        check(
            "database_identity_cross_read",
            expected=schema_request.database_identity,
            observed=csv_request.database_identity,
        ),
        image_revision_check(request),
        check("schema_verify", expected=TARGET_SCHEMA, observed=schema),
        check("public_items_verify", expected=EXPECTED_POST_PUBLIC, observed=schema_public),
        check("public_items_cross_read", expected=schema_public, observed=csv_public),
        check("csv5_batches_verify", expected=EXPECTED_CSV_FILES, observed=csv_state["batches"]),
        check("csv5_rows_verify", expected=EXPECTED_CSV_ROWS, observed=csv_state["rows"]),
        check(
            "csv5_accepted_verify",
            expected=EXPECTED_CSV_ACCEPTED,
            observed=csv_state["accepted"],
        ),
        *structural_checks,
    ]
    accepted = all(value.get("passed") is True for value in checks)
    return receipt(
        schema_request,
        status="accepted" if accepted else "rejected",
        schema_before=TARGET_SCHEMA,
        schema_after=schema,
        forward_boundary="schema_0078" if schema == TARGET_SCHEMA else "not_crossed",
        row_counts={
            "accepted": csv_state["accepted"],
            "batches": csv_state["batches"],
            "public_items": schema_public,
            "rejected": 0,
            "rows": csv_state["rows"],
            **structural_counts,
        },
        checks=checks,
    )


async def _execute(request: H35Request) -> Receipt:
    if request.operation == "preflight":
        return await run_preflight(request)
    if request.operation == "migrate":
        return await run_migrate(request)
    if request.operation == "csv5":
        return await run_csv5(request)
    return await _run_verify(request)


class _ArgumentError(ValueError):
    """raw argv를 반사하지 않는 argparse 경계 오류."""


class _ContractParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _ArgumentError from None


def _early_error(error_code: str) -> None:
    print(
        json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "status": "failed",
                "error_code": error_code,
            },
            separators=(",", ":"),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = _ContractParser(
        prog="h35_cutover.py",
        add_help=False,
        description=(
            "Docker-manager 전용 H35 typed helper. request는 stdin JSON, "
            "receipt는 stdout 단일 JSON line입니다."
        ),
    )
    parser.add_argument("operation", choices=OPERATIONS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except _ArgumentError:
        _early_error("invalid_arguments")
        return 2
    operation = cast("Operation", args.operation)
    try:
        request = parse_request(sys.stdin.read(), operation=operation)
    except H35ContractError:
        _early_error("invalid_request")
        return 2
    try:
        result = asyncio.run(_execute(request))
    except H35IdentityError:
        _early_error("database_identity_unavailable")
        return 1
    except Exception:  # noqa: BLE001 - raw exception/secret을 process 경계에 내보내지 않는다.
        _early_error("migration_failed" if request.operation == "migrate" else "internal_error")
        return 1
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "accepted" else 3


__all__ = [
    "CONTRACT_VERSION",
    "H35ContractError",
    "H35Request",
    "Receipt",
    "build_parser",
    "main",
    "parse_request",
    "receipt_digest",
]
