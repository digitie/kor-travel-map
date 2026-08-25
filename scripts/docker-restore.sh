#!/usr/bin/env bash
# `300` baseline에는 검증된 복구 형식이 아직 없다. backup은 audit/forensics 전용이며,
# 이 명령은 어떤 env 파일·Docker·DB·volume을 읽거나 바꾸기 전에 항상 종료한다.
set -euo pipefail

echo "restore is disabled: backup artifacts are audit-only under the 300 baseline" >&2
echo "Alembic archive replay, previous-revision restore, and hot swap are unsupported" >&2
exit 2
