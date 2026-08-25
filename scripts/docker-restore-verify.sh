#!/usr/bin/env bash
# restore 산출물이 존재하지 않으므로 verification도 실행 가능한 복구 경로가 아니다.
set -euo pipefail

echo "restore verification is disabled: backup artifacts are audit-only under the 300 baseline" >&2
echo "Alembic archive replay, previous-revision restore, and hot swap are unsupported" >&2
exit 2
