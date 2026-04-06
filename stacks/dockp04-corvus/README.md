# Corvus Deployment

Generic deployment template - customize for your infrastructure.

Next-gen customer zero deployment of Corvus operational governance platform.

## Quick Start

```bash
# 1. Clone the config
cd /mnt/docker/stacks/corvus  # or your stack directory
cp .env.template .env

# 2. Generate API keys for your agents
# For each agent that will use Corvus:
openssl rand -hex 32

# 3. Edit .env and set CORVUS_API_KEYS
# Format: key_name:key_type:role
# Example: CORVUS_API_KEYS=corvus-admin:admin:admin,nemoclaw:agent:ops-write

# 4. Deploy
docker compose pull
docker compose up -d

# 5. Verify health
curl http://localhost:8000/health
```

## Agent Integration

### Connecting Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "corvus": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-http"
      ],
      "env": {
        "HTTP_URL": "https://corvus.themillertribe-int.org/ops/mcp/sse",
        "HTTP_HEADERS": {
          "Authorization": "Bearer YOUR_CORVUS_API_KEY"
        }
      }
    }
  }
}
```

### Connecting NemoClaw

NemoClaw uses the Corvus MCP server for:
- Pre-action conflict checks (`ops_check_target`)
- Event emission (`ops_emit_event`)
- Incident creation (`ops_create_incident`)
- Change windows (`ops_create_change`, `ops_close_change`)

Configure in NemoClaw's MCP settings with the same endpoint.

## API Endpoints

| Endpoint | Description | Auth |
|----------|-------------|------|
| `/health` | Health check | Public |
| `/ops/events` | Emit/list events | Required |
| `/ops/incidents` | Create/list incidents | Required |
| `/ops/changes` | Change windows | Required |
| `/ops/cmdb` | Service registry | Required |
| `/ops/runbooks/triage` | Execute triage | Required |
| `/ops/mcp/sse` | MCP server endpoint | Internal |

## Security

- Non-root user (corvus:corvus)
- API key authentication
- Optional OIDC/JWT support
- Rate limiting (500/min/IP default)
- Audit logging on all `/ops/` and `/backup/` endpoints
- Secret sanitization in logs

## Monitoring

- Health endpoint: `http://corvus:8000/health`
- Metrics: `http://corvus:8000/ops/metrics`
- Netdata dashboards enabled

## Backup

Volume `corvus-data` contains:
- `corvus.db` - SQLite ops database
- `audit.jsonl` - Audit logs

Backup command:
```bash
docker exec corvus tar czf - /data | gzip > corvus-backup-$(date +%Y%m%d).tar.gz
```

## Troubleshooting

```bash
# Check logs
docker compose logs -f corvus

# Check health
curl http://localhost:8000/health

# Inspect container
docker inspect corvus

# Restart
docker compose restart corvus
```
