"""One place for every value the system runs on.

Baseline: settings from .env (or their defaults) and the reference documents in data/registry (rules, PII terms,
apps, prompts). Override: a row in config_overrides, set through the admin API, wins over the baseline.
Every change is validated before it is used, applied live by bumping the config version (every cache keyed on it
rebuilds on next use, no restart), and recorded in config_changes. Settings live in this process: run one worker,
or restart the others after a change.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import registry
from app.common.config import ADMIN_EDITABLE, Settings, bump_config_version, settings
from app.platform.admin.models import ConfigChange, ConfigOverride

logger = logging.getLogger("app.runtime_config")

SETTING, DOCUMENT = "setting", "document"
DOCUMENT_FILES = registry.documents  # admin name -> file; each owner registers its own with register_document()
SECRET_SETTINGS = frozenset({"ADMIN_API_KEY", "ANTHROPIC_API_KEY"})  # never shown, only whether it is set
_baseline = settings.model_copy()  # .env and defaults, before any admin override


class ConfigError(ValueError):
    """The change was refused; nothing was applied."""


def _applied() -> None:
    """Make a change live: every cache keyed on the config version rebuilds on next use."""
    bump_config_version()
    logging.getLogger().setLevel(settings.LOG_LEVEL.upper())


def _check_document(name: str) -> None:
    """Build what reads the document, so a broken one is refused before any ticket meets it."""
    registry.check_document(name)


def _validated(key: str, value: Any) -> Any:
    if key not in ADMIN_EDITABLE:
        raise ConfigError(f"{key} cannot be changed through the admin API")
    try:
        candidate = Settings(**{**settings.model_dump(), key: value})  # runs every field and cross-field check
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return getattr(candidate, key)


def _save_change(db: Session, kind: str, key: str, old: Any, new: Any, by: str) -> None:
    """Store the override (new=None removes it) and append to the history, in one commit."""
    row = db.get(ConfigOverride, (kind, key))
    if new is None:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(ConfigOverride(kind=kind, key=key, value=new, claimed_by=by))
    else:
        row.value, row.claimed_by = new, by
    db.add(ConfigChange(kind=kind, key=key, old_value=old, new_value=new, claimed_by=by))
    db.commit()
    logger.info(f"config change: {kind} {key} by {by}")


# Settings

def list_settings(db: Session) -> list[dict[str, Any]]:
    overridden = set(db.scalars(select(ConfigOverride.key).where(ConfigOverride.kind == SETTING)))
    current, baseline = settings.model_dump(mode="json"), _baseline.model_dump(mode="json")
    return [
        {
            "key": key,
            "value": bool(value) if key in SECRET_SETTINGS else value,
            "baseline": bool(baseline[key]) if key in SECRET_SETTINGS else baseline[key],
            "overridden": key in overridden,
            "editable": key in ADMIN_EDITABLE,
        }
        for key, value in current.items()
    ]


def set_setting(db: Session, key: str, value: Any, by: str) -> Any:
    new = _validated(key, value)
    old = getattr(settings, key)
    _save_change(db, SETTING, key, old, new, by)
    setattr(settings, key, new)
    _applied()
    return new


def reset_setting(db: Session, key: str, by: str) -> Any:
    if db.get(ConfigOverride, (SETTING, key)) is None:
        raise LookupError(f"{key} has no admin override")
    old, new = getattr(settings, key), getattr(_baseline, key)
    _save_change(db, SETTING, key, old, None, by)
    setattr(settings, key, new)
    _applied()
    return new


# Reference documents

def _filename(name: str) -> str:
    if name not in DOCUMENT_FILES:
        raise LookupError(f"Unknown document {name}; one of {', '.join(DOCUMENT_FILES)}")
    return DOCUMENT_FILES[name]


def get_document(name: str) -> tuple[Any, bool]:
    filename = _filename(name)
    return registry.load_registry(filename), filename in registry.overrides


def _set_override(filename: str, document: Any) -> Any:
    """Put the admin document in place; returns the override it replaced (None if the file was in use)."""
    previous = registry.overrides.get(filename)
    registry.overrides[filename] = document
    _applied()
    return previous


def _clear_override(filename: str) -> Any:
    """Go back to the file; returns the override it removed (None if there was none)."""
    previous = registry.overrides.pop(filename, None)
    _applied()
    return previous


def _restore(filename: str, previous: Any) -> None:
    """Undo a refused change: put back exactly what was in use before it."""
    if previous is None:
        _clear_override(filename)
    else:
        _set_override(filename, previous)


def set_document(db: Session, name: str, document: Any, by: str) -> None:
    filename = _filename(name)
    old = registry.load_registry(filename)
    previous = _set_override(filename, document)
    try:
        _check_document(name)
        _save_change(db, DOCUMENT, name, old, document, by)
    except Exception as exc:
        _restore(filename, previous)
        raise ConfigError(f"{name} refused: {exc}") from exc


def reset_document(db: Session, name: str, by: str) -> None:
    filename = _filename(name)
    if filename not in registry.overrides:
        raise LookupError(f"{name} has no admin override")
    old = registry.load_registry(filename)
    previous = _clear_override(filename)
    try:
        _check_document(name)
        _save_change(db, DOCUMENT, name, old, None, by)
    except Exception as exc:
        _restore(filename, previous)
        raise ConfigError(f"{name}: the file in data/registry does not load: {exc}") from exc


# History and startup

def list_changes(db: Session, limit: int) -> list[ConfigChange]:
    return list(db.scalars(select(ConfigChange).order_by(ConfigChange.id.desc()).limit(limit)))


def apply_overrides(db: Session) -> None:
    """At startup: put every stored override in place. One that no longer validates is skipped and logged."""
    for row in db.scalars(select(ConfigOverride)):
        try:
            if row.kind == SETTING:
                setattr(settings, row.key, _validated(row.key, row.value))
            else:
                _set_override(_filename(row.key), row.value)
                _check_document(row.key)
        except Exception as exc:
            if row.kind == DOCUMENT and row.key in DOCUMENT_FILES:
                _clear_override(DOCUMENT_FILES[row.key])
            logger.warning(f"config override {row.kind} {row.key} skipped: {exc}")
    _applied()
