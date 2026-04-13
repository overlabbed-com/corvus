#!/bin/bash
# Parallel deployment script for Corvus Phase 4
# Runs independent tasks concurrently

set -e

echo "🚀 Starting parallel deployment..."

# Task 1: Copy code to dockp04
echo "📦 Task 1: Copying code to dockp04..."
rsync -avz --progress \
  /Users/tmiller/git/overlabbed-com/corvus/corvus-server/ \
  tmiller@192.168.20.14:/opt/corvus/corvus-server/ &
TASK1_PID=$!

# Task 2: Review GitOps stack
echo "📋 Task 2: Reviewing GitOps stack..."
cd /Users/tmiller/git/tmt-homelab/homelab-automation
git checkout -b feature/corvus-phase4-deploy 2>/dev/null || true
cat stacks/dockp04-corvus/docker-compose.yml > /tmp/compose-review.txt &
TASK2_PID=$!

# Task 3: Prepare test scripts
echo "🧪 Task 3: Preparing functional test scripts..."
cat > /tmp/corvus-tests.sh << 'TESTEOF'
#!/bin/bash
CORVUS_URL="http://192.168.20.14:9420"

echo "=== Test 1: Health Check ==="
curl -s "$CORVUS_URL/health" | jq .

echo "=== Test 2: Create Test Incidents ==="
INC1=$(curl -s -X POST "$CORVUS_URL/ops/incidents" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test GPU failure 1", "target": "vllm-inference", "severity": "critical", "source": "test"}')
echo "$INC1" | jq .

INC2=$(curl -s -X POST "$CORVUS_URL/ops/incidents" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test GPU failure 2", "target": "litellm", "severity": "critical", "source": "test"}')
echo "$INC2" | jq .

echo "=== Test 3: CI Model ==="
curl -s -X POST "$CORVUS_URL/ops/cmdb/ci" \
  -H "Content-Type: application/json" \
  -d '{"name": "test-cert-2026", "ci_type": "cert", "service_name": "caddy", "expires_at": "2026-10-15T00:00:00Z"}' | jq .

echo "=== Test 4: Deploy Triage ==="
curl -s -X POST "$CORVUS_URL/ops/discovery/deploy/analyze" \
  -H "Content-Type: application/json" \
  -d '{"service": "test-service", "error": "Container OOMKilled"}' | jq .

echo "=== Test 5: Pattern Quality ==="
curl -s "$CORVUS_URL/ops/patterns" | jq .

echo "=== All tests complete ==="
TESTEOF
chmod +x /tmp/corvus-tests.sh &
TASK3_PID=$!

# Wait for all tasks
wait $TASK1_PID
wait $TASK2_PID
wait $TASK3_PID

echo "✅ All parallel tasks complete!"
echo ""
echo "Next steps:"
echo "1. ssh tmiller@192.168.20.14 'sudo chown -R tmiller:docker /opt/corvus/corvus-server'"
echo "2. ssh tmiller@192.168.20.14 'cd /opt/corvus/corvus-server && sudo docker build -t corvus-server:latest .'"
echo "3. ssh tmiller@192.168.20.14 'cd /mnt/docker/stacks/dockp04-corvus && sudo docker compose up -d'"
echo "4. /tmp/corvus-tests.sh"
