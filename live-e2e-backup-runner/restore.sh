#!/usr/bin/env bash
# live E2E도 backup을 복원 경로로 사용하지 않는다. 300 이후 backup은 audit-only다.
set -euo pipefail

echo "live restore runner is disabled: backup artifacts are audit-only under the 300 baseline" >&2
echo "Alembic archive replay, previous-revision restore, and hot swap are unsupported" >&2
exit 2
