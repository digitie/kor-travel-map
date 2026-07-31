#!/usr/bin/env bash
# T-VN-H35 — map/pinvi build context를 target 커밋으로 맞춘다.
#
# target은 인자로 받는다. 인자가 없으면 확인만 하고 아무것도 바꾸지 않는다.
set -Eeuo pipefail
MAP=/home/digitie/.cache/c7-final.pihf0x9o/map
PINVI=/home/digitie/.cache/c7-final.pihf0x9o/pinvi
TARGET="${1:-}"

echo "=== map build ctx ==="
echo "  HEAD   : $(git -C "$MAP" rev-parse HEAD | cut -c1-12)"
dirty="$(git -C "$MAP" status --porcelain | head -3 | tr '\n' ' ')"
echo "  dirty  : [${dirty}]"
git -C "$MAP" fetch origin --prune --quiet
echo "  origin/main: $(git -C "$MAP" rev-parse origin/main | cut -c1-12)"

echo "=== pinvi build ctx (HELD) ==="
echo "  HEAD   : $(git -C "$PINVI" rev-parse HEAD | cut -c1-12)"
pdirty="$(git -C "$PINVI" status --porcelain | head -3 | tr '\n' ' ')"
echo "  dirty  : [${pdirty}]"

if [ -z "$TARGET" ]; then
  echo
  echo "(확인만 함 — target 인자를 주면 checkout 한다)"
  exit 0
fi

if [ -n "$dirty" ]; then
  echo "** map build ctx가 dirty다 — 중단" >&2
  exit 1
fi

echo
echo "=== target $TARGET 으로 checkout ==="
git -C "$MAP" cat-file -t "$TARGET" >/dev/null 2>&1 || {
  echo "** target 커밋이 없다 (fetch 후에도)" >&2; exit 1; }
# target이 origin/main과 같은지 확인 — 다르면 무엇을 배포하는지 불분명해진다.
if [ "$(git -C "$MAP" rev-parse origin/main)" != "$(git -C "$MAP" rev-parse "$TARGET")" ]; then
  echo "** target != origin/main — 중단(무엇을 배포하는지 불분명하다)" >&2
  exit 1
fi
git -C "$MAP" checkout --detach --quiet "$TARGET"
echo "  HEAD -> $(git -C "$MAP" rev-parse HEAD | cut -c1-12)"
echo "  dirty: [$(git -C "$MAP" status --porcelain | head -3 | tr '\n' ' ')]"
