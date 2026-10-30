"""Admin endpoints: view and change every setting and reference document (rules, PII terms, apps, prompts) at runtime.

Protected by the X-Admin-Key header, which must match ADMIN_API_KEY from the environment. With no key set,
every admin endpoint answers 503.
"""

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.common.config import settings
from app.db.session import get_db
from app.platform.admin import runtime_config
from app.platform.admin.runtime_config import ConfigError
from app.platform.admin.schemas import ChangeOut, DocumentIn, DocumentOut, SettingIn, SettingOut


def require_admin(x_admin_key: str | None = Header(None)) -> None:
    if not settings.ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="Admin API is switched off: set ADMIN_API_KEY in the environment")
    if not x_admin_key or not secrets.compare_digest(x_admin_key, settings.ADMIN_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or wrong X-Admin-Key")


def claimed_by(x_admin_user: str | None = Header(None)) -> str:
    """Who the caller says they are, recorded in the history. Not verified: the admin key is shared."""
    return x_admin_user or "admin"


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _setting(db: Session, key: str) -> SettingOut:
    for row in runtime_config.list_settings(db):
        if row["key"] == key:
            return SettingOut(**row)
    raise HTTPException(status_code=404, detail=f"Unknown setting {key}")


@router.get("/settings", response_model=list[SettingOut], summary="List every setting")
def list_settings(db: Session = Depends(get_db)) -> list[SettingOut]:
    return [SettingOut(**row) for row in runtime_config.list_settings(db)]


@router.put("/settings/{key}", response_model=SettingOut, summary="Change a setting now")
def put_setting(key: str, payload: SettingIn, db: Session = Depends(get_db), by: str = Depends(claimed_by)) -> SettingOut:
    _setting(db, key)  # 404 for an unknown key
    try:
        runtime_config.set_setting(db, key, payload.value, by)
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _setting(db, key)


@router.delete("/settings/{key}", response_model=SettingOut, summary="Go back to the .env value")
def delete_setting(key: str, db: Session = Depends(get_db), by: str = Depends(claimed_by)) -> SettingOut:
    try:
        runtime_config.reset_setting(db, key, by)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _setting(db, key)


@router.get("/documents", response_model=list[DocumentOut], summary="List reference documents: rules, PII terms, apps, prompts")
def list_documents() -> list[DocumentOut]:
    return [get_document(name) for name in runtime_config.DOCUMENT_FILES]


@router.get("/documents/{name}", response_model=DocumentOut, summary="Get one reference document")
def get_document(name: str) -> DocumentOut:
    try:
        document, overridden = runtime_config.get_document(name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentOut(name=name, overridden=overridden, document=document)


@router.put("/documents/{name}", response_model=DocumentOut, summary="Replace a reference document now")
def put_document(name: str, payload: DocumentIn, db: Session = Depends(get_db), by: str = Depends(claimed_by)) -> DocumentOut:
    try:
        runtime_config.set_document(db, name, payload.document, by)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return get_document(name)


@router.delete("/documents/{name}", response_model=DocumentOut, summary="Go back to the file in data/registry")
def delete_document(name: str, db: Session = Depends(get_db), by: str = Depends(claimed_by)) -> DocumentOut:
    try:
        runtime_config.reset_document(db, name, by)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return get_document(name)


@router.get("/changes", response_model=list[ChangeOut], summary="Change history, newest first")
def list_changes(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)) -> list[ChangeOut]:
    return runtime_config.list_changes(db, limit)
