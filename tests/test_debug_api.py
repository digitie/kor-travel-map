from __future__ import annotations

from pathlib import Path

from krtour_map.debug_api import handle
from krtour_map.debug_ui import render_debug_ui_html


def _database_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def test_debug_api_schema_feature_crud_and_table_browser(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "debug.sqlite3")

    schema = handle({"action": "schema", "database_url": database_url, "create_schema": True})
    assert schema["ok"] is True
    assert any(table["name"] == "features" for table in schema["schema"]["tables"])

    sample = handle({"action": "sample_feature"})["feature"]
    created = handle({"action": "upsert_feature", "database_url": database_url, "feature": sample})
    assert created["ok"] is True
    assert created["feature"]["feature_id"] == "debug_feature_sample"

    listing = handle(
        {
            "action": "list_features",
            "database_url": database_url,
            "q": "Sample",
            "filters": {"kind": "place"},
        }
    )
    assert listing["total"] == 1
    assert listing["items"][0]["name"] == "Debug Sample Feature"

    detail = handle(
        {
            "action": "get_feature",
            "database_url": database_url,
            "feature_id": "debug_feature_sample",
        }
    )
    assert detail["feature"]["model"]["category"] == "tourism.attraction"
    assert detail["feature"]["related"]["weather_values"] == []

    patched = handle(
        {
            "action": "patch_feature",
            "database_url": database_url,
            "feature_id": "debug_feature_sample",
            "patch": {"name": "Debug Sample Feature Edited", "status": "active"},
        }
    )
    assert patched["feature"]["name"] == "Debug Sample Feature Edited"
    assert patched["feature"]["status"] == "active"

    table = handle(
        {
            "action": "list_table",
            "database_url": database_url,
            "table": "features",
            "q": "Edited",
        }
    )
    assert table["total"] == 1
    assert table["items"][0]["feature_id"] == "debug_feature_sample"

    deleted = handle(
        {
            "action": "delete_feature",
            "database_url": database_url,
            "feature_id": "debug_feature_sample",
        }
    )
    assert deleted["ok"] is True

    deleted_detail = handle(
        {
            "action": "get_feature",
            "database_url": database_url,
            "feature_id": "debug_feature_sample",
        }
    )
    assert deleted_detail["feature"]["model"]["status"] == "deleted"


def test_debug_api_standard_data_preview_and_load(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "standard-debug.sqlite3")
    handle({"action": "schema", "database_url": database_url, "create_schema": True})

    item = {
        "fstvlNm": "샘플축제",
        "opar": "샘플광장",
        "fstvlStartDate": "2026-05-20",
        "fstvlEndDate": "2026-05-21",
        "latitude": "37.5665",
        "longitude": "126.9780",
        "referenceDate": "2026-05-20",
    }
    catalog = handle({"action": "etl_catalog"})
    preview = handle(
        {
            "action": "preview_standard_data",
            "dataset_key": "standard_cultural_festivals",
            "items": [item],
        }
    )
    loaded = handle(
        {
            "action": "load_standard_data",
            "database_url": database_url,
            "dataset_key": "standard_cultural_festivals",
            "items": [item],
        }
    )

    assert catalog["ok"] is True
    assert any(row["dataset_key"] == "standard_cultural_festivals" for row in catalog["datasets"])
    assert any(row["dataset_key"] == "krex_traffic_notices" for row in catalog["datasets"])
    assert preview["counts"]["features"] == 1
    assert loaded["load"]["features"] == 1


def test_debug_api_notice_preview_load_and_bounds_filter(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "notice-debug.sqlite3")
    handle({"action": "schema", "database_url": database_url, "create_schema": True})
    item = {
        "notice_id": "traffic-1",
        "title": "영동선 강릉방향 사고 처리",
        "message": "1차로 사고 처리 중",
        "lat": 37.543,
        "lon": 128.442,
        "source_agency": "한국도로공사",
        "valid_start_time": "2026-05-20T09:00:00+09:00",
    }

    preview = handle(
        {
            "action": "preview_notice_data",
            "dataset_key": "krex_traffic_notices",
            "items": [item],
        }
    )
    loaded = handle(
        {
            "action": "load_notice_data",
            "database_url": database_url,
            "dataset_key": "krex_traffic_notices",
            "items": [item],
        }
    )
    listing = handle(
        {
            "action": "list_features",
            "database_url": database_url,
            "filters": {
                "kind": "notice",
                "notice_type": "traffic_accident",
                "only_with_coord": True,
            },
            "bounds": {"south": 37.0, "west": 128.0, "north": 38.0, "east": 129.0},
        }
    )

    assert preview["counts"]["notice_details"] == 1
    assert preview["notice_details"][0]["notice_type"] == "traffic_accident"
    assert loaded["load"]["notice_details"] == 1
    assert listing["total"] == 1
    assert listing["items"][0]["marker_icon"] == "car"
    assert listing["items"][0]["notice_type"] == "traffic_accident"


def test_debug_api_dagster_run_and_rustfs_config(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path / "dagster-debug.sqlite3")
    rustfs_config = tmp_path / "rustfs.toml"
    handle({"action": "schema", "database_url": database_url, "create_schema": True})

    saved = handle(
        {
            "action": "save_rustfs_config",
            "config_path": str(rustfs_config),
            "config": {
                "enabled": True,
                "endpoint_url": "http://127.0.0.1:19000",
                "public_endpoint_url": "http://127.0.0.1:19000",
                "console_url": "http://127.0.0.1:19001",
                "region": "us-east-1",
                "bucket": "tripmate-media",
                "access_key_id": "tripmate-dev-access",
                "secret_access_key": "tripmate-dev-secret",
                "upload_url_expires_seconds": 900,
                "max_upload_bytes": 10485760,
                "allowed_content_types": ["image/jpeg", "video/mp4", "application/pdf"],
            },
        }
    )
    config = handle({"action": "rustfs_config", "config_path": str(rustfs_config)})
    jobs = handle({"action": "dagster_jobs"})
    dagster_run = handle(
        {
            "action": "run_dagster_etl",
            "database_url": database_url,
            "dataset_key": "standard_tourism_roads",
            "items": [
                {
                    "stretNm": "남산 무장애산책길",
                    "stretIntrcn": "무장애 산책로",
                    "stretLt": "800m",
                    "reqreTime": "40분",
                    "beginSpotNm": "입구",
                    "beginRdnmadr": "서울특별시 중구",
                    "endSpotNm": "전망대",
                    "endRdnmadr": "서울특별시 중구",
                    "referenceDate": "2026-02-09",
                }
            ],
        }
    )

    assert saved["settings"]["bucket"] == "tripmate-media"
    assert config["settings"]["secret_access_key"] == "<configured>"
    assert any(job["dataset_key"] == "standard_tourism_roads" for job in jobs["jobs"])
    assert any(job["dataset_key"] == "krex_traffic_notices" for job in jobs["jobs"])
    assert dagster_run["load"]["route_details"] == 1


def test_render_debug_ui_html_contains_standard_etl_controls() -> None:
    html = render_debug_ui_html()

    assert "python-krtour-map Debug UI" in html
    assert "standard_tourism_roads" in html
    assert "http://localhost:8601/api/debug" in html
    assert "b93b82c48729c08c24c943911a8727f9" in html
    assert "react-kakao-maps-sdk" in html
    assert "RustFS UI" in html
    assert "krex_traffic_notices" in html
    assert "Only visible map bounds" in html
