"""Read the editable reference documents in data/registry.

A file is the baseline; an admin override (set by app.platform.admin.runtime_config) replaces the whole document.
Each owner registers its documents here (shared ones in common/, the rest in each agent), so the admin API can list,
change and check them without knowing any agent.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import yaml

from app.common.config import config_version, settings

overrides: dict[str, Any] = {}  # filename -> document; filled from the database at startup and on every admin change
documents: dict[str, str] = {}  # admin name -> file under data/registry
_checks: dict[str, list[Callable[[], object]]] = {}  # admin name -> what to build to prove the document works


def register_document(name: str, filename: str, check: Callable[[], object]) -> None:
    """Make a document editable through the admin API. `check` builds whatever reads it and raises if it is broken."""
    documents[name] = filename
    _checks.setdefault(name, []).append(check)


def check_document(name: str) -> None:
    for check in _checks.get(name, []):
        check()


def read_file(filename: str) -> Any:
    return yaml.safe_load((settings.REGISTRY_DIR / filename).read_text(encoding="utf-8"))


def load_registry(filename: str) -> Any:
    return _load(filename, config_version())


@lru_cache(maxsize=16)
def _load(filename: str, version: int) -> Any:
    return overrides[filename] if filename in overrides else read_file(filename)
