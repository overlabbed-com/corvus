# Service Registry (CMDB)

The CMDB is Corvus's service registry. Every service your agents manage
gets registered here with its classification, dependencies, and baseline
behavior.

## Service Types

| Type | Description | Examples |
|------|------------|---------|
| `inference` | GPU inference engines | vLLM, TGI |
| `database` | Databases | PostgreSQL, MySQL, Redis |
| `proxy` | Reverse proxy / load balancer | Caddy, Nginx, Traefik |
| `mcp_bridge` | MCP server bridges | FastAPI tools, API wrappers |
| `secrets` | Secrets management | 1Password Connect, Vault |
| `iot_gateway` | IoT gateways / controllers | Zigbee2MQTT, MQTT, ESPHome |
| `home_automation` | Home automation platforms | Home Assistant |
| `media` | Media services | Plex, Sonarr, Radarr |
| `monitoring` | Observability stack | Splunk, Netdata, Uptime Kuma |
| `automation` | Workflow orchestration | Prefect, ops-agent |
| `dns` | DNS infrastructure | CoreDNS, Pi-hole |
| `utility` | Stateless misc services | Tunnels, cron, Redis, autoheal |

Service type determines which FMEA triage runbook is selected.

## Configuration Items (CIs)

Services are the top-level unit, but operational intelligence requires
**sub-service granularity**. A CI is anything with an operational lifecycle
that can fail, expire, degrade, or cause impact. Not just application
components — accounts, subscriptions, licenses, hardware components, network
objects, storage datasets.

The ITIL definition of CI: "any component that needs to be managed in order
to deliver an IT service." Corvus takes this literally and deeply.

The graph traversal from a CI to an incident is what turns "Sonarr can't
download" into "the Astraweb account expired, which broke sabnzbd, which
starved Sonarr, which means Plex isn't getting new content."

### CI Types

#### Application Components
| Type | Description | Examples | Key Fields |
|------|-------------|---------|------------|
| `search` | Saved searches / scheduled reports | Splunk saved searches, Grafana alerts | schedule, avg_runtime_ms, status |
| `index` | Data indexes / collections | Splunk indexes, Milvus collections | max_size_gb, current_size_gb, retention_days |
| `app` | Installed applications / plugins | Splunk apps, OWUI tools, HA integrations | version, vendor, installed_at |
| `model` | ML/AI models | vLLM models, embedding models | size_gb, quantization, path, loaded |
| `flow` | Orchestration flows | Prefect flows, Prefect deployments | schedule, last_run, avg_duration_s, status |
| `endpoint` | HTTP/API endpoints | Health checks, API routes, webhooks | url, method, expected_status, avg_latency_ms |
| `automation` | Automation rules / triggers | HA automations, ops-agent playbooks, cron | trigger, last_triggered, success_rate |
| `integration` | Service-to-service connectors | HA integrations, OWUI connections, MCP servers | status, config_hash, last_healthy |
| `library` | Media / content libraries | Plex libraries, Radarr root folders | path, item_count, last_scan |
| `queue` | Processing / download queues | Sabnzbd queue, Prefect work queue | depth, avg_throughput, stuck_threshold |

#### Credentials & Subscriptions
| Type | Description | Examples | Key Fields |
|------|-------------|---------|------------|
| `account` | External service accounts | Astraweb, Usenet providers, cloud APIs | provider, username, expires_at, status |
| `credential` | Authentication tokens / keys | API keys, OAuth tokens, PATs | secret_path, rotated_at, expires_at, consumers[] |
| `license` | Software licenses | Portainer BE, Splunk | vendor, tier, expires_at, seat_count |
| `subscription` | Recurring service subscriptions | Cloudflare, domain registrations, B2 | provider, plan, renews_at, cost |
| `cert` | TLS certificates | Let's Encrypt wildcards, self-signed CA | domain, issuer, expires_at, auto_renew |

#### Infrastructure Components
| Type | Description | Examples | Key Fields |
|------|-------------|---------|------------|
| `zone` | DNS zones | example.com, internal zones | provider, record_count, serial |
| `record` | DNS records | A records, CNAME, TXT | zone, name, type, value, ttl |
| `vlan` | Network segments | VLAN 20 (server), VLAN 400 (IoT) | id, subnet, purpose, gateway |
| `firewall_rule` | Network access rules | UniFi firewall rules | direction, source, destination, action |
| `dataset` | Storage datasets | ZFS datasets, NFS exports | pool, path, used_gb, quota_gb, compression |
| `snapshot` | Storage snapshots | ZFS snapshots, B2 restic snapshots | dataset, created_at, size_gb, retention |
| `backup_job` | Backup schedules | Restic jobs, ZFS send/receive | schedule, last_run, last_success, target |

