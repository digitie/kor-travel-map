from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from krtour_map.exceptions import FixtureAssertionError

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "x-api-key",
        "api-key",
        "api_key",
        "apikey",
        "servicekey",
        "service_key",
        "certkey",
        "access_token",
        "refresh_token",
        "token",
        "secret",
    }
)


def jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [jsonable(item) for item in obj]
    if isinstance(obj, tuple):
        return [jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: jsonable(value) for key, value in obj.items()}
    return obj


def redact_sensitive(obj: Any) -> Any:
    if isinstance(obj, dict):
        redacted: dict[Any, Any] = {}
        for key, value in obj.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "<REDACTED>"
            else:
                redacted[key] = redact_sensitive(value)
        return redacted
    if isinstance(obj, list):
        return [redact_sensitive(item) for item in obj]
    return obj


def slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[\\/:*?\"<>|]+", "-", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "case"


def save_fixture(
    *,
    base_dir: str | Path,
    function_name: str,
    case_name: str,
    description: str,
    input_data: dict[str, Any],
    request_data: dict[str, Any],
    response_data: dict[str, Any],
    parsed_result: Any,
    processed_result: Any,
    assertion: dict[str, Any] | None = None,
    library_version: str | None = None,
    overwrite: bool = False,
) -> Path:
    safe_case_name = slugify(case_name)
    fixture_dir = Path(base_dir) / function_name
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / f"{safe_case_name}.json"

    if fixture_path.exists() and not overwrite:
        raise FileExistsError(f"Fixture already exists: {fixture_path}")

    fixture = {
        "name": safe_case_name,
        "function": function_name,
        "description": description,
        "input": redact_sensitive(jsonable(input_data)),
        "request": redact_sensitive(jsonable(request_data)),
        "response": redact_sensitive(jsonable(response_data)),
        "parsed": jsonable(parsed_result),
        "processed": jsonable(processed_result),
        "assertion": assertion
        or {
            "mode": "snapshot",
            "exclude_fields": ["fetched_at", "request_id", "updated_at", "collected_at"],
            "required_fields": [],
        },
        "meta": {
            "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "library_version": library_version,
            "source": "debug_ui",
        },
    }

    with fixture_path.open("w", encoding="utf-8") as file:
        json.dump(fixture, file, ensure_ascii=False, indent=2)
        file.write("\n")

    return fixture_path


def load_fixture(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def remove_fields(obj: Any, exclude_fields: list[str]) -> Any:
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if key in exclude_fields:
                continue
            result[key] = remove_fields(value, exclude_fields)
        return result
    if isinstance(obj, list):
        return [remove_fields(item, exclude_fields) for item in obj]
    return obj


def _has_path(obj: Any, field_path: str) -> bool:
    current = obj
    for part in field_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return False
    return True


def assert_case(actual: Any, expected: Any, assertion: dict[str, Any]) -> None:
    mode = assertion.get("mode", "snapshot")
    actual_json = jsonable(actual)
    expected_json = jsonable(expected)

    if mode == "snapshot":
        exclude_fields = list(assertion.get("exclude_fields", []))
        actual_clean = remove_fields(actual_json, exclude_fields)
        expected_clean = remove_fields(expected_json, exclude_fields)
        if actual_clean != expected_clean:
            raise FixtureAssertionError("Snapshot assertion failed")
        return

    if mode == "schema_only":
        if actual_json is None:
            raise FixtureAssertionError("Schema-only assertion produced None")
        return

    if mode == "required_fields":
        for field in assertion.get("required_fields", []):
            if not _has_path(actual_json, field):
                raise FixtureAssertionError(f"Required field missing: {field}")
        return

    if mode == "count":
        if actual_json.get("count") != expected_json.get("count"):
            raise FixtureAssertionError("Count assertion failed")
        return

    raise ValueError(f"Unknown assertion mode: {mode}")


Runner = dict[str, Callable[[Any], Any]]


def replay_fixture(fixture: dict[str, Any], runners: dict[str, Runner]) -> Any:
    function_name = fixture["function"]
    runner = runners[function_name]
    parsed = runner["parse"](fixture["response"]["body"])
    processed = runner["process"](parsed)
    assert_case(processed, fixture["processed"], fixture.get("assertion", {"mode": "snapshot"}))
    return processed
