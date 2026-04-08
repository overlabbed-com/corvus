#!/usr/bin/env bash
# Corvus Governance Installer
#
# Installs Corvus operational governance hooks and rules for AI coding assistants.
# Detects which tools are installed and configures each one appropriately.
#
# Usage:
#   ./install-corvus-governance.sh [options]
#
# Options:
#   --project-dir DIR   Install project-level rules to DIR (default: current dir)
#   --api-key KEY       Set Corvus API key (or set CORVUS_API_KEY env var)
#   --source-dir DIR    Location of corvus-hooks source (default: script's directory)
#   --dry-run           Show what would be done without doing it
#   --help              Show this help
#
# The installer copies hooks and rules FROM the corvus-hooks source directory
# TO each tool's expected location. Nothing is symlinked.

set -euo pipefail

# Source dir defaults to wherever this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}"
PROJECT_DIR="."
API_KEY=""
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --api-key) API_KEY="$2"; shift 2 ;;
        --source-dir) SOURCE_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) head -20 "$0" | tail -17; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
info() { echo -e "${BLUE}[i]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; }

do_cmd() {
    if $DRY_RUN; then
        info "DRY RUN: $1"
    else
        eval "$2"
        log "$1"
    fi
}

# ---------------------------------------------------------------------------
# Verify prerequisites
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Corvus Governance Installer"
echo "=========================================="
echo ""

# Check source exists
if [[ ! -f "${SOURCE_DIR}/corvus_core.py" ]]; then
    err "corvus_core.py not found at ${SOURCE_DIR}/"
    err "Run this script from the corvus-hooks directory or specify --source-dir"
    exit 1
fi

info "Source: ${SOURCE_DIR}/"

# Check/set API key
if [[ -z "$API_KEY" ]]; then
    API_KEY="${CORVUS_API_KEY:-}"
fi

if [[ -z "$API_KEY" ]]; then
    # Try macOS keychain
    if command -v security &>/dev/null; then
        API_KEY=$(security find-generic-password \
            -s "${CORVUS_KEYCHAIN_SERVICE:-corvus}" \
            -a "${CORVUS_KEYCHAIN_ACCOUNT:-api-key}" \
            -w 2>/dev/null || true)
    fi
fi

if [[ -z "$API_KEY" ]]; then
    warn "No Corvus API key found. Hooks will work but skip governance checks."
    warn "Set via: --api-key KEY, CORVUS_API_KEY env var, or macOS keychain"
else
    log "Corvus API key found"
fi

# ---------------------------------------------------------------------------
# Detect installed tools
# ---------------------------------------------------------------------------
echo ""
info "Detecting installed AI coding assistants..."
echo ""

INSTALLED_TOOLS=()

# Claude Code
if command -v claude &>/dev/null; then
    INSTALLED_TOOLS+=("claude-code")
    log "Found: Claude Code"
fi

# Codex CLI (OpenAI)
if command -v codex &>/dev/null; then
    INSTALLED_TOOLS+=("codex")
    log "Found: Codex CLI"
fi

# Cline (VS Code extension — check for config dir)
if [[ -d "${HOME}/Documents/Cline" ]] || [[ -d "${HOME}/.cline" ]]; then
    INSTALLED_TOOLS+=("cline")
    log "Found: Cline"
fi

# Windsurf
if command -v windsurf &>/dev/null || [[ -d "${HOME}/.windsurf" ]]; then
    INSTALLED_TOOLS+=("windsurf")
    log "Found: Windsurf"
fi

# Cursor
if command -v cursor &>/dev/null || [[ -d "${HOME}/.cursor" ]]; then
    INSTALLED_TOOLS+=("cursor")
    log "Found: Cursor"
fi

# Continue
if [[ -d "${HOME}/.continue" ]]; then
    INSTALLED_TOOLS+=("continue")
    log "Found: Continue"
fi

# Aider
if command -v aider &>/dev/null; then
    INSTALLED_TOOLS+=("aider")
    log "Found: Aider"
fi

# GitHub Copilot (check for VS Code extension)
if [[ -d "${HOME}/.vscode/extensions" ]] && ls "${HOME}/.vscode/extensions/" | grep -q "github.copilot" 2>/dev/null; then
    INSTALLED_TOOLS+=("copilot")
    log "Found: GitHub Copilot"
fi

# Augment
if [[ -d "${HOME}/.augment" ]]; then
    INSTALLED_TOOLS+=("augment")
    log "Found: Augment"
fi

# Amazon Q
if command -v q &>/dev/null || [[ -d "${HOME}/.amazon-q" ]]; then
    INSTALLED_TOOLS+=("amazon-q")
    log "Found: Amazon Q"
fi

if [[ ${#INSTALLED_TOOLS[@]} -eq 0 ]]; then
    warn "No AI coding assistants detected. Installing project-level rules only."
fi

echo ""

# ---------------------------------------------------------------------------
# Claude Code — full hook deployment
# ---------------------------------------------------------------------------
if [[ " ${INSTALLED_TOOLS[*]} " =~ " claude-code " ]]; then
    info "Installing Claude Code hooks and rules..."
    CC_HOOKS_DIR="${HOME}/.claude/hooks"
    CC_RULES_DIR="${HOME}/.claude/rules"
    CC_SETTINGS="${HOME}/.claude/settings.json"

    # Copy hook scripts
    do_cmd "Claude Code: hooks → ${CC_HOOKS_DIR}/" \
        "mkdir -p '${CC_HOOKS_DIR}' && cp '${SOURCE_DIR}/corvus_core.py' '${SOURCE_DIR}/corvus-governance.py' '${SOURCE_DIR}/corvus-event-emit.py' '${SOURCE_DIR}/corvus-lifecycle.py' '${CC_HOOKS_DIR}/'"

    # Copy adapters (used by Codex/Cline too, but CC hooks dir is the standard location)
    do_cmd "Claude Code: adapters → ${CC_HOOKS_DIR}/adapters/" \
        "mkdir -p '${CC_HOOKS_DIR}/adapters' && cp '${SOURCE_DIR}/adapters/'*.py '${CC_HOOKS_DIR}/adapters/'"

    # Copy governance rules
    if [[ -d "${SOURCE_DIR}/claude-code/rules" ]]; then
        do_cmd "Claude Code: governance rules → ${CC_RULES_DIR}/" \
            "mkdir -p '${CC_RULES_DIR}/agents' '${CC_RULES_DIR}/tasks' && cp '${SOURCE_DIR}/claude-code/rules/governance.md' '${CC_RULES_DIR}/' && cp '${SOURCE_DIR}/claude-code/rules/agents/'*.md '${CC_RULES_DIR}/agents/' && cp '${SOURCE_DIR}/claude-code/rules/tasks/'*.md '${CC_RULES_DIR}/tasks/'"
    fi

    # Merge hooks config into settings.json
    if [[ -f "${SOURCE_DIR}/claude-code/hooks.json" ]]; then
        if [[ -f "$CC_SETTINGS" ]]; then
            # Check if hooks are already configured
            if python3 -c "import json; d=json.load(open('${CC_SETTINGS}')); exit(0 if 'hooks' in d and 'PreToolUse' in d['hooks'] else 1)" 2>/dev/null; then
                info "Claude Code: hooks already configured in ${CC_SETTINGS}"
            else
                do_cmd "Claude Code: merge hooks config into ${CC_SETTINGS}" \
                    "python3 -c \"
import json
with open('${CC_SETTINGS}') as f: settings = json.load(f)
with open('${SOURCE_DIR}/claude-code/hooks.json') as f: hooks = json.load(f)
hooks.pop('\\\$comment', None)
settings['hooks'] = hooks
with open('${CC_SETTINGS}', 'w') as f: json.dump(settings, f, indent=2)
\""
            fi
        else
            do_cmd "Claude Code: create ${CC_SETTINGS} with hooks config" \
                "mkdir -p '${HOME}/.claude' && python3 -c \"
import json
with open('${SOURCE_DIR}/claude-code/hooks.json') as f: hooks = json.load(f)
hooks.pop('\\\$comment', None)
with open('${CC_SETTINGS}', 'w') as f: json.dump({'hooks': hooks}, f, indent=2)
\""
        fi
    fi

    echo ""
fi

# ---------------------------------------------------------------------------
# Codex CLI
# ---------------------------------------------------------------------------
if [[ " ${INSTALLED_TOOLS[*]} " =~ " codex " ]]; then
    CODEX_CONFIG="${HOME}/.codex/config.toml"
    if [[ -f "$CODEX_CONFIG" ]] && grep -q "corvus" "$CODEX_CONFIG" 2>/dev/null; then
        info "Codex CLI: Corvus hooks already configured in $CODEX_CONFIG"
    else
        warn "Codex CLI: Add to ${CODEX_CONFIG}:"
        cat <<'TOML'

  [hooks.PreToolUse]
  matcher = "shell|Bash"
  command = "python3 ~/.claude/hooks/adapters/codex_hooks.py pre-tool"
  timeout = 10

  [hooks.PostToolUse]
  matcher = "shell|Bash"
  command = "python3 ~/.claude/hooks/adapters/codex_hooks.py post-tool"
  timeout = 10

  [hooks.UserPromptSubmit]
  command = "python3 ~/.claude/hooks/adapters/codex_hooks.py user-prompt"
  timeout = 5
TOML
    fi
fi

# ---------------------------------------------------------------------------
# Cline
# ---------------------------------------------------------------------------
if [[ " ${INSTALLED_TOOLS[*]} " =~ " cline " ]]; then
    CLINE_GLOBAL="${HOME}/Documents/Cline/Hooks"
    if [[ -d "$CLINE_GLOBAL" ]] && [[ -f "${CLINE_GLOBAL}/corvus-governance.py" ]]; then
        info "Cline: Global hook already installed"
    else
        do_cmd "Cline: Copy hook to ${CLINE_GLOBAL}/" \
            "mkdir -p '${CLINE_GLOBAL}' && cp '${SOURCE_DIR}/adapters/cline_hooks.py' '${CLINE_GLOBAL}/corvus-governance.py'"
    fi
fi

echo ""

# ---------------------------------------------------------------------------
# Project-level rules (tool-agnostic governance docs)
# ---------------------------------------------------------------------------
info "Installing project-level governance rules to: ${PROJECT_DIR}"
echo ""

RULES_SRC="${SOURCE_DIR}/rules"

# AGENTS.md (Cline, Augment, Codex CLI, Continue, Amazon Q)
if [[ ! -f "${PROJECT_DIR}/AGENTS.md" ]]; then
    do_cmd "AGENTS.md (Cline, Augment, Codex, Continue, Amazon Q)" \
        "cp '${RULES_SRC}/AGENTS.md' '${PROJECT_DIR}/AGENTS.md'"
else
    warn "AGENTS.md already exists in ${PROJECT_DIR} — skipping"
fi

# .cursorrules
if [[ " ${INSTALLED_TOOLS[*]} " =~ " cursor " ]]; then
    if [[ ! -f "${PROJECT_DIR}/.cursorrules" ]]; then
        do_cmd ".cursorrules (Cursor)" \
            "cp '${RULES_SRC}/.cursorrules' '${PROJECT_DIR}/.cursorrules'"
    else
        warn ".cursorrules already exists — skipping"
    fi
fi

# .continuerules
if [[ " ${INSTALLED_TOOLS[*]} " =~ " continue " ]]; then
    if [[ ! -f "${PROJECT_DIR}/.continuerules" ]]; then
        do_cmd ".continuerules (Continue)" \
            "cp '${RULES_SRC}/.continuerules' '${PROJECT_DIR}/.continuerules'"
    else
        warn ".continuerules already exists — skipping"
    fi
fi

# .github/copilot-instructions.md
if [[ " ${INSTALLED_TOOLS[*]} " =~ " copilot " ]]; then
    if [[ ! -f "${PROJECT_DIR}/.github/copilot-instructions.md" ]]; then
        do_cmd ".github/copilot-instructions.md (Copilot)" \
            "mkdir -p '${PROJECT_DIR}/.github' && cp '${RULES_SRC}/copilot-instructions.md' '${PROJECT_DIR}/.github/copilot-instructions.md'"
    else
        warn ".github/copilot-instructions.md already exists — skipping"
    fi
fi

# .augment/rules/corvus-governance.md
if [[ " ${INSTALLED_TOOLS[*]} " =~ " augment " ]]; then
    if [[ ! -f "${PROJECT_DIR}/.augment/rules/corvus-governance.md" ]]; then
        do_cmd ".augment/rules/corvus-governance.md (Augment)" \
            "mkdir -p '${PROJECT_DIR}/.augment/rules' && cp '${RULES_SRC}/augment-corvus-governance.md' '${PROJECT_DIR}/.augment/rules/corvus-governance.md'"
    else
        warn ".augment/rules/corvus-governance.md already exists — skipping"
    fi
fi

# CONVENTIONS.md (Aider)
if [[ " ${INSTALLED_TOOLS[*]} " =~ " aider " ]]; then
    if [[ ! -f "${PROJECT_DIR}/CONVENTIONS.md" ]]; then
        do_cmd "CONVENTIONS.md (Aider)" \
            "cp '${RULES_SRC}/CONVENTIONS.md' '${PROJECT_DIR}/CONVENTIONS.md'"
    else
        warn "CONVENTIONS.md already exists — skipping"
    fi
fi

# .windsurfrules
if [[ " ${INSTALLED_TOOLS[*]} " =~ " windsurf " ]]; then
    if [[ ! -f "${PROJECT_DIR}/.windsurfrules" ]]; then
        do_cmd ".windsurfrules (Windsurf)" \
            "cp '${RULES_SRC}/.cursorrules' '${PROJECT_DIR}/.windsurfrules'"
    else
        warn ".windsurfrules already exists — skipping"
    fi
fi

echo ""

# ---------------------------------------------------------------------------
# Store API key if provided and on macOS
# ---------------------------------------------------------------------------
if [[ -n "$API_KEY" ]] && command -v security &>/dev/null; then
    KC_SVC="${CORVUS_KEYCHAIN_SERVICE:-corvus}"
    KC_ACCT="${CORVUS_KEYCHAIN_ACCOUNT:-api-key}"
    EXISTING=$(security find-generic-password -s "$KC_SVC" -a "$KC_ACCT" -w 2>/dev/null || true)
    if [[ "$EXISTING" != "$API_KEY" ]]; then
        do_cmd "Store API key in macOS keychain (service=${KC_SVC})" \
            "security add-generic-password -s '${KC_SVC}' -a '${KC_ACCT}' -w '${API_KEY}' -U"
    else
        info "API key already in keychain"
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Installation Complete"
echo "=========================================="
echo ""
info "Source:         ${SOURCE_DIR}/"
info "Project rules:  ${PROJECT_DIR}/"
info "Tools detected: ${INSTALLED_TOOLS[*]:-none}"
echo ""

if [[ " ${INSTALLED_TOOLS[*]} " =~ " claude-code " ]]; then
    info "Claude Code:"
    info "  Hooks:  ~/.claude/hooks/ (corvus_core + 3 hook scripts + adapters)"
    info "  Rules:  ~/.claude/rules/ (governance + agents + ops-protocol)"
    info "  Config: ~/.claude/settings.json (hooks section)"
fi

echo ""
info "All tools share the same Corvus governance:"
info "  - Pre-action conflict check (MANDATORY)"
info "  - Event emission after state changes (MANDATORY)"
info "  - Incident/Change/Design workflow enforcement"
info "  - GitOps policy (no SSH config edits)"
echo ""

if [[ " ${INSTALLED_TOOLS[*]} " =~ " codex " ]]; then
    warn "ACTION REQUIRED: Manually add Codex CLI hooks to ~/.codex/config.toml"
    warn "  (see output above for the TOML snippet)"
fi

echo ""
log "Done. Corvus governance is now enforced across your AI coding tools."