#### Hardware Components
| Type | Description | Examples | Key Fields |
|------|-------------|---------|------------|
| `disk` | Physical/virtual disks | NVMe, SAS, SSD in ZFS pools | host, serial, size_gb, pool, health |
| `nic` | Network interfaces | Physical NICs, bond interfaces | host, mac, speed, vlan, status |
| `psu` | Power supplies | Server PSUs | host, slot, status, wattage |
| `controller` | Hardware controllers | RAID, HBA, Zigbee coordinators | host, type, firmware, devices[] |

#### IoT / Home Automation
| Type | Description | Examples | Key Fields |
|------|-------------|---------|------------|
| `device` | IoT devices | Zigbee sensors, switches, lights | protocol, manufacturer, battery_pct, last_seen |
| `scene` | Automation scenes | HA scenes, lighting presets | entities[], last_activated |
| `bridge` | Protocol bridges | Z2M instances, Matter bridges | coordinator, device_count, firmware |
| `sensor` | Sensor readings | Temperature, humidity, motion | device, unit, last_value, threshold |

### CI Relationships

CIs connect to services, to each other, and to operational records.
Relationships are typed and directional — the graph is a directed property graph.

#### Structural
- `BELONGS_TO` — CI is part of a service
- `CONTAINS` — CI contains sub-CIs (dataset contains snapshots)
- `INSTALLED_ON` — app/model installed on service/GPU

#### Dependency
- `DEPENDS_ON` — hard dependency (breaks without it)
- `USES` — soft dependency (degrades without it)
- `READS_FROM` — data dependency (search reads index, service reads dataset)
- `WRITES_TO` — output dependency (service writes to index/queue)
- `AUTHENTICATES_WITH` — credential dependency (service uses account/token)
- `FEEDS` — pipeline dependency (prowlarr feeds sonarr, sabnzbd feeds radarr)

#### Infrastructure
- `LOADED_ON` — model loaded on GPU
- `STORED_ON` — data stored on volume/dataset
- `HOSTED_ON` — runs on a specific host/VLAN
- `SECURES` — cert secures endpoint
- `PROXIED_BY` — endpoint proxied by reverse proxy
- `ROUTES_TO` — DNS record/firewall rule routes to target
- `MANAGED_BY` — CI lifecycle managed by another service (certbot manages certs)

#### Operational
- `AFFECTS_CI` — incident affects a specific CI
- `CHANGED_BY` — change record modified this CI
- `MONITORED_BY` — CI is watched by a monitoring rule/search
- `EXPIRED` — temporal: account/cert/license has expired (auto-generated edge)

### API

#### Register CI
```
POST /ops/cmdb/ci
```
```json
{
  "type": "search",
  "name": "security_audit_daily",
  "service": "splunk",
  "properties": {
    "schedule": "0 2 * * *",
    "avg_runtime_ms": 45000,
    "status": "enabled"
  },
  "relationships": [
    {"type": "READS_FROM", "target_type": "index", "target": "main"},
    {"type": "DEFINED_BY", "target_type": "app", "target": "corvus-splunk"}
  ]
}
```

#### List CIs
```
GET /ops/cmdb/ci?service=splunk&type=search
```

#### CI Impact
```
GET /ops/cmdb/ci/{name}/impact
```
Returns graph traversal: what depends on this CI, what incidents affect it,
what changes touched it recently.

## API

### Register Service
```
POST /ops/cmdb/register
```
```json
{
  "name": "vllm-primary",
  "host": "host-01",
  "service_type": "inference",
  "critical": true,
  "dependencies": ["nfs-models", "caddy"],
  "registered_by": "ops-agent:discovery"
}
```

Upserts — if the service exists, updates fields and refreshes `last_seen`.

### List Services
```
GET /ops/cmdb?service_type=inference&critical=true&host=host-01
```

### Get Service
```
GET /ops/cmdb/{name}
```

### Update Service
```
PATCH /ops/cmdb/{name}
```
```json
{
  "baseline_behavior": {
    "expected_restarts_per_day": 0,
    "startup_time_seconds": 600
  },
  "alert_policy": "escalate"
}
```

