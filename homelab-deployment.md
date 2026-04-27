# Corvus Customer Zero — Homelab Deployment Guide

**Target Host**: tmtdockp04 (192.168.20.14)  
**Stack Path**: `/mnt/docker/stacks/dockp04-corvus`  
**Repo**: `github.com/tmt-homelab/homelab-automation`

---

## Quick Start

### 1. Configure Secrets in 1Password

Open the 1Password vault **Homelab** → item **Dockp04-Corvus-Secrets** and add:

| Field | Value | Required |
|-------|-------|----------|
| `CORVUS_API_KEYS` | `claude-code-key` (or your API key) | ✅ Yes |
| `NEO4J_PASSWORD` | `your-strong-password` | ✅ Yes |
| `CORVUS_SIEM_URL` | `https://splunk.themillertribe-int.org:8088/services/collector/event` | ⚠️ Optional |
| `CORVUS_SIEM_TOKEN` | `your-splunk-hec-token` | ⚠️ Optional |
| `CORVUS_LLM_URL` | `http://litellm:4000` | ⚠️ Optional |
| `GITHUB_TOKEN` | `ghp_xxx` (GitHub PAT with repo scope) | ✅ For Flywheel |
| `GITHUB_REPO` | `overlabbed-com/corvus` | ✅ For Flywheel |

### 2. Deploy via GitHub Actions

The deployment is triggered automatically when you push to `main` in `homelab-automation`:

```bash
cd /Users/tmiller/git/homelab-automation
git checkout main
git pull origin main
```

Or manually trigger the workflow:
- Go to: https://github.com/tmt-homelab/homelab-automation/actions/workflows/deploy-dockp04-corvus.yml
- Click "Run workflow"
- Select "main" branch
- Click "Run workflow"

### 3. Verify Deployment

```bash
# Check container health
ssh tmiller@192.168.20.14 "sudo docker ps --filter name=corvus --format 'table {{.Names}}\t{{.Status}}'"

# View logs
ssh tmiller@192.168.20.14 "sudo docker logs corvus --tail 50"

# Check health endpoint
curl -s http://192.168.20.14:9420/health | jq
```

Expected output:
```json
{
  "status": "healthy",
  "timestamp": "2026-04-26T12:00:00Z",
  "components": {
    "database": "healthy",
    "graph": "healthy",
    "siem": "healthy"
  }
}
```

---

## Customer Zero Flywheel Activation

### Enable Continuous Improvement

Once `GITHUB_TOKEN` is configured, the flywheel runs **automatically every hour**.

#### Verify Flywheel is Running

```bash
# Check for flywheel logs
ssh tmiller@192.168.20.14 "sudo docker logs corvus --tail 200 | grep -i flywheel"

# Expected output:
# "Starting continuous improvement flywheel cycle..."
# "Harvesting operational issues..."
# "Creating GitHub issues for critical gaps..."
```

#### Monitor Success Criteria

```bash
# Check success criteria status
curl -s http://192.168.20.14:9420/ops/success-criteria/status | jq

# Expected output:
{
  "criteria": [
    {"name": "Zero Critical Vulnerabilities", "target": 0, "current": 0, "achieved": true},
    {"name": "SIEM Delivery Rate", "target": "99.9%", "current": "99.5%", "achieved": true},
    {"name": "Test Coverage", "target": "85%", "current": "90%", "achieved": true},
    ...
  ],
  "overall_score": 100,
  "all_achieved": true
}
```

#### View Implementation Progress

```bash
curl -s http://192.168.20.14:9420/ops/implementation/status | jq
```

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `CORVUS_API_KEYS` | API keys for authentication | `claude-code-key` |
| `NEO4J_PASSWORD` | Neo4j database password | `your-strong-password` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `CORVUS_SIEM_URL` | Splunk HEC endpoint | (disabled) |
| `CORVUS_SIEM_TOKEN` | Splunk HEC token | (disabled) |
| `CORVUS_LLM_URL` | LLM endpoint for runbook enhancement | (disabled) |

### Customer Zero Flywheel

| Variable | Description | Example |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub PAT with repo scope | `ghp_xxx` |
| `GITHUB_REPO` | Repository for issue creation | `overlabbed-com/corvus` |

---

## Troubleshooting

### Container Not Starting

