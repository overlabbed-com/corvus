# Corvus Phase 4 Deployment Plan — Dev Environment

**Target:** dockp04 (192.168.20.14)  
**Stack:** homelab-automation/stacks/dockp04-corvus  
**Date:** 2026-04-13

---

## Prerequisites

### 1. Access Requirements
- SSH access to dockp04 as `tmiller`
- Docker access (sudo) on dockp04
- 1Password Connect access for secrets
- GitHub PAT for cloning tmt-homelab repo

### 2. Local State
- ✅ Corvus Phase 4 merged to main (commit: 33491ed)
- ✅ All tests passing (67+ tests)
- ✅ Docker build context ready in `/Users/tmiller/git/overlabbed-com/corvus/corvus-server`

### 3. Dev Environment State
- Current Corvus deployment on dockp04
- Neo4j running for graph features
- infra-services network available

---

## Deployment Steps

### Phase 1: Prepare Local Build Context

```bash
cd /Users/tmiller/git/overlabbed-com/corvus

# Verify latest commit
git log --oneline -1
# Expected: 33491ed feat(phase4.4-4.6): complete remaining phases

# Check build context
ls -la corvus-server/
# Should contain: src/, tests/, Dockerfile, requirements.txt
```

**Status:** ✅ Ready

---

### Phase 2: Update GitOps Stack Definition

```bash
cd /Users/tmiller/git/tmt-homelab/homelab-automation

# Create feature branch
git checkout -b feature/corvus-phase4-deploy

# Review current stack
cat stacks/dockp04-corvus/docker-compose.yml

# Check for any needed changes
# - Verify build context path: /opt/corvus/corvus-server
# - Verify environment variables
# - Verify Neo4j configuration
```

**Expected Changes:** None (Phase 4 is backward compatible)

---

### Phase 3: Copy Code to dockp04

```bash
# Create directory on dockp04
ssh tmiller@192.168.20.14 "sudo mkdir -p /opt/corvus"

# Copy corvus-server code
rsync -avz --progress \
  /Users/tmiller/git/overlabbed-com/corvus/corvus-server/ \
  tmiller@192.168.20.14:/opt/corvus/corvus-server/

# Verify copy
ssh tmiller@192.168.20.14 "ls -la /opt/corvus/corvus-server/"
# Should show: src/, tests/, Dockerfile, requirements.txt, etc.

# Set proper ownership
ssh tmiller@192.168.20.14 "sudo chown -R tmiller:docker /opt/corvus/corvus-server"
```

**Estimated Time:** 2-3 minutes  
**Files:** ~500 files, ~100MB

---

### Phase 4: Build Docker Image on dockp04

```bash
ssh tmiller@192.168.20.14 << 'SSH_EOF'
cd /opt/corvus/corvus-server

# Clean previous builds
sudo docker rmi corvus-server:latest 2>/dev/null || true

# Build new image
sudo docker build -t corvus-server:latest .

# Verify build
sudo docker images | grep corvus-server
# Expected: corvus-server latest with recent timestamp

# Check image size
sudo docker images corvus-server --format "table {{.Size}}"
# Expected: ~500MB-1GB (Python + dependencies)
SSH_EOF
```

**Estimated Time:** 5-10 minutes  
**Output:** New Docker image with Phase 4 features

---

### Phase 5: Verify Environment Variables

```bash
# Check current .env on dockp04
ssh tmiller@192.168.20.14 "cat /mnt/docker/stacks/dockp04-corvus/.env 2>/dev/null || echo 'No .env found'"

# Check template
cat /Users/tmiller/git/tmt-homelab/homelab-automation/stacks/dockp04-corvus/.env.template

# Verify required variables:
# - CORVUS_API_KEYS (from 1Password)
# - NEO4J_PASSWORD (from 1Password)
# - CORVUS_SIEM_URL (optional)
# - CORVUS_SIEM_TOKEN (optional)
# - CORVUS_LLM_URL (optional)
```

**Expected:** All required variables present

---

### Phase 6: Deploy with Docker Compose

```bash
# Option A: GitOps workflow (recommended)
cd /Users/tmiller/git/tmt-homelab/homelab-automation
git add stacks/dockp04-corvus/
git commit -m "deploy: Corvus Phase 4 with drift detection and graph triage"
git push origin feature/corvus-phase4-deploy

# Create PR and merge (triggers GitHub Actions)
gh pr create --title "deploy: Corvus Phase 4" --body "Phase 4 features: correlation, CI model, deploy triage, drift detection, pattern quality, graph triage"
# Wait for CI to merge and deploy

# Option B: Manual deploy (faster for testing)
ssh tmiller@192.168.20.14 << 'SSH_EOF'
cd /mnt/docker/stacks/dockp04-corvus

# Pull latest compose if needed
sudo docker compose pull

# Stop old containers
sudo docker compose down

# Start new containers
sudo docker compose up -d

# Wait for health checks
sleep 30

# Verify status
sudo docker ps | grep corvus
SSH_EOF
```

**Estimated Time:** 5-15 minutes (depending on GitOps vs manual)

---

### Phase 7: Verify Deployment

