#!/usr/bin/env bash
# Feeds fixture ninfer log text to the busy check.
set -u
script="$(dirname "$0")/../deploy/ninfer-mode"
fail=0

check() { # name expected_exit text
  printf '%s\n' "$3" | bash "$script" --busy-from-stdin
  local rc=$?
  if [[ $rc -ne $2 ]]; then echo "FAIL: $1 (exit $rc, wanted $2)"; fail=1; else echo "ok: $1"; fi
}

L='[2026-11-05 22:06:30.852] [info] ninfer-serve: throughput interval=5.000s prefill=4.4tok/s decode=0.6tok/s'
check "running=1 is busy" 0 "$L running=1 prefilling=0 decode_ready=0 waiting=0 avg_decode_batch=1.00"
check "prefilling=2 is busy" 0 "$L running=0 prefilling=2 decode_ready=0 waiting=0 avg_decode_batch=1.00"
check "decode_ready=1 is busy" 0 "$L running=0 prefilling=0 decode_ready=1 waiting=0 avg_decode_batch=1.00"
check "waiting=3 is busy" 0 "$L running=0 prefilling=0 decode_ready=0 waiting=3 avg_decode_batch=1.00"
check "all zero is idle" 1 "$L running=0 prefilling=0 decode_ready=0 waiting=0 avg_decode_batch=1.00"
check "no log lines is idle" 1 ""
check "non-throughput line is idle" 1 "[2026-11-05 22:06:30.852] [info] ninfer-serve: other running=5"
check "one busy line among idle is busy" 0 "$L running=0 prefilling=0 decode_ready=0 waiting=0
$L running=1 prefilling=0 decode_ready=0 waiting=0"
check "prefill=4.4tok/s alone is not a count" 1 "$L running=0 prefilling=0 decode_ready=0 waiting=0"

# --- full runs of main with stubbed systemctl, docker, curl, sleep ---
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/systemctl" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == is-active ]]; then
  [[ " $STUB_ACTIVE " == *" ${@: -1} "* ]]; exit $?
fi
echo "$*" >> "$STUB_DIR/calls"
[[ "$*" == "start $STUB_FAIL_START" ]] && exit 1
exit 0
STUB
cat > "$T/bin/docker" <<'STUB'
#!/usr/bin/env bash
cat "$STUB_DIR/dockerlog" 2>/dev/null
STUB
cat > "$T/bin/curl" <<'STUB'
#!/usr/bin/env bash
n=$(cat "$STUB_DIR/curlcount" 2>/dev/null || echo 0); echo $((n + 1)) > "$STUB_DIR/curlcount"
(( n < ${STUB_CURL_FAILS:-0} )) && exit 22
exit 0
STUB
printf '#!/usr/bin/env bash\nexit 0\n' > "$T/bin/sleep"
chmod +x "$T/bin/"*

run_main() { # name desired state_file_mode [running_mode, default = state_file_mode]
  rm -f "$T/calls" "$T/curlcount" "$T/state/mode-state.json"
  mkdir -p "$T/state"
  echo "$2" > "$T/state/desired-mode"
  [[ -n "$3" ]] && echo "{\"mode\":\"$3\",\"state\":\"ready\",\"busy\":false}" > "$T/state/mode-state.json"
  local running="${4:-$3}" active=ninfer.service
  [[ "$running" == speech ]] && active=ninfer-speech.service
  STUB_ACTIVE="$active" STUB_DIR="$T" SPEECH_GATEWAY_STATE_DIR="$T/state" PATH="$T/bin:$PATH" NINFER_HEALTH_TIMEOUT=4 \
    bash "$script"
}
expect() { # name want_state_json want_calls
  local got calls
  got="$(cat "$T/state/mode-state.json")"; calls="$(paste -sd'|' "$T/calls" 2>/dev/null)"
  if [[ "$got" == "$2" && "$calls" == "$3" ]]; then echo "ok: $1"
  else echo "FAIL: $1"; echo "  state: $got"; echo "  calls: $calls"; fail=1; fi
}

: > "$T/dockerlog"
STUB_FAIL_START="" run_main x speech full
expect "idle full to speech" '{"mode":"speech","state":"ready","busy":false}' \
  "stop ninfer.service|start ninfer-speech.service"

STUB_FAIL_START="" run_main x full speech
expect "idle speech to full" '{"mode":"full","state":"ready","busy":false}' \
  "stop ninfer-speech.service|start ninfer.service"

echo "$L running=1 prefilling=0 decode_ready=0 waiting=0" > "$T/dockerlog"
STUB_FAIL_START="" run_main x speech full
expect "busy refuses without touching units" '{"mode":"full","state":"ready","busy":true}' ""

: > "$T/dockerlog"
STUB_FAIL_START="ninfer-speech.service" run_main x speech full
expect "failed start rolls back" '{"mode":"full","state":"failed","busy":false}' \
  "stop ninfer.service|start ninfer-speech.service|stop ninfer-speech.service|start ninfer.service"

STUB_FAIL_START="" STUB_CURL_FAILS=2 run_main x speech full
expect "health timeout rolls back" '{"mode":"full","state":"failed","busy":false}' \
  "stop ninfer.service|start ninfer-speech.service|stop ninfer-speech.service|start ninfer.service"

# Stale report after a reboot: the file says speech but full ninfer is running.
: > "$T/dockerlog"
STUB_FAIL_START="" run_main x speech speech full
expect "stale speech state with full running still switches" \
  '{"mode":"speech","state":"ready","busy":false}' \
  "stop ninfer.service|start ninfer-speech.service"

STUB_FAIL_START="" run_main x speech switching full
expect "unrecognised state-file mode with full running still switches" \
  '{"mode":"speech","state":"ready","busy":false}' \
  "stop ninfer.service|start ninfer-speech.service"

exit $fail
