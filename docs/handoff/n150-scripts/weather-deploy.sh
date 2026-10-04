#!/bin/bash
# Deploy weather alerts skip-locked fix (#71): build api + code-server, migrate (no-op), recreate api + code-server, then cancel orphaned runs.
set -euo pipefail
WANT="${1:?merge sha}"
cd /home/digitie/kor-travel-weather
git fetch -q origin
[ -z "$(git status --porcelain)" ] || { echo "weather build context dirty; STOP"; exit 2; }
git merge -q --ff-only "$WANT"
[ "$(git rev-parse HEAD)" = "$WANT" ] || { echo "not at $WANT"; exit 3; }
cat > /tmp/wk-inner.sh <<'EOS'
set -euo pipefail
K=/opt/kor-travel-docker-manager
DC() { docker compose --project-name kor-travel-docker-manager --project-directory "$K" -f "$K/docker-compose.yml" "$@"; }
LOG=/root/weather-alerts-$(date -u +%Y%m%dT%H%M%SZ); install -d -m 0700 "$LOG"; echo "log=$LOG"
umask 077; exec 9>>/run/lock/kor-travel-docker-manager/global-mutation.lock; umask 022
flock -w 300 9 || { echo "lock G busy"; exit 75; }
rc=0; DC build kor-travel-weather-api kor-travel-weather-dagster-code-server </dev/null >"$LOG/build.out" 2>&1 || rc=$?
echo "build rc=$rc"; grep -E " Built|ERROR|failed" "$LOG/build.out" | tail -5; [ "$rc" = 0 ] || exit 5
rc=0; DC run -T --rm --no-deps kor-travel-weather-migrate </dev/null >"$LOG/migrate.out" 2>&1 || rc=$?
echo "migrate rc=$rc"; [ "$rc" = 0 ] || { grep -v -i -E "password|secret" "$LOG/migrate.out" | tail -10; exit 6; }
for c in $(docker ps -q); do docker inspect -f '{{.Name}} {{index .Config.Labels "com.docker.compose.config-hash"}}' "$c"; done | sort > "$LOG/pre.txt"
rc=0; DC up -d --no-deps kor-travel-weather-api kor-travel-weather-dagster-code-server </dev/null >"$LOG/up.out" 2>&1 || rc=$?
echo "up rc=$rc"; grep -v -i -E "password|secret" "$LOG/up.out" | tail -6
for c in $(docker ps -q); do docker inspect -f '{{.Name}} {{index .Config.Labels "com.docker.compose.config-hash"}}' "$c"; done | sort > "$LOG/post.txt"
echo "== changed"; { diff "$LOG/pre.txt" "$LOG/post.txt" || true; } | grep -E '^[<>]' | awk '{print $1,$2}' | sort -u -k2,2 | awk '{print $2}' | sort -u
exit $rc
EOS
sudo bash /tmp/wk-inner.sh </dev/null; rc=$?; rm -f /tmp/wk-inner.sh
for i in $(seq 1 40); do s=$(docker ps --format '{{.Names}} {{.Status}}' | grep -E '^kor-travel-weather-(api|dagster-code-server)'); echo "$s" | grep -q -E 'starting|unhealthy' || break; sleep 6; done
echo "$s"
curl -s -H 'Content-Type: application/json' -d '{"query":"{ workspaceOrError { ... on Workspace { locationEntries { name locationOrLoadError { __typename } } } } }"}' http://127.0.0.1:11002/graphql; echo
python3 /tmp/orph.py
exit $rc
