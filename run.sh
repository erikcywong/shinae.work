#!/usr/bin/env bash
# Coffee Super-Agent OS — one-command runner
set -e
cd "$(dirname "$0")"
PORT="${1:-8787}"
shift || true
export PYTHONIOENCODING=utf-8
if [ "${1:-}" = "--reset" ]; then rm -rf var; fi
echo "Coffee Super-Agent OS → http://127.0.0.1:${PORT}"
python3 app/server.py --port "$PORT" "$@"
