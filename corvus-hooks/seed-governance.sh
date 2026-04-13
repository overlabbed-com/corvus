#!/usr/bin/env bash
# seed-governance.sh — Ingest Claude Code governance rules into Corvus
#
# Reads all .md files from ~/.claude/rules/ and ingests each as a
# source_type=governance knowledge entry in Corvus. Idempotent — updates
# existing entries matched by title, creates new ones if absent.
#
# Usage:
#   ./seed-governance.sh [options]
#
# Options:
#   --rules-dir DIR     Path to rules directory (default: ~/.claude/rules)
#   --corvus-url URL    Corvus API base URL (default: https://corvus.example.com)
#   --api-key KEY       Corvus API key (or set CORVUS_API_KEY env var)
#   --dry-run           Show what would be done without making API calls
#   --help              Show this help

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
RULES_DIR="${HOME}/Documents/Claude/.claude/rules"
CORVUS_URL="https://corvus.example.com"
API_KEY=""
DRY_RUN=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --rules-dir)  RULES_DIR="$2"; shift 2 ;;
        --corvus-url) CORVUS_URL="$2"; shift 2 ;;
        --api-key)    API_KEY="$2"; shift 2 ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --help)       head -17 "$0" | tail -15; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Colored output
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1" >&2; }

# ---------------------------------------------------------------------------
# Resolve API key
# ---------------------------------------------------------------------------
if [[ -z "$API_KEY" ]]; then
    API_KEY="${CORVUS_API_KEY:-}"
fi

if [[ -z "$API_KEY" ]] && command -v security &>/dev/null; then
    API_KEY=$(security find-generic-password \
        -s "${CORVUS_KEYCHAIN_SERVICE:-corvus-example}" \
        -a "${CORVUS_KEYCHAIN_ACCOUNT:-corvus-api-key}" \
        -w 2>/dev/null || true)
fi

if [[ -z "$API_KEY" ]]; then
    err "No Corvus API key found."
    err "Provide via: --api-key KEY, CORVUS_API_KEY env var, or macOS keychain"
    exit 1
fi

# ---------------------------------------------------------------------------
# Validate rules directory
# ---------------------------------------------------------------------------
if [[ ! -d "$RULES_DIR" ]]; then
    err "Rules directory not found: ${RULES_DIR}"
    exit 1
fi

echo ""
echo "=========================================="
echo "  Corvus Governance Seed"
echo "=========================================="
echo ""
log "Rules dir:  ${RULES_DIR}"
log "Corvus URL: ${CORVUS_URL}"
if $DRY_RUN; then
    warn "DRY RUN — no API calls will be made"
fi
echo ""

