#!/usr/bin/env bash
# Corvus Governance Installer
#
# Installs Corvus operational governance hooks and rules for AI coding assistants.
# Detects which tools are installed and configures each one appropriately.
#
# Usage:
#   ./install-corvus-governance.sh [--project-dir /path/to/project] [--api-key KEY]
#
# Options:
#   --project-dir DIR   Install project-level rules to DIR (default: current dir)
#   --api-key KEY       Set Corvus API key (or set CORVUS_API_KEY env var)
#   --hooks-dir DIR     Location of hooks source (default: ~/.claude/hooks)
#   --dry-run           Show what would be done without doing it
#   --help              Show this help

set -euo pipefail

HOOKS_DIR="${HOME}/.claude/hooks"
PROJECT_DIR="."
API_KEY=""
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --api-key) API_KEY="$2"; shift 2 ;;
        --hooks-dir) HOOKS_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) head -17 "$0" | tail -14; exit 0 ;;
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

# Check hooks source exists
if [[ ! -f "${HOOKS_DIR}/corvus_core.py" ]]; then
    err "corvus_core.py not found at ${HOOKS_DIR}/"
    err "Clone the hooks directory first or specify --hooks-dir"
    exit 1
fi

# Check/set API key
if [[ -z "$API_KEY" ]]; then
    API_KEY="${CORVUS_API_KEY:-}"
fi

if [[ -z "$API_KEY" ]]; then
    # Try macOS keychain
    if command -v security &>/dev/null; then
        API_KEY=$(security find-generic-password -s "corvus.themillertribe-int.org" -a "claude-code-api-key" -w 2>/dev/null || true)
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
# Install hooks for tools with hook systems
# ---------------------------------------------------------------------------

# Claude Code (hooks in settings.json — already configured if using this repo)
if [[ " ${INSTALLED_TOOLS[*]} " =~ " claude-code " ]]; then
    info "Claude Code: hooks configured in ~/.claude/settings.json"
    info "  PreToolUse  -> corvus-governance.py (conflict check)"
    info "  PostToolUse -> corvus-event-emit.py (auto event emission)"
    info "  UserPromptSubmit -> corvus-lifecycle.py (intent classification)"
fi

# Codex CLI
if [[ " ${INSTALLED_TOOLS[*]} " =~ " codex " ]]; then
    CODEX_CONFIG="${HOME}/.codex/config.toml"
    if [[ -f "$CODEX_CONFIG" ]] && grep -q "corvus" "$CODEX_CONFIG" 2>/dev/null; then
        info "Codex CLI: Corvus hooks already configured in $CODEX_CONFIG"
    else
        info "Codex CLI: Add to ${CODEX_CONFIG}:"
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

# Cline
if [[ " ${INSTALLED_TOOLS[*]} " =~ " cline " ]]; then
    CLINE_GLOBAL="${HOME}/Documents/Cline/Hooks"
    if [[ -d "$CLINE_GLOBAL" ]] && [[ -L "${CLINE_GLOBAL}/corvus-governance.py" ]]; then
        info "Cline: Global hook already linked"
    else
        do_cmd "Cline: Link global hook" \
            "mkdir -p '${CLINE_GLOBAL}' && ln -sf '${HOOKS_DIR}/adapters/cline_hooks.py' '${CLINE_GLOBAL}/corvus-governance.py'"
    fi
fi

echo ""

# ---------------------------------------------------------------------------
# Install project-level rules
# ---------------------------------------------------------------------------

info "Installing project-level governance rules to: ${PROJECT_DIR}"
echo ""

RULES_SRC="${HOOKS_DIR}/rules"

# AGENTS.md (Cline, Augment, Codex CLI, Continue)
if [[ ! -f "${PROJECT_DIR}/AGENTS.md" ]]; then
    do_cmd "AGENTS.md (Cline, Augment, Codex, Continue)" \
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
    EXISTING=$(security find-generic-password -s "corvus.themillertribe-int.org" -a "claude-code-api-key" -w 2>/dev/null || true)
    if [[ "$EXISTING" != "$API_KEY" ]]; then
        do_cmd "Store API key in macOS keychain" \
            "security add-generic-password -s 'corvus.themillertribe-int.org' -a 'claude-code-api-key' -w '${API_KEY}' -U"
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
info "Hooks source: ${HOOKS_DIR}/"
info "Project rules: ${PROJECT_DIR}/"
info "Tools configured: ${INSTALLED_TOOLS[*]:-none detected}"
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
