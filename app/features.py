"""
Sentral katalog over feature-flagg per tenant.

Hver feature har en standardverdi som brukes nar tenant.features_enabled
mangler verdien. Super-admin kan overstyre per tenant via
PUT /admin/tenants/{id}/features.

Bruk:
    from app.features import has_feature, FEATURE_DEFAULTS
    if not has_feature(tenant, "templates"):
        raise HTTPException(403, "Funksjon ikke tilgjengelig")
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

# (key, navn, beskrivelse, default)
FEATURE_CATALOG: list[dict[str, Any]] = [
    {"key": "templates",        "name": "Maler",                "description": "Faste bestillingsmaler og matrise.",                  "default": True},
    {"key": "routes",           "name": "Ruter",                "description": "Rutehandtering og kjoreliste.",                       "default": True},
    {"key": "production",       "name": "Produksjonsrapport",   "description": "Produksjon og svinn-/faktisk-logg.",                  "default": True},
    {"key": "driver_app",       "name": "Sjafor-side",          "description": "Mobil sjafor-flyt med ferdigmelding.",                "default": True},
    {"key": "susoft_sync",      "name": "Susoft-integrasjon",   "description": "Synk av kunder/produkter mot Susoft.",                "default": True},
    {"key": "customer_portal",  "name": "Kundeportal",          "description": "Selvbetjent bestilling for sluttkunder (kommer).",    "default": False},
    {"key": "advanced_reports", "name": "Avanserte rapporter",  "description": "Eksport til Excel og dypere analyse.",                "default": False},
    {"key": "audit_log",        "name": "Audit-log",            "description": "Detaljert hendelseslogg for compliance.",             "default": False},
    {"key": "two_factor",       "name": "To-faktor (2FA)",      "description": "TOTP for admin-brukere.",                             "default": False},
]

FEATURE_DEFAULTS: dict[str, bool] = {f["key"]: f["default"] for f in FEATURE_CATALOG}


def has_feature(tenant, key: str) -> bool:
    """
    Returner True hvis tenant har feature aktivert (eller standard er True
    og tenant ikke har overstyrt).
    """
    if tenant is None:
        return FEATURE_DEFAULTS.get(key, False)
    enabled = getattr(tenant, "features_enabled", None) or {}
    if key in enabled:
        return bool(enabled[key])
    return FEATURE_DEFAULTS.get(key, False)


def require_feature(tenant, key: str) -> None:
    """Reis 403 hvis feature ikke er aktivert for denne tenanten."""
    if not has_feature(tenant, key):
        label = next((f["name"] for f in FEATURE_CATALOG if f["key"] == key), key)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Funksjon '{label}' er ikke aktivert for denne kunden.",
        )


def merged_features(tenant) -> dict[str, bool]:
    """Effective features (defaults + tenant overrides) for frontend."""
    base = dict(FEATURE_DEFAULTS)
    overrides = (getattr(tenant, "features_enabled", None) or {}) if tenant else {}
    for k, v in overrides.items():
        if isinstance(k, str):
            base[k] = bool(v)
    return base


def feature_required(key: str):
    """
    FastAPI-dependency-fabrikk. Bruk pa router-niva:

        from app.features import feature_required
        router = APIRouter(
            prefix="/templates",
            dependencies=[Depends(feature_required("templates"))],
        )
    """
    from fastapi import Depends
    from .dependencies import get_current_tenant  # local import unngar sirkel

    def _dep(tenant=Depends(get_current_tenant)):
        require_feature(tenant, key)
        return True
    return _dep
