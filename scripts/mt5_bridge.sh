#!/usr/bin/env bash
# mt5_bridge.sh — lifecycle helper for the MT5 Docker bridge on Apple Silicon.
#
# The bridge runs a headless MetaTrader 5 terminal inside an x86_64 container
# (prebuilt gmag11/metatrader5_vnc image; see docker/compose.mt5.yml); the
# siliconmetatrader5 Python client (backend="bridge") connects to its rpyc
# port. See README_MT5_SETUP.md for the full picture.
#
# Works with any running Docker daemon (Docker Desktop, OrbStack, Colima).
#
# Usage:
#   scripts/mt5_bridge.sh up        # docker compose up -d (pulls image first time)
#   scripts/mt5_bridge.sh down      # compose down (container stops, volume persists)
#   scripts/mt5_bridge.sh status    # daemon / container / port state
#   scripts/mt5_bridge.sh logs      # follow container logs
#   scripts/mt5_bridge.sh vnc       # print the web-VNC URL for broker login
#   scripts/mt5_bridge.sh test      # run the Python connection smoke test
#
# Env (override as needed):
#   MT5_BRIDGE_PORT   rpyc port to probe       (default 18812; 8001 also mapped)
#   MT5_VNC_USER      web UI username          (default trader)
#   MT5_VNC_PASSWORD  web UI password          (default momq-local — change it)
#   MT5_COMPOSE_FILE  path to the compose file (default docker/compose.mt5.yml)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${MT5_COMPOSE_FILE:-${PROJECT_DIR}/docker/compose.mt5.yml}"
BRIDGE_PORT="${MT5_BRIDGE_PORT:-18812}"
VNC_URL="http://localhost:3000"

red()   { printf "\033[31m%s\033[0m\n" "$*"; }
green() { printf "\033[32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }

daemon_up() { docker info >/dev/null 2>&1; }

ensure_daemon() {
  command -v docker >/dev/null 2>&1 || { red "docker CLI not found."; exit 1; }
  if daemon_up; then
    green "Docker daemon: running."
    return
  fi
  # Try to wake Docker Desktop if it's installed but not running.
  if [ -d "/Applications/Docker.app" ]; then
    yellow "Docker daemon not running — starting Docker Desktop…"
    open -a Docker
    for _ in $(seq 1 30); do
      sleep 2
      daemon_up && { green "Docker daemon: running."; return; }
    done
  fi
  red "No Docker daemon reachable. Start Docker Desktop / OrbStack (or Colima:"
  red "  brew install colima && colima start --arch x86_64 --vm-type=qemu)"
  exit 1
}

compose() {
  [ -f "${COMPOSE_FILE}" ] || { red "Compose file not found: ${COMPOSE_FILE}"; exit 1; }
  docker compose -f "${COMPOSE_FILE}" "$@"
}

port_open() { nc -z localhost "${BRIDGE_PORT}" >/dev/null 2>&1; }

cmd="${1:-status}"
case "${cmd}" in
  up)
    ensure_daemon
    yellow "Bringing up the MT5 container (first run pulls ~1.6 GB, then MT5"
    yellow "auto-installs inside — allow ~5-15 min under emulation)…"
    compose up -d
    green "Container starting. Watch progress:  scripts/mt5_bridge.sh logs"
    echo "Web UI (broker login):  ${VNC_URL}  (user: ${MT5_VNC_USER:-trader} / pwd: ${MT5_VNC_PASSWORD:-momq-local})"
    echo "Then probe the bridge:  scripts/mt5_bridge.sh test"
    ;;
  down)
    compose down
    green "Container stopped (config volume persists)."
    ;;
  status)
    if daemon_up; then green "Docker daemon: running"; else yellow "Docker daemon: not running"; fi
    if daemon_up && [ -f "${COMPOSE_FILE}" ]; then
      docker compose -f "${COMPOSE_FILE}" ps 2>/dev/null || true
    fi
    if port_open; then green "rpyc bridge: reachable on :${BRIDGE_PORT}";
    else yellow "rpyc bridge: not reachable on :${BRIDGE_PORT}"; fi
    ;;
  logs)
    compose logs -f
    ;;
  vnc)
    echo "${VNC_URL}  (user: ${MT5_VNC_USER:-trader} / password: ${MT5_VNC_PASSWORD:-momq-local})"
    ;;
  test)
    if ! port_open; then
      yellow "Bridge port :${BRIDGE_PORT} closed — the smoke test will fall back to the MOCK."
    fi
    ( cd "${PROJECT_DIR}" && uv run python tests/test_smoke.py )
    ;;
  *)
    grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
