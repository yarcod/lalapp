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
exit $fail