```bash
# Check logs
ssh tmiller@192.168.20.14 "sudo docker logs corvus --tail 100"

# Common issues:
# - Missing API key: CORVUS_API_KEYS not set
# - Neo4j connection failed: Check corvus-neo4j container health
# - Port already in use: Check if 9420 or 7687 are occupied
```

### Flywheel Not Running

```bash
# Check if GITHUB_TOKEN is set
ssh tmiller@192.168.20.14 "sudo docker exec corvus env | grep GITHUB_TOKEN"

# If missing, redeploy after adding to 1Password

# Check GitHub API rate limit
curl -s http://192.168.20.14:9420/debug/state | jq '.github_rate_limit'
```

### SIEM Forwarding Not Working

```bash
# Check Splunk connectivity
ssh tmiller@192.168.20.14 "sudo docker exec corvus curl -s -X POST \
  'https://splunk.themillertribe-int.org:8088/services/collector/health' \
  -H 'Authorization: Splunk YOUR_TOKEN'"

# Check dead-letter queue for failed events
curl -s http://192.168.20.14:9420/ops/events/dead-letter | jq
```

### Graph Database Issues

```bash
# Check Neo4j health
ssh tmiller@192.168.20.14 "sudo docker exec corvus-neo4j wget -q --spider http://localhost:7474"

# View Neo4j logs
ssh tmiller@192.168.20.14 "sudo docker logs corvus-neo4j --tail 50"

# Restart if needed
ssh tmiller@192.168.20.14 "sudo docker restart corvus-neo4j"
```

---

## Maintenance

### View Logs

```bash
# Corvus server logs
ssh tmiller@192.168.20.14 "sudo docker logs corvus --follow"

# Neo4j logs
ssh tmiller@192.168.20.14 "sudo docker logs corvus-neo4j --follow"

# Save logs for analysis
ssh tmiller@192.168.20.14 "sudo docker logs corvus --tail 1000 > corvus-logs.txt"
```

### Restart Services

```bash
# Restart single service
ssh tmiller@192.168.20.14 "sudo docker restart corvus"

# Restart entire stack
ssh tmiller@192.168.20.14 "cd /mnt/docker/stacks/dockp04-corvus && sudo docker compose restart"
```

### Update Deployment

```bash
# Trigger new deployment via GitOps
cd /Users/tmiller/git/homelab-automation
git pull origin main  # Merge PR #139 or other changes

# Or manually re-run workflow (see above)
```

### Backup Data

```bash
# Backup Corvus data volume
ssh tmiller@192.168.20.14 "sudo docker run --rm \
  -v dockp04-corvus-corvus-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/corvus-backup-$(date +%Y%m%d).tar.gz /data"

# Backup Neo4j data volume
ssh tmiller@192.168.20.14 "sudo docker run --rm \
  -v dockp04-corvus-neo4j-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/neo4j-backup-$(date +%Y%m%d).tar.gz /data"
```

### Restore from Backup

```bash
# Restore Corvus data
ssh tmiller@192.168.20.14 "sudo docker run --rm \
  -v dockp04-corvus-corvus-data:/data \
  -v /path/to/backup:/backup \
  alpine tar xzf /backup/corvus-backup.tar.gz -C /"

# Restart Corvus
ssh tmiller@192.168.20.14 "sudo docker restart corvus"
```

---

## Monitoring & Observability

### Prometheus Metrics

```bash
# Access metrics endpoint
curl -s http://192.168.20.14:9420/metrics

# Sample output:
# corvus_events_total 1234
# corvus_incidents_open 2
# corvus_changes_active 1
# corvus_gap_detection_total 5
# corvus_success_criteria_score 100
```

### Detailed Health Checks

```bash
# Basic health
curl -s http://192.168.20.14:9420/health | jq

# Detailed diagnostics
curl -s http://192.168.20.14:9420/health/detailed | jq

# Readiness probe
curl -s http://192.168.20.14:9420/health/ready | jq
```

### Debug Endpoints

```bash
# System state
curl -s http://192.168.20.14:9420/debug/state | jq

# Memory profile
curl -s http://192.168.20.14:9420/debug/memory | jq

# Active triage sessions
curl -s http://192.168.20.14:9420/debug/triage | jq
```

---

## Integration Points

### Splunk SIEM Forwarding

When `CORVUS_SIEM_URL` and `CORVUS_SIEM_TOKEN` are configured:

