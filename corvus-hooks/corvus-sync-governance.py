#!/usr/bin/env python3
"""SessionStart hook: sync governance rules from Corvus.

Calls sync-governance.sh to pull governance entries from Corvus and write them
to ~/.claude/rules/. Fail-open: if the script is missing, times out, or fails,
the session starts normally with cached rules.

All output goes to stderr so it doesn't interfere with CC hook JSON protocol.
"""

import os
import subprocess
import sys

TIMEOUT_SECONDS = 10


def main() -> int:
    # Locate sync-governance.sh in the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sync_script = os.path.join(script_dir, "sync-governance.sh")

    try:
        result = subprocess.run(
            [sync_script],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        # Print stdout and stderr to stderr (avoid polluting hook JSON on stdout)
        if result.stdout:
            print(result.stdout.rstrip(), file=sys.stderr)
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)

        if result.returncode != 0:
            print(
                f"[corvus-sync] sync-governance.sh exited {result.returncode}; "
                "using cached rules",
                file=sys.stderr,
            )

    except FileNotFoundError:
        print(
            f"[corvus-sync] sync-governance.sh not found at {sync_script}; "
            "using cached rules",
            file=sys.stderr,
        )

    except subprocess.TimeoutExpired:
        print(
            f"[corvus-sync] sync-governance.sh timed out after {TIMEOUT_SECONDS}s; "
            "using cached rules",
            file=sys.stderr,
        )

    except Exception as exc:
        print(
            f"[corvus-sync] unexpected error: {exc}; using cached rules",
            file=sys.stderr,
        )

    # Always exit 0 -- fail-open so session starts regardless
    return 0


if __name__ == "__main__":
    sys.exit(main())
