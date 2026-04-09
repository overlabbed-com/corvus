# Governance Freshness Check

At session start, check `~/.claude/rules/.governance-sync-metadata` for the
`synced_at` timestamp. If the file is missing or the timestamp is more than
24 hours old, warn the operator:

> "Governance rules may be stale (last synced: [timestamp]). Corvus sync
> may have failed. Run `~/.claude/hooks/sync-governance.sh` to refresh,
> or verify Corvus is reachable."

This check is informational — do not refuse to work based on stale governance.
Cached rules are still valid, just potentially outdated.
