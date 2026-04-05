# Corvus CLI

Command-line interface for the Corvus operational governance API.

## Install

```bash
pip install typer httpx pyyaml
```

## Configure

Set environment variables:
```bash
export CORVUS_URL=http://corvus:8000
export CORVUS_TOKEN=your-api-token
```

Or create `~/.corvus.yaml`:
```yaml
url: http://corvus:8000
token: your-api-token
```

## Usage

```bash
# Pre-action check
python cli/corvus_cli.py status caddy

# Session briefing
python cli/corvus_cli.py context

# Blast radius analysis
python cli/corvus_cli.py blast-radius postgresql

# Dependency chain
python cli/corvus_cli.py deps litellm

# Operational metrics
python cli/corvus_cli.py metrics

# Incident management
python cli/corvus_cli.py incidents list
python cli/corvus_cli.py incidents create --target caddy --title "502 errors"

# Change windows
python cli/corvus_cli.py changes create --targets "vllm,litellm" --description "Model swap"
python cli/corvus_cli.py changes close CHG-12345

# Events
python cli/corvus_cli.py events emit --type change.completed --target vllm
python cli/corvus_cli.py events watch --severity warning

# CMDB
python cli/corvus_cli.py cmdb list --type inference
python cli/corvus_cli.py cmdb get caddy

# Trust ledger
python cli/corvus_cli.py trust list

# Gap detection
python cli/corvus_cli.py gaps

# Config drift
python cli/corvus_cli.py drift

# Connection collection
python cli/corvus_cli.py collect

# Agent instructions
python cli/corvus_cli.py instructions
```

## Alias

Add to your shell profile:
```bash
alias corvus='python /path/to/corvus-server/cli/corvus_cli.py'
```
