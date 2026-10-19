"""The closed error-enum codes (the contract v1.1) — the single source the
boundary (engine_shim), the compiler's coverage invariant, and the fixture
corpus all reference. The enum is CLOSED: adding a code requires a fixture
that triggers it (the coverage invariant) — one artifact, two consumers."""
# NOTE: "idempotency_replay" is NOT an error code — the replay is a SUCCESS
# marker on the cached response. The enum is closed: adding a code requires
# a fixture that triggers it.
ERROR_CODES = {
    "not_found", "no_sites", "duplicate_site", "unknown_type",
    "missing_instructions", "choice_without_criteria", "score_without_scale",
    "provenance_below_floor", "probability_in_facts", "out_of_enum",
    "quota_exhausted",
}
