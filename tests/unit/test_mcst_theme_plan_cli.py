"""ADR-121 전환 계획 CLI·migration 446 seed 대조."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from kortravelmap.cli.main import build_parser
from kortravelmap.cli.mcst_theme_plan import mcst_plan_dataset_configs, plan_report
from kortravelmap.core.theme_attach import AttachCandidate, PlanFeature, plan_existing_features
from kortravelmap.providers.mcst import MCST_FILE_DATASETS, MCST_PET_BUSINESS_CATEGORIES

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "446_mcst_place_attributes.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_446", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_seed_matches_provider_attribute_codes() -> None:
    migration = _migration()
    seeded = {
        dataset_key: code for dataset_key, _entity_type, code in migration.DATASET_ATTRIBUTES
    }
    provider = {
        spec.dataset_key: spec.attribute_code
        for spec in MCST_FILE_DATASETS.values()
        if spec.attribute_code is not None
    }
    assert seeded == provider
    assert {entity for _key, entity, _code in migration.DATASET_ATTRIBUTES} == {
        spec.entity_type for spec in MCST_FILE_DATASETS.values() if spec.attribute_code
    }
    catalog = {code for code, _label, _group, _order in migration.PLACE_ATTRIBUTES}
    assert set(provider.values()) == catalog


def test_plan_configs_mark_only_pet_list_for_pet_business() -> None:
    configs = mcst_plan_dataset_configs()
    assert configs["mcst_pet_friendly_culture_facilities_csv"].pet_business == (
        MCST_PET_BUSINESS_CATEGORIES
    )
    assert all(
        not config.pet_business
        for key, config in configs.items()
        if key != "mcst_pet_friendly_culture_facilities_csv"
    )


def test_plan_report_counts_and_samples() -> None:
    features = [
        PlanFeature(
            feature_id="a", dataset_key="d1", name="가", created_at="1", place_list=False,
            pet_business=False, master_category_prefixes=None,
            candidates=(AttachCandidate("M", "가", "01040100", 10.0, 1),),
        ),
        PlanFeature(
            feature_id="b", dataset_key="d1", name="나", created_at="1", place_list=False,
            pet_business=True, master_category_prefixes=None, candidates=(),
        ),
    ]
    report = plan_report(features, plan_existing_features(features), samples=5)
    assert report["by_dataset"] == {"d1": {"attach": 1, "retire": 1}}
    assert report["retiring_feature_count"] == 2
    assert report["samples"]["d1"]["attach"][0]["target_feature_id"] == "M"


def test_cli_registers_read_only_plan_command() -> None:
    args = build_parser().parse_args(["mcst-theme-plan", "--samples", "3"])
    assert args.command == "mcst-theme-plan"
    assert args.samples == 3