### Bulk Sync
```
POST /ops/cmdb/bulk-sync
```
```json
[
  {"name": "svc-1", "host": "host1", "service_type": "utility"},
  {"name": "svc-2", "host": "host2", "service_type": "database"}
]
```

### Bulk Classify
```
POST /ops/cmdb/bulk-classify
```
```json
[
  {"name": "svc-1", "service_type": "inference"},
  {"name": "svc-2", "service_type": "database"}
]
```

## Declared vs Running State (Config Drift Detection)

Every service can track its declared configuration (from GitOps) alongside its
running configuration (from container inspection). When they diverge, Corvus
generates a `gap:coverage:config-drift:{target}` problem.

### Declared State Fields

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `declared_image` | string | GitOps compose | Expected container image |
| `declared_healthcheck` | boolean | GitOps compose | Whether compose defines a healthcheck |
| `declared_env_hash` | string | GitOps compose | SHA256 of env var names (not values) |
| `declared_networks` | string[] | GitOps compose | Network memberships |
| `last_declared_at` | datetime | GitOps pipeline | When declared state was last updated |

### Population

Declared state is populated from two sources:
1. **GitOps pipeline** (authoritative): On deploy, CI/CD parses compose file
   and POSTs declared state to Corvus CMDB
2. **Discovery sweep** (detection): Agents periodically compare running
   containers against CMDB declared state and flag drift

### API

#### Update Declared State
```
PATCH /ops/cmdb/{name}
```
```json
{
  "declared_image": "caddy:2-alpine",
  "declared_healthcheck": true,
  "declared_env_hash": "a1b2c3d4..."
}
```

#### Drift Check
```
GET /ops/cmdb/{name}/drift
```
Returns comparison of declared vs running state with drift fields highlighted.

## Baseline Behavior

Per-service baselines enable intelligent alerting:

```json
{
  "expected_restarts_per_day": 0,
  "startup_time_seconds": 600,
  "expected_response_time_ms": 500
}
```

A certbot container restarting daily? Normal. A database restarting?
Incident. Baselines make this distinction automatic.

## Alert Policy

| Policy | Behavior |
|--------|---------|
| `default` | Normal alerting rules apply |
| `silent` | Suppress alerts (use with caution — requires change window visibility) |
| `escalate` | Always escalate to human, never auto-remediate |

## Configuration Item (CI) API

### Register CI
```
POST /ops/cmdb/ci
```
```json
{
  "name": "wildcard-cert-2026",
  "ci_type": "cert",
  "service_name": "caddy",
  "expires_at": "2026-10-15T00:00:00Z",
  "parent_ci": null,
  "operational_status": "active",
  "metadata": {
    "issuer": "Let's Encrypt",
    "domains": ["*.example.com"]
  }
}
```

**Response** (201):
```json
{
  "name": "wildcard-cert-2026",
  "ci_type": "cert",
  "service_name": "caddy",
  "expires_at": "2026-10-15T00:00:00Z",
  "parent_ci": null,
  "operational_status": "active",
  "metadata": {"issuer": "Let's Encrypt", "domains": ["*.example.com"]},
  "days_until_expiry": 185,
  "created_at": "2026-04-13T10:00:00Z",
  "updated_at": "2026-04-13T10:00:00Z",
  "relationships": {
    "used_by": ["caddy"],
    "parent": null,
    "children": []
  }
}
```

### Get CI
```
GET /ops/cmdb/ci/{name}
```

### Get CI Impact
```
GET /ops/cmdb/ci/{name}/impact
```
**Response**:
```json
{
  "ci_name": "powerdns-api-key",
  "ci_type": "credential",
  "direct_dependents": ["powerdns", "caddy"],
  "indirect_dependents": ["all-dns-dependent-services"],
  "services_using": ["powerdns", "caddy"],
  "change_window_required": true,
  "risk_level": "high"
}
```

### Get Expiring CIs
```
GET /ops/cmdb/ci/expiring?days=30
```
**Response**:
```json
{
  "expiring_in_7_days": [
    {"name": "cert-staging", "ci_type": "cert", "expires_at": "...", "days_left": 5, "service_name": "caddy"}
  ],
  "expiring_in_30_days": [
    {"name": "slack-webhook-old", "ci_type": "credential", "expires_at": "...", "days_left": 15}
  ],
  "expiring_in_90_days": [],
  "already_expired": [
    {"name": "old-api-key", "ci_type": "credential", "expires_at": "...", "days_left": -10}
  ]
}
```

### List CIs
```
GET /ops/cmdb/ci?ci_type=cert&status=active
```

