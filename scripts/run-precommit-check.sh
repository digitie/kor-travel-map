#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

resolve_python() {
  if [[ -n "${PYTHON:-}" ]]; then
    printf '%s\n' "$PYTHON"
  elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python"
  elif [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
    printf '%s\n' "$ROOT_DIR/.venv/Scripts/python.exe"
  else
    printf '%s\n' "python"
  fi
}

python_bin="$(resolve_python)"
check_name="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$check_name" in
  ruff-format)
    if [[ $# -eq 0 ]]; then
      echo "no Python files supplied for ruff format --check"
      exit 0
    fi
    "$python_bin" -m ruff format --check "$@"
    ;;
  mypy)
    "$python_bin" -m mypy --strict -p kortravelmap
    "$python_bin" -m mypy --strict -p kortravelmap.dagster
    ;;
  lint-imports)
    "$python_bin" -c "from importlinter.cli import lint_imports_command; import sys; sys.argv=['lint-imports']; lint_imports_command()"
    ;;
  *)
    echo "usage: $0 {ruff-format|mypy|lint-imports} [files...]" >&2
    exit 2
    ;;
esac
