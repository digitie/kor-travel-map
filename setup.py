"""setuptools build hook for production-only module exclusions."""

from __future__ import annotations

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

_HISTORICAL_H35_MODULES = frozenset(
    {
        "kortravelmap.cli._h35_cache_target",
        "kortravelmap.cli._h35_catalog",
        "kortravelmap.cli._h35_contract",
        "kortravelmap.cli._h35_csv5",
        "kortravelmap.cli._h35_schema",
        "kortravelmap.cli._h35_schema_version",
        "kortravelmap.cli.h35_cutover",
    }
)


class _ProductionBuildPy(_build_py):
    """0200 squash 이전 H35 실행 모듈을 wheel에서 제외한다."""

    def find_package_modules(
        self, package: str, package_dir: str
    ) -> list[tuple[str, str, str]]:
        return [
            module
            for module in super().find_package_modules(package, package_dir)
            if f"{module[0]}.{module[1]}" not in _HISTORICAL_H35_MODULES
        ]

    def find_all_modules(self) -> list[tuple[str, str, str]]:
        return [
            module
            for module in super().find_all_modules()
            if f"{module[0]}.{module[1]}" not in _HISTORICAL_H35_MODULES
        ]

    def run(self) -> None:
        super().run()
        build_root = Path(self.build_lib)
        for module_name in _HISTORICAL_H35_MODULES:
            module_path = build_root.joinpath(*module_name.split(".")).with_suffix(".py")
            module_path.unlink(missing_ok=True)


setup(cmdclass={"build_py": _ProductionBuildPy})
