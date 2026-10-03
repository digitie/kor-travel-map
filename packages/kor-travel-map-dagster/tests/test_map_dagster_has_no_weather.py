"""Map Dagster에 날씨 적재 경로가 다시 생기지 않게 한다(ADR-104 → ADR-105).

2026-10-01 소유자 결정 두 개가 이 파일의 근거다.

- ADR-104: KMA(기상청)는 kor-travel-weather가 소유하고 Map은 KMA data.go.kr
  오퍼레이션을 부르지 않는다.
- ADR-105: Map은 ``weather`` kind feature를 **어떤 원천에서도** 적재하지 않고(KMA·
  에어코리아·KREX 휴게소 기상·산림청 산악기상·산불위험예보), **날씨 출처 notice**(KMA
  특보)도 적재하지 않는다. 날씨 출처가 아닌 notice(KREX 교통공지·산림청 산사태 예보)는
  남는다 — 마지막 검사가 그쪽을 양성으로 결박한다.

이 검사는 **이름이 아니라 정체성과 효과**에 결박한다. job 이름을 나열하지 않는다.

- 정체성: dataset이 무엇을 만드는지는 DB 카탈로그가 정한다
  (``provider_sync.provider_datasets.capabilities.produces``). 그 정본의 시드
  (``alembic/baseline/seed.sql``)에서 **날씨 dataset** = ``produces``에 ``"weather"``가
  있는 dataset + ``produces``에 ``"notice"``가 있고 provider가 ``python-kma-api``인
  dataset(KMA는 날씨 provider다)을 유도하고, 그 dataset에 결박된 operation key를
  ``provider_dataset_operations``와 ``provider_dataset_operation_scopes`` 두 표에서 모은다.
  이름을 바꿔 다시 들여와도 카탈로그가 날씨라고 말하면 걸린다.
- 효과: 날씨 값을 쓰려면 core client의 날씨 쓰기(``load_weather_values``·
  ``load_air_quality``·``materialize_current_weather_summary``)를 부르거나 날씨 전용
  모듈을 import해야 하고, 날씨 전용 provider(카탈로그상 dataset이 전부 날씨인 provider —
  KMA·에어코리아)를 부르려면 그 client 패키지를 import해야 한다. 이름·태그를 전부 피해 간
  asset도 이 축에서 걸린다.

**각 검사를 빨갛게 만드는 main 쪽 사실**(이 브랜치 직전 ``origin/main`` 0886c2ac1 기준.
조정자가 그 트리에서 실제로 돌려 확인한다 — 이 파일을 쓴 에이전트는 pytest를 돌리지 못했다):

- ``test_no_dagster_job_schedule_or_sensor_targets_weather``: main의 Definitions에
  ``feature_weather_airkorea_air_quality_job`` 등 job과 그 schedule이 있다
  (``schedules.FEATURE_LOAD_SCHEDULE_SPECS``) — 카탈로그상 날씨 operation key다.
- ``test_no_dagster_asset_is_bound_to_weather``: main의 ``feature_operation_registry``가
  날씨 operation key에 handler를 결박하고, ``resources.PROVIDER_RECORD_RESOURCE_SPECS``에
  ``(python-airkorea-api, airkorea_stations)`` 등 날씨 dataset의 resource spec이 있으며
  ``feature_weather_*`` asset이 그 resource를 요구한다.
- ``test_no_launch_path_accepts_a_weather_operation_key``: main의 큐 runner
  (``feature_update_runner._OPERATION_RUNNER_SPEC_ROWS``)와 handler registry가 날씨 key를
  받는다 — ``resolve_feature_operation_handler``가 예외 없이 돌아온다.
- ``test_no_dagster_code_writes_weather_values``: main의 ``assets.py``가
  ``client.load_weather_values``·``client.load_air_quality``를, ``maintenance.py``가
  ``client.materialize_current_weather_summary``를 부르고 ``assets.py``가
  ``kortravelmap.providers.airkorea``를 import한다.
- ``test_map_runtime_source_cannot_reach_weather_only_providers``: main의
  ``provider_fetchers.py``가 ``importlib.import_module("airkorea")``를,
  ``kma_weather.py``가 ``kma``를 import한다.
- ``test_the_catalog_still_names_weather_operations``·
  ``test_kept_notice_loaders_are_still_launchable``: 항진명제 방지·양성 검사라 main에서도
  초록이다. 대신 유도를 비우면(예: ``_WEATHER_KIND``를 다른 값으로) 빨개지는지로 확인한다.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from dataclasses import dataclass
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
_DAGSTER_SRC = (
    _REPO_ROOT / "packages" / "kor-travel-map-dagster" / "src" / "kortravelmap" / "dagster"
)
_OPERATION_KEY_TAG = "kor_travel_map.operation_key"

#: 카탈로그 ``capabilities.produces``의 kind 값. 이름이 아니라 kind가 정체성이다.
_WEATHER_KIND = "weather"
_NOTICE_KIND = "notice"

#: 날씨 provider — 이 provider의 notice는 날씨 출처 notice(기상특보)다(ADR-105 정체성 규칙).
#: 리터럴이지만 오타는 :func:`test_the_catalog_still_names_weather_operations`가 잡는다
#: (카탈로그에 이 provider가 실재해야 한다).
_KMA_PROVIDER = "python-kma-api"

#: data.go.kr에서 기상청(KMA) 서비스가 사는 경로 접두사(``apis.data.go.kr/1360000/...``).
#: provider 라이브러리를 거치지 않고 HTTP를 직접 치는 우회를 잡는다.
_KMA_DATA_GO_KR_SERVICE_PATH = "1360000"

#: core client의 날씨 쓰기 — 이것을 부르는 것이 "날씨 값을 쓴다"는 효과다.
#: 셋 다 main에 실재했다(``kortravelmap.client.AsyncKorTravelMapClient``).
_WEATHER_WRITE_CALLS = frozenset(
    {"load_weather_values", "load_air_quality", "materialize_current_weather_summary"}
)

#: 날씨 전용 core 모듈. main에 실재했다(ADR-105로 core에서도 지운다).
_WEATHER_ONLY_CORE_MODULES = (
    "kortravelmap.infra.weather_repo",
    "kortravelmap.core.weather",
    "kortravelmap.providers.airkorea",
    "kortravelmap.providers.kma",
)

#: Map 런타임 소스 — Dagster code location이 import하는 core와 package들의 ``src``.
_RUNTIME_SOURCE_ROOTS: tuple[Path, ...] = (
    _REPO_ROOT / "src",
    *sorted((_REPO_ROOT / "packages").glob("*/src")),
)

_DATASET_ROW = re.compile(
    r"INSERT INTO provider_sync\.provider_datasets \([^)]*\) OVERRIDING SYSTEM VALUE "
    r"VALUES \((\d+), '([^']*)', '([^']*)', '(?:[^']|'')*', '[^']*', (?:true|false), "
    r"'([^']*)'"
)
_OPERATION_ROW = re.compile(
    r"INSERT INTO provider_sync\.provider_dataset_operations \([^)]*\) "
    r"VALUES \((\d+), '([^']*)', '([^']*)'"
)
_OPERATION_SCOPE_ROW = re.compile(
    r"INSERT INTO provider_sync\.provider_dataset_operation_scopes \([^)]*\) "
    r"VALUES \((\d+), '[^']*', '([^']*)', '([^']*)'"
)


@dataclass(frozen=True)
class _Dataset:
    provider: str
    dataset_key: str
    produces: frozenset[str]

    @property
    def is_weather(self) -> bool:
        """weather kind를 만들거나, 날씨 provider(KMA)의 notice다."""
        return _WEATHER_KIND in self.produces or (
            _NOTICE_KIND in self.produces and self.provider == _KMA_PROVIDER
        )


def _catalog_datasets() -> dict[int, _Dataset]:
    seed = _SEED.read_text(encoding="utf-8")
    datasets: dict[int, _Dataset] = {}
    for match in _DATASET_ROW.finditer(seed):
        capabilities = json.loads(match.group(4))
        produces = capabilities.get("produces", [])
        assert isinstance(produces, list), match.group(3)
        datasets[int(match.group(1))] = _Dataset(
            provider=match.group(2),
            dataset_key=match.group(3),
            produces=frozenset(str(kind) for kind in produces),
        )
    return datasets


def _catalog_operation_bindings() -> list[tuple[int, str, str]]:
    """``(provider_dataset_id, operation_key, operation_kind)`` — 두 결박 표를 합친다."""
    seed = _SEED.read_text(encoding="utf-8")
    bindings = [
        (int(match.group(1)), match.group(2), match.group(3))
        for match in _OPERATION_ROW.finditer(seed)
    ]
    bindings.extend(
        (int(match.group(1)), match.group(2), match.group(3))
        for match in _OPERATION_SCOPE_ROW.finditer(seed)
    )
    return bindings


def _transport_moves() -> dict[str, str]:
    """ADR-106(migration 404)이 kor-travel-transport dataset으로 옮긴 적재 operation key.

    시드(rev 300)는 옛 provider dataset을 담는다. 404가 그 operation을 끄고 새 dataset의
    operation(이름이 다르다)을 켜므로, 시드에서 유도한 key를 404의 대응표로 번역한다.
    """
    import importlib.util

    path = _REPO_ROOT / "alembic" / "versions" / "404_transport_provider_identity.py"
    spec = importlib.util.spec_from_file_location("_migration_404", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    datasets = _catalog_datasets()
    moved = {
        (old_provider, old_dataset): job
        for old_provider, old_dataset, _new, _label, _kind, job in module.DATASET_MOVES
    }
    return {
        key: moved[(datasets[dataset_id].provider, datasets[dataset_id].dataset_key)]
        for dataset_id, key, kind in _catalog_operation_bindings()
        if kind != "preview"
        and (datasets[dataset_id].provider, datasets[dataset_id].dataset_key) in moved
    }


def _operation_keys_for(dataset_ids: set[int]) -> frozenset[str]:
    """그 dataset에 결박된 적재 operation key — preview(fixture-only)는 뺀다.

    ADR-106으로 옮겨진 operation은 404가 켠 새 key로 번역한다.
    """
    moves = _transport_moves()
    return frozenset(
        moves.get(key, key)
        for dataset_id, key, kind in _catalog_operation_bindings()
        if dataset_id in dataset_ids and kind != "preview"
    )


def _weather_dataset_ids() -> set[int]:
    return {
        dataset_id
        for dataset_id, dataset in _catalog_datasets().items()
        if dataset.is_weather
    }


def _weather_operation_keys() -> frozenset[str]:
    return _operation_keys_for(_weather_dataset_ids())


def _weather_dataset_identities() -> set[tuple[str, str]]:
    datasets = _catalog_datasets()
    return {
        (datasets[dataset_id].provider, datasets[dataset_id].dataset_key)
        for dataset_id in _weather_dataset_ids()
    }


def _kept_notice_dataset_ids() -> set[int]:
    """날씨 출처가 아닌 notice dataset — ADR-105가 남기는 쪽."""
    return {
        dataset_id
        for dataset_id, dataset in _catalog_datasets().items()
        if _NOTICE_KIND in dataset.produces and not dataset.is_weather
    }


def _weather_only_providers() -> frozenset[str]:
    """카탈로그상 dataset이 **전부** 날씨인 provider. client를 부를 이유가 남지 않는다."""
    by_provider: dict[str, list[bool]] = {}
    for dataset in _catalog_datasets().values():
        by_provider.setdefault(dataset.provider, []).append(dataset.is_weather)
    return frozenset(provider for provider, flags in by_provider.items() if all(flags))


def _import_package(provider: str) -> str:
    """provider 배포명의 import 패키지 — 핀된 provider 표면 manifest가 정본.

    manifest에서 빠진 provider(Map이 더 이상 핀하지 않는 것)는 배포명 규약
    ``python-<package>-api``로 유도한다. 그 규약은 manifest에 남은 모든 provider에서
    성립해야 한다 — 어긋나면 유도가 낡았다.
    """
    surface = json.loads(_PROVIDER_SURFACE.read_text(encoding="utf-8"))["providers"]
    for name, entry in surface.items():
        match = re.fullmatch(r"python-(.+)-api", name)
        assert match is not None, f"provider 배포명이 규약 밖이다: {name}"
        assert entry["package"] == match.group(1), (
            f"provider 배포명 규약이 깨졌다: {name} → {entry['package']}"
        )
    if provider in surface:
        package = surface[provider]["package"]
        assert isinstance(package, str)
        assert package
        return package
    match = re.fullmatch(r"python-(.+)-api", provider)
    assert match is not None, f"provider 배포명이 규약 밖이다: {provider}"
    return match.group(1)


def test_the_catalog_still_names_weather_operations() -> None:
    """항진명제 방지 — 유도가 비면 아래 검사가 아무것도 재지 않는다.

    하한은 "본 것"에 건다(2026-10-01 시드 실측): 날씨 dataset 12개(weather 11 + KMA
    특보 1), 그 적재 operation 9개(KMA 다섯 · 에어코리아 · KREX 휴게소 기상 · 산림청 둘),
    날씨 전용 provider 둘(KMA · 에어코리아).
    """

    datasets = _catalog_datasets()
    assert any(dataset.provider == _KMA_PROVIDER for dataset in datasets.values()), (
        f"카탈로그에 {_KMA_PROVIDER}가 없다 — 정체성 상수가 낡았거나 오타다"
    )
    weather_ids = _weather_dataset_ids()
    assert len(weather_ids) >= 12, f"시드에서 날씨 dataset을 덜 찾았다: {sorted(weather_ids)}"
    keys = _weather_operation_keys()
    assert len(keys) >= 9, f"시드에서 날씨 적재 operation을 덜 찾았다: {sorted(keys)}"
    assert len(datasets) > len(weather_ids), "카탈로그 파싱이 날씨만 보고 있다"
    providers = _weather_only_providers()
    assert {_KMA_PROVIDER, "python-airkorea-api"} <= providers, (
        f"날씨 전용 provider 유도가 낡았다: {sorted(providers)}"
    )


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


def test_no_dagster_job_schedule_or_sensor_targets_weather() -> None:
    """job·schedule·sensor 대상의 operation key가 카탈로그상 날씨면 실패한다.

    UI의 "Launch"·백필·schedule·sensor는 전부 Definitions에 있는 job을 고른다. job이
    없으면 그 경로들이 날씨 operation을 고를 수 없다.
    """

    weather_keys = _weather_operation_keys()
    offenders: list[str] = []
    for job in defs.resolve_all_job_defs():
        operation_key = job.tags.get(_OPERATION_KEY_TAG)
        if job.name in weather_keys or operation_key in weather_keys:
            offenders.append(f"job {job.name} (operation_key={operation_key})")
    repository = defs.get_repository_def()
    for schedule in repository.schedule_defs:
        if schedule.job_name in weather_keys:
            offenders.append(f"schedule {schedule.name} → {schedule.job_name}")
    sensor_targets = 0
    for sensor in repository.sensor_defs:
        for target in _sensor_target_job_names(sensor):
            sensor_targets += 1
            if target in weather_keys:
                offenders.append(f"sensor {sensor.name} → {target}")
    # 항진명제 방지: 큐 sensor는 feature update job을 겨눈다 — 대상 추출이 0이면 낡았다.
    assert sensor_targets > 0, "sensor 대상 job을 하나도 읽지 못했다 — 추출이 낡았다"
    assert not offenders, f"Map Dagster에 날씨 instigator·job이 있다: {offenders}"


def test_no_dagster_asset_is_bound_to_weather() -> None:
    """asset이 날씨 operation에 결박되거나 날씨 dataset의 resource를 요구하면 실패한다."""

    weather_keys = _weather_operation_keys()
    weather_asset_keys = {
        asset_key
        for key, binding in FEATURE_OPERATION_HANDLERS.items()
        if key in weather_keys
        for asset_key in binding.asset_keys
    }
    identities = _weather_dataset_identities()
    weather_resource_keys = {
        spec.resource_key
        for spec in PROVIDER_RECORD_RESOURCE_SPECS
        if (spec.provider_package, spec.dataset_key) in identities
    }
    # 항진명제 방지: resource spec 결박 축이 실제로 dataset을 맞추는지 본다 — 남은
    # notice dataset의 spec은 찾아져야 한다.
    datasets = _catalog_datasets()
    kept_identities = {
        (datasets[dataset_id].provider, datasets[dataset_id].dataset_key)
        for dataset_id in _kept_notice_dataset_ids()
    }
    assert any(
        (spec.provider_package, spec.dataset_key) in kept_identities
        for spec in PROVIDER_RECORD_RESOURCE_SPECS
    ), "resource spec과 카탈로그 dataset을 하나도 맞추지 못했다 — 결박 축이 낡았다"

    offenders: list[str] = []
    for assets_def in defs.resolve_asset_graph().assets_defs:
        for key in assets_def.keys:
            name = key.to_user_string()
            if name in weather_asset_keys:
                offenders.append(f"asset {name}: 날씨 operation handler")
            required = set(assets_def.required_resource_keys) & weather_resource_keys
            if required:
                offenders.append(f"asset {name}: 날씨 resource {sorted(required)}")
    assert not weather_resource_keys, (
        f"날씨 dataset의 provider record resource가 남았다: {sorted(weather_resource_keys)}"
    )
    assert not offenders, f"Map Dagster asset이 날씨에 결박돼 있다: {offenders}"


def _provider_dataset_scope(operation_key: str, provider: str) -> ProviderDatasetRefreshScope:
    return ProviderDatasetRefreshScope(
        request_id="11111111-1111-4111-8111-111111111111",
        provider_dataset_id=1,
        sync_scope="dataset_wide",
        operation_key=operation_key,
        provider=provider,
        dataset_key="catalog-label",
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


def test_no_launch_path_accepts_a_weather_operation_key() -> None:
    """handler registry와 큐 runner가 날씨 operation key를 받지 않는다.

    큐 runner는 API(``POST /ops/pipeline/requests``)·PinVi cache target refresh·
    run-now가 모두 지나는 실행 경계다. ``provider_dataset`` scope로 넣는다 — 옛
    ``DISABLED_FEATURE_LOAD_OPERATION_KEYS`` 게이트가 일부러 통과시키던 "의도한 한 번"
    경로다. settings 팩토리가 불리면 runner가 provider 작업에 들어간 것이다.
    """

    weather_keys = _weather_operation_keys()
    registered = sorted(weather_keys & feature_operation_handler_keys())
    assert not registered, f"handler registry에 날씨 operation이 있다: {registered}"
    for operation_key in sorted(weather_keys):
        with pytest.raises(UnknownFeatureOperationHandlerError):
            resolve_feature_operation_handler(operation_key)

        runner = FeatureUpdateAssetRunner(
            common_resources={},
            log=None,
            settings_factory=lambda key=operation_key: pytest.fail(
                f"{key}: runner가 날씨 요청을 실행하려 했다"
            ),
        )
        scope = _provider_dataset_scope(operation_key, _KMA_PROVIDER)
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


def test_no_dagster_code_writes_weather_values() -> None:
    """효과 축: Dagster 소스가 날씨 값을 쓰는 core 경로를 부르거나 import하지 않는다.

    asset·op·sensor·runner 어느 것이든, 이름과 태그를 전부 피해 가도 날씨 값을 쓰려면
    여기 있는 client 메서드를 부르거나 날씨 전용 모듈을 import해야 한다.
    """

    scanned_files = 0
    scanned_calls = 0
    offenders: list[str] = []
    for path in sorted(_DAGSTER_SRC.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        scanned_files += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                scanned_calls += 1
                name = _call_name(node.func)
                if name in _WEATHER_WRITE_CALLS:
                    offenders.append(f"{relative}:{node.lineno}: {name}()")
        for module in _WEATHER_ONLY_CORE_MODULES:
            for line in _imports_module(tree, module):
                offenders.append(f"{relative}:{line}: import {module}")
    # 항진명제 방지: Dagster 패키지는 모듈 20개 남짓에 호출 수천 건이다.
    assert scanned_files >= 20, f"Dagster 소스를 거의 보지 못했다: {scanned_files}개"
    assert scanned_calls >= 1_000, f"호출을 거의 보지 못했다: {scanned_calls}건"
    assert not offenders, f"Map Dagster가 날씨 값을 쓸 수 있다: {offenders}"


def test_map_runtime_source_cannot_reach_weather_only_providers() -> None:
    """효과 축: Map 런타임 소스가 날씨 전용 provider client를 import하거나 KMA 경로를 치지 않는다.

    대상 provider는 카탈로그에서 유도한다 — dataset이 전부 날씨인 provider(KMA·에어코리아).
    KREX·산림청은 남는 dataset이 있으므로 client import 자체는 정당하다(그쪽은 위의
    operation·resource·효과 축이 잡는다).
    """

    packages = {provider: _import_package(provider) for provider in _weather_only_providers()}
    assert len(packages) >= 2, f"날씨 전용 provider를 덜 찾았다: {packages}"
    scanned = 0
    offenders: list[str] = []
    for root in _RUNTIME_SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            scanned += 1
            relative = path.relative_to(_REPO_ROOT).as_posix()
            tree = ast.parse(source, filename=relative)
            for provider, package in sorted(packages.items()):
                for line in _imports_module(tree, package):
                    offenders.append(f"{relative}:{line}: import {package} ({provider})")
            if _KMA_DATA_GO_KR_SERVICE_PATH in source:
                offenders.append(f"{relative}: KMA data.go.kr 서비스 경로")
    assert scanned > 100, f"런타임 소스를 거의 보지 못했다: {scanned}개"
    assert not offenders, f"Map 런타임 소스가 날씨 전용 provider를 부를 수 있다: {offenders}"


def test_kept_notice_loaders_are_still_launchable() -> None:
    """양성: 날씨 출처가 아닌 notice 적재는 **남아 있어야** 한다(ADR-105 결정 2).

    날씨를 지우다 notice 공용 경로를 함께 지우면 위의 음성 검사는 전부 초록이다 —
    "아무것도 없다"는 "날씨가 없다"를 만족한다. 그래서 남겨야 할 쪽을 카탈로그에서
    유도해 Definitions job · handler binding · 큐 runner spec 세 경계에서 결박한다.
    하한은 시드가 보여 주는 수다(2026-10-01: KREX 교통공지 · 산림청 산사태 예보).
    """

    kept_ids = _kept_notice_dataset_ids()
    assert len(kept_ids) >= 2, f"남는 notice dataset을 덜 찾았다: {sorted(kept_ids)}"
    kept_keys = _operation_keys_for(kept_ids)
    assert len(kept_keys) >= len(kept_ids), (
        f"남는 notice dataset에 적재 operation이 결박돼 있지 않다: {sorted(kept_keys)}"
    )
    assert not kept_keys & _weather_operation_keys(), "남는 notice와 날씨가 operation을 공유한다"

    job_operation_keys: set[str] = set()
    for job in defs.resolve_all_job_defs():
        job_operation_keys.add(job.name)
        tagged = job.tags.get(_OPERATION_KEY_TAG)
        if tagged is not None:
            job_operation_keys.add(tagged)
    runner = FeatureUpdateAssetRunner(
        common_resources={},
        log=None,
        settings_factory=lambda: pytest.fail("spec 조회만 한다 — settings를 만들 이유가 없다"),
    )
    datasets = _catalog_datasets()
    providers = {datasets[dataset_id].provider for dataset_id in kept_ids}
    missing: list[str] = []
    for operation_key in sorted(kept_keys):
        if operation_key not in job_operation_keys:
            missing.append(f"{operation_key}: Definitions job 없음")
        if operation_key not in feature_operation_handler_keys():
            missing.append(f"{operation_key}: handler binding 없음")
            continue
        binding = resolve_feature_operation_handler(operation_key)
        spec = runner._spec_for_scope(  # noqa: SLF001 - 큐 runner 실행 경계 결박
            _provider_dataset_scope(operation_key, sorted(providers)[0])
        )
        if spec.asset_key not in binding.asset_keys:
            missing.append(f"{operation_key}: runner asset {spec.asset_key} ≠ {binding.asset_keys}")
    assert not missing, f"날씨가 아닌 notice 적재가 사라졌다: {missing}"
