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
| `automation` | Workflow orchestration | Prefect, NemoClaw |
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
| `automation` | Automation rules / triggers | HA automations, NemoClaw playbooks, cron | trigger, last_triggered, success_rate |
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
| `zone` | DNS zones | themillertribe.org, internal zones | provider, record_count, serial |
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
  "host": "tmtdockp01",
  "service_type": "inference",
  "critical": true,
  "dependencies": ["nfs-models", "caddy"],
  "registered_by": "nemoclaw:discovery"
}
```

Upserts — if the service exists, updates fields and refreshes `last_seen`.

### List Services
```
GET /ops/cmdb?service_type=inference&critical=true&host=tmtdockp01
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
