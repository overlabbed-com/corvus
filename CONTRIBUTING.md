# Contributing to Corvus

Thanks for your interest in contributing to Corvus! This document covers
the basics of getting set up and submitting changes.

## Development Setup

```bash
cd corvus-server
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Running the Server

```bash
cd corvus-server
uvicorn src.app:app --reload --port 8000
```

## Running with Docker

```bash
docker build -t corvus corvus-server/
docker run -d -p 8000:8000 -v corvus-data:/data corvus
```

## Project Structure

```
corvus-server/
├── src/
│   ├── app.py              # FastAPI application entry point
│   ├── config.py           # Environment-based configuration
│   ├── database.py         # SQLite schema and connection management
│   ├── ocsf.py             # OCSF 1.3.0 event transformer
│   ├── mcp_server.py       # MCP server (12 tools for AI agents)
│   ├── middleware/          # Auth (RBAC) and audit logging
│   ├── models/             # Pydantic request/response models
│   ├── routers/            # FastAPI route handlers
│   ├── runbooks/           # YAML runbook loader and triage executor
│   ├── siem/               # Splunk HEC forwarder
│   └── tasks/              # Background tasks (expiry, gap detection)
├── runbooks/               # FMEA triage runbooks (12 YAML files)
├── tests/                  # Test suite
└── Dockerfile
```

## Writing Tests

Tests use pytest with pytest-asyncio. The test client uses httpx's ASGI transport
to test the FastAPI app directly without starting a server.

```python
@pytest.mark.asyncio
async def test_something(client):
    resp = await client.post("/ops/events", json={...})
    assert resp.status_code == 201
```

Run tests:
```bash
cd corvus-server
python -m pytest tests/ -v
```

## Adding a Runbook

1. Create a YAML file in `corvus-server/runbooks/`
2. Follow the format in `spec/runbooks.md`
3. Name it `triage-{service_type}.yaml`
4. Add tests in `tests/test_runbooks.py`

## Submitting Changes

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Ensure all tests pass
5. Submit a PR

## Code Style

- Python 3.11+
- Type hints everywhere
- No unnecessary abstractions
- Tests for all new functionality

## License

By contributing, you agree that your contributions will be licensed
under the Apache License 2.0.
