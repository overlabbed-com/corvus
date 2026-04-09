#!/usr/bin/env bash
# sync-governance.sh — Pull governance rules from Corvus and write to ~/.claude/rules/
#
# Pulls all source_type=governance entries from Corvus, writes each as a .md
# file to the target rules directory. Atomic: writes to temp dir first, then
# rsyncs into place. Fail-open: if Corvus is unreachable, exits 0 with a warning.
#
# Usage:
#   ./sync-governance.sh [options]
#
# Options:
#   --target-dir DIR    Path to rules directory (default: ~/.claude/rules)
#   --corvus-url URL    Corvus API base URL (default: https://corvus.themillertribe-int.org)
#   --api-key KEY       Corvus API key (or set CORVUS_API_KEY env var)
#   --dry-run           Show what would be done without writing files
#   --help              Show this help

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TARGET_DIR="${HOME}/.claude/rules"
CORVUS_URL="https://corvus.themillertribe-int.org"
API_KEY=""
DRY_RUN=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-dir)  TARGET_DIR="$2"; shift 2 ;;
        --corvus-url)  CORVUS_URL="$2"; shift 2 ;;
        --api-key)     API_KEY="$2"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --help)        head -17 "$0" | tail -15; exit 0 ;;
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
warn() { echo -e "${YELLOW}[!]${NC} $1" >&2; }
err()  { echo -e "${RED}[x]${NC} $1" >&2; }

# ---------------------------------------------------------------------------
# Resolve API key (priority: flag > env > macOS keychain)
# ---------------------------------------------------------------------------
if [[ -z "$API_KEY" ]]; then
    API_KEY="${CORVUS_API_KEY:-}"
fi

if [[ -z "$API_KEY" ]] && command -v security &>/dev/null; then
    API_KEY=$(security find-generic-password \
        -s "${CORVUS_KEYCHAIN_SERVICE:-corvus.themillertribe-int.org}" \
        -a "${CORVUS_KEYCHAIN_ACCOUNT:-corvus-api-key}" \
        -w 2>/dev/null || true)
fi

if [[ -z "$API_KEY" ]]; then
    err "No Corvus API key found."
    err "Provide via: --api-key KEY, CORVUS_API_KEY env var, or macOS keychain"
    exit 1
fi

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_ENTRY_SIZE=51200    # 50KB per entry
MAX_TOTAL_SIZE=512000   # 500KB total governance
METADATA_FILE=".governance-sync-metadata"

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Corvus Governance Sync"
echo "=========================================="
echo ""
log "Target dir: ${TARGET_DIR}"
log "Corvus URL: ${CORVUS_URL}"
if $DRY_RUN; then
    warn "DRY RUN — no files will be written"
fi
echo ""

# ---------------------------------------------------------------------------
# Fetch governance entries from Corvus (fail-open)
# ---------------------------------------------------------------------------
log "Fetching governance entries from Corvus..."

FETCH_RESPONSE=""
FETCH_HTTP_CODE=""
FETCH_RESULT=$(curl -s -w '\n%{http_code}' \
    --connect-timeout 10 \
    --max-time 30 \
    -H "Authorization: Bearer ${API_KEY}" \
    "${CORVUS_URL}/ops/knowledge?source_type=governance&limit=200" 2>&1) || {
    warn "Corvus unreachable (connection failed). Using cached rules."
    exit 0
}

# Split response body and HTTP status code
FETCH_HTTP_CODE=$(echo "$FETCH_RESULT" | tail -1)
FETCH_RESPONSE=$(echo "$FETCH_RESULT" | head -n -1)

# Fail-open: non-2xx response
if ! [[ "$FETCH_HTTP_CODE" =~ ^2 ]]; then
    warn "Corvus returned HTTP ${FETCH_HTTP_CODE}. Using cached rules."
    exit 0
fi

# ---------------------------------------------------------------------------
# Validate and process entries via python3
# (all JSON parsing and file writing logic in one python3 invocation to avoid
#  shell string interpolation of content)
# ---------------------------------------------------------------------------

# Pass API response via stdin, config via env vars
export _SYNC_TARGET_DIR="$TARGET_DIR"
export _SYNC_DRY_RUN="$DRY_RUN"
export _SYNC_MAX_ENTRY_SIZE="$MAX_ENTRY_SIZE"
export _SYNC_MAX_TOTAL_SIZE="$MAX_TOTAL_SIZE"
export _SYNC_METADATA_FILE="$METADATA_FILE"
export _SYNC_CORVUS_URL="$CORVUS_URL"

