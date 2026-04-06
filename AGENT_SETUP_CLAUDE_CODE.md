# Setting Up Corvus MCP Server for Claude Code

This guide shows how to connect your Claude Code instances to Corvus for operational governance.

## Prerequisites

1. Corvus must be running and accessible
2. You need an API key from your Corvus administrator

## Step 1: Add Corvus MCP Server to Your Claude Code Config

Add this to your `~/.claude/settings.json` or project's `.claude/settings.json`:

```json
{
  "mcpServers": {
    "corvus": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-http"],
      "env": {
        "HTTP_URL": "http://corvus-host:9420/ops/mcp/sse",
        "HTTP_HEADERS": {
          "Authorization": "Bearer YOUR_API_KEY_HERE"
        }
      }
    }
  }
}
```

Replace:
- `corvus-host:9420` with your Corvus server address
- `YOUR_API_KEY_HERE` with your actual API key

## Step 2: Restart Claude Code

After saving the config, restart Claude Code to load the new MCP server.

## Step 3: Verify Connection

Ask Claude: "What Corvus tools are available?" - it should list all 15+ Corvus MCP tools.

## Available Corvus MCP Tools

Once connected, you have access to:

| Tool | Purpose |
|------|---------|
| `corvus_check_target` | Pre-action conflict check before infrastructure changes |
| `corvus_emit_event` | Emit operational events |
| `corvus_create_incident` | Create incident records |
| `corvus_create_change` | Declare change windows |
| `corvus_close_change` | Close change windows |
| `corvus_get_context` | Session briefing (last 24h events) |
| `corvus_watch_events` | Watch for other agent activity |
| `corvus_blast_radius` | Dependency impact analysis |
| `corvus_dependency_chain` | Upstream dependencies |
| `corvus_triage` | Execute runbook triage |
| `corvus_get_service` | CMDB service details |
| `corvus_list_services` | List registered services |
| `corvus_register_service` | Register new service |
| `corvus_correlated_gpu` | GPU incident correlation |
| `corvus_expiring_cis` | List expiring configuration items |

## Example Usage

```
Before restarting a service, always check:
"Check if it's safe to restart vllm-primary using corvus_check_target"

After making changes, emit an event:
"Emit a change.completed event for the vllm-primary deployment"

At session start, get context:
"Get me the Corvus context for the last 24 hours"
```

## Troubleshooting

### Connection Failed
- Verify Corvus is running: `curl http://corvus-host:9420/health`
- Check API key is correct
- Ensure HTTP_URL points to `/ops/mcp/sse`

### Tools Not Available
- Restart Claude Code after adding config
- Check Claude Code logs for MCP server errors
- Verify npx is available in your PATH

## Security Notes

- Never commit API keys to git
- Use `.env` files or secret managers for key storage
- Different agents should have different API keys with appropriate roles
- Rotate keys periodically
