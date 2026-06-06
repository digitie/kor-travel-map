#!/usr/bin/env python3
"""Start mcp-telegram after loading local, ignored credentials."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


ENV_FILE = ".env.mcp-telegram"
REQUIRED_ENV = ("API_ID", "API_HASH")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _candidate_commands() -> list[str]:
    candidates: list[str] = []
    found = shutil.which("mcp-telegram")
    if found:
        candidates.append(found)

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(
            str(
                Path(appdata)
                / "Python"
                / f"Python{sys.version_info.major}{sys.version_info.minor}"
                / "Scripts"
                / "mcp-telegram.exe"
            )
        )

    candidates.append(str(Path.home() / ".local" / "bin" / "mcp-telegram"))
    return candidates


def _find_command() -> str | None:
    for command in _candidate_commands():
        if Path(command).exists():
            return command
    return None


def main() -> int:
    _load_env_file(Path.cwd() / ENV_FILE)
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("NO_COLOR", "1")

    missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
    if missing:
        sys.stderr.write(
            f"{ENV_FILE} or process env must define: {', '.join(missing)}\n"
        )
        return 1

    command = _find_command()
    if command is None:
        sys.stderr.write(
            "mcp-telegram executable not found. Install with "
            "`uv tool install mcp-telegram` or `python -m pip install --user "
            "mcp-telegram`.\n"
        )
        return 1

    args = sys.argv[1:] or ["start"]
    os.execvpe(command, [command, *args], os.environ)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
