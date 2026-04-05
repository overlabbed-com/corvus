# Runbook Format

Corvus runbooks are YAML files that define FMEA-informed triage procedures.
Each runbook targets a service type and contains investigation steps,
diagnosis hints, and remediation guardrails.

## Structure

```yaml
name: Inference Service Triage
type: triage
service_type: inference
version: 1
description: FMEA-informed investigation for GPU inference engines

investigation:
  - name: Check GPU state
    type: gpu.nvidia_smi
    params:
      host: "{{ host }}"
    outputs:
      gpu_state: "{{ result }}"
    timeout: 10

diagnosis_hints:
  - pattern: "cuda_oom|out of memory"
    root_cause: gpu_oom
    restart_safe: false
    explanation: "CUDA OOM — check VRAM allocation"

remediation:
  restart_safe: conditional
  pre_restart_checks:
    - "gpu_state.vram_available > 1024"
  post_restart_verification:
    - type: http.check
      params:
        url: "http://{{ target }}:8000/health"
        timeout: 300
        expect_status: 200
  escalation_triggers:
    - "nccl error"
    - "NFS mount missing"
```

## Investigation Step Types

| Type | Description | Execution |
|------|------------|-----------|
| `gpu.nvidia_smi` | Parse nvidia-smi output | Agent-side |
| `containers.logs` | Read and grep container logs (see `spec/investigation.md` for standards) | Agent-side |
| `containers.inspect` | Get container metadata including exit code | Agent-side |
| `containers.drift_check` | Compare running config against CMDB declared state | Agent-side |
| `host.check` | Named host checks (disk, NFS, memory) | Agent-side |
| `http.check` | HTTP health check with timeout | Server-side |
| `mqtt.check` | MQTT broker connectivity | Agent-side |
| `deploy.workflow_logs` | Pull CI/CD workflow logs and parse failure details | Agent-side |

Steps marked "Agent-side" return a structured placeholder — the calling
agent (NemoClaw, etc.) executes the actual check and passes results back
via `investigation_data`.

## Diagnosis Matching

Diagnosis hints use regex patterns matched against combined investigation
output. First match wins. If no hint matches, diagnosis is `unknown` with
low confidence, and a `gap:accuracy:unclassifiable` problem is generated.

## API

### Execute Triage
```
POST /ops/runbooks/triage
```
```json
{
  "target": "vllm-primary",
  "host": "tmtdockp01",
  "service_type": "inference",
  "investigation_data": {
    "logs": "CUDA error: out of memory on device 0"
  }
}
```

### List Runbooks
```
GET /ops/runbooks
```

### Coverage Report
```
GET /ops/runbooks/coverage
```

## Shipped Runbooks

Corvus ships with 12 FMEA runbooks covering all service types:

| Runbook | Service Type | Key Failure Modes |
|---------|-------------|------------------|
| triage-inference | inference | CUDA OOM, NCCL, NFS, model loading |
| triage-database | database | Disk full, connections, corruption, deadlocks |
| triage-proxy | proxy | TLS, config, upstream, port conflicts |
| triage-mcp-bridge | mcp_bridge | Upstream down, auth expired, Python crashes |
| triage-secrets | secrets | Sync failure, credential corruption |
| triage-iot-gateway | iot_gateway | Coordinator, MQTT, device flood |
| triage-home-automation | home_automation | Network, MQTT, HomeKit, integrations |
| triage-media | media | DB locked, disk full, streaming, indexers |
| triage-monitoring | monitoring | Provisioning loop, auth, collectors |
| triage-automation | automation | DB connection, workers, flows |
| triage-dns | dns | Resolver, zone transfer, records |
| triage-utility | utility | Tunnels, certs, GPU workloads, autoheal |
| triage-deploy | deploy | Stale config, slow startup, missing networks, disk full |
