#!/bin/bash
# Guarded same-pair pinned rebuild: on failure, immediately docker-start the Map/PinVi runtime containers.
set -u
TAG="${1:?tag}"; OUT=/root/rebuild-ktdm-rebuild-$TAG; RB=ktdm-rebuild-$TAG
MGR=$(tr -d '[:space:]' < /opt/kor-travel-docker-manager/.ktdm-source-revision)
SVCS="kor-travel-map-api-latest pinvi-api-latest kor-travel-map-dagster-code-server-latest pinvi-dagster-code-server-latest kor-travel-map-ui-latest pinvi-web-latest"
echo "[$(date -u +%T)] start $RB mgr=$MGR"
systemd-run --no-block --unit="$RB" --collect --property=Type=oneshot --property=TimeoutStartSec=7200 \
  /opt/kor-travel-docker-manager/scripts/run-pinned-rebuild-once "$MGR" "$OUT" >/dev/null || { echo launch-failed; exit 3; }
while [ "$(systemctl show "$RB" -p ActiveState --value)" = activating ]; do sleep 15; done
python3 -c "import json;d=json.load(open('$OUT/result.json'));print('[result]',{k:d.get(k) for k in ('success','outcome','phase','status','stage')})" 2>/dev/null || echo "[result] missing"
down=$(for c in $SVCS; do s=$(docker inspect -f '{{.State.Running}}' $c 2>/dev/null); [ "$s" = true ] || echo $c; done)
if [ -n "$down" ]; then echo "[$(date -u +%T)] RECOVER: starting $down"; docker start $down; fi
for i in $(seq 1 60); do s=$(docker ps -a --format '{{.Names}} {{.Status}}' | grep -E 'map-(api|ui|dagster)|pinvi-(api|web|dagster)'); echo "$s" | grep -qE 'starting|Exited|unhealthy' || break; sleep 15; done
echo "$s"; for u in https://${PINVI_UI_HOST:?set PINVI_UI_HOST}/ https://${PINVI_API_HOST:?set PINVI_API_HOST}/health https://${MAP_UI_HOST:?set MAP_UI_HOST}/login https://${MAP_API_HOST:?set MAP_API_HOST}/health; do curl -s -o /dev/null -m 20 -w "%{http_code} $u\n" $u; done
python3 -c "import json;d=json.load(open('/home/digitie/f1d-v5-rehearsal/state-pr203-retry/kor-travel-docker-manager/deploy-status.json'));print('[deploy-status]',d.get('state'),d.get('map_revision','')[:8],sorted((d.get('databases') or {}).keys()))"
echo GUARDED_DONE
