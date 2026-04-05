# Corvus — Product Vision & Ideation Capture

> Living document. Captures all brainstorming, design decisions, and roadmap items
> from the founding session (2026-03-29) and ongoing ideation.

## The One-Liner

**Operational governance for AI agent fleets.**

Your AI agents are smart individually. Corvus makes them smart together.

## Origin Story

Born from a homelab with two AI agents (Claude Code and NemoClaw) that kept
stepping on each other. CC stopped a container for GPU training. NemoClaw detected
it as a failure and alerted. The human was the message bus between his own AI tools.

The solution evolved through four projects:
- **Project 019 (SOP)**: Shared database — changes, incidents, problems, CMDB, events
- **Project 020 (FMEA Runbooks)**: Service-type-aware triage — not generic log pulls
- **Project 021 (UOP)**: Unified protocol — same rules for all agents, blind spot detection
- **Project 023 (Graph Explorer)**: OCSF-native audit trail with Splunk visualization

The inflection point: this isn't a homelab tool. This is a product that doesn't exist yet.

## Core Thesis

Every organization deploying AI agents will face the same problem: agents operating
independently with no shared awareness, no operational governance, and no audit trail.
Corvus solves this with a drop-in platform that provides mature operational governance
regardless of which agents, LLMs, or infrastructure you use.

## What Corvus Provides

### Core (always deployed)

| Capability | Description | Origin |
|-----------|-------------|--------|
| **Shared Ops State** | Changes, incidents, problems, CMDB — one source of truth | Project 019 |
| **Event Protocol** | OCSF 1.3.0 native, graph-traversable, SIEM-portable | Project 023 |
| **Knowledge Management** | RAG-backed operational memory — agents learn from resolutions | Project 015/017 |
| **FMEA Runbooks** | Service-type-aware triage — failure mode analysis, not pattern matching | Project 020 |
| **Blind Spot Detection** | System knows what it doesn't know, generates improvement backlog | Project 021 |
| **Conflict Check** | Pre-action target status: GO/CAUTION/STOP | Project 021 |
| **Runbook Engine** | YAML-based, declarative, auditable investigation + remediation | Project 020 |

### Extensible Modules

#### Governance Frameworks
| Module | Description | Status |
|--------|-------------|--------|
| ITIL | Change/incident/problem management with lifecycle | Built (core) |
| PMP | Project gates, deliverable tracking, risk registers | Planned |
| Agile | Sprint planning, velocity from agent event data, burndown | Planned |
| Lean | Value stream mapping, waste detection | Planned |
| SAFe | Portfolio → program → team alignment | Planned |

#### Compliance Controls
| Module | Controls | Status |
|--------|----------|--------|
| SOC 2 Type II | CC6-CC9 mapped to OCSF events | Planned |
| ISO 27001 | Annex A controls | Planned |
| NIST CSF | Identify, Protect, Detect, Respond, Recover | Planned |
| FedRAMP | NIST 800-53 control families | Planned |
| PCI DSS | Requirements mapped to operational evidence | Planned |

#### Integrations
| Category | Systems | Status |
|----------|---------|--------|
| Ticketing | Jira, ServiceNow, Linear | Planned |
| Communication | Slack, Teams, PagerDuty | Slack built (NemoClaw) |
| SIEM | Splunk, Azure Sentinel, Google Chronicle, Elastic | Splunk in progress |
| LLM | Any OpenAI-compatible API | Built (via LiteLLM) |
| Infrastructure | Docker, Kubernetes, bare metal | Docker built |

#### Agent Adapters
| Agent Framework | Description | Status |
|----------------|-------------|--------|
| NemoClaw | TMT Homelab autonomous ops agent | Built (customer zero) |
| Claude Code | CC governance rules + MCP tools | Built (customer zero) |
| CrewAI | CrewAI agent adapter | Planned |
| AutoGen | AutoGen adapter | Planned |
| LangChain | LangChain agent adapter | Planned |
| Custom | HTTP-based integration guide | Planned |

