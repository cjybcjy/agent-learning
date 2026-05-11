#!/usr/bin/env bash
# Demo launcher for Market Heatmap MVP
# Usage: ./scripts/demo.sh [web|scheduler|all]

set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_python() {
    if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
        log_error "Python not found. Please install Python >= 3.10"
        exit 1
    fi
    PYTHON=$(command -v python3 || command -v python)
    log_info "Using Python: $PYTHON"
}

check_deps() {
    if ! $PYTHON -c "import heatmap" 2>/dev/null; then
        log_warn "heatmap package not installed in editable mode"
        log_info "Run: pip install -e ."
        exit 1
    fi
}

start_web() {
    log_info "Starting Web Server (API + Frontend) on http://localhost:8000"
    log_info "  - Frontend: http://localhost:8000/"
    log_info "  - API Docs: http://localhost:8000/docs"
    # Kill any existing process on port 8000 to avoid bind conflicts
    lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 0.5
    $PYTHON -m heatmap.web &
    WEB_PID=$!
    log_ok "Web server PID: $WEB_PID"
    echo $WEB_PID > /tmp/heatmap-web.pid
}

start_scheduler() {
    # Prevent duplicate scheduler processes
    if pgrep -f "heatmap.scheduler" >/dev/null 2>&1; then
        log_warn "Scheduler already running, skipping start"
        return
    fi
    log_info "Starting Scheduler (data collection + AI signals)"
    $PYTHON -m heatmap.scheduler &
    SCHEDULER_PID=$!
    log_ok "Scheduler PID: $SCHEDULER_PID"
    echo $SCHEDULER_PID > /tmp/heatmap-scheduler.pid
}

start_scheduler() {
    log_info "Starting Scheduler (data collection + AI signals)"
    $PYTHON -m heatmap.scheduler &
    SCHEDULER_PID=$!
    log_ok "Scheduler PID: $SCHEDULER_PID"
    echo $SCHEDULER_PID > /tmp/heatmap-scheduler.pid
}

stop_all() {
    log_info "Stopping all heatmap processes..."
    if [ -f /tmp/heatmap-web.pid ]; then
        kill $(cat /tmp/heatmap-web.pid) 2>/dev/null && log_ok "Web server stopped" || true
        rm -f /tmp/heatmap-web.pid
    fi
    if [ -f /tmp/heatmap-scheduler.pid ]; then
        kill $(cat /tmp/heatmap-scheduler.pid) 2>/dev/null && log_ok "Scheduler stopped" || true
        rm -f /tmp/heatmap-scheduler.pid
    fi
    # Fallback: kill any remaining processes
    pkill -f "heatmap.web" 2>/dev/null || true
    pkill -f "heatmap.scheduler" 2>/dev/null || true
    log_ok "All stopped"
}

show_status() {
    log_info "Process status:"
    if [ -f /tmp/heatmap-web.pid ] && kill -0 $(cat /tmp/heatmap-web.pid) 2>/dev/null; then
        log_ok "Web server running (PID: $(cat /tmp/heatmap-web.pid))"
    else
        log_warn "Web server not running"
    fi
    if [ -f /tmp/heatmap-scheduler.pid ] && kill -0 $(cat /tmp/heatmap-scheduler.pid) 2>/dev/null; then
        log_ok "Scheduler running (PID: $(cat /tmp/heatmap-scheduler.pid))"
    else
        log_warn "Scheduler not running"
    fi
}

print_help() {
    cat <<EOF
Usage: $(basename "$0") [COMMAND]

Commands:
  web         Start only the web server (API + frontend)
  scheduler   Start only the scheduler (data collection + AI)
  all         Start both web server and scheduler (default)
  stop        Stop all running processes
  status      Show running process status
  help        Show this help message

Examples:
  $(basename "$0") web       # Start web server only
  $(basename "$0") all       # Start full stack
  $(basename "$0") stop      # Stop everything

EOF
}

# Main
COMMAND=${1:-all}

case "$COMMAND" in
    web)
        check_python
        check_deps
        start_web
        log_ok "Web server ready at http://localhost:8000"
        log_info "Press Ctrl+C to stop"
        wait
        ;;
    scheduler)
        check_python
        check_deps
        start_scheduler
        log_ok "Scheduler running"
        log_info "Press Ctrl+C to stop"
        wait
        ;;
    all)
        check_python
        check_deps
        start_web
        sleep 2
        start_scheduler
        log_ok "Full stack running!"
        log_info "  Web:      http://localhost:8000"
        log_info "  API Docs: http://localhost:8000/docs"
        log_info "Press Ctrl+C to stop all"
        wait
        ;;
    stop)
        stop_all
        ;;
    status)
        show_status
        ;;
    help|--help|-h)
        print_help
        ;;
    *)
        log_error "Unknown command: $COMMAND"
        print_help
        exit 1
        ;;
esac
