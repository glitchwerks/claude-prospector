#!/usr/bin/env bash
# Install / restore the claude-prospector plugin for the self-audit Stop-hook spike (#129).
#
# This branch (self-audit-spike-129) ships:
#   1. hooks/hooks.json with session-audit-prompt.py registered as a Stop hook
#   2. .claude-plugin/marketplace.json declaring a local marketplace
#      "claude-prospector-spike" that points at this worktree as its sole plugin
#
# Persistent install is achieved by adding the worktree as a marketplace, then
# installing the plugin from that marketplace. The release marketplace
# (glitchwerks) stays registered; we just temporarily install the spike copy
# instead of the released one.
#
# Subcommands:
#   install  - Add this worktree as the 'claude-prospector-spike' marketplace,
#              uninstall any currently-installed claude-prospector, and install
#              the spike copy.
#   status   - Show the active claude-prospector install and the configured
#              marketplaces so you can verify which copy is live.
#   restore  - Uninstall the spike copy, remove the 'claude-prospector-spike'
#              marketplace, and reinstall claude-prospector from the
#              'glitchwerks' marketplace. Run when the spike concludes.
#
# The worktree root is resolved relative to this script's location, so the
# script works regardless of cwd.
#
# Issue: https://github.com/glitchwerks/claude-prospector/issues/129

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_NAME="claude-prospector"
SPIKE_MARKETPLACE="claude-prospector-spike"
RELEASE_MARKETPLACE="glitchwerks"

# ANSI color helpers (skip when stdout isn't a tty).
if [ -t 1 ]; then
    C_STEP=$'\033[36m'   # cyan
    C_CMD=$'\033[90m'    # dark gray
    C_WARN=$'\033[33m'   # yellow
    C_OFF=$'\033[0m'
else
    C_STEP=''; C_CMD=''; C_WARN=''; C_OFF=''
fi

step()  { printf '%s>> %s%s\n' "$C_STEP" "$*" "$C_OFF"; }
trace() { printf '%s   %s%s\n' "$C_CMD" "$*" "$C_OFF"; }
warn()  { printf '%s   %s%s\n' "$C_WARN" "$*" "$C_OFF"; }

run_claude() {
    trace "claude $*"
    claude "$@"
}

usage() {
    printf 'Usage: %s {install|status|restore}\n' "$0" >&2
    exit 64
}

[ $# -eq 1 ] || usage
ACTION="$1"

case "$ACTION" in
    install)
        step "Spike worktree: $WORKTREE_ROOT"

        step "Adding spike marketplace '$SPIKE_MARKETPLACE' (idempotent)..."
        if ! run_claude plugin marketplace add "$WORKTREE_ROOT"; then
            warn "(marketplace add failed; may already be registered, continuing)"
        fi

        step "Uninstalling any current $PLUGIN_NAME install..."
        if ! run_claude plugin uninstall "$PLUGIN_NAME"; then
            warn "(no existing install to remove, continuing)"
        fi

        step "Installing $PLUGIN_NAME from $SPIKE_MARKETPLACE..."
        run_claude plugin install "${PLUGIN_NAME}@${SPIKE_MARKETPLACE}"

        step "Done. Verify with: ./scripts/spike-install.sh status"
        step "Open a new Claude Code session; the Stop hook fires at session end."
        ;;

    status)
        step "Configured marketplaces:"
        run_claude plugin marketplace list

        step "Active $PLUGIN_NAME install:"
        claude plugin list | grep -E "(^|\s)$PLUGIN_NAME(\s|$)" -A 2 || {
            warn "$PLUGIN_NAME not found in 'claude plugin list' output."
            exit 1
        }
        ;;

    restore)
        step "Uninstalling spike copy of $PLUGIN_NAME..."
        if ! run_claude plugin uninstall "$PLUGIN_NAME"; then
            warn "(no existing install to remove, continuing)"
        fi

        step "Removing spike marketplace '$SPIKE_MARKETPLACE'..."
        if ! run_claude plugin marketplace remove "$SPIKE_MARKETPLACE"; then
            warn "(marketplace not present, continuing)"
        fi

        step "Reinstalling release $PLUGIN_NAME from '$RELEASE_MARKETPLACE'..."
        run_claude plugin install "${PLUGIN_NAME}@${RELEASE_MARKETPLACE}"

        step "Done. Release copy active; spike hook is no longer registered."
        ;;

    *)
        usage
        ;;
esac