## Architecture Decisions

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-29 | Agent-agnostic — no agent SDK | Corvus works with ANY agent via HTTP. Not tied to a framework. |
| 2026-03-29 | OCSF-native from day one | Portable across SIEMs. Standard > custom. |
| 2026-03-29 | Single deployable (corvus-server) | One container, one config. Not a distributed system. |
| 2026-03-29 | Modules, not hardcoded frameworks | Governance and compliance are plug-in, not built-in. ITIL is a module. |
| 2026-03-29 | NemoClaw is a consumer, not part of product | Agents are customers. Corvus is the platform. |
| 2026-03-29 | Portability as design constraint, not feature | Every decision must work outside the homelab. |
| 2026-03-29 | Blind spot detection is operational, not periodic | The system generates problem records about its own gaps in real-time. |
| 2026-03-29 | Gaps ARE problems (existing table) | No new abstractions. Gaps use the same lifecycle as operational problems. |
| 2026-03-29 | Compliance evidence is auto-generated | Map OCSF events to control frameworks. Audit prep is a query, not a project. |
| 2026-03-30 | Neo4j for operational graph (moved from long-term) | Every operational question is a traversal. 92 services today, product targets 500+. Learn patterns now, not later. |
| 2026-03-30 | Investigation standards as enforceable contracts | Agents submit evidence to Corvus; server validates schema (422 on missing exit_code, unseparated logs). Spec is code, not docs. |
| 2026-03-30 | Correlation groups replace per-incident alerts | Shared-resource failures produce 1 group alert, not N independent alerts. Reduces noise, finds root cause. |
| 2026-03-30 | Config drift as CMDB first-class concept | Declared state (from GitOps) vs running state (from inspection). Drift = gap problem, auto-generated. |
| 2026-03-30 | Deploy failures get FMEA treatment | triage-deploy.yaml — same runbook framework as runtime triage. No more passthrough alerts. |
| 2026-03-30 | Sub-service CI granularity in graph | Not just "Splunk is slow" — which search, which index, which change. Search → index → incident is operational intelligence done right. |
| 2026-03-30 | 6-layer discovery (declared, observed, inspected, reported, inferred, elicited) | Discovery is THE priority — the graph is only as good as the data in it. No single layer catches everything; together they build a living graph. |
| 2026-03-30 | Edge provenance with confidence aggregation | Every edge carries layers[], confidence, first_discovered, last_confirmed. Multi-layer confirmation increases confidence. Inferred edges below threshold go to suggestion queue. |
| 2026-03-30 | Discovery is what kills CMDBs — Corvus solves it portably | Docker adapter (customer zero), K8s and bare metal adapters planned. Universal graph schema, platform-specific adapters. Bootstrap to 80% coverage in <2 hours. |

## Improvement Ideas (from Wiggum Loop brainstorm)

### Investigation Quality
| ID | Idea | Impact | Effort | Status |
|----|------|--------|--------|--------|
| IQ-1 | Complete runbook set (all 14 service types) | High | Medium | 3 of 14 done |
| IQ-2 | Structured log parsing per service | High | Medium | Planned |
| IQ-3 | Cross-service correlation (dependency graph traversal) | Very High | High | Planned (needs graph) |
| IQ-4 | Historical comparison (baseline vs actual) | Medium | Medium | CMDB field exists |
| IQ-5 | LLM-assisted diagnosis (pass investigation to LLM) | High | Medium | Planned |

### False Positives / Noise
| ID | Idea | Impact | Effort | Status |
|----|------|--------|--------|--------|
| FP-1 | Per-service alert baselines (CMDB baseline_behavior) | Very High | Medium | Field exists, needs population |
| FP-2 | Alert suppression rules engine (declarative) | High | Medium | Planned |
| FP-3 | Intelligent severity scoring (type + critical + deps) | Medium | Low | Planned |
| FP-4 | Recurring maintenance window awareness | Medium | Low | Change windows exist |

### Autonomy Gaps
| ID | Idea | Impact | Effort | Status |
|----|------|--------|--------|--------|
| AG-1 | Remediation runbooks (not just triage — fix steps) | Very High | High | Planned (020 P3) |
| AG-2 | Trust ledger acceleration (bulk promote proven actions) | High | Low | Planned |
| AG-3 | Self-healing playbook chains (diagnosis → auto-fix → verify) | High | High | Planned |
| AG-4 | Capacity-aware remediation (check resources before acting) | Medium | Medium | Planned |

