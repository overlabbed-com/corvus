"""Module loader — discovers, validates, and activates Corvus modules.

Modules are directories under `modules/` containing a `module.yaml` manifest.
Each module can register:
- API endpoints (FastAPI routers)
- Event hooks (pre/post processing of operational events)
- Scheduled tasks (background loops)
- Metrics contributions (dashboard widgets)
- MCP tools (exposed via the MCP endpoint)

Module lifecycle: discover → validate → load → register → activate
"""

import importlib
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

logger = logging.getLogger(__name__)


@dataclass
class ModuleManifest:
    """Parsed module.yaml manifest."""

    name: str
    version: str
    type: str  # governance, compliance, integration
    description: str = ""
    author: str = ""
    entry_point: str = "module"  # Python module name within the directory
    dependencies: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadedModule:
    """A fully loaded and registered module."""

    manifest: ModuleManifest
    path: Path
    router: APIRouter | None = None
    event_hooks: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[Callable[[], Coroutine]] = field(default_factory=list)
    metrics_fn: Callable[[], Coroutine] | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    active: bool = False


class ModuleRegistry:
    """Central registry for all loaded modules."""

    def __init__(self):
        self._modules: dict[str, LoadedModule] = {}

    @property
    def modules(self) -> dict[str, LoadedModule]:
        return self._modules

    def get(self, name: str) -> LoadedModule | None:
        return self._modules.get(name)

    def list_all(self) -> list[LoadedModule]:
        return list(self._modules.values())

    def list_active(self) -> list[LoadedModule]:
        return [m for m in self._modules.values() if m.active]

    def register(self, module: LoadedModule) -> None:
        """Register a loaded module."""
        self._modules[module.manifest.name] = module
        logger.info(
            "Module registered: %s v%s (%s)",
            module.manifest.name,
            module.manifest.version,
            module.manifest.type,
        )


# Global registry
registry = ModuleRegistry()


def _parse_manifest(manifest_path: Path) -> ModuleManifest | None:
    """Parse a module.yaml manifest file."""
    try:
        with open(manifest_path) as f:
            data = yaml.safe_load(f) or {}

        required = ["name", "version", "type"]
        for key in required:
            if key not in data:
                logger.warning("Module manifest %s missing required field: %s", manifest_path, key)
                return None

        return ModuleManifest(
            name=data["name"],
            version=data["version"],
            type=data["type"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", "module"),
            dependencies=data.get("dependencies", []),
            config_schema=data.get("config_schema", {}),
        )
    except Exception as e:
        logger.error("Failed to parse module manifest %s: %s", manifest_path, e)
        return None


def _load_module_code(module_dir: Path, manifest: ModuleManifest) -> LoadedModule | None:
    """Import the module's Python code and extract registrations."""
    entry_file = module_dir / f"{manifest.entry_point}.py"
    if not entry_file.exists():
        logger.warning("Module %s: entry point %s.py not found", manifest.name, manifest.entry_point)
        return None

    try:
        # Import the module dynamically
        import sys

        module_parent = str(module_dir.parent)
        if module_parent not in sys.path:
            sys.path.insert(0, module_parent)

        spec = importlib.util.spec_from_file_location(
            f"corvus_module_{manifest.name}",
            entry_file,
        )
        if spec is None or spec.loader is None:
            logger.error("Module %s: could not create import spec", manifest.name)
            return None

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        loaded = LoadedModule(manifest=manifest, path=module_dir)

        # Extract registrations from the module
        if hasattr(mod, "router"):
            loaded.router = mod.router

        if hasattr(mod, "event_hooks"):
            loaded.event_hooks = mod.event_hooks

        if hasattr(mod, "background_tasks"):
            loaded.tasks = mod.background_tasks

        if hasattr(mod, "get_metrics"):
            loaded.metrics_fn = mod.get_metrics

        if hasattr(mod, "mcp_tools"):
            loaded.tools = mod.mcp_tools

        return loaded
    except Exception as e:
        logger.error("Module %s: failed to load: %s", manifest.name, e)
        return None


def discover_modules(modules_dir: Path) -> list[Path]:
    """Find all module directories containing module.yaml."""
    if not modules_dir.exists():
        return []

    found = []
    for child in sorted(modules_dir.iterdir()):
        if child.is_dir() and (child / "module.yaml").exists():
            found.append(child)
    return found


def load_modules(modules_dir: Path) -> int:
    """Discover, load, and register all modules from a directory.

    Returns the number of successfully loaded modules.
    """
    module_dirs = discover_modules(modules_dir)
    loaded_count = 0

    for module_dir in module_dirs:
        manifest_path = module_dir / "module.yaml"
        manifest = _parse_manifest(manifest_path)
        if not manifest:
            continue

        # Check dependencies
        missing_deps = [d for d in manifest.dependencies if d not in registry.modules]
        if missing_deps:
            logger.warning(
                "Module %s: missing dependencies %s — skipping",
                manifest.name,
                missing_deps,
            )
            continue

        loaded = _load_module_code(module_dir, manifest)
        if loaded:
            loaded.active = True
            registry.register(loaded)
            loaded_count += 1

    return loaded_count


def register_module_routers(app: Any) -> int:
    """Register all module routers with the FastAPI app.

    Returns number of routers registered.
    """
    count = 0
    for module in registry.list_active():
        if module.router:
            prefix = f"/ops/modules/{module.manifest.name}"
            app.include_router(module.router, prefix=prefix, tags=[f"module:{module.manifest.name}"])
            logger.info("Module %s: router registered at %s", module.manifest.name, prefix)
            count += 1
    return count
