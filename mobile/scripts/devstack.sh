#!/usr/bin/env bash
# Local test stack for the mobile app, all on this Mac (no LAN needed):
#   Android emulator (window visible) -> Expo Go -> Metro :8081
#                                     -> backend :8000 (mock AI)
# The emulator reaches both ports through `adb reverse`, so the app uses
# http://127.0.0.1:8000 inside the emulator.
#
# The backend runs from the pinned worktree ../../sahayak-pin (a detached
# checkout of a known-good commit), never from the working tree the other
# window edits. Its Python venv and test data live inside the pin, untracked:
#   .venv/                     Python environment
#   .devdata/ticketapp.db      the test database (uploads in .devdata/uploads)
#   .devdata/test-accounts.txt the test logins
#
# Usage: scripts/devstack.sh start | stop | status | open
set -euo pipefail

MOBILE="$(cd "$(dirname "$0")/.." && pwd)"
PIN="${SAHAYAK_PIN:-$(cd "$MOBILE/../.." && pwd)/sahayak-pin}"
DATA="$PIN/.devdata"
STATE="$MOBILE/.devstack"            # pid files and logs (gitignored)
SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
ADB="$SDK/platform-tools/adb"
AVD="${AVD:-Medium_Phone_API_36.1}"
BACKEND_PORT=8000
METRO_PORT=8081

mkdir -p "$STATE"

running() { [ -f "$STATE/$1.pid" ] && kill -0 "$(cat "$STATE/$1.pid")" 2>/dev/null; }

start_emulator() {
  if "$ADB" devices | grep -q '^emulator-.*device$'; then
    echo "emulator: already running"
  else
    echo "emulator: starting $AVD (window opens on screen)"
    nohup "$SDK/emulator/emulator" -avd "$AVD" -camera-back virtualscene -camera-front emulated \
      >"$STATE/emulator.log" 2>&1 </dev/null &
    echo $! >"$STATE/emulator.pid"
  fi
  "$ADB" wait-for-device
  until [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 2; done
  "$ADB" reverse tcp:$BACKEND_PORT tcp:$BACKEND_PORT >/dev/null
  "$ADB" reverse tcp:$METRO_PORT tcp:$METRO_PORT >/dev/null
  echo "emulator: booted, ports $BACKEND_PORT and $METRO_PORT reversed"
}

start_backend() {
  if running backend; then echo "backend: already running"; return; fi
  [ -x "$PIN/.venv/bin/uvicorn" ] || { echo "backend: no venv in $PIN (see README)"; exit 1; }
  echo "backend: starting from $PIN @ $(git -C "$PIN" rev-parse --short HEAD)"
  (
    cd "$PIN"
    AI_PROVIDER=mock APP_ENV=development DB_PATH="$DATA/ticketapp.db" PYTHONDONTWRITEBYTECODE=1 \
      nohup .venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port $BACKEND_PORT \
      >"$STATE/backend.log" 2>&1 </dev/null &
    echo $! >"$STATE/backend.pid"
  )
  for _ in $(seq 30); do
    curl -s --noproxy '*' -m 2 "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null && { echo "backend: up"; return; }
    sleep 1
  done
  echo "backend: not answering, see $STATE/backend.log"; exit 1
}

start_metro() {
  if running metro; then echo "metro: already running"; return; fi
  echo "metro: starting on :$METRO_PORT"
  (
    cd "$MOBILE"
    EXPO_PUBLIC_API_URL="http://127.0.0.1:$BACKEND_PORT" \
      nohup npx expo start --localhost --port $METRO_PORT >"$STATE/metro.log" 2>&1 </dev/null &
    echo $! >"$STATE/metro.pid"
  )
  for _ in $(seq 60); do
    curl -s --noproxy '*' -m 2 "http://127.0.0.1:$METRO_PORT/status" | grep -q running && { echo "metro: up"; return; }
    sleep 1
  done
  echo "metro: not answering, see $STATE/metro.log"; exit 1
}

open_app() {
  if ! "$ADB" shell pm list packages | grep -q 'host.exp.exponent'; then
    # Expo CLI caches the Expo Go APK for this SDK after its first install.
    apk="$(ls "$HOME"/.expo/android-apk-cache/Expo-Go-58.*.apk 2>/dev/null | tail -1)"
    [ -n "$apk" ] || { echo "app: Expo Go not installed and no cached APK (README: Expo Go)"; exit 1; }
    echo "app: installing $(basename "$apk")"
    "$ADB" install -r "$apk" >/dev/null
  fi
  "$ADB" shell am force-stop host.exp.exponent
  "$ADB" shell am start -a android.intent.action.VIEW -d "exp://127.0.0.1:$METRO_PORT" host.exp.exponent >/dev/null
  echo "app: opening in Expo Go (first load bundles for ~30 s)"
}

stop_one() {
  if running "$1"; then
    # npx starts a child; stop the whole process group of children too.
    pkill -P "$(cat "$STATE/$1.pid")" 2>/dev/null || true
    kill "$(cat "$STATE/$1.pid")" 2>/dev/null || true
    echo "$1: stopped"
  else
    echo "$1: not running"
  fi
  rm -f "$STATE/$1.pid"
}

case "${1:-}" in
  start)
    start_emulator
    start_backend
    start_metro
    open_app
    ;;
  open) open_app ;;
  stop)
    stop_one metro
    stop_one backend
    if "$ADB" devices | grep -q '^emulator-'; then "$ADB" emu kill >/dev/null 2>&1 || true; echo "emulator: stopped"; fi
    rm -f "$STATE/emulator.pid"
    ;;
  status)
    for p in backend metro; do running $p && echo "$p: running" || echo "$p: stopped"; done
    "$ADB" devices | grep -q '^emulator-.*device$' && echo "emulator: running" || echo "emulator: stopped"
    ;;
  *)
    echo "usage: $0 start | stop | status | open"; exit 2 ;;
esac
