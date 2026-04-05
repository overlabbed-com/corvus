# Corvus

**Operational governance for AI agent fleets.**

Your AI agents are smart individually. Corvus makes them smart together.

Deploy one container. Connect your agents, infrastructure, LLM, and SIEM. Your agents go from independent tools to governed operators with shared awareness, self-improving blind spot detection, and audit-grade compliance evidence.

## The Problem

AI agents operating infrastructure have no shared awareness. Agent A restarts a container. Agent B detects the restart as a failure and alerts. The human is the message bus between their own AI tools.

Corvus gives your agents a shared operational picture. When one acts, the others know. When something breaks, the right investigation fires — not a generic log pull. When an auditor asks "what happened?" — the evidence chain is already there.

## Core (always deployed)

| Capability | What It Does |
|-----------|--------------|
| **Shared Ops State** | Changes, incidents, problems, CMDB — one source of truth for all agents |
| **Event Protocol** | OCSF 1.3.0 native. Every action is structured, graph-traversable, SIEM-portable |
| **Knowledge Management** | RAG-backed operational memory. Agents learn from every resolution |
| **FMEA Runbooks** | Service-type-aware triage. Failure mode analysis, not pattern matching |
| **Blind Spot Detection** | The system continuously knows what it doesn't know and generates its own improvement backlog |
| **Conflict Check** | Before any agent acts, check if another agent is already working on the same target |

## Modules (plug in what you need)

### Governance Frameworks
| Module | Coverage |
|--------|----------|
| ITIL | Change, incident, problem management with proper lifecycle |
| PMP | Project gates, deliverable tracking, risk registers |
| Agile | Sprint planning, velocity (derived from agent event data), burndown |
| Lean | Value stream mapping, waste detection |
| SAFe | Portfolio → program → team alignment |

### Compliance Controls
| Module | Controls |
|--------|----------|
| SOC 2 Type II | CC6-CC9 mapped to agent events |
| ISO 27001 | Annex A controls mapped to OCSF |
| NIST CSF | Identify, Protect, Detect, Respond, Recover |
| FedRAMP | NIST 800-53 control families |
| PCI DSS | Requirements mapped to operational evidence |

Compliance evidence is auto-generated from operational data. "Show me SOC 2 CC8.1 for Q1" is a query, not a 3-week audit prep.

### Integrations
| Category | Supported |
|----------|-----------|
| Ticketing | Jira, ServiceNow, Linear |
| Communication | Slack, Teams, PagerDuty |
| SIEM | Splunk (custom app), Azure Sentinel, Google Chronicle, Elastic |
| Agents | Claude Code, CrewAI, AutoGen, LangChain, any HTTP-capable agent |
| LLM | Any OpenAI-compatible API (for triage diagnosis) |
| Infrastructure | Docker, Kubernetes, bare metal (via adapters) |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Your Agents                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────┐  │
│  │ Claude  │  │ CrewAI  │  │ Custom  │  │  ...  │  │
│  │  Code   │  │  Agent  │  │  Agent  │  │       │  │
│  └────┬────┘  └────┬────┘  └────┬────┘  └───┬───┘  │
└───────┼────────────┼────────────┼────────────┼──────┘
        │            │            │            │
        └────────────┴─────┬──────┴────────────┘
                           │ REST API
                    ┌──────┴──────┐
                    │             │
                    │   Corvus    │  ← Single deployment
                    │   Server    │    (Docker / app / managed)
                    │             │
                    │  ┌────────┐ │
                    │  │Ops State│ │  Changes, incidents, problems, CMDB
                    │  ├────────┤ │
                    │  │  OCSF  │ │  Event transformation + forwarding
                    │  ├────────┤ │
                    │  │Runbooks│ │  FMEA triage + remediation engine
                    │  ├────────┤ │
                    │  │  RAG   │ │  Operational knowledge management
                    │  ├────────┤ │
                    │  │Modules │ │  Governance + compliance + integrations
                    │  └────────┘ │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────┴────┐  ┌───┴───┐  ┌────┴─────┐
         │  Your   │  │ Your  │  │  Your    │
         │  SIEM   │  │ LLM   │  │ Tickets  │
         └─────────┘  └───────┘  └──────────┘
```

## Quick Start

```bash
docker run -d \
  -p 8000:8000 \
  -v corvus-data:/data \
  -e CORVUS_LLM_URL=http://your-llm:8000/v1 \
  -e CORVUS_SIEM_URL=https://your-splunk:8088 \
  ghcr.io/tmttodd/corvus:latest
```

Point your agents at `http://corvus:8000`. See the [protocol spec](spec/) for API contracts.

## Standards

- **OCSF 1.3.0** — Every event is schema-compliant and SIEM-portable
- **ITIL** — Change/incident/problem lifecycle (core module)
- **FMEA** — Failure Mode and Effects Analysis for service-aware triage

## Status

Customer zero: TMT Homelab — 92 services, 4 hosts, 9 GPUs, 2 AI agents (NemoClaw + Claude Code).

Active development. Core is proven in production. Modules and packaging in progress.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
