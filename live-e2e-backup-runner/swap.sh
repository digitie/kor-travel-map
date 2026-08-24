#!/usr/bin/env bash
# live E2E에서 hot swap은 지원하지 않는다. recovery format이 설계·검증되기 전에는
# `apply` 값을 포함한 모든 입력을 무시하고 mutation 없이 종료한다.
set -euo pipefail

echo "live restore swap runner is disabled: backup artifacts are audit-only under the 300 baseline" >&2
echo "Alembic archive replay, previous-revision restore, and hot swap are unsupported" >&2
exit 2