- All events forwarded to Splunk HEC
- OCSF 1.3.0 schema compliance
- Dead-letter queue for failed events
- Automatic retry with exponential backoff

**Splunk Sourcetypes:**
- `corvus:events` - Operational events
- `corvus:incidents` - Incident records
- `corvus:changes` - Change windows
- `corvus:gaps` - Gap detection findings

### GitHub Integration (Customer Zero)

When `GITHUB_TOKEN` and `GITHUB_REPO` are configured:

- Automatic issue creation for critical gaps
- Feedback loop to development pipeline
- Progress tracking via GitHub Issues
- Continuous improvement automation

**GitHub Token Scopes Required:**
- `repo` - Full repository control
- `workflow` - Update GitHub Actions

---

## Security Considerations

### API Keys

- `CORVUS_API_KEYS` stored in 1Password
- Never committed to git
- Rotate periodically

### Database Access

- Neo4j password stored in 1Password
- Internal network only (no public exposure)
- Authentication required for all queries

### SIEM Tokens

- Splunk HEC token stored in 1Password
- Never logged or printed
- Regenerate if compromised

### Network Access

| Port | Protocol | Access | Purpose |
|------|----------|--------|---------|
| 9420 | HTTP | Internal | Corvus API |
| 7474 | HTTP | Internal | Neo4j Browser |
| 7687 | Bolt | Internal | Neo4j Driver |

**All ports internal only — no public exposure.**

---

## Upgrade Path

### Version History

- **v1.0.0** (2026-04-26): Initial Customer Zero deployment with flywheel
- **v0.9.0**: Base Corvus platform
- **v0.8.0**: Gap detection and sweep operations
- **v0.7.0**: FMEA runbook engine
- **v0.6.0**: CMDB and service registry

### Upgrade Procedure

```bash
# 1. Check current version
ssh tmiller@192.168.20.14 "sudo docker exec corvus cat /data/VERSION 2>/dev/null || echo 'unknown'"

# 2. Pull latest image via GitOps (merge PR in homelab-automation)
cd /Users/tmiller/git/homelab-automation
git pull origin main

# 3. Verify deployment automatically triggered
# Check: https://github.com/tmt-homelab/homelab-automation/actions

# 4. Verify new version
ssh tmiller@192.168.20.14 "sudo docker exec corvus cat /data/VERSION"
```

---

## Support & Documentation

### Internal Documentation

- **Full Documentation**: `https://corvus.themillertribe-int.org/docs`
- **API Reference**: `https://corvus.themillertribe-int.org/docs/api`
- **Runbooks**: `github.com/overlabbed-com/corvus/corvus-server/runbooks/`
- **Knowledge Base**: `knowledge_search("corvus")`

### External Resources

- **Upstream Repo**: `github.com/overlabbed-com/corvus`
- **OCSF Spec**: `https://github.com/ocsf/ocsf-schema`
- **FMEA Guide**: `docs/fmea-triage.md`

### Incident Response

If Corvus itself becomes unhealthy:

1. **Check container status**: `sudo docker ps --filter name=corvus`
2. **View logs**: `sudo docker logs corvus --tail 100`
3. **Restart**: `sudo docker restart corvus`
4. **Escalate**: Create incident in Corvus (if still accessible)
5. **Fallback**: Use 1Password Connect directly on dockp04

---

## Success Criteria Reference

The Customer Zero flywheel tracks these 7 success criteria:

| Criteria | Target | Current | Weight |
|----------|--------|---------|--------|
| Zero Critical Vulnerabilities | 0 | (tracked) | 2.0 |
| SIEM Delivery Rate | 99.9% | (tracked) | 1.5 |
| Test Coverage | 85% | (tracked) | 1.0 |
| Mean Time To Resolution | 60 min | (tracked) | 1.5 |
| Gap Closure Rate | 90% | (tracked) | 1.0 |
| System Uptime | 99.9% | (tracked) | 2.0 |
| Feedback Loop Latency | 24h | (tracked) | 1.0 |

**Overall Score**: Weighted average of all criteria (0-100)

**Check Status**: `curl http://192.168.20.14:9420/ops/success-criteria/status | jq`

---

**Last Updated**: 2026-04-26  
**Status**: Production Ready ✅  
**Customer Zero**: Fully Operational 🎉
