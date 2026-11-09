#!/usr/bin/env bash
# Tier decision of the terranse llm-tier boot script, with stubbed nvidia-smi and systemctl.
set -u
script="${LLM_TIER_SCRIPT:-$(dirname "$0")/../../../../terranse/ansible/roles/llm/files/llm-tier}"
[[ -f "$script" ]] || { echo "FAIL: llm-tier script not found: $script"; exit 1; }
fail=0
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
cat > "$T/bin/nvidia-smi" <<'STUB'
#!/usr/bin/env bash
[[ -n "${STUB_VRAM:-}" ]] || exit 9
echo "$STUB_VRAM"
STUB
cat > "$T/bin/systemctl" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == is-active ]]; then [[ " $STUB_ACTIVE " == *" ${@: -1} "* ]]; exit $?; fi
echo "$*" >> "$STUB_DIR/calls"
exit 0
STUB
chmod +x "$T/bin/"*

run() { # vram active
  rm -f "$T/calls" "$T/tier"; rm -rf "$T/dropin"
  STUB_VRAM="$1" STUB_ACTIVE="$2" STUB_DIR="$T" PATH="$T/bin:$PATH" LLM_TIER_FILE="$T/tier" \
    LLM_TIER_DROPIN_DIR="$T/dropin" bash "$script" 2>/dev/null
}
expect() { # name tier calls dropin_context
  local tier calls ctx=""
  tier="$(cat "$T/tier" 2>/dev/null)"; calls="$(paste -sd'|' "$T/calls" 2>/dev/null)"
  [[ -f "$T/dropin/zz-llm-tier.conf" ]] && ctx="$(grep -o 'OLLAMA_CONTEXT_LENGTH=[0-9]*' "$T/dropin/zz-llm-tier.conf")"
  if [[ "$tier" == "$2" && "$calls" == "$3" && "$ctx" == "$4" ]]; then echo "ok: $1"
  else echo "FAIL: $1"; echo "  tier=$tier calls=$calls ctx=$ctx"; fail=1; fi
}

run 24576 "";  expect "24 GB slice is full and starts ninfer" full "start ninfer.service" ""
run 20480 "";  expect "exactly 20 GB is full" full "start ninfer.service" ""
run 20479 "";  expect "just under 20 GB is shared" shared "daemon-reload|start ollama.service" "OLLAMA_CONTEXT_LENGTH=8192"
run 12288 "";  expect "12 GB slice is shared with 8192 context" shared "daemon-reload|start ollama.service" "OLLAMA_CONTEXT_LENGTH=8192"
run "" "";     expect "unreadable GPU falls back to shared" shared "daemon-reload|start ollama.service" "OLLAMA_CONTEXT_LENGTH=8192"
run 24576 "ninfer-speech.service"
expect "active speech session: full but ninfer not started" full "" ""

exit $fail