### Blind Spots
| ID | Idea | Impact | Effort | Status |
|----|------|--------|--------|--------|
| BS-1 | Application-level health checks (hit /health, verify response) | Very High | Medium | Planned |
| BS-2 | Metric trend detection (Netdata integration) | High | High | Planned |
| BS-3 | NFS/storage mount monitoring | High | Low | Planned |
| BS-4 | Backup verification (did restic succeed?) | Medium | Low | Planned |
| BS-5 | Cross-host cascade detection | High | Medium | Per-host caps exist |
| BS-6 | End-to-end synthetic transactions | Very High | High | Planned |

### Unified Protocol
| ID | Idea | Impact | Effort | Status |
|----|------|--------|--------|--------|
| UP-1 | CC ops compliance (emit events, create incidents) | Very High | Medium | Rules written, needs practice |
| UP-2 | Real-time event feed to CC sessions | Very High | Medium | MCP tool deployed |
| UP-3 | Shared FMEA runbooks (CC + NC use same) | High | Medium | Planned (021 P3) |
| UP-4 | Pre-action conflict check | High | Medium | Deployed |
| UP-5 | Unified incident lifecycle | Very High | Low | Design exists |
| UP-6 | NC conflict check (NC checks for CC activity) | High | Medium | Planned (021 P2) |

## Threat Model Findings (2026-03-29)

27 findings from STRIDE analysis. Top items:

| ID | Finding | Risk | Status |
|----|---------|------|--------|
| E1.1 | /backup/exec allows arbitrary command execution | CRITICAL | Open |
| E1.2 | /backup/zfs allows arbitrary privileged commands | CRITICAL | Open |
| S1.1 | Single bearer token, no role differentiation | HIGH | Open |
| T1.1 | Mutable/deletable operational records | HIGH | Open |
| I1.1 | Unfiltered secrets in container logs | HIGH | Open |

Full report: `docs/designs/2026-03-29-threat-model.md`

## Customer Zero: TMT Homelab

| Metric | Value |
|--------|-------|
| Services monitored | 92 |
| FMEA service types | 14 |
| Triage runbooks | 3 (inference, database, proxy) |
| Docker hosts | 4 |
| GPUs | 9 (692GB VRAM) |
| AI agents | 2 (NemoClaw + Claude Code) |
| SOP tables | 5 (changes, events, CMDB, incidents, problems) |
| REST endpoints | 25+ |
| MCP tools | 15 |
| Tests | 540+ |

## Brand

**Corvus** — The crow constellation. Corvids are the smartest birds: they use tools,
plan ahead, communicate danger to the flock. A corvid that spots danger and alerts
the group IS this product.

Logo: Corvus constellation (4-star quadrilateral) with stylized crow silhouette overlay.

## What's Next

### Immediate (code migration)
- [ ] Migrate admin-api source → corvus-server/src/
- [ ] Migrate OCSF transformer → corvus-server/src/
- [ ] Write protocol spec documents (spec/)
- [ ] Set up CI/CD for corvus-server Docker image
- [ ] Create NemoClaw integration example (examples/nemoclaw/)
- [ ] Create Claude Code integration example (examples/claude-code/)

### Short-term (product hardening)
- [ ] 6-layer service discovery framework (spec/discovery.md) — THE priority. Graph is only as good as the data
- [ ] Neo4j operational graph (dependency traversal, correlation groups, blast radius) — moved from long-term per 2026-03-30 design
- [ ] Investigation standards enforcement (spec/investigation.md — exit codes, log categories, pattern quality)
- [ ] Correlation group detection (shared GPU/dependency/host/volume failure grouping)
- [ ] Deploy runbook (triage-deploy.yaml — CI/CD pipeline failure investigation)
- [ ] Config drift detection (CMDB declared vs running state comparison)
- [ ] Remediate CRITICAL threat model findings (E1.1, E1.2)
- [ ] Complete UOP Phase 1 exit criteria (1b, 1c, 1d)
- [ ] Remaining FMEA runbooks (11 service types)
- [ ] Splunk app Phase 3 (graph explorer)
- [ ] Compliance module: SOC 2 control mapping (first compliance module)

### Medium-term (module ecosystem)
- [ ] Jira integration module
- [ ] PMP governance module
- [ ] Agile governance module
- [ ] Additional SIEM modules (Sentinel, Chronicle)
- [ ] Kubernetes infrastructure adapter
- [ ] Remediation runbooks + self-healing chains

### Long-term (product maturity)
- [ ] Multi-tenant support
- [ ] SaaS deployment option
- [ ] Public documentation site
- [ ] Open-source core with commercial modules
