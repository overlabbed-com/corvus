"""Agent instructions endpoint — dynamic markdown for LLM consumption.

Returns a structured document that any LLM can read to understand
how to use the Corvus API. Generated from the live OpenAPI spec
so it's always up-to-date.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["agent-instructions"])

PREAMBLE = """# Corvus — Operational Governance API

You are interacting with Corvus, an operational governance platform for AI agent fleets.
Corvus tracks changes, incidents, events, problems, service baselines, and dependency graphs.

## Base URL

Use the base URL provided in your configuration. All endpoints require
`Authorization: Bearer <token>` header.

## Core Concepts

- **Change Window**: Declare before modifying infrastructure. Suppresses alerts for affected targets.
- **Event**: Any operational occurrence (change started, incident opened, remediation applied).
- **Incident**: An active problem being investigated or resolved.
- **Problem**: A recurring pattern of incidents (auto-correlated at 3+ incidents).
- **CMDB**: Configuration Management Database — all known services with type, host, dependencies.
- **Baseline**: Expected behavior for a service (e.g., "certbot restarts daily = normal").
- **Triage**: Runbook-driven diagnosis of an incident (sync or async).
- **Trust Ledger**: Tracks action success rates to determine automation autonomy levels.

## Workflows

### Before Modifying Infrastructure
1. `POST /ops/events/targets/{target}/status` — check for conflicts (GO/CAUTION/STOP)
2. `POST /ops/changes` — declare a change window with targets and rollback plan
3. Make changes
4. `POST /ops/events` — emit completion event
5. `PATCH /ops/changes/{id}` — close the change window

### Investigating an Incident
1. `POST /ops/incidents` — create incident record
2. `POST /ops/runbooks/steps/triage/async` — start async triage (get investigation steps)
3. Execute each pending step and `POST /ops/runbooks/steps/{step_id}/result`
4. `POST /ops/runbooks/steps/triage/{triage_id}/continue` — get diagnosis
5. Apply remediation
6. `POST /ops/events` — emit resolution event

### Session Start
1. `GET /ops/events/context` — get 24h briefing (events, incidents, changes, gaps)

"""


def _generate_endpoint_docs(openapi_schema: dict) -> str:
    """Generate endpoint documentation from OpenAPI schema."""
    lines = ["## API Endpoints\n"]

    # Group by tag
    tag_groups: dict[str, list[str]] = {}
    for path, methods in sorted(openapi_schema.get("paths", {}).items()):
        for method, spec in methods.items():
            if method in ("options", "head"):
                continue
            tags = spec.get("tags", ["other"])
            tag = tags[0] if tags else "other"
            if tag not in tag_groups:
                tag_groups[tag] = []

            summary = spec.get("summary", spec.get("description", ""))
            if summary:
                summary = summary.split("\n")[0][:100]

            params_doc = ""
            params = spec.get("parameters", [])
            if params:
                param_parts = []
                for p in params:
                    name = p.get("name", "?")
                    p_type = p.get("schema", {}).get("type", "string")
                    required = p.get("required", False)
                    desc = p.get("description", "")
                    marker = " (required)" if required else ""
                    param_parts.append(f"  - `{name}` ({p_type}{marker}): {desc}")
                params_doc = "\n" + "\n".join(param_parts)

            body_doc = ""
            request_body = spec.get("requestBody", {})
            if request_body:
                content = request_body.get("content", {})
                json_schema = content.get("application/json", {}).get("schema", {})
                if "$ref" in json_schema:
                    ref_name = json_schema["$ref"].split("/")[-1]
                    schemas = openapi_schema.get("components", {}).get("schemas", {})
                    ref_schema = schemas.get(ref_name, {})
                    props = ref_schema.get("properties", {})
                    required_fields = ref_schema.get("required", [])
                    if props:
                        body_parts = []
                        for prop_name, prop_spec in props.items():
                            p_type = prop_spec.get("type", "any")
                            desc = prop_spec.get("description", "")
                            req = " (required)" if prop_name in required_fields else ""
                            body_parts.append(f"  - `{prop_name}` ({p_type}{req}): {desc}")
                        body_doc = "\n  Body:\n" + "\n".join(body_parts)

            entry = f"### `{method.upper()} {path}`\n{summary}{params_doc}{body_doc}\n"
            tag_groups[tag].append(entry)

    for tag in sorted(tag_groups.keys()):
        lines.append(f"### {tag.title()}\n")
        for entry in tag_groups[tag]:
            lines.append(entry)

    return "\n".join(lines)


@router.get("/agent-instructions", response_class=PlainTextResponse)
async def get_agent_instructions():
    """Dynamic markdown instructions for LLM agents.

    Returns a human/LLM-readable document describing all Corvus API
    endpoints, workflows, and concepts. Generated from the live OpenAPI spec.
    """
    from src.app import app

    schema = app.openapi()
    endpoint_docs = _generate_endpoint_docs(schema)

    return PREAMBLE + endpoint_docs
