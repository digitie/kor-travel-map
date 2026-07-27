"""Admin frontend 의존 보안 경계 회귀 테스트."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "packages" / "kor-travel-map-admin" / "frontend"


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _named_data_variants(source: str) -> set[str]:
    return set(
        re.findall(
            r"\b(data-[a-z][a-z-]*)(?:/[A-Za-z0-9_-]+)?:",
            source,
        )
    )


@pytest.mark.unit
def test_frontend_security_versions_and_overrides_are_locked() -> None:
    root_package = _json(ROOT / "package.json")
    frontend_package = _json(FRONTEND / "package.json")
    lock_packages = _json(ROOT / "package-lock.json")["packages"]
    eslint_config = (FRONTEND / "eslint.config.mjs").read_text(encoding="utf-8")

    assert root_package["packageManager"] == "npm@10.9.4"
    assert root_package["engines"] == {"node": ">=22", "npm": "10.9.4"}
    assert root_package["scripts"]["audit:high"] == (
        "npx --yes npm@10.9.4 audit --audit-level=high"
    )
    assert root_package["scripts"]["verify:npm-tree"] == (
        "node scripts/verify-npm-tree.mjs"
    )
    assert root_package["scripts"]["verify:frontend-eslint"] == (
        "node scripts/verify-frontend-eslint-config.mjs"
    )
    assert root_package["scripts"]["verify:next-sharp"] == (
        "node scripts/verify-next-sharp.mjs"
    )
    assert root_package["overrides"] == {
        "next": {"postcss": "8.5.23", "sharp": "0.35.3"},
        "@redocly/openapi-core": {
            "js-yaml": "4.3.0",
            "minimatch": "10.2.5",
        },
    }
    assert frontend_package["dependencies"]["next"] == "16.2.12"
    for unused in ("@hookform/resolvers", "react-hook-form", "zod"):
        assert unused not in frontend_package["dependencies"]
    assert "shadcn" not in frontend_package["devDependencies"]
    assert "eslint-config-next" not in frontend_package["devDependencies"]
    assert frontend_package["devDependencies"]["@playwright/test"] == "1.60.0"
    assert "eslint-plugin-react-x" in frontend_package["devDependencies"]
    assert "eslint-plugin-react-dom" in frontend_package["devDependencies"]
    assert "reactX.configs.recommended" in eslint_config
    assert "reactDom.configs.recommended" in eslint_config
    assert '"import-x/no-anonymous-default-export": "warn"' in eslint_config

    assert lock_packages["node_modules/next"]["version"] == "16.2.12"
    assert lock_packages["node_modules/postcss"]["version"] == "8.5.23"
    assert lock_packages["node_modules/sharp"]["version"] == "0.35.3"
    assert lock_packages["node_modules/@playwright/test"]["version"] == "1.60.0"
    assert (
        lock_packages["node_modules/@redocly/openapi-core"]["version"]
        == "1.34.17"
    )
    assert lock_packages["node_modules/minimatch"]["version"] == "10.2.5"
    assert lock_packages["node_modules/js-yaml"]["version"] == "4.3.0"


@pytest.mark.unit
def test_vendor_contracts_are_fail_closed_in_every_npm_docker_context() -> None:
    root_package = _json(ROOT / "package.json")
    installer = (ROOT / "scripts" / "patch-redocly-openapi-core.mjs").read_text(
        encoding="utf-8"
    )
    sharp_smoke = (ROOT / "scripts" / "verify-next-sharp.mjs").read_text(
        encoding="utf-8"
    )
    npm_tree_verifier = (ROOT / "scripts" / "verify-npm-tree.mjs").read_text(
        encoding="utf-8"
    )
    eslint_verifier = (
        ROOT / "scripts" / "verify-frontend-eslint-config.mjs"
    ).read_text(encoding="utf-8")
    dockerfiles = {
        path.name: path.read_text(encoding="utf-8")
        for path in (
            ROOT / "docker" / "frontend.Dockerfile",
            ROOT / "docker" / "c7-playwright.Dockerfile",
        )
    }
    workflow = (ROOT / ".github" / "workflows" / "frontend.yml").read_text(
        encoding="utf-8"
    )

    assert root_package["scripts"]["postinstall"] == (
        "node scripts/patch-redocly-openapi-core.mjs"
    )
    assert 'const expectedVersion = "1.34.17";' in installer
    assert "existsSync(packageJsonPath)" in installer
    assert "beforeCount !== 1 || afterCount !== 0" in installer
    assert "minimatch.minimatch(url, pattern)" in installer
    assert 'const expectedNextVersion = "16.2.12";' in sharp_smoke
    assert 'const expectedSharpVersion = "0.35.3";' in sharp_smoke
    assert "optimizeImage" in sharp_smoke
    assert 'contentType: "image/webp"' in sharp_smoke
    assert "const expectedProblems = [" in npm_tree_verifier
    assert "tree.problems ?? []" in npm_tree_verifier
    assert '[npmExecPath, "--version"]' in npm_tree_verifier
    assert "assert.deepEqual(" in npm_tree_verifier
    assert 'severity("react-hooks/rules-of-hooks")' in eslint_verifier
    assert 'severity(`react-x/${duplicateRule}`)' in eslint_verifier
    assert 'severity("react-x/no-missing-key")' in eslint_verifier

    patch_copy = (
        "COPY scripts/patch-redocly-openapi-core.mjs "
        "./scripts/patch-redocly-openapi-core.mjs"
    )
    sharp_copy = (
        "COPY scripts/verify-next-sharp.mjs ./scripts/verify-next-sharp.mjs"
    )
    tree_copy = "COPY scripts/verify-npm-tree.mjs ./scripts/verify-npm-tree.mjs"
    install_token = "npx --yes npm@10.9.4 ci --workspaces --include=optional"
    tree_token = "npx --yes npm@10.9.4 run verify:npm-tree"
    verify_token = "npx --yes npm@10.9.4 run verify:next-sharp"
    for dockerfile in dockerfiles.values():
        assert patch_copy in dockerfile
        assert sharp_copy in dockerfile
        assert tree_copy in dockerfile
        assert install_token in dockerfile
        assert tree_token in dockerfile
        assert verify_token in dockerfile
        assert dockerfile.index(patch_copy) < dockerfile.index(install_token)
        assert dockerfile.index(sharp_copy) < dockerfile.index(install_token)
        assert dockerfile.index(tree_copy) < dockerfile.index(install_token)
        assert dockerfile.index(install_token) < dockerfile.index(tree_token)
        assert dockerfile.index(tree_token) < dockerfile.index(verify_token)

    assert 'node-version: "22.23.1"' in workflow
    assert install_token in workflow
    assert tree_token in workflow
    assert "npx --yes npm@10.9.4 run verify:frontend-eslint" in workflow
    assert verify_token in workflow
    assert "mcr.microsoft.com/playwright:v1.60.0-noble@sha256:" in (
        dockerfiles["c7-playwright.Dockerfile"]
    )


@pytest.mark.unit
def test_frontend_owns_every_named_shadcn_css_token_it_uses() -> None:
    css = (FRONTEND / "src" / "app" / "globals.css").read_text(encoding="utf-8")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FRONTEND / "src").rglob("*")
        if path.suffix in {".ts", ".tsx"}
    )

    assert '@import "shadcn/tailwind.css";' not in css
    used_variants = _named_data_variants(source)
    assert _named_data_variants(
        "group-data-open/tabs:block peer-data-busy/form:opacity-50"
    ) == {"data-open", "data-busy"}
    defined_variants = set(
        re.findall(r"@custom-variant\s+(data-[a-z][a-z-]*)\b", css)
    )
    assert used_variants == defined_variants

    for removed_token in (
        "animate-accordion-down",
        "animate-accordion-up",
        "no-scrollbar",
    ):
        assert removed_token not in source
