#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Install Python dependencies if requirements.txt exists
if [ -f "corvus-server/requirements.txt" ]; then
  pip install -r corvus-server/requirements.txt
fi

# Install any root-level requirements
if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt
fi
