#!/usr/bin/env python3
"""The corvus-v2 build proof: the engine actually serves.

This is the harness's "build" step, and it proves three things a unit test
cannot: the app object constructs from a real config, it serves over a real
socket, and the auth boundary both admits a valid key and rejects an invalid
one. The 401 control matters — a check that only ever sees 200 would pass on
an app whose auth gate was deleted.

Exit 0 on success, non-zero with the reason on failure.
"""
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
from corvus.app import create_app  # noqa: E402
from corvus.config import FleetConfig  # noqa: E402

API_KEY = "dev-local-key"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = free_port()
    cfg = FleetConfig(name="dev-fleet", node_id="dev-1", api_key=API_KEY)
    app = create_app(config=cfg, db_path=":memory:")
    import uvicorn

    t = threading.Thread(
        target=lambda: uvicorn.run(app, host="127.0.0.1", port=port, log_level="error"),
        daemon=True,
    )
    t.start()
    time.sleep(1.5)

    def get(path: str, key: str):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"X-Corvus-Key": key})
        return urllib.request.urlopen(req, timeout=5)

    health = json.loads(get("/health", "unused").read())
    assert health["status"] == "ok", f"health not ok: {health}"

    authed = json.loads(get("/ops/events", API_KEY).read())
    assert authed is not None, "the authenticated read returned nothing"

    try:
        get("/ops/events", "wrong-key")
    except urllib.error.HTTPError as e:
        assert e.code == 401, f"expected 401 for a bad key, got {e.code}"
    else:
        return fail("the auth gate did NOT reject a wrong key")

    print(f"build: ok — {health['fleet']} / health + authenticated read + 401 control")
    return 0


def fail(msg: str) -> int:
    print(f"build: FAILED — {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