```bash
# Check container health
ssh tmiller@192.168.20.14 << 'SSH_EOF'
# Corvus service
sudo docker inspect corvus --format '{{.State.Health.Status}}'

# Neo4j service
sudo docker inspect corvus-neo4j --format '{{.State.Health.Status}}'

# View logs (last 50 lines)
sudo docker logs corvus --tail 50
SSH_EOF

# Expected output:
# - corvus: healthy
# - corvus-neo4j: healthy
```

---

### Phase 8: Functional Testing

#### Test 1: Health Check
```bash
curl -s http://192.168.20.14:9420/health | jq .
# Expected: {"status": "healthy", "graph": true, ...}
```

#### Test 2: Correlation Groups (Phase 4.1)
```bash
# Create test incidents
curl -X POST http://192.168.20.14:9420/ops/incidents \
  -H "Content-Type: application/json" \
  -d '{"title": "Test GPU failure 1", "target": "vllm-inference", "severity": "critical", "source": "test"}'

curl -X POST http://192.168.20.14:9420/ops/incidents \
  -H "Content-Type: application/json" \
  -d '{"title": "Test GPU failure 2", "target": "litellm", "severity": "critical", "source": "test"}'

# Check correlation
curl -X POST http://192.168.20.14:9420/ops/correlations/check \
  -H "Content-Type: application/json" \
  -d '{"incidents": ["INC-XXX", "INC-YYY"]}'
```

#### Test 3: CI Model (Phase 4.2)
```bash
# Register a CI
curl -X POST http://192.168.20.14:9420/ops/cmdb/ci \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-cert-2026",
    "ci_type": "cert",
    "service_name": "caddy",
    "expires_at": "2026-10-15T00:00:00Z",
    "metadata": {"issuer": "Let's Encrypt"}
  }'

# Query expiring CIs
curl http://192.168.20.14:9420/ops/cmdb/ci/expiring?days=30 | jq .
```

#### Test 4: Deploy Triage (Phase 4.3)
```bash
# Analyze deploy failure
curl -X POST http://192.168.20.14:9420/ops/discovery/deploy/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "service": "test-service",
    "error": "Container OOMKilled"
  }'

# Expected: diagnosis: resource_exhaustion, confidence: 0.9
```

#### Test 5: Drift Detection (Phase 4.4)
```bash
# Register declared state
curl -X POST http://192.168.20.14:9420/ops/cmdb/test-service/declared \
  -H "Content-Type: application/json" \
  -d '{
    "image": "myapp:v1.2.3",
    "healthcheck": "curl health",
    "env_hash": "abc123"
  }'

# Check drift
curl http://192.168.20.14:9420/ops/cmdb/test-service/drift | jq .
```

#### Test 6: Pattern Quality (Phase 4.5)
```bash
# List patterns
curl http://192.168.20.14:9420/ops/patterns | jq .

# Get top patterns
curl http://192.168.20.14:9420/ops/patterns/top-10 | jq .

# Submit feedback
curl -X POST http://192.168.20.14:9420/ops/patterns/PATTERN_ID/feedback \
  -H "Content-Type: application/json" \
  -d '{"success": true, "resolution_time_minutes": 15}'
```

#### Test 7: Graph Triage (Phase 4.6)
```bash
# Triage with graph context
curl -X POST http://192.168.20.14:9420/ops/triage/with-graph \
  -H "Content-Type: application/json" \
  -d '{
    "service": "vllm-inference",
    "incident_title": "Service failing"
  }'

# Root cause analysis
curl -X POST http://192.168.20.14:9420/ops/triage/root-cause-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "service_name": "vllm-inference",
    "affected_services": ["litellm", "open-webui"]
  }'
```

---

## Rollback Plan

If deployment fails:

```bash
ssh tmiller@192.168.20.14 << 'SSH_EOF'
cd /mnt/docker/stacks/dockp04-corvus

# Stop new containers
sudo docker compose down

# Rebuild from previous tag
sudo docker build -t corvus-server:previous /opt/corvus/corvus-server

# Restore previous image
sudo docker tag corvus-server:previous corvus-server:latest

# Restart
sudo docker compose up -d
SSH_EOF
```

---

## Success Criteria

- ✅ All containers healthy
- ✅ All 7 functional tests pass
- ✅ Neo4j graph queries working
- ✅ No error logs in last 5 minutes
- ✅ API response times < 500ms

---

## Estimated Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| 1. Local prep | 1 min | Already done |
| 2. GitOps update | 2 min | Review only |
| 3. Copy code | 3 min | rsync |
| 4. Build image | 5-10 min | Docker build |
| 5. Verify env | 2 min | Check .env |
| 6. Deploy | 5-15 min | GitOps or manual |
| 7. Verify | 3 min | Health checks |
| 8. Testing | 15 min | 7 test suites |
| **Total** | **36-41 min** | |

---

## Post-Deployment

1. Update PR description with deployment status
2. Notify team: "Corvus Phase 4 deployed to dev"
3. Schedule demo of new features
4. Plan production deployment after validation
5. Document any issues encountered

---

**Ready to execute?** Run the deployment steps in order, or let me know if you want me to execute them via SSH.
