# Story 6.1: Homelab Deployment Guide

## Phase 6: Customer Zero Deployment

### Prerequisites
- Docker host: dockp04 (192.168.20.14)
- GitOps repo: `homelab-automation`
- 1Password Connect configured

### Steps

1. **Clone homelab-automation repo**
```bash
gh repo clone tmt-homelab/homelab-automation
cd homelab-automation
git checkout -b feature/phase6-corvus-deploy
```

2. **Update Corvus stack**
Edit `stacks/dockp04-corvus/docker-compose.yml`:
```yaml
services:
  corvus:
    image: ghcr.io/overlabbed-com/corvus:latest
    environment:
      - CORVUS_SIEM_URL=${CORVUS_SIEM_URL}
      - CORVUS_SIEM_TOKEN=${CORVUS_SIEM_TOKEN}
      - GITHUB_TOKEN=${GITHUB_TOKEN}  # For feedback loop
      - GITHUB_REPO=overlabbed-com/corvus
```

3. **Add secrets to 1Password**
```bash
# Create new item in Homelab vault
op item create "Corvus Secrets" --vault Homelab \
  --field "CORVUS_SIEM_URL=https://ingest.hisplunk.com" \
  --field "CORVUS_SIEM_TOKEN=hec-token-here" \
  --field "GITHUB_TOKEN=ghp_xxx"
```

4. **Update deploy workflow**
Edit `.github/workflows/deploy-dockp04-corvus.yml` to include new secrets.

5. **Commit and push**
```bash
git add stacks/dockp04-corvus/
git commit -m "feat: deploy Corvus with Phase 1-5 fixes"
git push -u origin feature/phase6-corvus-deploy
gh pr create --title "Deploy Corvus Phase 1-5" --body "..."
```

6. **Monitor deployment**
```bash
# Watch CI/CD
gh run watch

# Check container health
ssh tmiller@192.168.20.14 "docker ps | grep corvus"
ssh tmiller@192.168.20.14 "docker logs corvus --tail 50"
```

7. **Verify functionality**
```bash
# Test health endpoint
curl -s https://corvus.themillertribe-int.org/health | jq

# Test metrics endpoint
curl -s https://corvus.themillertribe-int.org/metrics | head -20

# Verify event forwarding
curl -s https://corvus.themillertribe-int.org/ops/events/dead-letter
```

### Success Criteria
- [ ] Container running and healthy
- [ ] Health endpoint responding
- [ ] Metrics endpoint accessible
- [ ] Events flowing to Splunk
- [ ] Feedback loop creating GitHub issues (if gaps exist)

---

**Status**: Ready for deployment once PR #25 is merged