SYNC_OUTPUT=$(printf '%s\n' "$FETCH_RESPONSE" | python3 << 'PYTHON_EOF'
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Read config from env
target_dir = Path(os.environ["_SYNC_TARGET_DIR"]).expanduser()
dry_run = os.environ["_SYNC_DRY_RUN"] == "true"
max_entry_size = int(os.environ["_SYNC_MAX_ENTRY_SIZE"])
max_total_size = int(os.environ["_SYNC_MAX_TOTAL_SIZE"])
metadata_filename = os.environ["_SYNC_METADATA_FILE"]

# Parse API response from stdin
raw = sys.stdin.read()
try:
    entries = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"WARN:Invalid JSON from Corvus: {e}", file=sys.stderr)
    sys.exit(0)

if not isinstance(entries, list):
    print("WARN:Corvus returned non-list response. Using cached rules.", file=sys.stderr)
    sys.exit(0)

# Fail-open on empty
if len(entries) == 0:
    print("WARN:Corvus returned 0 governance entries. Using cached rules.", file=sys.stderr)
    sys.exit(0)


def title_to_order(title: str) -> int:
    """Derive governance_order from title when API doesn't provide it.

    Mirrors the seed script's map_tags_and_order logic.
    """
    if title.startswith("agents-"):
        return 20
    if title.startswith("tasks-"):
        return 40
    mapping = {
        "governance": 10,
        "dev-governance": 15,
        "coding-standards": 30,
        "file-hygiene": 35,
        "web-search-routing": 50,
        "local-model-tools": 50,
    }
    return mapping.get(title, 50)


def title_to_filepath(title: str) -> str:
    """Convert Corvus title to relative file path.

    Reverses seed script convention:
      agents-architect -> agents/architect.md
      tasks-ops-protocol -> tasks/ops-protocol.md
      governance -> governance.md
    """
    # Check for subdirectory prefixes
    for prefix in ("agents-", "tasks-"):
        if title.startswith(prefix):
            dirname = prefix.rstrip("-")
            basename = title[len(prefix):]
            return f"{dirname}/{basename}.md"
    return f"{title}.md"


# ---- Validate and sort entries ----
valid_entries = []
total_size = 0
skipped = 0

for entry in entries:
    title = (entry.get("title") or "").strip()
    content = (entry.get("content") or "").strip()

    # Skip entries with empty title or content
    if not title or not content:
        print(f"SKIP:Empty title or content: {title!r}", file=sys.stderr)
        skipped += 1
        continue

    content_bytes = len(content.encode("utf-8"))

    # Skip oversized entries
    if content_bytes > max_entry_size:
        print(f"SKIP:{title} exceeds {max_entry_size}B ({content_bytes}B)", file=sys.stderr)
        skipped += 1
        continue

    # Check total size budget
    if total_size + content_bytes > max_total_size:
        print(
            f"STOP:Total governance size would exceed {max_total_size}B. "
            f"Stopping at {len(valid_entries)} entries.",
            file=sys.stderr,
        )
        break

    total_size += content_bytes

    # Extract governance_order (API may or may not include it)
    order = entry.get("governance_order")
    if order is None:
        order = title_to_order(title)

    valid_entries.append({
        "title": title,
        "content": content,
        "governance_order": order,
        "filepath": title_to_filepath(title),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    })

# Sort by governance_order ascending, then title
valid_entries.sort(key=lambda e: (e["governance_order"], e["title"]))

if len(valid_entries) == 0:
    print("WARN:No valid governance entries after filtering. Using cached rules.", file=sys.stderr)
    sys.exit(0)

# ---- Dry-run: just report ----
if dry_run:
    for e in valid_entries:
        size = len(e["content"].encode("utf-8"))
        print(f"DRY:{e['filepath']} (order={e['governance_order']}, {size}B, sha256={e['sha256'][:12]}...)")
    print(f"SUMMARY:entries={len(valid_entries)},skipped={skipped},total_bytes={total_size}")
    sys.exit(0)

