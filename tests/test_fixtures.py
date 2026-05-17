from __future__ import annotations

import json

import pytest

from krtour_map.fixtures import assert_case, load_fixture, redact_sensitive, save_fixture


def test_redact_sensitive_masks_nested_values() -> None:
    redacted = redact_sensitive(
        {
            "headers": {"Authorization": "Bearer secret"},
            "query": {"serviceKey": "plain-key"},
            "items": [{"access_token": "token"}],
        }
    )

    assert redacted["headers"]["Authorization"] == "<REDACTED>"
    assert redacted["query"]["serviceKey"] == "<REDACTED>"
    assert redacted["items"][0]["access_token"] == "<REDACTED>"


def test_save_fixture_redacts_and_refuses_overwrite(tmp_path, sample_feature) -> None:
    path = save_fixture(
        base_dir=tmp_path,
        function_name="feature_summary",
        case_name="Sample Feature",
        description="sample",
        input_data={"api_key": "secret"},
        request_data={"headers": {"Authorization": "secret"}},
        response_data={"body": sample_feature.model_dump(mode="json")},
        parsed_result=sample_feature,
        processed_result={"feature_id": sample_feature.feature_id},
        library_version="0.1.0",
    )

    loaded = load_fixture(path)
    assert loaded["input"]["api_key"] == "<REDACTED>"
    assert loaded["request"]["headers"]["Authorization"] == "<REDACTED>"
    assert path.name == "sample-feature.json"
    with pytest.raises(FileExistsError):
        save_fixture(
            base_dir=tmp_path,
            function_name="feature_summary",
            case_name="Sample Feature",
            description="sample",
            input_data={},
            request_data={},
            response_data={"body": {}},
            parsed_result={},
            processed_result={},
        )


def test_assert_case_snapshot_excludes_volatile_fields() -> None:
    assert_case(
        {"id": "1", "updated_at": "now", "nested": {"request_id": "abc"}},
        {"id": "1", "updated_at": "then", "nested": {"request_id": "def"}},
        {"mode": "snapshot", "exclude_fields": ["updated_at", "request_id"]},
    )


def test_assert_case_required_fields_supports_dotted_paths() -> None:
    assert_case(
        {"feature": {"id": "f_1"}, "count": 1},
        {},
        {"mode": "required_fields", "required_fields": ["feature.id"]},
    )


def test_generated_fixture_file_is_valid_json(tmp_path, sample_feature) -> None:
    path = save_fixture(
        base_dir=tmp_path,
        function_name="feature_summary",
        case_name="json-valid",
        description="sample",
        input_data={},
        request_data={},
        response_data={"body": sample_feature.model_dump(mode="json")},
        parsed_result=sample_feature,
        processed_result={"feature_id": sample_feature.feature_id},
    )

    with path.open("r", encoding="utf-8") as file:
        assert json.load(file)["name"] == "json-valid"
