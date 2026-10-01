"""Map Dagster에 KMA 적재 경로가 다시 생기지 않게 한다(ADR-104).

2026-10-01 소유자 결정: KMA(기상청)는 kor-travel-weather가 소유하고, Map은 KMA
data.go.kr 오퍼레이션을 다시는 부르지 않는다. 그 전까지 Map은 KMA 자동 적재를 코드
목록(``DISABLED_FEATURE_LOAD_SCHEDULES``)으로만 끄고 있었고, 수동 launch·백필·
``provider_dataset`` 큐 요청은 그대로 KMA를 불렀다.

이 검사는 **이름이 아니라 정체성과 효과**에 결박한다.

- 정체성: operation key가 어느 provider의 것인지는 DB 카탈로그가 정한다
  (``provider_sync.provider_dataset_operations`` → ``provider_datasets.provider``).
  여기서는 그 정본의 시드(``alembic/baseline/seed.sql``)에서 ``python-kma-api``가
  소유한 operation key를 **유도**한다 — job 이름을 나열하지 않는다. 이름을 바꿔
  다시 들여와도 카탈로그가 KMA라고 말하면 걸린다.
- 효과: KMA를 부르려면 provider 라이브러리(``python-kma-api``의 import 패키지)를
  import하거나 KMA data.go.kr 서비스 경로를 직접 쳐야 한다. Map 런타임 소스 어디에도
  그 둘이 없어야 한다. 이름·태그를 전부 피해 간 asset도 이 축에서 걸린다.

각 검사는 KMA 경로가 있던 ``origin/main``(이 브랜치 직전)에서 실제로 빨갛다
(``docs/journal.md`` 2026-10-01 항목에 실측을 적었다).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from kortravelmap.infra.feature_update_executor import ProviderDatasetRefreshScope
from kortravelmap.providers.feature_operation_registry import (
    FEATURE_OPERATION_HANDLERS,
    UnknownFeatureOperationHandlerError,
    feature_operation_handler_keys,
    resolve_feature_operation_handler,
)
from kortravelmap.providers.kma import KMA_PROVIDER_NAME

from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.feature_update_runner import FeatureUpdateAssetRunner
from kortravelmap.dagster.resources import PROVIDER_RECORD_RESOURCE_SPECS

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SEED = _REPO_ROOT / "alembic" / "baseline" / "seed.sql"
_PROVIDER_SURFACE = _REPO_ROOT / "src" / "kortravelmap" / "providers" / "_provider_surface.json"
_OPERATION_KEY_TAG = "kor_travel_map.operation_key"

#: data.go.kr에서 기상청(KMA) 서비스가 사는 경로 접두사(``apis.data.go.kr/1360000/...``).
#: provider 라이브러리를 거치지 않고 HTTP를 직접 치는 우회를 잡는다.
_KMA_DATA_GO_KR_SERVICE_PATH = "1360000"

#: Map 런타임 소스 — Dagster code location이 import하는 core와 세 package의 ``src``.
_RUNTIME_SOURCE_ROOTS: tuple[Path, ...] = (
    _REPO_ROOT / "src",
    *sorted((_REPO_ROOT / "packages").glob("*/src")),
)

_DATASET_ROW = re.compile(
    r"INSERT INTO provider_sync\.provider_datasets \([^)]*\) OVERRIDING SYSTEM VALUE "
    r"VALUES \((\d+), '([^']*)', '([^']*)'"
)
_OPERATION_ROW = re.compile(
    r"INSERT INTO provider_sync\.provider_dataset_operations \([^)]*\) "
    r"VALUES \((\d+), '([^']*)', '([^']*)'"
)


def _catalog_operation_providers() -> dict[str, str]:
    """시드 카탈로그의 ``operation_key → provider``. 정체성의 정본은 카탈로그다."""
    seed = _SEED.read_text(encoding="utf-8")
    provider_by_dataset = {
        int(match.group(1)): match.group(2) for match in _DATASET_ROW.finditer(seed)
    }
    providers: dict[str, str] = {}
    for match in _OPERATION_ROW.finditer(seed):
        providers[match.group(2)] = provider_by_dataset[int(match.group(1))]
    return providers


def _kma_operation_keys() -> frozenset[str]:
    """KMA가 소유한 적재 operation key — preview(fixture-only)는 뺀다."""
    seed = _SEED.read_text(encoding="utf-8")
    kinds = {match.group(2): match.group(3) for match in _OPERATION_ROW.finditer(seed)}
    return frozenset(
        key
        for key, provider in _catalog_operation_providers().items()
        if provider == KMA_PROVIDER_NAME and kinds[key] != "preview"
    )


def _kma_import_package() -> str:
    """``python-kma-api``의 import 패키지 이름 — 핀된 provider 표면 manifest가 정본."""
    surface = json.loads(_PROVIDER_SURFACE.read_text(encoding="utf-8"))
    package = surface["providers"][KMA_PROVIDER_NAME]["package"]
    assert isinstance(package, str)
    assert package
    return package


def test_the_catalog_still_names_kma_operations() -> None:
    """항진명제 방지 — 유도가 비면 아래 검사가 아무것도 재지 않는다.

    하한은 "본 것"에 건다: 시드가 KMA dataset에 결박한 적재 operation이 실제로
    보여야 한다(2026-10-01 기준 5개 — 초단기실황·초단기예보·단기·중기·특보).
    """

    keys = _kma_operation_keys()
    assert len(keys) >= 5, f"시드에서 KMA 적재 operation을 찾지 못했다: {sorted(keys)}"
    providers = _catalog_operation_providers()
    assert len(providers) > len(keys), "카탈로그 파싱이 KMA만 보고 있다"


def test_no_dagster_job_or_schedule_belongs_to_kma() -> None:
    """job·schedule의 operation key가 카탈로그상 KMA면 실패한다.

    UI의 "Launch"·백필·schedule 명령은 전부 Definitions에 있는 job을 고른다. job이
    없으면 그 경로들이 KMA를 고를 수 없다.
    """

    providers = _catalog_operation_providers()
    kma_keys = _kma_operation_keys()
    offenders: list[str] = []
    for job in defs.resolve_all_job_defs():
        operation_key = job.tags.get(_OPERATION_KEY_TAG)
        if job.name in kma_keys or (
            operation_key is not None and providers.get(operation_key) == KMA_PROVIDER_NAME
        ):
            offenders.append(f"job {job.name} (operation_key={operation_key})")
    repository = defs.get_repository_def()
    for schedule in repository.schedule_defs:
        if schedule.job_name in kma_keys:
            offenders.append(f"schedule {schedule.name} → {schedule.job_name}")
    sensor_targets = 0
    for sensor in repository.sensor_defs:
        for target in _sensor_target_job_names(sensor):
            sensor_targets += 1
            if target in kma_keys:
                offenders.append(f"sensor {sensor.name} → {target}")
    # 항진명제 방지: 큐 sensor는 feature update job을 겨눈다 — 대상 추출이 0이면 낡았다.
    assert sensor_targets > 0, "sensor 대상 job을 하나도 읽지 못했다 — 추출이 낡았다"
    assert not offenders, f"Map Dagster에 KMA instigator·job이 있다: {offenders}"


def _sensor_target_job_names(sensor: Any) -> list[str]:
    """sensor가 run을 요청하는 job 이름. run-status sensor처럼 대상이 없으면 빈 목록."""
    names: list[str] = []
    for target in getattr(sensor, "targets", None) or ():
        try:
            name = target.job_name
        except Exception:  # noqa: BLE001 - 대상 종류마다 표면이 다르다
            continue
        if isinstance(name, str):
            names.append(name)
    return names


def test_no_dagster_asset_is_bound_to_kma() -> None:
    """asset이 KMA operation에 결박되거나 KMA provider resource를 요구하면 실패한다."""

    kma_keys = _kma_operation_keys()
    kma_asset_keys = {
        asset_key
        for key, binding in FEATURE_OPERATION_HANDLERS.items()
        if key in kma_keys
        for asset_key in binding.asset_keys
    }
    kma_resource_keys = {
        spec.resource_key
        for spec in PROVIDER_RECORD_RESOURCE_SPECS
        if spec.provider_package == KMA_PROVIDER_NAME
    }
    offenders: list[str] = []
    for assets_def in defs.resolve_asset_graph().assets_defs:
        for key in assets_def.keys:
            name = key.to_user_string()
            if name in kma_asset_keys:
                offenders.append(f"asset {name}: KMA operation handler")
            required = set(assets_def.required_resource_keys) & kma_resource_keys
            if required:
                offenders.append(f"asset {name}: KMA resource {sorted(required)}")
    assert not kma_resource_keys, (
        f"KMA provider record resource가 남았다: {sorted(kma_resource_keys)}"
    )
    assert not offenders, f"Map Dagster asset이 KMA에 결박돼 있다: {offenders}"


def test_no_launch_path_accepts_a_kma_operation_key() -> None:
    """handler registry와 큐 runner가 KMA operation key를 받지 않는다.

    큐 runner는 API(``POST /ops/pipeline/requests``)·PinVi cache target refresh·
    run-now가 모두 지나는 실행 경계다. ``provider_dataset`` scope로 넣는다 — 옛
    ``DISABLED_FEATURE_LOAD_OPERATION_KEYS`` 게이트가 일부러 통과시키던 "의도한 한 번"
    경로다. settings 팩토리가 불리면 runner가 provider 작업에 들어간 것이다.
    """

    kma_keys = _kma_operation_keys()
    registered = sorted(kma_keys & feature_operation_handler_keys())
    assert not registered, f"handler registry에 KMA operation이 있다: {registered}"
    for operation_key in sorted(kma_keys):
        with pytest.raises(UnknownFeatureOperationHandlerError):
            resolve_feature_operation_handler(operation_key)

        runner = FeatureUpdateAssetRunner(
            common_resources={},
            log=None,
            settings_factory=lambda key=operation_key: pytest.fail(
                f"{key}: runner가 KMA 요청을 실행하려 했다"
            ),
        )
        scope = ProviderDatasetRefreshScope(
            request_id="11111111-1111-4111-8111-111111111111",
            provider_dataset_id=1,
            sync_scope="dataset_wide",
            operation_key=operation_key,
            provider=KMA_PROVIDER_NAME,
            dataset_key="kma",
            scope_type="provider_dataset",
            request_scope={
                "type": "provider_dataset",
                "provider_dataset_id": 1,
                "sync_scope": "dataset_wide",
            },
            update_policy={"prevent_provider_reactivation": True},
            feature_ids=("feature-1",),
            feature_count=1,
            prevent_provider_reactivation=True,
        )
        with pytest.raises(RuntimeError, match="지원하지 않는 operation_key"):
            asyncio.run(runner(cast(Any, None), scope))


_IMPORT_FUNCTIONS = frozenset({"import_module", "__import__"})


def _call_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _imported_names(node: ast.AST) -> list[str]:
    """이 노드가 import하는 모듈 이름 — 문장 import와 동적 import 둘 다."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module]
    if (
        isinstance(node, ast.Call)
        and _call_name(node.func) in _IMPORT_FUNCTIONS
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return [node.args[0].value]
    return []


def _imports_module(tree: ast.AST, package: str) -> list[int]:
    """``package``(또는 그 하위 모듈)를 import하는 줄 번호."""
    return [
        cast(Any, node).lineno
        for node in ast.walk(tree)
        if any(
            name == package or name.startswith(f"{package}.")
            for name in _imported_names(node)
        )
    ]


def test_map_runtime_source_cannot_reach_kma() -> None:
    """효과 축: Map 런타임 소스가 KMA client를 import하거나 KMA 경로를 치지 않는다."""

    package = _kma_import_package()
    scanned = 0
    offenders: list[str] = []
    for root in _RUNTIME_SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            scanned += 1
            relative = path.relative_to(_REPO_ROOT).as_posix()
            for line in _imports_module(ast.parse(source, filename=relative), package):
                offenders.append(f"{relative}:{line}: import {package}")
            if _KMA_DATA_GO_KR_SERVICE_PATH in source:
                offenders.append(f"{relative}: KMA data.go.kr 서비스 경로")
    assert scanned > 100, f"런타임 소스를 거의 보지 못했다: {scanned}개"
    assert not offenders, f"Map 런타임 소스가 KMA를 부를 수 있다: {offenders}"
