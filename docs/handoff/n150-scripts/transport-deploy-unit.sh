systemd-run --no-block --unit=transport-deploy-<sha4> --collect --property=Type=oneshot --property=TimeoutStartSec=7200 \
  --uid=digitie --gid=digitie --working-directory=/home/digitie/apps/kor-travel-transport \
  -E HOME=/home/digitie -E REMOTE_APP_DIR=/home/digitie/apps/kor-travel-transport -E REMOTE_ENV_FILE=.env.server14 \
  -E COMPOSE_PROJECT_NAME=kor-travel-transport -E CANDIDATE_SHA=<CANDIDATE_SHA> \
  -E DEPLOY_MODE=deploy \
  bash -c './scripts/deploy-server14-remote.sh > /tmp/transport-deploy-<sha4>.log 2>&1'
echo "result=$(systemctl show transport-deploy-<sha4> -p Result --value 2>/dev/null)"
tail -25 /tmp/transport-deploy-<sha4>.log | cut -c1-220
docker ps --format "{{.Names}} {{.Status}}" | grep transport
