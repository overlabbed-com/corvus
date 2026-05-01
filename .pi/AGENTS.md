# corvus (direct clone) — Pi Agent Context

This is a direct clone of `overlabbed-com/corvus` — the canonical Corvus operational governance platform source.

Remote: `https://github.com/overlabbed-com/corvus.git`

## What This Repo Does

Corvus provides shared operational state, structured events, FMEA triage runbooks, knowledge management, dependency graphs, and trust ledger for AI agent fleets. Any agent that speaks HTTP can use it.

## Key Capabilities

- Shared ops state: changes, incidents, problems, CMDB
- Event protocol: OCSF 1.3.0 native, SIEM-portable
- FMEA runbooks: 13 service types, service-type-aware triage
- Knowledge management: FTS-backed operational memory
- Conflict check: prevent agents from working the same target simultaneously
- Dependency graph: Neo4j-backed topology, blast radius queries
- Trust ledger: track agent reliability per action type

## Key Directories

```
config/            — Default configuration
docs/              — Architecture and API documentation
AGENT_INTEGRATION_GUIDE.md
AGENT_SETUP_CLAUDE_CODE.md
```

## Homelab Instance

The homelab Corvus runs on dockp04. Deployment config: `tmt-homelab/homelab-automation/stacks/dockp04-corvus/`.

Development happens here (source). Deployment is separate (GitOps repo).

## Branch Pattern

`feature/<description>` or `fix/<description>`

## PORTABLE CODE RULES — CRITICAL

Corvus is open-source and portable. It must be deployable by anyone.

- **No homelab IPs** (no `192.168.20.*`)
- **No dockp* hostnames**
- **No homelab-specific defaults** in code or config
- Generic examples only in docs (`my-server`, `example.com`, `192.0.2.x`)
- Homelab deployment details belong in `tmt-homelab/homelab-automation`, not here
