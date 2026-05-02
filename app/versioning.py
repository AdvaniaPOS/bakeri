"""
Hjelpere for API-versjonering og deprecation.

Bruk ``deprecation_headers(...)`` for å markere et endepunkt eller respons som
deprekert i tråd med ARCHITECTURE.md §0.

Eksempel::

    from fastapi import Response
    from app.versioning import deprecation_headers

    @router.get("/legacy/orders")
    async def legacy_orders(response: Response):
        for k, v in deprecation_headers(
            sunset="2026-06-01",
            successor="https://docs.poshub.no/api/v2/orders",
        ).items():
            response.headers[k] = v
        return ...
"""
from __future__ import annotations

from datetime import datetime, timezone


def deprecation_headers(
    sunset: str | None = None,
    successor: str | None = None,
) -> dict[str, str]:
    """
    Bygg standard deprecation-headers.

    :param sunset: ISO-dato (YYYY-MM-DD) eller RFC1123-streng for når support fjernes.
    :param successor: full URL til etterfølgende versjon (legges i Link-headeren).
    """
    headers: dict[str, str] = {"Deprecation": "true"}
    if sunset:
        try:
            # Aksepter YYYY-MM-DD og konverter til RFC1123.
            dt = datetime.fromisoformat(sunset).replace(tzinfo=timezone.utc)
            headers["Sunset"] = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
        except ValueError:
            headers["Sunset"] = sunset
    if successor:
        headers["Link"] = f'<{successor}>; rel="successor-version"'
    return headers