# ---------------------------------------------------------------------------
# Tag + order mapping (pure bash — no external dependencies)
# ---------------------------------------------------------------------------
map_tags_and_order() {
    # $1 = relative path (e.g. "agents/architect.md", "governance.md")
    local relpath="$1"

    case "$relpath" in
        agents/*.md)
            TAGS='["governance","agent-role"]'
            ORDER=20
            ;;
        tasks/*.md)
            TAGS='["governance","ops-task"]'
            ORDER=40
            ;;
        governance.md)
            TAGS='["governance","risk-framework"]'
            ORDER=10
            ;;
        dev-governance.md)
            TAGS='["governance","dev-governance"]'
            ORDER=15
            ;;
        coding-standards.md)
            TAGS='["governance","coding-standards"]'
            ORDER=30
            ;;
        file-hygiene.md)
            TAGS='["governance","file-hygiene"]'
            ORDER=35
            ;;
        web-search-routing.md)
            TAGS='["governance","web-search-routing"]'
            ORDER=50
            ;;
        local-model-tools.md)
            TAGS='["governance","local-model-tools"]'
            ORDER=50
            ;;
        *)
            TAGS='["governance"]'
            ORDER=50
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Build title from relative path
# ---------------------------------------------------------------------------
make_title() {
    # $1 = relative path (e.g. "agents/architect.md")
    # Output: "agents-architect" (no .md, / replaced with -)
    local t="$1"
    t="${t%.md}"          # strip .md extension
    echo "${t//\//-}"     # replace / with -
}

# ---------------------------------------------------------------------------
# JSON construction via python3 (safe — no shell interpolation into code)
# ---------------------------------------------------------------------------
build_post_json() {
    # Reads title, content, tags from environment; writes JSON to stdout
    python3 -c '
import json, os, sys
obj = {
    "title": os.environ["_SEED_TITLE"],
    "content": os.environ["_SEED_CONTENT"],
    "source_type": "governance",
    "tags": json.loads(os.environ["_SEED_TAGS"]),
}
json.dump(obj, sys.stdout)
'
}

build_patch_json() {
    # Reads title, content, tags, order from environment; writes JSON to stdout
    python3 -c '
import json, os, sys
obj = {
    "title": os.environ["_SEED_TITLE"],
    "content": os.environ["_SEED_CONTENT"],
    "tags": json.loads(os.environ["_SEED_TAGS"]),
    "governance_order": int(os.environ["_SEED_ORDER"]),
}
json.dump(obj, sys.stdout)
'
}

# ---------------------------------------------------------------------------
# Fetch existing governance entries (for idempotent matching)
# ---------------------------------------------------------------------------
fetch_existing() {
    if $DRY_RUN; then
        echo '[]'
        return
    fi

    local response
    response=$(curl -sfS \
        -H "Authorization: Bearer ${API_KEY}" \
        "${CORVUS_URL}/ops/knowledge?source_type=governance&limit=200" 2>&1) || {
        err "Failed to fetch existing governance entries: ${response}"
        exit 1
    }
    echo "$response"
}

# ---------------------------------------------------------------------------
# Look up entry ID by title in the cached existing entries JSON
# ---------------------------------------------------------------------------
find_entry_id() {
    # $1 = title to match, $2 = existing entries JSON
    local title="$1"
    local existing_json="$2"
    # Pass title via env to avoid injection into python code
    _SEED_LOOKUP_TITLE="$title" python3 -c '
import json, os, sys
title = os.environ["_SEED_LOOKUP_TITLE"]
entries = json.loads(sys.stdin.read())
for e in entries:
    if e.get("title") == title:
        print(e["id"])
        sys.exit(0)
sys.exit(1)
' <<< "$existing_json" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
log "Fetching existing governance entries..."
EXISTING_JSON=$(fetch_existing)

CREATED=0
UPDATED=0
SKIPPED=0
ERRORS=0

# Find all .md files (excluding backups and hidden files)
while IFS= read -r filepath; do
    # Compute relative path from rules dir
    relpath="${filepath#"${RULES_DIR}/"}"

    # Skip backup files
    case "$relpath" in
        *.backup|*.bak|*.orig|.*)
            warn "Skipping: ${relpath} (backup/hidden file)"
            SKIPPED=$((SKIPPED + 1))
            continue
            ;;
    esac

    title=$(make_title "$relpath")
    map_tags_and_order "$relpath"
    content=$(cat "$filepath")

    if $DRY_RUN; then
        log "Would seed: ${title}  tags=${TAGS}  order=${ORDER}  (${#content} bytes)"
        continue
    fi

    # Export values for python3 JSON builders (avoids shell interpolation risk)
    export _SEED_TITLE="$title"
    export _SEED_CONTENT="$content"
    export _SEED_TAGS="$TAGS"
    export _SEED_ORDER="$ORDER"

    # Check if entry already exists
    entry_id=$(find_entry_id "$title" "$EXISTING_JSON" || true)

    if [[ -n "$entry_id" ]]; then
        # PATCH existing entry
        patch_json=$(build_patch_json)
        http_code=$(curl -s -o /dev/null -w '%{http_code}' \
            -X PATCH \
            -H "Authorization: Bearer ${API_KEY}" \
            -H "Content-Type: application/json" \
            --data-raw "$patch_json" \
            "${CORVUS_URL}/ops/knowledge/${entry_id}")

        if [[ "$http_code" =~ ^2 ]]; then
            log "Updated: ${title} (${entry_id})"
            UPDATED=$((UPDATED + 1))
        else
            err "Failed to update ${title} (${entry_id}): HTTP ${http_code}"
            ERRORS=$((ERRORS + 1))
        fi
    else
        # POST new entry
        post_json=$(build_post_json)
        response=$(curl -s -w '\n%{http_code}' \
            -X POST \
            -H "Authorization: Bearer ${API_KEY}" \
            -H "Content-Type: application/json" \
            --data-raw "$post_json" \
            "${CORVUS_URL}/ops/knowledge")

        http_code=$(echo "$response" | tail -1)
        body=$(echo "$response" | head -n -1)

        if [[ "$http_code" == "201" ]]; then
            new_id=$(echo "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id","?"))')
            log "Created: ${title} (${new_id})"
            CREATED=$((CREATED + 1))

            # Set governance_order via PATCH (POST model doesn't include it)
            patch_order_json=$(python3 -c '
import json, os, sys
json.dump({"governance_order": int(os.environ["_SEED_ORDER"])}, sys.stdout)
')
            curl -s -o /dev/null \
                -X PATCH \
                -H "Authorization: Bearer ${API_KEY}" \
                -H "Content-Type: application/json" \
                --data-raw "$patch_order_json" \
                "${CORVUS_URL}/ops/knowledge/${new_id}" || {
                    warn "Failed to set governance_order on ${new_id}"
                }
        else
            err "Failed to create ${title}: HTTP ${http_code}"
            err "Response: ${body}"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # Clean up exported vars
    unset _SEED_TITLE _SEED_CONTENT _SEED_TAGS _SEED_ORDER

done < <(find "$RULES_DIR" -name "*.md" -type f | sort)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Seed Complete"
echo "=========================================="
echo ""

if $DRY_RUN; then
    log "Dry run — no changes made"
else
    log "Created: ${CREATED}"
    log "Updated: ${UPDATED}"
    if [[ $SKIPPED -gt 0 ]]; then
        warn "Skipped: ${SKIPPED}"
    fi
    if [[ $ERRORS -gt 0 ]]; then
        err "Errors:  ${ERRORS}"
        exit 1
    fi
fi
