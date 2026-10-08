#!/usr/bin/env bash
# Phase 0 boundary probes for docs/EXECUTION_DESIGN.md (Linux).
# Uses no AI quota. Prints PASS/FAIL/INFO per check; exit 1 if any FAIL.
set -u
W=$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/axon-probe.XXXXXX")
trap 'rm -rf "$W"' EXIT
fail=0
pass() { echo "PASS $1"; }
bad() { echo "FAIL $1"; fail=1; }
expect_ok() { if "${@:2}" >/dev/null 2>&1; then pass "$1"; else bad "$1"; fi; }
expect_no() { if "${@:2}" >/dev/null 2>&1; then bad "$1"; else pass "$1"; fi; }

# Project repo + per-attempt clone sharing objects read-only.
git init -q "$W/main"
git -C "$W/main" -c user.name=p -c user.email=p@local commit -q --allow-empty -m base
BASE=$(git -C "$W/main" rev-parse HEAD)
git clone -q --shared "$W/main" "$W/att"

# Attempt sandbox. --tmpfs /run hides docker.sock and the user dbus/systemd socket.
SB=(bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --tmpfs /run --tmpfs "$HOME"
    --ro-bind "$W/main" "$W/main" --bind "$W/att" "$W/att" --chdir "$W/att"
    --unshare-pid --die-with-parent)
NONET=("${SB[@]}" --unshare-net)
G=(git -c user.name=axon -c user.email=axon@local -c core.hooksPath=/dev/null)

expect_ok "snapshot commit inside sandbox" "${NONET[@]}" "${G[@]}" commit -q --allow-empty -m snap
expect_no "main repo hooks read-only"      "${NONET[@]}" sh -c "echo x > '$W/main/.git/hooks/post-checkout'"
expect_no "main repo objects read-only"    "${NONET[@]}" sh -c "echo x > '$W/main/.git/objects/probe'"
expect_ok "result exported as bundle"      "${NONET[@]}" git bundle create -q "$W/att/out.bundle" "$BASE..HEAD"
expect_ok "runtime fetches bundle"         git -C "$W/main" fetch -q "$W/att/out.bundle" HEAD:refs/axon/att1
expect_no "user credentials hidden"        "${NONET[@]}" sh -c 'ls ~/.claude ~/.codex ~/.ssh'
expect_no "docker socket hidden"           "${NONET[@]}" test -S /var/run/docker.sock
expect_no "user dbus socket hidden"        "${NONET[@]}" test -S "/run/user/$(id -u)/bus"
expect_no "check sandbox has no network"   "${NONET[@]}" curl -s -m5 https://example.com
expect_ok "nested sandbox allowed"         "${SB[@]}" bwrap --ro-bind / / --dev /dev --unshare-net true

# Resource limits + kill whole tree via a systemd user scope (cgroup v2).
U=axon-probe-$$
MEM=$(systemd-run --user --scope -q -p MemoryMax=200M --unit="$U-mem" \
  sh -c 'cat /sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup)/memory.max' 2>/dev/null)
[ "$MEM" = 209715200 ] && pass "cgroup MemoryMax applied" || bad "cgroup MemoryMax applied ($MEM)"
T=$((40000 + $$ % 9999))
systemd-run --user --scope -q --unit="$U-kill" sh -c "setsid sh -c 'sleep $T & sleep $T' & sleep $T" &
sleep 1
systemctl --user stop "$U-kill.scope" 2>/dev/null
sleep 1
expect_no "stop kills setsid'd children" pgrep -x -f "sleep $T"

# Codex tool sandbox, nested inside the attempt sandbox.
if command -v codex >/dev/null; then
  CX=$(readlink -f "$(command -v codex)"); CXD=$(dirname "$(dirname "$CX")")
  CS=("${SB[@]}" --ro-bind "$CXD" "$CXD" --ro-bind "$HOME/.codex" "$HOME/.codex"
      "$CX" sandbox -P :workspace -C "$W/att" --)
  expect_ok "codex: workspace write"   "${CS[@]}" touch "$W/att/ok"
  # $HOME is a writable tmpfs in the outer sandbox, so only codex can block this.
  expect_no "codex: outside write"     "${CS[@]}" touch "$HOME/x"
  expect_no "codex: network"           "${CS[@]}" curl -s -m5 https://example.com
  "${CS[@]}" test -r "$HOME/.codex/auth.json" 2>/dev/null &&
    echo "INFO codex: commands can read the agent's own auth.json (mitigated by secret scan)"
else
  echo "INFO codex not installed; skipped"
fi
exit $fail
