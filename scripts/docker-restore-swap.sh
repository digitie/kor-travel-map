#!/usr/bin/env bash
# `300` baseline에는 restore target/swap 계약이 없다. 실행 본문을 남기지 않아 향후
# guard 회귀가 과거 destructive 경로를 재노출하지 않게 한다.
set -euo pipefail

echo "restore swap is disabled: backup artifacts are audit-only under the 300 baseline" >&2
echo "Alembic archive replay, previous-revision restore, and hot swap are unsupported" >&2
exit 2
