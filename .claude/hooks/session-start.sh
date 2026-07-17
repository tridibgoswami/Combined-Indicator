#!/bin/bash
set -euo pipefail

# Only run in remote Claude Code environment
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Set git identity so commits are verified and stop-hook doesn't fire
git config user.email "noreply@anthropic.com"
git config user.name "Claude"

# Install Python dependencies
pip install --quiet -r requirements.txt
pip install --quiet -e ".[dev]" 2>/dev/null || true
