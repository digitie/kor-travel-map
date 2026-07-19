#!/usr/bin/env bash

# C7 runner가 source하는 process/container lifecycle primitive. 이 파일은 단독 실행하지 않는다.

terminate_active_command() {
  local grace_attempts="${1:-40}"
  local attempt pgid="${ACTIVE_COMMAND_PGID-}" pid="$ACTIVE_COMMAND_PID"
  [[ "$grace_attempts" =~ ^[0-9]+$ ]] && (( grace_attempts >= 1 )) || return 1
  [[ -n "$pid" ]] || return 0
  if [[ -n "$pgid" && "$pgid" == "$pid" ]]; then
    kill -TERM -- "-$pgid" 2>/dev/null || true
  else
    kill -TERM "$pid" 2>/dev/null || true
  fi
  for (( attempt = 0; attempt < grace_attempts; attempt += 1 )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null || true
      ACTIVE_COMMAND_PID=""
      ACTIVE_COMMAND_PGID=""
      return 0
    fi
    sleep 0.25
  done
  if [[ -n "$pgid" && "$pgid" == "$pid" ]]; then
    kill -KILL -- "-$pgid" 2>/dev/null || true
  else
    kill -KILL "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
  ACTIVE_COMMAND_PID=""
  ACTIVE_COMMAND_PGID=""
}

remove_active_container() {
  local expected_uid="${1:-0}"
  local expected_gid="${2:-$expected_uid}"
  local active_container_id active_container_name observed_container_ids
  [[ "$expected_uid" =~ ^[0-9]+$ && "$expected_gid" =~ ^[0-9]+$ ]] || return 1
  [[ -n "${ACTIVE_CID_FILE-}" && -n "${ACTIVE_CONTAINER_REF_FILE-}" ]] || return 0
  if [[ ! -e "$ACTIVE_CID_FILE" && ! -L "$ACTIVE_CID_FILE" ]]; then
    # creator intent만 있으면 docker create→cidfile gap일 수 있다. 자동 추측 정리를 하지
    # 않고 tracked recovery tool이 name/label/runtime mount를 검증하도록 상태를 보존한다.
    [[ ! -e "$ACTIVE_CONTAINER_REF_FILE" && ! -L "$ACTIVE_CONTAINER_REF_FILE" ]] && return 0
    return 1
  fi
  [[
    -f "$ACTIVE_CID_FILE" &&
    ! -L "$ACTIVE_CID_FILE" &&
    "$(stat -c '%u:%g:%a' -- "$ACTIVE_CID_FILE" 2>/dev/null)" == "$expected_uid:$expected_gid:600"
  ]] || return 1
  [[
    -f "$ACTIVE_CONTAINER_REF_FILE" &&
    ! -L "$ACTIVE_CONTAINER_REF_FILE" &&
    "$(stat -c '%u:%g:%a' -- "$ACTIVE_CONTAINER_REF_FILE" 2>/dev/null)" == "$expected_uid:$expected_gid:600"
  ]] || return 1
  [[
    -n "${ACTIVE_CREATE_OUTCOME_FILE-}" &&
    -f "$ACTIVE_CREATE_OUTCOME_FILE" &&
    ! -L "$ACTIVE_CREATE_OUTCOME_FILE" &&
    "$(stat -c '%u:%g:%a' -- "$ACTIVE_CREATE_OUTCOME_FILE" 2>/dev/null)" == "$expected_uid:$expected_gid:600"
  ]] || return 1
  active_container_name="$(python3 - \
    "$ACTIVE_CONTAINER_REF_FILE" \
    "$ACTIVE_CREATE_OUTCOME_FILE" \
    "${RUNTIME_DIR-}" <<'PY'
import json
import os
import stat
import sys

try:
    values = []
    for raw in sys.argv[1:3]:
        fd = os.open(raw, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            observed = os.fstat(fd)
            if not stat.S_ISREG(observed.st_mode) or stat.S_IMODE(observed.st_mode) != 0o600:
                raise RuntimeError("unsafe state file")
            values.append(json.loads(os.read(fd, 4097)))
        finally:
            os.close(fd)
except (OSError, ValueError):
    raise SystemExit(1)
value, outcome = values
if not isinstance(value, dict) or set(value) != {
    "container_name",
    "creator_pgid",
    "creator_pid",
    "creator_sid",
    "creator_start_ticks",
    "phase",
    "runtime",
    "version",
}:
    raise SystemExit(1)
name = value["container_name"]
if (
    not isinstance(name, str)
    or value["phase"] != "created"
    or (
        value["creator_pid"],
        value["creator_pgid"],
        value["creator_sid"],
        value["creator_start_ticks"],
    )
    != (0, 0, 0, 0)
    or value["runtime"] != sys.argv[3]
    or not isinstance(outcome, dict)
    or set(outcome) != {"phase", "status", "version"}
    or outcome != {"phase": "create", "status": 0, "version": 1}
):
    raise SystemExit(1)
print(name)
PY
  )" || return 1
  [[
    "$active_container_name" =~ ^kor-travel-map-c7-e2e-[0-9]+$ &&
    "$active_container_name" == "${ACTIVE_CONTAINER_NAME-}"
  ]] || return 1
  active_container_id="$(<"$ACTIVE_CID_FILE")"
  [[ "$active_container_id" =~ ^[0-9a-f]{64}$ ]] || return 1
  observed_container_ids="$(
    timeout --signal=KILL 10s docker container ls --all --quiet --no-trunc \
      --filter "id=$active_container_id" 2>/dev/null
  )" || return 1
  if [[ -n "$observed_container_ids" ]]; then
    [[ "$observed_container_ids" == "$active_container_id" ]] || return 1
    timeout --signal=KILL 30s docker container rm --force -- \
      "$active_container_id" >/dev/null 2>&1 || return 1
  fi
  rm -f -- "$ACTIVE_CID_FILE" "$ACTIVE_CONTAINER_REF_FILE" || return 1
  [[ -z "${ACTIVE_CREATE_OUTCOME_FILE-}" ]] ||
    rm -f -- "$ACTIVE_CREATE_OUTCOME_FILE"
}
