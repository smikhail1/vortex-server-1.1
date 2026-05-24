#!/usr/bin/env bash
set -u

ROOT="${ROOT:-$HOME/vortex-server-1.1}"
cd "$ROOT" || exit 1

MAX_LOG_MB="${MAX_LOG_MB:-50}"
KEEP_TAIL_LINES="${KEEP_TAIL_LINES:-5000}"
ANALYSIS_MAX_AGE_DAYS="${ANALYSIS_MAX_AGE_DAYS:-2}"

RUNTIME_DIR="_runtime"
TAIL_DIR="$RUNTIME_DIR/log_tails"
REPORT="$RUNTIME_DIR/log_maintenance.log"

mkdir -p "$TAIL_DIR"

now() {
  date -Is
}

size_mb() {
  local f="$1"
  if [ ! -f "$f" ]; then
    echo 0
    return
  fi
  du -m "$f" 2>/dev/null | awk '{print $1}'
}

rotate_if_big() {
  local f="$1"
  local mb
  mb="$(size_mb "$f")"

  if [ "$mb" -gt "$MAX_LOG_MB" ]; then
    local ts
    ts="$(date +%Y-%m-%d_%H-%M-%S)"
    local base
    base="$(basename "$f")"

    echo "$(now) ROTATE $f size=${mb}MB max=${MAX_LOG_MB}MB" >> "$REPORT"

    tail -n "$KEEP_TAIL_LINES" "$f" > "$TAIL_DIR/${base%.log}_tail_${ts}.log" 2>/dev/null || true
    : > "$f"
  else
    echo "$(now) OK $f size=${mb}MB max=${MAX_LOG_MB}MB" >> "$REPORT"
  fi
}

echo "===== LOG MAINTENANCE START $(now) =====" >> "$REPORT"

echo "--- disk before ---" >> "$REPORT"
df -h >> "$REPORT" 2>&1 || true

rotate_if_big "server.log"
rotate_if_big "vortex.log"

echo "$(now) CLEAN python caches" >> "$REPORT"
find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find . -type d -name ".pytest_cache" -prune -exec rm -rf {} + 2>/dev/null || true

echo "$(now) CLEAN old analysis snapshots older than ${ANALYSIS_MAX_AGE_DAYS} days" >> "$REPORT"
find _analysis -type f \( \
  -name "dashboard_*.json" -o \
  -name "health_*.json" -o \
  -name "risk_*.json" -o \
  -name "reconcile_*.json" \
\) -mtime +"$ANALYSIS_MAX_AGE_DAYS" -delete 2>/dev/null || true

echo "--- disk after ---" >> "$REPORT"
df -h >> "$REPORT" 2>&1 || true

echo "===== LOG MAINTENANCE END $(now) =====" >> "$REPORT"