## CI Lifecycle States

| State | Description | Transition Triggers |
|-------|-------------|---------------------|
| `active` | Normal operational state | Default on registration |
| `expiring` | Within 30 days of expiry | Auto-detected by expiry sweep |
| `expired` | Past expiry date | Auto-detected by expiry sweep |
| `revoked` | Manually revoked before expiry | Manual action (e.g., security incident) |
| `decommissioned` | Retired, no longer in use | Manual action |

## Expiry Handling

**Alert Schedule**:
- 30 days before: `info` event logged
- 7 days before: `warning` event + Slack notification
- 1 day before: `critical` event + incident auto-created
- Expired: `critical` event + incident auto-escalated

**Auto-transition**: Background task runs every 5 minutes to:
1. Query CIs expiring within 30 days → set status to `expiring`
2. Query CIs past expiry → set status to `expired`
3. Emit events for status transitions

## Neo4j Graph Schema

**CI Node Labels**:
```cypher
(:CI {name, ci_type, expires_at, operational_status, metadata})
```

**Relationship Types**:
- `(:Service)-[:USES]->(:CI)` — Service uses this CI
- `(:CI)-[:BELONGS_TO]->(:CI)` — Child-parent CI relationship
- `(:CI)-[:RENEWS_TO]->(:CI)` — Old cert → new cert transition
- `(:CI)-[:CONTAINS]->(:CI)` — Zone contains records, dataset contains snapshots
- `(:CI)-[:DEPENDS_ON]->(:CI)` — CI depends on another CI
- `(:Incident)-[:AFFECTS_CI]->(:CI)` — Incident impacts this CI

## Deploy Tracking Fields (Phase 4.3)

Services track their deployment state to enable drift detection and failure analysis.

| Field | Type | Description |
|-------|------|-------------|
| `declared_image` | string | Image tag from GitOps compose file |
| `declared_healthcheck` | string | Healthcheck command from compose |
| `declared_env_hash` | string | SHA256 of env var names (not values) |
| `declared_networks` | string[] | Networks from compose file |
| `last_declared_at` | datetime | When declared state was last updated |
| `last_deploy_attempt` | datetime | Last deploy attempt timestamp |
| `last_deploy_status` | string | success, failure, in_progress, cancelled |
| `last_deploy_error` | string | Error message if deploy failed |

### Usage

**Register declared state** (called by GitOps pipeline after compose parse):
```
POST /ops/cmdb/{name}/declared
```
```json
{
  "image": "myapp:v1.2.3",
  "healthcheck": "curl -f http://localhost:8080/health",
  "env_hash": "a1b2c3d4...",
  "networks": ["bridge", "custom"]
}
```

**Record deploy attempt** (called by GitHub Actions):
```
POST /ops/cmdb/{name}/deploy
```
```json
{
  "status": "failure",
  "error": "Container OOMKilled",
  "workflow_run_id": 12345
}
```

**Check drift**:
```
GET /ops/cmdb/{name}/drift
```
```json
{
  "has_drift": true,
  "drift_fields": ["image", "healthcheck"],
  "declared": {
    "image": "myapp:v1.2.3",
    "healthcheck": "curl health"
  },
  "running": {
    "image": "myapp:v1.2.2",
    "healthcheck": "curl /health"
  },
  "severity": "high"
}
```

## Deploy Failure Diagnosis (Phase 4.3)

Deploy failures are analyzed and classified into patterns:

| Diagnosis | Symptoms | Confidence | Remediation |
|-----------|----------|------------|-------------|
| `resource_exhaustion` | OOMKilled, memory errors | 90% | Increase limits, optimize |
| `slow_startup` | Healthcheck timeout | 85% | Increase timeout, optimize init |
| `stale_container_config` | Out of sync errors | 90% | Re-sync from GitOps |
| `image_pull_failure` | Pull access denied | 95% | Check credentials, verify tag |
| `dependency_unavailable` | Connection refused | 80% | Check dependency health |
| `unknown_deploy_failure` | No clear pattern | 30% | Manual investigation |

**API**: `POST /ops/discovery/deploy/analyze`
```json
{
  "service": "myapp",
  "error": "Container OOMKilled",
  "workflow_logs": "..."
}
```

**Response**:
```json
{
  "diagnosis": "resource_exhaustion",
  "confidence": 0.9,
  "remediation": [
    "Check container memory limits",
    "Increase limits or optimize service"
  ],
  "root_cause_hint": "Service exceeded memory limits"
}
```