# ---- Atomic write to temp directory ----
tmp_dir = Path(tempfile.mkdtemp(prefix="corvus-governance-"))
try:
    for e in valid_entries:
        fpath = tmp_dir / e["filepath"]
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(e["content"], encoding="utf-8")

    # Write metadata file
    metadata = {
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corvus_url": os.environ.get("_SYNC_CORVUS_URL", ""),
        "entry_count": len(valid_entries),
        "total_bytes": total_size,
        "entries": {
            e["filepath"]: {
                "title": e["title"],
                "governance_order": e["governance_order"],
                "sha256": e["sha256"],
            }
            for e in valid_entries
        },
    }
    (tmp_dir / metadata_filename).write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    # Print temp dir path for shell to rsync from
    print(f"TMPDIR:{tmp_dir}")
    print(f"SUMMARY:entries={len(valid_entries)},skipped={skipped},total_bytes={total_size}")

except Exception as exc:
    # Clean up temp dir on failure
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"ERROR:{exc}", file=sys.stderr)
    sys.exit(1)
PYTHON_EOF
) || {
    # Python exited non-zero — fail-open (warnings already printed to stderr)
    exit 0
}

# Clean up exported env vars
unset _SYNC_TARGET_DIR _SYNC_DRY_RUN _SYNC_MAX_ENTRY_SIZE _SYNC_MAX_TOTAL_SIZE
unset _SYNC_METADATA_FILE _SYNC_CORVUS_URL

# ---------------------------------------------------------------------------
# Parse python output
# ---------------------------------------------------------------------------
TMPDIR=""
SUMMARY=""

while IFS= read -r line; do
    case "$line" in
        DRY:*)
            log "Would write: ${line#DRY:}"
            ;;
        TMPDIR:*)
            TMPDIR="${line#TMPDIR:}"
            ;;
        SUMMARY:*)
            SUMMARY="${line#SUMMARY:}"
            ;;
    esac
done <<< "$SYNC_OUTPUT"

# Dry-run: nothing more to do
if $DRY_RUN; then
    echo ""
    log "Dry run complete — no files written"
    if [[ -n "$SUMMARY" ]]; then
        # Parse summary
        ENTRIES=$(echo "$SUMMARY" | python3 -c "import sys; parts=dict(p.split('=') for p in sys.stdin.read().strip().split(',')); print(parts.get('entries','?'))")
        SKIP=$(echo "$SUMMARY" | python3 -c "import sys; parts=dict(p.split('=') for p in sys.stdin.read().strip().split(',')); print(parts.get('skipped','?'))")
        log "Would sync: ${ENTRIES} entries (${SKIP} skipped)"
    fi
    exit 0
fi

# Validate temp dir exists
if [[ -z "$TMPDIR" || ! -d "$TMPDIR" ]]; then
    warn "No temp directory produced. Using cached rules."
    exit 0
fi

# ---------------------------------------------------------------------------
# Ensure target directory exists
# ---------------------------------------------------------------------------
mkdir -p "$TARGET_DIR"

# ---------------------------------------------------------------------------
# Rsync: ADD/UPDATE synced files, do NOT delete non-Corvus files
# ---------------------------------------------------------------------------
# --remove-source-files moves synced files from tmp to target without deleting
# existing files in target that aren't in the tmp dir.
log "Syncing governance files to ${TARGET_DIR}..."
rsync -a --remove-source-files "${TMPDIR}/" "${TARGET_DIR}/"

# ---------------------------------------------------------------------------
# Cleanup temp directory
# ---------------------------------------------------------------------------
rm -rf "$TMPDIR"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Sync Complete"
echo "=========================================="
echo ""

if [[ -n "$SUMMARY" ]]; then
    ENTRIES=$(echo "$SUMMARY" | python3 -c "import sys; parts=dict(p.split('=') for p in sys.stdin.read().strip().split(',')); print(parts.get('entries','?'))")
    SKIP=$(echo "$SUMMARY" | python3 -c "import sys; parts=dict(p.split('=') for p in sys.stdin.read().strip().split(',')); print(parts.get('skipped','?'))")
    BYTES=$(echo "$SUMMARY" | python3 -c "import sys; parts=dict(p.split('=') for p in sys.stdin.read().strip().split(',')); print(parts.get('total_bytes','?'))")
    log "Synced: ${ENTRIES} entries (${BYTES} bytes)"
    if [[ "$SKIP" != "0" ]]; then
        warn "Skipped: ${SKIP} entries"
    fi
fi

log "Metadata: ${TARGET_DIR}/${METADATA_FILE}"
